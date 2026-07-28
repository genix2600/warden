"""Playbook definition, parameter grounding, and argv rendering.

This module is the security boundary. Everything downstream of it -- the
executor, the verifier -- trusts that an ``ActionProposal`` it receives was
produced here, which means:

1. the action id names a real registry entry;
2. the parameters validated against that entry's Pydantic model;
3. the parameters were *corroborated against observed reality* by the entry's
   own guard;
4. the argv was rendered from a template held in source, never from model output.

Point 3 is the one that is unusual and the one worth reading twice. Schema
validation only proves a value is well-formed; it cannot tell you that
``profile="FreeAirportWiFi"`` is a network this machine has never seen. So each
playbook carries a guard with access to the observation store, and an action
whose parameters are not backed by something Warden actually observed is
rejected before a human is ever asked to approve it. The agent cannot connect
you to a network it did not watch you use, and cannot restart a device that is
not in the device tree.
"""

from __future__ import annotations

import string
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, JsonValue, ValidationError

from warden.contracts import ActionProposal, ActionSpec, RiskTier, Symptom, VerifySpec
from warden.store import ObservationStore

_FORMATTER = string.Formatter()

#: A guard returns None when the parameters are grounded, or a human-readable
#: reason when they are not. The reason is surfaced verbatim in the UI, because
#: "Warden refused to act and here is why" is more trustworthy than silence.
ParamGuard = Callable[[BaseModel, ObservationStore], str | None]

#: Derives parameters from a symptom's facts. Used by the deterministic reasoner,
#: and as the fallback when a model declines to supply them.
ParamBinder = Callable[[Symptom, ObservationStore], dict[str, JsonValue]]


class ActionRejected(Exception):
    """The proposal did not survive validation. Carries the reason for display."""


class NoParams(BaseModel):
    """For actions that take no arguments. ``extra="forbid"`` still matters here:
    it is what turns a model inventing ``{"force": true}`` into a rejection."""

    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True, slots=True)
class Playbook:
    id: str
    title: str
    summary: str
    when_to_use: str
    risk: RiskTier
    params_model: type[BaseModel]
    argv_template: list[str]
    verify: VerifySpec
    expected_effect: str
    requires_admin: bool = False
    requires_network: bool = False
    reversible: bool = True
    est_duration_s: float = 5.0
    rollback_action_id: str | None = None
    guard: ParamGuard | None = None
    binder: ParamBinder | None = None
    #: Free-text note rendered under the command in the approval card. Used to
    #: explain anything surprising about the command itself.
    note: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)

    def to_spec(self) -> ActionSpec:
        return ActionSpec(
            id=self.id,
            title=self.title,
            summary=self.summary,
            when_to_use=self.when_to_use,
            risk=self.risk,
            requires_admin=self.requires_admin,
            requires_network=self.requires_network,
            reversible=self.reversible,
            est_duration_s=self.est_duration_s,
            params_schema=self.params_model.model_json_schema(),
            argv_template=list(self.argv_template),
            verify=self.verify,
            rollback_action_id=self.rollback_action_id,
        )

    def bind(self, symptom: Symptom, store: ObservationStore) -> dict[str, JsonValue]:
        return self.binder(symptom, store) if self.binder else {}

    def propose(
        self,
        params: dict[str, JsonValue],
        store: ObservationStore,
        *,
        rationale: str,
    ) -> ActionProposal:
        """Validate, ground and render. The only way an ActionProposal is made."""
        try:
            validated = self.params_model.model_validate(params)
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
            )
            raise ActionRejected(f"parameters for {self.id} are invalid ({problems})") from exc

        if self.guard is not None:
            reason = self.guard(validated, store)
            if reason:
                raise ActionRejected(f"{self.id} refused: {reason}")

        argv = render_argv(self.argv_template, validated.model_dump())
        return ActionProposal(
            action_id=self.id,
            params=validated.model_dump(mode="json"),
            rendered_argv=argv,
            rationale=rationale,
            expected_effect=self.expected_effect,
            risk=self.risk,
            requires_admin=self.requires_admin,
            reversible=self.reversible,
            est_duration_s=self.est_duration_s,
            verify=self.verify,
        )


def render_argv(template: list[str], params: Mapping[str, object]) -> list[str]:
    """Substitute ``{name}`` placeholders token by token.

    Substitution happens *within* a token and never across tokens, which is what
    makes this safe without any escaping: ``netsh`` wants ``name=My Network`` as
    a single argument, and because the result is handed to ``CreateProcess`` as
    an argv array rather than to a shell, a value containing spaces, quotes or
    semicolons is still exactly one argument. There is no shell to inject into.

    An unknown placeholder is an error rather than an empty string. A template
    referring to a parameter that does not exist is a bug in the registry, and
    silently rendering ``name=`` would turn it into a confusing runtime failure.
    """
    rendered: list[str] = []
    for token in template:
        try:
            value = _FORMATTER.vformat(token, (), _StrictParams(params))
        except KeyError as exc:
            raise ActionRejected(
                f"template token {token!r} references unknown parameter {exc}"
            ) from exc
        if not value.strip():
            raise ActionRejected(f"template token {token!r} rendered empty")
        rendered.append(value)
    return rendered


class _StrictParams(dict[str, object]):
    def __missing__(self, key: str) -> str:  # pragma: no cover - exercised via render_argv
        raise KeyError(key)


class PlaybookRegistry:
    """The complete, closed set of things Warden can do.

    Exposed in full over the API so the capability list can be audited without
    reading source, and iterated by the reasoner prompt so the model sees exactly
    the same catalogue the guardrail will hold it to.
    """

    def __init__(self, playbooks: list[Playbook]) -> None:
        duplicates = {p.id for p in playbooks if sum(q.id == p.id for q in playbooks) > 1}
        if duplicates:
            raise ValueError(f"duplicate playbook ids: {sorted(duplicates)}")
        self._by_id = {p.id: p for p in playbooks}

    def __contains__(self, action_id: object) -> bool:
        return action_id in self._by_id

    def __iter__(self) -> Iterator[Playbook]:
        return iter(self._by_id.values())

    def __len__(self) -> int:
        return len(self._by_id)

    def get(self, action_id: str) -> Playbook:
        try:
            return self._by_id[action_id]
        except KeyError:
            raise ActionRejected(
                f"no such action {action_id!r}; Warden can only run its registered playbooks"
            ) from None

    @property
    def ids(self) -> list[str]:
        return list(self._by_id)

    def specs(self) -> list[ActionSpec]:
        return [p.to_spec() for p in self._by_id.values()]
