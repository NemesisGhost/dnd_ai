"""R01 S5-E3: the shape of the end-membership route and of its declaration (inventory safeguards; the runtime proof is
`tests/database/test_r01_s5e3_end_membership.py` and `test_r01_s5e3_end_races.py`).

- The route is finalized, in the keyed registry only, and its handler never calls the legacy command.
- The lock order, with each row once at the mode it needs: role class, delegation class, memberships, open evidence,
  accounts, campaign, the five dependent classes, receipt last. The late (`NOWAIT`) locks are the only locks that
  may reverse the class order, and they can never wait.
- Obligations by outcome: every closure is `EachLockedRow(complete=True)`, the audit row is `PerEvidence` of the
  open-membership lock, the receipt is `Exactly(1)` on a fresh keyed request; no `Between`, no optional bound for the
  already-ended branch.
- The handler defers, binds, judges a replay by one `finalize`, and after the main `finalize` runs only the module
  write function and the receipt step.
"""

import ast
import inspect
import textwrap
import uuid
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
from dnd_ai.commands import membership_end_plans as plans
from dnd_ai.commands.memberships import MembershipEndedStateChangedError
from dnd_ai.domain.authorization_steps import (
    Between,
    EachLockedRow,
    Exactly,
    LockMode,
    PerEvidence,
)
from tests.r01_manifest import _S5E3_ROUTES, _iter_api_routes

pytestmark = pytest.mark.unit

END = ("POST", "/campaigns/{campaign_id}/memberships/{campaign_membership_id}/end")


def _handler() -> Callable[..., Any]:
    for route in _iter_api_routes(list(create_app().routes)):
        assert isinstance(route, APIRoute)
        if any((method, route.path) == END for method in route.methods):
            return route.endpoint
    raise AssertionError("the end route is not registered")


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


def test_the_end_route_is_finalized_and_keyed_pre_write_only() -> None:
    assert {END} == _S5E3_ROUTES
    assert END in R01_FINALIZED_ROUTES and END not in R01_PENDING_ROUTES
    assert R01_KEYED_PRE_WRITE_ROUTES[END] is plans.END_DECLARATIONS
    assert END not in R01_UNKEYED_PRE_WRITE_ROUTES
    assert (
        plans.END_DECLARATIONS.reserved is not None and plans.END_DECLARATIONS.unkeyed is not None
    )


def test_the_handler_runs_prepare_then_finalize_then_only_the_module_write_and_the_receipt() -> (
    None
):
    function = _tree(_handler())
    names = [_name(call) for call in _calls(function)]
    assert "end_campaign_membership" not in names, "the legacy command is no longer the route"
    for required in (
        "_begin_lifecycle_request",
        "prepare_end_membership",
        "finalize",
        "write_end_membership",
        "_complete_receipt_with",
    ):
        assert required in names, required
    assert (
        names.index("_begin_lifecycle_request")
        < names.index("prepare_end_membership")
        < names.index("finalize")
        < names.index("write_end_membership")
        < names.index("_complete_receipt_with")
    )
    finalize_line = next(c.lineno for c in _calls(function) if _name(c) == "finalize")
    after = {_name(c) for c in _calls(function) if c.lineno > finalize_line}
    allowed = {
        "write_end_membership",
        "EndCampaignMembershipResponse",
        "_complete_receipt_with",
    }
    assert after <= allowed, after - allowed
    for forbidden in (
        "record_change_log",
        "complete_idempotent_request",
        "begin_idempotent_request",
    ):
        assert forbidden not in names


def test_the_lock_order_is_roles_delegations_memberships_open_evidence_accounts_campaign_dependents_receipt() -> (
    None
):
    d = plans.END_DECLARATIONS
    assert d.reserved is not None and d.unkeyed is not None
    expected = [
        plans.END_ACTOR_ROLE_RANGE,
        plans.END_TARGET_ROLE_ROW,
        plans.END_TARGET_DELEGATIONS,
        plans.ACTOR_MEMBERSHIP_LOCK,
        plans.TARGET_MEMBERSHIP_LOCK,
        plans.END_OPEN_MEMBERSHIP,
        plans.END_LATE_ROLE_ROW,
        plans.END_LATE_DELEGATION,
        plans.ACTOR_ACCOUNT_LOCK,
        plans.CAMPAIGN_ROW_LOCK,
        plans.CAMPAIGN_KEY_SHARE_LOCK,
        plans.END_RELATIONSHIPS,
        plans.END_GRANTS,
        plans.END_GROUP_MEMBERSHIPS,
        plans.END_REVELATIONS,
        plans.END_REVELATION_MEMBERS,
    ]
    assert list(d.unkeyed.locks) == expected
    assert list(d.reserved.locks) == [*expected, plans.RECEIPT_LOCK]
    assert d.reserved.steps[-1] is plans.END_RECEIPT and d.unkeyed.steps == d.reserved.steps[:-1]


def test_each_lock_has_the_mode_it_needs_and_only_the_late_locks_do_not_wait() -> None:
    modes = {
        plans.END_ACTOR_ROLE_RANGE: LockMode.SHARE,
        plans.END_TARGET_ROLE_ROW: LockMode.UPDATE,
        plans.END_TARGET_DELEGATIONS: LockMode.UPDATE,
        plans.ACTOR_MEMBERSHIP_LOCK: LockMode.SHARE,
        plans.TARGET_MEMBERSHIP_LOCK: LockMode.UPDATE,
        plans.END_OPEN_MEMBERSHIP: LockMode.UPDATE,
        plans.END_LATE_ROLE_ROW: LockMode.UPDATE,
        plans.END_LATE_DELEGATION: LockMode.UPDATE,
        plans.ACTOR_ACCOUNT_LOCK: LockMode.SHARE,
        plans.CAMPAIGN_ROW_LOCK: LockMode.UPDATE,
        plans.CAMPAIGN_KEY_SHARE_LOCK: LockMode.KEY_SHARE,
        plans.END_RELATIONSHIPS: LockMode.UPDATE,
        plans.END_GRANTS: LockMode.UPDATE,
        plans.END_GROUP_MEMBERSHIPS: LockMode.UPDATE,
        plans.END_REVELATIONS: LockMode.UPDATE,
        plans.END_REVELATION_MEMBERS: LockMode.UPDATE,
    }
    for lock, mode in modes.items():
        assert lock.mode is mode, lock.name
    no_wait = {lock.name for lock in modes if lock.statement._for_update_arg.nowait}
    assert no_wait == {"end_late_role_row", "end_late_delegation"}
    # the shared/exclusive split of the role class: the actor's rows S, the target's U
    assert plans.END_ACTOR_ROLE_RANGE.mode is LockMode.SHARE
    assert plans.END_TARGET_ROLE_ROW.mode is LockMode.UPDATE


def test_obligations_are_evidence_driven_with_no_optional_bound() -> None:
    d = plans.END_DECLARATIONS.reserved
    assert d is not None
    by_name = {step.name: step for step in d.steps}
    closures = (
        "end_revoke_role",
        "end_revoke_late_role",
        "end_close_delegation",
        "end_close_late_delegation",
        "end_revoke_relationship",
        "end_revoke_grant",
        "end_remove_group_membership",
        "end_close_revelation",
        "end_remove_revelation_member",
        "end_membership",
    )
    for name in closures:
        cardinality = by_name[name].cardinality
        assert cardinality == EachLockedRow(complete=True), name
        assert by_name[name].target_lock is not None
    assert by_name["end_membership"].target_lock is plans.END_OPEN_MEMBERSHIP
    audit = by_name["audit_membership_ended"].cardinality
    assert isinstance(audit, PerEvidence) and audit.lock is plans.END_OPEN_MEMBERSHIP
    assert by_name["receipt"].cardinality == Exactly(1)
    assert not [s for s in d.steps if isinstance(s.cardinality, Between)]
    # the late rows are closed by their own steps, bound to their own locks
    assert by_name["end_revoke_late_role"].target_lock is plans.END_LATE_ROLE_ROW
    assert by_name["end_close_late_delegation"].target_lock is plans.END_LATE_DELEGATION


def test_the_membership_update_is_foreign_key_bound_to_the_actor_lock_and_the_status_lookup() -> (
    None
):
    step = plans.END_MEMBERSHIP
    bound = {binding.constraint.columns.keys()[0]: binding.lock for binding in step.fks}
    assert bound == {
        "ended_by_membership_id": plans.ACTOR_MEMBERSHIP_LOCK,
        "membership_status_id": None,
    }


def test_the_campaign_mode_invariant_refuses_a_write_under_a_weaker_lock() -> None:
    plans.require_campaign_mode_covers_writes(will_write=True, campaign_for_update=True)
    plans.require_campaign_mode_covers_writes(will_write=False, campaign_for_update=False)
    with pytest.raises(RuntimeError):
        plans.require_campaign_mode_covers_writes(will_write=True, campaign_for_update=False)


def test_prepare_chooses_the_campaign_mode_from_the_open_evidence_and_locks_late_rows_nowait_only() -> (
    None
):
    source = inspect.getsource(plans.prepare_end_membership)
    assert "if will_write:\n        plan.lock(connection, CAMPAIGN_ROW_LOCK" in source
    assert "plan.lock(connection, CAMPAIGN_KEY_SHARE_LOCK" in source
    assert (
        "require_campaign_mode_covers_writes(will_write=will_write, campaign_for_update=will_write)"
        in source
    )
    # the only locks taken after the membership's own that name a role or delegation row are the NOWAIT ones
    assert source.index("END_LATE_ROLE_ROW") > source.index("END_OPEN_MEMBERSHIP")
    assert "END_TARGET_ROLE_ROW" in source and "END_TARGET_DELEGATIONS" in source
    first_late = source.index("END_LATE_ROLE_ROW")
    assert "END_TARGET_ROLE_ROW" not in source[first_late:]
    assert "END_TARGET_DELEGATIONS" not in source[first_late:]


def test_the_retryable_conflict_is_a_409_with_a_stable_code() -> None:
    assert MembershipEndedStateChangedError.safe_status_code == 409
    assert MembershipEndedStateChangedError.safe_error_code == "membership_end_state_changed"


def test_changed_fields_lists_the_closed_ids_by_kind_and_includes_the_late_rows() -> None:
    a, b, c = uuid.UUID(int=1), uuid.UUID(int=2), uuid.UUID(int=3)
    prepared = plans.EndPrepared(
        world_id=uuid.uuid4(),
        action_id=uuid.uuid4(),
        status_id=uuid.uuid4(),
        will_write=True,
        role_ids=(a, c),
        late_role_ids=(b,),
        delegation_ids=(a,),
        relationship_ids=(b,),
    )
    changed = plans.changed_fields(prepared)
    assert changed["revoked_membership_role_ids"] == [str(a), str(b), str(c)]
    assert changed["revoked_membership_character_relationship_ids"] == [str(b)]
    assert set(changed) == {
        "revoked_membership_role_ids",
        "revoked_membership_character_relationship_ids",
        "revoked_resource_grant_ids",
        "removed_access_group_membership_ids",
        "closed_character_revelation_ids",
        "removed_character_revelation_member_ids",
    }
