"""R01 E2 (design T-1): the two AI provider routes' static shape.

`POST /campaigns/{campaign_id}/ai/npc-conversation` and `.../ai/synthesis` are finalized with family
`engine_two_phase`. The handler finalizes the request plan (the early check), then ends the request transaction,
then calls the command. The command runs two `authorized_transaction` blocks, T1 and T2, with the provider call
between them, and nothing else (no connection, no transaction) is held across the call. The routes are in no
deferred-reservation registry: they have no reservation.
"""

import ast
import inspect
import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from dnd_ai.api import ai_npc, ai_synthesis
from dnd_ai.api.r01_pending_routes import (
    R01_DEFERRED_RESERVATION_ROUTES,
    R01_FINALIZED_ROUTES,
    R01_LATE_RESERVATION_ROUTES,
    R01_PENDING_ROUTES,
)
from dnd_ai.api.r01_pre_write_routes import (
    R01_KEYED_PRE_WRITE_ROUTES,
    R01_UNKEYED_PRE_WRITE_ROUTES,
)
from dnd_ai.commands import ai_npc as npc_command
from dnd_ai.commands import ai_synthesis as synthesis_command
from dnd_ai.commands.ai_perspective import register_requirements
from tests.r01_manifest import E2_ROUTES, ENGINE_TWO_PHASE, MANIFEST_PATH

pytestmark = pytest.mark.unit

NPC = ("POST", "/campaigns/{campaign_id}/ai/npc-conversation")
SYNTHESIS = ("POST", "/campaigns/{campaign_id}/ai/synthesis")

HANDLERS = [
    (NPC, ai_npc, "request_npc_conversation_turn_endpoint", "request_npc_conversation_turn"),
    (SYNTHESIS, ai_synthesis, "request_campaign_synthesis_endpoint", "request_campaign_synthesis"),
]
COMMANDS = [
    (npc_command, "request_npc_conversation_turn", "generate_npc_turn"),
    (synthesis_command, "request_campaign_synthesis", "generate_synthesis"),
]


def _function(module: Any, name: str) -> ast.FunctionDef:
    tree = ast.parse(inspect.getsource(module))
    return next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)


def _call_lines(node: ast.AST) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            func = n.func
            if isinstance(func, ast.Name):
                found.append((n.lineno, func.id))
            elif isinstance(func, ast.Attribute):
                found.append((n.lineno, func.attr))
    return sorted(found)


def test_the_routes_are_finalized_two_phase_and_in_no_other_registry() -> None:
    assert {NPC, SYNTHESIS} == E2_ROUTES
    for route in E2_ROUTES:
        assert route in R01_FINALIZED_ROUTES
        assert route not in R01_PENDING_ROUTES
        assert route not in R01_KEYED_PRE_WRITE_ROUTES
        assert route not in R01_UNKEYED_PRE_WRITE_ROUTES
        assert route not in R01_DEFERRED_RESERVATION_ROUTES
        assert route not in R01_LATE_RESERVATION_ROUTES


def test_o2s_registries_and_the_inventory_are_as_designed() -> None:
    assert len(R01_DEFERRED_RESERVATION_ROUTES) == 129
    assert len(R01_LATE_RESERVATION_ROUTES) == 2
    assert (
        len(R01_FINALIZED_ROUTES) == 187 and len(R01_PENDING_ROUTES) == 0
    )  # 183 / 4 before R01 E4, 182 / 5 before R01 E3


def test_the_committed_manifest_classifies_both_engine_two_phase() -> None:
    records = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    for route in E2_ROUTES:
        mine = [r for r in records if (r["method"], r["path"]) == route]
        assert len(mine) == 1
        assert mine[0]["family"] == ENGINE_TWO_PHASE == "engine_two_phase"


@pytest.mark.parametrize(("route", "module", "handler", "command"), HANDLERS)
def test_each_handler_finalizes_the_request_plan_then_ends_the_transaction_then_calls_the_command(
    route: tuple[str, str], module: Any, handler: str, command: str
) -> None:
    function = _function(module, handler)
    parameters = {a.arg for a in function.args.args}
    assert {"connection", "plan", "engine"} <= parameters
    calls = _call_lines(function)
    names = [n for _, n in calls]
    assert names.count("finalize") == 1
    assert names.count("end_request_transaction") == 1
    assert names.count(command) == 1
    finalize = next(line for line, n in calls if n == "finalize")
    end = next(line for line, n in calls if n == "end_request_transaction")
    call = next(line for line, n in calls if n == command)
    assert finalize < end < call
    # no request-connection use after the transaction ended
    uses = [
        n.lineno
        for n in ast.walk(function)
        if isinstance(n, ast.Name) and n.id == "connection" and isinstance(n.ctx, ast.Load)
    ]
    assert max(uses) < end


@pytest.mark.parametrize(("module", "command", "provider_call"), COMMANDS)
def test_each_command_opens_exactly_two_authorized_transactions_with_the_provider_between(
    module: Any, command: str, provider_call: str
) -> None:
    function = _function(module, command)
    withs = [
        n
        for n in ast.walk(function)
        if isinstance(n, ast.With)
        and any(
            isinstance(item.context_expr, ast.Call)
            and isinstance(item.context_expr.func, ast.Name)
            and item.context_expr.func.id == "authorized_transaction"
            for item in n.items
        )
    ]
    assert len(withs) == 2
    first, second = sorted(withs, key=lambda w: w.lineno)
    provider = [line for line, n in _call_lines(function) if n == provider_call]
    assert len(provider) == 1
    assert first.end_lineno is not None
    assert first.end_lineno < provider[0] < second.lineno
    # nothing opens a transaction of its own, and `engine.begin` / `engine.connect` are never used
    source = ast.unparse(function)
    for forbidden in ("engine.begin", "engine.connect", ".commit("):
        assert forbidden not in source, forbidden


@pytest.mark.parametrize(("module", "command", "provider_call"), COMMANDS)
def test_each_transaction_registers_its_requirements_first_and_finalizes_last(
    module: Any, command: str, provider_call: str
) -> None:
    function = _function(module, command)
    withs = sorted(
        (n for n in ast.walk(function) if isinstance(n, ast.With)), key=lambda w: w.lineno
    )
    assert len(withs) == 2
    for block in withs:
        names = [n for _, n in _call_lines(block)]
        assert names[0] == "authorized_transaction"
        assert names[1] == "register_requirements"


def test_an_empty_requirement_factory_is_refused_before_any_statement() -> None:
    connection, plan = MagicMock(), MagicMock()
    with pytest.raises(ValueError):
        register_requirements(connection, plan, lambda: [])
    connection.execute.assert_not_called()
    plan.require.assert_not_called()


def test_the_factories_return_fresh_requirement_objects_on_every_call() -> None:
    import uuid

    user, character = uuid.uuid4(), uuid.uuid4()
    npc = ai_npc.npc_turn_requirements(actor_user_id=user, character_id=character)
    first, second = npc(), npc()
    assert len(first) == len(second) == 2
    assert all(a is not b for a, b in zip(first, second, strict=True))
    synthesis = ai_synthesis.synthesis_requirements(actor_user_id=user, audience_tier="gm_brief")
    assert len(synthesis()) == 2
    assert all(a is not b for a, b in zip(synthesis(), synthesis(), strict=True))
    observer = ai_synthesis.synthesis_requirements(
        actor_user_id=user, audience_tier="observer_summary"
    )
    assert [r.name for r in observer()] == ["route.campaign.view"]
