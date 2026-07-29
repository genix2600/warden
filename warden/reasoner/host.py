"""The model runtime that ships inside the build.

Warden's whole argument is that it reads *your* machine and answers on *your*
machine. That argument collapses the moment someone downloads the build and the
header says "rules engine" because Ollama was never installed -- the product
looks like the scripted troubleshooter it was written to replace, and the person
evaluating it has no way to know the difference.

So the model runtime is shipped, not assumed. ``ollama.exe`` is a self-contained
Go binary: it does not need installing, does not register a service, and does not
need administrator. Started as a child process with ``OLLAMA_MODELS`` pointed at
the bundled weights and ``OLLAMA_HOST`` on a private loopback port, it gives the
existing :class:`~warden.reasoner.llm.OllamaClient` something to talk to with no
change to that client at all.

Three tiers, in order, each reported honestly on the Readiness page:

1. the runtime bundled with this build,
2. an Ollama the user already had, on the default port,
3. the deterministic rules engine.

The port is private and chosen at runtime rather than using 11434, so Warden
never collides with -- or quietly hijacks -- an Ollama the user is already
running for something else.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

from warden.paths import resource_path

log = logging.getLogger(__name__)

#: Where ``scripts/fetch-model.ps1`` stages the runtime, mirrored into the
#: bundle by ``warden.spec``.
RUNTIME_DIR = "runtime"

#: Serving weights off disk the first time is slow, and slower again from a
#: cold file cache on a machine that has just extracted a zip.
_START_TIMEOUT_S = 60.0

_CREATE_NO_WINDOW = 0x08000000


def bundled_binary() -> Path | None:
    """The ``ollama.exe`` shipped with this build, if there is one."""
    binary = resource_path(RUNTIME_DIR, "ollama.exe")
    return binary if binary.is_file() else None


def bundled_models() -> Path | None:
    path = resource_path(RUNTIME_DIR, "models")
    return path if path.is_dir() else None


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class ModelHost:
    """Runs the bundled model server for the lifetime of the application.

    Owns nothing else. If the runtime is not bundled, :meth:`start` returns
    ``None`` and every caller falls through to the next tier -- absence is a
    supported configuration, not an error, because a source checkout has no
    ``runtime/`` and should still run.
    """

    def __init__(self) -> None:
        self._process: subprocess.Popen[bytes] | None = None
        self.endpoint: str | None = None

    def start(self) -> str | None:
        """Launch the bundled server. Returns its endpoint, or None if absent."""
        binary, models = bundled_binary(), bundled_models()
        if binary is None or models is None:
            log.info("no model runtime in this build; looking for a system Ollama")
            return None

        port = _free_port()
        host = f"127.0.0.1:{port}"
        environment = {
            **os.environ,
            "OLLAMA_HOST": host,
            "OLLAMA_MODELS": str(models),
            # Warden asks one question at a time and waits for a human between
            # them. Parallelism would only add memory pressure on the small
            # machines this is built for.
            "OLLAMA_NUM_PARALLEL": "1",
            "OLLAMA_MAX_LOADED_MODELS": "1",
        }

        try:
            self._process = subprocess.Popen(
                [str(binary), "serve"],
                env=environment,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                # Without this the packaged, windowless build flashes a console.
                creationflags=_CREATE_NO_WINDOW,
            )
        except OSError as exc:
            log.warning("could not start the bundled model runtime: %s", exc)
            return None

        if not self._wait_until_ready(port):
            log.warning("the bundled model runtime did not become ready in time")
            self.stop()
            return None

        self.endpoint = f"http://{host}"
        log.info("model runtime listening on %s with weights from %s", self.endpoint, models)
        return self.endpoint

    def _wait_until_ready(self, port: int) -> bool:
        """Wait for the model list, not merely for the socket.

        Ollama binds its port before it has finished indexing the model store,
        so an accepted connection is not the same as a usable server. Warden
        asked the socket once and got an empty model list back, concluded there
        was no model, and fell through to the rules engine -- with the weights
        sitting right there. On a slower machine, or one reading these files off
        a freshly extracted zip, that window is wider, not narrower.
        """
        deadline = time.monotonic() + _START_TIMEOUT_S
        while time.monotonic() < deadline:
            if self._process is not None and self._process.poll() is not None:
                return False  # It exited; waiting out the timeout helps nobody.
            if self._models_visible(port):
                return True
            time.sleep(0.3)
        return False

    @staticmethod
    def _models_visible(port: int) -> bool:
        request = urllib.request.Request(f"http://127.0.0.1:{port}/api/tags")
        try:
            with urllib.request.urlopen(request, timeout=1.0) as response:
                payload = json.load(response)
        except (OSError, ValueError):
            return False
        return bool(payload.get("models"))

    def stop(self) -> None:
        """Terminate the child. Called on shutdown; safe to call twice."""
        process = self._process
        self._process = None
        self.endpoint = None
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
