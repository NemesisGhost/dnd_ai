"""R01 S5-E2: the shape of the four migrated membership routes and of their declarations (inventory safeguards;
the runtime proof is `tests/database/test_r01_s5e2_membership_routes.py`).

- The registry names the four routes and they are finalized; ownership transfer is finalized too, an **unkeyed**
  pre-write route (plan 6.27.4: `PerAbsence`, `AnyConfirmed` and the unkeyed registry made it declarable).
- Lock orders, with the one reading of the global order (one ordered `FOR UPDATE` statement per class that
  contains a target): roles, delegations, memberships, accounts, campaign, catalogue rows, targets, receipt last.
- Obligations by outcome: no `Between`; the revoke update, delegation closure and audit are conditioned on lock
  evidence; the receipt is `Exactly(1)` on a fresh keyed request.
- Each handler defers, binds, judges a replay by one `finalize`, and after the main `finalize` runs only the
  module write function and the receipt step.
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
from dnd_ai.api.r01_pre_write_routes import (
    R01_KEYED_PRE_WRITE_ROUTES,
    R01_UNKEYED_PRE_WRITE_ROUTES,
)
from dnd_ai.commands import membership_role_plans as plans
from dnd_ai.domain.authorization_steps import (
    Between,
    EachLockedRow,
    Exactly,
    LockMode,
    PerEvidence,
)
from tests.r01_manifest import _S5E2_ROUTES, _S5E2_TRANSFER_ROUTES, _iter_api_routes

pytestmark = pytest.mark.unit

CAMPAIGN = "/campaigns/{campaign_id}"
ROUTE = {
    "add": ("POST", CAMPAIGN + "/memberships"),
    "assign": ("POST", CAMPAIGN + "/memberships/{campaign_membership_id}/roles"),
    "change": ("POST", CAMPAIGN + "/memberships/roles/{membership_role_id}/change"),
    "revoke": ("POST", CAMPAIGN + "/memberships/roles/{membership_role_id}/revoke"),
}
DECLARATIONS = {
    "add": plans.ADD_DECLARATIONS,
    "assign": plans.ASSIGN_DECLARATIONS,
    "change": plans.CHANGE_DECLARATIONS,
    "revoke": plans.REVOKE_DECLARATIONS,
}
PREPARE = {
    "add": "prepare_add_member",
    "assign": "prepare_assign_role",
    "change": "prepare_change_role",
    "revoke": "prepare_revoke_role",
}
WRITE = {
    "add": "write_add_member",
    "assign": "write_assign_role",
    "change": "write_change_role",
    "revoke": "write_revoke_role",
}
TRANSFER = ("POST", CAMPAIGN + "/ownership-transfer")


def _handlers() -> dict[tuple[str, str], Callable[..., Any]]:
    found: dict[tuple[str, str], Callable[..., Any]] = {}
    for route in _iter_api_routes(list(create_app().routes)):
        assert isinstance(route, APIRoute)
        for method in route.methods:
            if (method, route.path) in _S5E2_ROUTES | {TRANSFER}:
                found[(method, route.path)] = route.endpoint
    return found


def _tree(handler: Callable[..., Any]) -> ast.FunctionDef:
    tree = ast.parse(textwrap.dedent(inspect.getsource(handler)))
    return next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))


def _name(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    return func.attr if isinstance(func, ast.Attribute) else ""


def _calls(node: ast.AST) -> list[ast.Call]:
    return [n for n in ast.walk(node) if isinstance(n, ast.Call)]


def test_the_four_routes_are_keyed_pre_write_and_transfer_is_unkeyed_pre_write() -> None:
    assert set(ROUTE.values()) == _S5E2_ROUTES and len(_S5E2_ROUTES) == 4
    assert set(R01_FINALIZED_ROUTES) >= _S5E2_ROUTES
    assert not _S5E2_ROUTES & set(R01_PENDING_ROUTES)
    for name, key in ROUTE.items():
        assert R01_KEYED_PRE_WRITE_ROUTES[key] is DECLARATIONS[name]
    # ownership transfer: finalized, an unkeyed pre-write route (T4), in the unkeyed registry only
    assert TRANSFER in _S5E2_TRANSFER_ROUTES
    assert TRANSFER in R01_FINALIZED_ROUTES and TRANSFER not in R01_PENDING_ROUTES
    assert TRANSFER not in R01_KEYED_PRE_WRITE_ROUTES
    assert R01_UNKEYED_PRE_WRITE_ROUTES[TRANSFER] is plans.TRANSFER_DECLARATION
    assert not set(R01_UNKEYED_PRE_WRITE_ROUTES) & set(R01_KEYED_PRE_WRITE_ROUTES)
    assert set(R01_UNKEYED_PRE_WRITE_ROUTES) <= set(R01_FINALIZED_ROUTES)
    names = {_name(c) for c in _calls(_tree(_handlers()[TRANSFER]))}
    assert "prepare_transfer" in names and "transfer_campaign_ownership" not in names
    end = ("POST", CAMPAIGN + "/memberships/{campaign_membership_id}/end")
    assert end in R01_PENDING_ROUTES, "end membership is S5-E3"


@pytest.mark.parametrize("route", sorted(ROUTE))
def test_the_lock_order_is_roles_memberships_accounts_campaign_catalogue_targets_receipt(
    route: str,
) -> None:
    d = DECLARATIONS[route]
    assert d.reserved is not None and d.unkeyed is not None
    expected = {
        "add": [
            plans.ACTOR_ROLES_LOCK,
            plans.ACTOR_MEMBERSHIP_LOCK,
            plans.ACTOR_ACCOUNT_LOCK,
            plans.TARGET_ACCOUNT_LOCK,
            plans.CAMPAIGN_ROW_LOCK,
            plans.ROLE_CATALOGUE_LOCK,
            plans.IDENTITY_LOCK,
        ],
        "assign": [
            plans.ACTOR_ROLES_LOCK,
            plans.ACTOR_MEMBERSHIP_LOCK,
            plans.TARGET_MEMBERSHIP_LOCK,
            plans.ACTOR_ACCOUNT_LOCK,
            plans.TARGET_ACCOUNT_LOCK,
            plans.CAMPAIGN_KEY_SHARE_LOCK,
            plans.ROLE_CATALOGUE_LOCK,
        ],
        "change": [
            plans.ROLE_ROWS_WITH_TARGET,
            plans.DELEGATION_LOCK,
            plans.ACTOR_MEMBERSHIP_LOCK,
            plans.TARGET_MEMBERSHIP_LOCK,
            plans.ACTOR_ACCOUNT_LOCK,
            plans.CAMPAIGN_ROW_LOCK,
            plans.ROLE_CATALOGUE_LOCK,
        ],
        "revoke": [
            plans.ROLE_ROWS_WITH_TARGET,
            plans.REVOKE_OUTSTANDING_LOCK,
            plans.DELEGATION_LOCK,
            plans.ACTOR_MEMBERSHIP_LOCK,
            plans.ACTOR_ACCOUNT_LOCK,
            plans.CAMPAIGN_ROW_LOCK,
        ],
    }[route]
    assert list(d.unkeyed.locks) == expected
    assert list(d.reserved.locks) == [*expected, plans.RECEIPT_LOCK]
    modes = {lock.name: lock.mode for lock in d.reserved.locks}
    # the role class that contains a target is one ordered FOR UPDATE statement over actor and target rows; the
    # membership class (C4) is the actor's open membership FOR SHARE and the target's FOR UPDATE, two statements
    if "role_rows_with_target" in modes:
        assert modes["role_rows_with_target"] is LockMode.UPDATE
    if route in ("assign", "change"):
        assert modes["actor_membership_share"] is LockMode.SHARE
        assert modes["target_membership_update"] is LockMode.UPDATE
    assert modes.get("target_account_key_share", LockMode.KEY_SHARE) is LockMode.KEY_SHARE
    campaign = "campaign_key_share" if route == "assign" else "campaign_row_update"
    assert modes[campaign] is (LockMode.KEY_SHARE if route == "assign" else LockMode.UPDATE)


@pytest.mark.parametrize("route", sorted(ROUTE))
def test_the_obligations_are_outcome_specific_and_never_optional(route: str) -> None:
    d = DECLARATIONS[route]
    assert d.reserved is not None and d.unkeyed is not None
    steps = list(d.reserved.steps)
    assert steps[-1] is plans.MEMBERSHIP_RECEIPT and steps[:-1] == list(d.unkeyed.steps)
    assert plans.MEMBERSHIP_RECEIPT.cardinality == Exactly(1)
    for step in steps:
        assert not isinstance(step.cardinality, Between), step.name
    by_name = {s.name: s for s in steps}
    if route == "revoke":
        assert by_name["revoke_role"].cardinality == EachLockedRow(complete=True)
        assert by_name["close_delegation"].cardinality == EachLockedRow(complete=True)
        audit = by_name["audit_revoked"].cardinality
        assert isinstance(audit, PerEvidence) and audit.lock is plans.REVOKE_OUTSTANDING_LOCK
    elif route == "change":
        assert by_name["revoke_old_role"].cardinality == Exactly(1)
        assert by_name["close_delegation_on_change"].cardinality == EachLockedRow(complete=True)
        assert by_name["insert_new_role"].cardinality == Exactly(1)
        assert by_name["audit_changed"].cardinality == Exactly(1)
    else:
        for step in steps[:-1]:
            assert step.cardinality == Exactly(1), step.name
    assert len(by_name) == len(steps)


def test_the_membership_and_role_triggers_are_pinned_by_name_and_source_hash() -> None:
    names = {t.name for t in plans.MEMBERSHIP_TRIGGERS | plans.MEMBERSHIP_ROLE_TRIGGERS}
    assert names == {
        "tr_campaign_memberships_enforce_actor_scope",
        "tr_campaign_memberships_enforce_immutable",
        "tr_campaign_memberships_retain_access_manager",
        "tr_campaign_memberships_set_updated_at",
        "tr_membership_roles_enforce_scope",
        "tr_membership_roles_retain_access_manager",
    }
    assert all(len(t.function.source_md5) == 32 for t in plans.DELEGATION_TRIGGERS)


@pytest.mark.parametrize("route", sorted(ROUTE))
def test_a_handler_defers_binds_judges_a_replay_and_then_runs_only_declared_steps(
    route: str,
) -> None:
    handler = _handlers()[ROUTE[route]]
    function = _tree(handler)
    assert "plan" in {a.arg for a in function.args.args}
    body_calls = [c for stmt in function.body for c in _calls(stmt)]
    names = [_name(c) for c in sorted(body_calls, key=lambda c: (c.lineno, c.col_offset))]
    assert names[0] == "_begin_lifecycle_request"
    assert names.count("finalize") == 1
    main = names.index("finalize")
    assert names.index(PREPARE[route]) < main < names.index(WRITE[route])
    allowed = {
        WRITE[route],
        "_complete_receipt_with",
        "model_dump",
        "CampaignMembershipResponse",
        "MembershipRoleResponse",
    }
    assert set(names[main + 1 :]) <= allowed, set(names[main + 1 :]) - allowed
    for call in body_calls:
        assert _name(call) not in {"execute", "begin_idempotent_request", "record_change_log"}, (
            route
        )
