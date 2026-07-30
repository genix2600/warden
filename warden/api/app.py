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

from warden.audit import run_audit
from warden.contracts import ActionSpec, AgentEvent, AgentLogEvent, AuditReport, Incident
from warden.contracts.state import AgentSnapshot, DomainHealth
from warden.demo import DemoHarness
from warden.domains import DOMAINS, summarise
from warden.executor.restore import describe as describe_restore
from warden.orchestrator import Agent, SessionRecorder
from warden.paths import resource_path
from warden.playbooks import CANDIDATES, REGISTRY
from warden.reasoner.host import ModelHost, has_weights
from warden.reasoner.llm import DEFAULT_MODEL
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

    The standard download is about 160 MB and leaves the weights out; the
    offline one carries them. Telling someone with the lean build to run an
    Ollama command they do not have would be useless advice, so the two cases
    say different things.
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
        version="0.1.0",
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
    async def decline(incident_id: str) -> Incident:
        try:
            return await agent.decline(incident_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

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
                    "that is fine — nothing has changed, and everything that does not "
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
            agent.bus.publish(AgentLogEvent(text=f"Downloading the model — {line}"))

        agent.bus.publish(AgentLogEvent(text=f"Downloading {DEFAULT_MODEL}. This is about 1 GB."))
        ok = await asyncio.to_thread(host.pull, DEFAULT_MODEL, progress)
        if not ok:
            return RelaunchResponse(
                started=False,
                detail=(
                    "The download did not finish. Check the connection and try again — "
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
