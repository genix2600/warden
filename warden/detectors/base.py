"""Detector protocol.

A detector reads the store and returns zero or more symptoms. It must be a pure
function of the store: no I/O, no clock beyond ``utcnow``, no model. That purity
is what makes ``tests/test_detectors.py`` able to replay a recorded incident and
assert the exact symptom set, and it is what makes the live demo behave the same
way twice.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import JsonValue

from warden.contracts import Observation, Severity, Symptom
from warden.store import ObservationStore


class Detector(ABC):
    id: str
    version: str = "1"
    #: Symptom codes this detector is capable of raising. Declared so the
    #: playbook registry can be checked for coverage at import time -- a symptom
    #: nobody can act on is a gap worth failing a test over.
    raises: tuple[str, ...] = ()

    @abstractmethod
    def evaluate(self, store: ObservationStore) -> list[Symptom]:
        """Return the symptoms currently present. Called every tick."""

    def symptom(
        self,
        code: str,
        *,
        severity: Severity,
        title: str,
        detail: str,
        facts: dict[str, JsonValue],
        evidence: list[Observation | None],
    ) -> Symptom:
        return Symptom(
            code=code,
            severity=severity,
            title=title,
            detail=detail,
            facts=facts,
            evidence=[o.id for o in evidence if o is not None],
            detector=self.id,
            detector_version=self.version,
        )


def mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None
