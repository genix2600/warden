"""The check registry, and the three checks, driven from hand-built readings.

No hardware. Every case here is one a real machine could present and this
development machine cannot: an adapter whose driver hides the setting, a
mechanical disk, a restart owed for a month.
"""

from __future__ import annotations

from datetime import timedelta

from pydantic import JsonValue

from warden.audit import CHECKS, run_audit
from warden.audit.checks import DefragOnSsdCheck, RebootPendingCheck, WifiPowerSavingCheck
from warden.contracts import (
    CheckStatus,
    Mechanism,
    Observation,
    ObservationKind,
    Provenance,
    utcnow,
)
from warden.domains import BY_ID
from warden.store import ObservationStore


def observation(source: str, value: JsonValue) -> Observation:
    return Observation(
        source=source,
        kind=ObservationKind.STATE,
        value=value,
        provenance=Provenance(probe="test", mechanism=Mechanism.CIM, elapsed_ms=1),
    )


def store_with(**sources: JsonValue) -> ObservationStore:
    store = ObservationStore()
    store.ingest([observation(s.replace("__", "."), v) for s, v in sources.items()])
    return store


class TestRegistryCoverage:
    """The rules the registry enforces at import, asserted again here."""

    def test_every_check_belongs_to_a_user_facing_domain(self) -> None:
        for check in CHECKS:
            assert check.domain_id in BY_ID, (
                f"{check.id} files its findings under {check.domain_id!r}, which is not "
                "an area the user sees anywhere else in the interface"
            )

    def test_every_check_cites_where_its_threshold_came_from(self) -> None:
        for check in CHECKS:
            assert check.metric.rationale_source.strip()

    def test_every_check_names_a_unit(self) -> None:
        """No unit means no measurement means it should not have shipped."""
        for check in CHECKS:
            assert check.metric.unit.strip()

    def test_check_ids_are_unique(self) -> None:
        assert len({c.id for c in CHECKS}) == len(CHECKS)


class TestAuditPass:
    def test_a_broken_check_does_not_cost_the_user_the_others(self) -> None:
        class Exploding(WifiPowerSavingCheck):
            id = "exploding"

            def run(self, store: ObservationStore) -> object:  # type: ignore[override]
                raise RuntimeError("boom")

        report = run_audit(ObservationStore())
        assert len(report.results) == len(CHECKS)
        assert report.finished_at is not None

    def test_an_empty_store_reads_as_unknown_not_healthy(self) -> None:
        """The whole product argues against reporting health it did not verify."""
        report = run_audit(ObservationStore())
        assert report.optimal == 0
        assert all(r.status is CheckStatus.COULD_NOT_READ for r in report.results)


class TestWifiPowerSaving:
    def test_power_saving_enabled_is_suboptimal(self) -> None:
        store = store_with(audit__wifi__power_management=[{"name": "Wi-Fi", "power_saving": True}])
        result = WifiPowerSavingCheck().run(store)
        assert result.status is CheckStatus.SUBOPTIMAL
        assert "power" in result.detail.lower()

    def test_power_saving_disabled_is_optimal(self) -> None:
        store = store_with(audit__wifi__power_management=[{"name": "Wi-Fi", "power_saving": False}])
        assert WifiPowerSavingCheck().run(store).status is CheckStatus.OPTIMAL

    def test_a_driver_that_hides_the_setting_is_not_a_pass(self) -> None:
        """None is 'the driver does not say', which is not 'it is switched off'."""
        store = store_with(audit__wifi__power_management=[{"name": "Wi-Fi", "power_saving": None}])
        assert WifiPowerSavingCheck().run(store).status is CheckStatus.COULD_NOT_READ

    def test_a_machine_with_no_wireless_is_not_applicable(self) -> None:
        store = store_with(audit__wifi__power_management=[])
        assert WifiPowerSavingCheck().run(store).status is CheckStatus.NOT_APPLICABLE


class TestRebootPending:
    def _state(self, *, pending: bool, days: float) -> dict[str, JsonValue]:
        return {
            "servicing": pending,
            "windows_update": False,
            "file_renames": False,
            "last_boot": (utcnow() - timedelta(days=days)).isoformat(),
        }

    def test_nothing_pending_is_optimal(self) -> None:
        store = store_with(audit__servicing__reboot_pending=self._state(pending=False, days=1))
        assert RebootPendingCheck().run(store).status is CheckStatus.OPTIMAL

    def test_pending_for_a_month_is_suboptimal(self) -> None:
        store = store_with(audit__servicing__reboot_pending=self._state(pending=True, days=30))
        result = RebootPendingCheck().run(store)
        assert result.status is CheckStatus.SUBOPTIMAL
        assert "30 days" in result.detail

    def test_pending_since_this_morning_is_not_worth_nagging_about(self) -> None:
        """Restarts are owed all the time. Only a forgotten one is a finding."""
        store = store_with(audit__servicing__reboot_pending=self._state(pending=True, days=0.2))
        assert RebootPendingCheck().run(store).status is CheckStatus.OPTIMAL


class TestDefragOnSsd:
    def test_a_schedule_against_solid_state_is_correct_not_a_fault(self) -> None:
        """Modern Windows sends TRIM here. Calling it a problem is scaremongering."""
        store = store_with(
            audit__defrag__schedule={"present": True, "state": "Ready"},
            hw__storage__disks=[{"media_type": "SSD", "friendly_name": "NVMe"}],
        )
        result = DefragOnSsdCheck().run(store)
        assert result.status is CheckStatus.OPTIMAL
        assert "TRIM" in result.detail

    def test_a_mechanical_drive_with_no_schedule_is_a_real_finding(self) -> None:
        store = store_with(
            audit__defrag__schedule={"present": False, "state": None},
            hw__storage__disks=[{"media_type": "HDD", "friendly_name": "Spinning"}],
        )
        assert DefragOnSsdCheck().run(store).status is CheckStatus.SUBOPTIMAL

    def test_no_schedule_and_no_mechanical_drive_does_not_arise(self) -> None:
        store = store_with(
            audit__defrag__schedule={"present": False, "state": None},
            hw__storage__disks=[{"media_type": "SSD", "friendly_name": "NVMe"}],
        )
        assert DefragOnSsdCheck().run(store).status is CheckStatus.NOT_APPLICABLE
