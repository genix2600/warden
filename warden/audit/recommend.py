"""Turning a finding into something the user can act on, or deciding not to.

A :class:`~warden.contracts.audit.CheckResult` says a setting is wrong. A
:class:`~warden.contracts.audit.Recommendation` says what to do about it, what
number will move, and how to put it back. Most findings never become one, and
that is the normal case rather than a gap:

* a check that is ``optimal``, ``not_applicable`` or ``could_not_read`` has
  nothing to fix, and the contract refuses to attach a proposal to one;
* an ``intent_dependent`` finding has no correct answer, so it carries the
  choices and their costs instead of a command;
* and a fix that cannot be undone is not offered at all.

That last rule is why clearing temporary files is missing. It is the obvious
action, it would work, and a deletion cannot be reversed, so the prior value can
never be captured and the recommendation cannot be built. Warden reports the
gigabyte and recommends Storage Sense instead, which is revertible and stops the
problem recurring rather than fixing it once.

The revert record is read **before** the command runs, as part of building the
recommendation. Capturing it afterwards would record the value Warden just wrote.
"""

from __future__ import annotations

import logging

from warden.contracts import (
    ActionProposal,
    CheckResult,
    CheckStatus,
    IntentChoice,
    MetricReading,
    Recommendation,
    RevertRecord,
)
from warden.playbooks import REGISTRY, ActionRejected, render_argv
from warden.store import ObservationStore, as_dict, as_float

log = logging.getLogger(__name__)

#: check id -> the action that fixes it, and the parameters to fix it with.
#:
#: Deliberately explicit rather than inferred. A table a reviewer can read in
#: one glance is worth more here than a clever mapping, because the question
#: "what can the audit actually change on my machine" should have a short
#: answer.
FIXES: dict[str, tuple[str, dict[str, int]]] = {
    "storage.storage_sense": ("tuneup.storage_sense", {"enabled": 1}),
    "performance.processor_cap": ("tuneup.processor_ceiling", {"percent": 100}),
}


def recommend(result: CheckResult, store: ObservationStore) -> Recommendation | None:
    """Build the recommendation for a finding, or None when there is nothing to offer."""
    from warden.audit import BY_CHECK

    check = BY_CHECK.get(result.check_id)
    if check is None:
        return None

    current = _current_reading(check.metric.metric_id, store)

    if result.status is CheckStatus.INTENT_DEPENDENT:
        choices = _choices_for(result.check_id)
        if len(choices) < 2:
            return None
        return Recommendation(
            result=result,
            metric=check.metric,
            current=current,
            expected_improvement="Depends which you choose; both costs are shown above.",
            choices=choices,
        )

    if result.status is not CheckStatus.SUBOPTIMAL:
        return None

    fix = FIXES.get(result.check_id)
    if fix is None:
        # A real finding with no action behind it. The check explains what to do
        # instead, which for a stale driver means going to the vendor.
        return None

    action_id, params = fix
    proposal = _propose(action_id, params)
    if proposal is None:
        return None

    revert = _capture_revert(result.check_id, action_id, store)
    if revert is None:
        log.info("no way back for %s; not offering it", result.check_id)
        return None

    return Recommendation(
        result=result,
        metric=check.metric,
        current=current,
        expected_improvement=_expected(result.check_id),
        proposal=proposal,
        revert=revert,
    )


def _propose(action_id: str, params: dict[str, int]) -> ActionProposal | None:
    try:
        playbook = REGISTRY.get(action_id)
        argv = render_argv(playbook.argv_template, dict(params))
    except ActionRejected as exc:
        log.warning("could not build a proposal for %s: %s", action_id, exc)
        return None

    return ActionProposal(
        action_id=playbook.id,
        params=dict(params),
        rendered_argv=argv,
        rationale=playbook.when_to_use,
        expected_effect=playbook.expected_effect,
        risk=playbook.risk,
        reversible=playbook.reversible,
        requires_admin=playbook.requires_admin,
        est_duration_s=playbook.est_duration_s,
        verify=playbook.verify,
    )


def _capture_revert(check_id: str, action_id: str, store: ObservationStore) -> RevertRecord | None:
    """Read the value this action is about to overwrite.

    Returns None when the prior value cannot be read, which means the
    recommendation is never built and the user is never offered a change they
    could not undo. Same shape as the executor refusing an action that needs
    rights it does not have: refuse before the person commits, not after.
    """
    if check_id == "storage.storage_sense":
        observation = store.latest("audit.storage.reclaimable")
        if observation is None:
            return None
        was_on = bool(as_dict(observation.value).get("storage_sense_on"))
        return RevertRecord(
            action_id=action_id,
            prior={"enabled": 1 if was_on else 0},
            describe=(
                "Storage Sense would be switched back "
                + ("on" if was_on else "off")
                + ", exactly as it is now."
            ),
        )

    if check_id == "performance.processor_cap":
        observation = store.latest("audit.power.profile")
        if observation is None:
            return None
        ceiling = as_float(as_dict(observation.value).get("ac_max_pct"))
        if ceiling is None:
            return None
        return RevertRecord(
            action_id=action_id,
            prior={"percent": int(ceiling)},
            describe=f"The processor ceiling would go back to {ceiling:.0f}% on mains power.",
        )

    return None


def _current_reading(metric_id: str, store: ObservationStore) -> MetricReading:
    """The metric as it stands, so the delta afterwards has something to subtract."""
    sources = {
        "storage.reclaimable_mb": ("audit.storage.reclaimable", "reclaimable_mb"),
        "performance.ac_max_pct": ("audit.power.profile", "ac_max_pct"),
        "performance.dc_max_pct": ("audit.power.profile", "dc_max_pct"),
        "performance.startup_count": ("audit.startup", "count"),
    }
    source, key = sources.get(metric_id, ("", ""))
    observation = store.latest(source) if source else None
    value = as_float(as_dict(observation.value).get(key)) if observation else None
    return MetricReading(
        metric_id=metric_id,
        value=value,
        unit="",
        observation_ids=[observation.id] if observation else [],
    )


def _expected(check_id: str) -> str:
    """An honest bound, written to be checkable after the fact."""
    return {
        "storage.storage_sense": (
            "Typically a gigabyte or two returned over the following week, and the "
            "space stops accumulating after that. Nothing is deleted today."
        ),
        "performance.processor_cap": (
            "The processor ceiling goes from its current cap to 100%. How much "
            "faster the machine feels depends entirely on what you run."
        ),
    }.get(check_id, "Measured before and after, and reported either way.")


def _choices_for(check_id: str) -> list[IntentChoice]:
    """Both sides of a question that has no correct answer."""
    if check_id == "performance.power_plan":
        return [
            IntentChoice(
                id="speed",
                label="Let the processor run at full speed on battery",
                cost="Noticeably shorter battery life away from a socket.",
            ),
            IntentChoice(
                id="battery",
                label="Keep the current limit",
                cost="The machine stays slower on battery than it needs to be.",
            ),
        ]
    if check_id == "performance.startup_load":
        return [
            IntentChoice(
                id="keep",
                label="Leave them alone",
                cost="Sign-in stays as slow as it is now.",
            ),
            IntentChoice(
                id="review",
                label="Review the list yourself in Task Manager",
                cost="A few minutes, and Warden cannot tell you which ones matter to you.",
            ),
        ]
    return []
