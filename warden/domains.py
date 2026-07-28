"""The machine as a person thinks about it, rather than as the code does.

Internally Warden has collectors with ids like ``sys.privacy`` and symptom codes
like ``CAM.BLOCKED_BY_PRIVACY``. Those are the right names for the code and the
wrong names for a user, who does not have a mental model containing "collectors"
and would describe the same thing as "my camera".

This module is the translation layer, and it is data rather than logic so that
the whole surface a user sees can be reviewed in one screenful. Each domain names
the collectors that feed it and the symptoms that belong to it; health is then
derived, never stored, so it cannot drift from what the detectors actually found.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from warden.contracts import Severity, Symptom
from warden.contracts.state import CollectorHealth


@dataclass(frozen=True, slots=True)
class Domain:
    id: str
    label: str
    #: One line, in the words a user would use to describe the thing breaking.
    blurb: str
    #: Rendered in the interface. Kept here so the mapping is in one place.
    icon: str
    collectors: tuple[str, ...]
    symptoms: tuple[str, ...]
    #: Sources whose latest value is worth showing on the domain's card.
    highlights: tuple[str, ...] = field(default_factory=tuple)


DOMAINS: tuple[Domain, ...] = (
    Domain(
        id="network",
        label="Internet & Wi-Fi",
        blurb="Whether you are connected, and whether anything actually loads.",
        icon="wifi",
        collectors=("net.wifi", "net.connectivity", "net.config"),
        symptoms=(
            "NET.WIFI.DISCONNECTED",
            "NET.WIFI.RADIO_OFF",
            "NET.WIFI.NO_ADAPTER",
            "NET.GATEWAY.UNREACHABLE",
            "NET.INTERNET.UNREACHABLE",
            "NET.DNS.FAILURE",
            "NET.PROXY_CONFIGURED_BUT_OFFLINE",
            "NET.HOSTS_OVERRIDE",
        ),
        highlights=("net.wifi.link", "net.connectivity.internet", "net.wifi.signal_pct"),
    ),
    Domain(
        id="sharing",
        label="Sharing & Discovery",
        blurb="Whether this machine can see shared printers and other computers.",
        icon="share",
        collectors=("net.config",),
        symptoms=("NET.PROFILE_PUBLIC_ON_TRUSTED",),
        highlights=("net.profile",),
    ),
    Domain(
        id="printing",
        label="Printing",
        blurb="Whether print jobs can reach a printer at all.",
        icon="printer",
        collectors=("sys.services",),
        symptoms=("PRINT.SPOOLER_STOPPED",),
    ),
    Domain(
        id="sound",
        label="Sound",
        blurb="Whether anything can play audio.",
        icon="speaker",
        collectors=("sys.services",),
        symptoms=("AUDIO.SERVICE_STOPPED",),
    ),
    Domain(
        id="camera",
        label="Camera & Microphone",
        blurb="Whether apps are allowed to see and hear you, and whether the hardware works.",
        icon="camera",
        collectors=("sys.privacy", "sys.services"),
        symptoms=(
            "CAM.BLOCKED_BY_PRIVACY",
            "MIC.BLOCKED_BY_PRIVACY",
            "CAM.DEVICE_DISABLED",
            "CAM.SERVICE_STOPPED",
        ),
        highlights=("privacy.camera", "privacy.microphone", "cam.devices"),
    ),
    Domain(
        id="bluetooth",
        label="Bluetooth",
        blurb="Whether wireless headphones, mice and keyboards can connect.",
        icon="bluetooth",
        collectors=("sys.services",),
        symptoms=("BT.SERVICE_STOPPED",),
    ),
    Domain(
        id="updates",
        label="Windows Update",
        blurb="Whether security updates are still arriving.",
        icon="download",
        collectors=("sys.services",),
        symptoms=("UPDATE.SERVICE_STOPPED",),
    ),
    Domain(
        id="search",
        label="Search",
        blurb="Whether the Start menu and File Explorer can find your files.",
        icon="search",
        collectors=("sys.services",),
        symptoms=("SEARCH.SERVICE_STOPPED",),
    ),
    Domain(
        id="battery",
        label="Battery",
        blurb="How much of its original capacity the battery still holds.",
        icon="battery",
        collectors=("hw.battery",),
        symptoms=("POWER.BATTERY_WORN",),
        highlights=("hw.battery.health", "hw.battery.charge"),
    ),
    Domain(
        id="storage",
        label="Storage",
        blurb="Drive health, and whether there is room left to work in.",
        icon="drive",
        collectors=("hw.storage", "sys.perf"),
        symptoms=("STORAGE.DISK_UNHEALTHY", "SYS.DISK_LOW"),
        highlights=("hw.storage.disks", "sys.disk.volumes"),
    ),
    Domain(
        id="performance",
        label="Speed & Temperature",
        blurb="Whether the processor is being held back by heat.",
        icon="gauge",
        collectors=("thermal", "sys.perf", "sys.processes"),
        symptoms=("THERMAL.SUSTAINED_THROTTLE", "THERMAL.HIGH_TEMPERATURE"),
        highlights=("cpu.performance_pct", "thermal.cpu_c", "sys.cpu.percent", "cpu.clock"),
    ),
    Domain(
        id="devices",
        label="Devices & Drivers",
        blurb="Hardware Windows has flagged as not working.",
        icon="chip",
        collectors=("sys.devices",),
        symptoms=("DEV.DEVICE_FAULT",),
        highlights=("dev.problem_devices",),
    ),
    Domain(
        id="clock",
        label="Clock",
        blurb="Whether the time is being kept correct, which secure websites depend on.",
        icon="clock",
        collectors=("sys.time",),
        symptoms=("TIME.NOT_SYNCHRONISED",),
        highlights=("sys.time.sync",),
    ),
)

BY_ID = {domain.id: domain for domain in DOMAINS}

#: Symptom code -> the domain a user would file it under.
DOMAIN_OF_SYMPTOM = {code: domain.id for domain in DOMAINS for code in domain.symptoms}


def domain_for(symptom_code: str) -> Domain | None:
    domain_id = DOMAIN_OF_SYMPTOM.get(symptom_code)
    return BY_ID.get(domain_id) if domain_id else None


def unmapped_symptoms(known: set[str]) -> set[str]:
    """Symptom codes no domain claims.

    Called by the coverage test: a symptom with no domain would be detected,
    diagnosed and then displayed nowhere, which is a worse failure than not
    detecting it at all.
    """
    return known - set(DOMAIN_OF_SYMPTOM)


def summarise(
    domain: Domain,
    active: list[Symptom],
    collectors: dict[str, CollectorHealth],
) -> tuple[str, str]:
    """Return (state, plain-English one-liner) for a domain.

    States are deliberately few. A user does not need seven gradations; they
    need to know whether to look at something. "unknown" is kept distinct from
    "ok" because a collector that failed is not evidence of health -- claiming
    otherwise is the specific dishonesty this whole project argues against.
    """
    mine = [s for s in active if s.code in domain.symptoms]
    if mine:
        worst = min(mine, key=lambda s: {"critical": 0, "warn": 1, "info": 2}[s.severity.value])
        if worst.severity is Severity.CRITICAL:
            return "problem", worst.title
        if worst.severity is Severity.WARN:
            return "attention", worst.title
        return "note", worst.title

    watching = [collectors[c] for c in domain.collectors if c in collectors]
    if watching and all(not c.healthy for c in watching):
        return "unknown", "Warden could not read this, so it cannot say."
    if not watching:
        return "unknown", "Not being watched on this machine."
    return "ok", "Working normally."
