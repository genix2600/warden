"""Session recording and replay.

Every run writes its event stream to a JSON Lines file. Because the recording is
the same ``AgentEvent`` sequence the live interface consumes, a replayed session
renders identically to a live one -- there is no second code path that could
drift, and no way for a recording to show something the live agent could not.

This exists for three reasons, in order of how often they matter:

1. **Tests.** ``tests/`` replay recorded incidents through the real detectors and
   assert the real symptoms, with no Windows and no hardware involved.
2. **After the fact.** A user, or we, can reopen exactly what the agent saw when
   it made a call it should not have.
3. **A labelled fallback.** If hardware misbehaves during a live demonstration,
   a recorded incident can be replayed rather than improvised over. The
   interface marks replayed sessions permanently and unmistakably -- the source
   field is carried on every event and the header states it -- because a
   recording presented as live would destroy the only thing this project is
   really selling.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import TextIO

from warden.contracts import AgentEvent, AgentEventAdapter, Source
from warden.winenv import describe_host

log = logging.getLogger(__name__)

SESSION_DIR = Path("sessions")
FIXTURE_DIR = Path("fixtures")


class SessionRecorder:
    """Appends events to a JSONL file. Flushes every line, deliberately.

    A crash is precisely when the recording matters most, so buffering it away
    would defeat the purpose. These are small files written a few times a second.
    """

    def __init__(self, directory: Path = SESSION_DIR, name: str | None = None) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        stamp = name or datetime.now().strftime("%Y%m%d-%H%M%S")
        self.path = directory / f"session-{stamp}.jsonl"
        self._handle: TextIO | None = self.path.open("w", encoding="utf-8")
        self._write_header()
        log.info("recording session to %s", self.path)

    def _write_header(self) -> None:
        # Not an AgentEvent: a metadata line the replay reader skips. Keeping the
        # host description with the recording is what makes an old session
        # interpretable later.
        self._raw({"__warden_session__": 1, "host": describe_host()})

    def _raw(self, payload: dict[str, object]) -> None:
        if self._handle is None:
            return
        self._handle.write(json.dumps(payload, default=str) + "\n")
        self._handle.flush()

    def __call__(self, event: AgentEvent) -> None:
        if self._handle is None:
            return
        self._handle.write(event.model_dump_json() + "\n")
        self._handle.flush()

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None


def read_session(path: Path) -> Iterator[AgentEvent]:
    """Parse a recorded session, marking every event as replayed.

    The source is rewritten on read rather than trusted from the file, so a
    hand-edited recording cannot claim to be live data.
    """
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                log.warning("%s line %d is not valid JSON; skipping", path.name, line_number)
                continue
            if "__warden_session__" in payload:
                continue
            try:
                event = AgentEventAdapter.validate_python(payload)
            except ValueError as exc:
                log.warning(
                    "%s line %d does not fit the event schema: %s",
                    path.name,
                    line_number,
                    exc,
                )
                continue
            yield event.model_copy(update={"source": Source.REPLAY})


def list_sessions(*directories: Path) -> list[Path]:
    found: list[Path] = []
    for directory in directories or (FIXTURE_DIR, SESSION_DIR):
        if directory.exists():
            found.extend(sorted(directory.glob("*.jsonl")))
    return found
