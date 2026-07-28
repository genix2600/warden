"""Did it actually work?

The verifier re-reads the machine after an action and evaluates the predicate
the user was shown before they approved. This is the step that separates Warden
from a chatbot that says "try running this" and then asks how it went.

Two details it would be easy to get wrong:

* **Poll, don't sample once.** Re-associating with an access point takes a few
  seconds; a DHCP renewal takes longer. Checking once, immediately, would report
  failure for a fix that was still in progress. So each spec declares a settle
  period and a deadline, and the verifier polls between them.
* **Inconclusive is a real answer.** If the collector that would prove the fix
  cannot run, the honest report is that we could not tell -- not that the fix
  failed. Those get different words in the UI and a different incident outcome.
"""

from __future__ import annotations

import logging
import time

from pydantic import JsonValue

from warden.collectors import CollectorHost
from warden.contracts import (
    VerificationOutcome,
    VerificationResult,
    VerifySpec,
)
from warden.playbooks import PREDICATES
from warden.store import ObservationStore

log = logging.getLogger(__name__)


class Verifier:
    def __init__(self, collectors: CollectorHost, store: ObservationStore) -> None:
        self._collectors = collectors
        self._store = store

    def capture_before(self, spec: VerifySpec) -> list[str]:
        """Ids of the readings that will be compared against, recorded up front."""
        return [
            observation.id
            for source in self._sources_for(spec)
            if (observation := self._store.latest(source)) is not None
        ]

    def verify(
        self,
        spec: VerifySpec,
        params: dict[str, JsonValue],
        evidence_before: list[str] | None = None,
    ) -> VerificationResult:
        predicate = PREDICATES.get(spec.predicate.id)
        if predicate is None:
            return VerificationResult(
                outcome=VerificationOutcome.INCONCLUSIVE,
                predicate=spec.predicate,
                detail=f"no such check {spec.predicate.id!r} is registered",
                evidence_before=evidence_before or [],
            )

        args = {**spec.predicate.args, **params}
        if spec.settle_s:
            time.sleep(spec.settle_s)

        deadline = time.monotonic() + spec.timeout_s
        attempts = 0
        passed: bool | None = None
        detail = "the check never produced a result"

        while True:
            attempts += 1
            fresh = self._collectors.run_ids(spec.probes)
            self._store.ingest(fresh.observations)
            passed, detail = predicate(self._store, args)
            if passed is True:
                break
            if time.monotonic() >= deadline:
                break
            time.sleep(min(spec.poll_interval_s, max(deadline - time.monotonic(), 0.1)))

        outcome = (
            VerificationOutcome.PASSED
            if passed is True
            else VerificationOutcome.FAILED
            if passed is False
            else VerificationOutcome.INCONCLUSIVE
        )
        log.info("verification %s after %d attempt(s): %s", outcome.value, attempts, detail)
        return VerificationResult(
            outcome=outcome,
            predicate=spec.predicate,
            detail=detail,
            attempts=attempts,
            evidence_before=evidence_before or [],
            evidence_after=[
                observation.id
                for source in self._sources_for(spec)
                if (observation := self._store.latest(source)) is not None
            ],
        )

    def _sources_for(self, spec: VerifySpec) -> list[str]:
        """Observation sources produced by the collectors this spec re-runs."""
        wanted = set(spec.probes)
        return [
            source
            for source in self._store.sources()
            if any(source.startswith(prefix) for prefix in wanted)
        ]
