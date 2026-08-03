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

    def test_a_described_problem_is_offered_the_whole_registry(self, wifi_symptom) -> None:
        """Measured, and the reason this changed. Asked about a wrong clock the
        model wrote `Set-Date -Date (Get-Date)` -- which sets the clock to the
        time it already is -- while `time.resync` sat in the registry unoffered,
        with a predicate that would have proved whether it worked.

        There is no shortlist for a problem typed in words. There is still a
        registry, and it often holds exactly the right fix."""
        wifi_symptom.code = "USER.DESCRIBED"
        text = build_user_prompt(
            wifi_symptom, ObservationStore(), REGISTRY, may_compose=True
        )
        assert "time.resync" in text
        assert "sys.service.restart" in text
        assert "Only write one when nothing here fits" in text

    def test_a_detected_symptom_keeps_its_shortlist(self, wifi_symptom) -> None:
        """Widening the described case must not widen the detected one, or a
        model could answer a full disk by restarting the wireless adapter."""
        text = build_user_prompt(wifi_symptom, ObservationStore(), REGISTRY)
        assert "time.resync" not in text
        assert "Only write one when nothing here fits" not in text

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


class TestCitationsArrivingAsProse:
    """`supporting` asks for observation ids and a model answers with a sentence.

    Measured: `supporting` came back as the bare string "No system errors are
    reported in the logs." An earlier validator passed any non-list through
    untouched, so it failed the list type check and cost the entire diagnosis --
    on the packaged build, with a real key, answering a real question.
    """

    def test_a_sentence_where_a_list_belongs_is_dropped(self) -> None:
        d = decision(
            hypotheses=[
                {
                    "cause": "c",
                    "domain": "software",
                    "likelihood": 0.5,
                    "reasoning": "r",
                    "supporting": "No system errors are reported in the logs.",
                }
            ]
        )
        assert d.hypotheses[0].supporting == []

    def test_both_citation_fields_are_covered(self) -> None:
        d = decision(
            hypotheses=[
                {
                    "cause": "c",
                    "domain": "software",
                    "likelihood": 0.5,
                    "reasoning": "r",
                    "supporting": "prose",
                    "contradicting": "more prose",
                }
            ]
        )
        assert d.hypotheses[0].supporting == []
        assert d.hypotheses[0].contradicting == []

    def test_non_string_items_inside_a_list_are_dropped(self) -> None:
        d = decision(
            hypotheses=[
                {
                    "cause": "c",
                    "domain": "software",
                    "likelihood": 0.5,
                    "reasoning": "r",
                    "supporting": ["abc123", 42, None, "def456"],
                }
            ]
        )
        assert d.hypotheses[0].supporting == ["abc123", "def456"]

    def test_a_proper_list_still_works(self) -> None:
        d = decision(
            hypotheses=[
                {
                    "cause": "c",
                    "domain": "software",
                    "likelihood": 0.5,
                    "reasoning": "r",
                    "supporting": ["abc123"],
                }
            ]
        )
        assert d.hypotheses[0].supporting == ["abc123"]


class FakeCloud:
    """A cloud client that answers from a script, and records what it was asked.

    The prompts matter as much as the replies here: the point of the retry is
    that the second call is told why the first was refused.
    """

    def __init__(self, *replies: CloudDecision) -> None:
        self._replies = list(replies)
        self.prompts: list[str] = []
        self.available = True

    async def refresh_models(self) -> None:  # pragma: no cover - never reached
        raise AssertionError("available is already True")

    async def decide(self, system: str, user: str) -> tuple[CloudDecision, str, int]:
        self.prompts.append(user)
        return self._replies.pop(0), "llama-3.3-70b-versatile", 100


def command(argv: list[str], **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "argv": argv,
        "explain": "restart the service",
        "changes": "the service restarts",
        "reversible": True,
        "undo": "start it again",
        "check": "see whether Bluetooth reconnects",
        "requires_admin": True,
        "risk": "reversible",
    }
    payload.update(overrides)
    return payload


class TestARefusalIsFeedbackNotAnEnding:
    """Measured live, and the reason this loop exists.

    Asked "bluetooth isn't working", the model wrote a command, the screen
    refused it, and the incident closed as unresolved with a crossed-out
    command on screen and no next step. The diagnosis had been fine; only the
    command's form was rejected. Ending there produces exactly the useless
    non-answer this product was built to replace, reached from the other side.
    """

    @pytest.mark.asyncio
    async def test_the_second_attempt_is_told_why_the_first_failed(
        self, wifi_symptom
    ) -> None:
        from warden.reasoner import Reasoner

        refused = decision(command=command(["powershell", "-ec", "SQBFAFgA"]))
        accepted = decision(
            command=command(["powershell", "-Command", "Restart-Service bthserv"])
        )
        cloud = FakeCloud(refused, accepted)

        reasoner = Reasoner(use_llm=False)
        reasoner.set_cloud(cloud)  # type: ignore[arg-type]
        result = await reasoner.diagnose([wifi_symptom], ObservationStore())

        assert len(cloud.prompts) == 2
        assert "REFUSED BEFORE THE USER SAW IT" in cloud.prompts[1]
        assert "base64" in cloud.prompts[1]
        assert "-ec" in cloud.prompts[1]

        assert result.composed is not None
        assert result.composed.refused is None
        assert result.verdict is Verdict.ACTIONABLE

    @pytest.mark.asyncio
    async def test_the_first_refusal_is_still_shown(self, wifi_symptom) -> None:
        """The user is told the model's first answer was thrown away. Silently
        retrying until something passes is how a guardrail becomes decorative."""
        from warden.reasoner import Reasoner

        cloud = FakeCloud(
            decision(command=command(["powershell", "-ec", "SQBFAFgA"])),
            decision(command=command(["powershell", "-Command", "Restart-Service bthserv"])),
        )
        reasoner = Reasoner(use_llm=False)
        reasoner.set_cloud(cloud)  # type: ignore[arg-type]
        result = await reasoner.diagnose([wifi_symptom], ObservationStore())

        assert any(
            "refused the model's first command" in r
            for r in result.reasoner.guardrail_rejections
        )

    @pytest.mark.asyncio
    async def test_it_retries_once_and_then_stops(self, wifi_symptom) -> None:
        """Not a loop. A second refusal is an answer: this cannot be written in a
        form Warden will run, and saying so beats spending someone's rate limit
        on a demonstration day."""
        from warden.reasoner import Reasoner

        cloud = FakeCloud(
            decision(command=command(["vssadmin", "delete", "shadows"])),
            decision(command=command(["diskpart", "/s", "x.txt"])),
        )
        reasoner = Reasoner(use_llm=False)
        reasoner.set_cloud(cloud)  # type: ignore[arg-type]
        result = await reasoner.diagnose([wifi_symptom], ObservationStore())

        assert len(cloud.prompts) == 2
        assert result.composed is not None
        assert result.composed.refused is not None
        assert result.verdict is Verdict.NEEDS_MORE_DATA

    @pytest.mark.asyncio
    async def test_a_reviewed_action_on_the_retry_still_wins(self, wifi_symptom) -> None:
        """Being told "that command was refused" is the prompt most likely to
        make a model look harder at the reviewed list. When it does, the answer
        has to go through the grounding guardrail, not the refusal list."""
        from warden.reasoner import Reasoner

        cloud = FakeCloud(
            decision(command=command(["powershell", "-ec", "SQBFAFgA"])),
            decision(action_id="net.wifi.scan", params={}),
        )
        reasoner = Reasoner(use_llm=False)
        reasoner.set_cloud(cloud)  # type: ignore[arg-type]
        result = await reasoner.diagnose([wifi_symptom], ObservationStore())

        assert result.composed is None
        assert result.proposal is not None
        assert result.proposal.action_id == "net.wifi.scan"


class TestNullsAndNonBooleans:
    """Two more ways a real reply failed the schema, both measured.

    Both are the same underlying asymmetry: Ollama gets the schema as a decoding
    grammar and physically cannot emit an invalid value, while Groq's
    `json_object` mode guarantees only that the output parses. Every constraint
    the local path gets for free has to be re-established here, and the cost of
    missing one is not a crash -- it is a silent fall back to the rules engine.
    """

    def test_explicit_nulls_are_treated_as_unanswered(self) -> None:
        """Measured on a reply about DNS: five nulls in one object, all of them
        for fields the model was right not to answer, and the whole reply was
        rejected."""
        d = CloudDecision.model_validate(
            {
                "summary": "dns is not resolving",
                "hypotheses": [
                    {"cause": "stale cache", "domain": "software",
                     "likelihood": 0.7, "reasoning": "r"}
                ],
                "verdict": "actionable",
                "action_id": "net.dns.flush",
                "params": None,
                "service_reason": None,
                "service_who": None,
                "service_next_step": None,
                "interim_mitigation": None,
            }
        )
        assert d.action_id == "net.dns.flush"
        assert d.params == {}
        assert d.service_reason == ""

    def test_a_null_command_still_means_no_command(self) -> None:
        d = decision(command=None)
        assert d.command is None

    @pytest.mark.parametrize(
        ("given", "expected"),
        [("true", True), ("Yes", True), ("false", False), ("N/A", False),
         ("unknown", False), (1, True), (0, False)],
    )
    def test_booleans_arriving_as_words(self, given: object, expected: bool) -> None:
        """Measured: `"reversible": "N/A"` on a reply about an undetected second
        monitor. Unreadable resolves to False, the cautious reading for both
        fields it guards."""
        d = decision(
            command={
                "argv": ["ipconfig", "/all"],
                "explain": "e", "changes": "c", "undo": "u", "check": "k",
                "reversible": given, "requires_admin": given, "risk": "reads_only",
            }
        )
        assert d.command is not None
        assert d.command.reversible is expected
        assert d.command.requires_admin is expected
