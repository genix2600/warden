"""The event stream. One append-only sequence, shared by the UI, the session
log and the replay engine.

There is exactly one way state leaves the agent: as an ``AgentEvent``. The
WebSocket sends these, the session recorder writes these, and replay reads these
back. Because the three paths share a type, a recorded incident renders in the
UI identically to a live one -- which is what makes the recording trustworthy as
a demo fallback and useful as a test fixture.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, TypeAdapter

from warden.contracts.actions import (
    ActionProposal,
    Decision,
    ExecutionRecord,
    VerificationResult,
)
from warden.contracts.common import Contract, Source, utcnow
from warden.contracts.diagnosis import Diagnosis
from warden.contracts.incidents import Incident, IncidentState
from warden.contracts.observations import Observation, ProbeError
from warden.contracts.symptoms import Symptom


class _Event(Contract):
    seq: int = Field(default=0, description="Monotonic. The UI detects gaps and resyncs.")
    ts: datetime = Field(default_factory=utcnow)
    source: Source = Source.LIVE


class TelemetryEvent(_Event):
    type: Literal["telemetry"] = "telemetry"
    observations: list[Observation]
    errors: list[ProbeError] = Field(default_factory=list)


class AgentLogEvent(_Event):
    """The agent narrating itself. Not decoration -- it is the audit trail in prose."""

    type: Literal["agent.log"] = "agent.log"
    level: Literal["info", "warn", "error"] = "info"
    text: str
    detail: str | None = None


class AgentStatusEvent(_Event):
    type: Literal["agent.status"] = "agent.status"
    monitoring: bool
    tick: int
    collectors_ok: list[str] = Field(default_factory=list)
    collectors_failed: list[str] = Field(default_factory=list)
    reasoner_available: bool = False
    reasoner_model: str | None = None


class SymptomRaisedEvent(_Event):
    type: Literal["symptom.raised"] = "symptom.raised"
    symptom: Symptom


class SymptomClearedEvent(_Event):
    type: Literal["symptom.cleared"] = "symptom.cleared"
    code: str


class IncidentOpenedEvent(_Event):
    type: Literal["incident.opened"] = "incident.opened"
    incident: Incident


class IncidentStateEvent(_Event):
    type: Literal["incident.state"] = "incident.state"
    incident_id: str
    state: IncidentState


class DiagnosisReadyEvent(_Event):
    type: Literal["diagnosis.ready"] = "diagnosis.ready"
    incident_id: str
    diagnosis: Diagnosis


class ProposalPendingEvent(_Event):
    type: Literal["proposal.pending"] = "proposal.pending"
    incident_id: str
    proposal: ActionProposal


class DecisionEvent(_Event):
    type: Literal["proposal.decided"] = "proposal.decided"
    incident_id: str
    proposal_id: str
    decision: Decision


class ExecutionStartedEvent(_Event):
    type: Literal["execution.started"] = "execution.started"
    incident_id: str
    argv: list[str]


class ExecutionOutputEvent(_Event):
    type: Literal["execution.output"] = "execution.output"
    incident_id: str
    stream: Literal["stdout", "stderr"]
    text: str


class ExecutionFinishedEvent(_Event):
    type: Literal["execution.finished"] = "execution.finished"
    incident_id: str
    record: ExecutionRecord


class VerificationEvent(_Event):
    type: Literal["verification.result"] = "verification.result"
    incident_id: str
    result: VerificationResult


class IncidentClosedEvent(_Event):
    type: Literal["incident.closed"] = "incident.closed"
    incident: Incident


AgentEvent = Annotated[
    TelemetryEvent
    | AgentLogEvent
    | AgentStatusEvent
    | SymptomRaisedEvent
    | SymptomClearedEvent
    | IncidentOpenedEvent
    | IncidentStateEvent
    | DiagnosisReadyEvent
    | ProposalPendingEvent
    | DecisionEvent
    | ExecutionStartedEvent
    | ExecutionOutputEvent
    | ExecutionFinishedEvent
    | VerificationEvent
    | IncidentClosedEvent,
    Field(discriminator="type"),
]

AgentEventAdapter: TypeAdapter[AgentEvent] = TypeAdapter(AgentEvent)
"""Parse an event of unknown type from JSON. Used by the replay reader."""
