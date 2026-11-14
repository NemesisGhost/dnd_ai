"""R01 S5-D: the shape of the five migrated access-management routes and of the two keyed pre-write
declarations. AST checks are inventory safeguards only (the runtime proof is in
`tests/database/test_r01_s5d_foundry_routes.py` and `test_r01_s5d_invitation_routes.py`).

- The three post-write Foundry routes take the plan after their capability dependency and finalize it as the
  last top-level statement, after every command and audit call.
- The two invitation routes are *pre-write*: the deferral precedes the reservation, `bind_reservation` follows
  it, a request without a key binds the unkeyed declaration, a replay is judged by one `finalize` before the
  receipt leaves, and after the main `finalize` only declared `plan.execute` steps (and the command's own
  write function) touch the database.
- The registry names exactly those two routes, they are finalized (not pending), and their declarations
  document the lock order: the inviting membership then the campaign for create, **the invitation then the
  campaign** for revoke (the one exception to the global order, plan section 6.25), and the reservation row
  last.
- The five world routes are untouched: still pending.
"""

import ast
import inspect
import textwrap
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.routing import APIRoute

from dnd_ai.api.app import create_app
from dnd_ai.api.r01_pending_routes import R01_FINALIZED_ROUTES, R01_PENDING_ROUTES
from dnd_ai.api.r01_pre_write_routes import R01_KEYED_PRE_WRITE_ROUTES
from dnd_ai.commands.campaign_invitation_plans import (
    CREATE_DECLARATIONS,
    REVOKE_DECLARATIONS,
)
from dnd_ai.domain.authorization_steps import Between, Exactly, LockMode
from tests.r01_manifest import _S5D_ROUTES, _iter_api_routes

pytestmark = pytest.mark.unit

CAMPAIGN = "/campaigns/{campaign_id}"
POST_WRITE = {
    ("DELETE", CAMPAIGN + "/foundry/connections/{foundry_connection_id}"),
    ("DELETE", CAMPAIGN + "/foundry/devices/{foundry_device_id}"),
    ("POST", CAMPAIGN + "/integration/external-systems/{external_system_id}/foundry-identities"),
}
PRE_WRITE = {
    ("POST", CAMPAIGN + "/invitations"),
    ("POST", CAMPAIGN + "/invitations/{campaign_invitation_id}/revoke"),
}
WORLD_ROUTES = {
    ("POST", "/worlds/{world_id}/ownership-transfer"),
    ("POST", "/worlds/{world_id}/roles"),
    ("POST", "/worlds/{world_id}/roles/{world_membership_id}/end"),
    ("POST", "/worlds/{world_id}/use-grants"),
    ("POST", "/worlds/{world_id}/use-grants/{world_use_grant_id}/revoke"),
}

#: Calls that touch the database for the request (besides `plan.*`), each of which precedes the final statement
DB_CALLS = {
    "record_change_log",
    "revoke_foundry_device",
    "revoke_foundry_connection",
    "_link_foundry_identity_impl",
    "timeline_world_id",
    "begin_idempotent_request",
    "complete_idempotent_request",
    "prepare_create_invitation",
    "prepare_revoke_invitation",
}


def _handlers() -> dict[tuple[str, str], Callable[..., Any]]:
    found: dict[tuple[str, str], Callable[..., Any]] = {}
    for route in _iter_api_routes(list(create_app().routes)):
        assert isinstance(route, APIRoute)
        for method in route.methods:
            if (method, route.path) in _S5D_ROUTES:
                found[(method, route.path)] = route.endpoint
    return found


def _tree(handler: Callable[..., Any]) -> ast.FunctionDef:
    tree = ast.parse(textwrap.dedent(inspect.getsource(handler)))
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


def test_the_five_routes_are_the_s5d_set_and_all_resolve_to_handlers() -> None:
    assert _S5D_ROUTES == POST_WRITE | PRE_WRITE and len(_S5D_ROUTES) == 5
    assert set(_handlers()) == _S5D_ROUTES
    assert set(R01_FINALIZED_ROUTES) >= _S5D_ROUTES
    assert not _S5D_ROUTES & set(R01_PENDING_ROUTES)


def test_the_world_routes_are_not_reclassified() -> None:
    """S5-D finalizes no world route and reclassifies none: they stay pending (planned exclusions)."""
    assert set(R01_PENDING_ROUTES) >= WORLD_ROUTES
    assert not WORLD_ROUTES & set(R01_FINALIZED_ROUTES)


@pytest.mark.parametrize("route", sorted(POST_WRITE))
def test_a_post_write_handler_finalizes_last_exactly_once_after_every_database_call(
    route: tuple[str, str],
) -> None:
    function = _tree(_handlers()[route])
    assert "plan" in {a.arg for a in function.args.args}
    finalizes = [c for c in _calls(function) if _name(c) == "finalize"]
    assert len(finalizes) == 1
    statement = next(
        s for s in function.body if isinstance(s, ast.Expr) and s.value is finalizes[0]
    )
    assert [
        s for s in function.body if s.lineno > statement.lineno and not isinstance(s, ast.Return)
    ] == []
    for call in _calls(function):
        if _name(call) in DB_CALLS:
            assert call.lineno < finalizes[0].lineno, _name(call)
    assert not [c for c in _calls(function) if _name(c) == "execute"], (
        "a post-write handler runs no plan step"
    )


@pytest.mark.parametrize("route", sorted(PRE_WRITE))
def test_a_pre_write_handler_orders_deferral_reservation_binding_finalize_and_declared_steps(
    route: tuple[str, str],
) -> None:
    function = _tree(_handlers()[route])
    assert "plan" in {a.arg for a in function.args.args}
    names = [(_name(c), c.lineno) for c in _calls(function)]
    first = {n: min(line for m, line in names if m == n) for n, _ in names}
    assert (
        first["defer_reservation_campaign_fk"]
        < first["begin_idempotent_request"]
        < first["bind_reservation"]
    )
    assert "bind_unkeyed" in first
    # the unkeyed binding is the else of the keyed branch, never reachable after a deferral
    key_branch = next(
        n
        for n in function.body
        if isinstance(n, ast.If) and "idempotency_key" in ast.unparse(n.test)
    )
    assert any(_name(c) == "bind_unkeyed" for s in key_branch.orelse for c in _calls(s))
    assert not any(_name(c) == "bind_unkeyed" for s in key_branch.body for c in _calls(s))
    # one finalize in the replay branch (R-D4), one at the top level
    finalizes = [c for c in _calls(function) if _name(c) == "finalize"]
    assert len(finalizes) == 2
    replay_branch = next(
        n
        for n in ast.walk(function)
        if isinstance(n, ast.If) and "IdempotentReplay" in ast.unparse(n.test)
    )
    assert [c for c in _calls(replay_branch) if _name(c) == "finalize"]
    top = next(
        s
        for s in function.body
        if isinstance(s, ast.Expr)
        and isinstance(s.value, ast.Call)
        and _name(s.value) == "finalize"
    )
    # nothing before it writes outside the plan: no audit helper, no receipt helper
    assert not [
        c
        for c in _calls(function)
        if _name(c) in {"record_change_log", "complete_idempotent_request"}
    ]
    # after it, only declared steps and the command's own write function touch the database
    after = [c for s in function.body if s.lineno > top.lineno for c in _calls(s)]
    allowed = {
        "execute",
        "write_create_invitation",
        "write_revoke_invitation",
        "receipt_params",
        "model_dump",
        "uuid",
        "UUID",
        "str",
        "CreateCampaignInvitationResponse",
        "RevokeCampaignInvitationResponse",
    }
    assert {_name(c) for c in after} <= allowed, {_name(c) for c in after} - allowed
    for call in _calls(function):
        if _name(call) in DB_CALLS:
            assert call.lineno < top.lineno, _name(call)


def test_the_registry_names_exactly_the_two_invitation_routes() -> None:
    assert set(R01_KEYED_PRE_WRITE_ROUTES) == PRE_WRITE
    assert set(R01_KEYED_PRE_WRITE_ROUTES) <= set(R01_FINALIZED_ROUTES)
    assert R01_KEYED_PRE_WRITE_ROUTES[("POST", CAMPAIGN + "/invitations")] is CREATE_DECLARATIONS
    assert (
        R01_KEYED_PRE_WRITE_ROUTES[
            ("POST", CAMPAIGN + "/invitations/{campaign_invitation_id}/revoke")
        ]
        is REVOKE_DECLARATIONS
    )


def _lock_order(declaration: Any) -> list[tuple[str, str, LockMode]]:
    return [(lock.name, lock.table.fullname, lock.mode) for lock in declaration.locks]


def test_the_declared_lock_orders_document_the_one_exception_to_the_global_order() -> None:
    assert _lock_order(CREATE_DECLARATIONS.reserved) == [
        ("actor_membership_key_share", "security.campaign_memberships", LockMode.KEY_SHARE),
        ("campaign_key_share", "campaign.campaigns", LockMode.KEY_SHARE),
        ("receipt_row", "security.idempotent_requests", LockMode.UPDATE),
    ]
    assert _lock_order(REVOKE_DECLARATIONS.reserved) == [
        ("invitation_row", "security.campaign_invitations", LockMode.UPDATE),
        ("campaign_key_share", "campaign.campaigns", LockMode.KEY_SHARE),
        ("receipt_row", "security.idempotent_requests", LockMode.UPDATE),
    ]
    # unkeyed: the same locks without the reservation row
    assert (
        _lock_order(CREATE_DECLARATIONS.unkeyed)[:2]
        == _lock_order(CREATE_DECLARATIONS.reserved)[:2]
    )
    assert len(CREATE_DECLARATIONS.unkeyed.locks) == len(REVOKE_DECLARATIONS.unkeyed.locks) == 2
    assert _lock_order(REVOKE_DECLARATIONS.unkeyed) == _lock_order(REVOKE_DECLARATIONS.reserved)[:2]


def test_the_declared_steps_and_bounds() -> None:
    def steps(declaration: Any) -> list[tuple[str, Any]]:
        return [(s.name, s.cardinality) for s in declaration.steps]

    assert steps(CREATE_DECLARATIONS.reserved) == [
        ("insert_invitation", Exactly(1)),
        ("audit_created", Exactly(1)),
        ("receipt", Exactly(1)),
    ]
    assert steps(CREATE_DECLARATIONS.unkeyed) == steps(CREATE_DECLARATIONS.reserved)[:2]
    # a revoke that finds the invitation already revoked attempts neither the update nor the audit insert,
    # but a fresh keyed request always completes its receipt
    assert steps(REVOKE_DECLARATIONS.reserved) == [
        ("revoke_invitation", Between(0, 1)),
        ("audit_revoked", Between(0, 1)),
        ("receipt", Exactly(1)),
    ]
    assert steps(REVOKE_DECLARATIONS.unkeyed) == steps(REVOKE_DECLARATIONS.reserved)[:2]
