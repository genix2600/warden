"""The loop end to end, with a fake collector standing in for Windows.

Exercises the parts that only appear once the pieces are assembled: escalation
after a failed verification, the approval gate refusing to be skipped, and an
incident closing itself when the problem goes away on its own.
"""

from __future__ import annotations

import asyncio

import pytest

from warden.collectors import CollectorHost
from warden.collectors.base import Collector
from warden.contracts import IncidentState, ProbeResult, Verdict
from warden.detectors import DetectorBank
from warden.orchestrator import Agent
from warden.reasoner import Reasoner

from .conftest import make_observation

CONNECTED = {
    "state": "connected",
    "ssid": "HomeNet",
    "profile": "HomeNet",
    "radio": "on",
    "signal_pct": 80,
    "interface": "Wi-Fi",
}
DROPPED = {"state": "disconnected", "ssid": None, "profile": None, "radio": "on"}


class ScriptedCollector(Collector):
    """Replays a scripted sequence of link states, then holds the last one."""

    id = "net.wifi"
    interval_s = 0.0
    description = "test double"

    def __init__(self, script: list[dict]) -> None:
        self.script = script
        self.calls = 0

    def probe(self) -> ProbeResult:
        state = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        return ProbeResult(
            observations=[
                make_observation(
                    "net.wifi.adapter",
                    {"present": True, "name": "Wi-Fi", "status": "Up"},
                ),
                make_observation("net.wifi.link", state),
                make_observation("net.wifi.profiles", ["HomeNet"]),
            ]
        )


def build_agent(script: list[dict]) -> Agent:
    collector = ScriptedCollector(script)
    host = CollectorHost(collectors=[collector], bridge=_NullBridge())  # type: ignore[arg-type]
    agent = Agent(
        collectors=host,
        # Zero clear window: these tests drive ticks as fast as they can, and
        # the production 30s hysteresis would stall every self-heal assertion.
        # tests/test_detectors.py covers the hysteresis itself.
        detectors=DetectorBank(clear_after_s=0.0),
        # The local model is off: these tests pin the deterministic behaviour
        # that must hold whether or not a model is installed.
        reasoner=Reasoner(use_llm=False),
        tick_s=0.01,
    )
    # These tests pin the loop itself -- detect, diagnose, propose, verify,
    # escalate -- so the agent has to be allowed to start on its own. The
    # shipped default is off; tests/test_on_demand.py covers that.
    agent.autodiagnose = True
    return agent


class _NullBridge:
    def warmup(self, timeout: float = 0.0) -> float:
        return 0.0

    def close(self) -> None:
        pass


@pytest.mark.asyncio
async def test_warmup_reaches_every_collector() -> None:
    """Collectors that measure a rate need a baseline before their first read.

    The host is responsible for giving them one. A collector added later that
    forgets to be warmed would publish a plausible-looking zero on its first
    sample, which is the worst kind of wrong.
    """
    warmed: list[str] = []

    class Recording(ScriptedCollector):
        def warmup(self) -> None:
            warmed.append(self.id)

    host = CollectorHost(collectors=[Recording([CONNECTED])], bridge=_NullBridge())  # type: ignore[arg-type]
    host.warmup()
    assert warmed == ["net.wifi"]


async def tick_until(agent: Agent, predicate, limit: int = 60) -> None:
    for _ in range(limit):
        await agent._tick()
        await asyncio.sleep(0.02)
        if predicate():
            return
    raise AssertionError("condition never became true")


@pytest.mark.asyncio
async def test_a_dropped_link_produces_an_approval_request_and_stops_there() -> None:
    agent = build_agent([CONNECTED, CONNECTED, DROPPED, DROPPED])
    await tick_until(
        agent,
        lambda: any(i.state is IncidentState.AWAITING_APPROVAL for i in agent.incidents.values()),
    )

    incident = next(iter(agent.incidents.values()))
    assert incident.diagnosis is not None
    assert incident.diagnosis.verdict is Verdict.ACTIONABLE
    proposal = incident.diagnosis.proposal
    assert proposal is not None
    assert proposal.rendered_argv == [
        "netsh",
        "wlan",
        "connect",
        "name=HomeNet",
        "interface=Wi-Fi",
    ]
    # Nothing has run, and nothing will until someone answers.
    assert incident.execution is None
    assert incident.decision is None


@pytest.mark.asyncio
async def test_declining_closes_the_incident_without_running_anything() -> None:
    agent = build_agent([CONNECTED, CONNECTED, DROPPED, DROPPED])
    await tick_until(
        agent,
        lambda: any(i.state is IncidentState.AWAITING_APPROVAL for i in agent.incidents.values()),
    )
    incident = await agent.decline(next(iter(agent.incidents)))

    assert incident.state is IncidentState.DECLINED
    assert incident.execution is None


@pytest.mark.asyncio
async def test_approving_a_second_time_is_refused() -> None:
    """The gate is a state machine, not a button that can be double-clicked."""
    agent = build_agent([CONNECTED, CONNECTED, DROPPED, DROPPED])
    await tick_until(
        agent,
        lambda: any(i.state is IncidentState.AWAITING_APPROVAL for i in agent.incidents.values()),
    )
    incident_id = next(iter(agent.incidents))
    await agent.decline(incident_id)

    with pytest.raises(ValueError, match="not awaiting_approval"):
        await agent.approve(incident_id)


@pytest.mark.asyncio
async def test_a_problem_that_fixes_itself_closes_without_acting() -> None:
    """Windows often reconnects on its own. An agent that ran a command anyway
    would be taking credit for something it did not do."""
    agent = build_agent([CONNECTED, CONNECTED, DROPPED, DROPPED, CONNECTED, CONNECTED])
    await tick_until(
        agent, lambda: any(i.state is IncidentState.RESOLVED for i in agent.incidents.values())
    )

    incident = next(iter(agent.incidents.values()))
    assert incident.execution is None
    assert any("cleared before any action" in note for note in incident.notes)


@pytest.mark.asyncio
async def test_escalation_offers_the_next_action_after_a_failure() -> None:
    """Recorded from real behaviour: `netsh wlan connect` reports success and
    frequently does not reconnect. The agent must climb the ladder rather than
    declare defeat."""
    agent = build_agent([CONNECTED, CONNECTED, DROPPED, DROPPED])
    await tick_until(
        agent,
        lambda: any(i.state is IncidentState.AWAITING_APPROVAL for i in agent.incidents.values()),
    )
    incident = next(iter(agent.incidents.values()))

    # Pretend the first fix ran and verification proved it did not work.
    incident.attempted_actions.append("net.wifi.reconnect")
    await agent._diagnose(incident)

    assert incident.diagnosis is not None
    assert incident.diagnosis.proposal is not None
    assert incident.diagnosis.proposal.action_id == "net.wifi.scan"
    assert incident.state is IncidentState.AWAITING_APPROVAL


@pytest.mark.asyncio
async def test_a_closed_incident_does_not_reopen_immediately() -> None:
    """The other half of the flapping fix, and the half that costs real time.

    Detector hysteresis stops a wobbling measurement raising twice, but once an
    incident has genuinely closed the old guard let the very next raise open a
    fresh one and run the model again. On a machine whose processor sat either
    side of the throttle threshold that meant the same unactionable verdict
    diagnosed over and over.
    """
    agent = build_agent([CONNECTED, CONNECTED, DROPPED, DROPPED])
    await tick_until(
        agent,
        lambda: any(i.state is IncidentState.AWAITING_APPROVAL for i in agent.incidents.values()),
    )
    incident = next(iter(agent.incidents.values()))
    code = incident.symptoms[0].code

    agent._set_state(incident, IncidentState.DECLINED)
    assert incident.state.is_terminal
    opened = len(agent.incidents)

    # The symptom comes straight back, as a flapping one does.
    agent._open_incident(incident.symptoms[0])
    assert len(agent.incidents) == opened, "declined a minute ago; do not ask again"

    # Once the cooldown expires it is a fresh problem worth reporting.
    agent._reopen_after[code] = 0.0
    agent._open_incident(incident.symptoms[0])
    assert len(agent.incidents) == opened + 1


@pytest.mark.asyncio
async def test_an_unactionable_verdict_gets_a_longer_cooldown() -> None:
    """A worn battery will still be worn in five minutes. Asking again is noise."""
    import time as _time

    agent = build_agent([CONNECTED, CONNECTED, DROPPED, DROPPED])
    await tick_until(
        agent,
        lambda: any(i.state is IncidentState.AWAITING_APPROVAL for i in agent.incidents.values()),
    )
    incident = next(iter(agent.incidents.values()))
    code = incident.symptoms[0].code

    agent._set_state(incident, IncidentState.NEEDS_SERVICE)
    remaining = agent._reopen_after[code] - _time.monotonic()
    assert remaining > 300.0, "an unfixable finding should be quieter than a fixable one"
