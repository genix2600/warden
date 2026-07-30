"""The six configuration checks, and the false positives they were built to dodge.

Most of these tests exist because the obvious version of the check fires on a
perfectly healthy machine. Each one is a trap found by running the probe against
real hardware rather than by reasoning about it.
"""

from __future__ import annotations

from datetime import timedelta

from pydantic import JsonValue

from warden.audit import run_audit
from warden.audit.settings import (
    DriverAgeCheck,
    PowerPlanCheck,
    ProcessorCapCheck,
    ReclaimableSpaceCheck,
    StartupLoadCheck,
    StorageSenseCheck,
)
from warden.contracts import (
    CheckStatus,
    Mechanism,
    Observation,
    ObservationKind,
    Provenance,
    utcnow,
)
from warden.store import ObservationStore


def reading(source: str, value: JsonValue) -> Observation:
    return Observation(
        source=source,
        kind=ObservationKind.STATE,
        value=value,
        provenance=Provenance(probe="test", mechanism=Mechanism.CIM, elapsed_ms=1),
    )


def store_with(source: str, value: JsonValue) -> ObservationStore:
    store = ObservationStore()
    store.ingest([reading(source, value)])
    return store


def driver(name: str, klass: str, age_days: float, provider: str = "Intel") -> dict[str, object]:
    return {
        "name": name,
        "provider": provider,
        "device_class": klass,
        "driver_date": (utcnow() - timedelta(days=age_days)).isoformat(),
    }


class TestDriverAge:
    def test_chipset_stubs_dated_1968_are_ignored(self) -> None:
        """The trap this check was rebuilt around.

        A real machine reports Intel SMBus, SPI and LPC controller drivers dated
        1968-07-18. That is a sentinel, not a date: the drivers are inbox stubs,
        no newer version exists, and nothing is wrong. Leading with a fifty-year-
        old driver would be advice nobody can act on, forever.
        """
        store = store_with(
            "audit.drivers",
            [
                {
                    "name": "Intel(R) SMBus - A0A3",
                    "provider": "INTEL",
                    "device_class": "System",
                    "driver_date": "1968-07-18T00:00:00+00:00",
                },
                driver("Intel(R) Iris(R) Xe Graphics", "Display", 40),
            ],
        )
        result = DriverAgeCheck().run(store)
        assert result.status is CheckStatus.OPTIMAL
        assert "Iris" in result.detail, "it should report the newest real driver, not the stub"

    def test_microsoft_pseudo_devices_never_reach_the_check(self) -> None:
        """WAN Miniports are genuinely dated 2006 and correctly never change.

        They are filtered in the collector query, so an empty list here means
        the check has nothing to judge rather than a healthy machine.
        """
        store = store_with("audit.drivers", [])
        assert DriverAgeCheck().run(store).status is CheckStatus.NOT_APPLICABLE

    def test_a_genuinely_abandoned_driver_is_reported(self) -> None:
        store = store_with(
            "audit.drivers", [driver("Realtek Audio", "MEDIA", 1100, provider="Realtek")]
        )
        result = DriverAgeCheck().run(store)
        assert result.status is CheckStatus.SUBOPTIMAL
        assert "Realtek" in result.detail

    def test_it_refuses_to_install_anything(self) -> None:
        """Warden cannot verify an arbitrary driver download is right for a device."""
        store = store_with("audit.drivers", [driver("Old GPU", "Display", 1500, "NVIDIA")])
        assert "will not download" in DriverAgeCheck().run(store).detail

    def test_recent_drivers_are_left_alone(self) -> None:
        store = store_with("audit.drivers", [driver("Intel Wi-Fi 6 AX201", "Net", 70)])
        assert DriverAgeCheck().run(store).status is CheckStatus.OPTIMAL


class TestProcessorCap:
    def test_the_default_hundred_percent_is_not_a_finding(self) -> None:
        store = store_with(
            "audit.power.profile", {"ac_max_pct": 100, "dc_max_pct": 100, "is_portable": True}
        )
        assert ProcessorCapCheck().run(store).status is CheckStatus.OPTIMAL

    def test_a_capped_processor_on_mains_is_reported(self) -> None:
        store = store_with(
            "audit.power.profile", {"ac_max_pct": 50, "dc_max_pct": 50, "is_portable": False}
        )
        result = ProcessorCapCheck().run(store)
        assert result.status is CheckStatus.SUBOPTIMAL
        assert result.observed == "50%"


class TestPowerPlan:
    def test_a_desktop_has_no_battery_to_trade_against(self) -> None:
        store = store_with(
            "audit.power.profile",
            {"scheme": "Balanced", "ac_max_pct": 100, "dc_max_pct": 100, "is_portable": False},
        )
        assert PowerPlanCheck().run(store).status is CheckStatus.NOT_APPLICABLE

    def test_a_limited_laptop_is_the_user_s_call_and_gets_no_fix(self) -> None:
        """There is no correct answer, so Warden presents both costs and stops."""
        store = store_with(
            "audit.power.profile",
            {"scheme": "Power saver", "ac_max_pct": 100, "dc_max_pct": 50, "is_portable": True},
        )
        result = PowerPlanCheck().run(store)
        assert result.status is CheckStatus.INTENT_DEPENDENT
        assert "will not change it for you" in result.detail


class TestStartupLoad:
    def test_a_short_list_is_unremarkable(self) -> None:
        store = store_with("audit.startup", {"run_keys": ["OneDrive"], "count": 1})
        assert StartupLoadCheck().run(store).status is CheckStatus.OPTIMAL

    def test_a_long_list_is_counted_and_not_judged(self) -> None:
        store = store_with(
            "audit.startup",
            {"run_keys": [f"App{n}" for n in range(13)], "startup_folder": [], "count": 13},
        )
        result = StartupLoadCheck().run(store)
        assert result.status is CheckStatus.INTENT_DEPENDENT
        assert "will not guess which" in result.detail
        assert "in bulk" in result.detail


class TestStorage:
    def test_normal_temp_usage_is_not_a_problem_to_sell_a_fix_for(self) -> None:
        store = store_with(
            "audit.storage.reclaimable", {"reclaimable_mb": 300, "storage_sense_on": True}
        )
        assert ReclaimableSpaceCheck().run(store).status is CheckStatus.OPTIMAL

    def test_a_gigabyte_is_worth_mentioning(self) -> None:
        store = store_with(
            "audit.storage.reclaimable", {"reclaimable_mb": 2048, "storage_sense_on": True}
        )
        result = ReclaimableSpaceCheck().run(store)
        assert result.status is CheckStatus.SUBOPTIMAL
        assert result.observed == "2.0 GB"

    def test_storage_sense_off_is_the_better_finding(self) -> None:
        """Turning it on is the difference between fixing this once and it staying fixed."""
        store = store_with(
            "audit.storage.reclaimable", {"reclaimable_mb": 1026, "storage_sense_on": False}
        )
        result = StorageSenseCheck().run(store)
        assert result.status is CheckStatus.SUBOPTIMAL
        assert "staying fixed" in result.detail

    def test_storage_sense_on_needs_no_action(self) -> None:
        store = store_with(
            "audit.storage.reclaimable", {"reclaimable_mb": 5000, "storage_sense_on": True}
        )
        assert StorageSenseCheck().run(store).status is CheckStatus.OPTIMAL


class TestNothingReadYet:
    def test_every_check_reports_unreadable_rather_than_healthy(self) -> None:
        """An empty store must never look like a clean bill of health."""
        empty = ObservationStore()
        for check in (
            DriverAgeCheck(),
            ProcessorCapCheck(),
            PowerPlanCheck(),
            StartupLoadCheck(),
            ReclaimableSpaceCheck(),
            StorageSenseCheck(),
        ):
            assert check.run(empty).status is CheckStatus.COULD_NOT_READ, check.id


class TestFirstReadingPending:
    """The first minute after launch, which used to look like nine failures.

    ``sys.audit`` samples every 120 seconds and two of its probes are allowed
    30, so a Tune-up page opened immediately after launch reads an empty store.
    Every check correctly says ``could_not_read``, and the page correctly says
    nine collectors are broken, which is nine times wronger than the truth.
    """

    def test_empty_store_is_pending_rather_than_broken(self) -> None:
        report = run_audit(ObservationStore())
        assert report.first_reading_pending is True
        assert report.unreadable == len(report.results)

    def test_one_reading_is_enough_to_stop_making_excuses(self) -> None:
        """A collector that reported once is no longer given the benefit of
        the doubt, so a genuinely wedged probe still surfaces as unreadable."""
        store = store_with("audit.power.profile", {"scheme": "Balanced"})
        report = run_audit(store)
        assert report.first_reading_pending is False
        assert report.unreadable > 0  # the other probes did not report

    def test_a_populated_store_is_never_pending(self) -> None:
        store = ObservationStore()
        store.ingest(
            [
                reading("audit.drivers", {"drivers": []}),
                reading("audit.power.profile", {"scheme": "Balanced"}),
            ]
        )
        assert run_audit(store).first_reading_pending is False
