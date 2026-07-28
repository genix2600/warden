"""Network settings that are invisible from the symptom.

Everything here shares a shape: the network appears to work, nothing reports an
error, and yet something specific is broken in a way the user has no route to
discovering. A proxy pointing at a server that no longer exists. A hosts file
entry left behind by an installer. A home network Windows has categorised as
public, silently switching off every kind of sharing.

None of these produce an error message. All of them are one command away from
fixed, once you know which command -- which is the whole product in one module.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import JsonValue

from warden.collectors.base import Collector, first, timed
from warden.collectors.psbridge import (
    PowerShellBridge,
    PowerShellError,
    PowerShellUnavailable,
    as_rows,
    json_pipeline,
)
from warden.contracts import Mechanism, ObservationKind, ProbeResult

HOSTS_FILE = Path(r"C:\Windows\System32\drivers\etc\hosts")

#: Get-NetConnectionProfile serialises NetworkCategory as an integer through
#: ConvertTo-Json, whatever it displays in a console.
NETWORK_CATEGORY = {0: "public", 1: "private", 2: "domain"}

#: Loopback targets are how a hosts entry blocks a site rather than redirecting
#: it. Distinguishing the two matters: blocking is usually deliberate (an ad
#: blocker), redirection to a real address is usually not.
_BLACKHOLE = {"0.0.0.0", "127.0.0.1", "::1", "::"}

_PROFILES = json_pipeline(
    "Get-NetConnectionProfile -ErrorAction SilentlyContinue | "
    "Select-Object Name,InterfaceAlias,NetworkCategory,IPv4Connectivity"
)
_DNS = json_pipeline(
    "Get-DnsClientServerAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | "
    "Where-Object { $_.ServerAddresses.Count -gt 0 } | "
    "Select-Object InterfaceAlias,ServerAddresses",
    depth=4,
)
_IE_PROXY = json_pipeline(
    "Get-ItemProperty 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings' "
    "-ErrorAction SilentlyContinue | Select-Object ProxyEnable,ProxyServer,AutoConfigURL"
)


class NetConfigCollector(Collector):
    id = "net.config"
    interval_s = 20.0
    description = "Network profile category, proxy configuration, DNS servers and the hosts file."

    def __init__(self, bridge: PowerShellBridge) -> None:
        self._ps = bridge

    def probe(self) -> ProbeResult:
        result = ProbeResult()
        self._probe_profile(result)
        self._probe_proxy(result)
        self._probe_dns(result)
        self._probe_hosts(result)
        return result

    def _probe_profile(self, result: ProbeResult) -> None:
        script = "Get-NetConnectionProfile"
        try:
            rows, ms = self._ps.run_json(_PROFILES)
        except (PowerShellError, PowerShellUnavailable) as exc:
            result.errors.append(self.failure(script, exc))
            return
        profiles: list[dict[str, JsonValue]] = []
        for row in as_rows(rows):
            code = row.get("NetworkCategory")
            profiles.append(
                {
                    "name": row.get("Name"),
                    "interface": row.get("InterfaceAlias"),
                    "category": NETWORK_CATEGORY.get(
                        code if isinstance(code, int) else -1, "unknown"
                    ),
                    "category_code": code,
                    "ipv4_connectivity": row.get("IPv4Connectivity"),
                }
            )
        result.observations.append(
            self.observation(
                "net.profile",
                ObservationKind.STATE,
                list(profiles),
                probe=script,
                mechanism=Mechanism.NETCMDLET,
                elapsed_ms=ms,
            )
        )

    def _probe_proxy(self, result: ProbeResult) -> None:
        """Two independent proxy settings, because Windows has two.

        ``netsh winhttp`` covers system services and most background traffic;
        the per-user Internet Settings key covers browsers and anything using
        WinINet. A machine can be broken by either, and a user who checks the
        Settings app only ever sees the second.
        """
        script = "netsh winhttp show proxy"
        try:
            text, ms = self._ps.run(f"{script} | Out-String")
        except (PowerShellError, PowerShellUnavailable) as exc:
            result.errors.append(self.failure(script, exc))
            text, ms = "", 0.0

        lowered = text.lower()
        winhttp_direct = "direct access" in lowered
        winhttp_server = None
        for line in text.splitlines():
            if "proxy server" in line.lower() and ":" in line:
                winhttp_server = line.split(":", 1)[1].strip() or None

        ie: dict[str, JsonValue] = {}
        try:
            rows, ie_ms = self._ps.run_json(_IE_PROXY)
            ie = first(as_rows(rows))
            ms += ie_ms
        except (PowerShellError, PowerShellUnavailable) as exc:
            result.errors.append(self.failure("Internet Settings ProxyEnable", exc))

        result.observations.append(
            self.observation(
                "net.proxy",
                ObservationKind.STATE,
                {
                    "winhttp_direct": winhttp_direct,
                    "winhttp_server": winhttp_server,
                    "user_proxy_enabled": bool(ie.get("ProxyEnable")),
                    "user_proxy_server": ie.get("ProxyServer"),
                    "auto_config_url": ie.get("AutoConfigURL"),
                },
                probe=f"{script}; Get-ItemProperty 'HKCU:\\...\\Internet Settings'",
                mechanism=Mechanism.NETSH,
                elapsed_ms=ms,
            )
        )

    def _probe_dns(self, result: ProbeResult) -> None:
        script = "Get-DnsClientServerAddress -AddressFamily IPv4"
        try:
            rows, ms = self._ps.run_json(_DNS)
        except (PowerShellError, PowerShellUnavailable) as exc:
            result.errors.append(self.failure(script, exc))
            return
        interfaces: list[dict[str, JsonValue]] = []
        for row in as_rows(rows):
            servers = row.get("ServerAddresses")
            interfaces.append(
                {
                    "interface": row.get("InterfaceAlias"),
                    "servers": servers if isinstance(servers, list) else [],
                }
            )
        result.observations.append(
            self.observation(
                "net.dns_servers",
                ObservationKind.INVENTORY,
                list(interfaces),
                probe=script,
                mechanism=Mechanism.NETCMDLET,
                elapsed_ms=ms,
            )
        )

    def _probe_hosts(self, result: ProbeResult) -> None:
        """Read the hosts file directly. No elevation needed to read it."""
        probe = f"read {HOSTS_FILE}"
        entries: list[dict[str, JsonValue]] = []
        with timed() as t:
            try:
                lines = HOSTS_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError as exc:
                result.errors.append(self.failure(probe, exc))
                return
            for number, raw in enumerate(lines, start=1):
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split()
                if len(parts) < 2:
                    continue
                address, *names = parts
                entries.append(
                    {
                        "line": number,
                        "address": address,
                        "hosts": [n for n in names if not n.startswith("#")],
                        "blackholed": address in _BLACKHOLE,
                        "text": line,
                    }
                )
        result.observations.append(
            self.observation(
                "net.hosts",
                ObservationKind.INVENTORY,
                list(entries),
                probe=probe,
                mechanism=Mechanism.FILE,
                elapsed_ms=t.ms,
            )
        )
