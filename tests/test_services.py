"""Six subsystems behind one collector, and the false alarm that nearly happened.

The case worth reading first is
``test_a_stopped_manual_service_is_not_a_fault``. Windows Update's service is
*stopped* on a perfectly healthy machine -- measured on the development box --
because its start type is Manual and Windows runs it on demand. A detector that
simply asked "is it running?" would report a critical fault on essentially every
Windows machine in the world.
"""

from __future__ import annotations

import pytest

from warden.collectors.services import RESTARTABLE, WATCHED
from warden.contracts import Severity, Verdict
from warden.detectors.services import ServiceDetector
from warden.playbooks import CANDIDATES, REGISTRY, ActionRejected
from warden.playbooks.predicates import PREDICATES
from warden.reasoner.rules import RulesReasoner
from warden.store import ObservationStore

from .conftest import make_observation

RUNNING, STOPPED = 4, 1
AUTOMATIC, MANUAL, DISABLED = 2, 3, 4


def services(store: ObservationStore, **overrides: tuple[int | None, int | None]) -> None:
    """Publish a service table; every service is healthy unless overridden."""
    rows = []
    for watched in WATCHED:
        status, start_type = overrides.get(watched.name, (RUNNING, AUTOMATIC))
        rows.append(
            {
                "name": watched.name,
                "subsystem": watched.subsystem,
                "present": status is not None,
                "status": status,
                "start_type": start_type,
                "display_name": f"{watched.subsystem.title()} Service",
            }
        )
    store.ingest([make_observation("sys.services", rows)])


class TestDetection:
    def test_all_healthy_raises_nothing(self, store: ObservationStore) -> None:
        services(store)
        assert ServiceDetector().evaluate(store) == []

    def test_a_stopped_manual_service_is_not_a_fault(self, store: ObservationStore) -> None:
        """Measured: wuauserv is Stopped/Manual on a healthy machine.

        Windows starts it on demand and stops it when it is done. Reporting this
        would be a critical alert on almost every Windows machine there is.
        """
        services(store, wuauserv=(STOPPED, MANUAL))
        assert ServiceDetector().evaluate(store) == []

    def test_a_stopped_automatic_service_is_a_fault(self, store: ObservationStore) -> None:
        services(store, Spooler=(STOPPED, AUTOMATIC))
        symptoms = ServiceDetector().evaluate(store)
        assert [s.code for s in symptoms] == ["PRINT.SPOOLER_STOPPED"]
        assert symptoms[0].severity is Severity.CRITICAL
        assert symptoms[0].facts["is_disabled"] is False

    def test_a_disabled_service_is_a_distinct_fault(self, store: ObservationStore) -> None:
        """Disabled needs a different fix: starting it alone would not stick."""
        services(store, Audiosrv=(STOPPED, DISABLED))
        symptoms = ServiceDetector().evaluate(store)
        assert [s.code for s in symptoms] == ["AUDIO.SERVICE_STOPPED"]
        assert symptoms[0].facts["is_disabled"] is True
        assert "turned off" in symptoms[0].title

    def test_an_absent_service_is_not_a_fault(self, store: ObservationStore) -> None:
        """A desktop with no Bluetooth genuinely has no bthserv."""
        services(store, bthserv=(None, None))
        assert ServiceDetector().evaluate(store) == []

    def test_several_subsystems_can_fail_at_once(self, store: ObservationStore) -> None:
        services(store, Spooler=(STOPPED, AUTOMATIC), Audiosrv=(STOPPED, AUTOMATIC))
        assert sorted(s.code for s in ServiceDetector().evaluate(store)) == [
            "AUDIO.SERVICE_STOPPED",
            "PRINT.SPOOLER_STOPPED",
        ]

    def test_the_detail_is_written_for_a_non_technical_reader(
        self, store: ObservationStore
    ) -> None:
        services(store, Spooler=(STOPPED, AUTOMATIC))
        detail = ServiceDetector().evaluate(store)[0].detail
        assert "nothing can print" in detail


class TestAllowlist:
    def test_only_watched_services_can_be_restarted(self, store: ObservationStore) -> None:
        """The reachable set is the table, not "any service you can name"."""
        services(store, Spooler=(STOPPED, AUTOMATIC))
        for forbidden in ("WinDefend", "MSSQLSERVER", "LanmanServer"):
            with pytest.raises(ActionRejected, match="not one of the services Warden watches"):
                REGISTRY.get("sys.service.restart").propose(
                    {"service": forbidden}, store, rationale="t"
                )

    def test_a_running_service_is_not_restarted(self, store: ObservationStore) -> None:
        services(store)
        with pytest.raises(ActionRejected, match="already running"):
            REGISTRY.get("sys.service.restart").propose(
                {"service": "Spooler"}, store, rationale="t"
            )

    def test_an_absent_service_is_not_restarted(self, store: ObservationStore) -> None:
        services(store, bthserv=(None, None))
        with pytest.raises(ActionRejected, match="not installed"):
            REGISTRY.get("sys.service.restart").propose(
                {"service": "bthserv"}, store, rationale="t"
            )

    @pytest.mark.parametrize("bad", ["Spooler; calc", "Spooler'", "Spo oler", "$(whoami)"])
    def test_a_service_name_cannot_carry_shell_syntax(
        self, store: ObservationStore, bad: str
    ) -> None:
        services(store, Spooler=(STOPPED, AUTOMATIC))
        with pytest.raises(ActionRejected):
            REGISTRY.get("sys.service.restart").propose({"service": bad}, store, rationale="t")

    def test_a_stopped_watched_service_renders_the_expected_command(
        self, store: ObservationStore
    ) -> None:
        services(store, Spooler=(STOPPED, AUTOMATIC))
        proposal = REGISTRY.get("sys.service.restart").propose(
            {"service": "Spooler"}, store, rationale="t"
        )
        assert proposal.rendered_argv[-1] == "Start-Service -Name 'Spooler' -ErrorAction Stop"
        assert proposal.requires_admin is True


class TestRouting:
    def test_every_watched_service_has_actions_and_a_handler(self) -> None:
        from warden.reasoner.rules import HANDLERS

        for watched in WATCHED:
            assert CANDIDATES[watched.symptom_code] == (
                "sys.service.restart",
                "sys.service.enable",
            )
            assert watched.symptom_code in HANDLERS

    def test_a_stopped_service_proposes_a_restart(self, store: ObservationStore) -> None:
        services(store, Spooler=(STOPPED, AUTOMATIC))
        symptom = ServiceDetector().evaluate(store)[0]
        diagnosis = RulesReasoner().diagnose([symptom], store)

        assert diagnosis.verdict is Verdict.ACTIONABLE
        assert diagnosis.proposal is not None
        assert diagnosis.proposal.action_id == "sys.service.restart"
        assert "printing" in diagnosis.summary

    def test_a_disabled_service_skips_straight_to_re_enabling(
        self, store: ObservationStore
    ) -> None:
        """Restarting a disabled service would fail, so the gentler action is
        deliberately skipped rather than tried and wasted."""
        services(store, Audiosrv=(STOPPED, DISABLED))
        symptom = ServiceDetector().evaluate(store)[0]
        diagnosis = RulesReasoner().diagnose([symptom], store)

        assert diagnosis.proposal is not None
        assert diagnosis.proposal.action_id == "sys.service.enable"

    def test_the_success_check_is_registered(self) -> None:
        for action in ("sys.service.restart", "sys.service.enable"):
            assert REGISTRY.get(action).verify.predicate.id in PREDICATES

    def test_the_allowlist_matches_the_watched_table(self) -> None:
        assert {w.name for w in WATCHED} == RESTARTABLE


class TestVerification:
    def test_the_predicate_reads_state_not_exit_code(self, store: ObservationStore) -> None:
        """Start-Service can succeed for a service that stops again immediately."""
        predicate = PREDICATES["service.running"]

        services(store, Spooler=(STOPPED, AUTOMATIC))
        passed, detail = predicate(store, {"service": "Spooler"})
        assert passed is False and "still stopped" in detail

        services(store)
        passed, detail = predicate(store, {"service": "Spooler"})
        assert passed is True and "now running" in detail

    def test_a_missing_reading_is_inconclusive_not_failure(self, store: ObservationStore) -> None:
        passed, detail = PREDICATES["service.running"](store, {"service": "Spooler"})
        assert passed is None
