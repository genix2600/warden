"""The reasoner's output: ranked causes, a verdict, and at most one proposal.

The type system does the routing. ``Verdict.NEEDS_SERVICE`` cannot carry a
proposal -- a model validator enforces it -- so "this is a hardware problem, go
get it serviced" is a state the software is structurally incapable of turning
into a command. That is the rule the pitch promises, expressed where it cannot
be forgotten.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, model_validator

from warden.contracts.actions import ActionProposal
from warden.contracts.common import Contract, Domain, Verdict, new_id, utcnow


class Hypothesis(Contract):
    cause: str = Field(description="One sentence, in the user's language, not ours.")
    domain: Domain
    likelihood: float = Field(ge=0.0, le=1.0)
    reasoning: str
    supporting: list[str] = Field(
        default_factory=list, description="Observation ids that argue for this cause."
    )
    contradicting: list[str] = Field(
        default_factory=list,
        description=(
            "Observation ids that argue against it. Asking for this explicitly is "
            "what stops a confident-sounding model from ignoring the reading that "
            "does not fit."
        ),
    )


class ServiceAdvice(Contract):
    """What we say when the answer is not a command.

    Two distinct cases share this shape, because they share a conclusion --
    software cannot do this -- and differ only in who acts. A radio disabled by
    a physical switch needs the person at the keyboard to flip it; a heatsink
    full of dust needs a technician. Collapsing both into "contact support"
    would be exactly the unhelpfulness this project exists to replace.
    """

    reason: str = Field(description="Why no command can fix this.")
    who: Literal["user", "technician"] = Field(
        description="Who has to act: the person at the machine, or someone with a screwdriver."
    )
    next_step: str = Field(
        description="For 'user', the physical thing to do. For 'technician', what to tell them."
    )
    interim_mitigation: str | None = Field(
        default=None, description="Something safe to do meanwhile, if anything."
    )
    urgency: Literal["routine", "soon", "urgent"] = "routine"


class ReasonerMode(StrEnum):
    LLM = "llm"
    RULES = "rules"  # deterministic fallback; always available, never blocks


class ReasonerInfo(Contract):
    """Disclosed in the UI on every diagnosis. Users should know which brain answered."""

    mode: ReasonerMode
    model: str | None = None
    latency_ms: int = 0
    fallback_reason: str | None = Field(
        default=None, description="Populated when the LLM path was attempted and abandoned."
    )
    guardrail_rejections: list[str] = Field(
        default_factory=list,
        description="Model proposals the guardrail refused, and why. Never hidden.",
    )


class Diagnosis(Contract):
    id: str = Field(default_factory=new_id)
    created_at: datetime = Field(default_factory=utcnow)
    symptom_codes: list[str]
    summary: str = Field(description="The headline, written for the user.")
    ranked_hypotheses: list[Hypothesis] = Field(default_factory=list)
    verdict: Verdict
    service_advice: ServiceAdvice | None = None
    proposal: ActionProposal | None = None
    reasoner: ReasonerInfo

    @model_validator(mode="after")
    def _verdict_matches_payload(self) -> Self:
        if self.verdict is Verdict.NEEDS_SERVICE:
            if self.proposal is not None:
                raise ValueError("a needs_service verdict must not carry an executable proposal")
            if self.service_advice is None:
                raise ValueError("a needs_service verdict must carry service advice")
        if self.verdict is Verdict.ACTIONABLE and self.proposal is None:
            raise ValueError("an actionable verdict must carry a proposal")
        return self

    @property
    def top(self) -> Hypothesis | None:
        return self.ranked_hypotheses[0] if self.ranked_hypotheses else None
