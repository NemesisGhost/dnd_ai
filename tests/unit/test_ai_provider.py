"""Mocked-HTTP-transport coverage for `dnd_ai.domain.ai_provider.
OpenAiCompatibleProvider` — the one real AI provider Phase 12 ships — plus
`NpcTurnOutput`'s own schema rules (the two proposal kinds and their mutual
exclusion) and `FakeAiProvider`'s matching test-double behavior. This file
is the only place that constructs `OpenAiCompatibleProvider`; every test
that does monkeypatches `httpx.post` itself, so no network call and no real
API key is required. See that module's own docstring for why one class
serves both hosted OpenAI and a locally hosted, OpenAI-API-compatible model
server.
"""

import json
import uuid
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from dnd_ai.domain.ai_provider import (
    FakeAiProvider,
    NpcTurnOutput,
    OpenAiCompatibleProvider,
    _npc_turn_function_schema,
)
from dnd_ai.domain.context_assembly import AdvanceableObjective, NpcConversationContext

pytestmark = pytest.mark.unit


def _context() -> NpcConversationContext:
    return NpcConversationContext(
        npc_entity_id=uuid.uuid4(),
        npc_name="Innkeeper Rowan",
        requesting_character_id=uuid.uuid4(),
        requesting_character_name="Alara",
        relationship_status_code="friendly",
        affinity=10,
        trust=5,
        active_encounter_id=None,
        known_facts_about_npc=(),
        revealable_knowledge=(),
        related_quests=(),
        advanceable_objectives=(),
    )


def _capture_post(
    monkeypatch: pytest.MonkeyPatch, response: httpx.Response | Exception
) -> list[dict[str, Any]]:
    """Replaces `httpx.post` with a fake that records its call kwargs and
    returns (or raises) `response`. `OpenAiCompatibleProvider` does
    `import httpx` locally inside each method, but that still binds the same
    module object `httpx` names at import time, so patching the attribute on
    the real `httpx` module intercepts it regardless of where it's called
    from."""
    calls: list[dict[str, Any]] = []

    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        calls.append({"url": url, **kwargs})
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(httpx, "post", fake_post)
    return calls


def _tool_call_response(
    *,
    function_name: str,
    arguments: dict[str, Any],
    finish_reason: str = "stop",
    status_code: int = 200,
) -> httpx.Response:
    body = {
        "choices": [
            {
                "finish_reason": finish_reason,
                "message": {
                    "tool_calls": [
                        {"function": {"name": function_name, "arguments": json.dumps(arguments)}}
                    ]
                },
            }
        ]
    }
    return httpx.Response(
        status_code, json=body, request=httpx.Request("POST", "https://example.invalid")
    )


# ---------------------------------------------------------------------------
# Request shape — endpoint, Bearer header, model, tool schema/tool_choice
# ---------------------------------------------------------------------------


def test_generate_npc_turn_posts_to_the_chat_completions_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _capture_post(
        monkeypatch,
        _tool_call_response(function_name="record_npc_turn", arguments={"dialogue": "Hi."}),
    )
    provider = OpenAiCompatibleProvider(
        api_key="sk-test", model_identifier="gpt-4o", base_url="https://api.openai.com/v1"
    )
    provider.generate_npc_turn(context=_context(), player_message="Hello")
    assert calls[0]["url"] == "https://api.openai.com/v1/chat/completions"


def test_generate_npc_turn_targets_a_local_base_url_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _capture_post(
        monkeypatch,
        _tool_call_response(function_name="record_npc_turn", arguments={"dialogue": "Hi."}),
    )
    provider = OpenAiCompatibleProvider(
        api_key=None, model_identifier="llama3", base_url="http://model-server.internal:8000/v1"
    )
    provider.generate_npc_turn(context=_context(), player_message="Hello")
    assert calls[0]["url"] == "http://model-server.internal:8000/v1/chat/completions"


def test_generate_npc_turn_sends_a_bearer_authorization_header_when_a_key_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _capture_post(
        monkeypatch,
        _tool_call_response(function_name="record_npc_turn", arguments={"dialogue": "Hi."}),
    )
    provider = OpenAiCompatibleProvider(api_key="sk-real-key", model_identifier="gpt-4o")
    provider.generate_npc_turn(context=_context(), player_message="Hello")
    assert calls[0]["headers"]["authorization"] == "Bearer sk-real-key"


def test_generate_npc_turn_omits_the_authorization_header_when_no_key_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The "local model server, no key needed" path — dnd_ai.config.Settings
    # only requires a key for the real hosted OpenAI default.
    calls = _capture_post(
        monkeypatch,
        _tool_call_response(function_name="record_npc_turn", arguments={"dialogue": "Hi."}),
    )
    provider = OpenAiCompatibleProvider(
        api_key=None, model_identifier="llama3", base_url="http://model-server.internal:8000/v1"
    )
    provider.generate_npc_turn(context=_context(), player_message="Hello")
    assert "authorization" not in calls[0]["headers"]


def test_generate_npc_turn_sends_the_configured_model_identifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _capture_post(
        monkeypatch,
        _tool_call_response(function_name="record_npc_turn", arguments={"dialogue": "Hi."}),
    )
    provider = OpenAiCompatibleProvider(api_key="sk-test", model_identifier="gpt-4o-mini")
    provider.generate_npc_turn(context=_context(), player_message="Hello")
    assert calls[0]["json"]["model"] == "gpt-4o-mini"


def test_generate_npc_turn_forces_the_record_npc_turn_function_via_tool_choice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _capture_post(
        monkeypatch,
        _tool_call_response(function_name="record_npc_turn", arguments={"dialogue": "Hi."}),
    )
    provider = OpenAiCompatibleProvider(api_key="sk-test", model_identifier="gpt-4o")
    provider.generate_npc_turn(context=_context(), player_message="Hello")
    payload = calls[0]["json"]
    assert payload["tool_choice"] == {"type": "function", "function": {"name": "record_npc_turn"}}
    (tool,) = payload["tools"]
    assert tool["function"]["name"] == "record_npc_turn"
    assert tool["function"]["parameters"]["required"] == ["dialogue"]


def test_generate_synthesis_posts_to_the_chat_completions_endpoint_with_its_own_tool_choice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _capture_post(
        monkeypatch,
        _tool_call_response(function_name="record_synthesis_answer", arguments={"answer": "ok"}),
    )
    provider = OpenAiCompatibleProvider(api_key="sk-test", model_identifier="gpt-4o")
    provider.generate_synthesis(
        context={}, audience_tier="gm_brief", question_text="What happened?"
    )
    assert calls[0]["url"] == "https://api.openai.com/v1/chat/completions"
    payload = calls[0]["json"]
    assert payload["tool_choice"] == {
        "type": "function",
        "function": {"name": "record_synthesis_answer"},
    }


# ---------------------------------------------------------------------------
# Successful tool-call parsing
# ---------------------------------------------------------------------------


def test_generate_npc_turn_parses_a_successful_tool_call(monkeypatch: pytest.MonkeyPatch) -> None:
    reveal_id = uuid.uuid4()
    _capture_post(
        monkeypatch,
        _tool_call_response(
            function_name="record_npc_turn",
            arguments={
                "dialogue": "Welcome, traveler.",
                "reveal_knowledge_item_id": str(reveal_id),
            },
            finish_reason="stop",
        ),
    )
    provider = OpenAiCompatibleProvider(api_key="sk-test", model_identifier="gpt-4o")
    result = provider.generate_npc_turn(context=_context(), player_message="Hello")
    assert result.error_message is None
    assert result.finish_reason == "stop"
    assert result.structured_output is not None
    assert result.structured_output.dialogue == "Welcome, traveler."
    assert result.structured_output.reveal_knowledge_item_id == reveal_id


def test_generate_synthesis_parses_a_successful_tool_call(monkeypatch: pytest.MonkeyPatch) -> None:
    _capture_post(
        monkeypatch,
        _tool_call_response(
            function_name="record_synthesis_answer",
            arguments={"answer": "The party defeated the ogre."},
        ),
    )
    provider = OpenAiCompatibleProvider(api_key="sk-test", model_identifier="gpt-4o")
    result = provider.generate_synthesis(
        context={}, audience_tier="gm_brief", question_text="Recap?"
    )
    assert result.error_message is None
    assert result.structured_output is not None
    assert result.structured_output.answer == "The party defeated the ogre."


# ---------------------------------------------------------------------------
# HTTP errors — never raised, always surfaced as ProviderResult.error_message
# ---------------------------------------------------------------------------


def test_generate_npc_turn_http_status_error_returns_error_message_not_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error_response = httpx.Response(
        500, json={"error": "boom"}, request=httpx.Request("POST", "https://example.invalid")
    )
    _capture_post(monkeypatch, error_response)
    provider = OpenAiCompatibleProvider(api_key="sk-test", model_identifier="gpt-4o")
    result = provider.generate_npc_turn(context=_context(), player_message="Hello")
    assert result.structured_output is None
    assert result.error_message is not None
    assert "HTTPStatusError" in result.error_message


def test_generate_npc_turn_connection_error_returns_error_message_not_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _capture_post(monkeypatch, httpx.ConnectError("connection refused"))
    provider = OpenAiCompatibleProvider(
        api_key=None, model_identifier="llama3", base_url="http://model-server.internal:8000/v1"
    )
    result = provider.generate_npc_turn(context=_context(), player_message="Hello")
    assert result.structured_output is None
    assert result.error_message is not None
    assert "ConnectError" in result.error_message


def test_generate_synthesis_http_status_error_returns_error_message_not_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error_response = httpx.Response(
        401,
        json={"error": "unauthorized"},
        request=httpx.Request("POST", "https://example.invalid"),
    )
    _capture_post(monkeypatch, error_response)
    provider = OpenAiCompatibleProvider(api_key="sk-bad", model_identifier="gpt-4o")
    result = provider.generate_synthesis(
        context={}, audience_tier="gm_brief", question_text="Recap?"
    )
    assert result.structured_output is None
    assert result.error_message is not None


# ---------------------------------------------------------------------------
# Invalid JSON and malformed response bodies — never raised
# ---------------------------------------------------------------------------


def test_generate_npc_turn_invalid_json_body_returns_error_message_not_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    malformed = httpx.Response(
        200, content=b"not valid json{{{", request=httpx.Request("POST", "https://example.invalid")
    )
    _capture_post(monkeypatch, malformed)
    provider = OpenAiCompatibleProvider(api_key="sk-test", model_identifier="gpt-4o")
    result = provider.generate_npc_turn(context=_context(), player_message="Hello")
    assert result.structured_output is None
    assert result.error_message is not None
    assert "JSON" in result.error_message


def test_generate_npc_turn_non_object_json_body_returns_error_message_not_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A syntactically valid JSON document that is nonetheless not the
    # expected object shape — e.g. a self-hosted server returning a bare
    # array on an unexpected route.
    non_object = httpx.Response(
        200, json=["unexpected", "array"], request=httpx.Request("POST", "https://example.invalid")
    )
    _capture_post(monkeypatch, non_object)
    provider = OpenAiCompatibleProvider(api_key="sk-test", model_identifier="gpt-4o")
    result = provider.generate_npc_turn(context=_context(), player_message="Hello")
    assert result.structured_output is None
    assert result.error_message is not None
    assert "JSON object" in result.error_message


def test_generate_npc_turn_missing_tool_call_returns_error_message_not_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = {"choices": [{"finish_reason": "stop", "message": {"content": "no tool call here"}}]}
    response = httpx.Response(
        200, json=body, request=httpx.Request("POST", "https://example.invalid")
    )
    _capture_post(monkeypatch, response)
    provider = OpenAiCompatibleProvider(api_key="sk-test", model_identifier="gpt-4o")
    result = provider.generate_npc_turn(context=_context(), player_message="Hello")
    assert result.structured_output is None
    assert result.finish_reason == "stop"
    assert result.error_message == "Provider response did not include the expected function call."


def test_generate_npc_turn_tool_call_with_invalid_arguments_json_returns_error_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "tool_calls": [
                        {"function": {"name": "record_npc_turn", "arguments": "{not json"}}
                    ]
                },
            }
        ]
    }
    response = httpx.Response(
        200, json=body, request=httpx.Request("POST", "https://example.invalid")
    )
    _capture_post(monkeypatch, response)
    provider = OpenAiCompatibleProvider(api_key="sk-test", model_identifier="gpt-4o")
    result = provider.generate_npc_turn(context=_context(), player_message="Hello")
    assert result.structured_output is None
    assert result.error_message == "Provider response did not include the expected function call."


def test_generate_npc_turn_tool_call_failing_schema_validation_returns_error_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Valid function call, valid JSON arguments, but missing the required
    # "dialogue" field — NpcTurnOutput.model_validate must reject it.
    _capture_post(
        monkeypatch,
        _tool_call_response(
            function_name="record_npc_turn", arguments={"reveal_knowledge_item_id": None}
        ),
    )
    provider = OpenAiCompatibleProvider(api_key="sk-test", model_identifier="gpt-4o")
    result = provider.generate_npc_turn(context=_context(), player_message="Hello")
    assert result.structured_output is None
    assert result.error_message is not None
    assert "schema validation" in result.error_message


# ---------------------------------------------------------------------------
# NpcTurnOutput's own schema — the second proposal kind
# (advance_quest_objective) and the "at most one proposal" discrimination
# rule. Pure Pydantic-model tests (no HTTP) plus a couple of end-to-end
# mocked-transport tests proving the same rules hold through
# OpenAiCompatibleProvider's own parsing path.
# ---------------------------------------------------------------------------


def test_npc_turn_output_accepts_an_advance_objective_proposal_alone() -> None:
    objective_id = uuid.uuid4()
    output = NpcTurnOutput(
        dialogue="At last!",
        advance_quest_objective_id=objective_id,
        advance_quest_objective_new_status="completed",
    )
    assert output.advance_quest_objective_id == objective_id
    assert output.reveal_knowledge_item_id is None


def test_npc_turn_output_rejects_both_proposal_kinds_at_once() -> None:
    with pytest.raises(ValidationError, match="mutually exclusive"):
        NpcTurnOutput(
            dialogue="...",
            reveal_knowledge_item_id=uuid.uuid4(),
            advance_quest_objective_id=uuid.uuid4(),
            advance_quest_objective_new_status="completed",
        )


def test_npc_turn_output_rejects_an_objective_id_without_a_status() -> None:
    with pytest.raises(ValidationError, match="must be set together"):
        NpcTurnOutput(dialogue="...", advance_quest_objective_id=uuid.uuid4())


def test_npc_turn_output_rejects_a_status_without_an_objective_id() -> None:
    with pytest.raises(ValidationError, match="must be set together"):
        NpcTurnOutput(dialogue="...", advance_quest_objective_new_status="completed")


def test_npc_turn_output_rejects_a_status_outside_the_closed_vocabulary() -> None:
    with pytest.raises(ValidationError):
        NpcTurnOutput.model_validate(
            {
                "dialogue": "...",
                "advance_quest_objective_id": str(uuid.uuid4()),
                "advance_quest_objective_new_status": "skipped",
            }
        )


def test_npc_turn_output_rejects_an_unrecognized_field() -> None:
    # extra="forbid": a provider response naming some other shape entirely
    # (a different command, an invented field) fails schema validation
    # outright rather than being silently ignored.
    with pytest.raises(ValidationError):
        NpcTurnOutput.model_validate({"dialogue": "...", "cast_a_spell": "fireball"})


def test_generate_npc_turn_rejects_a_tool_call_naming_both_proposal_kinds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _capture_post(
        monkeypatch,
        _tool_call_response(
            function_name="record_npc_turn",
            arguments={
                "dialogue": "...",
                "reveal_knowledge_item_id": str(uuid.uuid4()),
                "advance_quest_objective_id": str(uuid.uuid4()),
                "advance_quest_objective_new_status": "completed",
            },
        ),
    )
    provider = OpenAiCompatibleProvider(api_key="sk-test", model_identifier="gpt-4o")
    result = provider.generate_npc_turn(context=_context(), player_message="Hello")
    assert result.structured_output is None
    assert result.error_message is not None
    assert "schema validation" in result.error_message


def test_generate_npc_turn_rejects_a_tool_call_with_an_unrecognized_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _capture_post(
        monkeypatch,
        _tool_call_response(
            function_name="record_npc_turn",
            arguments={"dialogue": "...", "cast_a_spell": "fireball"},
        ),
    )
    provider = OpenAiCompatibleProvider(api_key="sk-test", model_identifier="gpt-4o")
    result = provider.generate_npc_turn(context=_context(), player_message="Hello")
    assert result.structured_output is None
    assert result.error_message is not None
    assert "schema validation" in result.error_message


def test_generate_npc_turn_parses_a_successful_advance_objective_proposal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    objective_id = uuid.uuid4()
    _capture_post(
        monkeypatch,
        _tool_call_response(
            function_name="record_npc_turn",
            arguments={
                "dialogue": "At last!",
                "advance_quest_objective_id": str(objective_id),
                "advance_quest_objective_new_status": "completed",
            },
        ),
    )
    provider = OpenAiCompatibleProvider(api_key="sk-test", model_identifier="gpt-4o")
    result = provider.generate_npc_turn(context=_context(), player_message="We did it!")
    assert result.error_message is None
    assert result.structured_output is not None
    assert result.structured_output.advance_quest_objective_id == objective_id
    assert result.structured_output.advance_quest_objective_new_status == "completed"
    assert result.structured_output.reveal_knowledge_item_id is None


def test_npc_turn_function_schema_advertises_the_advance_objective_fields() -> None:
    schema = _npc_turn_function_schema()
    properties = schema["function"]["parameters"]["properties"]
    assert "advance_quest_objective_id" in properties
    assert set(properties["advance_quest_objective_new_status"]["enum"]) == {
        "completed",
        "failed",
        None,
    }


# ---------------------------------------------------------------------------
# FakeAiProvider — the advance-objective candidate path, and its own
# mutual-exclusion guard mirroring NpcTurnOutput's.
# ---------------------------------------------------------------------------


def _context_with_advanceable_objective() -> NpcConversationContext:
    objective = AdvanceableObjective(
        quest_objective_id=uuid.uuid4(),
        quest_id=uuid.uuid4(),
        name="Recover the amulet",
        current_status_code=None,
    )
    return NpcConversationContext(
        npc_entity_id=uuid.uuid4(),
        npc_name="Innkeeper Rowan",
        requesting_character_id=uuid.uuid4(),
        requesting_character_name="Alara",
        relationship_status_code="friendly",
        affinity=10,
        trust=5,
        active_encounter_id=None,
        known_facts_about_npc=(),
        revealable_knowledge=(),
        related_quests=(),
        advanceable_objectives=(objective,),
    )


def test_fake_provider_proposes_the_first_advanceable_objective_when_asked() -> None:
    context = _context_with_advanceable_objective()
    provider = FakeAiProvider(advance_first_candidate=True, advance_new_status="failed")
    result = provider.generate_npc_turn(context=context, player_message="We failed...")
    assert result.structured_output is not None
    assert result.structured_output.advance_quest_objective_id == (
        context.advanceable_objectives[0].quest_objective_id
    )
    assert result.structured_output.advance_quest_objective_new_status == "failed"


def test_fake_provider_rejects_both_candidate_flags_at_once() -> None:
    with pytest.raises(ValueError, match="mutually exclusive"):
        FakeAiProvider(reveal_first_candidate=True, advance_first_candidate=True)
