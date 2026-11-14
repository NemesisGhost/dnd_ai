"""R01 S4b: the shape of the 21 migrated route-capability-only routes, and the Foundry route requirement.

Plan sections 7.3 and 12.5: AST checks are inventory safeguards only (the runtime proof is in
`tests/database/test_r01_s4b_routes.py`). For each of the 21 routes in `_S4B_ROUTES` they pin that:

- the handler takes the request's plan, declared after the `access` dependency that opens it;
- a handler that starts an idempotency passes the plan to it (`start_campaign_idempotency`) or, where it
  calls `begin_idempotent_request` itself, finalizes the plan inside the replay branch before the stored
  receipt leaves (R-D4);
- exactly one `plan.finalize(connection)` is a top-level statement of the handler, after every call that
  touches the database (command, audit, receipt completion), and nothing but the return follows it;
- the command takes no plan: none of the 21 commands calls a scope helper (S0 finding F-1), so S4b adds
  no lock and moves none;
- the Foundry-callable routes are exactly 1-4 and 18 of plan section 7.3, each with the scope it names.

The decision table at the end runs the Foundry part of the route requirement over constructed
snapshots: no database.
"""

import ast
import inspect
import json
import textwrap
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.routing import APIRoute

from dnd_ai.api.access import FoundryRouteFacts, route_capability_requirement
from dnd_ai.api.app import create_app
from dnd_ai.api.errors import ForbiddenError, NotFoundError
from tests.r01_manifest import _S4B_ROUTES, MANIFEST_PATH, _iter_api_routes
from tests.unit.test_r01_s2_route_shape import USER, _access, _decide, _snapshot

pytestmark = pytest.mark.unit

#: Calls that touch the database for the request, each of which must precede the final statement.
DB_CALLS = {
    "record_change_log",
    "finish_campaign_idempotency",
    "complete_idempotent_request",
    "start_campaign_idempotency",
    "begin_idempotent_request",
}

#: Plan section 7.3, routes 1-4 and 18: the routes a Foundry access token may call, and the scope each
#: names. Every other route refuses a Foundry principal.
FOUNDRY_ROUTES = {
    ("POST", "/campaigns/{campaign_id}/characters/{character_id}/conditions"): (
        "character_state_sync"
    ),
    (
        "POST",
        "/campaigns/{campaign_id}/characters/{character_id}/conditions/{condition_id}/remove",
    ): ("character_state_sync"),
    ("POST", "/campaigns/{campaign_id}/characters/{character_id}/hit-points"): (
        "character_state_sync"
    ),
    ("POST", "/campaigns/{campaign_id}/characters/{character_id}/resources"): (
        "character_state_sync"
    ),
    (
        "POST",
        "/campaigns/{campaign_id}/integration/external-systems/{external_system_id}/identifiers",
    ): "combat_sync",
}

#: Plan section 7.3's "idempotent" column: every route except 8, 18, 19, 20 and 21.
NO_IDEMPOTENCY = {
    ("POST", "/campaigns/{campaign_id}/encounters"),
    (
        "POST",
        "/campaigns/{campaign_id}/integration/external-systems/{external_system_id}/identifiers",
    ),
    ("POST", "/campaigns/{campaign_id}/reference-corpus/sources"),
    ("DELETE", "/campaigns/{campaign_id}/reference-corpus/sources/{source_document_id}"),
    ("POST", "/campaigns/{campaign_id}/foundry/pairing-codes"),
}


def _routes() -> dict[tuple[str, str], APIRoute]:
    app = create_app()
    found: dict[tuple[str, str], APIRoute] = {}
    for route in _iter_api_routes(list(app.routes)):
        assert isinstance(route, APIRoute)
        for method in route.methods:
            if (method, route.path) in _S4B_ROUTES:
                found[(method, route.path)] = route
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


def _replay_branch_calls(tree: ast.FunctionDef) -> list[ast.Call]:
    return [
        c
        for node in ast.walk(tree)
        if isinstance(node, ast.If) and "IdempotentReplay" in ast.unparse(node.test)
        for c in _calls(node)
    ]


def test_the_s4b_inventory_resolves_to_21_handlers() -> None:
    assert len(_S4B_ROUTES) == 21
    assert set(_routes()) == set(_S4B_ROUTES)


def test_the_s4b_inventory_is_the_manifests_route_capability_only_family() -> None:
    records = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    family = {(r["method"], r["path"]) for r in records if r["family"] == "route_capability_only"}
    assert family == set(_S4B_ROUTES)


@pytest.mark.parametrize("route", sorted(_S4B_ROUTES))
def test_a_migrated_handler_takes_the_plan_after_its_access_dependency(
    route: tuple[str, str],
) -> None:
    handler = _tree(_routes()[route].endpoint)
    arguments = [a.arg for a in handler.args.args]
    assert "plan" in arguments, "the handler does not take the plan"
    assert "access" in arguments
    assert arguments.index("plan") > arguments.index("access"), (
        "the plan precedes the dependency that opens it"
    )


@pytest.mark.parametrize("route", sorted(_S4B_ROUTES))
def test_a_replay_is_judged_before_the_receipt_leaves(route: tuple[str, str]) -> None:
    tree = _tree(_routes()[route].endpoint)
    calls = _calls(tree)
    starts = [c for c in calls if _name(c) == "start_campaign_idempotency"]
    begins = [c for c in calls if _name(c) == "begin_idempotent_request"]
    if route in NO_IDEMPOTENCY:
        # plan section 7.3: no idempotency key, so R-D4's replay rule does not apply
        assert not starts and not begins
        return
    assert starts or begins, "the handler no longer starts an idempotency"
    for start in starts:
        assert any(
            k.arg == "plan" and isinstance(k.value, ast.Name) and k.value.id == "plan"
            for k in start.keywords
        ), "start_campaign_idempotency does not receive the plan"
    if begins:
        replay_finals = [c for c in _replay_branch_calls(tree) if _name(c) == "finalize"]
        assert len(replay_finals) == 1, "the replay does not finalize the plan before it returns"
        # and that finalize precedes the receipt's return inside the branch
        branch = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.If) and "IdempotentReplay" in ast.unparse(n.test)
        )
        finalize_line = replay_finals[0].lineno
        returns = [n for n in ast.walk(branch) if isinstance(n, ast.Return)]
        assert returns and all(r.lineno > finalize_line for r in returns)


@pytest.mark.parametrize("route", sorted(_S4B_ROUTES))
def test_one_final_statement_follows_every_database_call(route: tuple[str, str]) -> None:
    tree = _tree(_routes()[route].endpoint)
    replay = _replay_branch_calls(tree)
    finals = [c for c in _calls(tree) if _name(c) == "finalize" and c not in replay]
    assert len(finals) == 1, "exactly one final finalize outside the replay branch"
    statement = next(s for s in tree.body if isinstance(s, ast.Expr) and s.value is finals[0])
    after = [s for s in tree.body if s.lineno > statement.lineno and not isinstance(s, ast.Return)]
    assert after == [], "a statement follows the final check"
    for returned in (s for s in tree.body if isinstance(s, ast.Return)):
        if returned.lineno > statement.lineno:
            # the return builds nothing from the database
            assert {_name(c) for c in _calls(returned)} == set()
    for call in _calls(tree):
        if call in replay or call is finals[0]:
            continue
        if _name(call) in DB_CALLS or _name(call).endswith("_impl"):
            assert call.lineno < finals[0].lineno, f"{_name(call)} follows the final check"
    # the command is called, and receives no plan: it takes no scope helper (plan section 7.3)
    impls = [c for c in _calls(tree) if _name(c).endswith("_impl")]
    assert len(impls) == 1, "the handler calls exactly one command"
    assert not any(k.arg == "plan" for k in impls[0].keywords)


def test_none_of_the_21_commands_takes_a_plan_or_a_scope_helper() -> None:
    """S4b adds no lock: the 21 commands are the S0 findings of plan section 7.3 and still call no scope
    helper and hold no actor row."""
    import importlib

    records = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    seen = 0
    for record in records:
        if (record["method"], record["path"]) not in _S4B_ROUTES:
            continue
        assert record["command_scope_markers"] == [], record["path"]
        for command in record["commands"]:
            module_path, _, function = command.rpartition(".")
            function_object = getattr(importlib.import_module(module_path), function)
            assert "plan" not in inspect.signature(function_object).parameters, command
            seen += 1
    assert seen == 21


def test_exactly_the_five_foundry_routes_accept_a_foundry_credential_with_their_scope() -> None:
    found: dict[tuple[str, str], str] = {}
    for route_key, route in _routes().items():
        for dependency in route.dependant.dependencies:
            call = dependency.call
            if call is not None and getattr(call, "allow_foundry_access", False):
                found[route_key] = str(call.foundry_scope)  # type: ignore[attr-defined]
    assert found == FOUNDRY_ROUTES


def test_a_route_that_names_no_foundry_scope_refuses_a_foundry_principal() -> None:
    for route_key, route in _routes().items():
        if route_key in FOUNDRY_ROUTES:
            continue
        capability = [
            d.call
            for d in route.dependant.dependencies
            if d.call is not None and hasattr(d.call, "allow_foundry_access")
        ]
        assert len(capability) == 1, route_key
        assert capability[0].allow_foundry_access is False  # type: ignore[attr-defined]
        assert capability[0].foundry_scope is None  # type: ignore[attr-defined]


# --- the Foundry part of the route requirement: scope and campaign binding -----------------------------------------------

ROUTE_CAMPAIGN = uuid.uuid4()
OTHER_CAMPAIGN = uuid.uuid4()


def _requirement(*, scope: str = "character_state_sync", bound: uuid.UUID | None = ROUTE_CAMPAIGN,
                 granted: frozenset[str] = frozenset({"character_state_sync"})) -> Any:  # fmt: skip
    return route_capability_requirement(
        capability_code="canon.edit",
        allow_archived_campaign=False,
        world_capability=None,
        world_id=None,
        actor_user_id=USER,
        foundry=FoundryRouteFacts(
            route_campaign_id=ROUTE_CAMPAIGN,
            bound_campaign_id=bound,
            route_scope=scope,
            granted_scopes=granted,
        ),
    )


def test_the_foundry_requirement_is_a_different_named_decision_from_the_plain_one() -> None:
    assert _requirement().name == "route.canon.edit.foundry"
    plain = route_capability_requirement(
        capability_code="canon.edit",
        allow_archived_campaign=False,
        world_capability=None,
        world_id=None,
        actor_user_id=USER,
    )
    assert plain.name == "route.canon.edit"


def test_a_foundry_credential_with_its_scope_bound_to_the_route_campaign_is_admitted() -> None:
    assert _decide(_requirement(), _snapshot(_access("canon.edit"))) is None


def test_a_foundry_credential_bound_to_another_campaign_is_refused_as_not_found() -> None:
    # the early check answers 404 for a paired credential of another campaign, indistinguishable from
    # "no such campaign"
    assert isinstance(
        _decide(_requirement(bound=OTHER_CAMPAIGN), _snapshot(_access("canon.edit"))), NotFoundError
    )
    assert isinstance(
        _decide(_requirement(bound=None), _snapshot(_access("canon.edit"))), NotFoundError
    )


def test_a_foundry_credential_without_the_routes_scope_is_refused_as_forbidden() -> None:
    refusal = _decide(
        _requirement(granted=frozenset({"combat_sync"})), _snapshot(_access("canon.edit"))
    )
    assert isinstance(refusal, ForbiddenError)
    # the same refusal an insufficient capability gives: scope and capability are indistinguishable
    assert type(refusal) is type(_decide(_requirement(), _snapshot(_access("campaign.view"))))


def test_the_foundry_checks_keep_the_dependencys_order() -> None:
    """The dependency answers no-access 404, archived 404, binding 404, scope 403, capability 403, in
    that order; the requirement refuses with the same error whichever is first to fail."""
    wrong_everything = _requirement(bound=OTHER_CAMPAIGN, granted=frozenset())
    # no access wins over everything
    assert isinstance(_decide(wrong_everything, _snapshot(None)), NotFoundError)
    # an archived campaign wins over scope and capability
    assert isinstance(
        _decide(
            _requirement(granted=frozenset()),
            _snapshot(_access("campaign.view", lifecycle="archived")),
        ),
        NotFoundError,
    )
    # the binding (404) wins over the scope (403) and the capability (403)
    assert isinstance(_decide(wrong_everything, _snapshot(_access("campaign.view"))), NotFoundError)
    # the scope (403) is judged before the capability; both are 403, so the type cannot tell them apart
    assert isinstance(
        _decide(_requirement(granted=frozenset()), _snapshot(_access("canon.edit"))), ForbiddenError
    )


def test_a_lapsed_role_is_refused_for_a_foundry_credential_that_still_holds_scope_and_binding() -> (
    None
):
    """The campaign capability is still judged from the snapshot: scope and binding are necessary, not
    sufficient."""
    assert isinstance(_decide(_requirement(), _snapshot(_access())), ForbiddenError)
