"""R01 S5-E4: the shape of the five grant and relationship routes and of their declarations (inventory safeguards; the
runtime proof is `tests/database/test_r01_s5e4_access_grants.py` and `test_r01_s5e4_access_races.py`).

- The five routes are finalized, in the keyed registry only, and no handler calls a legacy command.
- Every handler defers, reserves, binds, prepares, finalizes once, and after `finalize` runs only the module write
  function and the receipt step.
- The lock order, each row once at the mode it needs: a group grantee first; the actor's role rows; the memberships;
  the accounts; the campaign (`FOR UPDATE` to write a new row, `FOR KEY SHARE` to revoke); the catalogue rows; the
  targets; the receipt last. **No lock waits less than the S5-E3 exception allows: none of these locks is `NOWAIT`**
  (the S5-E3 owner exception does not extend to other routes), and no route can answer a new retryable status.
- Obligations by outcome: the two revokes are `EachLockedRow(complete=True)` with the audit row `PerEvidence` of the
  outstanding lock; the three creating routes write `Exactly(1)`; the receipt is `Exactly(1)` on a fresh keyed request; no
  `Between`, no optional bound for another branch.
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
from dnd_ai.commands import access_grant_plans as plans
from dnd_ai.domain.authorization_steps import (
    Between,
    EachLockedRow,
    Exactly,
    LockMode,
    PerEvidence,
)
from tests.r01_manifest import _S5E4_ROUTES, _iter_api_routes

pytestmark = pytest.mark.unit

CAMPAIGN = "/campaigns/{campaign_id}"
GRANT_REL = ("POST", CAMPAIGN + "/memberships/{campaign_membership_id}/character-relationships")
CHANGE_REL = (
    "POST",
    CAMPAIGN + "/character-relationships/{membership_character_relationship_id}/change",
)
REVOKE_REL = (
    "POST",
    CAMPAIGN + "/character-relationships/{membership_character_relationship_id}/revoke",
)
CREATE_GRANT = ("POST", CAMPAIGN + "/resource-grants")
REVOKE_GRANT = ("POST", CAMPAIGN + "/resource-grants/{resource_grant_id}/revoke")
ROUTES = {
    GRANT_REL: plans.GRANT_RELATIONSHIP_DECLARATIONS,
    CHANGE_REL: plans.CHANGE_RELATIONSHIP_DECLARATIONS,
    REVOKE_REL: plans.REVOKE_RELATIONSHIP_DECLARATIONS,
    CREATE_GRANT: plans.CREATE_GRANT_DECLARATIONS,
    REVOKE_GRANT: plans.REVOKE_GRANT_DECLARATIONS,
}
PREPARE = {
    GRANT_REL: ("prepare_grant_relationship", "write_grant_relationship"),
    CHANGE_REL: ("prepare_change_relationship", "write_change_relationship"),
    REVOKE_REL: ("prepare_revoke_relationship", "write_revoke_relationship"),
    CREATE_GRANT: ("prepare_create_grant", "write_create_grant"),
    REVOKE_GRANT: ("prepare_revoke_grant", "write_revoke_grant"),
}
LEGACY = (
    "grant_character_relationship",
    "change_character_relationship",
    "revoke_character_relationship",
    "create_resource_grant",
    "revoke_resource_grant",
)


def _handler(route: tuple[str, str]) -> Callable[..., Any]:
    for api_route in _iter_api_routes(list(create_app().routes)):
        assert isinstance(api_route, APIRoute)
        if any((method, api_route.path) == route for method in api_route.methods):
            return api_route.endpoint
    raise AssertionError(f"{route} is not registered")


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


def test_the_five_routes_are_finalized_and_keyed_pre_write_only() -> None:
    assert set(ROUTES) == _S5E4_ROUTES and len(_S5E4_ROUTES) == 5
    for route, declarations in ROUTES.items():
        assert route in R01_FINALIZED_ROUTES and route not in R01_PENDING_ROUTES
        assert R01_KEYED_PRE_WRITE_ROUTES[route] is declarations
        assert route not in R01_UNKEYED_PRE_WRITE_ROUTES
        assert declarations.reserved is not None and declarations.unkeyed is not None


@pytest.mark.parametrize("route", list(ROUTES), ids=lambda r: r[1].rsplit("/", 1)[-1])
def test_a_handler_runs_prepare_then_finalize_then_only_the_module_write_and_the_receipt(
    route: tuple[str, str],
) -> None:
    function = _tree(_handler(route))
    names = [_name(call) for call in _calls(function)]
    for legacy in LEGACY:
        assert legacy not in names, "the legacy command is no longer the route"
    prepare, write = PREPARE[route]
    for required in (
        "_begin_lifecycle_request",
        prepare,
        "finalize",
        write,
        "_complete_receipt_with",
    ):
        assert required in names, required
    assert names.count("finalize") == 1
    assert (
        names.index("_begin_lifecycle_request")
        < names.index(prepare)
        < names.index("finalize")
        < names.index(write)
        < names.index("_complete_receipt_with")
    )
    finalize_line = next(c.lineno for c in _calls(function) if _name(c) == "finalize")
    after = {_name(c) for c in _calls(function) if c.lineno > finalize_line}
    assert after <= {
        write,
        "_complete_receipt_with",
        "CharacterRelationshipResponse",
        "ResourceGrantResponse",
        "_resource_grant_target_kind_and_id",
        "str",
    }, after
    for forbidden in (
        "record_change_log",
        "complete_idempotent_request",
        "begin_idempotent_request",
    ):
        assert forbidden not in names


def test_no_route_lock_waits_less_and_no_route_has_a_new_retryable_response() -> None:
    """The S5-E3 owner exception (`NOWAIT` late locks, one retryable 409) is the exception of one route; it does not
    extend here."""
    for declarations in ROUTES.values():
        for declaration in (declarations.reserved, declarations.unkeyed):
            assert declaration is not None
            for lock in declaration.locks:
                arg = lock.statement._for_update_arg
                assert arg is not None and not arg.nowait and not arg.skip_locked, lock.name
    assert plans.GrantRowRefusedError.safe_status_code == 400
    assert plans.GrantRowRefusedError.safe_error_code == "validation_failed"


def test_the_lock_order_of_each_route() -> None:
    common_actor = [plans.ACTOR_ROLES_LOCK, plans.ACTOR_MEMBERSHIP_LOCK]
    expected = {
        GRANT_REL: [
            *common_actor,
            plans.TARGET_MEMBERSHIP_LOCK,
            plans.ACTOR_ACCOUNT_LOCK,
            plans.TARGET_ACCOUNT_LOCK,
            plans.CAMPAIGN_ROW_LOCK,
            plans.RELATIONSHIP_TYPE_BY_CODE_LOCK,
            plans.TARGET_ENTITY_LOCK,
            plans.CHARACTER_ROW_LOCK,
            plans.TIMELINE_KEY_SHARE_LOCK,
            plans.WORLD_TIMES_KEY_SHARE_LOCK,
        ],
        CHANGE_REL: [
            *common_actor,
            plans.TARGET_MEMBERSHIP_LOCK,
            plans.ACTOR_ACCOUNT_LOCK,
            plans.TARGET_ACCOUNT_LOCK,
            plans.CAMPAIGN_ROW_LOCK,
            plans.RELATIONSHIP_TYPE_BY_ID_LOCK,
            plans.TARGET_ENTITY_LOCK,
            plans.CHARACTER_ROW_LOCK,
            plans.RELATIONSHIP_ROW_LOCK,
            plans.TIMELINE_KEY_SHARE_LOCK,
            plans.WORLD_TIMES_KEY_SHARE_LOCK,
        ],
        REVOKE_REL: [
            *common_actor,
            plans.ACTOR_ACCOUNT_LOCK,
            plans.CAMPAIGN_KEY_SHARE_LOCK,
            plans.RELATIONSHIP_OUTSTANDING_LOCK,
        ],
        CREATE_GRANT: [
            plans.GROUP_GRANTEE_LOCK,
            *common_actor,
            plans.TARGET_MEMBERSHIP_LOCK,
            plans.ACTOR_ACCOUNT_LOCK,
            plans.TARGET_ACCOUNT_LOCK,
            plans.CAMPAIGN_ROW_LOCK,
            plans.CAPABILITY_LOCK,
            plans.TARGET_ENTITY_LOCK,
            plans.CHARACTER_ROW_LOCK,
            plans.KNOWLEDGE_ITEM_ROW_LOCK,
            plans.QUEST_ROW_LOCK,
            plans.EVENT_ROW_LOCK,
            plans.SESSION_LOCK,
        ],
        REVOKE_GRANT: [
            *common_actor,
            plans.ACTOR_ACCOUNT_LOCK,
            plans.CAMPAIGN_KEY_SHARE_LOCK,
            plans.GRANT_OUTSTANDING_LOCK,
        ],
    }
    for route, locks in expected.items():
        d = ROUTES[route]
        assert d.reserved is not None and d.unkeyed is not None
        # the declared order is the route's real order, but ACTOR_ROLES precedes the group row only for a membership
        # grantee: the group lock is the first lock whenever it is taken
        assert list(d.unkeyed.locks) == locks, route
        assert list(d.reserved.locks) == [*locks, plans.RECEIPT_LOCK], route
        assert d.reserved.steps[-1] is plans.GRANT_RECEIPT
        assert d.unkeyed.steps == d.reserved.steps[:-1]


def test_each_lock_has_the_mode_it_needs() -> None:
    modes = {
        plans.GROUP_GRANTEE_LOCK: LockMode.UPDATE,
        plans.ACTOR_ROLES_LOCK: LockMode.SHARE,
        plans.ACTOR_MEMBERSHIP_LOCK: LockMode.SHARE,
        plans.TARGET_MEMBERSHIP_LOCK: LockMode.UPDATE,
        plans.ACTOR_ACCOUNT_LOCK: LockMode.SHARE,
        plans.TARGET_ACCOUNT_LOCK: LockMode.KEY_SHARE,
        plans.CAMPAIGN_ROW_LOCK: LockMode.UPDATE,
        plans.CAMPAIGN_KEY_SHARE_LOCK: LockMode.KEY_SHARE,
        plans.RELATIONSHIP_TYPE_BY_CODE_LOCK: LockMode.UPDATE,
        plans.RELATIONSHIP_TYPE_BY_ID_LOCK: LockMode.UPDATE,
        plans.CAPABILITY_LOCK: LockMode.UPDATE,
        plans.TARGET_ENTITY_LOCK: LockMode.UPDATE,
        plans.CHARACTER_ROW_LOCK: LockMode.KEY_SHARE,
        plans.KNOWLEDGE_ITEM_ROW_LOCK: LockMode.KEY_SHARE,
        plans.QUEST_ROW_LOCK: LockMode.KEY_SHARE,
        plans.EVENT_ROW_LOCK: LockMode.KEY_SHARE,
        plans.SESSION_LOCK: LockMode.UPDATE,
        plans.TIMELINE_KEY_SHARE_LOCK: LockMode.KEY_SHARE,
        plans.WORLD_TIMES_KEY_SHARE_LOCK: LockMode.KEY_SHARE,
        plans.RELATIONSHIP_ROW_LOCK: LockMode.UPDATE,
        plans.RELATIONSHIP_OUTSTANDING_LOCK: LockMode.UPDATE,
        plans.GRANT_OUTSTANDING_LOCK: LockMode.UPDATE,
    }
    for lock, mode in modes.items():
        assert lock.mode is mode, lock.name
    # the two writing-and-revoking campaign modes: U to write a new row, KS to revoke
    for route in (GRANT_REL, CHANGE_REL, CREATE_GRANT):
        locks = ROUTES[route].unkeyed.locks  # type: ignore[union-attr]
        assert plans.CAMPAIGN_ROW_LOCK in locks and plans.CAMPAIGN_KEY_SHARE_LOCK not in locks
    for route in (REVOKE_REL, REVOKE_GRANT):
        locks = ROUTES[route].unkeyed.locks  # type: ignore[union-attr]
        assert plans.CAMPAIGN_KEY_SHARE_LOCK in locks and plans.CAMPAIGN_ROW_LOCK not in locks


def test_the_group_row_is_declared_first_and_only_the_grant_has_one() -> None:
    assert plans.CREATE_GRANT_DECLARATIONS.unkeyed.locks[0] is plans.GROUP_GRANTEE_LOCK  # type: ignore[union-attr]
    for route, d in ROUTES.items():
        if route != CREATE_GRANT:
            assert plans.GROUP_GRANTEE_LOCK not in d.unkeyed.locks  # type: ignore[union-attr]


def test_obligations_are_declared_with_no_optional_bound() -> None:
    for declarations in ROUTES.values():
        d = declarations.reserved
        assert d is not None
        assert not [s for s in d.steps if isinstance(s.cardinality, Between)]
        assert d.steps[-1].cardinality == Exactly(1)
    by_name = {s.name: s for s in plans.REVOKE_RELATIONSHIP_DECLARATIONS.reserved.steps}  # type: ignore[union-attr]
    assert by_name["revoke_relationship"].cardinality == EachLockedRow(complete=True)
    assert by_name["revoke_relationship"].target_lock is plans.RELATIONSHIP_OUTSTANDING_LOCK
    audit = by_name["audit_relationship_revoked"].cardinality
    assert isinstance(audit, PerEvidence) and audit.lock is plans.RELATIONSHIP_OUTSTANDING_LOCK
    by_name = {s.name: s for s in plans.REVOKE_GRANT_DECLARATIONS.reserved.steps}  # type: ignore[union-attr]
    assert by_name["revoke_resource_grant"].cardinality == EachLockedRow(complete=True)
    audit = by_name["audit_grant_revoked"].cardinality
    assert isinstance(audit, PerEvidence) and audit.lock is plans.GRANT_OUTSTANDING_LOCK
    for declarations in (
        plans.GRANT_RELATIONSHIP_DECLARATIONS,
        plans.CHANGE_RELATIONSHIP_DECLARATIONS,
        plans.CREATE_GRANT_DECLARATIONS,
    ):
        for step in declarations.reserved.steps[:-1]:  # type: ignore[union-attr]
            assert step.cardinality == Exactly(1), step.name
    assert plans.CHANGE_RELATIONSHIP_REVOKE_OLD.target_lock is plans.RELATIONSHIP_ROW_LOCK


def test_every_insert_foreign_key_is_bound_to_a_held_lock_except_the_audit_lookups() -> None:
    for step in (
        plans.GRANT_RELATIONSHIP_INSERT,
        plans.CHANGE_RELATIONSHIP_INSERT,
        plans.CREATE_GRANT_INSERT,
    ):
        assert step.fks and all(binding.lock is not None for binding in step.fks), step.name
    for audit in (
        plans.GRANT_RELATIONSHIP_AUDIT,
        plans.CHANGE_RELATIONSHIP_AUDIT,
        plans.REVOKE_RELATIONSHIP_AUDIT,
        plans.CREATE_GRANT_AUDIT,
        plans.REVOKE_GRANT_AUDIT,
    ):
        assert all(binding.lock is None for binding in audit.fks)
    # the owning membership of a change is bound to the membership lock, the order the end takes
    bound = {b.constraint.columns.keys()[0]: b.lock for b in plans.CHANGE_RELATIONSHIP_INSERT.fks}
    assert bound["campaign_membership_id"] is plans.TARGET_MEMBERSHIP_LOCK
    assert bound["granted_by_membership_id"] is plans.ACTOR_MEMBERSHIP_LOCK


def test_prepare_takes_a_group_grantee_first_and_the_membership_class_before_the_campaign() -> None:
    source = inspect.getsource(plans.prepare_create_grant)
    assert source.index("GROUP_GRANTEE_LOCK") < source.index("ACTOR_ROLES_LOCK")
    assert source.index("ACTOR_ACCOUNT_LOCK") < source.index("CAMPAIGN_ROW_LOCK")
    change = inspect.getsource(plans.prepare_change_relationship)
    assert change.index("lock_memberships(") < change.index("RELATIONSHIP_ROW_LOCK")
    assert change.index("CAMPAIGN_ROW_LOCK") < change.index("RELATIONSHIP_ROW_LOCK")
