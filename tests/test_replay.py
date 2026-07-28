"""Session recording round-trip.

The recording is only trustworthy if it is the same events the live interface
consumes, and only safe if a replayed session cannot pass itself off as live.
"""

from __future__ import annotations

from pathlib import Path

from warden.contracts import (
    AgentLogEvent,
    Source,
    SymptomRaisedEvent,
    TelemetryEvent,
)
from warden.orchestrator import SessionRecorder, read_session

from .conftest import make_observation


def test_events_survive_a_round_trip(tmp_path: Path, wifi_symptom) -> None:
    recorder = SessionRecorder(directory=tmp_path, name="test")
    written = [
        TelemetryEvent(seq=1, observations=[make_observation("sys.cpu.percent", 42.0)]),
        AgentLogEvent(seq=2, text="Detected: wireless is disconnected", level="warn"),
        SymptomRaisedEvent(seq=3, symptom=wifi_symptom),
    ]
    for event in written:
        recorder(event)
    recorder.close()

    read_back = list(read_session(recorder.path))
    assert [e.type for e in read_back] == ["telemetry", "agent.log", "symptom.raised"]
    assert [e.seq for e in read_back] == [1, 2, 3]

    telemetry = read_back[0]
    assert isinstance(telemetry, TelemetryEvent)
    assert telemetry.observations[0].value == 42.0
    assert telemetry.observations[0].provenance.probe == "test::sys.cpu.percent"


def test_a_replayed_session_is_always_marked_as_replayed(tmp_path: Path) -> None:
    """The source is rewritten on read rather than trusted from the file, so a
    hand-edited recording cannot claim to be live data."""
    recorder = SessionRecorder(directory=tmp_path, name="test")
    recorder(TelemetryEvent(seq=1, source=Source.LIVE, observations=[]))
    recorder.close()

    assert all(event.source is Source.REPLAY for event in read_session(recorder.path))


def test_a_corrupt_line_is_skipped_not_fatal(tmp_path: Path) -> None:
    recorder = SessionRecorder(directory=tmp_path, name="test")
    recorder(AgentLogEvent(seq=1, text="before"))
    recorder.close()
    with recorder.path.open("a", encoding="utf-8") as handle:
        handle.write("{not json at all\n")
        handle.write('{"type": "no.such.event", "seq": 9}\n')
        handle.write(AgentLogEvent(seq=2, text="after").model_dump_json() + "\n")

    events = list(read_session(recorder.path))
    assert [getattr(e, "text", None) for e in events] == ["before", "after"]


def test_the_header_records_the_machine(tmp_path: Path) -> None:
    """A session read six months later is only interpretable with the host it
    came from, so the recorder writes it first."""
    recorder = SessionRecorder(directory=tmp_path, name="test")
    recorder.close()
    first = recorder.path.read_text(encoding="utf-8").splitlines()[0]
    assert "__warden_session__" in first
    assert "os" in first
