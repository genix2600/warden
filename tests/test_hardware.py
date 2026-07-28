"""Physical wear detection, and the routing that follows from it.

Every case here ends in `NEEDS_SERVICE` or in silence. There is no path through
these detectors that produces a command, and the tests are written to make that
obvious rather than to be exhaustive about phrasing.
"""

from __future__ import annotations

import pytest

from warden.contracts import ObservationKind, Severity, Verdict
from warden.detectors.hardware import BatteryHealthDetector, StorageHealthDetector
from warden.playbooks import CANDIDATES
from warden.reasoner.rules import RulesReasoner
from warden.store import ObservationStore

from .conftest import make_observation


def battery(store: ObservationStore, *, health_pct: float | None, cycles: float = 300) -> None:
    design, full = 50000.0, (50000.0 * health_pct / 100 if health_pct else None)
    store.ingest(
        [
            make_observation("hw.battery.present", True),
            make_observation(
                "hw.battery.charge",
                {"percent": 80.0, "status_code": 2, "chemistry": "lithium-ion"},
                ObservationKind.METRIC,
            ),
            make_observation(
                "hw.battery.health",
                {
                    "design_mwh": design,
                    "full_charge_mwh": full,
                    "health_pct": health_pct,
                    "cycle_count": cycles,
                    "design_source": "powercfg /batteryreport",
                },
                ObservationKind.METRIC,
            ),
        ]
    )


class TestBattery:
    def test_a_healthy_battery_raises_nothing(self, store: ObservationStore) -> None:
        """Measured on the development machine: 100% of design at 48 cycles."""
        battery(store, health_pct=100.0, cycles=48)
        assert BatteryHealthDetector().evaluate(store) == []

    def test_mild_wear_is_not_reported(self, store: ObservationStore) -> None:
        """85% is normal for a two-year-old laptop and is not worth a warning."""
        battery(store, health_pct=85.0)
        assert BatteryHealthDetector().evaluate(store) == []

    def test_a_worn_battery_is_reported(self, store: ObservationStore) -> None:
        battery(store, health_pct=72.0)
        symptoms = BatteryHealthDetector().evaluate(store)
        assert [s.code for s in symptoms] == ["POWER.BATTERY_WORN"]
        assert symptoms[0].severity is Severity.WARN
        assert symptoms[0].facts["runtime_reduction_pct"] == 28.0

    def test_a_spent_battery_is_critical(self, store: ObservationStore) -> None:
        battery(store, health_pct=45.0)
        assert BatteryHealthDetector().evaluate(store)[0].severity is Severity.CRITICAL

    def test_a_desktop_with_no_battery_is_not_a_fault(self, store: ObservationStore) -> None:
        store.ingest(
            [
                make_observation("hw.battery.present", False),
                make_observation(
                    "hw.battery.health",
                    {"design_mwh": None, "full_charge_mwh": None, "health_pct": None},
                    ObservationKind.METRIC,
                ),
            ]
        )
        assert BatteryHealthDetector().evaluate(store) == []

    def test_unknown_capacity_concludes_nothing(self, store: ObservationStore) -> None:
        """No source on some machines reports design capacity. Silence beats a guess."""
        battery(store, health_pct=None)
        assert BatteryHealthDetector().evaluate(store) == []

    def test_high_cycle_count_changes_the_explanation_not_the_verdict(
        self, store: ObservationStore
    ) -> None:
        battery(store, health_pct=70.0, cycles=1200)
        assert BatteryHealthDetector().evaluate(store)[0].facts["wear_is_expected_for_age"] is True


class TestStorage:
    def test_a_healthy_drive_raises_nothing(self, store: ObservationStore) -> None:
        store.ingest(
            [
                make_observation(
                    "hw.storage.disks",
                    [{"name": "NVMe SAMSUNG", "health": "Healthy", "operational": "OK"}],
                    ObservationKind.INVENTORY,
                )
            ]
        )
        assert StorageHealthDetector().evaluate(store) == []

    def test_an_unreadable_health_status_is_not_a_failure(self, store: ObservationStore) -> None:
        """A drive whose health cannot be read is not a drive that is failing.

        Treating "Unknown" as a fault would produce exactly the false alarm this
        product exists to avoid.
        """
        store.ingest(
            [
                make_observation(
                    "hw.storage.disks",
                    [{"name": "Some drive", "health": "Unknown", "operational": "OK"}],
                    ObservationKind.INVENTORY,
                )
            ]
        )
        assert StorageHealthDetector().evaluate(store) == []

    @pytest.mark.parametrize("status", ["Unhealthy", "Warning"])
    def test_a_failing_drive_is_critical(self, store: ObservationStore, status: str) -> None:
        store.ingest(
            [
                make_observation(
                    "hw.storage.disks",
                    [
                        {
                            "name": "NVMe SAMSUNG",
                            "health": status,
                            "operational": "Degraded",
                            "media_type": "SSD",
                            "size_gb": 476,
                        }
                    ],
                    ObservationKind.INVENTORY,
                )
            ]
        )
        symptoms = StorageHealthDetector().evaluate(store)
        assert [s.code for s in symptoms] == ["STORAGE.DISK_UNHEALTHY"]
        assert symptoms[0].severity is Severity.CRITICAL


class TestRouting:
    """The whole point of these two domains."""

    def test_neither_symptom_has_any_action(self) -> None:
        assert CANDIDATES["POWER.BATTERY_WORN"] == ()
        assert CANDIDATES["STORAGE.DISK_UNHEALTHY"] == ()

    def test_a_worn_battery_routes_to_a_technician_with_the_numbers(
        self, store: ObservationStore
    ) -> None:
        battery(store, health_pct=68.0, cycles=650)
        symptom = BatteryHealthDetector().evaluate(store)[0]
        diagnosis = RulesReasoner().diagnose([symptom], store)

        assert diagnosis.verdict is Verdict.NEEDS_SERVICE
        assert diagnosis.proposal is None
        assert diagnosis.service_advice is not None
        assert diagnosis.service_advice.who == "technician"
        # The advice must carry the measurement, because that is what a repair
        # shop will check for themselves.
        assert "34000" in diagnosis.service_advice.next_step
        assert diagnosis.ranked_hypotheses[0].domain.value == "hardware"

    def test_a_failing_drive_routes_urgently_and_says_back_up_first(
        self, store: ObservationStore
    ) -> None:
        store.ingest(
            [
                make_observation(
                    "hw.storage.disks",
                    [{"name": "NVMe SAMSUNG", "health": "Unhealthy", "size_gb": 476}],
                    ObservationKind.INVENTORY,
                )
            ]
        )
        symptom = StorageHealthDetector().evaluate(store)[0]
        diagnosis = RulesReasoner().diagnose([symptom], store)

        assert diagnosis.verdict is Verdict.NEEDS_SERVICE
        assert diagnosis.service_advice is not None
        assert diagnosis.service_advice.urgency == "urgent"
        assert "back up" in diagnosis.summary.lower()
