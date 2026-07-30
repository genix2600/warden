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
    """Which brain answered. Three, and the difference is not cosmetic.

    ``LLM`` and ``CLOUD`` are separated rather than folded into one "a model
    answered" value because the honest disclosure differs. A local answer was
    reached without anything leaving the machine and is confined to the reviewed
    action registry. A cloud answer sent readings to a third party and may carry
    a command the model wrote itself. Labelling the second as the first would be
    the precise kind of quiet overstatement this project is an argument against,
    and every string in the interface that says "local model" reads this field.
    """

    LLM = "llm"  # on this machine's processor, reviewed actions only
    CLOUD = "cloud"  # hosted, user's own key, may compose a command
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


class ComposedCommand(Contract):
    """A command the cloud model wrote, rather than one Warden reviewed.

    Kept as a separate field from :attr:`Diagnosis.proposal` on purpose. An
    ``ActionProposal`` carries guarantees this cannot: it came from the closed
    registry, its parameters were checked against what was actually observed on
    the machine, and it declares a predicate that will decide whether it worked.
    A composed command has none of those, and reusing the same type would let
    the interface render both with the same confidence.

    Every field except ``argv`` exists to be read before approving. A model that
    will not say what its command changes or how to undo it has not earned the
    button, and making them required means "it did not say" is a schema failure
    rather than an empty panel.
    """

    argv: list[str] = Field(description="Exactly what will run. No shell, ever.")
    explain: str = Field(description="What this does, in plain language.")
    changes: str = Field(description="What it changes on the machine.")
    reversible: bool
    undo: str = Field(default="", description="How to put it back.")
    check: str = Field(default="", description="How you can tell whether it worked.")
    requires_admin: bool = False
    risk: Literal["reads_only", "reversible", "disruptive"] = "disruptive"
    refused: str | None = Field(
        default=None,
        description=(
            "Why Warden will not offer this, from the refusal list. When set the "
            "interface must show the refusal and no approve button."
        ),
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
    composed: ComposedCommand | None = Field(
        default=None,
        description=(
            "Set only on the cloud path, and only when no reviewed action fits. "
            "Mutually exclusive with `proposal` in practice: a reviewed action is "
            "grounded, verified and reversible, so it is always preferred."
        ),
    )
    reasoner: ReasonerInfo

    @model_validator(mode="after")
    def _verdict_matches_payload(self) -> Self:
        if self.verdict is Verdict.NEEDS_SERVICE:
            if self.proposal is not None:
                raise ValueError("a needs_service verdict must not carry an executable proposal")
            if self.composed is not None:
                raise ValueError("a needs_service verdict must not carry a composed command")
            if self.service_advice is None:
                raise ValueError("a needs_service verdict must carry service advice")
        # `composed` satisfies this as well as `proposal` does. The rule being
        # enforced is "actionable means there is something to approve", not
        # "actionable means the registry produced it" -- the two were the same
        # thing until a cloud model could write a command, and keeping the
        # narrower wording would have made every composed command a crash.
        if self.verdict is Verdict.ACTIONABLE and self.proposal is None and self.composed is None:
            raise ValueError("an actionable verdict must carry a proposal or a composed command")
        return self

    @property
    def top(self) -> Hypothesis | None:
        return self.ranked_hypotheses[0] if self.ranked_hypotheses else None
