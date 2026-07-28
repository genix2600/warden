"""Symptoms: deterministic findings, produced by code from real observations.

Nothing here involves a language model. A symptom is what a competent human
would tick off a checklist -- "the radio is on, a profile is saved, and we are
not associated". Keeping this layer deterministic is what makes the demo
repeatable and what keeps the model's job narrow: explain and choose, not
detect.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field, JsonValue

from warden.contracts.common import Contract, Severity, utcnow


class Symptom(Contract):
    code: str = Field(
        description="Stable dotted identifier, e.g. 'NET.WIFI.DISCONNECTED'. "
        "Playbooks and tests key off this; it is part of the public contract."
    )
    severity: Severity
    title: str = Field(description="One line, written for a non-technical user.")
    detail: str = Field(default="", description="What the detector actually saw.")
    observed_at: datetime = Field(default_factory=utcnow)
    evidence: list[str] = Field(
        default_factory=list, description="Observation ids backing this finding."
    )
    facts: dict[str, JsonValue] = Field(
        default_factory=dict,
        description=(
            "Normalised, named values the reasoner sees. Detectors are responsible "
            "for putting everything the model needs to decide in here -- the model "
            "does not get raw observation dumps."
        ),
    )
    detector: str
    detector_version: str = "1"

    @property
    def key(self) -> str:
        """Identity for raise/clear tracking across ticks."""
        return self.code
