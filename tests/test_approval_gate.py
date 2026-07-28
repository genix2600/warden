"""The promise that nothing runs without consent, asserted rather than claimed.

If any of these fail, the central safety property of the product is broken, and
that is the point of testing it at this level rather than through the UI: a
button can be moved, but the executor's signature cannot quietly acquire a
default.
"""

from __future__ import annotations

import inspect

import pytest

from warden.contracts import ActionProposal, ExecutionOutcome, RiskTier, VerifySpec, utcnow
from warden.contracts.actions import PredicateRef
from warden.executor import Executor
from warden.playbooks import REGISTRY


def build_proposal(**overrides) -> ActionProposal:
    playbook = REGISTRY.get("net.wifi.scan")
    base = dict(
        action_id="net.wifi.scan",
        params={},
        rendered_argv=list(playbook.argv_template),
        rationale="test",
        expected_effect="test",
        risk=RiskTier.READ_ONLY,
        requires_admin=False,
        reversible=True,
        est_duration_s=1.0,
        verify=VerifySpec(probes=[], predicate=PredicateRef(id="report.only", describe="none")),
    )
    return ActionProposal(**{**base, **overrides})


def test_execute_cannot_be_called_without_an_approval_timestamp() -> None:
    """`approved_at` is keyword-only and has no default. There is no way in."""
    signature = inspect.signature(Executor.execute)
    approved_at = signature.parameters["approved_at"]
    assert approved_at.default is inspect.Parameter.empty, (
        "approved_at acquired a default; an unapproved action could now execute"
    )
    assert approved_at.kind is inspect.Parameter.KEYWORD_ONLY

    with pytest.raises(TypeError):
        Executor().execute(build_proposal())  # type: ignore[call-arg]


def test_execution_record_always_carries_the_approval() -> None:
    record = Executor().execute(build_proposal(), approved_at=utcnow())
    assert record.approved_at is not None


def test_a_command_that_does_not_match_the_registry_is_refused() -> None:
    """Defence in depth: the executor re-renders the argv and compares.

    A proposal whose command was altered after it was built -- or which was
    never built by the registry at all -- never reaches CreateProcess.
    """
    tampered = build_proposal(rendered_argv=["netsh", "wlan", "delete", "profile", "name=*"])
    record = Executor().execute(tampered, approved_at=utcnow())

    assert record.outcome is ExecutionOutcome.BLOCKED
    assert record.exit_code is None, "a blocked action must never have run"
    assert "does not match what the registry would produce" in (record.blocked_reason or "")


def test_an_unknown_action_is_refused() -> None:
    record = Executor().execute(build_proposal(action_id="format.the.disk"), approved_at=utcnow())
    assert record.outcome is ExecutionOutcome.BLOCKED
    assert "only run its registered playbooks" in (record.blocked_reason or "")


def test_elevation_is_checked_before_running_not_after() -> None:
    """An admin-only action refuses up front rather than failing halfway."""
    from warden.winenv import is_admin

    playbook = REGISTRY.get("net.adapter.restart")
    proposal = build_proposal(
        action_id=playbook.id,
        params={"interface": "Wi-Fi"},
        rendered_argv=[t.format(interface="Wi-Fi") for t in playbook.argv_template],
        requires_admin=True,
        risk=RiskTier.INTRUSIVE,
    )
    record = Executor().execute(proposal, approved_at=utcnow())

    if is_admin():
        pytest.skip("running elevated; the refusal path cannot be exercised here")
    assert record.outcome is ExecutionOutcome.BLOCKED
    assert "administrator" in (record.blocked_reason or "").lower()
    assert record.exit_code is None
