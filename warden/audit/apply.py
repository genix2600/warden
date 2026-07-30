"""Applying a recommendation, and putting it back.

Both go through :class:`~warden.executor.runner.Executor` with an ``approved_at``
timestamp, the same four gates, and the same argv re-derivation as every fault
fix. There is no second execution path, which is the point: an action that
changes a working machine should not get an easier route than one that repairs a
broken one.

What this adds on top is the measurement. The metric is read before the command,
read again after, and the difference is reported whichever way it went. **"No
measurable change" is a first-class outcome** and is shown as prominently as an
improvement, because a tool that only reports its wins cannot be calibrated, and
an audit that always claims an improvement is indistinguishable from the
optimisers this one was built against.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from warden.contracts import ExecutionRecord, MetricReading, Recommendation, utcnow
from warden.executor import Executor
from warden.playbooks import REGISTRY, ActionRejected, render_argv
from warden.store import ObservationStore

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Applied:
    """What happened, and what it changed."""

    ok: bool
    detail: str
    record: ExecutionRecord | None = None
    before: MetricReading | None = None
    after: MetricReading | None = None
    #: Plain English, and honest when the answer is "nothing we can see".
    change: str = ""


def describe_change(
    before: MetricReading | None,
    after: MetricReading | None,
    unit: str,
    lower_is_better: bool,
) -> str:
    """Say what moved, in the direction a person cares about.

    Deliberately willing to say nothing happened. Several of these settings take
    days to show their effect, so an immediate zero is the expected answer rather
    than a failure, and claiming a win at the moment of the click would be a lie
    that is easy to tell and hard to catch.
    """
    if before is None or after is None:
        return "No measurement to compare against."

    start, end = _number(before.value), _number(after.value)
    if start is None or end is None:
        return "Warden could not measure this one either side, so it cannot say."

    delta = end - start
    if abs(delta) < 0.5:
        return "No measurable change yet."

    improved = delta < 0 if lower_is_better else delta > 0
    word = "better" if improved else "worse"
    return f"{abs(delta):.0f} {unit} {word} ({start:.0f} to {end:.0f})."


def apply(
    recommendation: Recommendation,
    executor: Executor,
    store: ObservationStore,
    *,
    revert: bool = False,
) -> Applied:
    """Run a recommendation's action, or the same action with its prior values.

    ``revert`` reuses the record captured when the recommendation was built,
    which was read before the original command ran. That ordering is the whole
    guarantee: capturing it afterwards would record the value Warden had just
    written.
    """
    proposal = recommendation.proposal
    if proposal is None:
        return Applied(ok=False, detail="This finding does not carry an action.")

    params: dict[str, object] = dict(proposal.params)
    if revert:
        if recommendation.revert is None:
            return Applied(ok=False, detail="There is no recorded prior value to go back to.")
        params = dict(recommendation.revert.prior)

    try:
        playbook = REGISTRY.get(proposal.action_id)
        argv = render_argv(playbook.argv_template, params)
    except ActionRejected as exc:
        return Applied(ok=False, detail=str(exc))

    # A fresh proposal rather than a mutated one, so the executor's argv
    # re-derivation compares against something built the same way it was.
    running = proposal.model_copy(update={"params": params, "rendered_argv": argv})

    before = _measure(recommendation, store)
    record = executor.execute(running, approved_at=utcnow())

    if record.blocked_reason:
        return Applied(ok=False, detail=record.blocked_reason, record=record)

    return Applied(
        ok=record.exit_code == 0,
        detail=(
            "Done. The change is measured below."
            if record.exit_code == 0
            else f"The command exited with code {record.exit_code}."
        ),
        record=record,
        before=before,
    )


def _measure(recommendation: Recommendation, store: ObservationStore) -> MetricReading:
    from warden.audit.recommend import _current_reading

    return _current_reading(recommendation.metric.metric_id, store)


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None
