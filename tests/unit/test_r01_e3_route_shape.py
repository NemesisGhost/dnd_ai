"""R01 E3: the Foundry combat sync's static shape.

`POST /campaigns/{campaign_id}/integration/foundry/combat-sync` is finalized with family `engine_claim_work`. The
handler finalizes the request plan (the early check), ends the request transaction, then calls the command. The command
takes the operation's session advisory lock on ONE connection and runs a claim and a work transaction on it, each in its
own `_planned_transaction` (a post-write plan whose final check is the last statement before COMMIT), and a failed work
is recorded by a third one (the fail transaction, E3-D5). Every set of requirements starts with the active-account check
(`account.active`). The route has no
reservation, so it is in no deferred-reservation registry.
"""

import ast
import inspect
import json
import uuid
from typing import Any
from unittest.mock import MagicMock

import pytest

from dnd_ai.api import integration as integration_api
from dnd_ai.api.r01_pending_routes import (
    R01_DEFERRED_RESERVATION_ROUTES,
    R01_FINALIZED_ROUTES,
    R01_LATE_RESERVATION_ROUTES,
    R01_PENDING_ROUTES,
)
from dnd_ai.api.r01_pre_write_routes import (
    R01_KEYED_PRE_WRITE_ROUTES,
    R01_UNKEYED_PRE_WRITE_ROUTES,
)
from dnd_ai.commands import integration as integration_command
from dnd_ai.domain.access import AuthenticatedPrincipal
from tests.r01_manifest import E3_ROUTES, ENGINE_CLAIM_WORK, MANIFEST_PATH

pytestmark = pytest.mark.unit

ROUTE = ("POST", "/campaigns/{campaign_id}/integration/foundry/combat-sync")


def _function(module: Any, name: str) -> ast.FunctionDef:
    tree = ast.parse(inspect.getsource(module))
    return next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)


def _call_lines(node: ast.AST) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            func = n.func
            if isinstance(func, ast.Name):
                found.append((n.lineno, func.id))
            elif isinstance(func, ast.Attribute):
                found.append((n.lineno, func.attr))
    return sorted(found)


def test_the_route_is_finalized_claim_work_and_in_no_other_registry() -> None:
    assert {ROUTE} == E3_ROUTES
    assert ROUTE in R01_FINALIZED_ROUTES
    assert ROUTE not in R01_PENDING_ROUTES
    assert ROUTE not in R01_KEYED_PRE_WRITE_ROUTES
    assert ROUTE not in R01_UNKEYED_PRE_WRITE_ROUTES
    assert ROUTE not in R01_DEFERRED_RESERVATION_ROUTES
    assert ROUTE not in R01_LATE_RESERVATION_ROUTES


def test_the_committed_manifest_classifies_it_engine_claim_work() -> None:
    records = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    mine = [r for r in records if (r["method"], r["path"]) == ROUTE]
    assert len(mine) == 1
    assert mine[0]["family"] == ENGINE_CLAIM_WORK == "engine_claim_work"


def test_the_handler_finalizes_the_request_plan_then_ends_the_transaction_then_calls_the_command() -> (
    None
):
    function = _function(integration_api, "apply_foundry_combat_sync_endpoint")
    parameters = {a.arg for a in function.args.args}
    assert {"connection", "plan", "engine"} <= parameters
    calls = _call_lines(function)
    names = [n for _, n in calls]
    assert names.count("finalize") == 1
    assert names.count("end_request_transaction") == 1
    assert names.count("apply_foundry_combat_sync") == 1
    finalize = next(line for line, n in calls if n == "finalize")
    end = next(line for line, n in calls if n == "end_request_transaction")
    call = next(line for line, n in calls if n == "apply_foundry_combat_sync")
    assert finalize < end < call
    # E3-D5: the request's own plan also judges the account, registered before it is finalized
    assert names.count("active_account_requirement") == 1
    account = next(line for line, n in calls if n == "active_account_requirement")
    require = next(line for line, n in calls if n == "require")
    assert require <= account < finalize
    uses = [
        n.lineno
        for n in ast.walk(function)
        if isinstance(n, ast.Name) and n.id == "connection" and isinstance(n.ctx, ast.Load)
    ]
    assert max(uses) < end  # the request connection is not used after its transaction ended
    # the scope and the system match are judged before the final check (R-D2 order)
    assert next(line for line, n in calls if n == "assert_foundry_system_matches") < finalize


def test_the_command_runs_exactly_a_claim_and_a_work_planned_transaction_on_the_lock_connection() -> (
    None
):
    function = _function(integration_command, "apply_foundry_combat_sync")
    planned = [
        n
        for n in ast.walk(function)
        if isinstance(n, ast.With)
        and any(
            isinstance(item.context_expr, ast.Call)
            and isinstance(item.context_expr.func, ast.Name)
            and item.context_expr.func.id == "_planned_transaction"
            for item in n.items
        )
    ]
    assert len(planned) == 3  # claim, work, and (E3-D5) the fail transaction
    source = ast.unparse(function)
    # the one connection of the call: no second connection, no `authorized_transaction` (it opens its own)
    assert source.count("engine.connect()") == 1
    for forbidden in ("engine.begin", "authorized_transaction"):
        assert forbidden not in source, forbidden
    assert (
        source.count(".commit(") == 1
    )  # only the advisory lock's own statement; C and W commit in their context
    # no plain transaction is left on the lock connection: the fail step is planned too, so its bookkeeping is judged
    plain = [
        n
        for n in ast.walk(function)
        if isinstance(n, ast.With)
        and any(
            isinstance(item.context_expr, ast.Call)
            and isinstance(item.context_expr.func, ast.Attribute)
            and item.context_expr.func.attr == "begin"
            for item in n.items
        )
    ]
    assert plain == []
    claim, work, fail = sorted(planned, key=lambda w: w.lineno)
    assert claim.end_lineno is not None and claim.end_lineno < work.lineno
    assert work.end_lineno is not None and work.end_lineno < fail.lineno  # F follows W's rollback
    # F is reached only when W's own final check did not refuse
    assert "if not work.final_refused" in source
    assert (
        "fail.final_refused" in source
    )  # and F's own refusal replaces the domain error for the caller


def test_the_planned_transaction_finalizes_last_and_never_closes_the_connection() -> None:
    function = _function(integration_command, "_planned_transaction")
    source = ast.unparse(function)
    assert ".close(" not in source and "invalidate" not in source
    calls = [n for _, n in _call_lines(function)]
    assert calls.index("begin") < calls.index("register_requirements") < calls.index("finalize")


def test_an_empty_requirement_factory_is_refused_before_any_statement() -> None:
    engine = MagicMock()
    with pytest.raises(ValueError, match="requirement"):
        integration_command.apply_foundry_combat_sync(
            engine,
            actor_user_id=uuid.uuid4(),
            campaign_id=uuid.uuid4(),
            requirements=lambda: [],
            external_system_id=uuid.uuid4(),
            external_operation_id="op",
            encounter_id=uuid.uuid4(),
            round_number=1,
            turn_order=0,
            actor_entity_id=uuid.uuid4(),
            world_time_id=uuid.uuid4(),
        )
    engine.connect.assert_not_called()  # no connection, so no advisory lock and no statement


def test_the_command_has_no_unscoped_mode() -> None:
    signature = inspect.signature(integration_command.apply_foundry_combat_sync)
    for name in ("actor_user_id", "campaign_id", "requirements"):
        parameter = signature.parameters[name]
        assert parameter.default is inspect.Parameter.empty, name  # required


def test_the_factory_returns_fresh_requirement_objects_on_every_call() -> None:
    campaign, user = uuid.uuid4(), uuid.uuid4()
    principal = MagicMock(spec=AuthenticatedPrincipal)
    principal.auth_method = "oidc"
    factory = integration_api.combat_sync_requirements(
        principal=principal, actor_user_id=user, campaign_id=campaign
    )
    first, second = factory(), factory()
    assert len(first) == len(second) == 2
    assert all(a is not b for a, b in zip(first, second, strict=True))
    assert first[0].name == "account.active" and first[0].account is True  # E3-D5, judged first
    assert (
        first[1].name == "route.canon.edit"
    )  # the capability that authorizes the sync (not `integration.manage`)


def _foundry_principal(campaign: uuid.UUID, scopes: frozenset[str]) -> AuthenticatedPrincipal:
    from dnd_ai.domain.access import FOUNDRY_ACCESS_AUTH_METHOD

    return AuthenticatedPrincipal(
        user_id=uuid.uuid4(),
        auth_method=FOUNDRY_ACCESS_AUTH_METHOD,
        foundry_external_system_id=uuid.uuid4(),
        foundry_world_id=uuid.uuid4(),
        campaign_id=campaign,
        foundry_connection_id=uuid.uuid4(),
        foundry_device_id=uuid.uuid4(),
        foundry_scopes=scopes,
    )


def test_the_factory_carries_the_foundry_binding_and_scope_and_the_archived_refusal() -> None:
    """The final checks re-apply the credential's campaign binding and `combat_sync` scope (constants of the principal) and
    refuse an archived campaign, exactly as the route dependency does at the start of the request."""
    campaign = uuid.uuid4()
    user = uuid.uuid4()
    foundry = integration_api.combat_sync_requirements(
        principal=_foundry_principal(campaign, frozenset({"combat_sync"})),
        actor_user_id=user,
        campaign_id=campaign,
    )
    assert foundry()[1].name == "route.canon.edit.foundry"
    session = MagicMock(spec=AuthenticatedPrincipal)
    session.auth_method = "oidc"
    plain = integration_api.combat_sync_requirements(
        principal=session, actor_user_id=user, campaign_id=campaign
    )
    assert plain()[1].name == "route.canon.edit"


def test_the_factory_is_built_from_the_route_requirement_with_canon_edit_and_no_archived_campaigns() -> (
    None
):
    source = inspect.getsource(integration_api.combat_sync_requirements)
    assert "_INTEGRATION_MANAGE_CAPABILITY" in source
    assert integration_api._INTEGRATION_MANAGE_CAPABILITY == "canon.edit"
    assert "allow_archived_campaign=False" in source
    assert "_foundry_facts(principal, campaign_id, _COMBAT_SYNC_SCOPE)" in source


def test_the_account_requirement_is_the_only_one_that_reads_the_account_and_refuses_with_a_404() -> (
    None
):
    from datetime import UTC, datetime

    from dnd_ai.api.access import active_account_requirement
    from dnd_ai.api.errors import NotFoundError
    from dnd_ai.domain.access import AuthoritySnapshot

    requirement = active_account_requirement()
    assert requirement.account is True and requirement.world_id is None and not requirement.reveal
    now = datetime.now(UTC)

    def snapshot(active: bool | None) -> AuthoritySnapshot:
        return AuthoritySnapshot(
            t_auth=now, isolation="read committed", access=None, account_active=active
        )

    assert requirement.predicate(snapshot(True)) is True
    for undeclared_or_inactive in (False, None):
        fresh = active_account_requirement()
        assert fresh.predicate(snapshot(undeclared_or_inactive)) is False
        assert isinstance(fresh.refusal(), NotFoundError)
    # the route requirement does not declare the account, so only account.active makes the snapshot read it
    other = integration_api.combat_sync_requirements(
        principal=MagicMock(spec=AuthenticatedPrincipal, auth_method="oidc"),
        actor_user_id=uuid.uuid4(),
        campaign_id=uuid.uuid4(),
    )()
    assert [r.account for r in other] == [True, False]
