"""Fixes for settings that are one command away, if you know the command.

Two of these need a word about scope.

``net.profile.private`` is the only action in the registry whose correct answer
depends on something Warden cannot measure -- whether the user trusts the
network they are on. It is offered, never assumed, and the approval card carries
the security trade-off rather than burying it.

``net.hosts.comment`` is the only action that edits a file. It comments lines out
rather than deleting them, and writes a timestamped backup first, so the change
is reversible by hand even if Warden is uninstalled the same day.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from warden.collectors.netconfig import HOSTS_FILE
from warden.contracts import PredicateRef, RiskTier, Symptom, VerifySpec
from warden.playbooks.base import NoParams, Playbook
from warden.store import ObservationStore, as_dict, as_list


class ProfileParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Windows network profile names come from the SSID and can contain almost
    #: anything, so the length bound does the work and the guard does the rest.
    name: str = Field(min_length=1, max_length=120)


def _profile_is_public(params: BaseModel, store: ObservationStore) -> str | None:
    assert isinstance(params, ProfileParams)
    for raw in as_list(store.value("net.profile")):
        profile = as_dict(raw)
        if profile.get("name") == params.name:
            if profile.get("category") != "public":
                return f"{params.name!r} is already {profile.get('category')}"
            return None
    return f"{params.name!r} is not a network Warden can currently see"


def _bind_profile(symptom: Symptom, store: ObservationStore) -> dict[str, JsonValue]:
    return {"name": symptom.facts.get("network")}


PROFILE_PRIVATE = Playbook(
    id="net.profile.private",
    title="Mark this network as private",
    summary=(
        "Switches the network from Public to Private, which re-enables network "
        "discovery, file sharing and printer sharing on this connection."
    ),
    when_to_use=(
        "The user cannot see shared printers or other computers on a network they "
        "own and trust, and Windows has the network categorised as public. Never on "
        "a network the user does not control."
    ),
    risk=RiskTier.INTRUSIVE,
    params_model=ProfileParams,
    argv_template=[
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        "Set-NetConnectionProfile -Name '{name}' -NetworkCategory Private -ErrorAction Stop",
    ],
    expected_effect=(
        "This machine becomes discoverable to other devices on this network, and can "
        "see shared printers and folders. On a network you do not trust, that is a "
        "meaningful exposure -- only approve this at home or in an office you control."
    ),
    verify=VerifySpec(
        probes=["net.config"],
        predicate=PredicateRef(
            id="net.profile_private",
            describe="Re-read the network profile and confirm the category changed.",
        ),
        timeout_s=20.0,
        settle_s=2.0,
    ),
    est_duration_s=4.0,
    requires_admin=True,
    guard=_profile_is_public,
    binder=_bind_profile,
    note=(
        "Changes one network's category. Reversible from Settings > Network at any "
        "time, and it applies to this network only."
    ),
    tags=("network", "sharing"),
)

PROXY_RESET = Playbook(
    id="net.proxy.reset",
    title="Clear the proxy configuration",
    summary=(
        "Removes the proxy settings so traffic goes out directly instead of through "
        "a server that is not answering."
    ),
    when_to_use=(
        "A proxy is configured but nothing outside the network is reachable, which is "
        "the signature of a proxy left behind by software that has since been removed."
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
        # Both settings, because Windows has two and clearing one leaves the
        # machine half-broken in a way that is even harder to diagnose.
        "netsh winhttp reset proxy | Out-Null; "
        "Set-ItemProperty 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\"
        "Internet Settings' -Name ProxyEnable -Value 0 -ErrorAction Stop",
    ],
    expected_effect=(
        "Requests stop being routed through the proxy. If this network genuinely "
        "requires one -- some workplaces do -- you will need to put it back."
    ),
    verify=VerifySpec(
        probes=["net.config", "net.connectivity"],
        predicate=PredicateRef(
            id="net.internet_reachable",
            describe="Try to reach an outside host again now the proxy is bypassed.",
        ),
        timeout_s=30.0,
        settle_s=3.0,
    ),
    est_duration_s=6.0,
    requires_admin=True,
    tags=("network", "proxy"),
)


class HostsParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The exact hostname to neutralise. One at a time, deliberately: a bulk
    #: "clean the hosts file" action would wipe legitimate ad-blocker entries.
    hostname: str = Field(min_length=1, max_length=253, pattern=r"^[A-Za-z0-9._-]+$")


def _hostname_is_in_hosts(params: BaseModel, store: ObservationStore) -> str | None:
    assert isinstance(params, HostsParams)
    for raw in as_list(store.value("net.hosts")):
        entry = as_dict(raw)
        if any(str(h).lower() == params.hostname.lower() for h in as_list(entry.get("hosts"))):
            return None
    return f"{params.hostname!r} does not appear in the hosts file"


HOSTS_COMMENT = Playbook(
    id="net.hosts.comment",
    title="Comment out one hosts-file entry",
    summary=(
        "Disables a single hosts-file line by commenting it out, after taking a backup of the file."
    ),
    when_to_use=(
        "A specific site is unreachable because the hosts file redirects it, and the "
        "user has confirmed the entry is not one they want."
    ),
    risk=RiskTier.INTRUSIVE,
    params_model=HostsParams,
    argv_template=[
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        # Backup first, then comment. Never delete: a commented line can be
        # restored by anyone with Notepad, a deleted one cannot.
        #
        # The braces of the PowerShell script block are doubled because this
        # string is a Python format template -- single braces here would be read
        # as placeholders and the action would be rejected every time it ran.
        # `check_template` enforces this at registry construction.
        f"$p='{HOSTS_FILE}'; "
        'Copy-Item $p "$p.warden-backup-$(Get-Date -f yyyyMMddHHmmss)" -ErrorAction Stop; '
        "(Get-Content $p) | ForEach-Object "
        "{{ if ($_ -notmatch '^\\s*#' -and $_ -match '\\b{hostname}\\b') {{ '# ' + $_ }} "
        "else {{ $_ }} }} | Set-Content $p -ErrorAction Stop",
    ],
    expected_effect=(
        "The site resolves normally again. The original file is saved alongside it "
        "with a .warden-backup timestamp."
    ),
    verify=VerifySpec(
        probes=["net.config"],
        predicate=PredicateRef(
            id="net.hosts_clear",
            describe="Re-read the hosts file and confirm the entry is commented out.",
        ),
        timeout_s=20.0,
        settle_s=1.0,
    ),
    est_duration_s=5.0,
    requires_admin=True,
    guard=_hostname_is_in_hosts,
    note="Takes a timestamped backup before changing anything, and comments rather than deletes.",
    tags=("network", "dns"),
)

NETCONFIG_PLAYBOOKS = [PROFILE_PRIVATE, PROXY_RESET, HOSTS_COMMENT]
