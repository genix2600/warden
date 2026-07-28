"""Prompt construction.

Two principles.

**The model sees exactly what the guardrail will hold it to.** The candidate
action list in the prompt is generated from the same registry the guardrail
validates against, so the model is never punished for a rule it was not told.
When the candidate list is empty, the prompt says so explicitly rather than
leaving the model to infer it from silence -- that is the case where a helpful
model is most tempted to invent a command.

**Evidence is quoted with its identifiers.** The model is asked to cite the
observation ids it relied on, and the guardrail drops citations that do not
resolve. A hypothesis that cannot point at a reading is one the interface will
show as unsupported.
"""

from __future__ import annotations

import json
from typing import Any

from warden.contracts import Observation, Symptom
from warden.playbooks import CANDIDATES, PlaybookRegistry
from warden.store import ObservationStore
from warden.winenv import describe_host

SYSTEM_PROMPT = """\
You are the reasoning stage of Warden, a diagnostic agent running on the user's \
own Windows machine. Deterministic collectors have already read the machine and \
deterministic detectors have already established the symptom. You are not being \
asked to detect anything, and you have no way to run commands.

Your job is to explain what is most likely wrong, and to choose at most one \
action from the list you are given.

Rules you must follow:

1. Choose only from the numbered actions provided. You cannot write a command, \
   and an action id that is not in the list will be rejected.
2. If the action list is empty, there is no software fix for this problem. Set \
   verdict to "needs_service" and say plainly what the user or a technician has \
   to do physically. Never imply a command exists when none was offered.
3. Prefer the lowest-risk action that could plausibly work. Do not reach for a \
   restart when a reconnect is offered.
4. If the evidence does not support any confident cause, set verdict to \
   "needs_more_data" rather than guessing.
5. Cite observation ids in "supporting" and "contradicting". Include the \
   readings that argue against your leading explanation -- a hypothesis with \
   nothing against it usually means you did not look.
6. Write for someone who is not a technician. No jargon that you do not \
   immediately explain, and no generic advice such as "restart your computer" or \
   "check your settings".

You are judged on whether the user ends up with a working machine and an \
accurate understanding of what happened, not on sounding confident.
"""


def _trim(value: Any, limit: int = 400) -> Any:
    """Keep the prompt readable. Long inventories are summarised, not dumped."""
    text = json.dumps(value, default=str)
    if len(text) <= limit:
        return value
    if isinstance(value, list):
        return {"first_items": value[:3], "total_items": len(value)}
    return text[:limit] + "..."


def _format_evidence(observations: list[Observation]) -> str:
    lines = []
    for obs in observations:
        lines.append(
            f"  [{obs.id}] {obs.source} = {json.dumps(_trim(obs.value), default=str)}"
            f"{' ' + obs.unit if obs.unit else ''}"
            f"  (read by: {obs.provenance.probe}; confidence {obs.confidence:g})"
        )
    return "\n".join(lines) if lines else "  (none)"


def _format_actions(
    symptom: Symptom, registry: PlaybookRegistry, exclude: frozenset[str] = frozenset()
) -> str:
    candidates = tuple(a for a in CANDIDATES.get(symptom.code, ()) if a not in exclude)
    if not candidates:
        exhausted = (
            "\n\n  Every action for this symptom has already been tried and verified as\n"
            "  not having worked, so there is nothing left to escalate to."
            if exclude
            else ""
        )
        return (
            "  (no actions are available for this symptom)\n\n"
            "  This is not an oversight. Warden's action registry has been reviewed and\n"
            "  contains no command that can fix this condition. The correct verdict is\n"
            '  "needs_service".' + exhausted
        )
    blocks = []
    for index, action_id in enumerate(candidates, start=1):
        playbook = registry.get(action_id)
        properties = playbook.params_model.model_json_schema().get("properties", {})
        params = ", ".join(properties) or "none"
        blocks.append(
            f"  {index}. id: {playbook.id}\n"
            f"     what it does: {playbook.summary}\n"
            f"     use it when: {playbook.when_to_use}\n"
            f"     risk: {playbook.risk.value}"
            f"{', needs administrator' if playbook.requires_admin else ''}\n"
            f"     parameters: {params}\n"
            f"     proof it worked: {playbook.verify.predicate.describe}"
        )
    return "\n\n".join(blocks)


def build_user_prompt(
    symptom: Symptom,
    store: ObservationStore,
    registry: PlaybookRegistry,
    exclude: frozenset[str] = frozenset(),
    extra_sources: tuple[str, ...] = (
        "sys.cpu.percent",
        "sys.memory",
        "log.system_errors",
    ),
) -> str:
    host = describe_host()
    cited = [obs for obs_id in symptom.evidence if (obs := store.by_id(obs_id)) is not None]
    context = [obs for source in extra_sources if (obs := store.latest(source)) is not None]
    already_tried = (
        "\nALREADY TRIED ON THIS INCIDENT (ran, and verification showed it did not work)\n"
        + "\n".join(f"  - {a}" for a in sorted(exclude))
        + "\n  Do not propose these again. Escalate or conclude.\n"
        if exclude
        else ""
    )

    return f"""\
MACHINE
  {host["os"]} (build {host["version"]}), {host["machine"]}
  Warden is running {"with" if host["elevated"] == "true" else "without"} administrator rights.

SYMPTOM (established deterministically, not by you)
  code:     {symptom.code}
  severity: {symptom.severity.value}
  title:    {symptom.title}
  detail:   {symptom.detail}
  detector: {symptom.detector} v{symptom.detector_version}

MEASURED FACTS
{json.dumps({k: _trim(v) for k, v in symptom.facts.items()}, indent=2, default=str)}

EVIDENCE THE DETECTOR CITED
{_format_evidence(cited)}

OTHER CURRENT READINGS
{_format_evidence(context)}
{already_tried}
ACTIONS YOU MAY CHOOSE FROM
{_format_actions(symptom, registry, exclude)}

Answer with the required JSON object.\
"""
