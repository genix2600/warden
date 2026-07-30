"""Detector registry and the raise/clear tracking that turns findings into events.

Detectors are stateless and re-evaluate the whole store every tick. The tracker
here holds the only state that matters: which symptoms were present last time,
so that a symptom appearing or disappearing becomes an event rather than a
repeated assertion.
"""

from __future__ import annotations

import logging
import time

from warden.contracts import Symptom
from warden.detectors.base import Detector
from warden.detectors.devices import DeviceFaultDetector, DiskSpaceDetector
from warden.detectors.hardware import BatteryHealthDetector, StorageHealthDetector
from warden.detectors.netconfig import (
    HostsFileDetector,
    NetworkProfileDetector,
    ProxyDetector,
)
from warden.detectors.network import ReachabilityDetector, WifiLinkDetector
from warden.detectors.privacy import CameraDeviceDetector, PrivacyBlockDetector
from warden.detectors.services import ServiceDetector
from warden.detectors.thermal import ThermalThrottleDetector
from warden.detectors.timesync import TimeSyncDetector
from warden.store import ObservationStore

log = logging.getLogger(__name__)

__all__ = [
    "BatteryHealthDetector",
    "CameraDeviceDetector",
    "Detector",
    "DetectorBank",
    "DeviceFaultDetector",
    "DiskSpaceDetector",
    "HostsFileDetector",
    "NetworkProfileDetector",
    "PrivacyBlockDetector",
    "ProxyDetector",
    "ReachabilityDetector",
    "ServiceDetector",
    "StorageHealthDetector",
    "ThermalThrottleDetector",
    "TimeSyncDetector",
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
        NetworkProfileDetector(),
        ProxyDetector(),
        HostsFileDetector(),
        TimeSyncDetector(),
    ]


#: How long a symptom must stay absent before it counts as cleared.
#:
#: Raising is already debounced -- a condition has to hold across consecutive
#: samples -- but clearing was instant, and that asymmetry is what produces
#: flapping. A processor oscillating either side of a threshold went
#: raised -> cleared -> raised every few seconds, and each raise opened a fresh
#: incident and ran the model again on a fault that had never actually gone
#: away. Observed on a machine holding 85-95% load: the same throttling
#: diagnosed over and over.
#:
#: Thirty seconds because the thermal detector already averages over a 45s
#: window, so its own output moves on that timescale; anything shorter would
#: let the mean cross back and forth inside the hysteresis gap.
_CLEAR_AFTER_S = 30.0


class DetectorBank:
    """Runs every detector and reports the delta against the previous tick."""

    def __init__(
        self,
        detectors: list[Detector] | None = None,
        clear_after_s: float = _CLEAR_AFTER_S,
    ) -> None:
        self.detectors = detectors if detectors is not None else build_default_detectors()
        #: Injectable so tests can assert the raise/clear contract without
        #: sleeping for half a minute. Production never overrides it.
        self.clear_after_s = clear_after_s
        self._active: dict[str, Symptom] = {}
        #: When each currently-absent symptom was last seen. A symptom in here
        #: is still considered active; it is on probation, not gone.
        self._missing_since: dict[str, float] = {}

    @property
    def active(self) -> list[Symptom]:
        return list(self._active.values())

    @property
    def known_codes(self) -> set[str]:
        return {code for d in self.detectors for code in d.raises}

    def evaluate(
        self, store: ObservationStore, now: float | None = None
    ) -> tuple[list[Symptom], list[str]]:
        """Return (newly raised symptoms, codes that have cleared).

        Clearing is deliberately slower than raising. A symptom that disappears
        is held for :data:`_CLEAR_AFTER_S` before it counts as gone, and if it
        reappears in that window it was never cleared and is never re-raised --
        so a measurement oscillating across its threshold produces one symptom
        rather than a new one every few seconds.
        """
        now = now if now is not None else time.monotonic()
        found: dict[str, Symptom] = {}
        for detector in self.detectors:
            try:
                for symptom in detector.evaluate(store):
                    found[symptom.code] = symptom
            except Exception:
                log.exception("detector %s raised", detector.id)

        raised = [s for code, s in found.items() if code not in self._active]

        cleared: list[str] = []
        for code in list(self._active):
            if code in found:
                self._missing_since.pop(code, None)
                continue
            since = self._missing_since.setdefault(code, now)
            if now - since >= self.clear_after_s:
                cleared.append(code)
                self._missing_since.pop(code, None)

        # Symptoms on probation stay active with their last seen detail, so the
        # interface does not blink them off and on either.
        self._active = {
            **{code: s for code, s in self._active.items() if code in self._missing_since},
            **found,
        }
        return raised, cleared
