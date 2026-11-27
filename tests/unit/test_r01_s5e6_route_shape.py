"""R01 S5-E6: the shape of the two reveal-delegation routes and of their declarations (inventory safeguards; the
runtime proof is `tests/database/test_r01_s5e6_reveal_delegation_routes.py`).

- Both routes are finalized, **unkeyed** pre-write routes: in the unkeyed registry only, no longer pending, and their
  handlers take no `Idempotency-Key` dependency and complete no receipt.
- Each handler prepares, finalizes exactly once at its top level and then runs only the module write function; it
  calls no legacy command and no audit helper of its own.
- Lock orders (the corrected S5-E2 order preserved): the role class in one pass (owner row `FOR SHARE`, `gm` row
  `FOR UPDATE`), the unlocked 404, the membership class (grantee `FOR NO KEY UPDATE`, caller `FOR KEY SHARE`), the
  delegation rows, the campaign `FOR KEY SHARE`; the recheck, the grantee judgment and the drift check follow the
  last lock. The revoke takes no campaign lock.
- Obligations: no `Between`; the optional branches are expressed by lock evidence (`PerAbsence`, `PerEvidence`,
  `EachLockedRow`, `AnyConfirmed`), never by an optional bound.
"""

import ast
import inspect
import textwrap
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.routing import APIRoute

from dnd_ai.api.app import create_app
from dnd_ai.api.r01_pending_routes import (
    R01_EXCLUDED_WORLD_ROUTES,
    R01_FINALIZED_ROUTES,
    R01_PENDING_ROUTES,
)
from dnd_ai.api.r01_pre_write_routes import (
    R01_KEYED_PRE_WRITE_ROUTES,
    R01_UNKEYED_PRE_WRITE_ROUTES,
)
from dnd_ai.commands import character_reveal
from dnd_ai.commands import reveal_delegation_plans as plans
from dnd_ai.domain.authorization_steps import (
    AnyConfirmed,
    Between,
    EachLockedRow,
    LockMode,
    PerAbsence,
    PerEvidence,
)
from tests.r01_manifest import _S5E6_ROUTES, _iter_api_routes

pytestmark = pytest.mark.unit

CAMPAIGN = "/campaigns/{campaign_id}"
GRANT = ("POST", CAMPAIGN + "/reveal-delegations")
REVOKE = ("POST", CAMPAIGN + "/reveal-delegations/{grantee_campaign_membership_id}/revoke")
PREPARE = {"grant": "prepare_grant", "revoke": "prepare_revoke"}
WRITE = {"grant": "write_grant", "revoke": "write_revoke"}
ROUTE = {"grant": GRANT, "revoke": REVOKE}
DECLARATION = {"grant": plans.GRANT_DECLARATION, "revoke": plans.REVOKE_DECLARATION}


def _handlers() -> dict[tuple[str, str], Callable[..., Any]]:
    found: dict[tuple[str, str], Callable[..., Any]] = {}
    for route in _iter_api_routes(list(create_app().routes)):
        assert isinstance(route, APIRoute)
        for method in route.methods:
            if (method, route.path) in _S5E6_ROUTES:
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


def test_the_two_routes_are_the_s5e6_set_finalized_unkeyed_and_no_longer_pending() -> None:
    assert {GRANT, REVOKE} == _S5E6_ROUTES
    assert set(R01_FINALIZED_ROUTES) >= _S5E6_ROUTES
    assert not _S5E6_ROUTES & set(R01_PENDING_ROUTES)
    assert not _S5E6_ROUTES & set(R01_KEYED_PRE_WRITE_ROUTES)
    assert R01_UNKEYED_PRE_WRITE_ROUTES[GRANT] is plans.GRANT_DECLARATION
    assert R01_UNKEYED_PRE_WRITE_ROUTES[REVOKE] is plans.REVOKE_DECLARATION
    # R01 E1 (plan 6.45) migrated the proposal-review route (180 / 7); R01 E2 (plan 6.48) the two AI
    # provider routes: 182 finalized, 5 pending; R01 E3 (plan 6.51) the Foundry combat sync: 183 finalized, 4 pending
    # R01 E4 (plan 6.54) the four reference-corpus routes: 187 finalized, 0 pending
    # 187 at R01 E4; 190 with the three P15-C11-S02-T01 control-assignment routes
    assert len(R01_FINALIZED_ROUTES) == 190 and len(R01_PENDING_ROUTES) == 0
    # S5-F bookkeeping: the five world routes are the explicit exclusions, neither finalized nor pending
    assert len([r for r in R01_EXCLUDED_WORLD_ROUTES if r[1].startswith("/worlds/")]) == 5
    assert not [r for r in R01_PENDING_ROUTES if r[1].startswith("/worlds/")]
    assert set(_handlers()) == _S5E6_ROUTES


@pytest.mark.parametrize("name", sorted(ROUTE))
def test_a_handler_prepares_finalizes_once_and_then_runs_only_the_module_write_function(
    name: str,
) -> None:
    function = _tree(_handlers()[ROUTE[name]])
    assert "plan" in {a.arg for a in function.args.args}
    # unkeyed: no Idempotency-Key dependency, no reservation, no receipt
    assert not {a.arg for a in function.args.args} & {"idempotency_key", "reservation"}
    body_calls = [c for stmt in function.body for c in _calls(stmt)]
    names = [_name(c) for c in sorted(body_calls, key=lambda c: (c.lineno, c.col_offset))]
    assert names.count("finalize") == 1
    main = names.index("finalize")
    assert names.index(PREPARE[name]) < main < names.index(WRITE[name])
    # nothing but the write function (and the response model) follows the final check
    assert set(names[main + 1 :]) <= {
        WRITE[name],
        "GrantCharacterRevealDelegationResponse",
        "RevokeCharacterRevealDelegationResponse",
    }, names[main + 1 :]
    forbidden = {
        "execute",
        "record_change_log",
        "grant_character_reveal_delegation",
        "revoke_character_reveal_delegation",
        "begin_idempotent_request",
        "start_campaign_idempotency",
        "_complete_receipt_with",
    }
    assert not forbidden & set(names), forbidden & set(names)


def test_the_direct_commands_are_unchanged_and_do_not_import_the_plan_module() -> None:
    source = inspect.getsource(character_reveal)
    assert "reveal_delegation_plans" not in source and "AuthorizationPlan" not in source
    for command in ("grant_character_reveal_delegation", "revoke_character_reveal_delegation"):
        assert callable(getattr(character_reveal, command))


def test_the_grant_declaration_locks_in_the_corrected_order_and_modes() -> None:
    d = plans.GRANT_DECLARATION
    assert [lock.name for lock in d.locks] == [
        "reveal_owner_row_share",
        "reveal_gm_row_update",
        "reveal_grantee_membership_no_key_update",
        "reveal_caller_membership_key_share",
        "reveal_stale_delegation_rows",
        "reveal_matching_delegation_row",
        "campaign_key_share",
    ]
    modes = {lock.name: lock.mode for lock in d.locks}
    assert modes == {
        "reveal_owner_row_share": LockMode.SHARE,
        "reveal_gm_row_update": LockMode.UPDATE,
        "reveal_grantee_membership_no_key_update": LockMode.NO_KEY_UPDATE,
        "reveal_caller_membership_key_share": LockMode.KEY_SHARE,
        "reveal_stale_delegation_rows": LockMode.UPDATE,
        "reveal_matching_delegation_row": LockMode.UPDATE,
        "campaign_key_share": LockMode.KEY_SHARE,
    }
    # the campaign is never stronger than the mode the insert needs (administrative recovery holds it FOR NO KEY
    # UPDATE while it waits for the membership it promotes), and the grantee's membership is never FOR UPDATE
    assert plans.GRANTEE_MEMBERSHIP_LOCK.mode is LockMode.NO_KEY_UPDATE
    assert plans.CAMPAIGN_KEY_SHARE_LOCK.mode is LockMode.KEY_SHARE


def test_the_revoke_declaration_takes_no_campaign_lock_and_no_gm_row() -> None:
    d = plans.REVOKE_DECLARATION
    assert [lock.name for lock in d.locks] == [
        "reveal_owner_row_share",
        "reveal_revoke_delegation_row",
        "reveal_caller_membership_key_share",
    ]
    assert plans.CAMPAIGN_KEY_SHARE_LOCK not in d.locks and plans.GM_ROW_LOCK not in d.locks
    assert plans.REVOKE_DELEGATION_LOCK.mode is LockMode.UPDATE
    assert plans.CALLER_MEMBERSHIP_LOCK.mode is LockMode.KEY_SHARE


def test_the_obligations_come_from_lock_evidence_and_no_bound_is_optional() -> None:
    for declaration in (plans.GRANT_DECLARATION, plans.REVOKE_DECLARATION):
        for step in declaration.steps:
            assert not isinstance(step.cardinality, Between), step.name
    close, insert, audit = plans.GRANT_DECLARATION.steps
    assert close.cardinality == EachLockedRow(complete=True) and close.target_lock is (
        plans.STALE_DELEGATION_LOCK
    )
    assert isinstance(insert.cardinality, PerAbsence)
    assert insert.cardinality.lock is plans.MATCHING_DELEGATION_LOCK
    assert isinstance(audit.cardinality, AnyConfirmed) and audit.cardinality.steps == (insert,)
    update, revoke_audit = plans.REVOKE_DECLARATION.steps
    assert update.cardinality == EachLockedRow(complete=True) and update.target_lock is (
        plans.REVOKE_DELEGATION_LOCK
    )
    assert isinstance(revoke_audit.cardinality, PerEvidence)
    assert revoke_audit.cardinality.lock is plans.REVOKE_DELEGATION_LOCK
    # the foreign keys the insert writes are each bound to the lock that holds the referenced row
    bound = {binding.lock.name for binding in insert.fks if binding.lock is not None}
    assert bound == {
        "campaign_key_share",
        "reveal_grantee_membership_no_key_update",
        "reveal_gm_row_update",
        "reveal_caller_membership_key_share",
    }
    assert {b.lock.name for b in update.fks if b.lock is not None} == {
        "reveal_caller_membership_key_share"
    }


def test_the_audit_steps_carry_the_legacy_command_names_tables_and_no_extra_columns() -> None:
    _, _, grant_audit = plans.GRANT_DECLARATION.steps
    _, revoke_audit = plans.REVOKE_DECLARATION.steps
    assert plans.GRANT_COMMAND_NAME == "grant_character_reveal_delegation"
    assert plans.REVOKE_COMMAND_NAME == "revoke_character_reveal_delegation"
    for step in (grant_audit, revoke_audit):
        assert step.value_binds == {"record", "world", "correlation", "changed"}


def _order(source: str, names: list[str]) -> None:
    positions = [source.index(name) for name in names]
    assert positions == sorted(positions), dict(zip(names, positions, strict=True))


def test_prepare_grant_reads_locks_and_judges_in_the_documented_order() -> None:
    """Discovery, the role pass (owner row, gm row), the 404, the membership class, the delegation rows, the
    campaign; then the fresh-instant judgments and the drift check; nothing is written here."""
    source = inspect.getsource(plans.prepare_grant)
    _order(
        source,
        [
            "normalize_reason(",
            "_discover_role_rows(",
            "OWNER_ROW_LOCK,",
            "GM_ROW_LOCK,",
            "_require_grantee_in_campaign(",
            "GRANTEE_MEMBERSHIP_LOCK",
            "CALLER_MEMBERSHIP_LOCK",
            "STALE_DELEGATION_LOCK",
            "MATCHING_DELEGATION_LOCK",
            "CAMPAIGN_KEY_SHARE_LOCK",
            "_database_clock(",
            "_recheck_caller_is_live_owner(",
            "find_live_builtin_gm_assignment(",
            "RevealDelegationRecipientNotGmError(",
            "RevealDelegationRecipientChangedError(",
            "_live_delegations(",
        ],
    )
    assert ".execute(" not in source.replace("plan.execute", "")
    assert "plan.execute" not in source, "no write before finalize"


def test_prepare_revoke_locks_the_owner_row_the_delegation_and_the_membership_in_that_order() -> (
    None
):
    source = inspect.getsource(plans.prepare_revoke)
    _order(
        source,
        [
            "normalize_reason(",
            "find_live_builtin_owner_assignment(",
            "OWNER_ROW_LOCK",
            "_require_grantee_in_campaign(",
            "REVOKE_DELEGATION_LOCK",
            "CALLER_MEMBERSHIP_LOCK",
            "_recheck_caller_is_live_owner(",
        ],
    )
    assert "plan.execute" not in source and "CAMPAIGN_KEY_SHARE_LOCK" not in source


def test_the_write_functions_run_only_declared_steps() -> None:
    for function, allowed in (
        (plans.write_grant, {"CLOSE_STALE_DELEGATION", "INSERT_DELEGATION", "GRANT_AUDIT"}),
        (plans.write_revoke, {"REVOKE_DELEGATION", "REVOKE_AUDIT"}),
    ):
        tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
        executed = {
            n.args[1].id
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and _name(n) == "execute"
            and len(n.args) > 1
            and isinstance(n.args[1], ast.Name)
        }
        assert executed == allowed
        assert "connection.execute" not in inspect.getsource(function)


def test_the_final_requirements_are_registered_after_every_early_check_and_before_the_plan_returns() -> (
    None
):
    """R01 S5-E6 correction: the owner (both routes) and the recipient (the grant) are registered with `plan.require`
    after the last early check (the drift check; the caller's recheck) and in that order, owner first. The early checks
    keep their precedence; the plan's `finalize` judges these at its own instant."""
    grant = inspect.getsource(plans.prepare_grant)
    _order(
        grant,
        [
            "RevealDelegationRecipientNotGmError(",
            "RevealDelegationRecipientChangedError(",
            "_live_delegations(",
            "plan.require(connection, owner_requirement(",
            "plan.require(connection, recipient_requirement(",
            "return GrantPrepared(",
        ],
    )
    revoke = inspect.getsource(plans.prepare_revoke)
    _order(
        revoke,
        [
            "_recheck_caller_is_live_owner(",
            "plan.require(connection, owner_requirement(",
            "return RevokePrepared(",
        ],
    )
    assert "recipient_requirement" not in revoke
    # the requirements read the final snapshot only: no connection, no cached liveness boolean
    for function in (plans.owner_requirement, plans.recipient_requirement):
        source = inspect.getsource(function)
        assert "connection" not in source and "execute(" not in source
    assert "grantee: uuid.UUID, gm_assignment: uuid.UUID" in inspect.getsource(
        plans.recipient_requirement
    )
