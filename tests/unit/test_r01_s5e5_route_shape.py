"""R01 S5-E5: the shape of the six migrated access-group routes (AST and declaration inventory; no database).

The runtime proof is in `tests/database/test_r01_s5e5_group_routes.py` and `test_r01_s5e5_group_interactions.py`; this module pins
what a refactor must not silently change: each handler takes the plan, prepares (locks and reads) before `plan.finalize`, writes
only through the declared steps after it and completes the receipt last; every declaration follows the AO-1 lock order
(role rows, then the group row, then memberships, accounts, the campaign at `FOR KEY SHARE`: CA-1), declares no optional bound,
and uses the new cardinalities where the design says.
"""

import ast
import inspect
import textwrap
from typing import Any

import pytest
from fastapi.routing import APIRoute

from dnd_ai.api import access_groups as api
from dnd_ai.api.app import create_app
from dnd_ai.api.r01_pending_routes import R01_FINALIZED_ROUTES, R01_PENDING_ROUTES
from dnd_ai.api.r01_pre_write_routes import R01_KEYED_PRE_WRITE_ROUTES
from dnd_ai.commands import access_group_plans as plans
from dnd_ai.domain.authorization_steps import (
    Between,
    EachLockedRow,
    Exactly,
    LockMode,
    PerConfirmedRow,
    PerEvidence,
    PerEvidenceRow,
)
from tests.r01_manifest import _S5E5_ROUTES, _iter_api_routes

pytestmark = pytest.mark.unit

CAMPAIGN = "/campaigns/{campaign_id}"
ROUTE = {
    "create": ("POST", CAMPAIGN + "/access-groups"),
    "update": ("POST", CAMPAIGN + "/access-groups/{access_group_id}/update"),
    "deactivate": ("POST", CAMPAIGN + "/access-groups/{access_group_id}/deactivate"),
    "reactivate": ("POST", CAMPAIGN + "/access-groups/{access_group_id}/reactivate"),
    "add": ("POST", CAMPAIGN + "/access-groups/{access_group_id}/members"),
    "remove": ("POST", CAMPAIGN + "/access-group-memberships/{access_group_membership_id}/remove"),
}
DECLARATIONS = {
    "create": plans.CREATE_DECLARATIONS,
    "update": plans.UPDATE_DECLARATIONS,
    "deactivate": plans.DEACTIVATE_DECLARATIONS,
    "reactivate": plans.REACTIVATE_DECLARATIONS,
    "add": plans.ADD_DECLARATIONS,
    "remove": plans.REMOVE_DECLARATIONS,
}
PREPARE_WRITE = {
    "create": ("prepare_create_group", "write_create_group"),
    "update": ("prepare_update_group", "write_update_group"),
    "deactivate": ("prepare_deactivate_group", "write_deactivate_group"),
    "reactivate": ("prepare_reactivate_group", "write_reactivate_group"),
    "add": ("prepare_add_members", "write_add_members"),
    "remove": ("prepare_remove_member", "write_remove_member"),
}


def _handlers() -> dict[tuple[str, str], Any]:
    found: dict[tuple[str, str], Any] = {}
    for route in _iter_api_routes(list(create_app().routes)):
        assert isinstance(route, APIRoute)
        for method in route.methods:
            if (method, route.path) in _S5E5_ROUTES:
                assert (method, route.path) not in found, "a route is registered twice (B-4)"
                found[(method, route.path)] = route.endpoint
    return found


def _calls(node: ast.AST) -> list[ast.Call]:
    return [n for n in ast.walk(node) if isinstance(n, ast.Call)]


def _name(call: ast.Call) -> str:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return ""


def test_the_six_routes_are_the_s5e5_set_finalized_registered_once_and_no_longer_pending() -> None:
    assert set(ROUTE.values()) == _S5E5_ROUTES and len(_S5E5_ROUTES) == 6
    assert set(_handlers()) == _S5E5_ROUTES
    assert set(R01_FINALIZED_ROUTES) >= _S5E5_ROUTES
    assert not _S5E5_ROUTES & set(R01_PENDING_ROUTES)
    for name, key in ROUTE.items():
        assert R01_KEYED_PRE_WRITE_ROUTES[key] is DECLARATIONS[name]


@pytest.mark.parametrize("name", sorted(ROUTE))
def test_a_handler_prepares_finalizes_once_writes_and_completes_the_receipt_last(name: str) -> None:
    handler = _handlers()[ROUTE[name]]
    function = next(
        n
        for n in ast.walk(ast.parse(textwrap.dedent(inspect.getsource(handler))))
        if isinstance(n, ast.FunctionDef)
    )
    assert "plan" in {a.arg for a in function.args.args}
    calls = _calls(function)
    prepare, write = PREPARE_WRITE[name]
    finalize = [c for c in calls if _name(c) == "finalize"]
    assert len(finalize) == 1
    positions = {
        _name(c): c.lineno
        for c in calls
        if _name(c) in {prepare, write, "_complete_receipt_with", "_begin_lifecycle_request"}
    }
    assert (
        positions["_begin_lifecycle_request"]
        < positions[prepare]
        < finalize[0].lineno
        < positions[write]
        < positions["_complete_receipt_with"]
    ), positions
    top = [s for s in function.body if isinstance(s, ast.Expr) and s.value is finalize[0]]
    assert top, "plan.finalize is a statement of the handler's own body"
    # no direct database access and no legacy command in the handler
    forbidden = {"record_change_log", "begin_idempotent_request", "complete_idempotent_request"}
    assert not [c for c in calls if _name(c) in forbidden]
    for legacy in (
        "create_access_group",
        "update_access_group",
        "deactivate_access_group",
        "reactivate_access_group",
        "add_access_group_members",
        "remove_access_group_member",
    ):
        assert legacy not in {_name(c) for c in calls}


def test_the_handlers_module_no_longer_imports_the_legacy_commands() -> None:
    source = inspect.getsource(api)
    assert "commands.access_groups import (\n    ACCESS_GROUP_DESCRIPTION_MAX_LENGTH" in source
    assert "add_access_group_members" not in source
    assert "deactivate_access_group(" not in source.replace("deactivate_access_group_endpoint(", "")


@pytest.mark.parametrize("name", sorted(DECLARATIONS))
def test_every_declaration_follows_the_ao1_lock_order_with_the_campaign_at_key_share(
    name: str,
) -> None:
    """AO-1 / CA-1: the actor's role rows first; the group row (when the route has one) before the memberships, accounts and the
    campaign; the campaign at `FOR KEY SHARE` and **never** `FOR UPDATE`; the receipt row last in a keyed declaration."""
    d = DECLARATIONS[name]
    assert d.reserved is not None and d.unkeyed is not None
    for declaration, keyed in ((d.reserved, True), (d.unkeyed, False)):
        locks = list(declaration.locks)
        assert locks[0] is plans.ACTOR_ROLES_LOCK
        if name in {"update", "deactivate", "reactivate", "add"}:
            assert locks[1] is plans.GROUP_LOCK
            assert plans.GROUP_LOCK.mode is LockMode.UPDATE
            for later in (
                plans.ACTOR_MEMBERSHIP_LOCK,
                plans.ACTOR_ACCOUNT_LOCK,
                plans.CAMPAIGN_KEY_SHARE_LOCK,
            ):
                assert locks.index(plans.GROUP_LOCK) < locks.index(later)
        campaign = [lock for lock in locks if lock.table.name == "campaigns"]
        assert campaign == [plans.CAMPAIGN_KEY_SHARE_LOCK]
        assert plans.CAMPAIGN_KEY_SHARE_LOCK.mode is LockMode.KEY_SHARE
        assert (locks[-1].name == "receipt_row") == keyed


def test_the_member_locks_are_no_key_update_and_the_dependents_are_locked_for_update() -> None:
    assert plans.MEMBER_LOCK.mode is LockMode.NO_KEY_UPDATE
    assert plans.MEMBER_ACCOUNT_LOCK.mode is LockMode.KEY_SHARE
    for lock in (
        plans.GROUP_OPEN_LINKS,
        plans.GROUP_ACTIVE_GRANTS,
        plans.GROUP_LIVE_REVELATIONS,
        plans.LINK_OPEN_LOCK,
    ):
        assert lock.mode is LockMode.UPDATE


def test_the_dependent_locks_follow_the_campaign_in_the_deactivate_declaration() -> None:
    locks = list(plans.DEACTIVATE_DECLARATIONS.unkeyed.locks)
    for dependent in (
        plans.GROUP_OPEN_LINKS,
        plans.GROUP_ACTIVE_GRANTS,
        plans.GROUP_LIVE_REVELATIONS,
    ):
        assert locks.index(plans.CAMPAIGN_KEY_SHARE_LOCK) < locks.index(dependent)
    assert locks.index(plans.GROUP_ACTIVE_LOCK) == locks.index(plans.GROUP_LOCK) + 1


def test_no_declaration_has_an_optional_bound_and_the_new_cardinalities_are_where_the_design_puts_them() -> (
    None
):
    for declarations in DECLARATIONS.values():
        for declaration in (declarations.reserved, declarations.unkeyed):
            assert declaration is not None
            for step in declaration.steps:
                assert not isinstance(step.cardinality, Between), step.name
    assert isinstance(plans.INSERT_LINK.cardinality, PerEvidenceRow)
    assert plans.INSERT_LINK.cardinality.lock is plans.MEMBER_LOCK
    assert set(plans.INSERT_LINK.cardinality.via.constraint.columns.keys()) == {
        "campaign_membership_id"
    }
    assert isinstance(plans.LINK_AUDIT.cardinality, PerConfirmedRow)
    assert plans.LINK_AUDIT.cardinality.step is plans.INSERT_LINK
    assert plans.LINK_AUDIT.cardinality.bind == "record"
    for step, lock in (
        (plans.ARCHIVE_GROUP, plans.GROUP_ACTIVE_LOCK),
        (plans.CLOSE_GROUP_LINKS, plans.GROUP_OPEN_LINKS),
        (plans.REVOKE_GROUP_GRANTS, plans.GROUP_ACTIVE_GRANTS),
        (plans.CLOSE_GROUP_REVELATIONS, plans.GROUP_LIVE_REVELATIONS),
        (plans.REACTIVATE_GROUP, plans.GROUP_ARCHIVED_LOCK),
        (plans.REMOVE_LINK, plans.LINK_OPEN_LOCK),
    ):
        assert step.cardinality == EachLockedRow(complete=True)
        assert step.target_lock is lock
    for step, lock in (
        (plans.DEACTIVATE_AUDIT, plans.GROUP_ACTIVE_LOCK),
        (plans.REACTIVATE_AUDIT, plans.GROUP_ARCHIVED_LOCK),
        (plans.REMOVE_AUDIT, plans.LINK_OPEN_LOCK),
    ):
        assert isinstance(step.cardinality, PerEvidence) and step.cardinality.lock is lock
    for step in (plans.INSERT_GROUP, plans.CREATE_AUDIT, plans.UPDATE_GROUP, plans.UPDATE_AUDIT):
        assert step.cardinality == Exactly(1)


def test_the_timestamps_are_the_approved_expressions() -> None:
    """I-3 and B-5: the grant close is clamped at `granted_at` and the revelation close at `created_at` (the legacy clamp);
    the two link closes and no other write use `now()`."""
    from sqlalchemy.dialects import postgresql

    def compiled(step: Any) -> str:
        return " ".join(str(step.statement.compile(dialect=postgresql.dialect())).split())

    assert (
        "revoked_at=greatest(pg_catalog.clock_timestamp(), security.resource_grants.granted_at)"
        in compiled(plans.REVOKE_GROUP_GRANTS)
    )
    assert (
        "ended_at=greatest(pg_catalog.clock_timestamp(), security.character_revelations.created_at)"
        in compiled(plans.CLOSE_GROUP_REVELATIONS)
    )
    assert "removed_at=pg_catalog.now()" in compiled(plans.CLOSE_GROUP_LINKS)
    assert "removed_at=pg_catalog.now()" in compiled(plans.REMOVE_LINK)


def test_h1_runs_after_the_three_dependent_locks_and_before_the_function_returns() -> None:
    source = inspect.getsource(plans.prepare_deactivate_group)
    last_lock = max(
        source.index(token)
        for token in ("GROUP_OPEN_LINKS", "GROUP_ACTIVE_GRANTS", "GROUP_LIVE_REVELATIONS")
    )
    assert last_lock < source.index("_check_cascade_complete(")
    # it runs on the active branch only
    assert "if will_archive:" in source[source.index("_check_cascade_complete(") - 80 :]


def test_the_group_lock_helper_takes_the_role_rows_first_and_every_group_locking_prepare_uses_it() -> (
    None
):
    helper = inspect.getsource(plans._lock_group)
    assert helper.index("ACTOR_ROLES_LOCK") < helper.index("GROUP_LOCK")
    for name in (
        "prepare_update_group",
        "prepare_deactivate_group",
        "prepare_reactivate_group",
        "prepare_add_members",
    ):
        source = inspect.getsource(getattr(plans, name))
        assert source.index("_lock_group(") < min(
            source.index(token)
            for token in (
                "ACTOR_MEMBERSHIP_LOCK",
                "_lock_actor_after_group(",
                "MEMBER_LOCK",
                "CAMPAIGN_KEY_SHARE_LOCK",
            )
            if token in source
        ), name
