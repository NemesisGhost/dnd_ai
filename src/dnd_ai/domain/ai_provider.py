"""The one AI provider integration Phase 12 delivers (docs/PLAN.md: "Start
with one NPC portrayal/conversation use case, one provider ... before
broader AI infrastructure").

`AiProvider` is a `Protocol` — `dnd_ai.commands.ai_npc` depends on this
interface, never on a concrete provider class, so normal automated tests
inject `FakeAiProvider` (deterministic, no network call, no API key) and
only a deliberate smoke-test script would ever construct
`AnthropicAiProvider` — matching docs/PLAN.md's "Normal automated tests
must not depend on live provider calls; real-provider testing is limited
to deliberate smoke verification."

Structured generated output (docs/PLAN.md's own exit-criteria-adjacent
deliverable "structured generated output"): every provider returns
`ProviderResult.structured_output` as an already-validated `NpcTurnOutput`
or `None` (never a bare, unvalidated dict) — `AnthropicAiProvider` forces
this via tool use (`tool_choice`), never by asking the model to emit JSON
in free text and hoping it parses.

`AnthropicAiProvider` uses `httpx` directly against the Messages API rather
than the `anthropic` SDK — this codebase already depends on `httpx`
(`scripts/foundry_provision.py`) and adding a second HTTP client dependency
for one call shape was not judged worth it; revisit if a second provider or
a broader use case needs the SDK's other functionality.
"""

import time
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

from .context_assembly import NpcConversationContext

_ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_API_VERSION = "2023-06-01"
_RECORD_NPC_TURN_TOOL_NAME = "record_npc_turn"


class NpcTurnOutput(BaseModel):
    """The one structured-output shape this phase's NPC-portrayal use case
    produces. `reveal_knowledge_item_id`, when set, must be a member of the
    context's own `revealable_knowledge` — `dnd_ai.commands.ai_npc`
    validates this independently of whatever the model claims; this type
    only proves the *shape* of the response, never that the id is safe to
    act on."""

    dialogue: str
    reveal_knowledge_item_id: uuid.UUID | None = None


@dataclass(frozen=True)
class ProviderResult:
    raw_response: str | None
    structured_output: NpcTurnOutput | None
    finish_reason: str | None
    latency_ms: int | None
    error_message: str | None


class AiProvider(Protocol):
    def generate_npc_turn(
        self, *, context: NpcConversationContext, player_message: str
    ) -> ProviderResult: ...


class FakeAiProvider:
    """Deterministic, network-free provider for automated tests
    (`tests/unit`, `tests/database`) — never used outside test code.
    Returns a fixed `dialogue` and, when `reveal_first_candidate` is set
    and the context has at least one revealable knowledge item, proposes
    revealing it — enough to exercise `dnd_ai.commands.ai_npc`'s proposal
    pipeline without any live call."""

    def __init__(
        self, *, dialogue: str = "Hello there.", reveal_first_candidate: bool = False
    ) -> None:
        self._dialogue = dialogue
        self._reveal_first_candidate = reveal_first_candidate

    def generate_npc_turn(
        self,
        *,
        context: NpcConversationContext,
        player_message: str,  # noqa: ARG002 — fixed canned dialogue; part of the AiProvider contract
    ) -> ProviderResult:
        reveal_id = (
            context.revealable_knowledge[0].knowledge_item_id
            if self._reveal_first_candidate and context.revealable_knowledge
            else None
        )
        return ProviderResult(
            raw_response=self._dialogue,
            structured_output=NpcTurnOutput(
                dialogue=self._dialogue, reveal_knowledge_item_id=reveal_id
            ),
            finish_reason="end_turn",
            latency_ms=0,
            error_message=None,
        )


def _npc_turn_tool_schema() -> dict[str, Any]:
    return {
        "name": _RECORD_NPC_TURN_TOOL_NAME,
        "description": "Record this NPC's spoken reply and, optionally, one fact to reveal.",
        "input_schema": {
            "type": "object",
            "properties": {
                "dialogue": {"type": "string"},
                "reveal_knowledge_item_id": {"type": ["string", "null"]},
            },
            "required": ["dialogue"],
        },
    }


def _build_system_prompt(context: NpcConversationContext) -> str:
    known = "; ".join(context.known_facts_about_npc) or "nothing yet"
    candidates = (
        "; ".join(f"{k.knowledge_item_id}: {k.statement}" for k in context.revealable_knowledge)
        or "none"
    )
    return (
        f"You are {context.npc_name}, an NPC in a tabletop RPG, speaking with "
        f"{context.requesting_character_name}. Relationship status: "
        f"{context.relationship_status_code or 'unestablished'} (affinity "
        f"{context.affinity}, trust {context.trust}). "
        f"{context.requesting_character_name} already knows: {known}. "
        f"You may optionally reveal exactly one of these facts, by id, if it fits the "
        f"conversation naturally — never invent a fact or an id not in this list: {candidates}. "
        "Reply only through the record_npc_turn tool."
    )


class AnthropicAiProvider:
    """The real provider — one HTTPS call per turn, structured output
    forced via tool use. Never constructed by normal automated tests; see
    this module's own docstring."""

    def __init__(
        self, *, api_key: str, model_identifier: str, timeout_seconds: float = 30.0
    ) -> None:
        self._api_key = api_key
        self._model_identifier = model_identifier
        self._timeout_seconds = timeout_seconds

    def generate_npc_turn(
        self, *, context: NpcConversationContext, player_message: str
    ) -> ProviderResult:
        import httpx

        started = time.monotonic()
        try:
            response = httpx.post(
                _ANTHROPIC_API_URL,
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": _ANTHROPIC_API_VERSION,
                    "content-type": "application/json",
                },
                json={
                    "model": self._model_identifier,
                    "max_tokens": 1024,
                    "system": _build_system_prompt(context),
                    "messages": [{"role": "user", "content": player_message}],
                    "tools": [_npc_turn_tool_schema()],
                    "tool_choice": {"type": "tool", "name": _RECORD_NPC_TURN_TOOL_NAME},
                },
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            return ProviderResult(
                raw_response=None,
                structured_output=None,
                finish_reason=None,
                latency_ms=int((time.monotonic() - started) * 1000),
                error_message=f"{type(exc).__name__} calling the Anthropic Messages API",
            )

        latency_ms = int((time.monotonic() - started) * 1000)
        body = response.json()
        raw_response = str(body)
        tool_input = _extract_tool_input(body)
        if tool_input is None:
            return ProviderResult(
                raw_response=raw_response,
                structured_output=None,
                finish_reason=body.get("stop_reason"),
                latency_ms=latency_ms,
                error_message="Provider response did not include the expected tool call.",
            )
        try:
            structured_output = NpcTurnOutput.model_validate(tool_input)
        except ValidationError as exc:
            return ProviderResult(
                raw_response=raw_response,
                structured_output=None,
                finish_reason=body.get("stop_reason"),
                latency_ms=latency_ms,
                error_message=f"Provider tool call failed schema validation: {exc.error_count()} error(s)",
            )
        return ProviderResult(
            raw_response=raw_response,
            structured_output=structured_output,
            finish_reason=body.get("stop_reason"),
            latency_ms=latency_ms,
            error_message=None,
        )


def _extract_tool_input(body: dict[str, Any]) -> dict[str, Any] | None:
    for block in body.get("content", []):
        if isinstance(block, dict) and block.get("type") == "tool_use":
            input_value = block.get("input")
            if isinstance(input_value, dict):
                return input_value
    return None
