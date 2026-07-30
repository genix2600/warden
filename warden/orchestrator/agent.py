"""The agent loop: observe, reason, propose, wait, act, verify.

The loop never blocks on anything slow. Collectors run on a thread pool because
they are blocking I/O; a diagnosis runs as a detached task because a local model
can take twenty seconds and telemetry must keep flowing while it thinks;
execution and verification run on threads for the same reason. What stays on the
event loop is only bookkeeping.

Between "propose" and "act" there is no timer, no default and no automatic path.
The loop simply stops advancing that incident until a human answers. An incident
can sit in ``awaiting_approval`` forever, and if the underlying condition
resolves itself in the meantime the incident closes without ever having run
anything -- which is the correct outcome and one a scripted troubleshooter
never reaches.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from datetime import datetime

from warden.collectors import CollectorHost
from warden.contracts import (
    AgentLogEvent,
    AgentStatusEvent,
    Decision,
    DecisionEvent,
    DiagnosisReadyEvent,
    ExecutionFinishedEvent,
    ExecutionOutcome,
    ExecutionOutputEvent,
    ExecutionStartedEvent,
    Incident,
    IncidentClosedEvent,
    IncidentOpenedEvent,
    IncidentState,
    IncidentStateEvent,
    ProposalPendingEvent,
    Source,
    Symptom,
    SymptomClearedEvent,
    SymptomRaisedEvent,
    TelemetryEvent,
    Verdict,
    VerificationEvent,
    VerificationOutcome,
    utcnow,
)
from warden.contracts.state import AgentSnapshot, CollectorHealth, ReasonerHealth
from warden.detectors import DetectorBank
from warden.domains import DOMAIN_OF_SYMPTOM
from warden.executor import Executor, Verifier
from warden.orchestrator.bus import EventBus
from warden.playbooks import CANDIDATES
from warden.reasoner import Reasoner
from warden.store import ObservationStore
from warden.winenv import describe_host, is_admin

log = logging.getLogger(__name__)

#: Collectors too slow for the fast loop, force-run when an incident opens
#: because the half-minute before a fault is when the event log gets interesting.
_CONTEXT_COLLECTORS = ("sys.eventlog", "sys.devices", "sys.processes")

#: How long to leave a symptom alone after an incident for it has closed.
#:
#: The detector hysteresis stops a flapping measurement raising twice, but it
#: cannot help once an incident has genuinely finished: the old guard here only
#: suppressed a duplicate while the previous incident was *open*, so a symptom
#: that closed and came back opened a fresh incident and re-ran the model.
#:
#: The two numbers differ because the situations do. A fix that worked and then
#: stopped working is worth knowing about reasonably soon. A verdict the user
#: cannot act on -- a worn battery, a failing disk, throttling under load -- or
#: one they explicitly declined will produce the identical answer next time, so
#: asking again in thirty seconds is nagging rather than diligence.
_REOPEN_AFTER_S = 300.0
_REOPEN_AFTER_UNACTIONABLE_S = 1800.0


class Agent:
    def __init__(
        self,
        *,
        collectors: CollectorHost | None = None,
        detectors: DetectorBank | None = None,
        reasoner: Reasoner | None = None,
        store: ObservationStore | None = None,
        bus: EventBus | None = None,
        tick_s: float = 2.0,
    ) -> None:
        self.collectors = collectors or CollectorHost()
        self.detectors = detectors or DetectorBank()
        self.store = store or ObservationStore()
        self.bus = bus or EventBus()
        self.reasoner = reasoner or Reasoner()
        self.executor = Executor()
        self.verifier = Verifier(self.collectors, self.store)

        self.tick_s = tick_s
        self.tick = 0
        #: Whether a raised symptom should open an incident by itself.
        #:
        #: Off by default, and that is a product decision rather than a
        #: performance one. Warden watches everything it can, but not everyone
        #: cares about everything it finds: a machine with no printer does not
        #: want to be told about the spooler, and a network deliberately left
        #: Public should not interrupt anyone. Detection stays automatic and
        #: everything found is visible on the Health page; the reasoning and
        #: the proposal wait until someone asks for them.
        #:
        #: Turning this on restores the older behaviour for anyone who wants
        #: the agent to act on its own.
        self.autodiagnose = False
        self.monitoring = False
        self.warming = False
        self.started_at: datetime | None = None
        self.session_path: str | None = None

        self.incidents: dict[str, Incident] = {}
        self._incident_by_code: dict[str, str] = {}
        self._loop_task: asyncio.Task[None] | None = None
        self._warmup_task: asyncio.Task[None] | None = None
        self._diagnosis_tasks: set[asyncio.Task[None]] = set()
        # One action at a time. Two fixes racing on the same machine is a class
        # of bug nobody should have to debug at a demonstration.
        self._execution_lock = asyncio.Lock()
        self._collector_errors: dict[str, str] = {}
        #: Symptom code -> monotonic time before which it must not reopen.
        self._reopen_after: dict[str, float] = {}
        #: Symptom codes the user has silenced for good. Loaded from settings by
        #: the API layer at startup, so the agent stays free of file I/O.
        self.muted: set[str] = set()

    # -- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        """Begin monitoring. Returns immediately; warmup continues behind it.

        This used to await the warmup and the model probe inline, and because
        uvicorn does not open its listening socket until application startup
        returns, that meant the desktop window could not appear until both had
        finished. Measured on a fresh install: 45 seconds of no window at all.
        Not a slow window -- no window, a taskbar icon and doubt.

        The work has not got faster. It simply no longer happens in front of
        someone looking at nothing: the socket opens in milliseconds, the window
        appears, and the interface shows what it is doing while the collectors
        prime behind it.
        """
        if self.monitoring or self.warming:
            return
        self.warming = True
        self._publish_status()
        self._log("Starting up. Warming the Windows management interface.")
        self._warmup_task = asyncio.create_task(self._warm_up(), name="warden-warmup")

    async def _warm_up(self) -> None:
        """Pay the one-off startup costs, then start ticking."""
        try:
            await asyncio.to_thread(self.collectors.warmup)
            model = await self.reasoner.probe_model()
            self._log(
                f"Local model ready: {model}."
                if model
                else "No local model found. Diagnoses will use the built-in rules engine.",
                level="info" if model else "warn",
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            # A collector that cannot warm up is already reported as unhealthy
            # and the tick loop copes with it. Refusing to start monitoring
            # because one probe failed would be a far worse outcome than
            # starting with one source missing.
            log.warning("warmup did not finish cleanly; monitoring anyway", exc_info=True)

        # `warming` deliberately stays true here. The first tick clears it, once
        # there are readings on screen rather than merely a loop running.
        self.monitoring = True
        self.started_at = utcnow()
        self._loop_task = asyncio.create_task(self._run(), name="warden-agent-loop")
        self._publish_status()

    async def stop(self) -> None:
        self.monitoring = False
        self.warming = False
        # Cancelled first: a warmup still in flight would otherwise set
        # monitoring back to True after this returns, and start a tick loop
        # against collectors that are being closed underneath it.
        if self._warmup_task is not None:
            self._warmup_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._warmup_task
            self._warmup_task = None
        if self._loop_task is not None:
            self._loop_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._loop_task
            self._loop_task = None
        for task in list(self._diagnosis_tasks):
            task.cancel()
        await asyncio.to_thread(self.collectors.close)

    async def _run(self) -> None:
        while self.monitoring:
            started = asyncio.get_running_loop().time()
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("tick failed")
            elapsed = asyncio.get_running_loop().time() - started
            await asyncio.sleep(max(self.tick_s - elapsed, 0.1))

    # -- the loop ----------------------------------------------------------

    async def _tick(self) -> None:
        self.tick += 1
        due = self.collectors.due()
        result = await asyncio.to_thread(self.collectors.run, due)
        self.store.ingest(result.observations)

        # Startup is over when there is something to look at, not when the
        # warmup function returned. Measured: warmup finished at 4s but the
        # first tick did not land readings until 12s, so clearing the flag
        # early bought the user eight seconds of an empty dashboard with no
        # explanation -- which is the thing the warming screen exists to
        # prevent.
        if self.warming:
            self.warming = False
            self._publish_status()

        self._collector_errors = {e.source: e.message for e in result.errors}
        if result.observations or result.errors:
            self.bus.publish(TelemetryEvent(observations=result.observations, errors=result.errors))

        raised, cleared = self.detectors.evaluate(self.store)
        for code in cleared:
            self.bus.publish(SymptomClearedEvent(code=code))
            self._on_symptom_cleared(code)
        for symptom in raised:
            self.bus.publish(SymptomRaisedEvent(symptom=symptom))
            if self.autodiagnose:
                self._open_incident(symptom)

        if self.tick % 5 == 0:
            self._publish_status()

    def _on_symptom_cleared(self, code: str) -> None:
        """A detector stopped reporting a code. That is not the same as fixed.

        This method used to close any non-terminal incident as ``RESOLVED``,
        which the interface renders as *"Fixed and verified"* -- the only value
        it paints green. On an incident that had already run an action and
        failed verification, that produced a card whose green header contradicted
        the red chip directly beneath it, and a History line reading "Fixed and
        verified. the adapter reports state 'disconnected'".

        A code goes quiet for three reasons and only one of them is a fix:

        * the fault was repaired,
        * the same fault **re-classified** to a different code, which is exactly
          what happens when a radio switching off flips ``NET.WIFI.DISCONNECTED``
          to ``NET.WIFI.RADIO_OFF``, or
        * the collector missed two samples in ten seconds, so the detector could
          not confirm the condition and reported nothing, which is
          indistinguishable from health at this layer.

        Warden cannot tell them apart from the absence alone. So the rule is
        narrow, and it is the whole fix: **a vanished symptom may only close an
        incident that has never executed anything.** Once an action has run, the
        outcome belongs to the verifier and to nothing else.
        """
        incident_id = self._incident_by_code.get(code)
        if incident_id is None:
            return
        incident = self.incidents[incident_id]
        if incident.state.is_terminal:
            return
        if incident.state in (IncidentState.EXECUTING, IncidentState.VERIFYING):
            return  # the verifier owns the outcome; do not race it

        if incident.execution is not None or incident.history:
            incident.notes.append(
                f"{code} stopped being reported, but Warden had already run "
                f"something and could not confirm it worked. A symptom going "
                f"quiet is not evidence of a fix, so this is being left open "
                f"rather than called resolved."
            )
            self._log(
                f"{code} stopped being reported. Not closing it: an action ran "
                f"here and was not verified.",
                level="warn",
            )
            return

        incident.notes.append("The condition cleared before any action was taken.")
        self._close(incident, IncidentState.RESOLVED)
        self._incident_by_code.pop(code, None)
        self._log(f"{code} cleared on its own; closing the incident without acting.")
        self.bus.publish(IncidentClosedEvent(incident=incident))

    def check(self, domain_id: str | None = None) -> list[str]:
        """Diagnose what has been found, for one area or all of them.

        This is the on-demand half of the split. Detection runs continuously
        and everything it finds is already on the Health page; nothing reasons
        about a finding or proposes a fix until someone asks here.

        Returns the symptom codes it started work on, which is empty when the
        area is fine -- a distinction the interface needs, because "checked,
        nothing wrong" and "did not check" must not look the same.

        Asking again bypasses the reopen cooldown. The cooldown exists to stop
        Warden interrupting; a person clicking Check is not being interrupted.
        """
        wanted = [
            symptom
            for symptom in self.detectors.active
            if domain_id is None or DOMAIN_OF_SYMPTOM.get(symptom.code) == domain_id
        ]
        for symptom in wanted:
            self._reopen_after.pop(symptom.code, None)
            self._open_incident(symptom)
        return [s.code for s in wanted]

    def _open_incident(self, symptom: Symptom) -> None:
        existing = self._incident_by_code.get(symptom.code)
        if existing and not self.incidents[existing].state.is_terminal:
            return

        if symptom.code in self.muted:
            # Muted is stronger than the cooldown and survives a restart. The
            # user has said this is not a fault on their machine: a network they
            # keep Public on purpose, a clock they know is right. Warden keeps
            # detecting it and keeps showing it on the Health page, and stops
            # having an opinion about it.
            log.debug("%s is muted; not opening an incident", symptom.code)
            return

        until = self._reopen_after.get(symptom.code)
        if until is not None and time.monotonic() < until:
            # Recently dealt with. Still visible on the Health page -- this
            # suppresses the interruption, not the finding.
            log.debug("%s is in its reopen cooldown; not opening again", symptom.code)
            return
        incident = Incident(title=symptom.title, symptoms=[symptom])
        self.incidents[incident.id] = incident
        self._incident_by_code[symptom.code] = incident.id
        self._log(f"Detected: {symptom.title}", detail=symptom.detail, level="warn")
        self.bus.publish(IncidentOpenedEvent(incident=incident))

        task = asyncio.create_task(self._diagnose(incident), name=f"diagnose-{incident.id}")
        self._diagnosis_tasks.add(task)
        task.add_done_callback(self._diagnosis_tasks.discard)

    async def _diagnose(self, incident: Incident) -> None:
        try:
            self._set_state(incident, IncidentState.DIAGNOSING)
            self._log("Gathering context: event log, device tree, running processes.")
            context = await asyncio.to_thread(self.collectors.run_ids, list(_CONTEXT_COLLECTORS))
            self.store.ingest(context.observations)

            self._log(
                "Reasoning over the evidence."
                if not incident.attempted_actions
                else "Re-reasoning with what the last attempt taught us."
            )
            diagnosis = await self.reasoner.diagnose(
                incident.symptoms, self.store, frozenset(incident.attempted_actions)
            )
            incident.diagnosis = diagnosis
            self.bus.publish(DiagnosisReadyEvent(incident_id=incident.id, diagnosis=diagnosis))
            self._log(
                diagnosis.summary,
                detail=f"answered by the {diagnosis.reasoner.mode.value} reasoner",
            )

            if diagnosis.verdict is Verdict.ACTIONABLE and diagnosis.proposal is not None:
                self._set_state(incident, IncidentState.AWAITING_APPROVAL)
                self.bus.publish(
                    ProposalPendingEvent(incident_id=incident.id, proposal=diagnosis.proposal)
                )
                self._log(
                    "Waiting for your approval to run: "
                    + " ".join(diagnosis.proposal.rendered_argv)
                )
            elif diagnosis.verdict is Verdict.NEEDS_SERVICE:
                self._close(incident, IncidentState.NEEDS_SERVICE)
                self._log(
                    "No command can fix this. Routing to a physical fix instead.",
                    level="warn",
                )
                self.bus.publish(IncidentClosedEvent(incident=incident))
            else:
                self._set_state(incident, IncidentState.MONITORING)
                self._log("Not enough evidence to act on yet. Continuing to watch.")
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("diagnosis failed for incident %s", incident.id)
            incident.notes.append("The diagnosis failed unexpectedly; see the log.")
            self._set_state(incident, IncidentState.MONITORING)

    # -- the approval gate -------------------------------------------------

    async def decline(self, incident_id: str, *, mute: bool = False) -> Incident:
        """Refuse a proposal, optionally for good.

        ``mute`` is the answer to Warden asking the same question forever. Some
        findings are not faults on a particular machine: a network deliberately
        left Public, a clock that is right but has no time server to prove it.
        The cooldown alone treats those as "ask again in thirty minutes", which
        over a working day is still nagging, and nagging about a decision
        already made is how a tool teaches people to ignore it.
        """
        incident = self._require(incident_id, IncidentState.AWAITING_APPROVAL)
        incident.decision = Decision.DECLINED
        incident.decided_at = utcnow()
        if mute:
            codes = [s.code for s in incident.symptoms]
            self.muted.update(codes)
            incident.notes.append(
                "You declined this and asked not to be told about it again. "
                "Warden will keep detecting it and keep showing it on the Health "
                "page, and will not propose a fix for it."
            )
            self._log(f"Muted {', '.join(codes)}. Still watched, no longer proposed.")
        else:
            incident.notes.append("You declined the proposed fix. Nothing was run.")
        self._close(incident, IncidentState.DECLINED)
        proposal = incident.diagnosis.proposal if incident.diagnosis else None
        if proposal is not None:
            self.bus.publish(
                DecisionEvent(
                    incident_id=incident.id,
                    proposal_id=proposal.id,
                    decision=Decision.DECLINED,
                )
            )
        self._log("Declined. Nothing was run.")
        self.bus.publish(IncidentClosedEvent(incident=incident))
        self._forget(incident)
        return incident

    async def approve(self, incident_id: str) -> Incident:
        """The only entry point to the executor. Nothing else calls it."""
        incident = self._require(incident_id, IncidentState.AWAITING_APPROVAL)
        assert incident.diagnosis is not None and incident.diagnosis.proposal is not None
        proposal = incident.diagnosis.proposal

        approved_at = utcnow()
        incident.decision = Decision.APPROVED
        incident.decided_at = approved_at
        self.bus.publish(
            DecisionEvent(
                incident_id=incident.id,
                proposal_id=proposal.id,
                decision=Decision.APPROVED,
            )
        )

        async with self._execution_lock:
            self._set_state(incident, IncidentState.EXECUTING)
            self.bus.publish(
                ExecutionStartedEvent(incident_id=incident.id, argv=proposal.rendered_argv)
            )
            self._log(f"Running: {' '.join(proposal.rendered_argv)}")

            loop = asyncio.get_running_loop()

            def on_output(stream: str, text: str) -> None:
                # Called from the executor's reader threads.
                loop.call_soon_threadsafe(
                    self.bus.publish,
                    ExecutionOutputEvent(incident_id=incident.id, stream=stream, text=text),  # type: ignore[arg-type]
                )

            before = self.verifier.capture_before(proposal.verify)
            record = await asyncio.to_thread(
                self.executor.execute,
                proposal,
                approved_at=approved_at,
                on_output=on_output,
            )
            incident.execution = record

            if record.outcome is ExecutionOutcome.BLOCKED:
                incident.notes.append(record.blocked_reason or "The action was blocked.")
                self._close(incident, IncidentState.UNRESOLVED)
                self._log(f"Refused to run: {record.blocked_reason}", level="error")
                self.bus.publish(ExecutionFinishedEvent(incident_id=incident.id, record=record))
                self.bus.publish(IncidentClosedEvent(incident=incident))
                self._forget(incident)
                return incident

            self._set_state(incident, IncidentState.VERIFYING)
            self._log(f"Checking whether it worked: {proposal.verify.predicate.describe}")
            verification = await asyncio.to_thread(
                self.verifier.verify, proposal.verify, proposal.params, before
            )
            record.verification = verification
            record.outcome = (
                ExecutionOutcome.RESOLVED
                if verification.outcome is VerificationOutcome.PASSED
                else ExecutionOutcome.NOT_RESOLVED
            )
            self.bus.publish(VerificationEvent(incident_id=incident.id, result=verification))
            self.bus.publish(ExecutionFinishedEvent(incident_id=incident.id, record=record))

            if verification.outcome is VerificationOutcome.PASSED:
                self._close(incident, IncidentState.RESOLVED)
                self._log(f"Fixed, and verified: {verification.detail}")
                self.bus.publish(IncidentClosedEvent(incident=incident))
                self._forget(incident)
                return incident

            incident.notes.append(
                f"{proposal.action_id} ran but did not resolve the problem: {verification.detail}"
            )
            incident.attempted_actions.append(proposal.action_id)
            incident.history.append(record)
            self._log(f"That did not fix it: {verification.detail}", level="warn")

        # Outside the lock: escalating re-diagnoses, which may call the model.
        if self._can_escalate(incident):
            self._log("Trying the next step up rather than giving up.")
            await self._diagnose(incident)
            return incident

        self._close(incident, IncidentState.UNRESOLVED)
        self._log(
            "Everything Warden can safely try for this has been tried, and the problem "
            "is still present.",
            level="warn",
        )
        self.bus.publish(IncidentClosedEvent(incident=incident))
        self._forget(incident)
        return incident

    def _can_escalate(self, incident: Incident) -> bool:
        """Is there a gentler-to-harsher step left that has not been tried?

        Escalation is bounded by the candidate list in the registry, so it stops
        on its own rather than looping. Each step still needs its own approval --
        escalating changes what is proposed, never whether consent is required.
        """
        tried = set(incident.attempted_actions)
        return any(
            action not in tried
            for symptom in incident.symptoms
            for action in CANDIDATES.get(symptom.code, ())
        )

    def _forget(self, incident: Incident) -> None:
        for code in [c for c, i in self._incident_by_code.items() if i == incident.id]:
            self._incident_by_code.pop(code, None)

    def _require(self, incident_id: str, expected: IncidentState) -> Incident:
        incident = self.incidents.get(incident_id)
        if incident is None:
            raise KeyError(f"no incident {incident_id}")
        if incident.state is not expected:
            raise ValueError(
                f"incident {incident_id} is {incident.state.value}, not {expected.value}"
            )
        return incident

    # -- helpers -----------------------------------------------------------

    def _set_state(self, incident: Incident, state: IncidentState) -> None:
        incident.state = state
        if state.is_terminal:
            self._start_cooldown(incident, state)
        self.bus.publish(IncidentStateEvent(incident_id=incident.id, state=state))

    def _close(self, incident: Incident, state: IncidentState) -> None:
        """Close an incident **and** hold its symptom down afterwards.

        This exists because the cooldown did not work, and had never worked.
        ``_start_cooldown`` was reachable only through ``_set_state``, but every
        one of the six terminal transitions called ``Incident.close()`` directly,
        which sets the state on the model and knows nothing about the agent. So
        ``_reopen_after`` was written to by nothing, ``_REOPEN_AFTER_S`` and
        ``_REOPEN_AFTER_UNACTIONABLE_S`` were decorative, and a symptom that was
        still present simply reopened on the very next tick.

        The visible result was Warden asking to switch a network profile to
        private, being declined, and asking again seconds later, forever. The
        thirty-minute hold on a declined proposal was in the source the whole
        time and never once ran.
        """
        incident.close(state)
        self._start_cooldown(incident, state)

    def _start_cooldown(self, incident: Incident, state: IncidentState) -> None:
        """Hold this symptom's code down for a while now the incident is over."""
        unactionable = state in (
            IncidentState.NEEDS_SERVICE,
            IncidentState.DECLINED,
            IncidentState.UNRESOLVED,
        )
        window = _REOPEN_AFTER_UNACTIONABLE_S if unactionable else _REOPEN_AFTER_S
        until = time.monotonic() + window
        for symptom in incident.symptoms:
            self._reopen_after[symptom.code] = until

    def _log(self, text: str, detail: str | None = None, level: str = "info") -> None:
        self.bus.publish(AgentLogEvent(text=text, detail=detail, level=level))  # type: ignore[arg-type]

    def _publish_status(self) -> None:
        self.bus.publish(
            AgentStatusEvent(
                monitoring=self.monitoring,
                warming=self.warming,
                tick=self.tick,
                collectors_ok=[
                    c.id for c in self.collectors.collectors if c.id not in self._collector_errors
                ],
                collectors_failed=sorted(self._collector_errors),
                reasoner_available=self.reasoner.client.available,
                reasoner_model=self.reasoner.client.resolve_model(),
            )
        )

    def snapshot(self) -> AgentSnapshot:
        client = self.reasoner.client
        return AgentSnapshot(
            monitoring=self.monitoring,
            warming=self.warming,
            source=Source.LIVE,
            tick=self.tick,
            sequence=self.bus.sequence,
            started_at=self.started_at.isoformat() if self.started_at else None,
            host=describe_host(),
            elevated=is_admin(),
            telemetry=self.store.snapshot(),
            active_symptoms=self.detectors.active,
            incidents=sorted(self.incidents.values(), key=lambda i: i.opened_at, reverse=True)[:20],
            collectors=[
                CollectorHealth(
                    id=c.id,
                    description=c.description,
                    interval_s=c.interval_s,
                    healthy=c.id not in self._collector_errors,
                    last_error=self._collector_errors.get(c.id),
                )
                for c in self.collectors.collectors
            ],
            reasoner=ReasonerHealth(
                enabled=True,
                available=client.available,
                model=client.resolve_model(),
                endpoint=client.endpoint,
                note=(
                    ""
                    if client.available
                    else "Ollama is not running. Warden falls back to its rules engine, "
                    "which handles every scenario but writes shorter explanations."
                ),
            ),
            session_path=self.session_path,
        )
