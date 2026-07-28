"""Actions: the closed set of things Warden is capable of doing to your machine.

The reasoner cannot write a command. It can only name an id from this registry
and supply parameters, which are validated against a schema before anything is
rendered. If the model hallucinates ``format.c.drive``, the guardrail rejects the
whole proposal and the deterministic fallback answers instead.

The argv is a *list*, never a string, and it is rendered from a template held
here in code -- not from model output. There is no shell anywhere in the
execution path.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, JsonValue

from warden.contracts.common import Contract, RiskTier, new_id, utcnow


class PredicateRef(Contract):
    """A named boolean check, evaluated against freshly collected observations."""

    id: str = Field(description="Key into the predicate registry, e.g. 'wifi.associated'.")
    args: dict[str, JsonValue] = Field(default_factory=dict)
    describe: str = Field(description="Plain English, shown to the user before they approve.")


class VerifySpec(Contract):
    """How we will know whether the fix actually worked.

    Declaring this *before* execution is the point. The user approves not just a
    command but the test that command will be judged by, so "fixed" is a
    measurement rather than a claim.
    """

    probes: list[str] = Field(description="Collector ids to re-run after the action.")
    predicate: PredicateRef
    timeout_s: float = Field(default=15.0, gt=0)
    poll_interval_s: float = Field(default=1.5, gt=0)
    settle_s: float = Field(default=0.0, ge=0, description="Grace period before the first check.")


class ActionSpec(Contract):
    """Public, serialisable description of one registry entry.

    Exposed at ``GET /api/actions`` in full so that the complete list of things
    this software can do to a machine is inspectable without reading the source.
    """

    id: str
    title: str
    summary: str
    when_to_use: str = Field(description="Shown to the reasoner as selection guidance.")
    risk: RiskTier
    requires_admin: bool = False
    requires_network: bool = False
    reversible: bool = True
    est_duration_s: float = 5.0
    params_schema: dict[str, JsonValue] = Field(
        default_factory=dict, description="JSON Schema derived from the action's param model."
    )
    argv_template: list[str] = Field(
        description="Tokens with {placeholders}; rendered by the registry, never by a model."
    )
    verify: VerifySpec
    rollback_action_id: str | None = None


class ActionProposal(Contract):
    """A concrete, fully-resolved intent awaiting a human decision."""

    id: str = Field(default_factory=new_id)
    action_id: str
    params: dict[str, JsonValue] = Field(default_factory=dict)
    rendered_argv: list[str] = Field(
        description="Exactly what will be executed. Displayed verbatim in the approval card."
    )
    rationale: str = Field(description="Why this action, for this evidence.")
    expected_effect: str = Field(description="What the user should expect to happen.")
    risk: RiskTier
    requires_admin: bool
    reversible: bool
    est_duration_s: float
    verify: VerifySpec


class Decision(StrEnum):
    APPROVED = "approved"
    DECLINED = "declined"


class VerificationOutcome(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"  # the check itself could not be evaluated


class VerificationResult(Contract):
    outcome: VerificationOutcome
    predicate: PredicateRef
    detail: str
    checked_at: datetime = Field(default_factory=utcnow)
    attempts: int = 1
    evidence_before: list[str] = Field(default_factory=list)
    evidence_after: list[str] = Field(default_factory=list)


class ExecutionOutcome(StrEnum):
    RESOLVED = "resolved"
    NOT_RESOLVED = "not_resolved"
    ERROR = "error"
    BLOCKED = "blocked"  # preflight or privilege check refused to run it


class ExecutionRecord(Contract):
    """Proof of what happened.

    ``approved_at`` is not decoration. Nothing in the executor will run without
    it, and ``tests/test_approval_gate.py`` exists to keep that true.
    """

    id: str = Field(default_factory=new_id)
    proposal_id: str
    action_id: str
    argv: list[str]
    approved_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    exit_code: int | None = None
    timed_out: bool = False
    stdout_tail: str = ""
    stderr_tail: str = ""
    verification: VerificationResult | None = None
    outcome: ExecutionOutcome = ExecutionOutcome.ERROR
    blocked_reason: str | None = None
