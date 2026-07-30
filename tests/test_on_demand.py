"""Warden watches on its own, but does not interrupt on its own.

The split these tests pin: detection runs continuously and everything it finds
is visible, while reasoning and proposals wait until somebody asks. It exists
because being told about a printer you do not own, or a network you left Public
deliberately, is noise -- and a tool that produces noise gets ignored, including
on the occasion it is right.
"""

from __future__ import annotations

import pytest

from warden.contracts import IncidentState

from .test_agent_loop import CONNECTED, DROPPED, build_agent, tick_until


def build_quiet_agent(script: list[dict]):
    """The shipped configuration: watching, not interrupting."""
    agent = build_agent(script)
    agent.autodiagnose = False
    return agent


@pytest.mark.asyncio
async def test_a_finding_does_not_open_an_incident_by_itself() -> None:
    agent = build_quiet_agent([CONNECTED, CONNECTED, DROPPED, DROPPED])
    await tick_until(agent, lambda: bool(agent.detectors.active))

    assert agent.detectors.active, "detection still runs; that is the point"
    assert agent.incidents == {}, "but nothing interrupted the user"


@pytest.mark.asyncio
async def test_the_finding_is_still_visible_while_it_waits() -> None:
    """Suppressing the interruption must not suppress the evidence."""
    agent = build_quiet_agent([CONNECTED, CONNECTED, DROPPED, DROPPED])
    await tick_until(agent, lambda: bool(agent.detectors.active))

    snapshot = agent.snapshot()
    assert [s.code for s in snapshot.active_symptoms] == ["NET.WIFI.DISCONNECTED"]


@pytest.mark.asyncio
async def test_asking_starts_the_diagnosis() -> None:
    agent = build_quiet_agent([CONNECTED, CONNECTED, DROPPED, DROPPED])
    await tick_until(agent, lambda: bool(agent.detectors.active))

    started = agent.check()
    assert started == ["NET.WIFI.DISCONNECTED"]

    await tick_until(
        agent,
        lambda: any(i.state is IncidentState.AWAITING_APPROVAL for i in agent.incidents.values()),
    )
    incident = next(iter(agent.incidents.values()))
    assert incident.diagnosis is not None


@pytest.mark.asyncio
async def test_checking_one_area_ignores_the_others() -> None:
    """The complaint this whole feature answers: I do not own a printer."""
    agent = build_quiet_agent([CONNECTED, CONNECTED, DROPPED, DROPPED])
    await tick_until(agent, lambda: bool(agent.detectors.active))

    assert agent.check("printing") == [], "nothing wrong with printing, and nothing opened"
    assert agent.incidents == {}

    assert agent.check("network") == ["NET.WIFI.DISCONNECTED"]
    assert len(agent.incidents) == 1


@pytest.mark.asyncio
async def test_checking_a_healthy_machine_reports_nothing_rather_than_failing() -> None:
    """ "Checked, nothing wrong" and "did not check" must not look the same."""
    agent = build_quiet_agent([CONNECTED, CONNECTED, CONNECTED])
    await tick_until(agent, lambda: agent.tick > 2)

    assert agent.check() == []
    assert agent.incidents == {}


@pytest.mark.asyncio
async def test_asking_overrides_the_reopen_cooldown() -> None:
    """The cooldown stops Warden interrupting. Someone clicking Check is not
    being interrupted, so it must not silently do nothing."""
    agent = build_quiet_agent([CONNECTED, CONNECTED, DROPPED, DROPPED])
    await tick_until(agent, lambda: bool(agent.detectors.active))

    agent.check()
    incident = next(iter(agent.incidents.values()))
    agent._set_state(incident, IncidentState.DECLINED)
    assert agent._reopen_after["NET.WIFI.DISCONNECTED"] > 0

    assert agent.check() == ["NET.WIFI.DISCONNECTED"]
    assert len(agent.incidents) == 2, "asked for explicitly, so it runs"
