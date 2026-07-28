"""An incident is one trip around the agent loop, from symptom to outcome."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from warden.contracts.actions import Decision, ExecutionRecord
from warden.contracts.common import Contract, new_id, utcnow
from warden.contracts.diagnosis import Diagnosis
from warden.contracts.symptoms import Symptom


class IncidentState(StrEnum):
    """The loop, spelled out. The UI renders this as a progress rail.

    observing -> diagnosing -> awaiting_approval -> executing -> verifying -> closed
    with three ways out that never reach the executor: needs_service, declined,
    and monitoring (evidence too thin to act, keep watching).
    """

    DIAGNOSING = "diagnosing"
    AWAITING_APPROVAL = "awaiting_approval"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"
    NEEDS_SERVICE = "needs_service"
    DECLINED = "declined"
    MONITORING = "monitoring"

    @property
    def is_terminal(self) -> bool:
        return self in {
            IncidentState.RESOLVED,
            IncidentState.UNRESOLVED,
            IncidentState.NEEDS_SERVICE,
            IncidentState.DECLINED,
        }


class Incident(Contract):
    id: str = Field(default_factory=new_id)
    opened_at: datetime = Field(default_factory=utcnow)
    closed_at: datetime | None = None
    state: IncidentState = IncidentState.DIAGNOSING
    title: str
    symptoms: list[Symptom] = Field(default_factory=list)
    diagnosis: Diagnosis | None = None
    decision: Decision | None = None
    decided_at: datetime | None = None
    execution: ExecutionRecord | None = None
    history: list[ExecutionRecord] = Field(
        default_factory=list,
        description="Every attempt made on this incident, in order, including failed ones.",
    )
    attempted_actions: list[str] = Field(
        default_factory=list,
        description=(
            "Action ids already tried and verified as not having worked. The reasoner is "
            "given this list so it escalates instead of proposing the same fix twice."
        ),
    )
    notes: list[str] = Field(default_factory=list)

    def close(self, state: IncidentState) -> None:
        self.state = state
        self.closed_at = utcnow()
