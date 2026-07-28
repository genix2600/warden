"""A long-lived PowerShell host, so polling the OS costs milliseconds.

Warden reads the machine through CIM classes and the Net* cmdlets rather than by
scraping ``netsh`` text, because CIM property names are locale-independent and
``netsh`` output is not: a German Windows prints "Status" where an English one
prints "State", and a parser built on the latter silently reports nothing on the
former.

The cost of that choice is process startup -- roughly half a second per
``powershell.exe`` invocation, which at a two-second poll interval across five
collectors would eat the machine we are supposed to be diagnosing. So we start
one host, hold it open, and stream one-line commands into it, delimited by a
sentinel. Steady-state cost drops to a few milliseconds per probe.

Two deliberate constraints:

* **Commands are single-line.** ``powershell -Command -`` consumes stdin
  line-by-line; a multi-line block would leave the host waiting for a
  continuation and desynchronise every later read. Enforced by assertion, not
  documentation.
* **A timeout kills the host.** Once a sentinel is missed we can no longer tell
  which output belongs to which request, so we do not try to recover in place --
  we tear down and let the next call start a clean host.
"""

from __future__ import annotations

import contextlib
import json
import logging
import subprocess
import threading
import time
from collections import deque
from queue import Empty, Queue
from typing import Any

log = logging.getLogger(__name__)

_SENTINEL = "<<WARDEN-EOF:{}>>"
_PRELUDE = (
    "[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
    "$ProgressPreference='SilentlyContinue'; "
    "$ErrorActionPreference='Stop'; "
    "$WarningPreference='SilentlyContinue'"
)
_LAUNCH = [
    "powershell.exe",
    "-NoProfile",
    "-NonInteractive",
    "-ExecutionPolicy",
    "Bypass",
    "-Command",
    "-",
]


class PowerShellError(RuntimeError):
    """The script ran and PowerShell itself reported a failure."""


class PowerShellUnavailable(RuntimeError):
    """The host could not be started or died mid-request."""


class PowerShellBridge:
    """Thread-safe. One host process, serialised by a lock."""

    def __init__(self, default_timeout: float = 8.0) -> None:
        self._default_timeout = default_timeout
        self._lock = threading.Lock()
        self._proc: subprocess.Popen[str] | None = None
        self._stdout: Queue[str | None] = Queue()
        self._stderr: deque[str] = deque(maxlen=50)
        self._counter = 0
        self._closed = False

    # -- lifecycle ---------------------------------------------------------

    def _spawn(self) -> subprocess.Popen[str]:
        proc = subprocess.Popen(
            _LAUNCH,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self._stdout = Queue()
        self._stderr.clear()
        threading.Thread(target=self._pump, args=(proc.stdout, self._stdout), daemon=True).start()
        threading.Thread(target=self._pump_err, args=(proc.stderr,), daemon=True).start()
        assert proc.stdin is not None
        proc.stdin.write(_PRELUDE + "\n")
        proc.stdin.flush()
        return proc

    @staticmethod
    def _pump(stream: Any, out: Queue[str | None]) -> None:
        try:
            for line in stream:
                out.put(line.rstrip("\r\n"))
        finally:
            out.put(None)  # EOF marker: unblocks a waiting reader on host death

    def _pump_err(self, stream: Any) -> None:
        for line in stream:
            self._stderr.append(line.rstrip("\r\n"))

    def _ensure(self) -> subprocess.Popen[str]:
        if self._closed:
            raise PowerShellUnavailable("bridge is closed")
        if self._proc is None or self._proc.poll() is not None:
            log.info("starting PowerShell host")
            self._proc = self._spawn()
        return self._proc

    def _kill(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        with contextlib.suppress(OSError):
            proc.kill()

    def close(self) -> None:
        self._closed = True
        with self._lock:
            self._kill()

    # -- requests ----------------------------------------------------------

    def run(self, script: str, timeout: float | None = None) -> tuple[str, float]:
        """Execute one line of PowerShell. Returns (stdout, elapsed_ms).

        Raises ``PowerShellError`` if the script threw, ``PowerShellUnavailable``
        if the host died or overran its timeout.
        """
        if "\n" in script:
            raise ValueError("psbridge commands must be a single line; join with ';'")
        deadline_s = timeout if timeout is not None else self._default_timeout

        with self._lock:
            proc = self._ensure()
            self._counter += 1
            token = _SENTINEL.format(self._counter)
            # The catch arm emits a structured marker rather than writing to
            # stderr, so a failing probe still terminates with its sentinel and
            # keeps the stream in sync.
            wrapped = (
                f"try {{ {script} }} "
                "catch { Write-Output ('__WARDEN_ERR__' + $_.Exception.Message) }; "
                f"Write-Output '{token}'"
            )
            started = time.perf_counter()
            try:
                assert proc.stdin is not None
                proc.stdin.write(wrapped + "\n")
                proc.stdin.flush()
            except OSError as exc:
                self._kill()
                raise PowerShellUnavailable(f"host closed its input: {exc}") from exc

            lines: list[str] = []
            hard_deadline = started + deadline_s
            while True:
                remaining = hard_deadline - time.perf_counter()
                if remaining <= 0:
                    self._kill()
                    raise PowerShellUnavailable(f"probe exceeded {deadline_s}s: {script[:80]}")
                try:
                    line = self._stdout.get(timeout=remaining)
                except Empty:
                    continue
                if line is None:
                    self._kill()
                    stderr = " | ".join(self._stderr)
                    raise PowerShellUnavailable(f"host exited. stderr: {stderr[:300]}")
                if line == token:
                    break
                lines.append(line)

            elapsed_ms = (time.perf_counter() - started) * 1000.0

        body = "\n".join(lines).strip()
        if body.startswith("__WARDEN_ERR__"):
            raise PowerShellError(body.removeprefix("__WARDEN_ERR__").strip())
        return body, elapsed_ms

    def warmup(self, timeout: float = 60.0) -> float:
        """Pre-import the modules and CIM classes the collectors will need.

        Measured on the development machine, the first ``Get-NetAdapter`` in a
        fresh host takes ~6s while PowerShell autoloads the module, and the first
        performance-counter query ~4s. Every call after that is under 100ms. If
        that cost lands on the first monitoring tick it looks like the agent
        hung; paid once at startup behind a splash state, it is invisible.
        """
        started = time.perf_counter()
        for script in (
            "Import-Module NetAdapter,NetConnection,NetTCPIP,DnsClient "
            "-ErrorAction SilentlyContinue; ''",
            "Get-CimInstance Win32_Processor -Property Name | Out-Null; ''",
            "Get-CimInstance Win32_PerfFormattedData_Counters_ProcessorInformation "
            "-Filter \"Name='_Total'\" | Out-Null; ''",
            "Get-NetAdapter -Physical | Out-Null; ''",
        ):
            try:
                self.run(script, timeout=timeout)
            except (PowerShellError, PowerShellUnavailable) as exc:
                log.warning("warmup step failed (non-fatal): %s", exc)
        return (time.perf_counter() - started) * 1000.0

    def run_json(self, script: str, timeout: float | None = None) -> tuple[Any, float]:
        """Run a script whose output is JSON. Empty output becomes ``None``.

        ``ConvertTo-Json`` unwraps single-element collections into a bare object,
        which is a well-known trap: a probe that returns one adapter and a probe
        that returns three would otherwise need different handling downstream.
        Callers use :func:`as_rows` to normalise.
        """
        body, elapsed_ms = self.run(script, timeout)
        if not body:
            return None, elapsed_ms
        try:
            return json.loads(body), elapsed_ms
        except json.JSONDecodeError as exc:
            raise PowerShellError(f"expected JSON, got: {body[:200]!r}") from exc


def as_rows(value: Any) -> list[dict[str, Any]]:
    """Normalise ConvertTo-Json output to a list of records."""
    if value is None:
        return []
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    return []


def json_pipeline(expr: str, depth: int = 3) -> str:
    """Wrap a pipeline so it always emits a JSON array, never a bare object.

    Windows PowerShell 5.1 -- the one actually present on every Windows box --
    has no ``-AsArray``, and its ``ConvertTo-Json`` collapses a single-element
    collection into a bare object. A probe that finds one wireless adapter would
    then return a different shape than one that finds two. Branching on
    ``.Count`` and bracketing by hand is unlovely but it is the only form that
    behaves identically on 5.1 and 7.x, and we are not willing to require 7.x.
    """
    return (
        f"$w=@({expr}); "
        "if($w.Count -eq 0){'[]'}"
        f"elseif($w.Count -eq 1){{'['+($w[0]|ConvertTo-Json -Depth {depth} -Compress)+']'}}"
        f"else{{$w|ConvertTo-Json -Depth {depth} -Compress}}"
    )
