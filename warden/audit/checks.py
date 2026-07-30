"""The three checks the audit ships with.

Chosen because each one is a common factory or installer default, invisible in
every consumer tool, and measurable. Nothing here is a guess about what "feels
faster".
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
from warden.store import ObservationStore, as_dict, as_list

#: Below this, a machine waiting to restart is just a machine that has been on
#: for a while. Beyond it, the pending update is not being applied, and the user
#: has no way to know: Windows stops prompting long before this.
_REBOOT_PENDING_DAYS = 3.0


class WifiPowerSavingCheck(Check):
    """The highest-value check in the audit, and the reason it exists.

    Windows is allowed, by default on a great many laptops, to power down the
    wireless adapter to save energy. The symptom is an intermittent "can't
    connect to this network" that fixes itself, appears unrelated to anything,
    and is blamed on the router. Warden already demonstrates *repairing* that
    disconnection. This check names the cause instead.
    """

    id = "wifi.power_saving"
    domain_id = "network"
    title = "Windows is allowed to switch off your Wi-Fi adapter to save power"
    metric = MetricSpec(
        metric_id="wifi.disconnects_per_hour",
        label="Unexpected wireless disconnections per hour",
        unit="disconnections per hour",
        direction=MetricDirection.LOWER_IS_BETTER,
        read_via=PredicateRef(
            id="wifi.associated",
            describe=(
                "Counted from the association state Warden already samples every "
                "two seconds, not from a vendor claim."
            ),
        ),
        rationale_source=(
            "Microsoft documents adapter power management as a cause of "
            "intermittent disconnection; the disconnection count is measured on "
            "this machine."
        ),
    )

    def run(self, store: ObservationStore) -> CheckResult:
        observation = store.latest("audit.wifi.power_management")
        if observation is None:
            return self.unreadable("The adapter's power settings have not been read yet.")

        adapters = [as_dict(row) for row in as_list(observation.value)]
        if not adapters:
            return self.not_applicable("This machine has no wireless adapter.")

        # None means the driver does not expose the setting. That is neither on
        # nor off, and must not be reported as either.
        saving = [a for a in adapters if a.get("power_saving") is True]
        unknown = [a for a in adapters if a.get("power_saving") is None]

        if saving:
            names = ", ".join(str(a.get("name")) for a in saving)
            return self.result(
                CheckStatus.SUBOPTIMAL,
                observed="Windows may power down the adapter",
                expected="The adapter stays powered",
                detail=(
                    f"{names} is set to let Windows turn it off to save power. On "
                    "battery this is a common cause of wireless dropping for a few "
                    "seconds at a time and then coming back, which usually gets "
                    "blamed on the router."
                ),
                evidence=[observation],
            )
        if unknown and len(unknown) == len(adapters):
            return self.unreadable("This adapter's driver does not report the setting.")
        return self.result(
            CheckStatus.OPTIMAL,
            observed="The adapter stays powered",
            detail="Windows is not allowed to power down the wireless adapter.",
            evidence=[observation],
        )


class RebootPendingCheck(Check):
    """A restart that has been owed for weeks, which nothing tells the user about.

    Windows prompts for a few days and then stops. The update is downloaded and
    staged but not applied, so the machine is neither patched nor complaining.
    """

    id = "servicing.reboot_pending"
    domain_id = "updates"
    title = "Windows has been waiting to finish an update"
    metric = MetricSpec(
        metric_id="servicing.days_pending",
        label="Days the machine has been waiting to restart",
        unit="days",
        direction=MetricDirection.LOWER_IS_BETTER,
        read_via=PredicateRef(
            id="report.only",
            describe=(
                "Uptime since last boot, against the three registry flags Windows "
                "sets when a restart is owed."
            ),
        ),
        rationale_source=(
            "Windows stops prompting after a few days; three days is where a "
            "pending restart changes from normal to overlooked."
        ),
    )

    def run(self, store: ObservationStore) -> CheckResult:
        observation = store.latest("audit.servicing.reboot_pending")
        if observation is None:
            return self.unreadable("The servicing state has not been read yet.")

        state = as_dict(observation.value)
        flags = [
            name
            for name in ("servicing", "windows_update", "file_renames")
            if bool(state.get(name))
        ]
        if not flags:
            return self.result(
                CheckStatus.OPTIMAL,
                observed="No restart owed",
                detail="Nothing is waiting on a restart.",
                evidence=[observation],
            )

        days = _days_since(state.get("last_boot"))
        if days is None:
            waited = "an unknown time"
        elif days < 1:
            waited = "less than a day"
        else:
            waited = f"{days:.0f} day{'s' if days >= 2 else ''}"
        status = (
            CheckStatus.SUBOPTIMAL
            if days is None or days >= _REBOOT_PENDING_DAYS
            else CheckStatus.OPTIMAL
        )
        detail = (
            f"An update is staged and waiting for a restart, and has been for {waited}. "
            "Until the machine restarts the update is not actually applied, and "
            "Windows stops reminding you after the first few days."
        )
        if status is CheckStatus.OPTIMAL:
            detail = (
                f"A restart is owed, but only for {waited}. That is normal; Windows "
                "will prompt. Worth knowing, not worth acting on yet."
            )
        return self.result(
            status,
            observed=f"restart pending ({', '.join(flags)})",
            expected="no restart owed",
            detail=detail,
            evidence=[observation],
        )


class DefragOnSsdCheck(Check):
    """Scheduled defragmentation against a solid-state drive.

    Deliberately careful. Modern Windows already sends TRIM rather than a true
    defragmentation pass to an SSD, so the schedule existing is usually correct
    and reporting it as a fault would be scaremongering. The check therefore
    reads the drive type first and stays quiet unless there is a real mismatch.

    It is also the honest example of the measurement rule biting: write
    amplification is not directly readable, so this check reports the mechanism
    and does not claim a number it cannot produce.
    """

    id = "storage.defrag_on_ssd"
    domain_id = "storage"
    title = "Scheduled drive optimisation"
    metric = MetricSpec(
        metric_id="storage.defrag_schedule_correct",
        label="Whether the scheduled optimisation matches the drive type",
        unit="correct or mismatched",
        direction=MetricDirection.TARGET_VALUE,
        read_via=PredicateRef(
            id="report.only",
            describe="The scheduled task's state, against the drive's reported media type.",
        ),
        rationale_source=(
            "Microsoft documents that Windows sends TRIM rather than "
            "defragmenting solid-state drives on this schedule."
        ),
    )

    def run(self, store: ObservationStore) -> CheckResult:
        schedule = store.latest("audit.defrag.schedule")
        disks_observation = store.latest("hw.storage.disks")
        if schedule is None or disks_observation is None:
            return self.unreadable("The drive list or the optimisation schedule is not read yet.")

        disks = [as_dict(row) for row in as_list(disks_observation.value)]
        if not disks:
            return self.unreadable("No physical drives were reported.")

        media = {str(d.get("media_type") or "").upper() for d in disks}
        has_mechanical = "HDD" in media
        schedule_state = as_dict(schedule.value)

        if not schedule_state.get("present"):
            if has_mechanical:
                return self.result(
                    CheckStatus.SUBOPTIMAL,
                    observed="no scheduled optimisation",
                    expected="scheduled optimisation enabled",
                    detail=(
                        "This machine has a mechanical drive and no optimisation is "
                        "scheduled. Mechanical drives genuinely do slow down without it."
                    ),
                    evidence=[schedule, disks_observation],
                )
            return self.not_applicable(
                "No optimisation is scheduled, and every drive here is solid-state, "
                "which does not need one."
            )

        if has_mechanical:
            return self.result(
                CheckStatus.OPTIMAL,
                observed="scheduled and appropriate",
                detail="Optimisation is scheduled, and this machine has a drive that benefits.",
                evidence=[schedule, disks_observation],
            )
        return self.result(
            CheckStatus.OPTIMAL,
            observed="scheduled, and correct for solid-state",
            detail=(
                "Optimisation is scheduled. Every drive here is solid-state, and on "
                "those Windows sends a TRIM command rather than defragmenting, so "
                "the schedule is doing the right thing. Tools that tell you to "
                "disable this are describing Windows 7."
            ),
            evidence=[schedule, disks_observation],
        )


def _days_since(iso: object) -> float | None:
    if not isinstance(iso, str):
        return None
    try:
        moment = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if moment.tzinfo is None:
        return None
    return max(0.0, (utcnow() - moment).total_seconds() / 86400.0)
