"""R01 S3: the shape of the 71 migrated definition authoring and lifecycle routes.

Plan section 12.5: AST checks are inventory safeguards only (the runtime proof is in
`tests/database/test_r01_s3_authoring_routes.py`). For each of the 71 routes in `_S3_ROUTES` they pin
that:

- the handler takes the request's plan, declared after the `access` dependency that opens it;
- the plan reaches the idempotency start (so a replay is judged, R-D4) and the command;
- exactly one `plan.finalize(connection)` is the last statement of the function that finalizes, after
  every call that touches the database (command, audit, receipt completion), and nothing but the return
  follows it.

Most routes delegate to a module-local helper (`_run`, `_write`, `_authoring_write`, `_route`); the
chain is followed through functions of the handler's module that take a `plan`. No database.
"""

import ast
import inspect
import json
import textwrap
import types
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.routing import APIRoute

from dnd_ai.api.app import create_app
from dnd_ai.domain.authorization import AuthorizationPlan
from tests.r01_manifest import _S3_ROUTES, MANIFEST_PATH, _iter_api_routes

pytestmark = pytest.mark.unit

#: Calls that touch the database for the request, each of which must precede the final statement.
DB_CALLS = {
    "record_change_log",
    "audit_content_write",
    "_audit_transition",
    "finish_campaign_idempotency",
    "complete_idempotent_request",
    "start_campaign_idempotency",
    "begin_idempotent_request",
    "command",
    "run",
}
#: Read-only helpers a migrated handler may call (they are not command or route-tail statements, but they
#: still must not follow the final statement).
READ_CALLS = {"get_quest_authoring", "get_dungeon_authoring", "get_area_authoring", "_load_view"}
#: Commands that are reads, not writes: the manifest lists them as callees.
NOT_COMMANDS = {
    "quest_has_progress",
    "capture_revision",
    "snapshot_from_view",
    "register_authoring_requirements",
    "lifecycle_world_capability_of",
}


def _routes() -> dict[tuple[str, str], Callable[..., Any]]:
    app = create_app()
    found: dict[tuple[str, str], Callable[..., Any]] = {}
    for route in _iter_api_routes(list(app.routes)):
        assert isinstance(route, APIRoute)
        for method in route.methods:
            if (method, route.path) in _S3_ROUTES:
                found[(method, route.path)] = route.endpoint
    return found


def _tree(function: Callable[..., Any]) -> ast.FunctionDef:
    tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
    return next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))


def _name(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _calls(node: ast.AST) -> list[ast.Call]:
    return [n for n in ast.walk(node) if isinstance(n, ast.Call)]


def _takes_plan(function: ast.FunctionDef) -> bool:
    return "plan" in {a.arg for a in function.args.args + function.args.kwonlyargs}


def _chain(endpoint: Callable[..., Any]) -> list[tuple[Callable[..., Any], ast.FunctionDef]]:
    """The handler, then every module-local function it calls that takes a plan, transitively."""
    module = inspect.getmodule(endpoint)
    assert module is not None
    seen: list[tuple[Callable[..., Any], ast.FunctionDef]] = []
    queue: list[Callable[..., Any]] = [endpoint]
    names: set[str] = set()
    while queue:
        function = queue.pop(0)
        tree = _tree(function)
        seen.append((function, tree))
        for call in _calls(tree):
            target = vars(module).get(_name(call))
            if (
                isinstance(target, types.FunctionType)
                and target.__module__ == module.__name__
                and target.__name__ not in names
                and _takes_plan(_tree(target))
            ):
                names.add(target.__name__)
                queue.append(target)
    return seen


def _command_names(route: tuple[str, str]) -> set[str]:
    records = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    names: set[str] = set()
    for record in records:
        if (record["method"], record["path"]) == route:
            for command in record["commands"]:
                module, _, function = command.rpartition(".")
                if module.startswith("dnd_ai.commands.") and function not in NOT_COMMANDS:
                    names.add(function)
    return names


def test_the_s3_inventory_resolves_to_71_handlers() -> None:
    assert len(_S3_ROUTES) == 71
    assert set(_routes()) == set(_S3_ROUTES)


@pytest.mark.parametrize("route", sorted(_S3_ROUTES))
def test_a_migrated_handler_takes_the_plan_after_its_access_dependency(
    route: tuple[str, str],
) -> None:
    handler = _tree(_routes()[route])
    arguments = [a.arg for a in handler.args.args]
    assert "plan" in arguments, "the handler does not take the plan"
    assert "access" in arguments
    assert arguments.index("plan") > arguments.index("access"), (
        "the plan precedes the dependency that opens it"
    )


@pytest.mark.parametrize("route", sorted(_S3_ROUTES))
def test_the_plan_reaches_the_idempotency_start_and_the_command(route: tuple[str, str]) -> None:
    chain = _chain(_routes()[route])
    calls = [call for _function, tree in chain for call in _calls(tree)]
    # every idempotency start of the chain gets the plan (a replay is judged, R-D4); the entity lifecycle's
    # own key handling is checked by the finalize test below
    for call in calls:
        if _name(call) == "start_campaign_idempotency":
            assert any(
                k.arg == "plan" and isinstance(k.value, ast.Name) and k.value.id == "plan"
                for k in call.keywords
            ), "start_campaign_idempotency does not receive the plan"
    # each command the manifest lists for the route receives it; a helper receives it by keyword too
    commands = _command_names(route)
    assert commands, "the manifest lists no command for the route"
    for name in commands:
        called = [c for c in calls if _name(c) == name]
        if not called and route[1].rsplit("/", 1)[-1] in {"archive", "restore"}:
            # the relationship lifecycle routes are built by `_lifecycle_endpoint(name, command)` and call
            # the command through its parameter (the lambda handed to `_run`)
            called = [c for c in calls if _name(c) == "command" and c.args]
        assert called, f"{name} is not called by the handler chain"
        for call in called:
            assert any(k.arg == "plan" for k in call.keywords), f"{name} does not receive the plan"


@pytest.mark.parametrize("route", sorted(_S3_ROUTES))
def test_one_final_statement_follows_every_database_call(route: tuple[str, str]) -> None:
    chain = _chain(_routes()[route])
    finalizing = [
        (function, tree)
        for function, tree in chain
        if any(_name(c) == "finalize" for c in _calls(tree))
    ]
    assert len(finalizing) == 1, "exactly one function of the chain finalizes the plan"
    _function, tree = finalizing[0]
    finals = [c for c in _calls(tree) if _name(c) == "finalize"]
    # a replay answered from a stored receipt is judged and finalized before it leaves (R-D4); that is
    # the only second finalize a function may hold, and it sits inside the replay branch
    replay_finals = [
        c
        for node in ast.walk(tree)
        if isinstance(node, ast.If) and "IdempotentReplay" in ast.unparse(node.test)
        for c in _calls(node)
        if _name(c) == "finalize"
    ]
    last = [c for c in finals if c not in replay_finals]
    assert len(last) == 1, "exactly one final finalize"
    statement = next(s for s in tree.body if isinstance(s, ast.Expr) and s.value is last[0])
    after = [s for s in tree.body if s.lineno > statement.lineno and not isinstance(s, ast.Return)]
    assert after == [], "a statement follows the final check"
    # the return that follows builds a response from values already in hand: it may construct a
    # `JSONResponse` and nothing else (a helper called in the return expression could still touch the
    # database after the final statement)
    for returned in (
        s for s in tree.body if isinstance(s, ast.Return) and s.lineno > statement.lineno
    ):
        extra = {_name(c) for c in _calls(returned)} - {"JSONResponse"}
        assert extra == set(), f"the return after the final check calls {sorted(extra)}"
    for call in _calls(tree):
        if _name(call) in DB_CALLS | READ_CALLS and call is not last[0]:
            in_replay_branch = call in [
                c
                for node in ast.walk(tree)
                if isinstance(node, ast.If) and "IdempotentReplay" in ast.unparse(node.test)
                for c in _calls(node)
            ]
            if not in_replay_branch:
                assert call.lineno < last[0].lineno, f"{_name(call)} follows the final check"
    if any(_name(c) == "begin_idempotent_request" for c in _calls(tree)):
        assert len(replay_finals) == 1, (
            "the stored receipt of a replay is not judged before it leaves"
        )


def test_every_migrated_command_requires_a_keyword_only_plan() -> None:
    """The command signatures: `plan` has no default, so a caller cannot forget it."""
    import importlib

    seen = 0
    for route in sorted(_S3_ROUTES):
        for name in _command_names(route):
            records = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
            for record in records:
                if (record["method"], record["path"]) != route:
                    continue
                for command in record["commands"]:
                    module_path, _, function = command.rpartition(".")
                    if function != name:
                        continue
                    function_object = getattr(importlib.import_module(module_path), function)
                    parameters = inspect.signature(function_object).parameters
                    if "plan" not in parameters:
                        # `create_npc` and `update_npc` forward **kwargs to the identity command
                        assert any(
                            p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters.values()
                        ), command
                        continue
                    parameter = parameters["plan"]
                    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY, command
                    assert parameter.default is inspect.Parameter.empty, command
                    assert parameter.annotation in (AuthorizationPlan, "AuthorizationPlan"), command
                    seen += 1
    assert seen >= 60, "the test lost its subject"


@pytest.mark.parametrize("route", sorted(_S3_ROUTES))
def test_the_authoring_decisions_are_registered_before_any_replay_can_finalize(
    route: tuple[str, str],
) -> None:
    """R-D4: a replay finalizes the plan before the command runs, so every decision the command
    registers must already be in the plan. In the function of the chain that opens the idempotency key,
    `require_authoring_decisions(connection, plan, access, world_capability=...)` is called first."""
    chain = _chain(_routes()[route])
    openers = [
        (function, tree)
        for function, tree in chain
        if any(
            _name(c) in ("start_campaign_idempotency", "begin_idempotent_request")
            for c in _calls(tree)
        )
    ]
    assert len(openers) == 1, "exactly one function of the chain opens the idempotency key"
    _function, tree = openers[0]
    calls = sorted(_calls(tree), key=lambda c: (c.lineno, c.col_offset))
    open_line = next(
        c.lineno
        for c in calls
        if _name(c) in ("start_campaign_idempotency", "begin_idempotent_request")
    )
    registered = [c for c in calls if _name(c) == "require_authoring_decisions"]
    assert len(registered) == 1, "the decisions are registered exactly once, in the opener"
    assert registered[0].lineno < open_line, (
        "the decisions are registered after the replay can answer"
    )
    assert any(k.arg == "world_capability" for k in registered[0].keywords)
