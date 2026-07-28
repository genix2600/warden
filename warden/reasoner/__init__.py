"""The reasoner facade: try the local model, fall back to rules, never block.

The fallback is not error handling bolted on afterwards -- it is the contract.
``diagnose`` always returns a usable ``Diagnosis``. Whether it came from the
model or from the rules is recorded on the diagnosis itself and shown in the
interface, so the user always knows which brain answered and why.
"""

from __future__ import annotations

import logging

from warden.contracts import Diagnosis, Symptom
from warden.playbooks import REGISTRY, PlaybookRegistry
from warden.reasoner.guardrail import GuardrailRejection, validate
from warden.reasoner.llm import DEFAULT_MODEL, LlmUnavailable, OllamaClient
from warden.reasoner.prompt import SYSTEM_PROMPT, build_user_prompt
from warden.reasoner.rules import RulesReasoner, primary_symptom
from warden.store import ObservationStore

log = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_MODEL",
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

    @property
    def client(self) -> OllamaClient:
        return self._client

    async def probe_model(self) -> str | None:
        """Refresh what is installed. Called at startup and by the doctor endpoint."""
        if not self._use_llm:
            return None
        await self._client.refresh_models()
        return self._client.resolve_model()

    async def diagnose(
        self,
        symptoms: list[Symptom],
        store: ObservationStore,
        exclude: frozenset[str] = frozenset(),
    ) -> Diagnosis:
        """Diagnose, optionally excluding actions already proven not to work here."""
        symptom = primary_symptom(symptoms)
        fallback_reason: str | None = None

        if self._use_llm and self._client.available:
            try:
                decision, model, latency_ms = await self._client.decide(
                    SYSTEM_PROMPT,
                    build_user_prompt(symptom, store, self._registry, exclude),
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
        elif self._use_llm:
            fallback_reason = "no local model is running; start Ollama for written explanations"
        else:
            fallback_reason = "the local model is disabled for this session"

        diagnosis = self._rules.diagnose(symptoms, store, exclude)
        diagnosis.reasoner = diagnosis.reasoner.model_copy(
            update={"fallback_reason": fallback_reason}
        )
        return diagnosis
