"""HTTP and WebSocket surface.

Bound to loopback only. Warden reads a machine's event log, device inventory and
network configuration; none of that should be reachable from the network the
machine is attached to, and the simplest way to guarantee it is to never listen
anywhere else.

The API is deliberately thin. It holds no diagnostic logic -- routes read agent
state, or hand a decision to the agent, and that is all. Everything interesting
happens behind ``Agent``, which is testable without starting a server.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from warden import credentials, settings
from warden.audit import run_audit
from warden.audit.apply import apply as apply_recommendation_action
from warden.audit.apply import describe_change
from warden.contracts import (
    ActionSpec,
    AgentEvent,
    AgentLogEvent,
    AuditReport,
    Incident,
    Severity,
    Symptom,
)
from warden.contracts.state import AgentSnapshot, DomainHealth
from warden.demo import DemoHarness
from warden.domains import DOMAINS, summarise
from warden.executor.restore import describe as describe_restore
from warden.orchestrator import Agent, SessionRecorder
from warden.paths import resource_path
from warden.playbooks import CANDIDATES, REGISTRY
from warden.reasoner import GroqClient
from warden.reasoner.host import ModelHost, has_weights
from warden.reasoner.llm import DEFAULT_MODEL
from warden.settings import Settings
from warden.winenv import describe_host, is_admin, is_frozen, relaunch_elevated

log = logging.getLogger(__name__)

UI_DIST = resource_path("ui", "dist")


class ScenarioResponse(BaseModel):
    scenario: str
    started: bool
    detail: str


class DoctorCheck(BaseModel):
    name: str
    ok: bool
    detail: str
    blocking: bool = Field(description="Whether a live demonstration is impossible without this.")


class DoctorReport(BaseModel):
    ready: bool
    checks: list[DoctorCheck]


class RelaunchResponse(BaseModel):
    started: bool
    detail: str


class AuditApplied(BaseModel):
    """The result of applying or reverting one recommendation.

    ``change`` is willing to say "No measurable change yet", and the interface
    shows that as prominently as an improvement. Several of these settings take
    days to show an effect, so an immediate zero is expected rather than a
    failure, and claiming a win at the moment of the click would be the exact
    unfalsifiable promise this whole subsystem argues against.
    """

    ok: bool
    detail: str
    change: str = ""
    reverted: bool = False


class ReasonerStatus(BaseModel):
    """Which brains are available, and what enabling the cloud one costs.

    Deliberately never carries the key. :func:`warden.credentials.hint` returns
    the last four characters and that is the most this API will disclose, so a
    screen recording of the Model page during a demonstration cannot leak it.
    """

    local_available: bool
    local_model: str | None = None
    cloud_enabled: bool = Field(description="Whether a key is stored and cloud mode is on.")
    cloud_key_hint: str = Field(default="", description="Last four characters only.")
    cloud_model: str | None = None
    cloud_reachable: bool = False
    detail: str = ""


class KeyRequest(BaseModel):
    api_key: str = Field(min_length=8, description="A Groq API key. Never logged, never returned.")


class ChatRequest(BaseModel):
    """A problem described in words rather than found by a detector."""

    message: str = Field(min_length=1, max_length=2000)


class ChatReply(BaseModel):
    incident_id: str | None = Field(
        default=None,
        description="Set when the description was enough to open an incident.",
    )
    reply: str
    detail: str = ""


class CheckStarted(BaseModel):
    """What a requested check picked up.

    ``started`` is empty when the area is fine. The interface needs that
    distinction: "checked, nothing wrong" and "did not check" must not look the
    same, which is the whole reason this returns a list rather than a boolean.
    """

    started: list[str] = Field(description="Symptom codes now being diagnosed.")
    detail: str


def _shutdown_this_instance() -> None:
    """Close the window and the process, so the elevated copy is the only one.

    The window owns the main thread and uvicorn is a daemon behind it, so
    closing the window is what actually ends the process -- and the ``finally``
    in ``__main__.main`` is what reaps the model runtime. Falling back to a hard
    exit matters for ``--headless``, where there is no window to close.
    """
    windows = []
    with suppress(Exception):
        import webview

        windows = list(webview.windows)

    if windows:
        for window in windows:
            with suppress(Exception):
                window.destroy()
        return
    # Headless: no window to close, so end the process directly. The model
    # runtime is a child and goes with it.
    os._exit(0)


def _no_model_detail() -> str:
    """Why there is no model, phrased for whichever build this is.

    The standard download is 46 MB and leaves the weights out; the offline one
    carries them. Telling someone with the lean build to run an Ollama command
    they do not have would be useless advice, so the two cases say different
    things.
    """
    from warden.reasoner.host import bundled_binary

    if bundled_binary() is not None:
        return (
            "not downloaded yet. Warden works without it -- the rules engine handles "
            "every scenario -- but a model writes better explanations. About 1 GB, "
            "downloaded once and kept."
        )
    return (
        f"no model service found. Install Ollama and run `ollama pull {DEFAULT_MODEL}`, "
        "or use the offline build, which carries the model inside it. Warden still "
        "works -- the rules engine handles every scenario."
    )


class CapabilityReport(BaseModel):
    """The complete list of things Warden can do to a machine.

    Served in full, including the argv template of every action, so that the
    capability surface can be audited without reading the source. A tool that
    asks for this much trust should be able to state its own limits precisely.
    """

    actions: list[ActionSpec]
    candidates_by_symptom: dict[str, list[str]]
    symptoms_with_no_software_fix: list[str]


def create_app(
    agent: Agent | None = None,
    record: bool = True,
    model_host: ModelHost | None = None,
) -> FastAPI:
    agent = agent or Agent()
    harness = DemoHarness()
    recorder: SessionRecorder | None = None

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        nonlocal recorder
        if record:
            recorder = SessionRecorder()
            agent.bus.add_sink(recorder)
            agent.session_path = str(recorder.path)
        saved = settings.load()
        agent.autodiagnose = saved.autodiagnose
        agent.muted = set(saved.muted_symptoms)
        await agent.start()
        try:
            yield
        finally:
            harness.shutdown()
            await agent.stop()
            if recorder is not None:
                recorder.close()

    app = FastAPI(
        title="Warden",
        version="1.0.0",
        summary="An agentic Windows diagnostician that shows its evidence and asks first.",
        lifespan=lifespan,
    )
    app.include_router(_routes(agent, harness, model_host))
    _mount_ui(app)
    return app


def _routes(agent: Agent, harness: DemoHarness, model_host: ModelHost | None) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/state", response_model=AgentSnapshot)
    async def get_state() -> AgentSnapshot:
        return agent.snapshot()

    @router.get("/actions", response_model=CapabilityReport)
    async def get_actions() -> CapabilityReport:
        return CapabilityReport(
            actions=REGISTRY.specs(),
            candidates_by_symptom={k: list(v) for k, v in CANDIDATES.items()},
            symptoms_with_no_software_fix=sorted(k for k, v in CANDIDATES.items() if not v),
        )

    @router.get("/domains", response_model=list[DomainHealth])
    async def get_domains() -> list[DomainHealth]:
        """The machine broken into the parts a person recognises.

        Computed fresh from the current symptoms and collector health, so a
        domain can never report "fine" because a stale summary said so.
        """
        snapshot = agent.snapshot()
        by_id = {c.id: c for c in snapshot.collectors}
        active = snapshot.active_symptoms
        return [
            DomainHealth(
                id=domain.id,
                label=domain.label,
                blurb=domain.blurb,
                icon=domain.icon,
                state=(summary := summarise(domain, active, by_id))[0],
                headline=summary[1],
                symptom_codes=list(domain.symptoms),
                active_symptoms=[s for s in active if s.code in domain.symptoms],
                collectors=list(domain.collectors),
                highlights={
                    source: observation
                    for source in domain.highlights
                    if (observation := agent.store.latest(source)) is not None
                },
            )
            for domain in DOMAINS
        ]

    # -- which brain, and the one secret Warden holds ----------------------

    def _cloud_status(detail: str = "") -> ReasonerStatus:
        key = credentials.load_key()
        cloud = agent.reasoner.cloud
        return ReasonerStatus(
            local_available=agent.reasoner.client.available,
            local_model=agent.reasoner.client.resolve_model(),
            cloud_enabled=cloud is not None,
            cloud_key_hint=credentials.hint(key),
            cloud_model=cloud.resolve_model() if cloud is not None else None,
            cloud_reachable=cloud.available if cloud is not None else False,
            detail=detail,
        )

    @router.get("/reasoner", response_model=ReasonerStatus)
    async def reasoner_status() -> ReasonerStatus:
        return _cloud_status()

    @router.put("/reasoner/key", response_model=ReasonerStatus)
    async def set_key(request: KeyRequest) -> ReasonerStatus:
        """Store a Groq key and switch the cloud path on.

        The key is written to its own file rather than into Settings, and the
        response says only whether it worked plus the last four characters.
        There is deliberately no route that returns it.
        """
        credentials.save_key(request.api_key)
        client = GroqClient(api_key=request.api_key)
        reachable = await client.refresh_models()
        if not reachable:
            credentials.clear_key()
            agent.reasoner.set_cloud(None)
            raise HTTPException(
                400,
                "That key did not work. Groq refused it or could not be reached. "
                "Nothing was saved.",
            )
        agent.reasoner.set_cloud(client)
        agent._log(
            f"Cloud model enabled: {client.resolve_model()}. "
            f"Readings will be sent to Groq when it is used.",
            level="warn",
        )
        return _cloud_status("Cloud model enabled.")

    @router.delete("/reasoner/key", response_model=ReasonerStatus)
    async def clear_key() -> ReasonerStatus:
        credentials.clear_key()
        agent.reasoner.set_cloud(None)
        agent._log("Cloud model switched off. Nothing leaves this machine again.")
        return _cloud_status("Cloud model switched off and the key deleted.")

    # -- describing a problem in words -------------------------------------

    @router.post("/chat", response_model=ChatReply)
    async def chat(request: ChatRequest) -> ChatReply:
        """Diagnose from a description rather than from a detector.

        The detectors find what they were written to find. A person sitting in
        front of a broken machine knows things no collector reads: that it began
        after an update, that it only happens on one monitor, that the sound
        works in one app and not another. This is the way in for that.

        It does not bypass anything. The description becomes context on a
        diagnosis that goes through the same reasoner, the same guardrail and
        the same approval gate as one a detector opened.
        """
        symptom = Symptom(
            code="USER.DESCRIBED",
            severity=Severity.WARN,
            title=request.message.strip()[:120],
            detail=request.message.strip(),
            detector="user",
            facts={"described": request.message.strip()},
        )
        try:
            incident = await agent.describe(symptom, note=request.message)
        except RuntimeError as exc:
            return ChatReply(reply=str(exc), detail="no reasoner available")
        diagnosis = incident.diagnosis
        if diagnosis is None:
            return ChatReply(incident_id=incident.id, reply="Warden could not work that out.")

        # The rules engine has handlers for the codes its detectors raise and
        # nothing for an arbitrary description, so its "summary" here is the
        # user's own sentence handed back. Echoing someone's words at them and
        # calling it a diagnosis is the single most chatbot-like thing this
        # application could do, so it says what is actually true instead.
        if diagnosis.reasoner.mode == "rules" and diagnosis.proposal is None:
            return ChatReply(
                incident_id=incident.id,
                reply=(
                    "Warden has no way to reason about a description on its own. Its "
                    "rules engine only knows the faults its detectors can find, and "
                    "the local model can only choose from the 17 reviewed actions. "
                    "Turn on the cloud model from the Model page and ask again, or "
                    "open Health to see what Warden has found by itself."
                ),
                detail="no model able to answer a free-text description",
            )
        return ChatReply(incident_id=incident.id, reply=diagnosis.summary)

    @router.post("/incidents/{incident_id}/approve-composed", response_model=Incident)
    async def approve_composed(incident_id: str) -> Incident:
        """Run a command the cloud model wrote, having been approved.

        A separate route from ``approve`` on purpose. The two do genuinely
        different things with genuinely different guarantees, and one endpoint
        that silently branched on which field was populated would be the sort of
        convenience that hides the distinction the whole design rests on.
        """
        try:
            return await agent.approve_composed(incident_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.get("/settings", response_model=Settings)
    async def get_settings() -> Settings:
        return settings.load()

    @router.put("/settings", response_model=Settings)
    async def put_settings(incoming: Settings) -> Settings:
        """Save preferences, and apply the ones the running agent cares about."""
        settings.save(incoming)
        agent.autodiagnose = incoming.autodiagnose
        agent.muted = set(incoming.muted_symptoms)
        return incoming

    @router.post("/check", response_model=CheckStarted)
    async def check(domain: str | None = None) -> CheckStarted:
        """Diagnose what has been found, for one area or all of them.

        Detection runs continuously and everything it finds is already on the
        Health page. This is where a finding turns into reasoning and a
        proposal, and it only happens because somebody asked -- so a machine
        with no printer is never interrupted about the spooler, and a network
        left Public on purpose stays a note rather than a demand.
        """
        codes = agent.check(domain)
        if not codes:
            return CheckStarted(
                started=[],
                detail=(
                    "Nothing to look into here. Warden has not found anything wrong in this area."
                    if domain
                    else "Nothing to look into. Warden has not found anything wrong."
                ),
            )
        return CheckStarted(
            started=codes,
            detail=f"Looking into {len(codes)} finding{'' if len(codes) == 1 else 's'}.",
        )

    @router.post("/audit/apply", response_model=AuditApplied)
    async def apply_recommendation(check_id: str, revert: bool = False) -> AuditApplied:
        """Apply a Tune-up recommendation, or put it back.

        Goes through the same executor and the same four gates as every fault
        fix. The recommendation is rebuilt from a fresh audit rather than
        remembered, so the prior value written into the revert record is read
        from the machine as it is now, not from a stale copy.
        """
        report = run_audit(agent.store)
        match = next((r for r in report.recommendations if r.result.check_id == check_id), None)
        if match is None:
            raise HTTPException(404, "no recommendation is available for that check")
        if match.proposal is None:
            raise HTTPException(
                409, "that finding is yours to decide on; Warden does not recommend an action"
            )

        outcome = await asyncio.to_thread(
            lambda: apply_recommendation_action(match, agent.executor, agent.store, revert=revert)
        )

        # Re-read so the delta compares against the machine after the command,
        # not against the readings that were already in the store.
        await asyncio.to_thread(agent.collectors.run_ids, ["sys.audit"])
        refreshed = run_audit(agent.store)
        after_match = next(
            (r for r in refreshed.recommendations if r.result.check_id == check_id), None
        )
        after = after_match.current if after_match else None

        change = describe_change(
            outcome.before,
            after,
            match.metric.unit,
            match.metric.direction.value == "lower_is_better",
        )
        agent.bus.publish(
            AgentLogEvent(text=f"Tune-up: {match.result.title}. {outcome.detail} {change}")
        )
        return AuditApplied(ok=outcome.ok, detail=outcome.detail, change=change, reverted=revert)

    @router.post("/audit", response_model=AuditReport)
    async def run_the_audit() -> AuditReport:
        """Examine settings that are wrong but have not broken anything.

        A POST, and only ever called when the user opens the page or asks for a
        re-check. There is deliberately no timer and no background pass: a tool
        that rescans on a schedule and grows a badge is the scareware pattern
        this feature was written not to be.
        """
        return run_audit(agent.store)

    @router.get("/events/recent", response_model=list[AgentEvent])
    async def recent_events(since: int = 0) -> list[Any]:
        """Events the interface may have missed, for resynchronising after a drop.

        It also exists so that the discriminated ``AgentEvent`` union appears in
        the OpenAPI document. The WebSocket carries these types but FastAPI does
        not describe socket payloads, and the interface's TypeScript definitions
        are generated from that document rather than hand-written -- so without a
        route mentioning the union, the front end would be typing the most
        important messages in the system by hand.
        """
        return [e for e in agent.bus.replay_buffer() if e.seq > since]

    @router.get("/observations/{observation_id}")
    async def get_observation(observation_id: str) -> Any:
        observation = agent.store.by_id(observation_id)
        if observation is None:
            raise HTTPException(404, "that reading has aged out of the buffer")
        return observation

    @router.post("/incidents/{incident_id}/approve", response_model=Incident)
    async def approve(incident_id: str) -> Incident:
        try:
            return await agent.approve(incident_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.post("/incidents/{incident_id}/decline", response_model=Incident)
    async def decline(incident_id: str, mute: bool = False) -> Incident:
        """Refuse a proposal. With ``mute``, refuse it permanently.

        The agent keeps the muted set in memory; persisting it is the API's job
        because the agent does no file I/O. Written after the decline succeeds,
        so a 404 or 409 cannot silently mute something.
        """
        try:
            incident = await agent.decline(incident_id, mute=mute)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        if mute:
            saved = settings.load()
            saved.muted_symptoms = sorted(agent.muted)
            settings.save(saved)
        return incident

    @router.post("/relaunch-elevated", response_model=RelaunchResponse)
    async def relaunch() -> RelaunchResponse:
        """Start an elevated copy of Warden and stand this one down.

        Only reachable when the user asks for it, from the point in the
        interface where they met the limit. Declining the UAC prompt is a valid
        answer and leaves this instance running untouched.
        """
        if is_admin():
            return RelaunchResponse(
                started=False, detail="Warden is already running as administrator."
            )
        started = await asyncio.to_thread(relaunch_elevated)
        if not started:
            return RelaunchResponse(
                started=False,
                detail=(
                    "Warden was not restarted. If you chose No on the Windows prompt "
                    "that is fine. Nothing has changed, and everything that does not "
                    "need administrator still works."
                ),
            )
        # The elevated copy is starting. Hand over rather than run alongside it:
        # two instances would mean two model runtimes, each holding a gigabyte,
        # and two agents proposing fixes for the same machine.
        asyncio.get_running_loop().call_later(0.5, _shutdown_this_instance)
        return RelaunchResponse(
            started=True,
            detail="Warden is restarting with administrator rights. This window will close.",
        )

    @router.post("/model/download", response_model=RelaunchResponse)
    async def download_model() -> RelaunchResponse:
        """Fetch the local model, on request.

        Never automatic. Warden works without it -- the rules engine answers
        every scenario end to end -- so spending a gigabyte of somebody's
        bandwidth is a decision for them, not a thing that happens because they
        opened an application.
        """
        host = model_host
        if host is None or host.endpoint is None:
            return RelaunchResponse(
                started=False,
                detail=(
                    "This build has no model runtime, so there is nothing to download "
                    "into. Install Ollama separately, or use the offline build."
                ),
            )
        if has_weights():
            return RelaunchResponse(started=False, detail="The model is already installed.")

        def progress(line: str) -> None:
            agent.bus.publish(AgentLogEvent(text=f"Downloading the model: {line}"))

        agent.bus.publish(AgentLogEvent(text=f"Downloading {DEFAULT_MODEL}. This is about 1 GB."))
        ok = await asyncio.to_thread(host.pull, DEFAULT_MODEL, progress)
        if not ok:
            return RelaunchResponse(
                started=False,
                detail=(
                    "The download did not finish. Check the connection and try again. "
                    "nothing is broken, and Warden keeps working without it."
                ),
            )
        await agent.reasoner.probe_model()
        return RelaunchResponse(
            started=True,
            detail="The model is installed. New diagnoses will use it from now on.",
        )

    @router.get("/doctor", response_model=DoctorReport)
    async def doctor() -> DoctorReport:
        return await _doctor(agent)

    # -- demonstration harness -------------------------------------------
    # Separated under its own prefix, and every response says plainly that a
    # real fault was induced. Nothing here is reachable from the agent loop.

    @router.post("/demo/wifi-drop", response_model=ScenarioResponse)
    async def demo_wifi_drop() -> ScenarioResponse:
        started, detail = await asyncio.to_thread(harness.wifi_drop)
        return ScenarioResponse(scenario="wifi_drop", started=started, detail=detail)

    @router.post("/demo/cpu-load", response_model=ScenarioResponse)
    async def demo_cpu_load(seconds: float = 120.0) -> ScenarioResponse:
        started, detail = harness.cpu_load(seconds=min(max(seconds, 10.0), 600.0))
        return ScenarioResponse(scenario="cpu_load", started=started, detail=detail)

    @router.post("/demo/stop-load", response_model=ScenarioResponse)
    async def demo_stop_load() -> ScenarioResponse:
        started, detail = harness.stop_load()
        return ScenarioResponse(scenario="stop_load", started=started, detail=detail)

    @router.get("/demo/status")
    async def demo_status() -> dict[str, Any]:
        return {
            "load_active": harness.load_active,
            "load_remaining_s": round(harness.load_remaining_s, 1),
        }

    @router.websocket("/events")
    async def events(websocket: WebSocket) -> None:
        await websocket.accept()
        try:
            async for event in agent.bus.subscribe():
                await websocket.send_text(event.model_dump_json())
        except (WebSocketDisconnect, ConnectionError):
            pass
        except RuntimeError:
            # Raised when the socket closes mid-send; not worth a stack trace.
            pass
        finally:
            with suppress(Exception):
                await websocket.close()

    return router


async def _doctor(agent: Agent) -> DoctorReport:
    """Pre-flight, meant to be run in front of the audience.

    Every check is something that has actually broken a demonstration at some
    point: a cold PowerShell host, a model that was never pulled, a wireless
    profile that does not exist so there is nothing to reconnect to.
    """
    checks: list[DoctorCheck] = []
    host = describe_host()

    checks.append(
        DoctorCheck(
            name="Windows",
            ok=host["os"].startswith("Windows"),
            detail=f"{host['os']} build {host['version']}",
            blocking=True,
        )
    )

    healthy = [c for c in agent.snapshot().collectors if c.healthy]
    checks.append(
        DoctorCheck(
            name="Collectors",
            ok=len(healthy) >= 4,
            detail=f"{len(healthy)} of {len(agent.collectors.collectors)} reporting",
            blocking=True,
        )
    )

    profiles = agent.store.value("net.wifi.profiles") or []
    link = agent.store.value("net.wifi.link") or {}
    checks.append(
        DoctorCheck(
            name="Wireless scenario",
            ok=bool(profiles) and isinstance(link, dict) and link.get("state") == "connected",
            detail=(
                f"connected to {link.get('ssid')!r} with "
                f"{len(profiles) if isinstance(profiles, list) else 0} saved profile(s)"
                if isinstance(link, dict) and link.get("state") == "connected"
                else "not currently connected -- connect first, so there is a profile to restore"
            ),
            blocking=True,
        )
    )

    provider = agent.store.value("thermal.provider") or {}
    active = provider.get("active") if isinstance(provider, dict) else None
    checks.append(
        DoctorCheck(
            name="Thermal scenario",
            ok=agent.store.latest("cpu.performance_pct") is not None,
            detail=(
                f"temperature sensors via {active}"
                if active
                else "no temperature sensor; using clock-throttle inference, which is enough"
            ),
            blocking=False,
        )
    )

    restore = await asyncio.to_thread(describe_restore)
    checks.append(
        DoctorCheck(
            name="Way back",
            ok=restore.available,
            detail=(
                f"{restore.detail} Warden takes one before the first disruptive action, "
                "and hands you to Windows' own restore screen rather than rolling the "
                "machine back itself."
            ),
            blocking=False,
        )
    )

    model = await agent.reasoner.probe_model()
    checks.append(
        DoctorCheck(
            name="Local model",
            ok=model is not None,
            detail=(
                f"{model} responding on {agent.reasoner.client.endpoint}"
                if model
                else _no_model_detail()
            ),
            blocking=False,
        )
    )

    checks.append(
        DoctorCheck(
            name="Administrator",
            ok=is_admin(),
            detail=(
                "elevated; device-restart and sensor actions are available"
                if is_admin()
                else "standard user; Warden will refuse elevated actions rather than fail "
                "halfway through one"
            ),
            blocking=False,
        )
    )

    return DoctorReport(
        ready=all(c.ok for c in checks if c.blocking),
        checks=checks,
    )


def _mount_ui(app: FastAPI) -> None:
    dist = UI_DIST
    if not dist.exists():
        # In a source checkout this is a step the developer has not run yet. In a
        # frozen build it is a packaging defect, and telling the user to run npm
        # would send them after a problem that is not theirs to fix.
        fix = (
            "this build is missing its interface; rebuild it with scripts/build-exe.ps1"
            if is_frozen()
            else "run `npm install && npm run build` in ui/, or use run.ps1"
        )

        @app.get("/")
        async def missing_ui() -> JSONResponse:
            return JSONResponse(
                status_code=503,
                content={"error": "the interface has not been built", "fix": fix},
            )

        return
    app.mount("/", StaticFiles(directory=dist, html=True), name="ui")
