"""Local model client, and the schema its answer must fit.

Warden talks to a model running on the same machine, through Ollama. That is a
design requirement rather than a cost decision: the headline scenario is a
laptop whose network has dropped, and a diagnostician that needs the internet to
explain why you have no internet is not a diagnostician. It also means the repo
has no key to leak and telemetry has nowhere to go -- the machine's event log,
device inventory and network configuration never leave it.

The model is given a closed catalogue of actions and asked to *choose*, never to
compose. Its response is constrained twice: by a JSON schema enforced during
decoding, so it cannot emit prose where an action id belongs, and then by the
guardrail, which checks the choice against the candidate set and the parameters
against reality. Anything that fails either check falls back to the rules
reasoner, and the reason is shown in the interface rather than swallowed.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

log = logging.getLogger(__name__)

DEFAULT_ENDPOINT = "http://127.0.0.1:11434"
#: Chosen for instruction-following and reliable structured output at a size that
#: fits a student laptop. Overridable, because the right answer depends on the
#: machine Warden is installed on.
DEFAULT_MODEL = "qwen2.5:7b-instruct"
FALLBACK_MODELS = ("qwen2.5:3b-instruct", "llama3.1:8b", "phi3.5")


class LlmHypothesis(BaseModel):
    model_config = ConfigDict(extra="ignore")

    cause: str = Field(description="One sentence, in plain language.")
    domain: Literal["software", "configuration", "driver", "hardware", "environment"]
    likelihood: float
    reasoning: str
    supporting: list[str] = Field(default_factory=list)
    contradicting: list[str] = Field(default_factory=list)


class LlmDecision(BaseModel):
    """The only shape a model reply may take.

    Parameters are typed as strings throughout because every parameter in the
    action registry is a string -- a profile name, an interface alias, a device
    instance path. Keeping the schema free of unions keeps the decoding grammar
    small and the failure modes boring.
    """

    model_config = ConfigDict(extra="ignore")

    summary: str
    hypotheses: list[LlmHypothesis]
    verdict: Literal["actionable", "needs_service", "needs_more_data"]
    action_id: str = ""
    params: dict[str, str] = Field(default_factory=dict)
    service_reason: str = ""
    service_who: Literal["user", "technician"] = "technician"
    service_next_step: str = ""
    interim_mitigation: str = ""
    urgency: Literal["routine", "soon", "urgent"] = "routine"


class LlmUnavailable(RuntimeError):
    """No local model answered. Never fatal -- the rules reasoner takes over."""


class OllamaClient:
    def __init__(
        self,
        endpoint: str = DEFAULT_ENDPOINT,
        model: str = DEFAULT_MODEL,
        timeout_s: float = 25.0,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        # A hard ceiling matters more than a fast model. If reasoning has not
        # finished by now the incident is better served by the deterministic
        # answer than by a user watching a spinner.
        self.timeout_s = timeout_s
        self._available_models: list[str] = []

    async def refresh_models(self) -> list[str]:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(f"{self.endpoint}/api/tags")
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            log.info("no local model service at %s (%s)", self.endpoint, exc)
            self._available_models = []
            return []
        self._available_models = [
            m["name"] for m in payload.get("models", []) if isinstance(m, dict) and "name" in m
        ]
        return self._available_models

    def resolve_model(self) -> str | None:
        """Pick the best installed model, so a missing preferred tag is not fatal."""
        if not self._available_models:
            return None
        names = self._available_models
        for candidate in (self.model, *FALLBACK_MODELS):
            for name in names:
                if name == candidate or name.startswith(candidate.split(":")[0] + ":"):
                    return name
        return names[0]

    @property
    def available(self) -> bool:
        return bool(self._available_models)

    async def decide(self, system: str, user: str) -> tuple[LlmDecision, str, int]:
        """Ask for a decision. Returns (decision, model used, latency in ms)."""
        model = self.resolve_model()
        if model is None:
            raise LlmUnavailable("no local model is installed")

        body: dict[str, Any] = {
            "model": model,
            "stream": False,
            # Schema-constrained decoding. The model is not asked politely for
            # JSON, it is prevented from emitting anything else.
            "format": LlmDecision.model_json_schema(),
            "options": {"temperature": 0.1, "num_ctx": 8192},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                response = await client.post(f"{self.endpoint}/api/chat", json=body)
                response.raise_for_status()
                payload = response.json()
        except httpx.TimeoutException as exc:
            raise LlmUnavailable(
                f"the local model did not answer within {self.timeout_s:.0f}s"
            ) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise LlmUnavailable(f"local model request failed: {exc}") from exc

        latency_ms = int(payload.get("total_duration", 0) / 1_000_000) or 0
        content = (payload.get("message") or {}).get("content") or ""
        try:
            decision = LlmDecision.model_validate(json.loads(content))
        except (json.JSONDecodeError, ValueError) as exc:
            raise LlmUnavailable(f"model reply did not fit the required schema: {exc}") from exc
        return decision, model, latency_ms
