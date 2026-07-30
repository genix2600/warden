"""Checks on settings that were configured once and never looked at again.

Separate from :mod:`warden.audit.checks`, which holds the three that shade into
fault territory (a stopped adapter, a pending restart, a wrong defrag schedule).
The ones here are pure configuration: a processor ceiling, a power plan, a
startup list, disk space that nobody has handed back.

Two of them are deliberately ``INTENT_DEPENDENT`` and offer no fix at all. That
is the honest answer for a setting whose correct value depends on what the user
wants from the machine, and it is the part of this subsystem that most clearly
separates it from a PC optimiser.
"""

from __future__ import annotations

from datetime import datetime

from warden.audit.base import Check
from warden.contracts import (
    CheckResult,
    CheckStatus,
    MetricDirection,
    MetricSpec,
    PredicateRef,
    utcnow,
)
from warden.store import ObservationStore, as_dict, as_float, as_list

#: Device classes where a stale driver is worth acting on, because the vendor
#: actually ships updates for them.
#:
#: Excluding the chipset classes is correctness, not tidiness. This machine
#: reports Intel SMBus, SPI and LPC controller drivers dated 1968-07-18, which is
#: a sentinel rather than a date: they are inbox stubs, no newer driver exists,
#: and nothing is wrong. A check keyed on "the oldest driver on the machine"
#: would lead with those forever and be useless every single time.
_DRIVER_CLASSES = frozenset({"display", "net", "bluetooth", "media", "image"})

#: Any date before this is treated as absent rather than ancient, for the same
#: reason. Nothing shipped a real Windows driver in 1968.
_EARLIEST_PLAUSIBLE_YEAR = 2000

#: Two years. Long enough that a maintained driver will have moved on, short
#: enough that an abandoned one shows up. Graphics and wireless vendors publish
#: several times a year.
_DRIVER_STALE_DAYS = 730.0

#: Below this there is nothing worth anyone's attention. A few hundred megabytes
#: of temporary files is how Windows works, not a problem to be sold a fix for.
_RECLAIMABLE_MB = 1024.0

#: Above this the startup list is worth reading. Not a fault: Warden has no idea
#: which of them the user wants.
_STARTUP_BUSY = 8


class DriverAgeCheck(Check):
    """Drivers a vendor has not touched in years.

    Reports and routes, never installs. Fetching a driver is between the user and
    their hardware vendor: Warden cannot verify that an arbitrary download is the
    right binary for this device, and a tool that installs unverifiable binaries
    has given up the only thing that makes it worth trusting.
    """

    id = "devices.driver_age"
    domain_id = "devices"
    title = "Driver age"
    metric = MetricSpec(
        metric_id="devices.oldest_driver_days",
        label="Age of the oldest driver that still receives updates",
        unit="days",
        direction=MetricDirection.LOWER_IS_BETTER,
        read_via=PredicateRef(
            id="report.only",
            describe="Driver dates from Win32_PnPSignedDriver, excluding Microsoft's own.",
        ),
        rationale_source=(
            "Graphics and wireless vendors ship several updates a year, so two "
            "years without one suggests the device has been dropped."
        ),
    )

    def run(self, store: ObservationStore) -> CheckResult:
        observation = store.latest("audit.drivers")
        if observation is None:
            return self.unreadable("The driver list has not been read yet.")

        candidates: list[tuple[float, dict[str, object]]] = []
        for raw in as_list(observation.value):
            driver = as_dict(raw)
            if str(driver.get("device_class") or "").lower() not in _DRIVER_CLASSES:
                continue
            age = _days_since(driver.get("driver_date"))
            if age is not None:
                candidates.append((age, dict(driver)))

        if not candidates:
            return self.not_applicable(
                "No drivers on this machine come from a vendor that publishes updates."
            )

        candidates.sort(key=lambda pair: pair[0], reverse=True)
        age, oldest = candidates[0]
        stale = [pair for pair in candidates if pair[0] >= _DRIVER_STALE_DAYS]
        years = age / 365.25

        if not stale:
            return self.result(
                CheckStatus.OPTIMAL,
                observed=f"{years:.1f} years",
                detail=(
                    f"The oldest driver that still receives updates is "
                    f"{oldest.get('name')}, from {years:.1f} years ago. Nothing "
                    "here looks abandoned."
                ),
                evidence=[observation],
            )

        names = ", ".join(str(driver.get("name")) for _, driver in stale[:2])
        plural = "s" if len(stale) != 1 else ""
        return self.result(
            CheckStatus.SUBOPTIMAL,
            observed=f"{years:.1f} years",
            expected="under two years",
            detail=(
                f"{len(stale)} driver{plural} have gone more than two years without "
                f"an update, the oldest by {years:.1f} years: {names}. Warden will "
                "not download drivers for you. Get them from the vendor "
                f"({oldest.get('provider')}) or through Windows Update."
            ),
            evidence=[observation],
        )


class ProcessorCapCheck(Check):
    """A processor ceiling below 100% while plugged in.

    The classic invisible slowdown. Something set the maximum processor state to
    a fraction, the machine has run at that fraction ever since, and nothing in
    Windows surfaces it anywhere a normal person would look.
    """

    id = "performance.processor_cap"
    domain_id = "performance"
    title = "Processor speed limit"
    metric = MetricSpec(
        metric_id="performance.ac_max_pct",
        label="Maximum processor state allowed on mains power",
        unit="percent",
        direction=MetricDirection.HIGHER_IS_BETTER,
        read_via=PredicateRef(
            id="report.only",
            describe="powercfg /q SCHEME_CURRENT SUB_PROCESSOR PROCTHROTTLEMAX, AC setting.",
        ),
        rationale_source=(
            "100 is the Windows default on every shipped power plan, so anything "
            "lower was set by a person or by another program."
        ),
    )

    def run(self, store: ObservationStore) -> CheckResult:
        observation = store.latest("audit.power.profile")
        if observation is None:
            return self.unreadable("The power profile has not been read yet.")

        ceiling = as_float(as_dict(observation.value).get("ac_max_pct"))
        if ceiling is None:
            return self.unreadable("Windows did not report a processor ceiling.")

        if ceiling >= 100:
            return self.result(
                CheckStatus.OPTIMAL,
                observed="100%",
                detail="The processor is allowed its full speed on mains power.",
                evidence=[observation],
            )
        return self.result(
            CheckStatus.SUBOPTIMAL,
            observed=f"{ceiling:.0f}%",
            expected="100%",
            detail=(
                f"The processor is capped at {ceiling:.0f}% of its speed while "
                "plugged in, so this machine has been running at a fraction of what "
                "it can do. Nothing in Windows shows this, and it is usually left "
                "behind by a battery-saving tool or a manufacturer utility."
            ),
            evidence=[observation],
        )


class PowerPlanCheck(Check):
    """Which power plan is active, where there is no correct answer.

    A laptop limiting its processor on battery is either someone stretching a
    charge through a flight or someone who has run at half speed for a year
    without knowing. Warden cannot tell those apart, so it presents the reading
    and recommends nothing.
    """

    id = "performance.power_plan"
    domain_id = "performance"
    title = "Power plan"
    metric = MetricSpec(
        metric_id="performance.dc_max_pct",
        label="Maximum processor state allowed on battery",
        unit="percent",
        direction=MetricDirection.TARGET_VALUE,
        read_via=PredicateRef(
            id="report.only",
            describe="powercfg /getactivescheme, with the battery processor ceiling.",
        ),
        rationale_source=(
            "No published threshold exists, because the correct value depends "
            "entirely on what the owner wants from the machine."
        ),
    )

    def run(self, store: ObservationStore) -> CheckResult:
        observation = store.latest("audit.power.profile")
        if observation is None:
            return self.unreadable("The power profile has not been read yet.")

        profile = as_dict(observation.value)
        scheme = str(profile.get("scheme") or "unknown")
        on_battery = as_float(profile.get("dc_max_pct"))

        if not bool(profile.get("is_portable")):
            return self.not_applicable(
                f"This is a desktop, running the {scheme} plan. There is no battery "
                "life to trade against speed."
            )
        if on_battery is not None and on_battery < 100:
            return self.result(
                CheckStatus.INTENT_DEPENDENT,
                observed=f"{scheme}, {on_battery:.0f}% on battery",
                detail=(
                    f"On battery this machine limits the processor to "
                    f"{on_battery:.0f}%. That is the right choice if you are "
                    "stretching a charge and the wrong one if you did not know it "
                    "was happening. Warden has no way to tell which, so it will not "
                    "change it for you."
                ),
                evidence=[observation],
            )
        return self.result(
            CheckStatus.OPTIMAL,
            observed=f"{scheme}, full speed on battery",
            detail=f"Running the {scheme} plan with no processor limit on battery.",
            evidence=[observation],
        )


class StartupLoadCheck(Check):
    """How many programs start with Windows. Counted, never judged.

    Warden does not know that somebody wants their backup client to stop
    launching. Disabling startup items in bulk to claim a faster boot is exactly
    the behaviour this subsystem exists not to repeat.
    """

    id = "performance.startup_load"
    domain_id = "performance"
    title = "Programs that start with Windows"
    metric = MetricSpec(
        metric_id="performance.startup_count",
        label="Programs launching at sign-in",
        unit="programs",
        direction=MetricDirection.LOWER_IS_BETTER,
        read_via=PredicateRef(
            id="report.only",
            describe="Run keys under HKLM and HKCU, plus both Startup folders.",
        ),
        rationale_source=(
            "No documented threshold exists. Eight is where the list stops fitting "
            "on one screen and starts being worth reading."
        ),
    )

    def run(self, store: ObservationStore) -> CheckResult:
        observation = store.latest("audit.startup")
        if observation is None:
            return self.unreadable("The startup list has not been read yet.")

        startup = as_dict(observation.value)
        count = int(as_float(startup.get("count")) or 0)
        names = [str(name) for name in as_list(startup.get("run_keys"))][:4]

        if count <= _STARTUP_BUSY:
            return self.result(
                CheckStatus.OPTIMAL,
                observed=f"{count} programs",
                detail=f"{count} programs start with Windows, which is unremarkable.",
                evidence=[observation],
            )
        return self.result(
            CheckStatus.INTENT_DEPENDENT,
            observed=f"{count} programs",
            detail=(
                f"{count} programs start with Windows, including "
                f"{', '.join(names)}. Some of those you want and some you have "
                "probably forgotten about. Warden will not guess which, and it will "
                "not disable them in bulk to claim a faster boot."
            ),
            evidence=[observation],
        )


class ReclaimableSpaceCheck(Check):
    """Disk space sitting in directories whose only job is discardable files."""

    id = "storage.reclaimable"
    domain_id = "storage"
    title = "Space that can be handed back"
    metric = MetricSpec(
        metric_id="storage.reclaimable_mb",
        label="Space held in temporary and update-cache directories",
        unit="MB",
        direction=MetricDirection.LOWER_IS_BETTER,
        read_via=PredicateRef(
            id="report.only",
            describe="Measured directly from %TEMP%, Windows\\Temp and the update cache.",
        ),
        rationale_source=(
            "Measured on this machine. A few hundred megabytes is how Windows "
            "works; a gigabyte is worth mentioning."
        ),
    )

    def run(self, store: ObservationStore) -> CheckResult:
        observation = store.latest("audit.storage.reclaimable")
        if observation is None:
            return self.unreadable("Temporary directories have not been measured yet.")

        megabytes = as_float(as_dict(observation.value).get("reclaimable_mb"))
        if megabytes is None:
            return self.unreadable("The measurement did not return a number.")

        if megabytes < _RECLAIMABLE_MB:
            return self.result(
                CheckStatus.OPTIMAL,
                observed=f"{megabytes:.0f} MB",
                detail=(
                    f"{megabytes:.0f} MB of temporary files, which is normal and not "
                    "worth acting on."
                ),
                evidence=[observation],
            )
        return self.result(
            CheckStatus.SUBOPTIMAL,
            observed=f"{megabytes / 1024:.1f} GB",
            expected="under 1 GB",
            detail=(
                f"{megabytes / 1024:.1f} GB is sitting in temporary and update-cache "
                "directories. Those exist to hold files that can be thrown away, and "
                "Warden measured the number rather than estimating it."
            ),
            evidence=[observation],
        )


class StorageSenseCheck(Check):
    """Whether Windows already clears temporary files on its own.

    The measurable one, and the better fix. Storage Sense on means reclaimable
    space stops growing without anybody thinking about it, which beats a person
    running a cleanup tool every few months and calling that maintenance.
    """

    id = "storage.storage_sense"
    domain_id = "storage"
    title = "Automatic cleanup"
    metric = MetricSpec(
        metric_id="storage.reclaimable_mb",
        label="Space held in temporary and update-cache directories",
        unit="MB",
        direction=MetricDirection.LOWER_IS_BETTER,
        read_via=PredicateRef(
            id="report.only",
            describe="The same measurement, re-read after Storage Sense has run.",
        ),
        rationale_source=(
            "Microsoft ships Storage Sense for exactly this, and it is off by "
            "default on many installations."
        ),
    )

    def run(self, store: ObservationStore) -> CheckResult:
        observation = store.latest("audit.storage.reclaimable")
        if observation is None:
            return self.unreadable("Storage Sense has not been read yet.")

        data = as_dict(observation.value)
        if bool(data.get("storage_sense_on")):
            return self.result(
                CheckStatus.OPTIMAL,
                observed="on",
                detail=(
                    "Windows clears temporary files on its own, so this stays tidy "
                    "without anybody remembering to do it."
                ),
                evidence=[observation],
            )
        megabytes = as_float(data.get("reclaimable_mb")) or 0.0
        return self.result(
            CheckStatus.SUBOPTIMAL,
            observed="off",
            expected="on",
            detail=(
                "Storage Sense is switched off, so temporary files accumulate until "
                f"somebody clears them. There is {megabytes:.0f} MB of that now. "
                "Turning it on is the difference between fixing this once and it "
                "staying fixed."
            ),
            evidence=[observation],
        )


def _days_since(iso: object) -> float | None:
    """Age in days, or None if the date is missing or implausible.

    Implausible matters. Inbox driver stubs carry sentinel dates in 1968, and
    treating one as a fifty-year-old driver would produce advice nobody can act
    on about hardware that is working perfectly.
    """
    if not isinstance(iso, str):
        return None
    try:
        moment = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if moment.tzinfo is None or moment.year < _EARLIEST_PLAUSIBLE_YEAR:
        return None
    return max(0.0, (utcnow() - moment).total_seconds() / 86400.0)
