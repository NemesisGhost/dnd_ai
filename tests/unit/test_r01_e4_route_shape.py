"""R01 E4: the four reference-corpus routes' static shape.

Ingest, grant, revoke and query (all session-only) are finalized in their request transaction: the dependency's early
check, the account requirement, the command's `_impl` on the request connection, the response built, then
`plan.finalize(connection)` as the last statement. They no longer end the request transaction or take the engine, so the
`engine_early_commit` family is empty and no production route is pending (187 finalized, 0 pending, 5 excluded).
"""

import ast
import inspect
import json
import textwrap
from typing import Any

import pytest

from dnd_ai.api import reference_corpus as api
from dnd_ai.api.app import create_app
from dnd_ai.api.r01_pending_routes import (
    R01_DEFERRED_RESERVATION_ROUTES,
    R01_EXCLUDED_WORLD_ROUTES,
    R01_FINALIZED_ROUTES,
    R01_LATE_RESERVATION_ROUTES,
    R01_PENDING_ROUTES,
)
from dnd_ai.api.r01_pre_write_routes import (
    R01_KEYED_PRE_WRITE_ROUTES,
    R01_UNKEYED_PRE_WRITE_ROUTES,
)
from dnd_ai.commands import reference_corpus as commands
from tests.r01_manifest import E4_ROUTES, MANIFEST_PATH, MIGRATED_ROUTES, _iter_api_routes

pytestmark = pytest.mark.unit

_BASE = "/campaigns/{campaign_id}/reference-corpus"
INGEST = ("POST", _BASE + "/sources/{source_document_id}/passages")
GRANT = ("POST", _BASE + "/sources/{source_document_id}/grant")
REVOKE = ("DELETE", _BASE + "/grants/{reference_source_campaign_id}")
QUERY = ("POST", _BASE + "/query")
IMPL = {
    INGEST: "_ingest_reference_passages_impl",
    GRANT: "_grant_source_to_campaign_impl",
    REVOKE: "_revoke_source_campaign_grant_impl",
    QUERY: "_retrieve_cited_passages_impl",
}
CAPABILITY = {
    INGEST: "rules_source.manage",
    GRANT: "rules_source.manage",
    REVOKE: "rules_source.manage",
    QUERY: "campaign.view",
}


def _handlers() -> dict[tuple[str, str], Any]:
    found: dict[tuple[str, str], Any] = {}
    for route in _iter_api_routes(list(create_app().routes)):
        for method in route.methods - {"HEAD", "OPTIONS"}:
            if (method, route.path) in E4_ROUTES:
                found[(method, route.path)] = route
    return found


def _function(endpoint: Any) -> ast.FunctionDef:
    tree = ast.parse(textwrap.dedent(inspect.getsource(endpoint)))
    return next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))


def _calls(node: ast.AST) -> list[tuple[int, str]]:
    found = []
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            func = n.func
            if isinstance(func, ast.Name):
                found.append((n.lineno, func.id))
            elif isinstance(func, ast.Attribute):
                found.append((n.lineno, func.attr))
    return sorted(found)


def test_the_four_routes_are_the_e4_set_finalized_and_in_no_other_registry() -> None:
    assert {INGEST, GRANT, REVOKE, QUERY} == E4_ROUTES and len(E4_ROUTES) == 4
    assert set(MIGRATED_ROUTES) >= E4_ROUTES and set(R01_FINALIZED_ROUTES) >= E4_ROUTES
    assert not E4_ROUTES & set(R01_PENDING_ROUTES)
    assert not E4_ROUTES & set(R01_KEYED_PRE_WRITE_ROUTES)
    assert not E4_ROUTES & set(R01_UNKEYED_PRE_WRITE_ROUTES)
    assert not E4_ROUTES & set(R01_DEFERRED_RESERVATION_ROUTES)
    assert not E4_ROUTES & set(R01_LATE_RESERVATION_ROUTES)


def test_the_inventory_is_187_finalized_0_pending_5_excluded() -> None:
    assert (len(R01_FINALIZED_ROUTES), len(R01_PENDING_ROUTES), len(R01_EXCLUDED_WORLD_ROUTES)) == (
        187,
        0,
        5,
    )
    assert dict(R01_PENDING_ROUTES) == {}


def test_the_manifest_classifies_them_route_capability_only_and_none_is_early_commit() -> None:
    records = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    mine = {(r["method"], r["path"]): r for r in records if (r["method"], r["path"]) in E4_ROUTES}
    assert set(mine) == E4_ROUTES
    for record in mine.values():
        assert record["family"] == "route_capability_only" and record["early_commit"] is False
    assert [r for r in records if r["family"] == "engine_early_commit"] == []


def test_the_four_routes_are_session_only_and_name_the_approved_capabilities() -> None:
    for key, route in _handlers().items():
        calls = [d.call for d in route.dependant.dependencies]
        guards = [c for c in calls if getattr(c, "allow_foundry_access", None) is not None]
        assert guards, key
        assert guards[0].allow_foundry_access is False, key  # type: ignore[attr-defined]
        assert guards[0].allow_archived_campaign is False, key  # type: ignore[attr-defined]
    assert (
        api._MANAGE_CAPABILITY == "rules_source.manage" and api._VIEW_CAPABILITY == "campaign.view"
    )
    for key, capability in CAPABILITY.items():
        source = inspect.getsource(_handlers()[key].endpoint)
        constant = (
            "_MANAGE_CAPABILITY" if capability == "rules_source.manage" else "_VIEW_CAPABILITY"
        )
        assert f"require_campaign_capability({constant})" in source, key


@pytest.mark.parametrize("key", sorted(E4_ROUTES))
def test_a_handler_runs_the_command_on_the_request_connection_and_finalizes_last(
    key: tuple[str, str],
) -> None:
    function = _function(_handlers()[key].endpoint)
    arguments = {a.arg for a in function.args.args}
    assert {"plan", "connection", "access"} <= arguments
    assert "engine" not in arguments and "request" not in arguments
    names = [n for _, n in _calls(function)]
    assert "end_request_transaction" not in names
    assert names.count("finalize") == 1
    final = next(
        s
        for s in function.body
        if isinstance(s, ast.Expr)
        and isinstance(s.value, ast.Call)
        and _name(s.value) == "finalize"
    )
    assert [
        s for s in function.body if s.lineno > final.lineno and not isinstance(s, ast.Return)
    ] == []
    calls = _calls(function)
    final_line = next(line for line, n in calls if n == "finalize")
    impl_line = next(line for line, n in calls if n == IMPL[key])
    account_line = next(line for line, n in calls if n == "active_account_requirement")
    require_line = next(line for line, n in calls if n == "require")
    assert (
        require_line <= account_line < impl_line < final_line
    )  # account registered, work, then the final check
    # the command receives the request's connection
    impl = next(c for c in ast.walk(function) if isinstance(c, ast.Call) and _name(c) == IMPL[key])
    assert isinstance(impl.args[0], ast.Name) and impl.args[0].id == "connection"
    # nothing database-touching follows the final check
    assert all(line <= final_line for line, n in calls if n in (IMPL[key], "record_change_log"))


def _name(call: ast.Call) -> str:
    func = call.func
    return (
        func.id
        if isinstance(func, ast.Name)
        else func.attr
        if isinstance(func, ast.Attribute)
        else ""
    )


def test_query_builds_its_response_before_the_final_check_and_returns_it_after() -> None:
    function = _function(_handlers()[QUERY].endpoint)
    assigned = next(
        s
        for s in function.body
        if isinstance(s, ast.Assign) and "response" in ast.unparse(s.targets[0])
    )
    final = next(
        s for s in function.body if isinstance(s, ast.Expr) and _name(s.value) == "finalize"
    )  # type: ignore[arg-type]
    returned = next(s for s in function.body if isinstance(s, ast.Return))
    assert assigned.lineno < final.lineno < returned.lineno
    assert isinstance(returned.value, ast.Name) and returned.value.id == "response"


def test_the_revoke_is_bound_to_the_route_campaign_in_the_handler_and_in_the_update() -> None:
    function = _function(_handlers()[REVOKE].endpoint)
    impl = next(
        c for c in ast.walk(function) if isinstance(c, ast.Call) and _name(c) == IMPL[REVOKE]
    )
    keywords = {k.arg: ast.unparse(k.value) for k in impl.keywords}
    assert keywords["campaign_id"] == "campaign_id"
    sql = inspect.getsource(commands._revoke_source_campaign_grant_impl)
    assert "campaign_id = :campaign" in sql and "reference_source_campaign_id = :grant" in sql


def test_the_retrieval_statement_judges_the_campaigns_ruleset_inside_itself() -> None:
    source = inspect.getsource(commands._retrieve_cited_passages_impl)
    assert "sd.ruleset_version_id = (" in source and "FROM campaign.campaigns c" in source
    for predicate in (
        "sd.status = 'active'",
        "sd.visibility = 'general'",
        "rsc.revoked_at IS NULL",
    ):
        assert predicate in source, (
            predicate
        )  # the existing active-source, visibility and active-grant predicates
    assert (
        "FOR UPDATE" not in source and "FOR SHARE" not in source
    )  # no explicit row lock (E4 adds none)


def test_the_public_command_wrappers_still_own_their_own_transaction() -> None:
    for name in (
        "grant_source_to_campaign",
        "revoke_source_campaign_grant",
        "ingest_reference_passages",
        "retrieve_cited_passages",
    ):
        assert "engine.begin()" in inspect.getsource(getattr(commands, name)), name
