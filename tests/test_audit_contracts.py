"""The rules that keep the audit from becoming an optimiser.

Each test here corresponds to a way this feature could quietly rot into the
thing it was built against: a recommendation with no measurable effect, a
"nothing to do" finding that somehow carries a command, a change that cannot be
undone. They are asserted against the type system rather than against behaviour,
because a validator cannot be forgotten the way a code review can.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from warden.contracts import (
    CheckResult,
    CheckStatus,
    IntentChoice,
    MetricDirection,
    MetricReading,
    MetricSpec,
    PredicateRef,
    Recommendation,
    RevertRecord,
)
from warden.contracts.actions import ActionProposal
from warden.contracts.common import RiskTier


def metric(metric_id: str = "boot.time_ms") -> MetricSpec:
    return MetricSpec(
        metric_id=metric_id,
        label="How long the machine takes to reach the desktop",
        unit="milliseconds",
        direction=MetricDirection.LOWER_IS_BETTER,
        read_via=PredicateRef(
            id="boot.duration",
            describe="Read from the Diagnostics-Performance log, event 100.",
        ),
        rationale_source="measured on this machine across the last 10 boots",
    )


def reading(value: object = 42000) -> MetricReading:
    return MetricReading(metric_id="boot.time_ms", value=value, unit="milliseconds")


def result(status: CheckStatus) -> CheckResult:
    return CheckResult(
        check_id="boot.startup_impact",
        domain_id="performance",
        title="Several programs start with Windows",
        status=status,
    )


def proposal(*, reversible: bool = True) -> ActionProposal:
    return ActionProposal(
        action_id="sys.startup.disable",
        params={"entry": "Example"},
        rendered_argv=["powershell.exe", "-NoProfile", "-Command", "Disable-Thing"],
        rationale="Because the measured startup cost is high.",
        expected_effect="The program no longer launches with Windows.",
        risk=RiskTier.REVERSIBLE,
        reversible=reversible,
        requires_admin=False,
        est_duration_s=3.0,
        verify=_verify(),
    )


def _verify() -> object:
    from warden.contracts.actions import VerifySpec

    return VerifySpec(
        probes=["sys.startup"],
        predicate=PredicateRef(id="report.only", describe="Re-read the startup list."),
    )


class TestMeasurementIsMandatory:
    """No measurement, no check. This is the rule the whole feature rests on."""

    def test_a_recommendation_cannot_exist_without_a_metric(self) -> None:
        with pytest.raises(ValidationError):
            Recommendation(  # type: ignore[call-arg]
                result=result(CheckStatus.SUBOPTIMAL),
                current=reading(),
                expected_improvement="typically 200-800 ms",
            )

    def test_a_threshold_must_cite_where_it_came_from(self) -> None:
        """An uncited threshold is a guess wearing a measurement's clothes."""
        with pytest.raises(ValidationError):
            MetricSpec(
                metric_id="x",
                label="x",
                unit="ms",
                direction=MetricDirection.LOWER_IS_BETTER,
                read_via=PredicateRef(id="x", describe="x"),
                rationale_source="",
            )

    def test_expected_improvement_cannot_be_blank(self) -> None:
        with pytest.raises(ValidationError):
            Recommendation(
                result=result(CheckStatus.SUBOPTIMAL),
                metric=metric(),
                current=reading(),
                expected_improvement="",
            )


class TestNothingToDoMeansNoCommand:
    @pytest.mark.parametrize(
        "status",
        [CheckStatus.OPTIMAL, CheckStatus.NOT_APPLICABLE, CheckStatus.COULD_NOT_READ],
    )
    def test_a_settled_check_cannot_carry_a_proposal(self, status: CheckStatus) -> None:
        with pytest.raises(ValidationError, match="nothing to fix"):
            Recommendation(
                result=result(status),
                metric=metric(),
                current=reading(),
                expected_improvement="none",
                proposal=proposal(),
            )

    def test_could_not_read_is_not_a_pass(self) -> None:
        """Distinct from optimal, for the same reason `unknown` is on Health."""
        assert CheckStatus.COULD_NOT_READ is not CheckStatus.OPTIMAL
        assert CheckStatus.NOT_APPLICABLE is not CheckStatus.OPTIMAL


class TestIntentDependentFindingsDoNotRecommend:
    """Some settings have no correct value, and saying so is the differentiator."""

    def test_an_intent_dependent_finding_cannot_recommend_an_action(self) -> None:
        with pytest.raises(ValidationError, match="must not recommend"):
            Recommendation(
                result=result(CheckStatus.INTENT_DEPENDENT),
                metric=metric(),
                current=reading(),
                expected_improvement="depends on what you want",
                proposal=proposal(),
                choices=[
                    IntentChoice(id="speed", label="Prefer speed", cost="shorter battery life"),
                    IntentChoice(id="battery", label="Prefer battery", cost="slower under load"),
                ],
            )

    def test_it_must_offer_at_least_two_options(self) -> None:
        with pytest.raises(ValidationError, match="at least two choices"):
            Recommendation(
                result=result(CheckStatus.INTENT_DEPENDENT),
                metric=metric(),
                current=reading(),
                expected_improvement="depends",
                choices=[IntentChoice(id="a", label="A", cost="something")],
            )


class TestEverythingCanBeUndone:
    """An audit changes a machine that currently works. Higher bar than a repair."""

    def test_an_irreversible_action_needs_a_captured_prior_value(self) -> None:
        with pytest.raises(ValidationError, match="captured before execution"):
            Recommendation(
                result=result(CheckStatus.SUBOPTIMAL),
                metric=metric(),
                current=reading(),
                expected_improvement="typically 200-800 ms",
                proposal=proposal(reversible=False),
            )

    def test_an_irreversible_action_is_allowed_once_it_can_be_undone(self) -> None:
        recommendation = Recommendation(
            result=result(CheckStatus.SUBOPTIMAL),
            metric=metric(),
            current=reading(),
            expected_improvement="typically 200-800 ms",
            proposal=proposal(reversible=False),
            revert=RevertRecord(
                action_id="sys.startup.disable",
                prior={"entry": "Example", "enabled": True},
                describe="Example would be restored to launching with Windows.",
            ),
        )
        assert recommendation.revert is not None

    def test_a_revert_record_cannot_be_empty(self) -> None:
        """An empty prior state is not a way back; it only looks like one."""
        with pytest.raises(ValidationError):
            RevertRecord(action_id="x", prior={}, describe="nothing")
