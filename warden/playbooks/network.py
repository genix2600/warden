"""Network playbooks."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from warden.contracts import PredicateRef, RiskTier, Symptom, VerifySpec
from warden.playbooks.base import NoParams, Playbook
from warden.store import ObservationStore

#: Windows interface aliases are user-renameable, so this is a real parameter
#: rather than a constant. The pattern is tight because one playbook below
#: interpolates it into a PowerShell command line rather than a bare argv token.
_INTERFACE = Field(default="Wi-Fi", min_length=1, max_length=32, pattern=r"^[A-Za-z0-9 _\-#]+$")


class WifiReconnectParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile: str = Field(min_length=1, max_length=64)
    interface: str = _INTERFACE


class InterfaceParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    interface: str = _INTERFACE


def _known_profile(params: BaseModel, store: ObservationStore) -> str | None:
    """Refuse to join a network Warden has no evidence this machine knows.

    Schema validation would happily accept ``profile="Free_Airport_WiFi"``. This
    is the check that makes that impossible: the name must either appear in the
    machine's saved profile list, or be one Warden itself watched the machine
    connected to earlier in this session. A reasoner cannot talk the executor
    into associating with an access point out of thin air.
    """
    assert isinstance(params, WifiReconnectParams)
    saved = store.value("net.wifi.profiles") or []
    if isinstance(saved, list) and params.profile in saved:
        return None
    seen = store.last_where("net.wifi.link", "state", "connected", within_s=3600)
    if (
        seen
        and isinstance(seen.value, dict)
        and params.profile in {seen.value.get("profile"), seen.value.get("ssid")}
    ):
        return None
    return (
        f"{params.profile!r} is not in this machine's saved wireless profiles and "
        f"was not observed in use during this session"
    )


def _interface_exists(params: BaseModel, store: ObservationStore) -> str | None:
    assert isinstance(params, InterfaceParams | WifiReconnectParams)
    known = {
        store.field("net.wifi.adapter", "name"),
        store.field("net.wifi.link", "interface"),
    }
    if params.interface in known:
        return None
    return f"{params.interface!r} is not a wireless interface Warden has observed"


def _bind_reconnect(symptom: Symptom, store: ObservationStore) -> dict[str, JsonValue]:
    facts = symptom.facts
    profile = facts.get("last_connected_profile") or facts.get("last_connected_ssid")
    interface = store.field("net.wifi.adapter", "name") or "Wi-Fi"
    return {"profile": profile, "interface": interface}


def _bind_interface(symptom: Symptom, store: ObservationStore) -> dict[str, JsonValue]:
    return {"interface": store.field("net.wifi.adapter", "name") or "Wi-Fi"}


WIFI_RECONNECT = Playbook(
    id="net.wifi.reconnect",
    title="Reconnect to the wireless network",
    summary="Asks Windows to re-associate the wireless adapter with a saved network profile.",
    when_to_use=(
        "The adapter is present and its radio is on, but it is not associated with any "
        "network, and a profile it was previously connected to is known."
    ),
    risk=RiskTier.REVERSIBLE,
    params_model=WifiReconnectParams,
    argv_template=["netsh", "wlan", "connect", "name={profile}", "interface={interface}"],
    expected_effect="The adapter associates with the named network within a few seconds.",
    verify=VerifySpec(
        probes=["net.wifi", "net.connectivity"],
        predicate=PredicateRef(
            id="wifi.associated",
            describe="Re-read the adapter and confirm it is associated to that network.",
        ),
        timeout_s=25.0,
        settle_s=3.0,
    ),
    est_duration_s=8.0,
    guard=_known_profile,
    binder=_bind_reconnect,
    note="Uses a profile already stored on this machine; no password is read or sent.",
    tags=("network", "wireless"),
)

WIFI_SCAN = Playbook(
    id="net.wifi.scan",
    title="Scan for visible wireless networks",
    summary="Lists the access points currently in range, with signal strength.",
    when_to_use=(
        "Wireless is down and it is not yet clear whether the network is out of range, "
        "or the evidence is too thin to propose a change."
    ),
    risk=RiskTier.READ_ONLY,
    params_model=NoParams,
    argv_template=["netsh", "wlan", "show", "networks", "mode=bssid"],
    expected_effect="Prints the networks in range. Nothing on the machine is changed.",
    verify=VerifySpec(
        probes=[],
        predicate=PredicateRef(
            id="report.only", describe="No state changes, so there is nothing to re-check."
        ),
        timeout_s=5.0,
    ),
    est_duration_s=4.0,
    tags=("network", "wireless", "diagnostic"),
)

DNS_FLUSH = Playbook(
    id="net.dns.flush",
    title="Clear the DNS resolver cache",
    summary="Discards cached name lookups so the next one is asked fresh.",
    when_to_use=(
        "Hosts are reachable by IP address but names are not resolving, which points at "
        "stale or poisoned cache entries rather than at the connection."
    ),
    risk=RiskTier.REVERSIBLE,
    params_model=NoParams,
    argv_template=["ipconfig", "/flushdns"],
    expected_effect="The next name lookup goes to the DNS server instead of the cache.",
    verify=VerifySpec(
        probes=["net.connectivity"],
        predicate=PredicateRef(
            id="net.dns_resolves", describe="Resolve a known hostname again and see if it answers."
        ),
        timeout_s=15.0,
        settle_s=1.0,
    ),
    est_duration_s=3.0,
    tags=("network", "dns"),
)

DHCP_RENEW = Playbook(
    id="net.dhcp.renew",
    title="Renew the network address lease",
    summary="Releases and re-requests this machine's IP configuration from the router.",
    when_to_use=(
        "The machine is associated to a network but the router does not answer, which is "
        "often a stale or conflicting address lease."
    ),
    risk=RiskTier.REVERSIBLE,
    params_model=NoParams,
    argv_template=["ipconfig", "/renew"],
    expected_effect=(
        "The adapter briefly drops its address and requests a new one. Connections in "
        "flight will stall for a few seconds."
    ),
    verify=VerifySpec(
        probes=["net.connectivity"],
        predicate=PredicateRef(
            id="net.gateway_reachable", describe="Ping the default gateway again."
        ),
        timeout_s=40.0,
        settle_s=4.0,
    ),
    est_duration_s=20.0,
    requires_network=False,
    tags=("network", "dhcp"),
)

ADAPTER_RESTART = Playbook(
    id="net.adapter.restart",
    title="Restart the wireless adapter",
    summary="Disables and re-enables the wireless network adapter.",
    when_to_use=(
        "Gentler network fixes have not worked and the adapter itself appears wedged. "
        "Prefer reconnecting or renewing the lease first."
    ),
    risk=RiskTier.INTRUSIVE,
    params_model=InterfaceParams,
    # The interface name is interpolated into a PowerShell command rather than a
    # bare argv token, which is the one place in this registry where a value
    # could alter the meaning of the command. That is why InterfaceParams pins
    # the pattern to alphanumerics, spaces and a few punctuation marks -- there
    # is no quote or semicolon it could carry.
    argv_template=[
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        "Restart-NetAdapter -Name '{interface}' -Confirm:$false",
    ],
    expected_effect=(
        "The adapter goes down and comes back up. All network connections drop for "
        "roughly ten seconds and Windows reconnects automatically."
    ),
    verify=VerifySpec(
        probes=["net.wifi", "net.connectivity"],
        predicate=PredicateRef(
            id="wifi.associated", describe="Confirm the adapter came back and re-associated."
        ),
        timeout_s=45.0,
        settle_s=6.0,
    ),
    est_duration_s=15.0,
    requires_admin=True,
    reversible=True,
    guard=_interface_exists,
    binder=_bind_interface,
    tags=("network", "adapter"),
)

NETWORK_PLAYBOOKS = [WIFI_RECONNECT, WIFI_SCAN, DNS_FLUSH, DHCP_RENEW, ADAPTER_RESTART]
