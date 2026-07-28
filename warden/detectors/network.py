"""Network detectors.

Two ideas do most of the work here.

**Debouncing.** Wireless roams. A laptop moving between two access points on the
same network reports "disconnected" for a tick or two and then reassociates on
its own. Firing an incident at the first bad sample would make Warden cry wolf
several times an hour on a normal machine, which is precisely the failure mode
that trained everyone to ignore their existing troubleshooter. Every symptom
here requires the condition to hold across consecutive samples.

**Root cause suppression.** If the radio is off, we are also not associated, and
we also cannot reach the internet, and DNS also fails. Reporting four symptoms
for one fault buries the one that matters. Each detector reports the most
specific condition it can prove and stays quiet about the consequences.
"""

from __future__ import annotations

from typing import Any

from warden.contracts import Observation, Severity, Symptom, utcnow
from warden.detectors.base import Detector
from warden.store import ObservationStore, as_dict

#: Two consecutive bad samples at a 2s poll -- roughly four seconds of fault
#: before Warden says anything. Long enough to ride out a roam, short enough
#: that a user watching the screen does not think it missed the event.
_CONSECUTIVE = 2
_WINDOW_S = 10.0


def _stable(store: ObservationStore, source: str, predicate: Any) -> list[Observation]:
    """Return recent samples if the condition holds across all of them, else []."""
    recent = store.history(source, within_s=_WINDOW_S)[-_CONSECUTIVE:]
    if len(recent) < _CONSECUTIVE:
        return []
    return recent if all(predicate(o.value) for o in recent) else []


class WifiLinkDetector(Detector):
    id = "net.wifi.link"
    raises = ("NET.WIFI.NO_ADAPTER", "NET.WIFI.RADIO_OFF", "NET.WIFI.DISCONNECTED")

    def evaluate(self, store: ObservationStore) -> list[Symptom]:
        adapter = store.latest("net.wifi.adapter")
        link = store.latest("net.wifi.link")
        if adapter is None or link is None:
            return []
        adapter_value = adapter.value if isinstance(adapter.value, dict) else {}
        link_value = link.value if isinstance(link.value, dict) else {}

        if not adapter_value.get("present"):
            return [
                self.symptom(
                    "NET.WIFI.NO_ADAPTER",
                    severity=Severity.CRITICAL,
                    title="No wireless adapter is present",
                    detail="Windows reports no physical 802.11 adapter on this machine.",
                    facts={"adapter": adapter_value},
                    evidence=[adapter, link],
                )
            ]

        radio = str(link_value.get("radio") or "").lower()
        if "off" in radio:
            # "Hardware Off" means a physical switch or firmware kill; no command
            # fixes that, and saying so is the whole point of the routing rule.
            hardware_switch = "hardware off" in radio
            return [
                self.symptom(
                    "NET.WIFI.RADIO_OFF",
                    severity=Severity.CRITICAL,
                    title="The wireless radio is switched off",
                    detail=f"netsh reports radio status {link_value.get('radio')!r}.",
                    facts={
                        "radio_status": link_value.get("radio"),
                        "hardware_switch": hardware_switch,
                        "adapter_status": adapter_value.get("status"),
                    },
                    evidence=[link, adapter],
                )
            ]

        samples = _stable(store, "net.wifi.link", lambda v: (v or {}).get("state") != "connected")
        if not samples:
            return []

        last_connected = store.last_where("net.wifi.link", "state", "connected", within_s=600)
        last_value = (
            last_connected.value
            if last_connected and isinstance(last_connected.value, dict)
            else {}
        )
        profiles = store.value("net.wifi.profiles") or []
        last_profile = last_value.get("profile") or last_value.get("ssid")
        seconds_down = (
            round((utcnow() - last_connected.captured_at).total_seconds())
            if last_connected
            else None
        )

        return [
            self.symptom(
                "NET.WIFI.DISCONNECTED",
                severity=Severity.CRITICAL,
                title="Wireless is disconnected",
                detail=(
                    f"The adapter is {adapter_value.get('status')} and the radio is on, "
                    f"but it has not been associated to a network for "
                    f"{_CONSECUTIVE} consecutive checks."
                ),
                facts={
                    "adapter_status": adapter_value.get("status"),
                    "radio_status": link_value.get("radio"),
                    "link_state": link_value.get("state"),
                    "last_connected_profile": last_profile,
                    "last_connected_ssid": last_value.get("ssid"),
                    "seconds_since_connected": seconds_down,
                    "last_signal_pct": last_value.get("signal_pct"),
                    "saved_profile_count": len(profiles) if isinstance(profiles, list) else 0,
                    "profile_is_saved": (isinstance(profiles, list) and last_profile in profiles),
                },
                evidence=[*samples, adapter, last_connected],
            )
        ]


class ReachabilityDetector(Detector):
    """Whether packets move, given that the link itself is up.

    Deliberately silent when the wireless link is down: "no internet" is not a
    finding when we already know the machine is not on a network. It reports
    only the cases the link state cannot explain.
    """

    id = "net.reachability"
    raises = ("NET.GATEWAY.UNREACHABLE", "NET.INTERNET.UNREACHABLE", "NET.DNS.FAILURE")

    def evaluate(self, store: ObservationStore) -> list[Symptom]:
        link = store.latest("net.wifi.link")
        link_state = (
            (link.value or {}).get("state") if link and isinstance(link.value, dict) else None
        )
        adapter_present = bool(store.field("net.wifi.adapter", "present"))
        if adapter_present and link_state != "connected":
            return []  # the link detector owns this fault

        internet = store.latest("net.connectivity.internet")
        gateway = store.latest("net.connectivity.gateway")
        dns = store.latest("net.connectivity.dns")
        if internet is None:
            return []

        gateway_value = gateway.value if gateway and isinstance(gateway.value, dict) else {}
        profile = store.value("net.connectivity.profile") or {}

        offline = _stable(store, "net.connectivity.internet", lambda v: v is False)
        if offline:
            gateway_ok = gateway_value.get("reachable")
            if gateway_ok is False:
                return [
                    self.symptom(
                        "NET.GATEWAY.UNREACHABLE",
                        severity=Severity.CRITICAL,
                        title="The router is not responding",
                        detail=(
                            f"Associated to a network, but the default gateway "
                            f"{gateway_value.get('address')} does not answer and no "
                            f"outside host is reachable."
                        ),
                        facts={
                            "gateway": gateway_value.get("address"),
                            "gateway_reachable": False,
                            "connection_profile": profile,
                            "ssid": as_dict(link.value).get("ssid") if link else None,
                        },
                        evidence=[*offline, gateway, link],
                    )
                ]
            return [
                self.symptom(
                    "NET.INTERNET.UNREACHABLE",
                    severity=Severity.WARN,
                    title="Connected to the network, but there is no internet",
                    detail=(
                        f"The gateway {gateway_value.get('address')} answers, so the local "
                        f"link is healthy, but nothing outside the network is reachable."
                    ),
                    facts={
                        "gateway": gateway_value.get("address"),
                        "gateway_reachable": True,
                        # The distinguishing fact: the fault is upstream of this
                        # machine, so no command run here can repair it.
                        "fault_is_upstream": True,
                        "connection_profile": profile,
                    },
                    evidence=[*offline, gateway],
                )
            ]

        broken_dns = _stable(
            store, "net.connectivity.dns", lambda v: (v or {}).get("resolves") is False
        )
        if broken_dns and internet.value is True:
            return [
                self.symptom(
                    "NET.DNS.FAILURE",
                    severity=Severity.WARN,
                    title="Names are not resolving",
                    detail=(
                        "Outside hosts are reachable by address, so the connection works, "
                        "but DNS lookups are failing."
                    ),
                    facts={
                        "probe_host": as_dict(dns.value).get("host") if dns else None,
                        "internet_reachable_by_ip": True,
                        "connection_profile": profile,
                    },
                    evidence=[*broken_dns, internet],
                )
            ]
        return []
