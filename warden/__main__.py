"""Entry point.

``python -m warden`` opens the desktop window. ``--headless`` runs the server
alone, which is how the API is exercised from tests and from a browser during
development.
"""

from __future__ import annotations

import argparse
import logging
import socket
import sys
import threading
import time
from pathlib import Path

import uvicorn

from warden.api import create_app
from warden.orchestrator import Agent
from warden.paths import data_path
from warden.reasoner import OllamaClient, Reasoner
from warden.reasoner.host import ModelHost
from warden.reasoner.llm import DEFAULT_ENDPOINT, DEFAULT_MODEL
from warden.winenv import is_windows

log = logging.getLogger(__name__)

WINDOW_TITLE = "Warden"


def _redirect_output_to_a_log_file() -> Path | None:
    """Give a windowed build somewhere to write, and somewhere to crash.

    A PyInstaller executable built with ``console=False`` has no console, so
    ``sys.stdout`` and ``sys.stderr`` are ``None``. Any library that reaches for
    them dies on import of its own logging config -- uvicorn's colour formatter
    calls ``sys.stdout.isatty()`` and brings the whole application down before
    the window ever appears.

    Pointing them at a file fixes that, and fixes the larger problem it exposed:
    a GUI application that cannot print has no way to tell anyone why it failed.
    Now it can, and the path is in the README.
    """
    if sys.stdout is not None and sys.stderr is not None:
        return None
    path = data_path("logs", "warden.log")
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a", encoding="utf-8", buffering=1)
    sys.stdout = handle
    sys.stderr = handle
    return path


def _free_port() -> int:
    """Ask the OS for an unused loopback port rather than hoping 8000 is free."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


#: Uvicorn does not open its listening socket until application startup has
#: finished, and Warden's startup warms the PowerShell host -- loading the
#: NetAdapter and Storage modules and priming Get-PhysicalDisk, which alone
#: costs 4.4s cold. From a frozen bundle on a first run, with Defender
#: inspecting 45 MB of newly written files at the same time, that comfortably
#: exceeds 20s. Waiting too briefly turns a slow start into "it doesn't work".
_SERVER_START_TIMEOUT_S = 90.0


def _wait_for_server(port: int, timeout_s: float = _SERVER_START_TIMEOUT_S) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def _webview2_present() -> bool:
    """Whether the Edge WebView2 Runtime is registered on this machine.

    Read from the registry rather than by probing the filesystem: the runtime
    installs per-machine or per-user, at paths that have moved between
    versions, and the registration is the thing WebView2 itself looks for.
    """
    import winreg

    keys = (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\EdgeUpdate\Clients"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\EdgeUpdate\Clients"),
    )
    # The Evergreen Runtime's fixed client id, stable across versions.
    client = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    for root, path in keys:
        try:
            with winreg.OpenKey(root, f"{path}\\{client}") as handle:
                version, _ = winreg.QueryValueEx(handle, "pv")
                if version and version != "0.0.0.0":
                    return True
        except OSError:
            continue
    return False


def main(argv: list[str] | None = None) -> int:
    # Before anything that might log, and before uvicorn builds its logging
    # configuration: a windowed build has no streams for either to write to.
    log_file = _redirect_output_to_a_log_file()

    parser = argparse.ArgumentParser(prog="warden", description=__doc__)
    parser.add_argument("--headless", action="store_true", help="run the server without a window")
    parser.add_argument("--port", type=int, default=0, help="0 picks a free port")
    parser.add_argument("--no-llm", action="store_true", help="skip the local model entirely")
    parser.add_argument("--no-record", action="store_true", help="do not write a session file")
    parser.add_argument("--model", default=None, help="override the local model tag")
    parser.add_argument("--log-level", default="info")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)-7s %(name)-28s %(message)s",
        datefmt="%H:%M:%S",
    )
    if log_file is not None:
        log.info("no console available; this run is being logged to %s", log_file)

    if not is_windows():
        log.error("Warden reads Windows-specific interfaces and only runs on Windows.")
        return 2

    # Start the bundled model runtime before the agent, so the first incident
    # finds a model already listening rather than racing it. Absent runtime is
    # a supported configuration: the client then talks to whatever Ollama the
    # user has, and failing that the rules engine answers.
    model_host = ModelHost()
    endpoint = None if args.no_llm else model_host.start()

    client = OllamaClient(
        endpoint=endpoint or DEFAULT_ENDPOINT,
        model=args.model or DEFAULT_MODEL,
    )

    agent = Agent(reasoner=Reasoner(client=client, use_llm=not args.no_llm))
    app = create_app(agent, record=not args.no_record, model_host=model_host)
    port = args.port or _free_port()

    config = uvicorn.Config(
        app, host="127.0.0.1", port=port, log_level=args.log_level, access_log=False
    )
    server = uvicorn.Server(config)

    # The model runtime is a child process, so it outlives a crash unless it is
    # explicitly reaped. A stray ollama.exe holding a model in memory after
    # Warden has gone is exactly the kind of thing that gets a tool uninstalled.
    try:
        if args.headless:
            log.info("Warden listening on http://127.0.0.1:%d", port)
            server.run()
            return 0

        thread = threading.Thread(target=server.run, name="warden-server", daemon=True)
        thread.start()
        if not _wait_for_server(port):
            log.error("the local server did not start; try --headless to see why")
            return 1

        import webview  # imported late so --headless does not require a GUI stack

        # WebView2 is a system component, not something the bundle can carry.
        # It ships with Windows 11 and reaches most Windows 10 machines through
        # Edge, but "most" is not "all" -- and without it the window opens
        # blank, which looks like Warden is broken rather than like a missing
        # runtime. Say so instead.
        if not _webview2_present():
            log.error(
                "Microsoft Edge WebView2 Runtime is not installed, so the window "
                "cannot render. Install the Evergreen Runtime from "
                "https://developer.microsoft.com/microsoft-edge/webview2/ "
                "or run Warden with --headless and open the address above."
            )
            return 3

        webview.create_window(
            WINDOW_TITLE,
            f"http://127.0.0.1:{port}/",
            width=1440,
            height=920,
            min_size=(1080, 720),
            background_color="#0B0F14",
        )
        # Blocks until the window closes; uvicorn is a daemon thread and goes with it.
        webview.start()
        server.should_exit = True
        thread.join(timeout=5)
        return 0
    finally:
        model_host.stop()


if __name__ == "__main__":
    sys.exit(main())
