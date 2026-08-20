"""The one AI provider integration Phase 12 delivers (docs/PLAN.md: "Start
with one NPC portrayal/conversation use case, one provider ... before
broader AI infrastructure").

`AiProvider` is a `Protocol` — `dnd_ai.commands.ai_npc` depends on this
interface, never on a concrete provider class, so normal automated tests
inject `FakeAiProvider` (deterministic, no network call, no API key) and
only a deliberate smoke-test script would ever construct
`OpenAiCompatibleProvider` — matching docs/PLAN.md's "Normal automated
tests must not depend on live provider calls; real-provider testing is
limited to deliberate smoke verification."

Structured generated output (docs/PLAN.md's own exit-criteria-adjacent
deliverable "structured generated output"): every provider returns
`ProviderResult.structured_output` as an already-validated `NpcTurnOutput`
or `None` (never a bare, unvalidated dict) — `OpenAiCompatibleProvider`
forces this via function-calling (`tool_choice` naming one function),
never by asking the model to emit JSON in free text and hoping it parses.

`OpenAiCompatibleProvider` targets the OpenAI Chat Completions API shape —
`POST {base_url}/chat/completions`, bearer auth, `tools`/`tool_choice`
function calling — rather than a vendor SDK, for two reasons at once: this
codebase already depends on `httpx` (`scripts/foundry_provision.py`) and
adding a vendor SDK dependency for one call shape was not judged worth it,
and the Chat Completions request/response shape is also the one nearly
every self-hosted inference server (Ollama, vLLM, LM Studio,
text-generation-webui, llama.cpp's own server, ...) chooses to mirror
specifically so existing OpenAI clients work against them unchanged. One
provider class therefore serves both real OpenAI (`base_url` defaults to
`https://api.openai.com/v1`) and a locally hosted model (point `base_url`
at the local server instead — see `dnd_ai.config.Settings.ai_provider_
base_url`) — the "path forward for a locally hosted model" is this same
class with different configuration, not a second implementation. Function-
calling fidelity still varies by local model/runtime; a model that ignores
`tool_choice` surfaces as an ordinary `error_message` result
(`_extract_tool_call` returning `None`), the same as any other malformed
provider response — never a crash, and never treated as this class's own
bug.
"""

import json
import time
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from pydantic import BaseModel, ValidationError

from .context_assembly import NpcConversationContext

if TYPE_CHECKING:
    import httpx

_DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
_RECORD_NPC_TURN_FUNCTION_NAME = "record_npc_turn"
_RECORD_SYNTHESIS_ANSWER_FUNCTION_NAME = "record_synthesis_answer"


class NpcTurnOutput(BaseModel):
    """The one structured-output shape this phase's NPC-portrayal use case
    produces. `reveal_knowledge_item_id`, when set, must be a member of the
    context's own `revealable_knowledge` — `dnd_ai.commands.ai_npc`
    validates this independently of whatever the model claims; this type
    only proves the *shape* of the response, never that the id is safe to
    act on."""

    dialogue: str
    reveal_knowledge_item_id: uuid.UUID | None = None


class SynthesisOutput(BaseModel):
    """The structured-output shape `dnd_ai.commands.ai_synthesis` produces —
    a single audience-tier-appropriate prose answer, grounded only in the
    already-filtered `CampaignSynthesisContext` payload it was given."""

    answer: str


@dataclass(frozen=True)
class ProviderResult:
    raw_response: str | None
    structured_output: NpcTurnOutput | None
    finish_reason: str | None
    latency_ms: int | None
    error_message: str | None


@dataclass(frozen=True)
class SynthesisProviderResult:
    raw_response: str | None
    structured_output: SynthesisOutput | None
    finish_reason: str | None
    latency_ms: int | None
    error_message: str | None


class AiProvider(Protocol):
    def generate_npc_turn(
        self, *, context: NpcConversationContext, player_message: str
    ) -> ProviderResult: ...

    def generate_synthesis(
        self, *, context: dict[str, Any], audience_tier: str, question_text: str
    ) -> SynthesisProviderResult: ...


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

    def generate_synthesis(
        self,
        *,
        context: dict[str, Any],
        audience_tier: str,  # noqa: ARG002 — fixed canned answer; part of the AiProvider contract
        question_text: str,  # noqa: ARG002 — fixed canned answer; part of the AiProvider contract
    ) -> SynthesisProviderResult:
        answer = f"({context.get('audience_tier')}) {self._dialogue}"
        return SynthesisProviderResult(
            raw_response=answer,
            structured_output=SynthesisOutput(answer=answer),
            finish_reason="end_turn",
            latency_ms=0,
            error_message=None,
        )


def _npc_turn_function_schema() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": _RECORD_NPC_TURN_FUNCTION_NAME,
            "description": "Record this NPC's spoken reply and, optionally, one fact to reveal.",
            "parameters": {
                "type": "object",
                "properties": {
                    "dialogue": {"type": "string"},
                    "reveal_knowledge_item_id": {"type": ["string", "null"]},
                },
                "required": ["dialogue"],
            },
        },
    }


def _build_system_prompt(context: NpcConversationContext) -> str:
    known = "; ".join(context.known_facts_about_npc) or "nothing yet"
    candidates = (
        "; ".join(f"{k.knowledge_item_id}: {k.statement}" for k in context.revealable_knowledge)
        or "none"
    )
    quests = (
        "; ".join(
            f"{q.name} ({q.participant_role}, currently {q.status_code})"
            for q in context.related_quests
        )
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
        f"Quests you are involved in: {quests}. "
        "Reply only through the record_npc_turn function."
    )


class OpenAiCompatibleProvider:
    """The real provider — one HTTPS call per turn against an OpenAI Chat
    Completions-shaped endpoint, structured output forced via function
    calling. Never constructed by normal automated tests; see this
    module's own docstring for why this one class covers both real OpenAI
    and a locally hosted, OpenAI-API-compatible model server."""

    def __init__(
        self,
        *,
        api_key: str | None,
        model_identifier: str,
        base_url: str = _DEFAULT_OPENAI_BASE_URL,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._api_key = api_key
        self._model_identifier = model_identifier
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    def _headers(self) -> dict[str, str]:
        headers = {"content-type": "application/json"}
        if self._api_key:
            headers["authorization"] = f"Bearer {self._api_key}"
        return headers

    def generate_npc_turn(
        self, *, context: NpcConversationContext, player_message: str
    ) -> ProviderResult:
        import httpx

        started = time.monotonic()
        try:
            response = httpx.post(
                f"{self._base_url}/chat/completions",
                headers=self._headers(),
                json={
                    "model": self._model_identifier,
                    "messages": [
                        {"role": "system", "content": _build_system_prompt(context)},
                        {"role": "user", "content": player_message},
                    ],
                    "tools": [_npc_turn_function_schema()],
                    "tool_choice": {
                        "type": "function",
                        "function": {"name": _RECORD_NPC_TURN_FUNCTION_NAME},
                    },
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
                error_message=f"{type(exc).__name__} calling the chat completions endpoint",
            )

        latency_ms = int((time.monotonic() - started) * 1000)
        body, parse_error = _parse_response_body(response)
        if body is None:
            return ProviderResult(
                raw_response=None,
                structured_output=None,
                finish_reason=None,
                latency_ms=latency_ms,
                error_message=parse_error,
            )
        raw_response = str(body)
        finish_reason = _finish_reason(body)
        tool_input = _extract_tool_call(body, function_name=_RECORD_NPC_TURN_FUNCTION_NAME)
        if tool_input is None:
            return ProviderResult(
                raw_response=raw_response,
                structured_output=None,
                finish_reason=finish_reason,
                latency_ms=latency_ms,
                error_message="Provider response did not include the expected function call.",
            )
        try:
            structured_output = NpcTurnOutput.model_validate(tool_input)
        except ValidationError as exc:
            return ProviderResult(
                raw_response=raw_response,
                structured_output=None,
                finish_reason=finish_reason,
                latency_ms=latency_ms,
                error_message=f"Provider function call failed schema validation: {exc.error_count()} error(s)",
            )
        return ProviderResult(
            raw_response=raw_response,
            structured_output=structured_output,
            finish_reason=finish_reason,
            latency_ms=latency_ms,
            error_message=None,
        )

    def generate_synthesis(
        self, *, context: dict[str, Any], audience_tier: str, question_text: str
    ) -> SynthesisProviderResult:
        import httpx

        started = time.monotonic()
        try:
            response = httpx.post(
                f"{self._base_url}/chat/completions",
                headers=self._headers(),
                json={
                    "model": self._model_identifier,
                    "messages": [
                        {
                            "role": "system",
                            "content": _build_synthesis_system_prompt(
                                context, audience_tier=audience_tier
                            ),
                        },
                        {"role": "user", "content": question_text},
                    ],
                    "tools": [_synthesis_answer_function_schema()],
                    "tool_choice": {
                        "type": "function",
                        "function": {"name": _RECORD_SYNTHESIS_ANSWER_FUNCTION_NAME},
                    },
                },
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            return SynthesisProviderResult(
                raw_response=None,
                structured_output=None,
                finish_reason=None,
                latency_ms=int((time.monotonic() - started) * 1000),
                error_message=f"{type(exc).__name__} calling the chat completions endpoint",
            )

        latency_ms = int((time.monotonic() - started) * 1000)
        body, parse_error = _parse_response_body(response)
        if body is None:
            return SynthesisProviderResult(
                raw_response=None,
                structured_output=None,
                finish_reason=None,
                latency_ms=latency_ms,
                error_message=parse_error,
            )
        raw_response = str(body)
        finish_reason = _finish_reason(body)
        tool_input = _extract_tool_call(body, function_name=_RECORD_SYNTHESIS_ANSWER_FUNCTION_NAME)
        if tool_input is None:
            return SynthesisProviderResult(
                raw_response=raw_response,
                structured_output=None,
                finish_reason=finish_reason,
                latency_ms=latency_ms,
                error_message="Provider response did not include the expected function call.",
            )
        try:
            structured_output = SynthesisOutput.model_validate(tool_input)
        except ValidationError as exc:
            return SynthesisProviderResult(
                raw_response=raw_response,
                structured_output=None,
                finish_reason=finish_reason,
                latency_ms=latency_ms,
                error_message=f"Provider function call failed schema validation: {exc.error_count()} error(s)",
            )
        return SynthesisProviderResult(
            raw_response=raw_response,
            structured_output=structured_output,
            finish_reason=finish_reason,
            latency_ms=latency_ms,
            error_message=None,
        )


def _synthesis_answer_function_schema() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": _RECORD_SYNTHESIS_ANSWER_FUNCTION_NAME,
            "description": "Record the audience-appropriate prose answer to this campaign question.",
            "parameters": {
                "type": "object",
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
            },
        },
    }


def _build_synthesis_system_prompt(context: dict[str, Any], *, audience_tier: str) -> str:
    recent = "; ".join(context.get("recent_event_summaries", [])) or "nothing recent"
    known = "; ".join(context.get("party_known_facts", [])) or "nothing beyond the above"
    recap = context.get("previous_session_recap") or "none recorded"
    return (
        f"You answer questions about an ongoing tabletop RPG campaign for a {audience_tier} "
        f"audience, using only the context below — never invent facts outside it. "
        f"Current session: {context.get('current_session_title') or 'none in progress'}. "
        f"Previous session recap: {recap}. Recent events: {recent}. "
        f"This audience additionally knows: {known}. "
        "Reply only through the record_synthesis_answer function."
    )


def _parse_response_body(response: "httpx.Response") -> tuple[dict[str, Any] | None, str | None]:
    """Parses an HTTP 2xx response body as a JSON object — untrusted input,
    same posture as `_extract_tool_call`'s own docstring: a provider or
    self-hosted local model server is never assumed to return well-formed
    JSON, let alone a JSON *object*, just because it returned a successful
    status code. Returns `(body, None)` on success, or `(None, message)` for
    either a body that isn't valid JSON at all or one that parses to
    something other than a JSON object (e.g. a bare array or scalar) — both
    reported as an ordinary `ProviderResult`/`SynthesisProviderResult`
    `error_message`, never an unhandled exception."""
    try:
        parsed = response.json()
    except ValueError:
        return None, "Provider response was not valid JSON."
    if not isinstance(parsed, dict):
        return None, "Provider response was not a JSON object."
    return parsed, None


def _finish_reason(body: dict[str, Any]) -> str | None:
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first = choices[0]
    if not isinstance(first, dict):
        return None
    reason = first.get("finish_reason")
    return reason if isinstance(reason, str) else None


def _extract_tool_call(body: dict[str, Any], *, function_name: str) -> dict[str, Any] | None:
    """The parsed JSON `arguments` of the first matching tool call in an
    OpenAI Chat Completions response — `choices[0].message.tool_calls`.
    Returns `None` for any shape mismatch (no choices, no tool call, wrong
    function name, unparseable arguments) rather than raising: a
    provider/model response is untrusted input, never assumed well-formed,
    the same posture `dnd_ai.api.errors` takes for every other external
    input in this codebase."""
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        return None
    tool_calls = message.get("tool_calls")
    if not isinstance(tool_calls, list):
        return None
    for call in tool_calls:
        if not isinstance(call, dict):
            continue
        function = call.get("function")
        if not isinstance(function, dict) or function.get("name") != function_name:
            continue
        arguments = function.get("arguments")
        if not isinstance(arguments, str):
            continue
        try:
            parsed = json.loads(arguments)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None
