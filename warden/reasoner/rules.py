"""The deterministic reasoner.

This is not a stub and it is not a placeholder for the model. It is the floor:
Warden must be able to diagnose and act with no language model present at all,
because the flagship scenario is a machine whose network is down, and a network
that is down is exactly when a remote model is least available. The local model
in ``ollama.py`` improves the *explanation* and the ranking; it is not load
bearing for correctness.

Everything here is a pure function of the symptom facts and the observation
store, so the same inputs always produce the same diagnosis. That is what makes
the demo repeatable and what lets ``tests/test_rules_reasoner.py`` pin the
behaviour of every symptom code.

Each handler encodes what a competent technician knows about one failure mode:
what usually causes it, what argues against the obvious answer, and -- most
importantly -- whether a command can fix it at all.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from warden.collectors.services import BY_NAME as _WATCHED_SERVICES
from warden.contracts import (
    ActionProposal,
    Diagnosis,
    Domain,
    Hypothesis,
    ReasonerInfo,
    ReasonerMode,
    ServiceAdvice,
    Severity,
    Symptom,
    Verdict,
)
from warden.playbooks import CANDIDATES, REGISTRY, ActionRejected, PlaybookRegistry
from warden.store import ObservationStore, as_dict, as_float

log = logging.getLogger(__name__)


@dataclass(slots=True)
class Draft:
    """A handler's conclusion, before it is turned into a proposal."""

    summary: str
    hypotheses: list[Hypothesis]
    advice: ServiceAdvice | None = None
    #: Restricts the candidate list further than CANDIDATES does, when the facts
    #: rule an action out. Empty means "use the registry's candidates in order".
    prefer: tuple[str, ...] = ()
    force_verdict: Verdict | None = None
    notes: list[str] = field(default_factory=list)


Handler = Callable[[Symptom, ObservationStore], Draft]


def _h(cause: str, domain: Domain, likelihood: float, reasoning: str) -> Hypothesis:
    return Hypothesis(cause=cause, domain=domain, likelihood=likelihood, reasoning=reasoning)


# --------------------------------------------------------------------------
# Network
# --------------------------------------------------------------------------


def _wifi_disconnected(symptom: Symptom, store: ObservationStore) -> Draft:
    facts = symptom.facts
    profile = facts.get("last_connected_profile")
    known = bool(facts.get("profile_is_saved")) or profile is not None
    down_for = facts.get("seconds_since_connected")

    hypotheses = [
        _h(
            f"The adapter dropped its association with {profile!r} and has not rejoined.",
            Domain.CONFIGURATION,
            0.7 if known else 0.4,
            (
                "The adapter is present and its radio is on, so the hardware is working. "
                "Windows sometimes fails to re-associate automatically after a brief signal "
                "loss or an access point restart."
            ),
        ),
        _h(
            "The network is out of range or its access point is down.",
            Domain.ENVIRONMENT,
            0.25,
            (
                f"Last observed signal was {facts.get('last_signal_pct')}%. If the access "
                "point has gone away, reconnecting will fail and the scan will show it "
                "missing -- which is itself the answer."
            ),
        ),
        _h(
            "The wireless driver has stopped responding.",
            Domain.DRIVER,
            0.1,
            (
                "Possible, but the adapter still reports its state cleanly, which a wedged "
                "driver usually does not. Worth trying only after a plain reconnect fails."
            ),
        ),
    ]
    summary = (
        f"Wireless has been disconnected for about {down_for} seconds. The adapter and "
        f"radio are both fine, so this looks like a dropped association rather than a "
        f"hardware fault."
        if down_for is not None
        else "Wireless is disconnected, and the adapter and radio are both healthy."
    )
    if not known:
        return Draft(
            summary=summary
            + " No previously used network was observed, so there is nothing to"
            + " reconnect to yet.",
            hypotheses=hypotheses,
            prefer=("net.wifi.scan",),
            notes=["no known profile to reconnect to; gathering more data instead"],
        )
    return Draft(summary=summary, hypotheses=hypotheses, prefer=("net.wifi.reconnect",))


def _wifi_radio_off(symptom: Symptom, store: ObservationStore) -> Draft:
    hardware_switch = bool(symptom.facts.get("hardware_switch"))
    return Draft(
        summary="The wireless radio is switched off, so no software fix applies.",
        hypotheses=[
            _h(
                "The radio has been turned off by a physical switch, a function key,"
                " or airplane mode.",
                Domain.HARDWARE if hardware_switch else Domain.CONFIGURATION,
                0.95,
                (
                    "Windows reports the radio as off rather than the adapter as failed. "
                    "A radio in this state is controlled by firmware and a physical control; "
                    "no command can override it."
                ),
            )
        ],
        advice=ServiceAdvice(
            reason=(
                "The wireless radio is disabled below the level software can reach. Warden "
                "will not pretend a command can turn it back on."
            ),
            who="user",
            next_step=(
                "Check for a physical wireless switch on the side or front edge of the laptop, "
                "try the function key with the aerial symbol, and make sure airplane mode is off "
                "in the Windows quick settings."
            ),
            urgency="soon",
        ),
        force_verdict=Verdict.NEEDS_SERVICE,
    )


def _wifi_no_adapter(symptom: Symptom, store: ObservationStore) -> Draft:
    return Draft(
        summary="No wireless adapter is visible to Windows at all.",
        hypotheses=[
            _h(
                "The wireless card has failed, come loose, or been disabled in firmware.",
                Domain.HARDWARE,
                0.7,
                "Windows enumerates no 802.11 device. A driver problem normally leaves a "
                "faulted device visible; a completely absent device points at hardware or BIOS.",
            ),
            _h(
                "The adapter is disabled in the BIOS or UEFI settings.",
                Domain.CONFIGURATION,
                0.3,
                "Worth checking before assuming failure, and free to check.",
            ),
        ],
        advice=ServiceAdvice(
            reason="There is no device present for any command to act on.",
            who="technician",
            next_step=(
                "Ask them to confirm the wireless card is seated and enabled in BIOS. "
                "Mention that Windows enumerates no 802.11 adapter at all, which narrows it "
                "to the card, its connector, or a firmware setting."
            ),
            interim_mitigation="A USB wireless adapter or a wired connection will work meanwhile.",
            urgency="soon",
        ),
        force_verdict=Verdict.NEEDS_SERVICE,
    )


def _gateway_unreachable(symptom: Symptom, store: ObservationStore) -> Draft:
    gateway = symptom.facts.get("gateway")
    return Draft(
        summary=(f"The machine is on the network but the router at {gateway} is not answering."),
        hypotheses=[
            _h(
                "The machine's address lease is stale or conflicts with another device.",
                Domain.CONFIGURATION,
                0.5,
                "Association succeeded but the first hop does not reply, which is the "
                "classic signature of an address that no longer fits the network.",
            ),
            _h(
                "The router itself has stopped responding or is rebooting.",
                Domain.ENVIRONMENT,
                0.4,
                "Equally consistent with the evidence. Renewing the lease is cheap and "
                "distinguishes the two: if the router is down, the renewal will also fail.",
            ),
        ],
        prefer=("net.dhcp.renew", "net.adapter.restart"),
    )


def _internet_unreachable(symptom: Symptom, store: ObservationStore) -> Draft:
    return Draft(
        summary=(
            "The local network is healthy -- the router answers -- but nothing beyond it "
            "is reachable. The fault is upstream of this machine."
        ),
        hypotheses=[
            _h(
                "The internet connection upstream of the router is down.",
                Domain.ENVIRONMENT,
                0.85,
                "The gateway responds, so this machine's networking stack, adapter and "
                "association are all working. Everything that is broken is on the other "
                "side of the router, where no command run here can reach.",
            ),
            _h(
                "A captive portal is intercepting traffic and waiting for a sign-in.",
                Domain.ENVIRONMENT,
                0.15,
                "Common on guest and hotel networks. Opening any page in a browser would "
                "reveal it.",
            ),
        ],
        advice=ServiceAdvice(
            reason=(
                "Every part of this machine's networking is verifiably working. The problem "
                "is on the far side of the router, so there is nothing here to fix."
            ),
            who="user",
            next_step=(
                "Check whether other devices on the same network can reach the internet. "
                "If none can, restart the router or contact the internet provider. If this "
                "is a guest network, open a browser and look for a sign-in page."
            ),
            urgency="routine",
        ),
        force_verdict=Verdict.NEEDS_SERVICE,
    )


def _dns_failure(symptom: Symptom, store: ObservationStore) -> Draft:
    return Draft(
        summary=(
            "The connection works -- outside hosts answer by address -- but name lookups "
            "are failing."
        ),
        hypotheses=[
            _h(
                "The resolver cache holds stale or bad entries.",
                Domain.CONFIGURATION,
                0.6,
                "Reachability by IP proves routing is fine, which isolates the fault to name "
                "resolution. A stale cache is both the most common cause and the cheapest to "
                "rule out.",
            ),
            _h(
                "The configured DNS server is not responding.",
                Domain.ENVIRONMENT,
                0.4,
                "If clearing the cache does not help, the server itself is the next suspect.",
            ),
        ],
        prefer=("net.dns.flush",),
    )


# --------------------------------------------------------------------------
# Thermal
# --------------------------------------------------------------------------


def _thermal(symptom: Symptom, store: ObservationStore) -> Draft:
    facts = symptom.facts
    performance = facts.get("mean_performance_pct")
    load = facts.get("mean_load_pct")
    temp = facts.get("max_temperature_c")
    process = facts.get("busiest_process")
    process_pct = facts.get("busiest_process_pct")
    temp_phrase = f", peaking at {temp:.0f} C" if isinstance(temp, int | float) else ""

    if facts.get("explained_by_running_software"):
        # A program is working hard and the machine is getting hot doing it.
        # That is a computer functioning correctly, and saying so is more useful
        # than manufacturing a fault.
        return Draft(
            summary=(
                f"The processor is running hot and below its rated speed{temp_phrase}, but "
                f"{process} is using {process_pct:.0f}% of the machine. This is the expected "
                f"behaviour of a laptop under sustained load, not a fault."
            ),
            hypotheses=[
                _h(
                    f"{process} is generating the load, and the machine is thermally "
                    f"limiting as designed.",
                    Domain.SOFTWARE,
                    0.8,
                    f"Delivered clock fell to {performance:.0f}% of rated while {process} held "
                    f"{process_pct:.0f}% of total CPU. Sustained all-core work legitimately "
                    f"exceeds what a thin chassis can dissipate; the processor slowing down is "
                    f"the protection working, not a failure of it.",
                ),
                _h(
                    "Cooling performance has degraded, and this workload is exposing it.",
                    Domain.HARDWARE,
                    0.2,
                    "Cannot be excluded from a single load period. It would be indicated by "
                    "the same throttling appearing at moderate load, or by the machine failing "
                    "to recover its clocks once the load stops.",
                ),
            ],
            advice=ServiceAdvice(
                reason=(
                    "The heat is being produced by a program that is running, so there is "
                    "nothing wrong for a command to repair."
                ),
                who="user",
                next_step=(
                    f"If you did not expect {process} to be this busy, close it and watch "
                    f"whether the clocks recover. If you did, no action is needed."
                ),
                urgency="routine",
            ),
            force_verdict=Verdict.NEEDS_SERVICE,
        )

    return Draft(
        summary=(
            f"Under sustained load the processor is delivering only {performance:.0f}% of its "
            f"rated speed{temp_phrase}, and no single program accounts for it. That points at "
            f"cooling, which is a physical problem."
        ),
        hypotheses=[
            _h(
                "Heat is not being carried away efficiently -- blocked vents, dust in the "
                "heatsink, or thermal compound past its life.",
                Domain.HARDWARE,
                0.75,
                f"The processor sat at {load:.0f}% busy yet could only hold {performance:.0f}% "
                f"of its rated clock, and no single process explains the load. That is the "
                f"signature of a cooling system that cannot remove the heat being produced. "
                f"None of those causes has a software remedy.",
            ),
            _h(
                "The machine is running in a hot environment or on a soft surface blocking "
                "its intakes.",
                Domain.ENVIRONMENT,
                0.2,
                "Free to rule out, and produces identical readings while it lasts.",
            ),
            _h(
                "A power or firmware profile is capping the processor deliberately.",
                Domain.CONFIGURATION,
                0.05,
                "Would produce a steadier cap rather than load-dependent throttling, so it "
                "fits the evidence less well.",
            ),
        ],
        advice=ServiceAdvice(
            reason=(
                "Overheating is a physical condition. There is no command that cleans a "
                "heatsink or replaces thermal compound, and Warden will not offer one."
            ),
            who="technician",
            next_step=(
                f"Ask for the fans and heatsink to be cleaned and the thermal compound "
                f"replaced. Tell them the processor holds only {performance:.0f}% of its rated "
                f"clock under sustained load"
                + (f" at {temp:.0f} C" if isinstance(temp, int | float) else "")
                + " with no single process responsible."
            ),
            interim_mitigation=(
                "Use the machine on a hard flat surface, keep the vents clear, and expect "
                "reduced performance during long tasks until it is serviced."
            ),
            urgency="soon",
        ),
        force_verdict=Verdict.NEEDS_SERVICE,
    )


# --------------------------------------------------------------------------
# Devices and storage
# --------------------------------------------------------------------------


def _device_fault(symptom: Symptom, store: ObservationStore) -> Draft:
    facts = symptom.facts
    name = facts.get("first_recoverable_name")
    recoverable = int(as_float(facts.get("recoverable_count")) or 0)
    if not recoverable:
        return Draft(
            summary=(
                f"{facts.get('fault_count')} device(s) are reporting faults, but none of them "
                f"are the kind that a restart clears."
            ),
            hypotheses=[
                _h(
                    "The device has failed, been removed, or needs a driver that is not installed.",
                    Domain.HARDWARE,
                    0.6,
                    "The reported problem codes are not the transient kind that a device "
                    "restart resolves.",
                )
            ],
            advice=ServiceAdvice(
                reason="The reported problem codes do not respond to a device restart.",
                who="user",
                next_step=(
                    "Open Device Manager, find the flagged device, and check whether a driver "
                    "is available from the manufacturer's support page for this model."
                ),
                urgency="routine",
            ),
            force_verdict=Verdict.NEEDS_SERVICE,
        )
    return Draft(
        summary=f"{name} is reporting a fault that a device restart often clears.",
        hypotheses=[
            _h(
                f"{name} has entered an error state its driver can recover from.",
                Domain.DRIVER,
                0.6,
                "The Configuration Manager problem code is one of the transient family, "
                "which usually clears when the device is stopped and restarted.",
            ),
            _h(
                "The device or its connection has a physical fault.",
                Domain.HARDWARE,
                0.4,
                "If the restart does not clear the code, this becomes the leading "
                "explanation and the answer stops being a software one.",
            ),
        ],
        prefer=("dev.driver.restart",),
    )


def _disk_low(symptom: Symptom, store: ObservationStore) -> Draft:
    worst = as_dict(symptom.facts.get("worst"))
    return Draft(
        summary=(
            f"Drive {worst.get('mount')} has {worst.get('free_gb')} GB free. Windows needs "
            f"headroom for updates and paging, and gets slow without it."
        ),
        hypotheses=[
            _h(
                "Accumulated temporary files, update caches and downloads are holding the space.",
                Domain.CONFIGURATION,
                0.7,
                "The usual cause on a machine that filled up gradually rather than suddenly.",
            ),
            _h(
                "User data has simply grown to fill the drive.",
                Domain.ENVIRONMENT,
                0.3,
                "Distinguished by measuring the temporary folders first, which is free and "
                "changes nothing.",
            ),
        ],
        prefer=("sys.disk.temp_report",),
    )


# --------------------------------------------------------------------------
# Physical wear
# --------------------------------------------------------------------------


def _battery_worn(symptom: Symptom, store: ObservationStore) -> Draft:
    facts = symptom.facts
    health = as_float(facts.get("health_pct")) or 0.0
    cycles = as_float(facts.get("cycle_count"))
    loss = as_float(facts.get("runtime_reduction_pct")) or 0.0
    expected = bool(facts.get("wear_is_expected_for_age"))
    cycle_phrase = f" over {cycles:.0f} charge cycles" if cycles else ""

    return Draft(
        summary=(
            f"The battery now holds {health:.0f}% of the capacity it shipped with"
            f"{cycle_phrase}, so you are getting roughly {loss:.0f}% less time on a "
            f"charge than when the machine was new. Nothing on the computer can "
            f"restore that."
        ),
        hypotheses=[
            _h(
                "The battery cells have aged, which every lithium battery does.",
                Domain.HARDWARE,
                0.9 if expected else 0.75,
                (
                    f"Capacity has fallen to {health:.0f}% of design{cycle_phrase}. "
                    + (
                        "That is normal wear for this many cycles rather than a fault."
                        if expected
                        else "That is more loss than the cycle count alone would explain, "
                        "which can point at sustained heat or long periods held at full charge."
                    )
                ),
            ),
            _h(
                "The battery reports its capacity incorrectly after a firmware or "
                "calibration issue.",
                Domain.HARDWARE,
                0.1,
                "Uncommon, and distinguished by a full discharge-and-recharge cycle "
                "changing the reported figure. Worth mentioning before paying for a "
                "replacement.",
            ),
        ],
        advice=ServiceAdvice(
            reason=(
                "Battery capacity is a physical property of the cells. There is no "
                "setting, driver or command that adds capacity back, and any software "
                "claiming to 'repair' a battery is not telling the truth."
            ),
            who="technician",
            next_step=(
                f"Ask for a battery replacement and quote the measurement: "
                f"{facts.get('full_charge_mwh')} mWh full charge against a "
                f"{facts.get('design_mwh')} mWh design capacity"
                + (f" at {cycles:.0f} cycles" if cycles else "")
                + ". That is the number a service centre will check for themselves."
            ),
            interim_mitigation=(
                "Keep the charger with you, and expect the remaining-time estimate to "
                "be optimistic. Avoid leaving it at 100% on mains for long periods, "
                "which accelerates the remaining wear."
            ),
            urgency="routine" if health >= 60 else "soon",
        ),
        force_verdict=Verdict.NEEDS_SERVICE,
    )


def _disk_unhealthy(symptom: Symptom, store: ObservationStore) -> Draft:
    facts = symptom.facts
    name = facts.get("name")
    return Draft(
        summary=(
            f"{name} is reporting a hardware fault through its own health monitoring. "
            f"Back up anything you care about now, before doing anything else."
        ),
        hypotheses=[
            _h(
                "The drive is failing and has flagged itself.",
                Domain.HARDWARE,
                0.85,
                (
                    f"The storage stack reports {facts.get('health')!r} for this drive. "
                    "That status comes from the drive's own SMART monitoring, which "
                    "reports a problem only after its internal thresholds have been "
                    "crossed. It is not a guess by Warden."
                ),
            ),
            _h(
                "A connection or controller fault is making a healthy drive look bad.",
                Domain.HARDWARE,
                0.15,
                "Possible, particularly for a drive on a cable rather than soldered "
                "down, and worth a technician checking before the drive is replaced.",
            ),
        ],
        advice=ServiceAdvice(
            reason=(
                "A drive reporting a SMART fault is failing hardware. No command "
                "repairs failing storage, and continuing to write to it risks the data "
                "still on it."
            ),
            who="technician",
            next_step=(
                f"Tell them the drive is a {facts.get('size_gb')} GB "
                f"{facts.get('media_type')} reporting health status "
                f"{facts.get('health')!r}, and ask for it to be replaced and the data "
                f"migrated. Bring a backup with you in case it fails during the work."
            ),
            interim_mitigation=(
                "Copy your important files to another drive or cloud storage today. "
                "Treat every start-up from now on as possibly the last one."
            ),
            urgency="urgent",
        ),
        force_verdict=Verdict.NEEDS_SERVICE,
    )


# --------------------------------------------------------------------------
# Windows services
# --------------------------------------------------------------------------


def _service_stopped(symptom: Symptom, store: ObservationStore) -> Draft:
    """One handler for six subsystems, because the reasoning genuinely is the same.

    The distinction that matters is disabled versus merely stopped: a disabled
    service will refuse to start, and even if forced it would not come back after
    a reboot, so the two need different actions and different explanations.
    """
    facts = symptom.facts
    subsystem = facts.get("subsystem")
    display = facts.get("display_name")
    disabled = bool(facts.get("is_disabled"))
    consequence = facts.get("consequence")

    if disabled:
        return Draft(
            summary=(
                f"Your {subsystem} is not working because the Windows service behind "
                f"it has been switched off entirely, which means {consequence}. It "
                f"will not come back on its own, or after a restart."
            ),
            hypotheses=[
                _h(
                    f"{display} was set to Disabled, by an administrator, a "
                    f"clean-up utility, or an installer.",
                    Domain.CONFIGURATION,
                    0.8,
                    (
                        "A disabled service is a deliberate setting rather than a "
                        "crash -- Windows does not disable services by itself. "
                        '"Optimiser" tools frequently disable this one to make a '
                        "start-up list look shorter."
                    ),
                ),
                _h(
                    "A policy set by an organisation is enforcing it off.",
                    Domain.CONFIGURATION,
                    0.2,
                    "Likely on a work or school machine, and if so Warden's change "
                    "will be reverted the next time policy is applied.",
                ),
            ],
            prefer=("sys.service.enable",),
        )

    return Draft(
        summary=(
            f"Your {subsystem} is not working because the Windows service behind it "
            f"has stopped, which means {consequence}. It is set to start "
            f"automatically, so it stopping is not normal."
        ),
        hypotheses=[
            _h(
                f"{display} stopped or crashed and Windows did not restart it.",
                Domain.SOFTWARE,
                0.7,
                (
                    "The service is configured to start automatically but is not "
                    "running, so something stopped it. Starting it again is both the "
                    "diagnosis and the fix -- if it stays up, that was the whole "
                    "problem."
                ),
            ),
            _h(
                "Something it depends on failed, and it stopped as a consequence.",
                Domain.SOFTWARE,
                0.2,
                "Distinguished cheaply: if it stops again immediately after being "
                "started, the cause is underneath it rather than in the service itself.",
            ),
            _h(
                "A driver or device the service needs has failed.",
                Domain.DRIVER,
                0.1,
                "More likely for audio, Bluetooth and camera than for printing or "
                "search, and would show up as a faulted device as well.",
            ),
        ],
        prefer=("sys.service.restart",),
    )


HANDLERS: dict[str, Handler] = {
    "POWER.BATTERY_WORN": _battery_worn,
    "STORAGE.DISK_UNHEALTHY": _disk_unhealthy,
    "NET.WIFI.DISCONNECTED": _wifi_disconnected,
    "NET.WIFI.RADIO_OFF": _wifi_radio_off,
    "NET.WIFI.NO_ADAPTER": _wifi_no_adapter,
    "NET.GATEWAY.UNREACHABLE": _gateway_unreachable,
    "NET.INTERNET.UNREACHABLE": _internet_unreachable,
    "NET.DNS.FAILURE": _dns_failure,
    "THERMAL.SUSTAINED_THROTTLE": _thermal,
    "THERMAL.HIGH_TEMPERATURE": _thermal,
    "DEV.DEVICE_FAULT": _device_fault,
    "SYS.DISK_LOW": _disk_low,
    # Six subsystems, one handler. Built from the same table the collector and
    # the candidate map use, so a new watched service needs no change here.
    **dict.fromkeys(
        (service.symptom_code for service in _WATCHED_SERVICES.values()), _service_stopped
    ),
}


def primary_symptom(symptoms: list[Symptom]) -> Symptom:
    """The one to answer when several are present.

    Severity first, then detector order. Root-cause suppression in the detector
    layer means it is rare for two unrelated criticals to coexist, and when they
    do, answering the more severe one first is the right instinct.
    """
    order = {Severity.CRITICAL: 0, Severity.WARN: 1, Severity.INFO: 2}
    return sorted(symptoms, key=lambda s: (order[s.severity], s.observed_at))[0]


class RulesReasoner:
    """Deterministic diagnosis. Always available, never blocks, never guesses."""

    def __init__(self, registry: PlaybookRegistry = REGISTRY) -> None:
        self._registry = registry

    def diagnose(
        self,
        symptoms: list[Symptom],
        store: ObservationStore,
        exclude: frozenset[str] = frozenset(),
    ) -> Diagnosis:
        symptom = primary_symptom(symptoms)
        handler = HANDLERS.get(symptom.code)
        draft = (
            handler(symptom, store)
            if handler
            else Draft(
                summary=symptom.title,
                hypotheses=[
                    _h(
                        symptom.detail or symptom.title,
                        Domain.SOFTWARE,
                        0.5,
                        "No specific knowledge is registered for this symptom code.",
                    )
                ],
                force_verdict=Verdict.NEEDS_MORE_DATA,
            )
        )
        if exclude:
            draft.summary = (
                f"{draft.summary} The previous fix did not hold, so this is the next step up."
            )
        return assemble(
            symptom,
            draft,
            store,
            self._registry,
            ReasonerInfo(mode=ReasonerMode.RULES),
            exclude=exclude,
        )


def assemble(
    symptom: Symptom,
    draft: Draft,
    store: ObservationStore,
    registry: PlaybookRegistry,
    reasoner: ReasonerInfo,
    proposal: ActionProposal | None = None,
    exclude: frozenset[str] = frozenset(),
) -> Diagnosis:
    """Turn a draft into a validated Diagnosis, building a proposal if one fits.

    Shared by the rules path and the model path so that both produce diagnoses
    with identical structure and identical guarantees. The model never gets its
    own route to a proposal.
    """
    notes = list(reasoner.guardrail_rejections)
    notes.extend(draft.notes)

    if proposal is None and draft.force_verdict is None:
        proposal, rejections = build_proposal(symptom, draft, store, registry, exclude)
        notes.extend(rejections)

    if draft.force_verdict is Verdict.NEEDS_SERVICE and draft.advice is not None:
        verdict, proposal = Verdict.NEEDS_SERVICE, None
    elif proposal is not None:
        verdict = Verdict.ACTIONABLE
    elif draft.advice is not None:
        verdict = Verdict.NEEDS_SERVICE
    else:
        verdict = draft.force_verdict or Verdict.NEEDS_MORE_DATA

    return Diagnosis(
        symptom_codes=[symptom.code],
        summary=draft.summary,
        ranked_hypotheses=sorted(draft.hypotheses, key=lambda h: h.likelihood, reverse=True),
        verdict=verdict,
        service_advice=draft.advice if verdict is Verdict.NEEDS_SERVICE else None,
        proposal=proposal,
        reasoner=reasoner.model_copy(update={"guardrail_rejections": notes}),
    )


def build_proposal(
    symptom: Symptom,
    draft: Draft,
    store: ObservationStore,
    registry: PlaybookRegistry,
    exclude: frozenset[str] = frozenset(),
) -> tuple[ActionProposal | None, list[str]]:
    """Try each candidate action in order until one validates and grounds.

    An action whose guard refuses is not an error: it is Warden declining to do
    something it cannot justify, and the reason is kept so the UI can show why
    the obvious fix was not offered.

    ``exclude`` carries the actions already tried on this incident and verified
    as not having worked. Candidates are ordered gentlest-first, so skipping the
    exhausted ones is what turns a single-shot fix into an escalation: reconnect,
    then scan, then restart the adapter.
    """
    # A candidate list that starts with the handler's preference still falls
    # through to the registry order once that preference is exhausted, so
    # escalation keeps working after the obvious fix fails.
    ordered = list(dict.fromkeys([*draft.prefer, *CANDIDATES.get(symptom.code, ())]))
    candidates = [a for a in ordered if a not in exclude]
    rejections: list[str] = []
    for action_id in candidates:
        try:
            playbook = registry.get(action_id)
            params = playbook.bind(symptom, store)
            return (
                playbook.propose(
                    params,
                    store,
                    rationale=draft.hypotheses[0].reasoning if draft.hypotheses else draft.summary,
                ),
                rejections,
            )
        except ActionRejected as exc:
            rejections.append(str(exc))
            log.info("candidate %s not usable: %s", action_id, exc)
    return None, rejections
