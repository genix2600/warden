"""What the machine told us, and exactly how we asked."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, JsonValue

from warden.contracts.common import Contract, Mechanism, new_id, utcnow


class ObservationKind(StrEnum):
    METRIC = "metric"  # a number that moves: cpu %, degrees C, signal strength
    STATE = "state"  # a discrete condition: connected / disconnected
    LOG_EVENT = "log_event"  # something the OS recorded happening
    INVENTORY = "inventory"  # what exists: saved profiles, devices, drivers


class Provenance(Contract):
    """The audit trail for a single reading.

    Every number Warden shows the user can be traced back to a command the user
    could run themselves and get the same answer. This is the entire difference
    between "the agent looked at your machine" and "the agent said something
    about your machine", and it is why this type is mandatory rather than
    optional.
    """

    probe: str = Field(description="The exact command or API call, verbatim, as run.")
    mechanism: Mechanism
    elapsed_ms: int = Field(ge=0)
    raw_ref: str | None = Field(
        default=None,
        description="Key into the session log holding the untruncated raw output.",
    )


class Observation(Contract):
    id: str = Field(default_factory=new_id)
    source: str = Field(
        description="Stable dotted id, e.g. 'net.wifi.state'. Detectors query by this."
    )
    kind: ObservationKind
    captured_at: datetime = Field(default_factory=utcnow)
    value: JsonValue
    unit: str | None = None
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description=(
            "The collector's own assessment of this reading's reliability. A CPU "
            "temperature inferred from clock throttling is real evidence but a "
            "weaker signal than a sensor read, and says so here."
        ),
    )
    provenance: Provenance

    def as_fact(self) -> JsonValue:
        """Compact form handed to the reasoner. Ids and timings are noise to it."""
        return self.value


class ProbeError(Contract):
    """A collector failing is itself information -- 'no sensor available' is a finding."""

    source: str
    probe: str
    message: str
    at: datetime = Field(default_factory=utcnow)


class ProbeResult(Contract):
    """What one collector run returns. Partial success is normal and expected."""

    observations: list[Observation] = Field(default_factory=list)
    errors: list[ProbeError] = Field(default_factory=list)

    def __add__(self, other: ProbeResult) -> ProbeResult:
        return ProbeResult(
            observations=[*self.observations, *other.observations],
            errors=[*self.errors, *other.errors],
        )
