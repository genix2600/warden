"""Wireless link state and actual reachability.

Split into two collectors because they answer different questions and fail
independently. ``net.wifi`` answers "are we associated with an access point";
``net.connectivity`` answers "can we reach anything". A machine can be firmly
associated to a router that has lost its uplink, and telling those two apart is
most of what makes a network diagnosis useful rather than a shrug.

Layering, strongest source first:

1. ``Get-NetAdapter`` / ``Get-NetConnectionProfile`` -- structured objects with
   locale-independent property names. Authoritative for up/down and for whether
   Windows itself believes there is internet.
2. ``netsh wlan show interfaces`` -- the only readily available source for SSID,
   signal percentage and radio kill-switch state. Its output is localised, so it
   is parsed tolerantly and never used for anything tier 1 can answer.
3. Direct sockets -- because both of the above report what Windows *thinks*, and
   the only way to know whether packets move is to move some.
"""

from __future__ import annotations

import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from warden.collectors.base import Collector, first, num, timed
from warden.collectors.psbridge import (
    PowerShellBridge,
    PowerShellError,
    PowerShellUnavailable,
    as_rows,
    json_pipeline,
)
from warden.contracts import Mechanism, ObservationKind, ProbeResult

#: TCP/53 on two public resolvers. Port 53 is chosen because it is reachable
#: without DNS working, which is the whole point: it separates "no route" from
#: "route but name resolution is broken".
_REACH_TARGETS = (("1.1.1.1", 53), ("8.8.8.8", 53))
_DNS_PROBE_HOST = "www.msftconnecttest.com"

_IPV4_CONNECTIVITY = {
    0: "disconnected",
    1: "no_traffic",
    2: "subnet",
    3: "local_network",
    4: "internet",
}

_ADAPTERS = json_pipeline(
    "Get-NetAdapter -Physical -ErrorAction SilentlyContinue | "
    "Where-Object { $_.MediaType -eq 'Native 802.11' } | "
    "Select-Object Name,Status,ifIndex,LinkSpeed,InterfaceDescription,AdminStatus"
)
_CONN_PROFILE = json_pipeline(
    "Get-NetConnectionProfile -ErrorAction SilentlyContinue | "
    "Select-Object Name,InterfaceAlias,IPv4Connectivity,IPv6Connectivity,NetworkCategory"
)
_DEFAULT_ROUTE = json_pipeline(
    "Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue | "
    "Sort-Object RouteMetric | Select-Object -First 1 NextHop,InterfaceAlias,RouteMetric"
)


def parse_wlan_interfaces(text: str) -> list[dict[str, str]]:
    """Parse ``netsh wlan show interfaces`` into one record per interface.

    Values legitimately contain colons (MAC addresses, cipher suites), so the
    split is on the *first* colon only. Keys are lowercased and compared exactly,
    which matters: a substring match for "ssid" would also swallow "AP BSSID".

    **Values also legitimately span lines**, and the version of this parser that
    skipped every line without a colon silently dropped the second half of them.
    The case that cost us a release:

    .. code-block:: text

        Radio status           : Hardware On
                                 Software Off

    The continuation carries the entire meaning. Dropping it left ``radio
    status`` reading ``"Hardware On"``, so a radio the user had switched off in
    software was reported as merely disconnected, and the detector raised
    ``NET.WIFI.DISCONNECTED`` -- a symptom with a reconnect action -- instead of
    ``NET.WIFI.RADIO_OFF``, which is deliberately unfixable and would have said
    "flip the switch". Warden proposed a command for a problem no command can
    reach, which is the failure mode the empty candidate lists exist to prevent.

    A continuation is an indented line with no colon arriving after a key. It is
    joined to that key with a single space rather than a newline, because every
    consumer of these records does substring tests on a flat string.
    """
    blocks: list[dict[str, str]] = []
    current: dict[str, str] = {}
    last_key: str | None = None
    for raw in text.splitlines():
        if not raw.strip():
            last_key = None  # a blank line ends any continuation
            continue
        if ":" not in raw:
            # Only an indented line can continue a value. An unindented one is
            # a heading or a separator and belongs to nothing.
            if last_key is not None and raw[:1].isspace():
                current[last_key] = f"{current[last_key]} {raw.strip()}".strip()
            continue
        key, _, value = raw.partition(":")
        key = key.strip().lower()
        value = value.strip()
        if not key:
            continue
        if key == "name" and current:
            blocks.append(current)
            current = {}
        current[key] = value
        last_key = key
    if current:
        blocks.append(current)
    return [b for b in blocks if "state" in b or "radio status" in b]


def parse_wlan_profiles(text: str) -> list[str]:
    """Best-effort list of saved wireless profiles.

    Localised output, so this is advisory only. The reconnect playbook prefers
    the profile Warden watched the machine using before the drop -- its own
    observation history -- and falls back to this list.
    """
    names: list[str] = []
    for raw in text.splitlines():
        if ":" not in raw:
            continue
        key, _, value = raw.partition(":")
        if "profile" not in key.strip().lower():
            continue
        value = value.strip()
        if value and value != "<None>":
            names.append(value)
    return names


def _percent(value: str | None) -> float | None:
    if not value:
        return None
    return num(value.replace("%", "").strip())


class WifiCollector(Collector):
    id = "net.wifi"
    interval_s = 2.0
    description = "Wireless adapter state, association, signal strength and saved profiles."

    def __init__(self, bridge: PowerShellBridge) -> None:
        self._ps = bridge
        self._profiles_cache: list[str] = []

    def probe(self) -> ProbeResult:
        result = ProbeResult()
        adapter = self._probe_adapter(result)
        self._probe_link(result, adapter_present=adapter is not None)
        self._probe_profiles(result)
        return result

    def _probe_adapter(self, result: ProbeResult) -> dict[str, Any] | None:
        script = "Get-NetAdapter -Physical | Where MediaType -eq 'Native 802.11'"
        try:
            rows, ms = self._ps.run_json(_ADAPTERS)
        except (PowerShellError, PowerShellUnavailable) as exc:
            result.errors.append(self.failure(script, exc))
            return None
        adapters = as_rows(rows)
        adapter = first(adapters)
        result.observations.append(
            self.observation(
                "net.wifi.adapter",
                ObservationKind.STATE,
                {
                    "present": bool(adapters),
                    "name": adapter.get("Name"),
                    "status": adapter.get("Status"),
                    "admin_status": adapter.get("AdminStatus"),
                    "description": adapter.get("InterfaceDescription"),
                    "link_speed": adapter.get("LinkSpeed"),
                    "if_index": adapter.get("ifIndex"),
                },
                probe=script,
                mechanism=Mechanism.NETCMDLET,
                elapsed_ms=ms,
            )
        )
        return adapter or None

    def _probe_link(self, result: ProbeResult, *, adapter_present: bool) -> None:
        script = "netsh wlan show interfaces"
        try:
            with timed() as t:
                completed = subprocess.run(
                    ["netsh", "wlan", "show", "interfaces"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=6,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
        except (OSError, subprocess.SubprocessError) as exc:
            result.errors.append(self.failure(script, exc))
            return

        blocks = parse_wlan_interfaces(completed.stdout)
        iface = first(blocks)
        state = (iface.get("state") or "").lower()
        radio = iface.get("radio status") or ("on" if adapter_present else "unknown")
        signal = _percent(iface.get("signal"))

        result.observations.append(
            self.observation(
                "net.wifi.link",
                ObservationKind.STATE,
                {
                    "state": state or ("disconnected" if adapter_present else "no_adapter"),
                    "ssid": iface.get("ssid") or None,
                    "profile": (iface.get("profile") or "").strip() or None,
                    "band": iface.get("band"),
                    "radio": radio,
                    "signal_pct": signal,
                    "rssi_dbm": num(iface.get("rssi")),
                    "interface": iface.get("name"),
                },
                probe=script,
                mechanism=Mechanism.NETSH,
                elapsed_ms=t.ms,
                # Localised output: high confidence on an English install, but we
                # say out loud that this is a weaker source than the cmdlets.
                confidence=0.9 if blocks else 0.4,
            )
        )
        if signal is not None:
            result.observations.append(
                self.observation(
                    "net.wifi.signal_pct",
                    ObservationKind.METRIC,
                    signal,
                    unit="%",
                    probe=script,
                    mechanism=Mechanism.NETSH,
                    elapsed_ms=t.ms,
                )
            )

    def _probe_profiles(self, result: ProbeResult) -> None:
        """Saved profiles change rarely; re-read only when the cache is empty."""
        script = "netsh wlan show profiles"
        if self._profiles_cache:
            elapsed = 0.0
        else:
            try:
                with timed() as t:
                    completed = subprocess.run(
                        ["netsh", "wlan", "show", "profiles"],
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=6,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
            except (OSError, subprocess.SubprocessError) as exc:
                result.errors.append(self.failure(script, exc))
                return
            self._profiles_cache = parse_wlan_profiles(completed.stdout)
            elapsed = t.ms
        result.observations.append(
            self.observation(
                "net.wifi.profiles",
                ObservationKind.INVENTORY,
                list(self._profiles_cache),
                probe=script,
                mechanism=Mechanism.NETSH,
                elapsed_ms=elapsed,
                confidence=0.9,
            )
        )


class ConnectivityCollector(Collector):
    id = "net.connectivity"
    interval_s = 3.0
    description = "Whether packets actually move: gateway, internet reachability, DNS."

    def __init__(self, bridge: PowerShellBridge) -> None:
        self._ps = bridge
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="net-reach")

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)

    def probe(self) -> ProbeResult:
        result = ProbeResult()
        # Reachability and DNS are network-bound and independent; run them
        # concurrently so a probe costs one timeout, not three.
        reach_future = self._pool.submit(self._reachable)
        dns_future = self._pool.submit(self._dns)
        self._probe_profile(result)
        self._probe_gateway(result)

        reachable, reach_ms, reach_target = reach_future.result()
        result.observations.append(
            self.observation(
                "net.connectivity.internet",
                ObservationKind.STATE,
                reachable,
                probe=f"TCP connect {reach_target}",
                mechanism=Mechanism.SOCKET,
                elapsed_ms=reach_ms,
            )
        )
        resolves, dns_ms = dns_future.result()
        result.observations.append(
            self.observation(
                "net.connectivity.dns",
                ObservationKind.STATE,
                {"resolves": resolves, "host": _DNS_PROBE_HOST},
                probe=f"getaddrinfo({_DNS_PROBE_HOST})",
                mechanism=Mechanism.SOCKET,
                elapsed_ms=dns_ms,
            )
        )
        return result

    def _probe_profile(self, result: ProbeResult) -> None:
        script = "Get-NetConnectionProfile"
        try:
            rows, ms = self._ps.run_json(_CONN_PROFILE)
        except (PowerShellError, PowerShellUnavailable) as exc:
            result.errors.append(self.failure(script, exc))
            return
        profiles = as_rows(rows)
        profile = first(profiles)
        code = profile.get("IPv4Connectivity")
        result.observations.append(
            self.observation(
                "net.connectivity.profile",
                ObservationKind.STATE,
                {
                    "any": bool(profiles),
                    "name": profile.get("Name"),
                    "interface": profile.get("InterfaceAlias"),
                    "ipv4": _IPV4_CONNECTIVITY.get(
                        code if isinstance(code, int) else -1, "unknown"
                    ),
                },
                probe=script,
                mechanism=Mechanism.NETCMDLET,
                elapsed_ms=ms,
            )
        )

    def _probe_gateway(self, result: ProbeResult) -> None:
        script = "Get-NetRoute -DestinationPrefix '0.0.0.0/0'"
        try:
            rows, ms = self._ps.run_json(_DEFAULT_ROUTE)
        except (PowerShellError, PowerShellUnavailable) as exc:
            result.errors.append(self.failure(script, exc))
            return
        route = first(as_rows(rows))
        next_hop = route.get("NextHop")
        reachable: bool | None = None
        if isinstance(next_hop, str) and next_hop not in ("", "0.0.0.0"):
            reachable = _ping(next_hop)
        result.observations.append(
            self.observation(
                "net.connectivity.gateway",
                ObservationKind.STATE,
                {"address": next_hop, "reachable": reachable, "via": route.get("InterfaceAlias")},
                probe=f"{script}; ping -n 1 -w 700 {next_hop or '<none>'}",
                mechanism=Mechanism.NETCMDLET,
                elapsed_ms=ms,
            )
        )

    @staticmethod
    def _reachable() -> tuple[bool, float, str]:
        with timed() as t:
            for host, port in _REACH_TARGETS:
                try:
                    with socket.create_connection((host, port), timeout=1.2):
                        return True, t.ms, f"{host}:{port}"
                except OSError:
                    continue
        targets = ", ".join(f"{h}:{p}" for h, p in _REACH_TARGETS)
        return False, t.ms, targets

    @staticmethod
    def _dns() -> tuple[bool, float]:
        with timed() as t:
            try:
                socket.getaddrinfo(_DNS_PROBE_HOST, 80, proto=socket.IPPROTO_TCP)
            except OSError:
                return False, t.ms
        return True, t.ms


def _ping(address: str) -> bool | None:
    """One ICMP echo with a hard 700ms deadline.

    ``Test-Connection`` on PowerShell 5.1 has no timeout parameter and blocks for
    about four seconds against a dead host, which is far too long to sit inside a
    three-second poll. ``ping.exe -w`` is bounded and always present.
    """
    try:
        completed = subprocess.run(
            ["ping", "-n", "1", "-w", "700", address],
            capture_output=True,
            timeout=3,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.returncode == 0
