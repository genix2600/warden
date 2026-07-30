"""The audit: a standing review of settings that are wrong but not broken.

Sits at the same layer as ``detectors``: it reads the store, it decides nothing
about what to run, and it has no I/O of its own. What it produces is a
:class:`~warden.contracts.audit.AuditReport` — findings, each carrying the
number that justifies it.

Two properties are enforced here at import, in the same style as the playbook
registry's ``_check_coverage``, because both are the sort of rule that decays
quietly:

* every check names a metric with a cited source, and
* every check belongs to one of the 13 user-facing domains.

There is deliberately no fourteenth "Optimisation" domain. A stale driver is a
Devices finding and a pending restart is a Windows Update finding, because those
are the areas a person already understands — inventing a domain for the
audit would file its findings somewhere the user has no reason to look.

The audit runs on demand and on first launch, **never on a timer**. A tool that
re-scans hourly and grows a badge is the scareware pattern this feature exists
not to be, and the absence of that timer is the design decision worth defending.
"""

from __future__ import annotations

import logging

from warden.audit.base import Check
from warden.audit.checks import (
    DefragOnSsdCheck,
    RebootPendingCheck,
    WifiPowerSavingCheck,
)
from warden.audit.settings import (
    DriverAgeCheck,
    PowerPlanCheck,
    ProcessorCapCheck,
    ReclaimableSpaceCheck,
    StartupLoadCheck,
    StorageSenseCheck,
)
from warden.contracts import AuditReport, CheckResult, CheckStatus, utcnow
from warden.domains import BY_ID
from warden.store import ObservationStore

log = logging.getLogger(__name__)

__all__ = ["CHECKS", "Check", "CheckResult", "CheckStatus", "run_audit"]

#: Every check Warden performs. Ordered as the Tune-up page reads them, so the
#: registry doubles as the documentation of what the audit covers.
CHECKS: tuple[Check, ...] = (
    WifiPowerSavingCheck(),
    RebootPendingCheck(),
    ProcessorCapCheck(),
    DriverAgeCheck(),
    StorageSenseCheck(),
    ReclaimableSpaceCheck(),
    PowerPlanCheck(),
    StartupLoadCheck(),
    DefragOnSsdCheck(),
)


def _check_coverage() -> None:
    """Fail the build on a check that cannot be trusted or cannot be found.

    Run at import rather than in a test, for the same reason the playbook
    registry does it: a check that ships without a measurable metric is exactly
    the failure this subsystem was written to prevent, and finding out at import
    time means it cannot reach a user.
    """
    seen: set[str] = set()
    for check in CHECKS:
        if check.id in seen:
            raise ValueError(f"duplicate check id {check.id!r}")
        seen.add(check.id)

        if check.domain_id not in BY_ID:
            raise ValueError(
                f"{check.id}: domain {check.domain_id!r} is not one of the user-facing "
                f"domains in warden.domains. Findings must belong to an area the user "
                f"already recognises; do not invent one for the audit."
            )
        if not check.metric.rationale_source.strip():
            raise ValueError(
                f"{check.id}: the metric cites no source for its threshold. A threshold "
                f"that cannot say where it came from is a guess."
            )


_check_coverage()


def run_audit(store: ObservationStore) -> AuditReport:
    """Run every check once against the current readings.

    A check that raises is reported as ``could_not_read`` rather than being
    allowed to abort the pass. One broken check must not cost the user the other
    thirty-three, and an audit that silently returns fewer findings than it has
    checks would be lying by omission.
    """
    report = AuditReport()
    for check in CHECKS:
        try:
            report.results.append(check.run(store))
        except Exception as exc:  # a check must never break the pass
            log.warning("check %s failed: %s", check.id, exc)
            report.results.append(check.unreadable(f"This check could not run: {exc}"))
    report.finished_at = utcnow()
    return report
