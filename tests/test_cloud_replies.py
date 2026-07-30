"""What a hosted model actually returns, and why none of it was survivable.

Every case here is a real reply from `llama-3.3-70b-versatile`, captured on the
first live calls. They matter because of a difference that is easy to miss when
writing the client: Ollama is handed the JSON schema as a *decoding grammar*, so
a local reply physically cannot contain an invalid enum or an over-long list.
Groq's `json_object` mode guarantees only that the output parses as JSON.

So every constraint the local path gets for free has to be re-established here by
coercion, and the cost of getting it wrong is not a crash. It is a silent
fallback to the rules engine: the user paid for a cloud call, waited for it, and
got the offline answer with no idea why.
"""

from __future__ import annotations

import pytest

from warden.contracts import Verdict
from warden.playbooks import REGISTRY
from warden.reasoner import build_composed_diagnosis
from warden.reasoner.cloud import CloudDecision
from warden.reasoner.prompt import build_user_prompt
from warden.store import ObservationStore

from .conftest import make_observation  # noqa: F401  (fixtures)


def decision(**overrides: object) -> CloudDecision:
    payload: dict[str, object] = {
        "summary": "something is wrong",
        "hypotheses": [
            {
                "cause": "a service stopped",
                "domain": "software",
                "likelihood": 0.7,
                "reasoning": "it stopped",
            }
        ],
        "verdict": "actionable",
        "action_id": "",
        "params": {},
    }
    payload.update(overrides)
    return CloudDecision.model_validate(payload)


class TestEnumsArrivingAsProse:
    """All four measured in a single real reply."""

    def test_a_product_name_where_a_domain_belongs(self) -> None:
        d = decision(
            hypotheses=[
                {
                    "cause": "index corrupt",
                    "domain": "Windows Search",
                    "likelihood": 0.6,
                    "reasoning": "r",
                }
            ]
        )
        assert d.hypotheses[0].domain == "software"

    @pytest.mark.parametrize(
        ("given", "expected"),
        [
            ("Windows Search", "software"),
            ("Audio Driver", "driver"),
            ("failing disk", "hardware"),
            ("thermal", "hardware"),
            ("registry setting", "configuration"),
            ("the router", "environment"),
            ("software", "software"),
        ],
    )
    def test_domains_map_onto_the_five(self, given: str, expected: str) -> None:
        d = decision(
            hypotheses=[
                {"cause": "c", "domain": given, "likelihood": 0.5, "reasoning": "r"}
            ]
        )
        assert d.hypotheses[0].domain == expected

    @pytest.mark.parametrize(
        ("given", "expected"),
        [("Unknown", 0.5), ("High", 0.8), ("Low", 0.2), ("85%", 0.85), (85, 0.85), (0.42, 0.42)],
    )
    def test_likelihood_accepts_words_percentages_and_numbers(
        self, given: object, expected: float
    ) -> None:
        d = decision(
            hypotheses=[
                {"cause": "c", "domain": "software", "likelihood": given, "reasoning": "r"}
            ]
        )
        assert d.hypotheses[0].likelihood == pytest.approx(expected)

    def test_an_organisation_name_where_who_belongs(self) -> None:
        """Measured: 'Microsoft Support or a Windows expert'. The field asks who
        physically acts, not who to phone."""
        assert decision(service_who="Microsoft Support or a Windows expert").service_who == (
            "technician"
        )

    def test_urgency_words_map_on(self) -> None:
        assert decision(urgency="Medium").urgency == "soon"
        assert decision(urgency="Critical").urgency == "urgent"
        assert decision(urgency="anything else").urgency == "routine"

    def test_an_unrecognised_risk_reads_as_the_worst_one(self) -> None:
        """The opposite default to everywhere else, because this value decides
        whether a restore point is taken before the command runs."""
        d = decision(
            command={
                "argv": ["ipconfig", "/flushdns"],
                "explain": "e",
                "changes": "c",
                "reversible": True,
                "check": "k",
                "requires_admin": False,
                "risk": "something nobody has heard of",
            }
        )
        assert d.command is not None
        assert d.command.risk == "disruptive"


class TestOverLongLists:
    def test_a_third_hypothesis_is_dropped_rather_than_fatal(self) -> None:
        """Measured. The reply was asked for at most two and returned three, and
        rejecting it threw away a correct answer about a sound driver."""
        d = decision(
            hypotheses=[
                {"cause": f"c{i}", "domain": "driver", "likelihood": 0.3, "reasoning": "r"}
                for i in range(3)
            ]
        )
        assert len(d.hypotheses) == 2

    def test_excess_citations_are_dropped(self) -> None:
        d = decision(
            hypotheses=[
                {
                    "cause": "c",
                    "domain": "software",
                    "likelihood": 0.5,
                    "reasoning": "r",
                    "supporting": [str(i) for i in range(9)],
                }
            ]
        )
        assert len(d.hypotheses[0].supporting) == 4


class TestNeedsServiceIsNotAnEscapeHatch:
    """Asked about a broken search index, a muted audio device and an offline
    printer, the model answered 'contact a technician' to all three.

    `needs_service` claims no command could ever help, which is a claim about
    physics. A model reaching for it out of uncertainty produces the exact
    useless non-answer this product exists to replace, so it is checked against
    the model's own stated causes rather than trusted.
    """

    def test_a_software_cause_cannot_send_you_to_a_repair_shop(self, wifi_symptom) -> None:
        d = build_composed_diagnosis(
            decision(
                verdict="needs_service",
                service_reason="needs further diagnosis",
                service_next_step="contact a technician",
                hypotheses=[
                    {
                        "cause": "search index corrupt",
                        "domain": "software",
                        "likelihood": 0.7,
                        "reasoning": "r",
                    }
                ],
            ),
            wifi_symptom,
            "test-model",
            10,
        )
        assert d.verdict is not Verdict.NEEDS_SERVICE
        assert any(
            "none of the causes it gave are physical" in r
            for r in d.reasoner.guardrail_rejections
        )

    def test_a_hardware_cause_still_routes_to_service(self, wifi_symptom) -> None:
        d = build_composed_diagnosis(
            decision(
                verdict="needs_service",
                service_reason="the heatsink is blocked",
                service_next_step="have the fan cleaned",
                hypotheses=[
                    {"cause": "dust", "domain": "hardware", "likelihood": 0.8, "reasoning": "r"}
                ],
            ),
            wifi_symptom,
            "test-model",
            10,
        )
        assert d.verdict is Verdict.NEEDS_SERVICE
        assert d.service_advice is not None
        assert d.service_advice.next_step == "have the fan cleaned"

    def test_service_without_a_reason_is_not_advice(self, wifi_symptom) -> None:
        d = build_composed_diagnosis(
            decision(
                verdict="needs_service",
                service_reason="",
                service_next_step="",
                hypotheses=[
                    {
                        "cause": "dead disk",
                        "domain": "hardware",
                        "likelihood": 0.9,
                        "reasoning": "r",
                    }
                ],
            ),
            wifi_symptom,
            "test-model",
            10,
        )
        assert d.verdict is Verdict.NEEDS_MORE_DATA
        assert d.service_advice is None


class TestActionableAcceptsAComposedCommand:
    def test_a_composed_command_satisfies_the_verdict(self, wifi_symptom) -> None:
        """`Diagnosis` required a `proposal` for ACTIONABLE, which no composed
        command has. Every single one raised a ValidationError, the diagnosis
        task swallowed it, and the incident landed with no diagnosis at
        all."""
        d = build_composed_diagnosis(
            decision(
                command={
                    "argv": ["net", "stop", "spooler"],
                    "explain": "stops the spooler",
                    "changes": "the print spooler stops",
                    "reversible": True,
                    "undo": "net start spooler",
                    "check": "try printing",
                    "requires_admin": True,
                    "risk": "disruptive",
                }
            ),
            wifi_symptom,
            "test-model",
            10,
        )
        assert d.verdict is Verdict.ACTIONABLE
        assert d.proposal is None
        assert d.composed is not None
        assert d.composed.argv == ["net", "stop", "spooler"]

    def test_a_refused_command_is_not_actionable(self, wifi_symptom) -> None:
        d = build_composed_diagnosis(
            decision(
                command={
                    "argv": ["vssadmin", "delete", "shadows"],
                    "explain": "e",
                    "changes": "c",
                    "reversible": False,
                    "check": "k",
                    "requires_admin": True,
                    "risk": "disruptive",
                }
            ),
            wifi_symptom,
            "test-model",
            10,
        )
        assert d.verdict is not Verdict.ACTIONABLE
        assert d.composed is not None
        assert d.composed.refused is not None


class TestEmptyActionListMeansTwoDifferentThings:
    def test_the_local_prompt_still_says_needs_service(self, wifi_symptom) -> None:
        """For a code deliberately mapped to no actions, that instruction is
        correct and must survive."""
        wifi_symptom.code = "NET.WIFI.RADIO_OFF"
        text = build_user_prompt(wifi_symptom, ObservationStore(), REGISTRY)
        assert '"needs_service"' in text

    def test_the_cloud_prompt_tells_it_to_write_one_instead(self, wifi_symptom) -> None:
        """For a code nobody wrote a playbook for -- every problem typed in
        words -- the old wording was a flat instruction to give up, and the
        model obeyed it over the system prompt."""
        wifi_symptom.code = "USER.DESCRIBED"
        text = build_user_prompt(
            wifi_symptom, ObservationStore(), REGISTRY, may_compose=True
        )
        assert "no reviewed action covers this" in text
        assert "Do NOT answer" in text

    def test_a_deliberate_refusal_is_not_overridden_by_may_compose(
        self, wifi_symptom
    ) -> None:
        """The seven unfixable symptoms keep their instruction even for a model
        that is allowed to write commands. A worn battery is still a worn
        battery."""
        wifi_symptom.code = "POWER.BATTERY_WORN"
        text = build_user_prompt(
            wifi_symptom, ObservationStore(), REGISTRY, may_compose=True
        )
        assert '"needs_service"' in text
        assert "no reviewed action covers this" not in text
