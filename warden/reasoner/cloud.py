"""The cloud reasoner: a hosted model, the user's own key, and a wider remit.

Warden's local model picks an id out of a closed registry of reviewed actions
and cannot do anything else, which is what makes it safe enough to run against a
stranger's computer without asking anyone's permission first. It is also why
seventeen actions is the ceiling on what Warden can repair, and why a user with
a problem outside those seventeen is told, correctly and uselessly, that nothing
can be done.

This client answers that, and it is not free. Two things change:

**Machine data leaves the computer.** The prompt carries readings taken from the
user's machine to a third party. That is a real cost, it is disclosed everywhere
it is relevant, and it is why this is opt-in, off by default, and requires a key
the user goes and fetches themselves.

**The model may write a command.** A hosted model of this size knows the Windows
command line far better than a 1.5B model does, and confining it to the registry
would throw away the only reason to reach for it. So a cloud decision may carry
a :class:`ComposedCommand` -- an actual argv the model wrote -- when no reviewed
action fits.

The safety argument does not survive that unchanged, so it is replaced rather
than stretched. A composed command is quarantined: it never runs without
explicit approval, it is shown exactly as it will run, it is checked against
:mod:`warden.executor.freeform`'s refusal list first, and the interface labels it
as written-by-the-model rather than reviewed. The closed registry keeps its own
guarantees for every other path; what it does not do is pretend to cover this
one.

The model is still asked to prefer a reviewed action whenever one fits, because
a reviewed action is grounded, verified by a declared predicate and reversible,
and none of those are true of something written on the spot.
"""

from __future__ import annotations

import logging
import time
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from warden.reasoner.llm import LlmDecision, LlmUnavailable

log = logging.getLogger(__name__)

#: Groq's OpenAI-compatible surface. Not configurable: a "point Warden at any
#: endpoint" setting is an exfiltration primitive wearing a helpful hat.
GROQ_ENDPOINT = "https://api.groq.com/openai/v1"

#: Ordered by preference, and every one of them is a fallback for the one above.
#:
#: The job needs instruction-following and real familiarity with the Windows
#: command line, not creative writing, and it needs to come back inside a
#: schema. The 70B lands that combination most reliably of what Groq serves; the
#: rest are here so a retired model id degrades to a working one instead of to
#: an error, which on Groq happens more often than anyone would like.
DEFAULT_MODEL = "llama-3.3-70b-versatile"
FALLBACK_MODELS = (
    "openai/gpt-oss-120b",
    "moonshotai/kimi-k2-instruct",
    "llama-3.1-8b-instant",
)


class ComposedCommand(BaseModel):
    """A command the model wrote, rather than one Warden reviewed.

    Every field except ``argv`` exists to be shown to the user before they
    approve. A model that cannot say what its command changes, or how you would
    put it back, has not earned the right to run it, and the fields are
    mandatory so that "it did not say" is a schema failure rather than an empty
    box on screen.
    """

    model_config = ConfigDict(extra="ignore")

    argv: list[str] = Field(
        min_length=1,
        max_length=24,
        description="The command as an argument list. First element is the executable.",
    )
    explain: str = Field(max_length=300, description="What this command does, in plain English.")
    changes: str = Field(
        max_length=300,
        description="What it will change on the machine. 'Nothing' if it only reads.",
    )
    reversible: bool = Field(description="Whether the change can be undone.")
    undo: str = Field(
        default="",
        max_length=300,
        description="How to put it back. Required when reversible is true.",
    )
    check: str = Field(
        max_length=300,
        description="How the user can tell whether it worked, in one sentence.",
    )
    requires_admin: bool = Field(description="Whether this needs an elevated prompt.")
    risk: Literal["reads_only", "reversible", "disruptive"] = Field(
        description="How much this disturbs the machine."
    )


class CloudDecision(LlmDecision):
    """A local decision, plus the option to have written a command.

    Inherits every field the guardrail already validates, so a cloud reply that
    picks a reviewed action takes exactly the same path as a local one and gets
    exactly the same checks. ``command`` is the only new surface, and it is the
    only part that needs a new gate.
    """

    model_config = ConfigDict(extra="ignore")

    command: ComposedCommand | None = Field(
        default=None,
        description=(
            "A command you wrote yourself. Leave null when a reviewed action "
            "fits: those are grounded and verified and yours is not."
        ),
    )
    reply: str = Field(
        default="",
        max_length=1200,
        description="Your answer to the user when they asked a question in words.",
    )


class GroqClient:
    """Talks to Groq. Same six members as :class:`~warden.reasoner.llm.OllamaClient`.

    Deliberately duck-typed against that class rather than sharing a base with
    it: they have almost nothing in common underneath, and a shared abstraction
    would be one written to fit two implementations and no idea.
    """

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        timeout_s: float = 30.0,
        endpoint: str = GROQ_ENDPOINT,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key
        self.model = model
        # Far tighter than the local model's 45s. A hosted 70B answers this
        # prompt in two to four seconds; anything past thirty is a network
        # problem, and Warden is frequently running because the network has a
        # problem. Failing fast to the local model beats a long spinner.
        self.timeout_s = timeout_s
        self._available_models: list[str] = []

    @property
    def available(self) -> bool:
        return bool(self.api_key) and bool(self._available_models)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    async def refresh_models(self) -> list[str]:
        """Ask which models this key can actually reach.

        Groq retires model ids on its own schedule, so a hard-coded default goes
        stale without warning. Asking costs one small request at startup and
        turns "the cloud model silently stopped working" into a name Warden can
        pick from the list it was given.
        """
        if not self.api_key:
            self._available_models = []
            return []
        try:
            async with httpx.AsyncClient(timeout=6.0) as client:
                response = await client.get(f"{self.endpoint}/models", headers=self._headers())
                response.raise_for_status()
                payload = response.json()
            self._available_models = [
                str(entry["id"]) for entry in payload.get("data", []) if entry.get("id")
            ]
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            log.info("groq model list unavailable: %s", exc)
            self._available_models = []
        return list(self._available_models)

    def resolve_model(self) -> str | None:
        """Pick the best model this key can reach, preferring the ordered list."""
        if not self._available_models:
            return None
        for candidate in (self.model, DEFAULT_MODEL, *FALLBACK_MODELS):
            if candidate in self._available_models:
                return candidate
        return self._available_models[0]

    async def decide(self, system: str, user: str) -> tuple[CloudDecision, str, int]:
        """One decision. Raises :class:`LlmUnavailable` and nothing else.

        Matching the local client's contract exactly, including that it never
        raises anything the facade does not already catch. A cloud model that is
        down must degrade to the local model and then to the rules engine
        without any caller having to know it happened.
        """
        model = self.resolve_model()
        if model is None:
            raise LlmUnavailable("no cloud model is reachable with this key")

        body = {
            "model": model,
            "temperature": 0.2,
            "max_completion_tokens": 1400,
            # Groq's json_object mode. The schema itself is carried in the
            # prompt rather than as a grammar, because Groq's strict structured
            # mode rejects the $defs and maxLength that Pydantic emits. So the
            # reply is validated on arrival instead, and a reply that does not
            # fit is an LlmUnavailable, which falls back rather than failing.
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }

        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                response = await client.post(
                    f"{self.endpoint}/chat/completions", headers=self._headers(), json=body
                )
                if response.status_code == 401:
                    raise LlmUnavailable("the cloud key was rejected; check it on the Model page")
                if response.status_code == 429:
                    raise LlmUnavailable("the cloud model is rate limited; try again shortly")
                response.raise_for_status()
                payload = response.json()
        except httpx.TimeoutException as exc:
            raise LlmUnavailable(
                f"the cloud model did not answer within {self.timeout_s:.0f}s"
            ) from exc
        except httpx.HTTPError as exc:
            raise LlmUnavailable(f"cloud model request failed: {exc}") from exc

        latency_ms = int((time.monotonic() - started) * 1000)
        try:
            content = payload["choices"][0]["message"]["content"]
            decision = CloudDecision.model_validate_json(content)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise LlmUnavailable(f"cloud reply did not fit the required schema: {exc}") from exc

        return decision, model, latency_ms
