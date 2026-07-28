"""Validation of model output, before it becomes a proposal a human can approve.

This is the layer that makes it safe to let a 7-billion-parameter model
influence what runs on someone's computer. It assumes the model is capable,
well-intentioned and occasionally wrong in ways that sound completely
reasonable, and it checks accordingly:

* the chosen action must be in the candidate set *for this symptom* -- not
  merely somewhere in the registry, so a model cannot answer a full disk by
  restarting the wireless adapter;
* the parameters must survive the playbook's own grounding guard, so a model
  cannot invent a network name or a device path;
* an ``actionable`` verdict for a symptom with no candidate actions is refused
  outright, which is the specific failure this project cares most about --
  a model manufacturing a software fix for a physical problem;
* every cited observation id must resolve to a real reading; ones that do not
  are dropped rather than displayed as evidence.

Refusals are not silent. Each one is recorded on the diagnosis and rendered in
the interface, because "the model suggested this and Warden would not run it" is
information the user is entitled to.
"""

from __future__ import annotations

import logging

from warden.contracts import (
    Diagnosis,
    Domain,
    Hypothesis,
    ReasonerInfo,
    ReasonerMode,
    ServiceAdvice,
    Symptom,
    Verdict,
)
from warden.playbooks import CANDIDATES, ActionRejected, PlaybookRegistry
from warden.reasoner.llm import LlmDecision
from warden.reasoner.rules import Draft, assemble
from warden.store import ObservationStore

log = logging.getLogger(__name__)


class GuardrailRejection(Exception):
    """The model's answer cannot be used. The caller falls back to rules."""


def validate(
    decision: LlmDecision,
    symptom: Symptom,
    store: ObservationStore,
    registry: PlaybookRegistry,
    *,
    model: str,
    latency_ms: int,
    exclude: frozenset[str] = frozenset(),
) -> Diagnosis:
    rejections: list[str] = []
    candidates = tuple(a for a in CANDIDATES.get(symptom.code, ()) if a not in exclude)

    hypotheses = _clean_hypotheses(decision, store, rejections)
    if not hypotheses:
        raise GuardrailRejection("the model returned no usable hypotheses")

    summary = decision.summary.strip()
    if not summary:
        raise GuardrailRejection("the model returned an empty summary")

    proposal = None
    advice = None
    force_verdict = None

    if decision.verdict == "actionable":
        if not candidates:
            # The exact mistake the whole design exists to prevent.
            raise GuardrailRejection(
                f"the model proposed acting on {symptom.code}, for which Warden's registry "
                f"deliberately contains no action; a physical problem has no software fix"
            )
        if decision.action_id in exclude:
            raise GuardrailRejection(
                f"the model proposed {decision.action_id!r} again, which was already run on "
                f"this incident and verified as not having worked"
            )
        if decision.action_id not in candidates:
            raise GuardrailRejection(
                f"the model chose {decision.action_id!r}, which is not among the actions "
                f"available for {symptom.code} ({', '.join(candidates) or 'none remaining'})"
            )
        playbook = registry.get(decision.action_id)
        # Bound parameters come from observed facts; the model may override them,
        # but every override still has to pass the playbook's grounding guard.
        params = {**playbook.bind(symptom, store), **decision.params}
        try:
            proposal = playbook.propose(params, store, rationale=hypotheses[0].reasoning)
        except ActionRejected as exc:
            raise GuardrailRejection(str(exc)) from exc

    elif decision.verdict == "needs_service":
        if not decision.service_reason.strip() or not decision.service_next_step.strip():
            raise GuardrailRejection(
                "the model declined to act but did not say what the user should do instead"
            )
        advice = ServiceAdvice(
            reason=decision.service_reason.strip(),
            who=decision.service_who,
            next_step=decision.service_next_step.strip(),
            interim_mitigation=decision.interim_mitigation.strip() or None,
            urgency=decision.urgency,
        )
        force_verdict = Verdict.NEEDS_SERVICE
    else:
        force_verdict = Verdict.NEEDS_MORE_DATA

    draft = Draft(
        summary=summary, hypotheses=hypotheses, advice=advice, force_verdict=force_verdict
    )
    reasoner = ReasonerInfo(
        mode=ReasonerMode.LLM,
        model=model,
        latency_ms=latency_ms,
        guardrail_rejections=rejections,
    )
    return assemble(symptom, draft, store, registry, reasoner, proposal=proposal, exclude=exclude)


def _clean_hypotheses(
    decision: LlmDecision, store: ObservationStore, rejections: list[str]
) -> list[Hypothesis]:
    cleaned: list[Hypothesis] = []
    for raw in decision.hypotheses:
        cause = raw.cause.strip()
        if not cause:
            continue
        supporting = _resolve(raw.supporting, store)
        contradicting = _resolve(raw.contradicting, store)
        dropped = (len(raw.supporting) - len(supporting)) + (
            len(raw.contradicting) - len(contradicting)
        )
        if dropped:
            rejections.append(
                f"dropped {dropped} citation(s) from {cause[:50]!r} that referred to "
                f"readings which do not exist"
            )
        cleaned.append(
            Hypothesis(
                cause=cause,
                domain=Domain(raw.domain),
                likelihood=min(max(raw.likelihood, 0.0), 1.0),
                reasoning=raw.reasoning.strip() or "No reasoning was given.",
                supporting=supporting,
                contradicting=contradicting,
            )
        )
    return cleaned


def _resolve(ids: list[str], store: ObservationStore) -> list[str]:
    return [i for i in ids if store.by_id(i) is not None]
