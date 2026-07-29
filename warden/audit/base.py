"""The check protocol, and the rule every check has to satisfy.

A :class:`Check` is to the audit what a detector is to the agent loop: a pure
function of the observation store, with no I/O of its own. That purity is what
lets the whole registry be exercised from hand-built observations, on a machine
that has none of the hardware being checked.

The difference from a detector is what it asserts. A detector says *something
has failed*. A check says *this setting is not what it should be, and here is
the number that proves it*. Every check therefore declares a
:class:`~warden.contracts.audit.MetricSpec` up front, at class level, where the
coverage test can see it -- a check that cannot name what it measures fails the
build rather than shipping as an unfalsifiable opinion.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import JsonValue

from warden.contracts import CheckResult, CheckStatus, MetricReading, MetricSpec, Observation
from warden.store import ObservationStore


class Check(ABC):
    """One setting, examined."""

    id: str
    #: Which of the 13 user-facing domains this belongs to. The audit
    #: deliberately has no domain of its own: a stale driver is a Devices
    #: finding and a pending reboot is a Windows Update finding, because those
    #: are the areas the user already understands.
    domain_id: str
    #: Shown as the finding's heading. Plain English, no jargon.
    title: str
    #: Declared at class level so the coverage test can assert every check has
    #: one without instantiating anything.
    metric: MetricSpec

    @abstractmethod
    def run(self, store: ObservationStore) -> CheckResult:
        """Examine the store and report. Never raises; see :meth:`unreadable`."""

    # -- helpers, so individual checks stay short and read like prose --------

    def result(
        self,
        status: CheckStatus,
        *,
        detail: str,
        observed: JsonValue = None,
        expected: JsonValue = None,
        evidence: list[Observation | None] | None = None,
    ) -> CheckResult:
        return CheckResult(
            check_id=self.id,
            domain_id=self.domain_id,
            title=self.title,
            status=status,
            observed=observed,
            expected=expected,
            detail=detail,
            observation_ids=[o.id for o in (evidence or []) if o is not None],
        )

    def unreadable(self, why: str) -> CheckResult:
        """The reading failed.

        Distinct from a pass, and displayed as such. Warden does not report a
        setting as correct because it could not look at it -- the same rule the
        Health page follows when a collector dies.
        """
        return self.result(CheckStatus.COULD_NOT_READ, detail=why)

    def not_applicable(self, why: str) -> CheckResult:
        """The check does not apply to this hardware.

        A defrag schedule on a machine with no mechanical disk is not a pass and
        not a problem; it is a question that does not arise here.
        """
        return self.result(CheckStatus.NOT_APPLICABLE, detail=why)

    def reading(self, value: JsonValue, observations: list[Observation | None]) -> MetricReading:
        return MetricReading(
            metric_id=self.metric.metric_id,
            value=value,
            unit=self.metric.unit,
            observation_ids=[o.id for o in observations if o is not None],
        )
