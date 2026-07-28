"""Shared fixtures.

Everything here builds observations by hand rather than touching Windows, which
is the payoff of keeping collectors and detectors strictly separate: the entire
detection, reasoning and guardrail layer is testable on any machine, in
milliseconds, with no hardware and no elevation.
"""

from __future__ import annotations

import pytest

from warden.contracts import (
    Mechanism,
    Observation,
    ObservationKind,
    Provenance,
    Severity,
    Symptom,
)
from warden.store import ObservationStore


def make_observation(
    source: str,
    value: object,
    kind: ObservationKind = ObservationKind.STATE,
    unit: str | None = None,
    confidence: float = 1.0,
) -> Observation:
    return Observation(
        source=source,
        kind=kind,
        value=value,  # type: ignore[arg-type]
        unit=unit,
        confidence=confidence,
        provenance=Provenance(probe=f"test::{source}", mechanism=Mechanism.CIM, elapsed_ms=1),
    )


@pytest.fixture
def store() -> ObservationStore:
    return ObservationStore()


@pytest.fixture
def connected_store(store: ObservationStore) -> ObservationStore:
    """A machine that is online and healthy."""
    store.ingest(
        [
            make_observation(
                "net.wifi.adapter", {"present": True, "name": "Wi-Fi", "status": "Up"}
            ),
            make_observation(
                "net.wifi.link",
                {
                    "state": "connected",
                    "ssid": "HomeNet",
                    "profile": "HomeNet",
                    "radio": "on",
                    "signal_pct": 82,
                    "interface": "Wi-Fi",
                },
            ),
            make_observation("net.wifi.profiles", ["HomeNet", "Cafe"], ObservationKind.INVENTORY),
            make_observation("net.connectivity.internet", True),
            make_observation("net.connectivity.dns", {"resolves": True, "host": "example.test"}),
            make_observation(
                "net.connectivity.gateway", {"address": "192.168.1.1", "reachable": True}
            ),
        ]
    )
    return store


@pytest.fixture
def disconnected_store(connected_store: ObservationStore) -> ObservationStore:
    """The same machine after the wireless link drops.

    Two consecutive bad samples, because every network detector debounces --
    a single bad reading is a roam, not a fault.
    """
    for _ in range(2):
        connected_store.ingest(
            [
                make_observation(
                    "net.wifi.link",
                    {
                        "state": "disconnected",
                        "ssid": None,
                        "profile": None,
                        "radio": "on",
                        "signal_pct": None,
                        "interface": "Wi-Fi",
                    },
                ),
                make_observation("net.connectivity.internet", False),
            ]
        )
    return connected_store


@pytest.fixture
def wifi_symptom() -> Symptom:
    return Symptom(
        code="NET.WIFI.DISCONNECTED",
        severity=Severity.CRITICAL,
        title="Wireless is disconnected",
        detail="adapter up, radio on, not associated",
        facts={
            "last_connected_profile": "HomeNet",
            "last_connected_ssid": "HomeNet",
            "profile_is_saved": True,
            "seconds_since_connected": 8,
            "adapter_status": "Up",
        },
        detector="test",
    )


@pytest.fixture
def thermal_symptom() -> Symptom:
    """Sustained throttling with no process to blame -- the cooling case."""
    return Symptom(
        code="THERMAL.SUSTAINED_THROTTLE",
        severity=Severity.CRITICAL,
        title="The processor is being held well below its rated speed",
        detail="45s at 98% busy delivering 61% of rated clock",
        facts={
            "window_s": 45.0,
            "mean_load_pct": 98.0,
            "mean_performance_pct": 61.0,
            "min_performance_pct": 55.0,
            "max_temperature_c": 96.0,
            "temperature_available": True,
            "busiest_process": "chrome.exe",
            "busiest_process_pct": 12.0,
            "explained_by_running_software": False,
            "cooling_suspect": True,
        },
        detector="test",
    )
