"""R01 O-2 structural pins (design N-2): the generated deferred / late-reservation sets, the two reservation paths
and the two evidence sites, the savepoint inventory, and the late-reservation order of the two revelation routes.

The 129 routes are every finalized authoring, operation and reveal route except the two revelation routes, which
reserve after their own campaign `FOR KEY SHARE` (design 1.2 R-C) and are not opted in.
"""

import ast
import json
from pathlib import Path
from typing import Any

import pytest

from dnd_ai.api import r01_pending_routes, r01_pre_write_routes

pytestmark = pytest.mark.unit

SRC = Path(__file__).resolve().parents[2] / "src" / "dnd_ai"
MANIFEST = Path(__file__).resolve().parents[1] / "r01_route_manifest.json"

DEFERRED = r01_pending_routes.R01_DEFERRED_RESERVATION_ROUTES
LATE = r01_pending_routes.R01_LATE_RESERVATION_ROUTES
_REVELATIONS = "/campaigns/{campaign_id}/characters/{character_id}/revelations"
_FAMILIES = {"authoring_scope", "operation_scope", "reveal_authority"}


def _records() -> dict[tuple[str, str], dict[str, Any]]:
    return {(r["method"], r["path"]): r for r in json.loads(MANIFEST.read_text(encoding="utf-8"))}


def _module(path: str) -> ast.Module:
    return ast.parse((SRC / path).read_text(encoding="utf-8"))


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    return next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)


def _calls(node: ast.AST) -> list[ast.Call]:
    return sorted(
        (n for n in ast.walk(node) if isinstance(n, ast.Call)),
        key=lambda c: (c.lineno, c.col_offset),
    )


def _callee(call: ast.Call) -> str:
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return call.func.id if isinstance(call.func, ast.Name) else ""


# --- the generated sets -------------------------------------------------------------------------------


def test_the_deferred_and_late_sets_are_the_reviewed_129_and_2() -> None:
    assert len(DEFERRED) == 129
    assert len(LATE) == 2
    assert {
        ("POST", _REVELATIONS),
        ("POST", _REVELATIONS + "/{character_revelation_id}/revoke"),
    } == LATE
    assert not DEFERRED & LATE


def test_the_two_sets_are_disjoint_from_every_other_registry() -> None:
    for registry in (
        set(r01_pending_routes.R01_PENDING_ROUTES),
        set(r01_pending_routes.R01_EXCLUDED_WORLD_ROUTES),
        set(r01_pre_write_routes.R01_KEYED_PRE_WRITE_ROUTES),
        set(r01_pre_write_routes.R01_UNKEYED_PRE_WRITE_ROUTES),
    ):
        assert not (DEFERRED | LATE) & registry
    assert (DEFERRED | LATE) <= r01_pending_routes.R01_FINALIZED_ROUTES


def test_the_131_reviewed_routes_are_exactly_the_three_families_and_nothing_else() -> None:
    records = _records()
    finalized_in_families = {
        key
        for key in r01_pending_routes.R01_FINALIZED_ROUTES
        if records[key]["family"] in _FAMILIES
    }
    assert finalized_in_families == DEFERRED | LATE
    assert len(finalized_in_families) == 131
    counts = dict.fromkeys(_FAMILIES, 0)
    for key in finalized_in_families:
        counts[records[key]["family"]] += 1
    assert counts == {"authoring_scope": 74, "operation_scope": 54, "reveal_authority": 3}
    # the S4b (route-capability-only) and access-management routes are never adopted (design 3.5, D-7)
    others = {
        key
        for key in r01_pending_routes.R01_FINALIZED_ROUTES
        if records[key]["family"] not in _FAMILIES
    }
    assert not others & (DEFERRED | LATE)


def test_every_deferred_route_is_keyed_optional_and_reaches_a_reviewed_evidence_site() -> None:
    """The reservation hook (R-A, R-B) and the campaign `KEY SHARE` site (E-A, E-B) every route reaches."""
    records = _records()
    for key in sorted(DEFERRED):
        record = records[key]
        assert record["idempotency"] == ["idempotency:campaign"], key
        scope = set(record["command_scope_markers"])
        if record["family"] == "reveal_authority":
            assert record["handler"].endswith("release_character_public_profile_endpoint")
            assert any(c.endswith(".release_character_public_profile") for c in record["commands"])
        else:
            assert scope & {"scope:authoring", "scope:operation"}, (key, scope)
    # the two late routes are keyed-optional too, but they are not adopters
    for key in LATE:
        assert records[key]["idempotency"] == ["idempotency:campaign"]


# --- the reservation hook -------------------------------------------------------------------------------


def test_the_one_helper_defers_before_the_reservation_and_binds_right_after() -> None:
    function = _function(_module("api/_authoring.py"), "begin_planned_idempotent_request")
    names = [_callee(c) for c in _calls(function)]
    assert names.count("defer_reservation_campaign_fk") == 1
    assert names.count("begin_idempotent_request") == 1
    assert names.count("bind_reservation") == 1
    assert (
        names.index("defer_reservation_campaign_fk")
        < names.index("begin_idempotent_request")
        < names.index("bind_reservation")
    )
    # it asks the plan, never the route table: only a `keyed_post_write` plan defers
    assert "keyed_post_write" in ast.unparse(function)


def test_both_reservation_paths_of_the_129_go_through_the_helper() -> None:
    for path, function_name in (
        ("api/_authoring.py", "start_campaign_idempotency"),
        ("api/entity_lifecycle.py", "_run"),
    ):
        function = _function(_module(path), function_name)
        names = [_callee(c) for c in _calls(function)]
        assert "begin_planned_idempotent_request" in names, path
        assert "begin_idempotent_request" not in names, path


def test_no_other_module_reserves_for_a_registered_route_outside_the_helper() -> None:
    """Only `api/idempotency.py` (the recorder), `_authoring.py`'s helper, the pre-write and unkeyed-plan routes
    and the late-reservation revelation command call `begin_idempotent_request`; the registered paths never do."""
    for path in ("api/entity_lifecycle.py",):
        assert "begin_idempotent_request(" not in (SRC / path).read_text(encoding="utf-8")


def test_the_late_reservation_routes_never_defer() -> None:
    for path in ("api/character_revelations.py", "commands/character_revelations.py"):
        source = (SRC / path).read_text(encoding="utf-8")
        assert "defer_reservation_campaign_fk" not in source, path
        assert "lock_campaign_evidence" not in source, path
        assert "begin_planned_idempotent_request" not in source, path


def test_each_late_route_reserves_only_after_its_own_campaign_lock() -> None:
    """The revelation commands call `_lock_caller_and_campaign` (the campaign `FOR KEY SHARE`) before `reserve()`,
    so their reservation's foreign-key check re-locks a held row and cannot wait (design 1.2 R-C)."""
    tree = _module("commands/character_revelations.py")
    for name in ("create_character_revelation", "revoke_character_revelation"):
        function = _function(tree, name)
        order = [_callee(c) for c in _calls(function)]
        assert "_lock_caller_and_campaign" in order, name
        assert "reserve" in order, name
        assert order.index("_lock_caller_and_campaign") < order.index("reserve"), name


# --- the evidence sites ---------------------------------------------------------------------------------


def _is_evidence_guard(statement: ast.stmt) -> bool:
    """`if <plan>.owes_campaign_evidence [and ...]: <plan>.lock_campaign_evidence(connection)`."""
    return (
        isinstance(statement, ast.If)
        and "owes_campaign_evidence" in ast.unparse(statement.test)
        and len(statement.body) == 1
        and isinstance(statement.body[0], ast.Expr)
        and isinstance(statement.body[0].value, ast.Call)
        and _callee(statement.body[0].value) == "lock_campaign_evidence"
        and not statement.orelse
    )


def _is_campaign_key_share(statement: ast.stmt) -> bool:
    return (
        isinstance(statement, ast.Assign)
        and "campaign.campaigns" in ast.unparse(statement)
        and "FOR KEY SHARE" in ast.unparse(statement)
    )


@pytest.mark.parametrize(
    ("path", "function_name"),
    [
        ("commands/_content.py", "lock_authoring_scope"),
        ("commands/character_public_profile.py", "release_character_public_profile"),
    ],
)
def test_the_evidence_statement_is_immediately_before_the_existing_campaign_statement(
    path: str, function_name: str
) -> None:
    """E-A and E-B: one evidence call, guarded by `owes_campaign_evidence`, directly before the campaign
    `FOR KEY SHARE` statement it precedes (the statement text is unchanged), and after every role, membership and
    account lock the function takes."""
    function = _function(_module(path), function_name)
    body = function.body
    at = next(i for i, s in enumerate(body) if _is_campaign_key_share(s))
    assert _is_evidence_guard(body[at - 1]), (
        "the evidence call must be immediately before the campaign lock"
    )
    calls = [_callee(c) for c in _calls(function)]
    assert calls.count("lock_campaign_evidence") == 1
    text = ast.unparse(ast.Module(body=body[:at], type_ignores=[]))
    if function_name == "lock_authoring_scope":
        for lock in (
            "FOR SHARE OF mr",  # the actor's role rows
            "campaign_memberships cm",  # the membership
            "security.users",  # the account
            "core.worlds",  # the world
        ):
            assert lock in text, lock
    else:
        for earlier in ("resolve_reveal_authority", "campaign_memberships", "core.worlds"):
            assert earlier in text, earlier


# --- the savepoint inventory ----------------------------------------------------------------------------


def test_the_only_savepoints_in_production_re_raise_a_translated_refusal() -> None:
    """AM-1.8 latches a savepoint rollback of an opted-in plan, so a success-path savepoint rollback would be
    refused at COMMIT. The only `begin_nested` blocks in the source are the two relationship ones; each is a
    `try` whose `IntegrityError` handler raises (the request is already refused, the response unchanged)."""
    sites: list[tuple[str, int, bool]] = []
    for path in sorted(SRC.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            uses = any(_callee(c) == "begin_nested" for stmt in node.body for c in _calls(stmt))
            if not uses:
                continue
            reraises = bool(node.handlers) and all(
                any(isinstance(n, ast.Raise) for n in ast.walk(handler))
                for handler in node.handlers
            )
            sites.append((path.relative_to(SRC).as_posix(), node.lineno, reraises))
    assert [(p, r) for p, _, r in sites] == [
        ("commands/world_relationships.py", True),
        ("commands/world_relationships.py", True),
    ]
    all_calls = sum(
        1
        for path in SRC.rglob("*.py")
        if "__pycache__" not in path.parts
        for c in _calls(ast.parse(path.read_text(encoding="utf-8")))
        if _callee(c) == "begin_nested"
    )
    assert all_calls == 2, "a begin_nested outside a re-raising try was added"
