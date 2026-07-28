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
from warden.store import ObservationStore

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


def report_only(store: ObservationStore, args: dict[str, JsonValue]) -> tuple[bool | None, str]:
    """For READ_ONLY actions: success means the command produced its report.

    Nothing changed, so there is nothing to re-measure. The executor's exit code
    is the whole result, and pretending to verify a state change that was never
    attempted would be theatre.
    """
    return True, "information gathered; no system state was changed"


PREDICATES: dict[str, Predicate] = {
    "wifi.associated": wifi_associated,
    "net.internet_reachable": internet_reachable,
    "net.dns_resolves": dns_resolves,
    "net.gateway_reachable": gateway_reachable,
    "device.healthy": device_healthy,
    "service.running": service_running,
    "report.only": report_only,
}
