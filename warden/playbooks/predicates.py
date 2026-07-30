"""Named success conditions.

A playbook declares which predicate proves it worked, and the user sees that
declaration before approving. After the action runs, the verifier re-reads the
relevant collectors and evaluates the predicate against fresh observations.

Predicates return a tri-state. ``None`` means "could not tell" -- the collector
that would answer failed, or the data is missing -- and it is deliberately not
folded into ``False``. Reporting "the fix did not work" when the truth is "we
could not check" would be a lie of exactly the kind this project is built to
avoid.
"""

from __future__ import annotations

from collections.abc import Callable

from pydantic import JsonValue

from warden.collectors.services import status_name
from warden.store import ObservationStore, as_dict, as_float

#: (passed, human-readable detail). ``passed`` of None means inconclusive.
Predicate = Callable[[ObservationStore, dict[str, JsonValue]], tuple[bool | None, str]]


def wifi_associated(store: ObservationStore, args: dict[str, JsonValue]) -> tuple[bool | None, str]:
    link = store.latest("net.wifi.link")
    if link is None or not isinstance(link.value, dict):
        return None, "no wireless reading available to check"
    state = link.value.get("state")
    ssid = link.value.get("ssid")
    expected = args.get("profile")
    if state != "connected":
        return False, f"the adapter reports state {state!r}"
    if expected and ssid and expected != ssid and expected != link.value.get("profile"):
        return False, f"connected, but to {ssid!r} rather than {expected!r}"
    return True, f"associated to {ssid!r} at {link.value.get('signal_pct')}% signal"


def internet_reachable(
    store: ObservationStore, args: dict[str, JsonValue]
) -> tuple[bool | None, str]:
    observation = store.latest("net.connectivity.internet")
    if observation is None:
        return None, "no reachability reading available"
    if observation.value is True:
        return True, f"an outside host answered ({observation.provenance.probe})"
    return False, "no outside host answered"


def dns_resolves(store: ObservationStore, args: dict[str, JsonValue]) -> tuple[bool | None, str]:
    observation = store.latest("net.connectivity.dns")
    if observation is None or not isinstance(observation.value, dict):
        return None, "no DNS reading available"
    host = observation.value.get("host")
    if observation.value.get("resolves") is True:
        return True, f"{host} resolved"
    return False, f"{host} still does not resolve"


def gateway_reachable(
    store: ObservationStore, args: dict[str, JsonValue]
) -> tuple[bool | None, str]:
    observation = store.latest("net.connectivity.gateway")
    if observation is None or not isinstance(observation.value, dict):
        return None, "no gateway reading available"
    reachable = observation.value.get("reachable")
    address = observation.value.get("address")
    if reachable is None:
        return None, "no default gateway is configured to test"
    return bool(reachable), f"gateway {address} {'answered' if reachable else 'did not answer'}"


def device_healthy(store: ObservationStore, args: dict[str, JsonValue]) -> tuple[bool | None, str]:
    observation = store.latest("dev.problem_devices")
    if observation is None or not isinstance(observation.value, list):
        return None, "no device inventory available"
    device_id = args.get("device_id")
    still_faulted = [
        d for d in observation.value if isinstance(d, dict) and d.get("device_id") == device_id
    ]
    if still_faulted:
        problem = still_faulted[0]
        return False, f"still reporting problem code {problem.get('problem_code')}"
    return True, "the device no longer reports a problem code"


def service_running(store: ObservationStore, args: dict[str, JsonValue]) -> tuple[bool | None, str]:
    """Did the named Windows service actually come up?

    Checks the re-read service table rather than the command's exit code.
    ``Start-Service`` can return successfully for a service that then stops again
    a second later because a dependency is missing, which is precisely the case
    an exit code cannot distinguish from success.
    """
    observation = store.latest("sys.services")
    if observation is None or not isinstance(observation.value, list):
        return None, "no service reading is available to check"
    wanted = args.get("service")
    for raw in observation.value:
        if isinstance(raw, dict) and raw.get("name") == wanted:
            display = raw.get("display_name") or wanted
            if raw.get("status") == 4:
                return True, f"{display} is now running"
            return False, f"{display} is still {status_name(raw.get('status'))}"
    return None, f"{wanted} was not present in the service reading"


def privacy_allowed(store: ObservationStore, args: dict[str, JsonValue]) -> tuple[bool | None, str]:
    """Is the capability no longer denied, at the scope we changed?"""
    label = "camera" if args.get("capability") == "webcam" else "microphone"
    observation = store.latest(f"privacy.{label}")
    if observation is None or not isinstance(observation.value, dict):
        return None, f"no privacy reading for the {label} is available"
    scope = str(args.get("scope") or "user")
    value = observation.value.get(scope)
    if value == "Deny":
        return False, f"{label} access is still set to Deny at {scope} scope"
    return True, f"{label} access at {scope} scope is now {value or 'unset, which allows it'}"


def camera_enabled(store: ObservationStore, args: dict[str, JsonValue]) -> tuple[bool | None, str]:
    observation = store.latest("cam.devices")
    if observation is None or not isinstance(observation.value, list):
        return None, "no camera inventory is available"
    wanted = args.get("instance_id")
    for raw in observation.value:
        if isinstance(raw, dict) and raw.get("instance_id") == wanted:
            if raw.get("problem_code") == 22:
                return False, f"{raw.get('name')} is still disabled"
            return True, f"{raw.get('name')} reports status {raw.get('status')}"
    return None, "that camera is no longer in the device list"


def net_profile_private(
    store: ObservationStore, args: dict[str, JsonValue]
) -> tuple[bool | None, str]:
    observation = store.latest("net.profile")
    if observation is None or not isinstance(observation.value, list):
        return None, "no network profile reading is available"
    wanted = args.get("name")
    for raw in observation.value:
        if isinstance(raw, dict) and raw.get("name") == wanted:
            category = raw.get("category")
            if category == "public":
                return False, f"{wanted} is still categorised as public"
            return True, f"{wanted} is now categorised as {category}"
    return None, f"{wanted} is no longer among the visible networks"


def hosts_entry_cleared(
    store: ObservationStore, args: dict[str, JsonValue]
) -> tuple[bool | None, str]:
    observation = store.latest("net.hosts")
    if observation is None or not isinstance(observation.value, list):
        return None, "no hosts file reading is available"
    hostname = str(args.get("hostname") or "").lower()
    for raw in observation.value:
        if isinstance(raw, dict):
            hosts = raw.get("hosts")
            if isinstance(hosts, list) and any(str(h).lower() == hostname for h in hosts):
                return False, f"{hostname} is still active in the hosts file"
    return True, f"{hostname} is no longer overridden by the hosts file"


def time_synchronised(
    store: ObservationStore, args: dict[str, JsonValue]
) -> tuple[bool | None, str]:
    """Did the clock actually come under a time server's control?

    Checked by re-reading the reported source rather than by trusting w32tm's
    own output, which prints a success message in cases where the resync did
    not in fact take.
    """
    observation = store.latest("sys.time.sync")
    if observation is None or not isinstance(observation.value, dict):
        return None, "no clock reading is available"
    sync = observation.value
    if sync.get("free_running") or sync.get("never_synced"):
        return False, f"the clock is still running on {sync.get('source')}"
    return True, f"the clock is now synchronised against {sync.get('source')}"


def report_only(store: ObservationStore, args: dict[str, JsonValue]) -> tuple[bool | None, str]:
    """For READ_ONLY actions: success means the command produced its report.

    Nothing changed, so there is nothing to re-measure. The executor's exit code
    is the whole result, and pretending to verify a state change that was never
    attempted would be theatre.
    """
    return True, "information gathered; no system state was changed"


def storage_sense_on(
    store: ObservationStore, args: dict[str, JsonValue]
) -> tuple[bool | None, str]:
    """Windows now clears temporary files by itself."""
    observation = store.latest("audit.storage.reclaimable")
    if observation is None:
        return None, "no storage reading is available to check"
    if bool(as_dict(observation.value).get("storage_sense_on")):
        return True, "Storage Sense is on; Windows will clear temporary files on a schedule"
    return False, "Storage Sense still reads as off"


def processor_uncapped(
    store: ObservationStore, args: dict[str, JsonValue]
) -> tuple[bool | None, str]:
    """The processor may use its full speed on mains power again."""
    observation = store.latest("audit.power.profile")
    if observation is None:
        return None, "no power profile reading is available to check"
    ceiling = as_float(as_dict(observation.value).get("ac_max_pct"))
    if ceiling is None:
        return None, "Windows did not report a processor ceiling"
    if ceiling >= 100:
        return True, "the processor is allowed 100% of its speed on mains power"
    return False, f"the ceiling is still {ceiling:.0f}%"


PREDICATES: dict[str, Predicate] = {
    "wifi.associated": wifi_associated,
    "net.internet_reachable": internet_reachable,
    "net.dns_resolves": dns_resolves,
    "net.gateway_reachable": gateway_reachable,
    "device.healthy": device_healthy,
    "service.running": service_running,
    "privacy.allowed": privacy_allowed,
    "camera.enabled": camera_enabled,
    "net.profile_private": net_profile_private,
    "net.hosts_clear": hosts_entry_cleared,
    "time.synchronised": time_synchronised,
    "report.only": report_only,
    "tuneup.storage_sense_on": storage_sense_on,
    "tuneup.processor_uncapped": processor_uncapped,
}
