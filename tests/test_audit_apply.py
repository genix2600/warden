"""Applying a Tune-up recommendation, and the honesty rules around it.

The interesting assertions here are the refusals. An audit changes a machine
that currently works, so the bar is higher than for a repair, and most of this
file is about Warden declining to offer something.
"""

from __future__ import annotations

import inspect

from warden.audit.apply import apply, describe_change
from warden.audit.recommend import FIXES, recommend
from warden.contracts import (
    CheckResult,
    CheckStatus,
    MetricReading,
)
from warden.executor import Executor
from warden.playbooks import REGISTRY
from warden.store import ObservationStore

from .test_audit_settings import store_with


def measurement(value: object) -> MetricReading:
    return MetricReading(metric_id="storage.reclaimable_mb", value=value, unit="MB")


class TestChangeIsReportedHonestly:
    def test_no_movement_says_so_rather_than_claiming_a_win(self) -> None:
        """Several of these settings take days. An immediate zero is expected.

        Claiming an improvement at the moment of the click is easy to do and
        hard to catch, and it is exactly the unfalsifiable promise this whole
        subsystem argues against.
        """
        change = describe_change(measurement(1000), measurement(1000), "MB", True)
        assert change == "No measurable change yet."

    def test_an_improvement_is_named_with_its_direction(self) -> None:
        change = describe_change(measurement(1500), measurement(500), "MB", True)
        assert "1000 MB better" in change
        assert "1500 to 500" in change

    def test_going_the_wrong_way_is_reported_too(self) -> None:
        change = describe_change(measurement(500), measurement(1500), "MB", True)
        assert "worse" in change

    def test_higher_is_better_flips_the_wording(self) -> None:
        """A processor ceiling going up is an improvement; disk usage going up is not."""
        change = describe_change(measurement(50), measurement(100), "percent", False)
        assert "better" in change

    def test_an_unmeasurable_metric_admits_it(self) -> None:
        assert "cannot say" in describe_change(measurement(None), measurement(None), "MB", True)
        assert "No measurement" in describe_change(None, measurement(5), "MB", True)


class TestWhatIsNeverOffered:
    def test_deleting_temporary_files_has_no_action(self) -> None:
        """The obvious cleanup action, absent because a deletion cannot be undone.

        Warden reports the gigabyte it measured and recommends Storage Sense
        instead, which is revertible and stops the problem recurring. Being
        unable to offer the obvious action is the rule working, not a gap.
        """
        assert "storage.reclaimable" not in FIXES

    def test_a_healthy_check_cannot_carry_an_action(self) -> None:
        result = CheckResult(
            check_id="storage.storage_sense",
            domain_id="storage",
            title="Automatic cleanup",
            status=CheckStatus.OPTIMAL,
        )
        assert recommend(result, ObservationStore()) is None

    def test_a_finding_with_no_way_back_is_not_offered(self) -> None:
        """No prior value readable means no recommendation is built at all.

        Same shape as the executor refusing an action that needs rights it does
        not have: refuse before the person commits, never after.
        """
        result = CheckResult(
            check_id="storage.storage_sense",
            domain_id="storage",
            title="Automatic cleanup",
            status=CheckStatus.SUBOPTIMAL,
        )
        assert recommend(result, ObservationStore()) is None, "nothing read, so nothing to revert"

    def test_an_intent_dependent_finding_offers_choices_and_no_command(self) -> None:
        store = store_with(
            "audit.startup", {"run_keys": ["A"] * 13, "startup_folder": [], "count": 13}
        )
        result = CheckResult(
            check_id="performance.startup_load",
            domain_id="performance",
            title="Programs that start with Windows",
            status=CheckStatus.INTENT_DEPENDENT,
        )
        suggestion = recommend(result, store)
        assert suggestion is not None
        assert suggestion.proposal is None
        assert len(suggestion.choices) == 2


class TestTheGateIsShared:
    def test_audit_actions_use_the_same_executor_and_still_require_approval(self) -> None:
        """The spec's rule: no second execution path.

        Asserted the same way tests/test_approval_gate.py asserts it for fault
        fixes, by inspecting the signature, so a refactor cannot quietly add an
        easier route for actions that change a working machine.
        """
        signature = inspect.signature(Executor.execute)
        approved = signature.parameters["approved_at"]
        assert approved.kind is inspect.Parameter.KEYWORD_ONLY
        assert approved.default is inspect.Parameter.empty, "there must be no default approval"

    def test_every_audit_action_is_in_the_one_registry(self) -> None:
        known = {spec.id for spec in REGISTRY.specs()}
        for check_id, (action_id, _) in FIXES.items():
            assert action_id in known, f"{check_id} points at an unregistered action"

    def test_every_audit_action_is_reversible(self) -> None:
        """An irreversible action could never satisfy the contract, so none exist."""
        for _, (action_id, _) in FIXES.items():
            assert REGISTRY.get(action_id).reversible


class TestRevertUsesTheCapturedValue:
    def _recommendation(self, sense_on: bool):
        store = store_with(
            "audit.storage.reclaimable",
            {"reclaimable_mb": 2048, "storage_sense_on": sense_on},
        )
        result = CheckResult(
            check_id="storage.storage_sense",
            domain_id="storage",
            title="Automatic cleanup",
            status=CheckStatus.SUBOPTIMAL,
        )
        return recommend(result, store), store

    def test_the_prior_value_is_recorded_before_anything_runs(self) -> None:
        suggestion, _ = self._recommendation(sense_on=False)
        assert suggestion is not None
        assert suggestion.revert is not None
        assert suggestion.revert.prior == {"enabled": 0}, "the value as it was, not as it will be"
        assert "switched back off" in suggestion.revert.describe

    def test_reverting_without_a_record_refuses(self) -> None:
        suggestion, store = self._recommendation(sense_on=False)
        assert suggestion is not None
        stripped = suggestion.model_copy(update={"revert": None})
        outcome = apply(stripped, Executor(), store, revert=True)
        assert not outcome.ok
        assert "no recorded prior value" in outcome.detail

    def test_a_recommendation_without_an_action_cannot_be_applied(self) -> None:
        suggestion, store = self._recommendation(sense_on=False)
        assert suggestion is not None
        stripped = suggestion.model_copy(update={"proposal": None})
        outcome = apply(stripped, Executor(), store)
        assert not outcome.ok
        assert "does not carry an action" in outcome.detail
