"""Detectors for physical wear.

Neither of these has a fix, and that is the point. They exist so that Warden can
say "this is a hardware problem, here is the measurement, here is what to tell a
repair shop" instead of offering a command that could not possibly help.
"""

from __future__ import annotations

from pydantic import JsonValue

from warden.config import THRESHOLDS, Thresholds
from warden.contracts import Severity, Symptom
from warden.detectors.base import Detector
from warden.store import ObservationStore, as_dict, as_float

#: Values the Windows storage stack reports for a drive that is not fine.
#: "Unknown" is excluded deliberately -- a drive whose health cannot be read is
#: not a drive that is failing, and reporting it as one would be a false alarm.
_UNHEALTHY = {"Unhealthy", "Warning"}


class BatteryHealthDetector(Detector):
    id = "hw.battery"
    raises = ("POWER.BATTERY_WORN",)

    def __init__(self, thresholds: Thresholds = THRESHOLDS) -> None:
        self.t = thresholds

    def evaluate(self, store: ObservationStore) -> list[Symptom]:
        observation = store.latest("hw.battery.health")
        if observation is None:
            return []
        if store.value("hw.battery.present") is not True:
            return []  # a desktop, not a fault

        health = as_dict(observation.value)
        health_pct = as_float(health.get("health_pct"))
        if health_pct is None or health_pct >= self.t.battery_worn_pct:
            return []

        cycles = as_float(health.get("cycle_count"))
        design = as_float(health.get("design_mwh"))
        full = as_float(health.get("full_charge_mwh"))
        failed = health_pct < self.t.battery_failed_pct
        expected_wear = cycles is not None and cycles >= self.t.battery_high_cycles

        return [
            self.symptom(
                "POWER.BATTERY_WORN",
                severity=Severity.CRITICAL if failed else Severity.WARN,
                title=(f"The battery holds {health_pct:.0f}% of its original capacity"),
                detail=(
                    f"Full charge is {full:.0f} mWh against a design capacity of "
                    f"{design:.0f} mWh"
                    + (f", after {cycles:.0f} charge cycles." if cycles else ".")
                ),
                facts={
                    "health_pct": health_pct,
                    "design_mwh": design,
                    "full_charge_mwh": full,
                    "cycle_count": cycles,
                    "wear_is_expected_for_age": expected_wear,
                    "chemistry": as_dict(store.value("hw.battery.charge")).get("chemistry"),
                    "runtime_reduction_pct": round(100.0 - health_pct, 1),
                },
                evidence=[observation, store.latest("hw.battery.charge")],
            )
        ]


class StorageHealthDetector(Detector):
    id = "hw.storage"
    raises = ("STORAGE.DISK_UNHEALTHY",)

    def evaluate(self, store: ObservationStore) -> list[Symptom]:
        observation = store.latest("hw.storage.disks")
        if observation is None or not isinstance(observation.value, list):
            return []

        failing: list[dict[str, JsonValue]] = [
            disk
            for raw in observation.value
            if (disk := as_dict(raw)) and disk.get("health") in _UNHEALTHY
        ]
        if not failing:
            return []

        worst = failing[0]
        return [
            self.symptom(
                "STORAGE.DISK_UNHEALTHY",
                severity=Severity.CRITICAL,
                title=f"{worst.get('name')} is reporting a hardware fault",
                detail=(
                    f"The drive's own health reporting returns "
                    f"{worst.get('health')!r} ({worst.get('operational')})."
                ),
                facts={
                    "disks": list(failing),
                    "disk_count": len(failing),
                    "name": worst.get("name"),
                    "health": worst.get("health"),
                    "media_type": worst.get("media_type"),
                    "size_gb": worst.get("size_gb"),
                },
                evidence=[observation, store.latest("hw.storage.volumes")],
            )
        ]
