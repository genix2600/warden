"""The bug that mattered most: a failed fix reported as "Fixed and verified".

A user switched Wi-Fi off. Warden detected it in four seconds, proposed
``netsh wlan connect``, ran it on approval, failed to reconnect, and then showed
a green header reading *"Fixed and verified"* above a red chip reading *"Did not
fix it"*. The session log said the truth. The interface did not.

Three independent defects stacked up to produce it, and each gets a class here.
They are separated because they fail independently: fixing any one of them
leaves the other two able to lie on their own.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from tests.conftest import make_observation
from warden.collectors import CollectorHost
from warden.collectors.network import parse_wlan_interfaces
from warden.contracts import (
    ExecutionOutcome,
    ExecutionRecord,
    IncidentState,
    PredicateRef,
    Severity,
    Symptom,
    VerificationOutcome,
    VerificationResult,
    utcnow,
)
from warden.detectors import DetectorBank
from warden.detectors.network import WifiLinkDetector
from warden.orchestrator import Agent
from warden.playbooks.predicates import PREDICATES
from warden.reasoner import Reasoner
from warden.store import ObservationStore

# ---------------------------------------------------------------------------
# 1. The parser that dropped half a value
# ---------------------------------------------------------------------------

#: Verbatim from `netsh wlan show interfaces` with the radio switched off in
#: software. The second line carries the entire meaning and has no colon.
RADIO_SOFTWARE_OFF = """
There is 1 interface on the system:

    Name                   : Wi-Fi
    Description            : Intel(R) Wi-Fi 6 AX201 160MHz
    GUID                   : 7c4a8d09-ca37-4b2f-9f1e-2b1c3d4e5f60
    Physical address       : a4:c3:f0:11:22:33
    State                  : disconnected
    Radio status           : Hardware On
                             Software Off
"""

RADIO_FULLY_ON = """
There is 1 interface on the system:

    Name                   : Wi-Fi
    State                  : connected
    SSID                   : HomeNet
    Radio status           : Hardware On
                             Software On
    Signal                 : 82%
"""


class TestMultiLineValues:
    def test_a_continuation_line_is_not_discarded(self) -> None:
        """The defect itself. Every line without a colon used to be skipped."""
        [interface] = parse_wlan_interfaces(RADIO_SOFTWARE_OFF)
        assert interface["radio status"] == "Hardware On Software Off"

    def test_the_radio_reads_as_off_so_the_symptom_can_be_right(self) -> None:
        """Downstream does a substring test, which is why the join is a space."""
        [interface] = parse_wlan_interfaces(RADIO_SOFTWARE_OFF)
        assert "off" in interface["radio status"].lower()

    def test_a_radio_that_is_on_does_not_read_as_off(self) -> None:
        [interface] = parse_wlan_interfaces(RADIO_FULLY_ON)
        assert "off" not in interface["radio status"].lower()

    def test_colons_inside_values_still_survive(self) -> None:
        """The original reason for splitting on the first colon only."""
        [interface] = parse_wlan_interfaces(RADIO_SOFTWARE_OFF)
        assert interface["physical address"] == "a4:c3:f0:11:22:33"

    def test_an_unindented_line_continues_nothing(self) -> None:
        """'There is 1 interface on the system:' is a heading, not a value."""
        [interface] = parse_wlan_interfaces(RADIO_SOFTWARE_OFF)
        assert "system" not in " ".join(interface.values()).lower()

    def test_a_blank_line_ends_a_continuation(self) -> None:
        text = "    Name : Wi-Fi\n    State : disconnected\n\n    orphaned text\n"
        [interface] = parse_wlan_interfaces(text)
        assert interface["state"] == "disconnected"


class TestSwitchedOffRadioIsUnfixable:
    def test_a_software_off_radio_raises_radio_off_not_disconnected(
        self, connected_store: ObservationStore
    ) -> None:
        """The whole point. RADIO_OFF maps to an empty candidate list, so no
        command can be proposed for it. DISCONNECTED maps to three, and that is
        how a switched-off radio got a `netsh wlan connect` it could never
        satisfy."""
        for _ in range(2):
            connected_store.ingest(
                [
                    make_observation(
                        "net.wifi.link",
                        {
                            "state": "disconnected",
                            "radio": "Hardware On Software Off",
                            "ssid": None,
                            "interface": "Wi-Fi",
                        },
                    )
                ]
            )
        symptoms = WifiLinkDetector().evaluate(connected_store)
        assert [s.code for s in symptoms] == ["NET.WIFI.RADIO_OFF"]

    def test_that_symptom_has_no_action_available(self) -> None:
        from warden.playbooks import CANDIDATES

        assert CANDIDATES["NET.WIFI.RADIO_OFF"] == ()


# ---------------------------------------------------------------------------
# 2. Stale readings passing as proof
# ---------------------------------------------------------------------------


class TestStaleEvidence:
    def test_a_reading_older_than_the_bound_is_withheld(self) -> None:
        store = ObservationStore()
        old = make_observation("net.wifi.link", {"state": "connected", "ssid": "HomeNet"})
        old.captured_at = utcnow() - timedelta(seconds=120)
        store.ingest([old])

        assert store.latest("net.wifi.link") is not None  # unbounded read: present
        assert store.latest("net.wifi.link", max_age_s=20.0) is None

    def test_a_fresh_reading_is_returned(self) -> None:
        store = ObservationStore()
        store.ingest([make_observation("net.wifi.link", {"state": "connected"})])
        assert store.latest("net.wifi.link", max_age_s=20.0) is not None

    def test_the_last_healthy_reading_cannot_verify_a_failed_fix(self) -> None:
        """The dangerous case, stated exactly.

        The last reading before a wireless drop says ``connected``. Retention is
        ten minutes. If the forced re-probe produces nothing -- netsh timed out,
        the PowerShell host was killed -- an unbounded read hands the verifier
        that pre-fault sample and it passes.
        """
        store = ObservationStore()
        before_the_fault = make_observation(
            "net.wifi.link", {"state": "connected", "ssid": "HomeNet", "signal_pct": 82}
        )
        before_the_fault.captured_at = utcnow() - timedelta(seconds=90)
        store.ingest([before_the_fault])

        passed, detail = PREDICATES["wifi.associated"](store, {"profile": "HomeNet"})
        assert passed is None, "a 90-second-old reading must not prove a fix"
        assert "no wireless reading" in detail


class TestGatheringInformationProvesNothing:
    def test_report_only_is_inconclusive_rather_than_passed(self) -> None:
        """It returned True, and True closes the incident as RESOLVED.

        `net.wifi.scan` is rung two of the wireless ladder. Passing vacuously
        closed the incident as fixed with the adapter still down and abandoned
        rung three.
        """
        passed, detail = PREDICATES["report.only"](ObservationStore(), {})
        assert passed is None
        assert "nothing is proven" in detail


# ---------------------------------------------------------------------------
# 3. A symptom going quiet is not a fix
# ---------------------------------------------------------------------------


@pytest.fixture
def symptom() -> Symptom:
    return Symptom(
        code="NET.WIFI.DISCONNECTED",
        severity=Severity.CRITICAL,
        title="Wireless is disconnected",
        detail="adapter up, radio on, not associated",
        detector="wifi.link",
        facts={"last_connected_profile": "HomeNet"},
    )


@pytest.fixture
def agent() -> Agent:
    """Bare agent. These tests call `_on_symptom_cleared` directly rather than
    driving ticks, because the branch under test is about incident bookkeeping
    and not about detection timing."""
    return Agent(
        collectors=CollectorHost(collectors=[], bridge=_NullBridge()),  # type: ignore[arg-type]
        detectors=DetectorBank(clear_after_s=0.0),
        reasoner=Reasoner(use_llm=False),
        tick_s=0.01,
    )


@pytest.fixture
def failed_execution() -> ExecutionRecord:
    """A reconnect that ran, exited zero, and did not reconnect. Measured
    behaviour: `netsh wlan connect` reports success one time in three."""
    return ExecutionRecord(
        proposal_id="p-test",
        action_id="net.wifi.reconnect",
        argv=["netsh", "wlan", "connect", "name=HomeNet", "interface=Wi-Fi"],
        approved_at=utcnow(),
        exit_code=0,
        outcome=ExecutionOutcome.NOT_RESOLVED,
        verification=VerificationResult(
            outcome=VerificationOutcome.FAILED,
            predicate=PredicateRef(
                id="wifi.associated",
                describe="Re-read the adapter and confirm it is associated.",
            ),
            detail="the adapter reports state 'disconnected'",
        ),
    )


class _NullBridge:
    def warmup(self, timeout: float = 0.0) -> float:
        return 0.0

    def close(self) -> None:
        pass


class TestSymptomClearedDoesNotMeanFixed:
    """`_on_symptom_cleared` closed any non-terminal incident as RESOLVED, and
    RESOLVED is the only value the interface paints green.

    A code stops being reported for three reasons and only one is a fix: the
    fault was repaired, the fault re-classified to a different code, or the
    collector missed two samples in ten seconds. Warden cannot tell them apart
    from the absence alone.
    """

    @staticmethod
    def _open(agent: Agent, symptom: Symptom):
        """`_open_incident` returns None; the incident is reachable by code."""
        agent._open_incident(symptom)
        return agent.incidents[agent._incident_by_code[symptom.code]]

    @pytest.mark.asyncio
    async def test_an_untouched_incident_still_closes_as_resolved(self, agent, symptom) -> None:
        """The legitimate case must keep working: nothing ran, so a symptom
        going away really is the machine sorting itself out."""
        incident = self._open(agent, symptom)
        agent._on_symptom_cleared(symptom.code)
        assert incident.state is IncidentState.RESOLVED

    @pytest.mark.asyncio
    async def test_an_incident_that_ran_something_is_not_closed(
        self, agent, symptom, failed_execution
    ) -> None:
        """The bug. An action ran, verification failed, the code churned to
        RADIO_OFF, and the header went green."""
        incident = self._open(agent, symptom)
        incident.execution = failed_execution

        agent._on_symptom_cleared(symptom.code)

        assert incident.state is not IncidentState.RESOLVED
        assert not incident.state.is_terminal
        assert any("not evidence of a fix" in note for note in incident.notes)

    @pytest.mark.asyncio
    async def test_a_failed_attempt_in_history_counts_too(
        self, agent, symptom, failed_execution
    ) -> None:
        """After escalation the failed run moves to `history` and `execution`
        is replaced, so checking only `execution` would reopen the hole."""
        incident = self._open(agent, symptom)
        incident.history.append(failed_execution)

        agent._on_symptom_cleared(symptom.code)

        assert incident.state is not IncidentState.RESOLVED

    @pytest.mark.asyncio
    async def test_the_verifier_is_still_left_alone_mid_flight(self, agent, symptom) -> None:
        incident = self._open(agent, symptom)
        incident.state = IncidentState.VERIFYING
        agent._on_symptom_cleared(symptom.code)
        assert incident.state is IncidentState.VERIFYING
