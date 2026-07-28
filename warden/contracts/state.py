"""The full-state snapshot the interface fetches once on connect.

The WebSocket carries changes; this carries where things currently stand. Having
both means a browser that reconnects does not have to replay an entire session
to know what is on screen.
"""

from __future__ import annotations

from pydantic import Field

from warden.contracts.common import Contract, Source
from warden.contracts.incidents import Incident
from warden.contracts.observations import Observation
from warden.contracts.symptoms import Symptom


class ReasonerHealth(Contract):
    enabled: bool
    available: bool
    model: str | None = None
    endpoint: str
    note: str = Field(
        default="",
        description="Why the model is unavailable, in words a user can act on.",
    )


class CollectorHealth(Contract):
    id: str
    description: str
    interval_s: float
    healthy: bool
    last_error: str | None = None


class DomainHealth(Contract):
    """One subsystem, as a person would recognise it.

    Derived on every request from live symptoms and collector health rather than
    stored, so it can never disagree with what the detectors actually found.
    """

    id: str
    label: str
    blurb: str
    icon: str
    state: str = Field(
        description="ok | note | attention | problem | unknown. Few states on purpose."
    )
    headline: str = Field(description="One line, in the user's language.")
    symptom_codes: list[str] = Field(default_factory=list)
    active_symptoms: list[Symptom] = Field(default_factory=list)
    collectors: list[str] = Field(default_factory=list)
    highlights: dict[str, Observation] = Field(
        default_factory=dict, description="Readings worth showing on this domain's card."
    )


class AgentSnapshot(Contract):
    monitoring: bool
    source: Source
    tick: int
    sequence: int = Field(description="Latest event sequence number, for gap detection.")
    started_at: str | None = None
    host: dict[str, str] = Field(default_factory=dict)
    elevated: bool = False
    telemetry: dict[str, Observation] = Field(
        default_factory=dict, description="Latest reading per source."
    )
    active_symptoms: list[Symptom] = Field(default_factory=list)
    incidents: list[Incident] = Field(default_factory=list)
    collectors: list[CollectorHealth] = Field(default_factory=list)
    reasoner: ReasonerHealth | None = None
    session_path: str | None = None
