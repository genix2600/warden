"""What happens when the model is wrong in a way that sounds reasonable.

Every case here is a plausible-looking model response. None of them reach the
executor.
"""

from __future__ import annotations

import pytest

from warden.contracts import Symptom, Verdict
from warden.playbooks import REGISTRY
from warden.reasoner.guardrail import GuardrailRejection, validate
from warden.reasoner.llm import LlmDecision, LlmHypothesis
from warden.store import ObservationStore


def decision(**overrides) -> LlmDecision:
    base = dict(
        summary="The wireless link dropped and has not come back.",
        hypotheses=[
            LlmHypothesis(
                cause="The association was lost.",
                domain="configuration",
                likelihood=0.8,
                reasoning="The adapter is up but not associated.",
            )
        ],
        verdict="actionable",
        action_id="net.wifi.reconnect",
        params={"profile": "HomeNet", "interface": "Wi-Fi"},
    )
    return LlmDecision(**{**base, **overrides})


def run(d: LlmDecision, symptom: Symptom, store: ObservationStore, **kwargs):
    return validate(d, symptom, store, REGISTRY, model="test", latency_ms=1, **kwargs)


class TestTheCentralRefusal:
    def test_a_model_cannot_invent_a_software_fix_for_a_physical_problem(
        self, thermal_symptom: Symptom, store: ObservationStore
    ) -> None:
        """The failure this whole design exists to prevent.

        THERMAL.SUSTAINED_THROTTLE has an empty candidate list, so a model that
        confidently proposes a command for it is refused outright and the
        deterministic reasoner answers instead.
        """
        with pytest.raises(GuardrailRejection, match="deliberately contains no action"):
            run(decision(action_id="net.dns.flush"), thermal_symptom, store)

    def test_the_rules_path_routes_that_symptom_to_servicing(
        self, thermal_symptom: Symptom, store: ObservationStore
    ) -> None:
        from warden.reasoner.rules import RulesReasoner

        diagnosis = RulesReasoner().diagnose([thermal_symptom], store)
        assert diagnosis.verdict is Verdict.NEEDS_SERVICE
        assert diagnosis.proposal is None
        assert diagnosis.service_advice is not None
        assert diagnosis.service_advice.who == "technician"


class TestActionSelection:
    def test_an_action_outside_the_candidate_set_is_refused(
        self, wifi_symptom: Symptom, disconnected_store: ObservationStore
    ) -> None:
        """Being in the registry is not enough; it must fit *this* symptom."""
        with pytest.raises(GuardrailRejection, match="not among the actions available"):
            run(decision(action_id="sys.disk.temp_report"), wifi_symptom, disconnected_store)

    def test_an_invented_action_is_refused(
        self, wifi_symptom: Symptom, disconnected_store: ObservationStore
    ) -> None:
        with pytest.raises(GuardrailRejection):
            run(decision(action_id="net.wifi.fix_everything"), wifi_symptom, disconnected_store)

    def test_ungrounded_parameters_are_refused(
        self, wifi_symptom: Symptom, disconnected_store: ObservationStore
    ) -> None:
        with pytest.raises(GuardrailRejection, match="not in this machine's saved"):
            run(
                decision(params={"profile": "Evil_Twin_AP", "interface": "Wi-Fi"}),
                wifi_symptom,
                disconnected_store,
            )

    def test_an_already_failed_action_cannot_be_proposed_again(
        self, wifi_symptom: Symptom, disconnected_store: ObservationStore
    ) -> None:
        with pytest.raises(GuardrailRejection, match="already run on this incident"):
            run(
                decision(),
                wifi_symptom,
                disconnected_store,
                exclude=frozenset({"net.wifi.reconnect"}),
            )


class TestWellFormedness:
    def test_a_declined_action_must_come_with_advice(
        self, thermal_symptom: Symptom, store: ObservationStore
    ) -> None:
        with pytest.raises(GuardrailRejection, match="did not say what the user should do"):
            run(
                decision(
                    verdict="needs_service",
                    service_reason="",
                ),
                thermal_symptom,
                store,
            )

    def test_an_empty_summary_is_refused(
        self, wifi_symptom: Symptom, disconnected_store: ObservationStore
    ) -> None:
        with pytest.raises(GuardrailRejection, match="empty summary"):
            run(decision(summary="   "), wifi_symptom, disconnected_store)

    def test_citations_that_do_not_resolve_are_dropped_and_reported(
        self, wifi_symptom: Symptom, disconnected_store: ObservationStore
    ) -> None:
        """A model citing evidence that does not exist loses the citation, not
        the whole answer -- but the user is told it happened."""
        d = decision(
            hypotheses=[
                LlmHypothesis(
                    cause="The association was lost.",
                    domain="configuration",
                    likelihood=0.8,
                    reasoning="because",
                    supporting=["deadbeefcafe", "0000notreal0"],
                )
            ]
        )
        diagnosis = run(d, wifi_symptom, disconnected_store)
        assert diagnosis.ranked_hypotheses[0].supporting == []
        assert any("do not exist" in note for note in diagnosis.reasoner.guardrail_rejections)

    def test_likelihood_is_clamped(
        self, wifi_symptom: Symptom, disconnected_store: ObservationStore
    ) -> None:
        d = decision(
            hypotheses=[
                LlmHypothesis(
                    cause="Certainly this.", domain="configuration", likelihood=42.0, reasoning="x"
                )
            ]
        )
        assert run(d, wifi_symptom, disconnected_store).ranked_hypotheses[0].likelihood == 1.0


class TestTheHappyPath:
    def test_a_good_answer_produces_a_grounded_proposal(
        self, wifi_symptom: Symptom, disconnected_store: ObservationStore
    ) -> None:
        diagnosis = run(decision(), wifi_symptom, disconnected_store)
        assert diagnosis.verdict is Verdict.ACTIONABLE
        assert diagnosis.proposal is not None
        assert diagnosis.proposal.rendered_argv == [
            "netsh",
            "wlan",
            "connect",
            "name=HomeNet",
            "interface=Wi-Fi",
        ]
        assert diagnosis.reasoner.mode.value == "llm"

    def test_missing_parameters_fall_back_to_observed_facts(
        self, wifi_symptom: Symptom, disconnected_store: ObservationStore
    ) -> None:
        """A model that names the action but not its arguments still works: the
        playbook's binder derives them from the symptom's own evidence."""
        diagnosis = run(decision(params={}), wifi_symptom, disconnected_store)
        assert diagnosis.proposal is not None
        assert "name=HomeNet" in diagnosis.proposal.rendered_argv
