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

import uvicorn

from warden.api import create_app
from warden.orchestrator import Agent
from warden.reasoner import OllamaClient, Reasoner
from warden.winenv import is_windows

log = logging.getLogger(__name__)

WINDOW_TITLE = "Warden"


def _free_port() -> int:
    """Ask the OS for an unused loopback port rather than hoping 8000 is free."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_server(port: int, timeout_s: float = 20.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def main(argv: list[str] | None = None) -> int:
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

    if not is_windows():
        log.error("Warden reads Windows-specific interfaces and only runs on Windows.")
        return 2

    client = OllamaClient(model=args.model) if args.model else OllamaClient()
    agent = Agent(reasoner=Reasoner(client=client, use_llm=not args.no_llm))
    app = create_app(agent, record=not args.no_record)
    port = args.port or _free_port()

    config = uvicorn.Config(
        app, host="127.0.0.1", port=port, log_level=args.log_level, access_log=False
    )
    server = uvicorn.Server(config)

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


if __name__ == "__main__":
    sys.exit(main())
