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
from warden.playbooks.network import NETWORK_PLAYBOOKS
from warden.playbooks.predicates import PREDICATES, Predicate

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

REGISTRY = PlaybookRegistry([*NETWORK_PLAYBOOKS, *DEVICE_PLAYBOOKS])

#: Symptom code -> action ids that may be considered, best first.
#: An empty tuple is a deliberate statement, not an oversight.
CANDIDATES: dict[str, tuple[str, ...]] = {
    "NET.WIFI.DISCONNECTED": ("net.wifi.reconnect", "net.wifi.scan", "net.adapter.restart"),
    "NET.DNS.FAILURE": ("net.dns.flush",),
    "NET.GATEWAY.UNREACHABLE": ("net.dhcp.renew", "net.adapter.restart"),
    "DEV.DEVICE_FAULT": ("dev.driver.restart",),
    "SYS.DISK_LOW": ("sys.disk.temp_report",),
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
}


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
