"""Device faults and storage headroom.

Both read a single inventory observation, so there is no windowing to do: a
device Windows has flagged with a Configuration Manager problem code is flagged
now, and a full disk is full now.
"""

from __future__ import annotations

from pydantic import JsonValue

from warden.config import THRESHOLDS, Thresholds
from warden.contracts import Severity, Symptom
from warden.detectors.base import Detector
from warden.store import ObservationStore, as_float

#: Problem codes where a device restart or driver reinstall is a sensible thing
#: to attempt. Codes outside this set (22 = deliberately disabled, 45 = simply
#: not plugged in) are states, not faults, and proposing a fix for them would be
#: the software equivalent of a scripted troubleshooter guessing.
_RECOVERABLE_CODES = {1, 3, 10, 14, 18, 19, 31, 37, 39, 43}
_NOT_A_FAULT = {22, 45}


class DeviceFaultDetector(Detector):
    id = "dev.fault"
    raises = ("DEV.DEVICE_FAULT",)

    def evaluate(self, store: ObservationStore) -> list[Symptom]:
        observation = store.latest("dev.problem_devices")
        if observation is None or not isinstance(observation.value, list):
            return []
        # Narrowed to dicts here so the reads below are checked. It is widened
        # back to JsonValue only where it enters `facts`, which is the boundary
        # where the shape genuinely becomes arbitrary again.
        faulted: list[dict[str, JsonValue]] = [
            d
            for d in observation.value
            if isinstance(d, dict) and d.get("problem_code") not in _NOT_A_FAULT
        ]
        if not faulted:
            return []

        recoverable = [d for d in faulted if d.get("problem_code") in _RECOVERABLE_CODES]
        headline = faulted[0]
        return [
            self.symptom(
                "DEV.DEVICE_FAULT",
                severity=Severity.WARN,
                title=(
                    f"{len(faulted)} device(s) reporting a fault"
                    if len(faulted) > 1
                    else f"{headline.get('name')} is not working"
                ),
                detail="; ".join(
                    f"{d.get('name')}: code {d.get('problem_code')} - {d.get('problem')}"
                    for d in faulted[:3]
                ),
                facts={
                    "devices": list(faulted[:5]),
                    "fault_count": len(faulted),
                    "recoverable_count": len(recoverable),
                    "first_recoverable_device_id": (
                        recoverable[0].get("device_id") if recoverable else None
                    ),
                    "first_recoverable_name": (recoverable[0].get("name") if recoverable else None),
                },
                evidence=[observation],
            )
        ]


class DiskSpaceDetector(Detector):
    id = "sys.disk"
    raises = ("SYS.DISK_LOW",)

    def __init__(self, thresholds: Thresholds = THRESHOLDS) -> None:
        self.t = thresholds

    def evaluate(self, store: ObservationStore) -> list[Symptom]:
        observation = store.latest("sys.disk.volumes")
        if observation is None or not isinstance(observation.value, list):
            return []
        tight: list[dict[str, JsonValue]] = [
            v
            for v in observation.value
            if isinstance(v, dict)
            # Both conditions, not either: a nearly-full drive with hundreds of
            # gigabytes left is not a problem, and a small drive at 80% is not
            # one either.
            and (as_float(v.get("percent_used")) or 0.0) >= self.t.disk_low_percent_used
            and (as_float(v.get("free_gb")) or 0.0) <= self.t.disk_low_free_gb
        ]
        if not tight:
            return []
        worst = min(tight, key=lambda v: as_float(v.get("free_gb")) or 0.0)
        return [
            self.symptom(
                "SYS.DISK_LOW",
                severity=Severity.WARN,
                title=f"Drive {worst.get('mount')} is nearly full",
                detail=(
                    f"{worst.get('free_gb')} GB free of {worst.get('total_gb')} GB "
                    f"({worst.get('percent_used')}% used)."
                ),
                facts={"volumes": list(tight), "worst": dict(worst)},
                evidence=[observation],
            )
        ]
