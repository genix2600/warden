"""Getting the clock back under a time server's control.

``w32tm /resync`` on its own fails silently on a machine whose time service is
not running, which is a common state -- W32Time ships with start type Manual and
nothing necessarily starts it. So the action starts the service, re-registers the
configuration if needed, and then resyncs, in one command whose parts are all
idempotent.
"""

from __future__ import annotations

from warden.contracts import PredicateRef, RiskTier, VerifySpec
from warden.playbooks.base import NoParams, Playbook

TIME_RESYNC = Playbook(
    id="time.resync",
    title="Synchronise the clock with a time server",
    summary=(
        "Starts the Windows time service if it is not running and forces an immediate "
        "synchronisation against the configured time server."
    ),
    when_to_use=(
        "The clock is free-running on the hardware clock with no successful "
        "synchronisation, so it will drift until certificate checks start failing."
    ),
    risk=RiskTier.REVERSIBLE,
    params_model=NoParams,
    argv_template=[
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        # Each step is safe to repeat. -ErrorAction on the resync is deliberately
        # left permissive: the verifier decides whether it worked by re-reading
        # the clock's source, not by trusting this command's own report.
        "Start-Service W32Time -ErrorAction SilentlyContinue; "
        "w32tm /resync /force 2>&1 | Out-String",
    ],
    expected_effect=(
        "The clock is corrected against a time server, usually within a few seconds. "
        "If it was significantly wrong, expect the displayed time to jump."
    ),
    verify=VerifySpec(
        probes=["sys.time"],
        predicate=PredicateRef(
            id="time.synchronised",
            describe="Re-read the clock's source and confirm it is no longer free-running.",
        ),
        # Reaching an NTP server and completing the exchange can take a few
        # rounds, so this gets a longer window than most.
        timeout_s=45.0,
        settle_s=3.0,
        poll_interval_s=4.0,
    ),
    est_duration_s=15.0,
    requires_admin=True,
    requires_network=True,
    note=("Corrects the clock only. No time zone, locale or scheduled task is touched."),
    tags=("time",),
)

TIME_PLAYBOOKS = [TIME_RESYNC]
