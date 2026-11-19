"""R01 E1 (design T-1): the proposal-review route's static shape.

`POST /campaigns/{campaign_id}/ai/proposed-changes/{ai_proposed_change_id}/review` is the first migrated engine
route: an **unkeyed, ordinary post-write** plan on the request-owned transaction. The handler takes the request
connection and the route's plan, calls the command, calls `plan.finalize(connection)` and only then builds the
response; the command runs on the caller's connection, locks the actor's operation scope first and opens no
transaction. The route must stay out of the deferred-reservation registry (O-2's 129): it has no reservation.
"""

import ast
import inspect
from typing import Any

import pytest

from dnd_ai.api import ai_npc
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
from dnd_ai.commands import ai_proposals
from tests.r01_manifest import E1_ROUTES, ENGINE_REQUEST_SCOPED, MANIFEST_PATH

pytestmark = pytest.mark.unit

ROUTE = ("POST", "/campaigns/{campaign_id}/ai/proposed-changes/{ai_proposed_change_id}/review")


def _function(module: Any, name: str) -> ast.FunctionDef:
    tree = ast.parse(inspect.getsource(module))
    return next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)


def _call_names(node: ast.AST) -> list[tuple[int, str]]:
    names: list[tuple[int, str]] = []
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            func = n.func
            if isinstance(func, ast.Name):
                names.append((n.lineno, func.id))
            elif isinstance(func, ast.Attribute):
                names.append((n.lineno, func.attr))
    return sorted(names)


def test_the_route_is_finalized_not_pending_and_in_no_pre_write_or_reservation_registry() -> None:
    assert {ROUTE} == E1_ROUTES
    assert ROUTE in R01_FINALIZED_ROUTES
    assert ROUTE not in R01_PENDING_ROUTES
    assert ROUTE not in R01_KEYED_PRE_WRITE_ROUTES
    assert ROUTE not in R01_UNKEYED_PRE_WRITE_ROUTES


def test_the_route_is_not_a_deferred_reservation_adopter_and_o2s_registry_is_unchanged() -> None:
    """Design 5 / D-6: calling the operation scope would classify it `operation_scope`, which is deferred."""
    assert ROUTE not in R01_DEFERRED_RESERVATION_ROUTES
    assert ROUTE not in R01_LATE_RESERVATION_ROUTES
    assert len(R01_DEFERRED_RESERVATION_ROUTES) == 129
    assert len(R01_LATE_RESERVATION_ROUTES) == 2


def test_the_committed_manifest_classifies_it_engine_request_scoped() -> None:
    import json

    records = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    mine = [r for r in records if (r["method"], r["path"]) == ROUTE]
    assert len(mine) == 1
    assert mine[0]["family"] == ENGINE_REQUEST_SCOPED == "engine_request_scoped"
    assert mine[0]["early_commit"] is False


def test_the_handler_takes_the_connection_and_plan_finalizes_last_and_never_ends_the_transaction() -> (
    None
):
    handler = _function(ai_npc, "review_proposed_change_endpoint")
    parameters = {a.arg for a in handler.args.args}
    assert {"connection", "plan"} <= parameters
    assert "engine" not in parameters and "request" not in parameters
    calls = _call_names(handler)
    names = [n for _, n in calls]
    assert "end_request_transaction" not in names
    assert names.count("finalize") == 1
    assert names.count("review_proposed_change") == 1
    review_line = next(line for line, n in calls if n == "review_proposed_change")
    finalize_line = next(line for line, n in calls if n == "finalize")
    assert review_line < finalize_line
    # the response is built after the final statement, with no further database access
    after = [n for line, n in calls if line > finalize_line]
    assert after == ["ReviewProposedChangeResponse"]


def test_the_npc_turn_handler_is_untouched_and_still_ends_its_transaction() -> None:
    names = [n for _, n in _call_names(_function(ai_npc, "request_npc_conversation_turn_endpoint"))]
    assert names.count("end_request_transaction") == 1


def test_the_command_takes_a_connection_and_a_keyword_only_plan_and_opens_no_transaction() -> None:
    command = _function(ai_proposals, "review_proposed_change")
    assert [a.arg for a in command.args.args] == ["connection"]
    assert [a.arg for a in command.args.kwonlyargs][:1] == ["plan"]
    source = ast.unparse(command)
    for forbidden in ("engine", ".begin(", ".commit(", ".rollback("):
        assert forbidden not in source, forbidden


def test_the_scope_is_locked_before_the_proposal_row() -> None:
    command = _function(ai_proposals, "review_proposed_change")
    calls = _call_names(command)
    scope = next(line for line, n in calls if n == "lock_operation_scope")
    proposal = next(line for line, n in calls if n == "_lock_pending_proposal")
    apply_ = next(line for line, n in calls if n == "_apply_proposal")
    assert scope < proposal < apply_


def test_the_advance_revalidation_locks_the_quest_and_advisory_scope_before_the_objective() -> None:
    """Design 4.3 / D-3(a): the human advance's own order (quest entity, advisory lock, then the objective)."""
    function = _function(ai_proposals, "_revalidate_advance_quest_objective")
    calls = _call_names(function)
    entity = next(line for line, n in calls if n == "require_state_targetable")
    advisory = next(line for line, n in calls if n == "lock_quest_runtime")
    objective_lock = next(
        n.lineno
        for n in ast.walk(function)
        if isinstance(n, ast.Constant)
        and isinstance(n.value, str)
        and "FOR UPDATE OF qo" in n.value
    )
    assert entity < advisory < objective_lock
