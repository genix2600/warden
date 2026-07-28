"""Detector registry and the raise/clear tracking that turns findings into events.

Detectors are stateless and re-evaluate the whole store every tick. The tracker
here holds the only state that matters: which symptoms were present last time,
so that a symptom appearing or disappearing becomes an event rather than a
repeated assertion.
"""

from __future__ import annotations

import logging

from warden.contracts import Symptom
from warden.detectors.base import Detector
from warden.detectors.devices import DeviceFaultDetector, DiskSpaceDetector
from warden.detectors.hardware import BatteryHealthDetector, StorageHealthDetector
from warden.detectors.network import ReachabilityDetector, WifiLinkDetector
from warden.detectors.privacy import CameraDeviceDetector, PrivacyBlockDetector
from warden.detectors.services import ServiceDetector
from warden.detectors.thermal import ThermalThrottleDetector
from warden.store import ObservationStore

log = logging.getLogger(__name__)

__all__ = [
    "BatteryHealthDetector",
    "CameraDeviceDetector",
    "Detector",
    "DetectorBank",
    "DeviceFaultDetector",
    "DiskSpaceDetector",
    "PrivacyBlockDetector",
    "ReachabilityDetector",
    "ServiceDetector",
    "StorageHealthDetector",
    "ThermalThrottleDetector",
    "WifiLinkDetector",
    "build_default_detectors",
]


def build_default_detectors() -> list[Detector]:
    return [
        WifiLinkDetector(),
        ReachabilityDetector(),
        ThermalThrottleDetector(),
        DeviceFaultDetector(),
        DiskSpaceDetector(),
        BatteryHealthDetector(),
        StorageHealthDetector(),
        ServiceDetector(),
        PrivacyBlockDetector(),
        CameraDeviceDetector(),
    ]


class DetectorBank:
    """Runs every detector and reports the delta against the previous tick."""

    def __init__(self, detectors: list[Detector] | None = None) -> None:
        self.detectors = detectors if detectors is not None else build_default_detectors()
        self._active: dict[str, Symptom] = {}

    @property
    def active(self) -> list[Symptom]:
        return list(self._active.values())

    @property
    def known_codes(self) -> set[str]:
        return {code for d in self.detectors for code in d.raises}

    def evaluate(self, store: ObservationStore) -> tuple[list[Symptom], list[str]]:
        """Return (newly raised symptoms, codes that have cleared)."""
        found: dict[str, Symptom] = {}
        for detector in self.detectors:
            try:
                for symptom in detector.evaluate(store):
                    found[symptom.code] = symptom
            except Exception:
                log.exception("detector %s raised", detector.id)

        raised = [s for code, s in found.items() if code not in self._active]
        cleared = [code for code in self._active if code not in found]
        self._active = found
        return raised, cleared
