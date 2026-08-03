"""Reading the error the machine just printed.

Warden ran `Restart-Service bthserv` and Windows replied:

    Cannot stop service 'Bluetooth Support Service (bthserv)' because it has
    dependent services. It can only be stopped if the Force flag is set.

Then Warden closed the incident as unresolved. The machine had named the fault
and the fix in a single sentence, and that sentence went to a log nobody reads.

A diagnostician that does not read the error it just caused is not diagnosing.
So the output goes back to the model, and what comes back returns to the same
approval gate as the first attempt -- a second model-written command is no more
reviewed than the first one was.
"""

from __future__ import annotations

import pytest

from warden.collectors import CollectorHost
from warden.contracts import (
    ExecutionOutcome,
    ExecutionRecord,
    Severity,
    Symptom,
    utcnow,
)
from warden.detectors import DetectorBank
from warden.orchestrator import Agent
from warden.playbooks import REGISTRY
from warden.reasoner import Reasoner
from warden.reasoner.prompt import build_user_prompt
from warden.store import ObservationStore

BTHSERV_STDERR = """Restart-Service : Cannot stop service 'Bluetooth Support Service \
(bthserv)' because it has dependent services. It can only be stopped if the Force flag \
is set.
At line:1 char:1
+ Restart-Service bthserv
+ ~~~~~~~~~~~~~~~~~~~~~~~
    + CategoryInfo          : InvalidOperation: (System.ServiceProcess.ServiceController\
:ServiceController) [Restart-Service], ServiceCommandException
    + FullyQualifiedErrorId : ServiceHasDependentServices,Microsoft.PowerShell.Commands.\
RestartServiceCommand"""


class _NullBridge:
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def run(self, *_: object, **__: object) -> object:
        raise AssertionError("these tests never collect")


def described(text: str = "bluetooth isn't working, send help") -> Symptom:
    return Symptom(
        code="USER.DESCRIBED",
        severity=Severity.WARN,
        title=text,
        detail=text,
        facts={"described": text},
        detector="user",
        detector_version="1",
    )


def failure(
    argv: list[str], *, exit_code: int | None = 1, stderr: str = BTHSERV_STDERR
) -> ExecutionRecord:
    return ExecutionRecord(
        proposal_id="composed",
        action_id="cloud.composed",
        argv=argv,
        approved_at=utcnow(),
        exit_code=exit_code,
        stderr_tail=stderr,
        outcome=ExecutionOutcome.NOT_RESOLVED,
    )


class TestTheOutputReachesThePrompt:
    def test_the_command_and_its_error_are_both_quoted(self) -> None:
        prompt = build_user_prompt(
            described(),
            ObservationStore(),
            REGISTRY,
            may_compose=True,
            attempts=[failure(["powershell.exe", "-Command", "Restart-Service bthserv"])],
        )
        assert "ALREADY RUN ON THIS INCIDENT" in prompt
        assert "Restart-Service bthserv" in prompt
        assert "Force flag is set" in prompt
        assert "exit code 1" in prompt

    def test_it_is_told_not_to_repeat_itself_or_claim_success(self) -> None:
        """Both failure modes were measured on the composed path: proposing the
        identical command again, and reporting a fix after a command that
        errored."""
        prompt = build_user_prompt(
            described(),
            ObservationStore(),
            REGISTRY,
            may_compose=True,
            attempts=[failure(["powershell.exe", "-Command", "Restart-Service bthserv"])],
        )
        assert "Do not repeat a command above unchanged" in prompt
        assert "do not claim the problem is now fixed" in prompt

    def test_nothing_is_added_when_nothing_has_run(self) -> None:
        prompt = build_user_prompt(described(), ObservationStore(), REGISTRY, may_compose=True)
        assert "ALREADY RUN ON THIS INCIDENT" not in prompt

    def test_a_timeout_is_reported_as_a_timeout(self) -> None:
        """Exit code alone is misleading for a command that never finished."""
        record = failure(["sfc", "/scannow"], exit_code=None, stderr="")
        record.timed_out = True
        prompt = build_user_prompt(
            described(), ObservationStore(), REGISTRY, may_compose=True, attempts=[record]
        )
        assert "timed out" in prompt

    def test_every_attempt_is_shown_not_just_the_last(self) -> None:
        """The model needs to see that it has already tried -Force, or it will
        try it again."""
        prompt = build_user_prompt(
            described(),
            ObservationStore(),
            REGISTRY,
            may_compose=True,
            attempts=[
                failure(["powershell.exe", "-Command", "Restart-Service bthserv"]),
                failure(["powershell.exe", "-Command", "Restart-Service bthserv -Force"]),
            ],
        )
        assert "1. powershell.exe -Command Restart-Service bthserv" in prompt
        assert "2. powershell.exe -Command Restart-Service bthserv -Force" in prompt


class TestTheRetryIsBounded:
    @pytest.fixture
    def agent(self) -> Agent:
        return Agent(
            collectors=CollectorHost(collectors=[], bridge=_NullBridge()),  # type: ignore[arg-type]
            detectors=DetectorBank(clear_after_s=0.0),
            reasoner=Reasoner(use_llm=False),
            tick_s=0.01,
        )

    class FakeCloud:
        available = True
        model = "llama-3.3-70b-versatile"

    def _incident(self, agent: Agent, attempts: int):
        from warden.contracts import Incident

        incident = Incident(title="t", symptoms=[described()])
        for _ in range(attempts):
            incident.history.append(failure(["powershell.exe", "-Command", "x"]))
        return incident

    def test_a_failure_earns_another_go(self, agent: Agent) -> None:
        agent.reasoner.set_cloud(self.FakeCloud())  # type: ignore[arg-type]
        assert agent._may_retry(self._incident(agent, 1)) is True

    def test_it_stops_at_three_commands(self, agent: Agent) -> None:
        """Not open-ended. Three covers a missing flag, a dependent service or a
        wrong service name, and stops short of a model trying variations at
        someone's machine while they watch."""
        agent.reasoner.set_cloud(self.FakeCloud())  # type: ignore[arg-type]
        assert agent._may_retry(self._incident(agent, 3)) is False

    def test_without_a_cloud_model_there_is_nothing_to_retry_with(
        self, agent: Agent
    ) -> None:
        """The local model picks from a closed registry and cannot write a
        corrected command; the rules engine has nothing to reconsider. Looking
        busy is worse than saying so."""
        assert agent.reasoner.cloud is None
        assert agent._may_retry(self._incident(agent, 1)) is False

    def test_an_unreachable_cloud_does_not_count_as_a_cloud(self, agent: Agent) -> None:
        class Offline:
            available = False
            model = "llama-3.3-70b-versatile"

        agent.reasoner.set_cloud(Offline())  # type: ignore[arg-type]
        assert agent._may_retry(self._incident(agent, 1)) is False


class TestTheClosingNoteStaysHonest:
    def test_a_command_that_failed_is_not_described_as_unverified_success(self) -> None:
        """The old note said "The command ran and exited 1. Warden did not
        verify this", which reads as though something plausibly worked. It did
        not: it errored."""
        note = Agent._composed_note(failure(["x"]), "see whether Bluetooth reconnects")
        assert "failed with exit code 1" in note
        assert "run out of things to try" in note

    def test_a_command_that_exited_zero_still_claims_nothing(self) -> None:
        record = failure(["x"], exit_code=0)
        record.outcome = ExecutionOutcome.RESOLVED
        note = Agent._composed_note(record, "see whether Bluetooth reconnects")
        assert "did not verify" in note
        assert "see whether Bluetooth reconnects" in note
