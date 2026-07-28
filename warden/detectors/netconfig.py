"""Detectors for settings that break things quietly.

The network-category one needs care, and is worth reading before the others.
Public is the *safe* default and the correct setting in a cafe or an airport;
switching it to Private enables discovery and file sharing, which on an
untrusted network is a genuine security regression. So this is not reported as a
fault -- it is reported at INFO severity, as an explanation for a specific
frustration ("I cannot see my printer"), with the trade-off stated. The decision
belongs to the user, which is exactly what the approval gate is for.

Reporting it as CRITICAL and rushing the user into Private would be Warden doing
the thing it exists to criticise: confident advice that makes the machine worse.
"""

from __future__ import annotations

from warden.contracts import Severity, Symptom
from warden.detectors.base import Detector
from warden.store import ObservationStore, as_dict, as_list

#: IPv4Connectivity 4 means Windows believes this network reaches the internet.
_INTERNET = 4


class NetworkProfileDetector(Detector):
    id = "net.profile"
    raises = ("NET.PROFILE_PUBLIC_ON_TRUSTED",)

    def evaluate(self, store: ObservationStore) -> list[Symptom]:
        observation = store.latest("net.profile")
        if observation is None:
            return []

        profiles = [as_dict(raw) for raw in as_list(observation.value)]
        public = [
            profile
            for profile in profiles
            if profile.get("category") == "public"
            # Only mention it on a network that is otherwise working. Piling this
            # on top of a broken connection would bury the fault that matters.
            and profile.get("ipv4_connectivity") == _INTERNET
        ]
        if not public:
            return []

        # Corroboration that this is a network the machine knows: a saved
        # wireless profile means it has been joined deliberately before. It is a
        # weak signal and is presented as one -- it raises the INFO note, it does
        # not decide anything.
        saved = store.value("net.wifi.profiles")
        saved_names = saved if isinstance(saved, list) else []
        profile = public[0]
        name = profile.get("name")
        recognised = any(
            isinstance(entry, str)
            and isinstance(name, str)
            and (entry in name or name.startswith(entry))
            for entry in saved_names
        )

        return [
            self.symptom(
                "NET.PROFILE_PUBLIC_ON_TRUSTED",
                # Deliberately not a fault. See the module docstring.
                severity=Severity.INFO,
                title=f"{name} is set up as a public network",
                detail=(
                    "Windows treats public networks as untrusted, so network discovery, "
                    "file sharing and printer sharing are all switched off on this "
                    "connection. That is the right setting on a network you do not "
                    "control, and the wrong one at home."
                ),
                facts={
                    "network": name,
                    "interface": profile.get("interface"),
                    "category": profile.get("category"),
                    "is_saved_wireless_profile": recognised,
                    "public_network_count": len(public),
                    # Named explicitly so the reasoner cannot present this as a
                    # fault to be fixed rather than a choice to be made.
                    "is_a_choice_not_a_fault": True,
                    "security_tradeoff": (
                        "Private makes this machine discoverable to others on the same "
                        "network. Only appropriate on a network you trust."
                    ),
                },
                evidence=[observation, store.latest("net.wifi.profiles")],
            )
        ]


class ProxyDetector(Detector):
    """A proxy configured but not working -- classic leftover from removed software."""

    id = "net.proxy"
    raises = ("NET.PROXY_CONFIGURED_BUT_OFFLINE",)

    def evaluate(self, store: ObservationStore) -> list[Symptom]:
        proxy_observation = store.latest("net.proxy")
        if proxy_observation is None:
            return []
        proxy = as_dict(proxy_observation.value)

        configured = bool(proxy.get("user_proxy_enabled")) or not proxy.get("winhttp_direct")
        if not configured:
            return []

        # A proxy is only a finding when something is actually failing. Plenty of
        # machines use one perfectly happily, especially on corporate networks.
        internet = store.latest("net.connectivity.internet")
        dns = store.latest("net.connectivity.dns")
        reachable = internet.value is True if internet else True
        resolves = as_dict(dns.value).get("resolves") is True if dns else True
        if reachable and resolves:
            return []

        server = proxy.get("user_proxy_server") or proxy.get("winhttp_server")
        return [
            self.symptom(
                "NET.PROXY_CONFIGURED_BUT_OFFLINE",
                severity=Severity.CRITICAL,
                title="Traffic is being sent through a proxy that is not answering",
                detail=(
                    f"This machine is configured to route requests through {server!r}, "
                    f"and nothing outside the network is currently reachable."
                ),
                facts={
                    "proxy_server": server,
                    "user_proxy_enabled": proxy.get("user_proxy_enabled"),
                    "winhttp_configured": not proxy.get("winhttp_direct"),
                    "auto_config_url": proxy.get("auto_config_url"),
                    "internet_reachable": reachable,
                },
                evidence=[proxy_observation, internet],
            )
        ]


class HostsFileDetector(Detector):
    """Entries in the hosts file that redirect or blackhole real sites."""

    id = "net.hosts"
    raises = ("NET.HOSTS_OVERRIDE",)

    def evaluate(self, store: ObservationStore) -> list[Symptom]:
        observation = store.latest("net.hosts")
        if observation is None:
            return []
        entries = [as_dict(raw) for raw in as_list(observation.value)]
        # localhost lines are the file's normal content and are not findings.
        interesting = [
            entry
            for entry in entries
            if not any(
                str(host).lower() in {"localhost", "localhost.localdomain"}
                for host in as_list(entry.get("hosts"))
            )
        ]
        if not interesting:
            return []

        blocked = [e for e in interesting if e.get("blackholed")]
        return [
            self.symptom(
                "NET.HOSTS_OVERRIDE",
                severity=Severity.WARN,
                title=f"{len(interesting)} website(s) are being redirected by the hosts file",
                detail=(
                    "The hosts file overrides normal name lookup for these addresses, "
                    "which is invisible to the browser and survives clearing every cache."
                ),
                facts={
                    "entry_count": len(interesting),
                    "blackholed_count": len(blocked),
                    "entries": list(interesting[:10]),
                    # Ad blockers and privacy tools legitimately write these, so
                    # this is reported for the user to judge rather than removed.
                    "may_be_deliberate": True,
                },
                evidence=[observation],
            )
        ]
