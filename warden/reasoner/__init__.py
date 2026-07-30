"""The reasoner facade: try the best brain available, fall back, never block.

The fallback is not error handling bolted on afterwards -- it is the contract.
``diagnose`` always returns a usable ``Diagnosis``. Which brain answered is
recorded on the diagnosis itself and shown in the interface, so the user always
knows, and the three are never blurred together.

There are three now, tried in this order:

**Cloud**, only if the user has enabled it and supplied a key. Knows the Windows
command line properly and may write a command when no reviewed action fits,
which is the only reason to reach for it. Costs a round trip and sends readings
off the machine.

**Local**, on this machine's processor. Confined to the reviewed registry,
sends nothing anywhere, and keeps working when the network is the fault -- which
is why it stays the default and why the cloud path can never be required.

**Rules**, deterministic, always available, and the reason the other two are
optional rather than load-bearing.

The ordering is the whole design. Each step down is a strict reduction in
capability and a strict increase in reliability, so a failure at any level lands
somewhere that still works. A cloud key that has expired, a Groq outage, a
rate limit, an unparseable reply: all of them degrade to the local model, and
then to rules, and the interface says which one you got and why.
"""

from __future__ import annotations

import logging

from warden.contracts import Diagnosis, ReasonerMode, Symptom
from warden.playbooks import REGISTRY, PlaybookRegistry
from warden.reasoner.cloud import GroqClient
from warden.reasoner.guardrail import GuardrailRejection, validate
from warden.reasoner.llm import DEFAULT_MODEL, LlmUnavailable, OllamaClient
from warden.reasoner.prompt import (
    CLOUD_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
    build_user_prompt,
)
from warden.reasoner.rules import RulesReasoner, primary_symptom
from warden.store import ObservationStore

log = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_MODEL",
    "GroqClient",
    "GuardrailRejection",
    "OllamaClient",
    "Reasoner",
    "RulesReasoner",
]


class Reasoner:
    def __init__(
        self,
        client: OllamaClient | None = None,
        registry: PlaybookRegistry = REGISTRY,
        use_llm: bool = True,
    ) -> None:
        self._client = client or OllamaClient()
        self._registry = registry
        self._rules = RulesReasoner(registry)
        self._use_llm = use_llm
        #: Set by the API when the user enables cloud mode with a key. None
        #: means the whole cloud path does not exist, which is the default and
        #: the state every install starts in.
        self._cloud: GroqClient | None = None

    @property
    def client(self) -> OllamaClient:
        return self._client

    @property
    def cloud(self) -> GroqClient | None:
        return self._cloud

    def set_cloud(self, client: GroqClient | None) -> None:
        """Turn cloud mode on or off for the running agent.

        A setter rather than a constructor argument because the key arrives
        while Warden is already running: the user pastes it into the Model page
        and expects the next diagnosis to use it, without a restart.
        """
        self._cloud = client

    async def probe_model(self) -> str | None:
        """Refresh what is reachable. Called at startup and by the doctor endpoint."""
        if self._cloud is not None:
            await self._cloud.refresh_models()
        if not self._use_llm:
            return None
        await self._client.refresh_models()
        return self._client.resolve_model()

    async def diagnose(
        self,
        symptoms: list[Symptom],
        store: ObservationStore,
        exclude: frozenset[str] = frozenset(),
        note: str = "",
    ) -> Diagnosis:
        """Diagnose, optionally excluding actions already proven not to work here.

        ``note`` carries what the user typed, when they described the problem in
        their own words rather than letting a detector find it. It goes into the
        prompt and nowhere else.
        """
        symptom = primary_symptom(symptoms)
        fallback_reason: str | None = None

        if self._cloud is not None:
            if not self._cloud.available:
                await self._cloud.refresh_models()
            if self._cloud.available:
                try:
                    return await self._diagnose_cloud(symptom, store, exclude, note)
                except (LlmUnavailable, GuardrailRejection) as exc:
                    fallback_reason = f"the cloud model was not used: {exc}"
                    log.info("cloud path failed, trying local: %s", exc)
            else:
                fallback_reason = "cloud mode is on but no model is reachable with that key"

        # Re-probe before giving up on the model. ``available`` is a cached
        # answer from the last check, and there are now several ways for it to
        # be stale in the user's favour: the bundled runtime starts in the
        # background and may not have been listening at startup, the user may
        # have downloaded the model since, or they may have started their own
        # Ollama. Falling back to rules while a working model sits there --
        # for the rest of the session, because nothing else refreshes it --
        # would be the wrong answer arrived at cheaply.
        if self._use_llm and not self._client.available:
            await self._client.refresh_models()

        if self._use_llm and self._client.available:
            try:
                decision, model, latency_ms = await self._client.decide(
                    SYSTEM_PROMPT,
                    build_user_prompt(symptom, store, self._registry, exclude, note),
                )
                return validate(
                    decision,
                    symptom,
                    store,
                    self._registry,
                    model=model,
                    latency_ms=latency_ms,
                    exclude=exclude,
                )
            except (LlmUnavailable, GuardrailRejection) as exc:
                fallback_reason = str(exc)
                log.info("falling back to rules: %s", fallback_reason)
        elif self._use_llm and fallback_reason is None:
            fallback_reason = "no local model is running; start Ollama for written explanations"
        elif fallback_reason is None:
            fallback_reason = "the local model is disabled for this session"

        diagnosis = self._rules.diagnose(symptoms, store, exclude)
        diagnosis.reasoner = diagnosis.reasoner.model_copy(
            update={"fallback_reason": fallback_reason}
        )
        return diagnosis

    async def _diagnose_cloud(
        self,
        symptom: Symptom,
        store: ObservationStore,
        exclude: frozenset[str],
        note: str,
    ) -> Diagnosis:
        """One cloud decision, validated two different ways.

        If the model picked a reviewed action it goes through the identical
        guardrail as a local answer, because the guarantees a reviewed action
        carries do not depend on which model chose it. Only when it wrote a
        command does the second path open, and that one is screened by the
        refusal list rather than by grounding.
        """
        assert self._cloud is not None
        decision, model, latency_ms = await self._cloud.decide(
            CLOUD_SYSTEM_PROMPT,
            build_user_prompt(
                symptom, store, self._registry, exclude, note, may_compose=True
            ),
        )

        # A reviewed action always wins. It is grounded against what was
        # actually observed, it declares a predicate that will decide whether it
        # worked, and it is reversible. None of that is true of a command
        # written a second ago, so a model that offers both gets the better one
        # taken and the other discarded.
        if decision.action_id:
            diagnosis = validate(
                decision,
                symptom,
                store,
                self._registry,
                model=model,
                latency_ms=latency_ms,
                exclude=exclude,
            )
            diagnosis.reasoner = diagnosis.reasoner.model_copy(
                update={"mode": ReasonerMode.CLOUD}
            )
            return diagnosis

        return build_composed_diagnosis(decision, symptom, model, latency_ms)


def build_composed_diagnosis(
    decision: object,
    symptom: Symptom,
    model: str,
    latency_ms: int,
) -> Diagnosis:
    """Turn a cloud reply that wrote a command into a Diagnosis.

    Split out of the class so that the chat path, which has no symptom from a
    detector, can reuse it without going through incident machinery.
    """
    from warden.contracts import (
        ComposedCommand,
        Domain,
        Hypothesis,
        ReasonerInfo,
        ServiceAdvice,
        Verdict,
    )
    from warden.executor.freeform import screen
    from warden.reasoner.cloud import CloudDecision

    assert isinstance(decision, CloudDecision)
    composed = None
    if decision.command is not None:
        refusal = screen(decision.command.argv)
        composed = ComposedCommand(
            argv=list(decision.command.argv),
            explain=decision.command.explain,
            changes=decision.command.changes,
            reversible=decision.command.reversible,
            undo=decision.command.undo,
            check=decision.command.check,
            requires_admin=decision.command.requires_admin,
            risk=decision.command.risk,
            refused=refusal,
        )

    verdict = (
        Verdict.ACTIONABLE
        if composed is not None and composed.refused is None
        else Verdict.NEEDS_MORE_DATA
    )

    # `Diagnosis` enforces that a needs_service verdict carries service advice,
    # and this used to set the verdict while dropping the fields the model had
    # already filled in -- so a perfectly good "this needs a person" answer
    # raised a ValidationError, the diagnosis task swallowed it, and the
    # incident landed in `monitoring` with no diagnosis at all and nothing on
    # screen to say why. Caught on the first live call against a real model.
    #
    # The verdict is downgraded rather than the advice invented. A model that
    # says "needs a technician" and cannot say what for has not produced advice,
    # and printing an empty reason under a confident heading is the failure mode
    # this whole contract exists to prevent.
    advice: ServiceAdvice | None = None
    rejections: list[str] = []
    if decision.verdict == "needs_service":
        reason = decision.service_reason.strip()
        next_step = decision.service_next_step.strip()
        physical = any(h.domain == "hardware" for h in decision.hypotheses)

        if not physical:
            # Measured, repeatedly, against a real model: asked about a broken
            # search index, a muted audio device and an offline printer, it
            # answered "needs_service / contact a technician" to all three. All
            # three are software and all three have a one-line fix.
            #
            # `needs_service` means *no command could ever help*, which is a
            # claim about physics. A model reaching for it because it is
            # uncertain produces the exact useless non-answer this product was
            # built to replace, and no amount of prompt wording made that
            # reliable -- so it is checked here instead, against the model's own
            # stated cause. If nothing it listed is hardware, it does not get to
            # send the user to a repair shop.
            rejections.append(
                "The model wanted to send you to a technician, but none of the "
                "causes it gave are physical. Warden downgraded that: a software "
                "fault is not something a repair shop can help with either."
            )
            verdict = Verdict.NEEDS_MORE_DATA
        elif reason and next_step:
            verdict = Verdict.NEEDS_SERVICE
            composed = None  # a physical cause cannot also have a command
            advice = ServiceAdvice(
                reason=reason,
                who=decision.service_who,
                next_step=next_step,
                interim_mitigation=decision.interim_mitigation.strip() or None,
                urgency=decision.urgency,
            )
        else:
            # It said "needs a person" and could not say what for. That is not
            # advice, and printing an empty reason under a confident heading is
            # the failure this contract exists to prevent.
            verdict = Verdict.NEEDS_MORE_DATA

    return Diagnosis(
        symptom_codes=[symptom.code],
        summary=decision.summary or decision.reply,
        ranked_hypotheses=[
            Hypothesis(
                cause=h.cause,
                domain=Domain(h.domain),
                likelihood=max(0.0, min(1.0, h.likelihood)),
                reasoning=h.reasoning,
                # Citations are dropped rather than trusted. The local path
                # resolves them against the store and discards the ones that do
                # not exist; a cloud model is if anything more likely to invent
                # an id, and an unresolvable citation on screen is worse than
                # none.
                supporting=[],
                contradicting=list(h.contradicting),
            )
            for h in decision.hypotheses
        ],
        verdict=verdict,
        service_advice=advice,
        composed=composed,
        reasoner=ReasonerInfo(
            mode=ReasonerMode.CLOUD,
            model=model,
            latency_ms=latency_ms,
            guardrail_rejections=(
                rejections
                + (
                    [f"Warden refused the command it wrote: {composed.refused}"]
                    if composed is not None and composed.refused
                    else []
                )
            ),
        ),
    )
