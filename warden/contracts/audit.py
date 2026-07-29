"""The audit: settings that are not broken, but are measurably wrong.

Warden's detectors react. Something fails, a symptom fires, an incident opens.
The audit is the other half: a standing review of settings that have never
failed and never will, but which leave the machine slower, less reliable or less
secure than it should be. Nobody has looked at them since the machine was built.

The word is *audit*, not *optimiser*, and the distinction is enforced here rather
than left to editorial discipline:

**Every check names a quantity, reads it before, and reads it again after.**

A recommendation that cannot say what number will change is precisely what a
registry cleaner sells -- an improvement claim that cannot be falsified. So a
:class:`Recommendation` without a :class:`MetricSpec` is not constructible, in
the same way a ``needs_service`` diagnosis cannot carry an executable proposal.
Some genuinely popular ideas are excluded by that rule: registry cleaning,
telemetry toggles, disabling services "for speed". They do not ship, because
their effect cannot be measured, so their claim cannot be checked.

The corollary matters as much: **"no measurable change" is a first-class
outcome**, displayed as prominently as an improvement. A tool that only reports
its wins cannot be calibrated, which is the same reason History already shows
failed actions beside successful ones.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Self

from pydantic import Field, JsonValue, model_validator

from warden.contracts.actions import ActionProposal, PredicateRef
from warden.contracts.common import Contract, new_id, utcnow


class MetricDirection(StrEnum):
    HIGHER_IS_BETTER = "higher_is_better"
    LOWER_IS_BETTER = "lower_is_better"
    TARGET_VALUE = "target_value"


class CheckStatus(StrEnum):
    """The verdict on one setting.

    Five values, and the last three are deliberately not collapsed into
    ``OPTIMAL``. A defrag schedule on a machine with no mechanical disk is
    ``NOT_APPLICABLE``; a check whose collector threw is ``COULD_NOT_READ``; a
    power plan on a laptop is ``INTENT_DEPENDENT`` because there is no correct
    answer. None of them is a pass, and reporting them as one would be the same
    dishonesty as colouring a failed collector green on the Health page.
    """

    OPTIMAL = "optimal"
    SUBOPTIMAL = "suboptimal"
    INTENT_DEPENDENT = "intent_dependent"
    NOT_APPLICABLE = "not_applicable"
    COULD_NOT_READ = "could_not_read"


#: Statuses that describe a setting Warden has no business changing.
_NO_ACTION_STATUSES = frozenset(
    {CheckStatus.OPTIMAL, CheckStatus.NOT_APPLICABLE, CheckStatus.COULD_NOT_READ}
)


class MetricSpec(Contract):
    """What a check measures, and where its threshold came from.

    ``rationale_source`` is not decoration. A threshold that cannot cite where it
    came from is a guess, and a guess dressed as a measurement is the failure
    mode this whole subsystem is built to avoid. If a check cannot fill this in
    honestly, the threshold should be reconsidered rather than the field padded.
    """

    metric_id: str = Field(description="Stable id, e.g. 'wifi.disconnects_per_hour'.")
    label: str = Field(description="Plain English. What a person would call this number.")
    unit: str = Field(description="Units, spelled out: 'milliseconds', 'GB', 'days'.")
    direction: MetricDirection
    read_via: PredicateRef = Field(description="How the number is obtained, and from where.")
    rationale_source: str = Field(
        min_length=1,
        description=(
            "Why the threshold is what it is: Microsoft documentation, measured "
            "on this machine, a hardware-class default. Never empty."
        ),
    )


class MetricReading(Contract):
    """One measurement of a metric, with the observations that produced it."""

    metric_id: str
    value: JsonValue
    unit: str
    captured_at: datetime = Field(default_factory=utcnow)
    observation_ids: list[str] = Field(default_factory=list)


class CheckResult(Contract):
    """The outcome of examining one setting."""

    check_id: str
    domain_id: str = Field(description="One of the 13 user-facing domains in warden.domains.")
    title: str = Field(description="Plain English, in the register of the rest of the interface.")
    status: CheckStatus
    observed: JsonValue = Field(default=None, description="What the setting is now.")
    expected: JsonValue = Field(default=None, description="What it would be, if changed.")
    detail: str = Field(default="", description="One or two sentences for a non-technical reader.")
    observation_ids: list[str] = Field(
        default_factory=list, description="Readings supporting this result, for the drawer."
    )
    checked_at: datetime = Field(default_factory=utcnow)


class RevertRecord(Contract):
    """Enough of the prior state to put it back.

    Captured *before* the action runs, as part of the execution path rather than
    as a courtesy afterwards. An audit changes settings on a machine that
    currently works, which is a higher bar than repairing one that does not, and
    the user has to be able to undo it.
    """

    action_id: str
    #: The setting's value before Warden touched it, keyed by parameter.
    prior: dict[str, JsonValue] = Field(min_length=1)
    captured_at: datetime = Field(default_factory=utcnow)
    describe: str = Field(description="Plain English: what would be restored, and to what.")


class IntentChoice(Contract):
    """One side of a question that has no correct answer.

    A processor capped at 50% is a misconfiguration on a desktop wired to mains
    and a deliberate choice on a laptop being stretched to last a flight. Warden
    presents both with their measured cost and recommends neither. Every
    competing tool assumes it knows which one you want.
    """

    id: str
    label: str = Field(description="What the user is choosing, in their words.")
    cost: str = Field(description="The measured downside of this choice, stated plainly.")


class Recommendation(Contract):
    """A finding the user could act on, and the number that would move.

    Three validators enforce the rules that make this honest, so they cannot be
    lost to a refactor:

    * no :class:`MetricSpec`, no recommendation;
    * a status meaning "nothing to do here" cannot carry a proposal;
    * an irreversible action cannot exist without a captured prior value.
    """

    id: str = Field(default_factory=new_id)
    result: CheckResult
    metric: MetricSpec
    current: MetricReading
    expected_improvement: str = Field(
        min_length=1,
        description=(
            "An honest range or qualitative bound -- 'typically 200-800 ms', not "
            "'up to 400% faster'. Written to be checkable after the fact."
        ),
    )
    proposal: ActionProposal | None = None
    revert: RevertRecord | None = None
    #: Populated only for INTENT_DEPENDENT findings, which carry no proposal.
    choices: list[IntentChoice] = Field(default_factory=list)

    @model_validator(mode="after")
    def _proposal_matches_status(self) -> Self:
        status = self.result.status
        if status in _NO_ACTION_STATUSES and self.proposal is not None:
            raise ValueError(
                f"a {status.value!r} check has nothing to fix and must not carry a proposal"
            )
        if status is CheckStatus.INTENT_DEPENDENT:
            if self.proposal is not None:
                raise ValueError(
                    "an intent-dependent finding must not recommend an action; "
                    "it presents the options and their costs, and asks"
                )
            if len(self.choices) < 2:
                raise ValueError("an intent-dependent finding must offer at least two choices")
        return self

    @model_validator(mode="after")
    def _irreversible_actions_carry_a_way_back(self) -> Self:
        # The executor already refuses an action needing elevation it does not
        # have. This is the same shape of refusal, moved earlier: if the prior
        # value could not be read, the recommendation cannot be built, so the
        # user is never offered a change they could not undo.
        if self.proposal is not None and not self.proposal.reversible and self.revert is None:
            raise ValueError(
                "an action that cannot be reversed must carry a RevertRecord captured "
                "before execution, or it must not be offered at all"
            )
        return self


class AuditReport(Contract):
    """Everything one pass of the audit found."""

    id: str = Field(default_factory=new_id)
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None
    results: list[CheckResult] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list)

    @property
    def optimal(self) -> int:
        return sum(1 for r in self.results if r.status is CheckStatus.OPTIMAL)

    @property
    def worth_changing(self) -> int:
        return sum(1 for r in self.results if r.status is CheckStatus.SUBOPTIMAL)

    @property
    def depends_on_you(self) -> int:
        return sum(1 for r in self.results if r.status is CheckStatus.INTENT_DEPENDENT)

    @property
    def unreadable(self) -> int:
        return sum(1 for r in self.results if r.status is CheckStatus.COULD_NOT_READ)
