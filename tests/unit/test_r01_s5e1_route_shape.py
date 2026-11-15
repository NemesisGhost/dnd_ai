"""R01 S5-E1: the shape of the three campaign lifecycle routes and of their declarations. AST checks are
inventory safeguards only; the runtime proof is `tests/database/test_r01_s5e1_lifecycle_routes.py`.

- The registry names the three routes, they are finalized (not pending), and each declaration documents the
  lock order of plan section 6.26: [world, timeline for reactivate,] the actor's role rows, membership and
  account, then the campaign, [the changed-row lock for update,] and the reservation row last.
- Obligations by outcome: update is `EachLockedRow(complete=True)` over the changed-row lock with
  `PerEvidence` audit; archive and reactivate are `Exactly(1)` for both writes. No `Between` appears: no
  optional bound is used merely because a branch may be a no-op.
- Each handler defers the reservation FK before the reservation, binds the outcome, judges a replay by one
  `finalize` before the receipt leaves, and after the main `finalize` runs only the module's write function
  and the receipt step (no direct database call).
- Nothing else adopted the capability: the world routes are still pending.
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
from dnd_ai.commands import campaign_lifecycle_plans as plans
from dnd_ai.domain.authorization_steps import (
    Between,
    EachLockedRow,
    Exactly,
    LockMode,
    PerEvidence,
)
from tests.r01_manifest import _S5E1_ROUTES, _S5E2_ROUTES, _iter_api_routes

pytestmark = pytest.mark.unit

CAMPAIGN = "/campaigns/{campaign_id}"
ROUTE = {
    "update": ("POST", CAMPAIGN + "/update"),
    "archive": ("POST", CAMPAIGN + "/archive"),
    "reactivate": ("POST", CAMPAIGN + "/reactivate"),
}
DECLARATIONS = {
    "update": plans.UPDATE_DECLARATIONS,
    "archive": plans.ARCHIVE_DECLARATIONS,
    "reactivate": plans.REACTIVATE_DECLARATIONS,
}
ACTOR = [plans.ACTOR_ROLES_LOCK, plans.ACTOR_MEMBERSHIP_LOCK, plans.ACTOR_ACCOUNT_LOCK]
DB_CALLS = {
    "begin_idempotent_request",
    "prepare_update_campaign",
    "prepare_archive_campaign",
    "prepare_reactivate_campaign",
    "execute",
}
PREPARE = {
    "update": "prepare_update_campaign",
    "archive": "prepare_archive_campaign",
    "reactivate": "prepare_reactivate_campaign",
}
WRITE = {
    "update": "write_update_campaign",
    "archive": "write_archive_campaign",
    "reactivate": "write_reactivate_campaign",
}


def _handlers() -> dict[tuple[str, str], Callable[..., Any]]:
    found: dict[tuple[str, str], Callable[..., Any]] = {}
    for route in _iter_api_routes(list(create_app().routes)):
        assert isinstance(route, APIRoute)
        for method in route.methods:
            if (method, route.path) in _S5E1_ROUTES:
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


def test_the_three_routes_are_the_s5e1_set_finalized_and_registered_as_keyed_pre_write() -> None:
    assert set(ROUTE.values()) == _S5E1_ROUTES and len(_S5E1_ROUTES) == 3
    assert set(_handlers()) == _S5E1_ROUTES
    assert set(R01_FINALIZED_ROUTES) >= _S5E1_ROUTES
    assert not _S5E1_ROUTES & set(R01_PENDING_ROUTES)
    for name, key in ROUTE.items():
        assert R01_KEYED_PRE_WRITE_ROUTES[key] is DECLARATIONS[name]


def test_the_world_routes_and_the_other_access_management_routes_are_untouched() -> None:
    world = {
        ("POST", "/worlds/{world_id}/ownership-transfer"),
        ("POST", "/worlds/{world_id}/roles"),
        ("POST", "/worlds/{world_id}/roles/{world_membership_id}/end"),
        ("POST", "/worlds/{world_id}/use-grants"),
        ("POST", "/worlds/{world_id}/use-grants/{world_use_grant_id}/revoke"),
    }
    assert set(R01_PENDING_ROUTES) >= world
    assert set(R01_KEYED_PRE_WRITE_ROUTES) - _S5E1_ROUTES - _S5E2_ROUTES == {
        ("POST", CAMPAIGN + "/invitations"),
        ("POST", CAMPAIGN + "/invitations/{campaign_invitation_id}/revoke"),
    }


@pytest.mark.parametrize("route", sorted(ROUTE))
def test_the_lock_order_is_actor_rows_then_campaign_then_receipt(route: str) -> None:
    d = DECLARATIONS[route]
    assert d.reserved is not None and d.unkeyed is not None
    head = [plans.WORLD_SHARE_LOCK, plans.TIMELINE_SHARE_LOCK] if route == "reactivate" else []
    tail = [plans.CAMPAIGN_ROW_LOCK] + ([plans.CAMPAIGN_CHANGED_LOCK] if route == "update" else [])
    assert list(d.unkeyed.locks) == head + ACTOR + tail
    assert list(d.reserved.locks) == head + ACTOR + tail + [plans.RECEIPT_ROW_LOCK]
    modes = {lock.name: lock.mode for lock in d.reserved.locks}
    assert modes["actor_role_rows"] is LockMode.SHARE
    assert modes["actor_membership_share"] is LockMode.SHARE
    assert modes["actor_account_share"] is LockMode.SHARE
    assert modes["campaign_row_update"] is LockMode.UPDATE
    if route == "reactivate":
        assert modes["world_share"] is LockMode.SHARE and modes["timeline_share"] is LockMode.SHARE


@pytest.mark.parametrize("route", sorted(ROUTE))
def test_the_obligations_are_outcome_specific_and_never_optional(route: str) -> None:
    d = DECLARATIONS[route]
    assert d.reserved is not None and d.unkeyed is not None
    business, audit = d.reserved.steps[0], d.reserved.steps[1]
    assert d.reserved.steps[2] is plans.LIFECYCLE_RECEIPT and len(d.reserved.steps) == 3
    assert list(d.unkeyed.steps) == [business, audit]
    if route == "update":
        assert business.cardinality == EachLockedRow(complete=True)
        assert business.target_lock is plans.CAMPAIGN_CHANGED_LOCK
        assert isinstance(audit.cardinality, PerEvidence)
        assert audit.cardinality.lock is plans.CAMPAIGN_CHANGED_LOCK
    else:
        assert business.cardinality == Exactly(1) and audit.cardinality == Exactly(1)
        assert business.target_lock is plans.CAMPAIGN_ROW_LOCK
    assert plans.LIFECYCLE_RECEIPT.cardinality == Exactly(1)
    for step in d.reserved.steps:
        assert not isinstance(step.cardinality, Between), step.name
    assert business.table.name == "campaigns" and audit.table.name == "change_log"


def test_the_campaign_triggers_are_all_pinned_by_name_and_source_hash() -> None:
    names = {t.name for t in plans.CAMPAIGN_TRIGGERS}
    assert names == {
        "tr_campaigns_set_updated_at",
        "tr_campaigns_enforce_ruleset_allowed",
        "tr_campaigns_enforce_immutable",
        "tr_campaigns_retain_access_manager",
        "tr_campaigns_bump_row_version",
    }
    assert all(len(t.function.source_md5) == 32 for t in plans.CAMPAIGN_TRIGGERS)
    for step in (plans.UPDATE_SETTINGS, plans.ARCHIVE_CAMPAIGN, plans.REACTIVATE_CAMPAIGN):
        assert step.triggers == plans.CAMPAIGN_TRIGGERS


@pytest.mark.parametrize("route", sorted(ROUTE))
def test_a_handler_defers_binds_judges_a_replay_and_then_runs_only_declared_steps(
    route: str,
) -> None:
    handler = _handlers()[ROUTE[route]]
    function = _tree(handler)
    assert "plan" in {a.arg for a in function.args.args}
    # the shared reservation phase and the handler's own sequence
    shared = ast.parse(
        textwrap.dedent(inspect.getsource(handler.__globals__["_begin_lifecycle_request"]))
    )
    ordered = [_name(c) for c in sorted(_calls(shared), key=lambda c: (c.lineno, c.col_offset))]
    for first, then in (
        ("bind_unkeyed", "defer_reservation_campaign_fk"),
        ("defer_reservation_campaign_fk", "begin_idempotent_request"),
        ("begin_idempotent_request", "bind_reservation"),
        ("bind_reservation", "finalize"),
    ):
        assert then in ordered and first in ordered
    assert ordered.index("defer_reservation_campaign_fk") < ordered.index(
        "begin_idempotent_request"
    )
    assert ordered.index("begin_idempotent_request") < ordered.index("bind_reservation")
    assert ordered.index("bind_reservation") < ordered.index("finalize")
    names = [_name(c) for c in sorted(_calls(function), key=lambda c: (c.lineno, c.col_offset))]
    assert names.count("finalize") == 1, "one main finalize; the replay's is in the shared phase"
    main = names.index("finalize")
    assert names.index(PREPARE[route]) < main < names.index(WRITE[route])
    after = names[main + 1 :]
    allowed = {
        WRITE[route],
        "_lifecycle_response",
        "_complete_receipt",
        "model_dump",
    }
    assert set(after) <= allowed, set(after) - allowed
    for call in _calls(function):
        if _name(call) in {"execute", "begin_idempotent_request", "record_change_log"}:
            raise AssertionError(f"{route}: a direct database call in the handler: {_name(call)}")
