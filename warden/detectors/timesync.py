"""A clock that is not being corrected by anything.

This detector reports a *cause*, not a symptom the user has noticed. Nobody
files a complaint saying "my clock is unsynchronised" -- they say secure sites
will not load, or their password stopped working, or Office wants activating
again. All of those are certificate validity checks failing against a clock that
has quietly drifted.

The finding is deliberately not "the time is wrong", and that is also why it is
only INFO. A free-running clock is usually correct today and wrong in three
months, so calling it a fault while the clock still reads right is a false alarm:
the user checks, sees the right time, and learns to ignore Warden.

Warden cannot measure how wrong the clock is, either. w32tm reports a phase
offset of zero on a machine that has never reached a server, because there is
nothing to compare against -- a zero here means "no idea", not "accurate". With
no way to quantify the error, claiming there is one would be inventing a number,
so this reports the condition at the severity the condition deserves and leaves
the decision with the user.

Worth knowing because the failure, when it arrives, is baffling: secure sites
stop loading and sign-ins start failing, all at once, and nothing points at the
clock.
"""

from __future__ import annotations

from warden.contracts import Severity, Symptom
from warden.detectors.base import Detector
from warden.store import ObservationStore, as_dict, as_list


class TimeSyncDetector(Detector):
    id = "sys.time"
    raises = ("TIME.NOT_SYNCHRONISED",)

    def evaluate(self, store: ObservationStore) -> list[Symptom]:
        observation = store.latest("sys.time.sync")
        if observation is None:
            return []
        sync = as_dict(observation.value)

        # Any one of the three is sufficient. Machines report this state in
        # different combinations depending on how they got into it, and
        # requiring all three would quietly miss most of them.
        free_running = bool(sync.get("free_running"))
        never_synced = bool(sync.get("never_synced"))
        not_synchronized = bool(sync.get("not_synchronized"))
        if not (free_running or never_synced or not_synchronized):
            return []

        peers = [as_dict(raw) for raw in as_list(store.value("sys.time.peers"))]
        pending = [p for p in peers if str(p.get("state", "")).lower() == "pending"]

        return [
            self.symptom(
                "TIME.NOT_SYNCHRONISED",
                # INFO, not WARN. The clock is very likely right at this moment;
                # what is wrong is that nothing is keeping it right.
                severity=Severity.INFO,
                title="Nothing is keeping this clock accurate",
                detail=(
                    "The time is probably correct right now. It is running off the "
                    "motherboard clock rather than being corrected by a time server, "
                    "so it will drift, and a clock a few minutes out breaks secure "
                    "websites and sign-ins in ways that never look like a clock "
                    f"problem. Windows reports the source as {sync.get('source')!r}, "
                    f"last successful sync {sync.get('last_sync')!r}"
                    + (
                        f", and {pending[0].get('peer')!r} has never answered, which "
                        "usually means a firewall is blocking it rather than anything "
                        "being broken here."
                        if pending
                        else "."
                    )
                ),
                facts={
                    "source": sync.get("source"),
                    "last_sync": sync.get("last_sync"),
                    "leap_indicator": sync.get("leap_indicator"),
                    "stratum": sync.get("stratum"),
                    "never_synced": never_synced,
                    "free_running": free_running,
                    "configured_peers": [p.get("peer") for p in peers],
                    "pending_peers": [p.get("peer") for p in pending],
                    # What actually goes wrong, so the explanation can lead with
                    # the consequence rather than with the mechanism.
                    "consequences": (
                        "secure websites failing to load, sign-ins being rejected, "
                        "Office asking to be reactivated, and Windows Update erroring"
                    ),
                },
                evidence=[observation, store.latest("sys.time.peers")],
            )
        ]
