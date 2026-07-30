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
from pydantic import BaseModel, ConfigDict, Field, field_validator

log = logging.getLogger(__name__)

DEFAULT_ENDPOINT = "http://127.0.0.1:11434"
#: Small deliberately. The model's job here is narrow: pick one id from a
#: candidate set that usually holds a single entry, and write two sentences
#: inside a schema it cannot break. That is classification plus short
#: generation, not open reasoning, and it does not need a large model.
#:
#: The constraint that decides it is the machine. Warden ships to laptops with
#: no discrete GPU, where inference is four CPU cores: measured on an
#: i5-1135G7, a 7B model produces 4-6 tokens/s, so a 300-token decision takes
#: 60-100s and never finishes inside the timeout below. A large model that
#: always times out is strictly worse than a small one that answers, which is
#: why the fallbacks are ordered smallest-first rather than best-first.
DEFAULT_MODEL = "qwen2.5:1.5b-instruct"
FALLBACK_MODELS = ("qwen2.5:3b-instruct", "llama3.2:3b", "phi3.5", "qwen2.5:7b-instruct")


# -- coercion ---------------------------------------------------------------
#
# Ollama is handed the JSON schema as a decoding grammar, so a local reply
# cannot contain an invalid enum value: the sampler is physically unable to emit
# one. Groq's `json_object` mode guarantees only that the output parses as JSON,
# and a 70B model asked for a "domain" will cheerfully answer "Windows Search".
#
# Measured on the first real cloud call, all four in one reply:
#
#     domain       'Windows Search'                        wanted one of five
#     likelihood   'Unknown'                               wanted a float
#     service_who  'Microsoft Support or a Windows expert' wanted user/technician
#     urgency      'Medium'                                wanted routine/soon/urgent
#
# Every one of those is a *correct answer in the wrong vocabulary*. Rejecting
# the whole reply over them threw away a good diagnosis and fell back to the
# rules engine, which is the worst outcome available: the user paid for a cloud
# call, waited for it, and got the offline answer with no idea why.
#
# So these map the answer onto the vocabulary instead. They run `mode="before"`,
# they never raise, and on the local path they are no-ops because constrained
# decoding has already produced a valid value.


def _coerce_domain(value: object) -> object:
    """Free text onto the five domains, keyed on what actually routes.

    ``hardware`` is the only value with a consequence -- it routes to servicing
    rather than to a command -- so it is matched first and matched narrowly.
    Everything unrecognised lands on ``software``, which is both the commonest
    truth and the safest wrong answer, since it leads to a proposal the user
    still has to approve.
    """
    if not isinstance(value, str):
        return value
    text = value.strip().lower()
    if text in _DOMAINS:
        return text
    for needle, domain in (
        ("driver", "driver"),
        ("hardware", "hardware"),
        ("physical", "hardware"),
        ("disk", "hardware"),
        ("battery", "hardware"),
        ("thermal", "hardware"),
        ("firmware", "hardware"),
        ("config", "configuration"),
        ("setting", "configuration"),
        ("polic", "configuration"),
        ("registry", "configuration"),
        ("permission", "configuration"),
        ("network", "environment"),
        ("router", "environment"),
        ("isp", "environment"),
        ("external", "environment"),
    ):
        if needle in text:
            return domain
    return "software"


def _coerce_likelihood(value: object) -> object:
    """A number, a percentage, or a word, onto 0..1.

    Models answer this three ways and only one of them is a float. ``"85%"`` and
    ``85`` both mean the same thing; ``"Unknown"`` means the model declined,
    which is a middling confidence rather than an error.
    """
    if isinstance(value, int | float) and not isinstance(value, bool):
        number = float(value)
        return min(1.0, number / 100.0 if number > 1.0 else max(0.0, number))
    if not isinstance(value, str):
        return value
    text = value.strip().lower().rstrip("%")
    try:
        number = float(text)
    except ValueError:
        for needle, score in (
            ("very high", 0.9),
            ("high", 0.8),
            ("likely", 0.7),
            ("medium", 0.5),
            ("moderate", 0.5),
            ("possible", 0.4),
            ("low", 0.2),
            ("unlikely", 0.15),
        ):
            if needle in text:
                return score
        return 0.5  # "unknown", or anything else: no opinion
    return min(1.0, number / 100.0 if number > 1.0 else max(0.0, number))


def _coerce_choice(value: object, options: tuple[str, ...], synonyms: dict[str, str]) -> object:
    """Generic: exact match, then a synonym anywhere in the text, then the
    first option as the conservative default."""
    if not isinstance(value, str):
        return value
    text = value.strip().lower().replace("-", "_").replace(" ", "_")
    if text in options:
        return text
    for needle, chosen in synonyms.items():
        if needle in text:
            return chosen
    return options[0]


_DOMAINS = frozenset({"software", "configuration", "driver", "hardware", "environment"})

_VERDICTS = ("needs_more_data", "actionable", "needs_service")
_VERDICT_WORDS = {
    "action": "actionable",
    "fix": "actionable",
    "command": "actionable",
    "service": "needs_service",
    "hardware": "needs_service",
    "repair": "needs_service",
    "replace": "needs_service",
    "technician": "needs_service",
}

_WHO = ("technician", "user")
_WHO_WORDS = {"user": "user", "you": "user", "yourself": "user", "owner": "user"}

_URGENCY = ("routine", "soon", "urgent")
_URGENCY_WORDS = {
    "urgent": "urgent",
    "critical": "urgent",
    "immediate": "urgent",
    "high": "urgent",
    "soon": "soon",
    "medium": "soon",
    "moderate": "soon",
    "low": "routine",
    "routine": "routine",
}

_RISK = ("disruptive", "reads_only", "reversible")
_RISK_WORDS = {
    "read": "reads_only",
    "none": "reads_only",
    "safe": "reads_only",
    "revers": "reversible",
    "undo": "reversible",
    "low": "reversible",
}


class LlmHypothesis(BaseModel):
    model_config = ConfigDict(extra="ignore")

    cause: str = Field(max_length=160, description="One sentence, in plain language.")
    domain: Literal["software", "configuration", "driver", "hardware", "environment"]
    likelihood: float
    reasoning: str = Field(max_length=400)
    supporting: list[str] = Field(default_factory=list, max_length=4)
    contradicting: list[str] = Field(default_factory=list, max_length=4)

    @field_validator("domain", mode="before")
    @classmethod
    def _domain(cls, value: object) -> object:
        return _coerce_domain(value)

    @field_validator("likelihood", mode="before")
    @classmethod
    def _likelihood(cls, value: object) -> object:
        return _coerce_likelihood(value)

    @field_validator("supporting", "contradicting", mode="before")
    @classmethod
    def _trim_citations(cls, value: object) -> object:
        return value[:4] if isinstance(value, list) else value


class LlmDecision(BaseModel):
    """The only shape a model reply may take.

    Parameters are typed as strings throughout because every parameter in the
    action registry is a string -- a profile name, an interface alias, a device
    instance path. Keeping the schema free of unions keeps the decoding grammar
    small and the failure modes boring.
    """

    model_config = ConfigDict(extra="ignore")

    summary: str = Field(max_length=300)
    #: Two, not "as many as it likes". Decision latency on a CPU-only machine is
    #: dominated by tokens generated, so bounding the output is a larger lever
    #: than choosing a smaller model -- and because Pydantic emits these bounds
    #: as ``maxItems``/``maxLength`` into the JSON schema, Ollama's constrained
    #: decoding enforces them *during* generation rather than truncating after,
    #: which is where the time is actually saved. It is also better interface:
    #: nobody ever read the third hypothesis.
    hypotheses: list[LlmHypothesis] = Field(max_length=2)

    @field_validator("hypotheses", mode="before")
    @classmethod
    def _trim_hypotheses(cls, value: object) -> object:
        """Keep the first two rather than rejecting the reply.

        `max_length` is enforced during generation on the local path, where the
        schema is the decoding grammar, so it can never be exceeded. On the
        cloud path it is only a request, and a 70B asked for "at most two"
        routinely returns three.

        Throwing away an otherwise good diagnosis over a third hypothesis
        nobody was going to read is the worst possible trade, and it is what
        happened on the second real cloud call: a correct answer about a sound
        driver was discarded and the user got the rules-engine echo instead.
        """
        return value[:2] if isinstance(value, list) else value
    verdict: Literal["actionable", "needs_service", "needs_more_data"]
    action_id: str = ""
    params: dict[str, str] = Field(default_factory=dict)
    service_reason: str = ""
    service_who: Literal["user", "technician"] = "technician"
    service_next_step: str = ""
    interim_mitigation: str = ""
    urgency: Literal["routine", "soon", "urgent"] = "routine"

    @field_validator("verdict", mode="before")
    @classmethod
    def _verdict(cls, value: object) -> object:
        return _coerce_choice(value, _VERDICTS, _VERDICT_WORDS)

    @field_validator("service_who", mode="before")
    @classmethod
    def _who(cls, value: object) -> object:
        return _coerce_choice(value, _WHO, _WHO_WORDS)

    @field_validator("urgency", mode="before")
    @classmethod
    def _urgency(cls, value: object) -> object:
        return _coerce_choice(value, _URGENCY, _URGENCY_WORDS)


class LlmUnavailable(RuntimeError):
    """No local model answered. Never fatal -- the rules reasoner takes over."""


class OllamaClient:
    def __init__(
        self,
        endpoint: str = DEFAULT_ENDPOINT,
        model: str = DEFAULT_MODEL,
        timeout_s: float = 45.0,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        # A hard ceiling still matters more than a fast model -- past this the
        # incident is better served by the deterministic answer than by a user
        # watching a spinner. But the ceiling has to clear the measurement with
        # room to spare: qwen2.5:1.5b answers this machine's wireless prompt in
        # 15.1-18.7s (see docs/calibration.md), and the build ships to laptops
        # that may be slower than this one. 25s left barely any headroom and
        # would have turned a working model into a silent fallback on a machine
        # nobody here has ever seen.
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
            # Keep the weights resident between incidents. Loading a model off
            # disk costs seconds Warden would otherwise pay again on every
            # incident after an idle gap -- which is exactly when a user is
            # watching, because incidents are rare by design.
            "keep_alive": -1,
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
