"""Whether the clock is actually synchronised, which almost nobody checks.

A drifting clock is one of the most misleading faults on a computer. It does not
present as "the time is wrong" -- the visible clock can look approximately
right while being minutes out. It presents as secure websites refusing to load,
logins failing, Office deactivating, and Windows Update erroring, because every
one of those depends on certificate validity windows that a skewed clock falls
outside of.

The development machine is a live example: ``Source: Local CMOS Clock``,
``Last Successful Sync Time: unspecified``, ``Leap Indicator: 3 (not
synchronized)``. It has never once reached a time server, and is running purely
on the motherboard battery clock. Nothing on the machine says so.
"""

from __future__ import annotations

from pydantic import JsonValue

from warden.collectors.base import Collector, num
from warden.collectors.psbridge import (
    PowerShellBridge,
    PowerShellError,
    PowerShellUnavailable,
)
from warden.contracts import Mechanism, ObservationKind, ProbeResult

#: What ``w32tm`` reports as its source when it has never synchronised with
#: anything and is free-running on the hardware clock.
LOCAL_CLOCK_SOURCES = ("local cmos clock", "free-running system clock")


def parse_w32tm_status(text: str) -> dict[str, str]:
    """``w32tm /query /status`` is colon-separated key/value lines.

    Values contain colons of their own -- times, and the ``3(not synchronized)``
    form of the leap indicator -- so the split is on the first colon only.
    """
    parsed: dict[str, str] = {}
    for raw in text.splitlines():
        if ":" not in raw:
            continue
        key, _, value = raw.partition(":")
        key = key.strip().lower()
        if key:
            parsed[key] = value.strip()
    return parsed


class TimeSyncCollector(Collector):
    id = "sys.time"
    interval_s = 60.0
    description = "Whether the system clock is synchronised with a time server, and how far off."

    def __init__(self, bridge: PowerShellBridge) -> None:
        self._ps = bridge

    def probe(self) -> ProbeResult:
        result = ProbeResult()
        script = "w32tm /query /status"
        try:
            text, ms = self._ps.run(f"{script} | Out-String", timeout=15.0)
        except (PowerShellError, PowerShellUnavailable) as exc:
            result.errors.append(self.failure(script, exc))
            return result

        status = parse_w32tm_status(text)
        source = status.get("source", "")
        leap = status.get("leap indicator", "")
        last_sync = status.get("last successful sync time", "")

        # Three independent signals that all mean "this clock is not being
        # corrected by anything". Any one of them is enough; requiring all three
        # would miss machines that report the state differently.
        never_synced = last_sync.lower() in {"unspecified", ""}
        free_running = any(marker in source.lower() for marker in LOCAL_CLOCK_SOURCES)
        not_synchronized = "not synchronized" in leap.lower()

        result.observations.append(
            self.observation(
                "sys.time.sync",
                ObservationKind.STATE,
                {
                    "source": source or None,
                    "leap_indicator": leap or None,
                    "last_sync": last_sync or None,
                    "stratum": status.get("stratum"),
                    "poll_interval": status.get("poll interval"),
                    "never_synced": never_synced,
                    "free_running": free_running,
                    "not_synchronized": not_synchronized,
                    # Present only once a sync has succeeded, so its absence is
                    # itself part of the finding rather than a gap.
                    "phase_offset": status.get("phase offset"),
                },
                probe=script,
                mechanism=Mechanism.NETCMDLET,
                elapsed_ms=ms,
            )
        )
        self._probe_peers(result)
        return result

    def _probe_peers(self, result: ProbeResult) -> None:
        """Which time servers are configured, and whether any has answered."""
        script = "w32tm /query /peers"
        try:
            text, ms = self._ps.run(f"{script} | Out-String", timeout=15.0)
        except (PowerShellError, PowerShellUnavailable) as exc:
            result.errors.append(self.failure(script, exc))
            return

        peers: list[dict[str, JsonValue]] = []
        current: dict[str, JsonValue] = {}
        for raw in text.splitlines():
            if ":" not in raw:
                continue
            key, _, value = raw.partition(":")
            key, value = key.strip().lower(), value.strip()
            if key == "peer":
                if current:
                    peers.append(current)
                current = {"peer": value}
            elif key == "state" and current:
                current["state"] = value
            elif key == "time remaining" and current:
                current["time_remaining_s"] = num(value.rstrip("s"))
        if current:
            peers.append(current)

        result.observations.append(
            self.observation(
                "sys.time.peers",
                ObservationKind.INVENTORY,
                list(peers),
                probe=script,
                mechanism=Mechanism.NETCMDLET,
                elapsed_ms=ms,
            )
        )
