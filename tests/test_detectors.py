"""Detectors, driven entirely by hand-built observations.

No Windows, no hardware, no elevation -- which is the whole reason collectors
and detectors are separate layers.
"""

from __future__ import annotations

from warden.contracts import ObservationKind, Severity
from warden.detectors import DetectorBank
from warden.detectors.network import ReachabilityDetector, WifiLinkDetector
from warden.detectors.thermal import ThermalThrottleDetector
from warden.store import ObservationStore

from .conftest import make_observation


class TestWifiLink:
    def test_a_healthy_link_raises_nothing(self, connected_store: ObservationStore) -> None:
        assert WifiLinkDetector().evaluate(connected_store) == []

    def test_a_sustained_drop_is_reported(self, disconnected_store: ObservationStore) -> None:
        symptoms = WifiLinkDetector().evaluate(disconnected_store)
        assert [s.code for s in symptoms] == ["NET.WIFI.DISCONNECTED"]
        assert symptoms[0].severity is Severity.CRITICAL

    def test_the_last_used_profile_comes_from_warden_s_own_history(
        self, disconnected_store: ObservationStore
    ) -> None:
        """Not from the saved-profile list, which is localised and often stale."""
        facts = WifiLinkDetector().evaluate(disconnected_store)[0].facts
        assert facts["last_connected_profile"] == "HomeNet"
        assert facts["profile_is_saved"] is True

    def test_a_single_bad_sample_is_ignored(self, connected_store: ObservationStore) -> None:
        """Roaming between access points must not raise an incident."""
        connected_store.ingest(
            [make_observation("net.wifi.link", {"state": "disconnected", "radio": "on"})]
        )
        assert WifiLinkDetector().evaluate(connected_store) == []

    def test_a_radio_switched_off_is_a_different_symptom(
        self, connected_store: ObservationStore
    ) -> None:
        """And one with no software fix, which is why it must not be conflated
        with an ordinary disconnection."""
        connected_store.ingest(
            [
                make_observation(
                    "net.wifi.link",
                    {"state": "disconnected", "radio": "Hardware Off", "ssid": None},
                )
            ]
        )
        symptoms = WifiLinkDetector().evaluate(connected_store)
        assert [s.code for s in symptoms] == ["NET.WIFI.RADIO_OFF"]
        assert symptoms[0].facts["hardware_switch"] is True

    def test_a_missing_adapter_is_reported_as_hardware(self, store: ObservationStore) -> None:
        store.ingest(
            [
                make_observation("net.wifi.adapter", {"present": False}),
                make_observation("net.wifi.link", {"state": "no_adapter", "radio": "unknown"}),
            ]
        )
        assert [s.code for s in WifiLinkDetector().evaluate(store)] == ["NET.WIFI.NO_ADAPTER"]


class TestReachability:
    def test_it_stays_quiet_when_the_link_itself_is_down(
        self, disconnected_store: ObservationStore
    ) -> None:
        """Root-cause suppression: reporting "no internet" on top of "no wireless"
        buries the finding that matters."""
        assert ReachabilityDetector().evaluate(disconnected_store) == []

    def test_a_reachable_gateway_with_no_internet_is_an_upstream_fault(
        self, connected_store: ObservationStore
    ) -> None:
        for _ in range(2):
            connected_store.ingest([make_observation("net.connectivity.internet", False)])
        symptoms = ReachabilityDetector().evaluate(connected_store)
        assert [s.code for s in symptoms] == ["NET.INTERNET.UNREACHABLE"]
        assert symptoms[0].facts["fault_is_upstream"] is True

    def test_an_unreachable_gateway_is_a_local_fault(
        self, connected_store: ObservationStore
    ) -> None:
        for _ in range(2):
            connected_store.ingest(
                [
                    make_observation("net.connectivity.internet", False),
                    make_observation(
                        "net.connectivity.gateway", {"address": "192.168.1.1", "reachable": False}
                    ),
                ]
            )
        assert [s.code for s in ReachabilityDetector().evaluate(connected_store)] == [
            "NET.GATEWAY.UNREACHABLE"
        ]

    def test_working_routing_with_broken_names_is_dns(
        self, connected_store: ObservationStore
    ) -> None:
        for _ in range(2):
            connected_store.ingest(
                [
                    make_observation("net.connectivity.internet", True),
                    make_observation(
                        "net.connectivity.dns", {"resolves": False, "host": "example.test"}
                    ),
                ]
            )
        assert [s.code for s in ReachabilityDetector().evaluate(connected_store)] == [
            "NET.DNS.FAILURE"
        ]


class TestThermal:
    def _load(self, store: ObservationStore, busy: float, performance: float, n: int = 8) -> None:
        for _ in range(n):
            store.ingest(
                [
                    make_observation("cpu.busy_pct", busy, ObservationKind.METRIC, "%"),
                    make_observation(
                        "cpu.performance_pct", performance, ObservationKind.METRIC, "%"
                    ),
                ]
            )

    def test_a_healthy_machine_under_load_raises_nothing(self, store: ObservationStore) -> None:
        """Measured behaviour of a working laptop: 100% busy, ~90% delivered.

        This is the case that matters most. The temptation when building a demo
        is to lower the threshold until something fires; this test pins the
        machine's real numbers so that cannot happen quietly.
        """
        self._load(store, busy=100.0, performance=90.6)
        assert ThermalThrottleDetector().evaluate(store) == []

    def test_idle_with_low_clocks_raises_nothing(self, store: ObservationStore) -> None:
        """A processor idling down is not a processor being held back."""
        self._load(store, busy=8.0, performance=45.0)
        assert ThermalThrottleDetector().evaluate(store) == []

    def test_sustained_load_with_collapsed_clocks_is_throttling(
        self, store: ObservationStore
    ) -> None:
        self._load(store, busy=98.0, performance=61.0)
        symptoms = ThermalThrottleDetector().evaluate(store)
        assert [s.code for s in symptoms] == ["THERMAL.SUSTAINED_THROTTLE"]
        assert symptoms[0].severity is Severity.CRITICAL
        assert symptoms[0].facts["cooling_suspect"] is True

    def test_a_runaway_process_is_distinguished_from_a_cooling_fault(
        self, store: ObservationStore
    ) -> None:
        """Same readings, different cause, completely different advice."""
        store.ingest(
            [
                make_observation(
                    "sys.top_processes",
                    [{"name": "handbrake.exe", "cpu_percent": 91.0, "pid": 1}],
                    ObservationKind.INVENTORY,
                )
            ]
        )
        self._load(store, busy=98.0, performance=61.0)
        facts = ThermalThrottleDetector().evaluate(store)[0].facts
        assert facts["explained_by_running_software"] is True
        assert facts["cooling_suspect"] is False

    def test_too_few_samples_concludes_nothing(self, store: ObservationStore) -> None:
        self._load(store, busy=100.0, performance=40.0, n=2)
        assert ThermalThrottleDetector().evaluate(store) == []

    def test_an_unprimed_process_sample_does_not_fake_a_cooling_fault(
        self, store: ObservationStore
    ) -> None:
        """psutil reports 0.0% for every process until it has two samples.

        If that unprimed reading reached the detector it would look like nothing
        is running, and a machine that is simply busy would be diagnosed as
        having failed cooling. `ProcessCollector.warmup()` primes the baseline;
        this pins the consequence of getting that wrong.
        """
        store.ingest(
            [
                make_observation(
                    "sys.top_processes",
                    [{"name": "handbrake.exe", "cpu_percent": 0.0, "pid": 1}],
                    ObservationKind.INVENTORY,
                )
            ]
        )
        self._load(store, busy=98.0, performance=61.0)
        facts = ThermalThrottleDetector().evaluate(store)[0].facts
        # With an unprimed sample the detector cannot see the busy process, so it
        # reaches the wrong conclusion. The fix lives in the collector; this test
        # documents why that fix is load-bearing rather than tidiness.
        assert facts["busiest_process_pct"] == 0.0
        assert facts["cooling_suspect"] is True, (
            "an all-zero process sample makes a busy machine look like a cooling fault"
        )


class TestDetectorBank:
    def test_a_symptom_is_raised_once_and_cleared_once(
        self, connected_store: ObservationStore
    ) -> None:
        bank = DetectorBank()
        raised, cleared = bank.evaluate(connected_store)
        assert raised == [] and cleared == []

        for _ in range(2):
            connected_store.ingest(
                [make_observation("net.wifi.link", {"state": "disconnected", "radio": "on"})]
            )
        raised, cleared = bank.evaluate(connected_store)
        assert [s.code for s in raised] == ["NET.WIFI.DISCONNECTED"]

        # Still present on the next tick: reported once, not every two seconds.
        raised, cleared = bank.evaluate(connected_store)
        assert raised == [] and cleared == []

        for _ in range(2):
            connected_store.ingest(
                [
                    make_observation(
                        "net.wifi.link",
                        {
                            "state": "connected",
                            "ssid": "HomeNet",
                            "profile": "HomeNet",
                            "radio": "on",
                            "signal_pct": 80,
                        },
                    )
                ]
            )
        raised, cleared = bank.evaluate(connected_store)
        assert cleared == ["NET.WIFI.DISCONNECTED"]
