"""The action registry, and the map from symptom to candidate actions.

``CANDIDATES`` is where hardware-versus-software routing is written down as
data. A symptom mapped to an empty tuple is a symptom this software has decided
it cannot fix, and that decision lives here in the registry rather than in a
prompt, where it can be read, reviewed and tested. A language model cannot argue
Warden into running a command for an overheating laptop, because for that
symptom there is no command in the candidate set to choose.

The module-level consistency check runs at import: every symptom a detector can
raise must appear here. A finding nobody has thought about how to answer is a
gap, and it should break the build rather than surface at a demo.
"""

from __future__ import annotations

from warden.detectors import build_default_detectors
from warden.playbooks.base import (
    ActionRejected,
    NoParams,
    ParamBinder,
    ParamGuard,
    Playbook,
    PlaybookRegistry,
    render_argv,
)
from warden.playbooks.devices import DEVICE_PLAYBOOKS
from warden.playbooks.netconfig import NETCONFIG_PLAYBOOKS
from warden.playbooks.network import NETWORK_PLAYBOOKS
from warden.playbooks.predicates import PREDICATES, Predicate
from warden.playbooks.privacy import PRIVACY_PLAYBOOKS
from warden.playbooks.services import SERVICE_CANDIDATES, SERVICE_PLAYBOOKS
from warden.playbooks.timesync import TIME_PLAYBOOKS
from warden.playbooks.tuneup import TUNEUP_PLAYBOOKS

__all__ = [
    "CANDIDATES",
    "PREDICATES",
    "REGISTRY",
    "ActionRejected",
    "NoParams",
    "ParamBinder",
    "ParamGuard",
    "Playbook",
    "PlaybookRegistry",
    "Predicate",
    "render_argv",
]

REGISTRY = PlaybookRegistry(
    [
        *NETWORK_PLAYBOOKS,
        *DEVICE_PLAYBOOKS,
        *SERVICE_PLAYBOOKS,
        *PRIVACY_PLAYBOOKS,
        *NETCONFIG_PLAYBOOKS,
        *TUNEUP_PLAYBOOKS,
        *TIME_PLAYBOOKS,
    ]
)

#: Symptom code -> action ids that may be considered, best first.
#: An empty tuple is a deliberate statement, not an oversight.
CANDIDATES: dict[str, tuple[str, ...]] = {
    "NET.WIFI.DISCONNECTED": ("net.wifi.reconnect", "net.wifi.scan", "net.adapter.restart"),
    "NET.DNS.FAILURE": ("net.dns.flush",),
    "NET.GATEWAY.UNREACHABLE": ("net.dhcp.renew", "net.adapter.restart"),
    "DEV.DEVICE_FAULT": ("dev.driver.restart",),
    "SYS.DISK_LOW": ("sys.disk.temp_report",),
    # Printing, audio, Bluetooth, update, search and camera all reduce to
    # "start the service behind it", so they share one pair of actions.
    **SERVICE_CANDIDATES,
    # A black camera is usually a permission, not a fault. Try the setting
    # before touching the device.
    "CAM.BLOCKED_BY_PRIVACY": ("privacy.allow",),
    "MIC.BLOCKED_BY_PRIVACY": ("privacy.allow",),
    "CAM.DEVICE_DISABLED": ("cam.device.enable",),
    # Invisible misconfiguration: the cause is unfindable from the symptom,
    # and the fix is one command the user would never guess.
    "NET.PROFILE_PUBLIC_ON_TRUSTED": ("net.profile.private",),
    "NET.PROXY_CONFIGURED_BUT_OFFLINE": ("net.proxy.reset",),
    "NET.HOSTS_OVERRIDE": ("net.hosts.comment",),
    "TIME.NOT_SYNCHRONISED": ("time.resync",),
    # --- no software fix exists for these -------------------------------
    # The fault is upstream of this machine; nothing run here reaches it.
    "NET.INTERNET.UNREACHABLE": (),
    # A radio switched off in hardware or firmware is not software-addressable.
    "NET.WIFI.RADIO_OFF": (),
    # No adapter means no adapter.
    "NET.WIFI.NO_ADAPTER": (),
    # Heat is a physical quantity. No command cleans a heatsink.
    "THERMAL.SUSTAINED_THROTTLE": (),
    "THERMAL.HIGH_TEMPERATURE": (),
    # Capacity is a property of the cells. Software cannot add it back, and
    # anything claiming to "repair" a battery is lying.
    "POWER.BATTERY_WORN": (),
    # A drive that has flagged itself through SMART is failing hardware.
    "STORAGE.DISK_UNHEALTHY": (),
}


def candidate_actions(
    symptom_code: str,
    registry: PlaybookRegistry = REGISTRY,
    exclude: frozenset[str] = frozenset(),
) -> tuple[str, ...]:
    """Which reviewed actions may be considered for this symptom code.

    One function so that the prompt and the guardrail cannot disagree. The
    prompt module's first principle is that the model sees exactly what the
    guardrail will hold it to, and that only holds if both ask the same
    question.

    Three cases, and the third was missing:

    * A code **mapped to actions** gets those actions. The ordinary path.
    * A code **mapped to an empty tuple** gets nothing, deliberately. A worn
      battery has no software fix and no model confidence may invent one.
    * A code **absent from the map entirely** gets the whole registry.

    That third case is every problem a user describes in their own words, and
    it used to get nothing -- so the model composed a command from scratch even
    when Warden already owned a reviewed one. Measured: asked about a wrong
    clock it wrote `Set-Date -Date (Get-Date)`, which sets the clock to the time
    it already is, while `time.resync` sat in the registry with a predicate that
    proves whether it worked. Asked about Bluetooth, audio, the print spooler
    and search, it wrote four service restarts that `sys.service.restart`
    already covers, grounded and verifiable.

    A reviewed action is better than a composed one on every axis that matters:
    it was read by a person, it is bound to real readings, it declares a test
    that decides whether it worked, and it can be undone. Offering the registry
    here does not weaken the closed-registry guarantee -- the model still picks
    an id it cannot invent, and the guardrail still checks it.
    """
    if symptom_code in CANDIDATES:
        return tuple(a for a in CANDIDATES[symptom_code] if a not in exclude)
    return tuple(a for a in registry.ids if a not in exclude)


def _check_coverage() -> None:
    detectable = {code for d in build_default_detectors() for code in d.raises}
    unmapped = detectable - set(CANDIDATES)
    if unmapped:
        raise RuntimeError(
            f"detectors can raise {sorted(unmapped)} but CANDIDATES has no entry for them; "
            "every symptom needs a decision, including the decision that nothing can be run"
        )
    unknown_actions = {
        action for actions in CANDIDATES.values() for action in actions if action not in REGISTRY
    }
    if unknown_actions:
        raise RuntimeError(f"CANDIDATES references unregistered actions: {sorted(unknown_actions)}")
    missing_predicates = {
        p.verify.predicate.id for p in REGISTRY if p.verify.predicate.id not in PREDICATES
    }
    if missing_predicates:
        raise RuntimeError(f"playbooks reference unknown predicates: {sorted(missing_predicates)}")


_check_coverage()
