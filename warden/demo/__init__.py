"""Fault injection for demonstrations.

This module induces *real* faults. It does not write fake telemetry, and there
is deliberately no code path anywhere in Warden that can. ``wifi_drop`` really
disconnects the wireless adapter; ``cpu_load`` really saturates every core until
the chassis heats up. The collectors then observe genuine consequences, the
detectors fire on genuine readings, and the fix is verified against a genuinely
recovered machine.

That distinction is the entire reason this file exists rather than a fixture
generator. A demonstration driven by injected observations proves that the
interface renders, and nothing else. A demonstration driven by a real
disconnection proves the product works.

Nothing here runs on its own. Every scenario is triggered explicitly, from a
clearly-marked panel, by a person who wants it to happen.
"""

from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import threading
import time
from dataclasses import dataclass

log = logging.getLogger(__name__)

#: Large enough that hashlib releases the interpreter lock for the duration of
#: each digest, which is what lets plain threads saturate every core. A
#: multiprocessing pool would also work and would be considerably more fragile
#: to spawn from inside a running web server on Windows.
_BURN_BUFFER = os.urandom(4 * 1024 * 1024)


@dataclass
class _LoadState:
    threads: list[threading.Thread]
    stop: threading.Event
    until: float


class DemoHarness:
    """Induces real faults on request. Never invoked by the agent itself."""

    def __init__(self) -> None:
        self._load: _LoadState | None = None

    # -- scenario 1: wireless ---------------------------------------------

    def wifi_drop(self) -> tuple[bool, str]:
        """Disconnect the wireless adapter, for real.

        The saved profile is untouched, so this is recoverable by the very
        action Warden will propose -- which is the point. The demonstration and
        the fix are the same mechanism seen from two sides.
        """
        try:
            completed = subprocess.run(
                ["netsh", "wlan", "disconnect"],
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return False, f"could not run netsh: {exc}"
        if completed.returncode != 0:
            return False, completed.stderr.strip() or "netsh refused the disconnect"
        log.info("demo: wireless disconnected")
        return True, (
            "Wireless disconnected. Warden should notice within about four seconds "
            "and propose reconnecting to the profile it last saw in use."
        )

    # -- scenario 2: thermal ----------------------------------------------

    def cpu_load(self, seconds: float = 120.0, workers: int | None = None) -> tuple[bool, str]:
        """Saturate every core so the machine genuinely heats and throttles."""
        if self.load_active:
            return False, "a load run is already in progress"
        count = workers or (os.cpu_count() or 4)
        stop = threading.Event()
        until = time.monotonic() + seconds
        threads = [
            threading.Thread(target=_burn, args=(stop, until), daemon=True, name=f"demo-burn-{i}")
            for i in range(count)
        ]
        for thread in threads:
            thread.start()
        self._load = _LoadState(threads=threads, stop=stop, until=until)
        log.info("demo: %d burn threads for %.0fs", count, seconds)
        return True, (
            f"Loading all {count} cores for {seconds:.0f}s. Warden needs about "
            f"{45:.0f}s of sustained load before it will call anything sustained."
        )

    def stop_load(self) -> tuple[bool, str]:
        if self._load is None:
            return False, "no load run is in progress"
        self._load.stop.set()
        self._load = None
        return True, "Load stopped. Clocks should recover within a few seconds."

    @property
    def load_active(self) -> bool:
        if self._load is None:
            return False
        if time.monotonic() > self._load.until or self._load.stop.is_set():
            self._load = None
            return False
        return True

    @property
    def load_remaining_s(self) -> float:
        return max(self._load.until - time.monotonic(), 0.0) if self._load else 0.0

    def shutdown(self) -> None:
        if self._load is not None:
            self._load.stop.set()
            self._load = None


def _burn(stop: threading.Event, until: float) -> None:
    while not stop.is_set() and time.monotonic() < until:
        hashlib.sha256(_BURN_BUFFER).digest()
