"""A clock that is not being corrected by anything.

This detector reports a *cause*, not a symptom the user has noticed. Nobody
files a complaint saying "my clock is unsynchronised" -- they say secure sites
will not load, or their password stopped working, or Office wants activating
again. All of those are certificate validity checks failing against a clock that
has quietly drifted.

The finding is deliberately not "the time is wrong". A free-running clock can be
seconds out today and twenty minutes out in three months, and the moment it
crosses the tolerance every TLS handshake on the machine starts failing at once.
Reporting the condition rather than waiting for the consequence is the entire
value here.
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
                severity=Severity.WARN,
                title="The clock is not being corrected by any time server",
                detail=(
                    f"Windows reports the time source as {sync.get('source')!r} with "
                    f"last successful sync {sync.get('last_sync')!r}"
                    + (
                        f", and its configured server {pending[0].get('peer')!r} has never "
                        f"answered."
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
