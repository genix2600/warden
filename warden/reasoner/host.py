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
from collections.abc import Callable
from pathlib import Path

from warden.paths import data_path, resource_path

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
    """Weights shipped inside the build, if this is the offline edition."""
    path = resource_path(RUNTIME_DIR, "models")
    return path if path.is_dir() else None


def model_store() -> Path:
    """Where the server should look for weights.

    Two editions ship. The offline one carries the weights inside the bundle, so
    it serves them from there -- read-only is fine, and nothing will ever be
    written back. The standard one is 46 MB instead of 967 MB and has no
    weights at all, so the store has to be somewhere the user can write, and
    somewhere that survives an upgrade replacing the application folder.

    A downloaded model therefore lands beside the recorded sessions, and
    reinstalling Warden does not mean fetching a gigabyte again.
    """
    bundled = bundled_models()
    return bundled if bundled is not None else data_path("models")


def has_weights() -> bool:
    """Whether any model is actually present, bundled or downloaded.

    A manifests directory with nothing under it is what an interrupted download
    leaves behind, so the check is for a file rather than for the folder.
    """
    manifests = model_store() / "manifests"
    return manifests.is_dir() and any(manifests.rglob("*"))


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
        self._binary: Path | None = None
        self._environment: dict[str, str] = {}
        self.endpoint: str | None = None

    def start(self) -> str | None:
        """Launch the bundled server. Returns its endpoint, or None if absent.

        Starts even with no weights present. The server is what makes the
        download possible in the first place, and a running server with an empty
        store is a perfectly coherent state -- the reasoner sees no model, says
        so, and the rules engine answers until one arrives.
        """
        binary = bundled_binary()
        if binary is None:
            log.info("no model runtime in this build; looking for a system Ollama")
            return None

        models = model_store()
        models.mkdir(parents=True, exist_ok=True)

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

        self._binary = binary
        self._environment = environment

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

        if not self._wait_until_ready(port, expect_models=has_weights()):
            log.warning("the bundled model runtime did not become ready in time")
            self.stop()
            return None

        self.endpoint = f"http://{host}"
        log.info("model runtime listening on %s with weights from %s", self.endpoint, models)
        return self.endpoint

    def _wait_until_ready(self, port: int, *, expect_models: bool) -> bool:
        """Wait for the server to answer, and for the store to be indexed.

        Ollama binds its port before it has finished indexing the model store,
        so an accepted connection is not the same as a usable server. Warden
        asked the socket once, got an empty model list back, concluded there was
        no model, and fell through to the rules engine -- with the weights
        sitting right there. On a slower machine, or one reading these files off
        a freshly extracted zip, that window is wider rather than narrower.

        ``expect_models`` is what keeps that fix from breaking the lean build.
        When weights are on disk, an empty list means "still indexing" and is
        worth waiting through. When there are none, an empty list is the correct
        and final answer, and waiting for it to change would stall startup for
        the full timeout before giving up on a server that was fine all along.
        """
        deadline = time.monotonic() + _START_TIMEOUT_S
        while time.monotonic() < deadline:
            if self._process is not None and self._process.poll() is not None:
                return False  # It exited; waiting out the timeout helps nobody.
            listed = self._list_models(port)
            if listed is not None and (listed or not expect_models):
                return True
            time.sleep(0.3)
        return False

    @staticmethod
    def _list_models(port: int) -> list[object] | None:
        """The server's model list, or None if it is not answering yet."""
        request = urllib.request.Request(f"http://127.0.0.1:{port}/api/tags")
        try:
            with urllib.request.urlopen(request, timeout=1.0) as response:
                payload = json.load(response)
        except (OSError, ValueError):
            return None
        models = payload.get("models")
        return list(models) if isinstance(models, list) else []

    def pull(self, model: str, on_progress: Callable[[str], None] | None = None) -> bool:
        """Download a model into the store. Blocking; call it off the event loop.

        Only reachable when the user asks for it. Warden does not fetch a
        gigabyte in the background on first launch: the application is useful
        without it -- the rules engine answers every scenario end to end -- and
        deciding to spend someone's bandwidth on their behalf is not Warden's
        call to make.
        """
        if self._binary is None:
            return False
        try:
            process = subprocess.Popen(
                [str(self._binary), "pull", model],
                env=self._environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                creationflags=_CREATE_NO_WINDOW,
            )
        except OSError as exc:
            log.warning("could not start the model download: %s", exc)
            return False

        if process.stdout is not None:
            for line in process.stdout:
                # Ollama redraws one progress line with carriage returns, so the
                # last segment is the current state rather than a new event.
                text = line.replace("\r", "\n").strip().splitlines()
                if text and on_progress is not None:
                    on_progress(text[-1])
        return process.wait() == 0

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
