"""R01 S2: the shape of the six migrated routes and the decision tables of their requirements.

Plan section 12.5: AST checks are inventory safeguards only (the runtime proof is in
`tests/database/test_r01_s2_profile_routes.py`). They pin that every route in `R01_FINALIZED_ROUTES`
takes the request's plan, passes it to its idempotency start and to its command, and calls
`plan.finalize(connection)` exactly once, after every other call that touches the database. The
decision tables run the requirements over constructed snapshots: no database.
"""

import ast
import inspect
import textwrap
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.routing import APIRoute

from dnd_ai.api.access import route_capability_requirement
from dnd_ai.api.app import create_app
from dnd_ai.api.errors import ForbiddenError, NotFoundError
from dnd_ai.api.r01_pending_routes import R01_FINALIZED_ROUTES
from dnd_ai.commands.character_public_profile import edit_requirement, reveal_held_requirement
from dnd_ai.domain.access import AccessContext, AuthoritySnapshot
from dnd_ai.domain.authoring import CampaignNotAuthorizedError, WorldAuthorityRequiredError
from dnd_ai.domain.authorization_requirements import judged_requirement
from dnd_ai.domain.public_profiles import (
    CharacterRevealRequiredError,
    PublicProfileEditDeniedError,
    PublicProfileNotFoundError,
)
from dnd_ai.domain.world_authority import WorldAuthority
from tests.r01_manifest import _S3_ROUTES, _iter_api_routes

pytestmark = pytest.mark.unit

#: S2's six routes. S3's 71 are checked by `test_r01_s3_route_shape.py`.
S2_ROUTES = frozenset(R01_FINALIZED_ROUTES) - _S3_ROUTES

DB_CALLS = {
    "record_change_log",
    "finish_campaign_idempotency",
    "start_campaign_idempotency",
    "lock_idempotency_key",
}


def _handlers() -> dict[tuple[str, str], Any]:
    app = create_app()
    found: dict[tuple[str, str], Any] = {}
    for route in _iter_api_routes(list(app.routes)):
        assert isinstance(route, APIRoute)
        for method in route.methods:
            if (method, route.path) in S2_ROUTES:
                found[(method, route.path)] = route.endpoint
    return found


def _calls(tree: ast.AST) -> list[ast.Call]:
    return [n for n in ast.walk(tree) if isinstance(n, ast.Call)]


def _name(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def test_the_finalized_routes_resolve_to_handlers() -> None:
    assert set(_handlers()) == set(S2_ROUTES)


@pytest.mark.parametrize("route", sorted(S2_ROUTES))
def test_a_finalized_handler_takes_the_plan_and_finalizes_it_last_exactly_once(
    route: tuple[str, str],
) -> None:
    handler = _handlers()[route]
    tree = ast.parse(textwrap.dedent(inspect.getsource(handler)))
    function = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))
    assert "plan" in {a.arg for a in function.args.args}, "the handler does not take the plan"

    finalizes = [c for c in _calls(function) if _name(c) == "finalize"]
    assert len(finalizes) == 1, "exactly one plan.finalize per handler"
    final = finalizes[0]
    # it is the call of an expression statement `plan.finalize(connection)`, at the handler's top level
    statement = next(s for s in function.body if isinstance(s, ast.Expr) and s.value is final)
    after = [
        s for s in function.body if s.lineno > statement.lineno and not isinstance(s, ast.Return)
    ]
    assert after == [], "a statement follows the final check"
    # every database-touching call of the request precedes it
    for call in _calls(function):
        if _name(call) in DB_CALLS or _name(call).startswith(
            ("save_", "copy_", "release_", "create_", "revoke_")
        ):
            assert call.lineno < final.lineno, f"{_name(call)} follows the final check"
    # the idempotency start gets the plan, so a replay is judged (plan 6.6)
    starts = [c for c in _calls(function) if _name(c) == "start_campaign_idempotency"]
    assert starts, "the handler no longer starts an idempotency"
    for start in starts:
        assert any(
            k.arg == "plan" and isinstance(k.value, ast.Name) and k.value.id == "plan"
            for k in start.keywords
        ), "start_campaign_idempotency does not receive the plan"
    # the command receives it too
    commands = [
        c
        for c in _calls(function)
        if _name(c).startswith(("save_", "copy_", "release_", "create_", "revoke_"))
    ]
    assert len(commands) == 1
    assert any(k.arg == "plan" for k in commands[0].keywords), (
        "the command does not receive the plan"
    )


# --- decision tables over constructed snapshots ----------------------------------------------------------------------

CAMPAIGN = uuid.uuid4()
USER = uuid.uuid4()
CHARACTER = uuid.uuid4()
WORLD = uuid.uuid4()


def _access(
    *roles: str, lifecycle: str = "active", grants: dict[Any, dict[str, str]] | None = None
) -> AccessContext:
    return AccessContext(
        user_id=USER,
        campaign_id=CAMPAIGN,
        campaign_membership_id=uuid.uuid4(),
        timeline_id=uuid.uuid4(),
        role_capabilities=frozenset(roles),
        character_capabilities={},
        grant_effects=grants or {},
        campaign_lifecycle_status=lifecycle,
    )


def _snapshot(
    access: AccessContext | None,
    *,
    reveal: str | None = None,
    world: WorldAuthority | None = None,
) -> AuthoritySnapshot:
    return AuthoritySnapshot(
        t_auth=datetime.now(UTC),
        isolation="read committed",
        access=access,
        world_id=WORLD if world is not None else None,
        world_authority=world,
        reveal_authority=reveal,  # type: ignore[arg-type]
    )


def _decide(requirement: Any, snapshot: AuthoritySnapshot) -> BaseException | None:
    return None if requirement.predicate(snapshot) else requirement.refusal()


def test_the_route_requirement_raises_what_the_dependency_raises() -> None:
    requirement = route_capability_requirement(
        capability_code="canon.edit",
        allow_archived_campaign=False,
        world_capability=None,
        world_id=None,
        actor_user_id=USER,
    )
    assert isinstance(_decide(requirement, _snapshot(None)), NotFoundError)
    assert isinstance(
        _decide(requirement, _snapshot(_access("canon.edit", lifecycle="archived"))), NotFoundError
    )
    assert isinstance(
        _decide(requirement, _snapshot(_access("canon.edit", lifecycle="deleted"))), NotFoundError
    )
    assert isinstance(_decide(requirement, _snapshot(_access("campaign.view"))), ForbiddenError)
    assert _decide(requirement, _snapshot(_access("canon.edit"))) is None


def test_the_route_requirement_admits_an_archived_campaign_only_when_the_route_does() -> None:
    requirement = route_capability_requirement(
        capability_code="campaign.view",
        allow_archived_campaign=True,
        world_capability=None,
        world_id=None,
        actor_user_id=USER,
    )
    assert _decide(requirement, _snapshot(_access("campaign.view", lifecycle="archived"))) is None


def test_the_route_requirement_declares_the_world_only_when_it_needs_it() -> None:
    plain = route_capability_requirement(
        capability_code="canon.edit",
        allow_archived_campaign=False,
        world_capability=None,
        world_id=WORLD,
        actor_user_id=USER,
    )
    assert plain.world_id is None
    scoped = route_capability_requirement(
        capability_code="canon.edit",
        allow_archived_campaign=False,
        world_capability="world.canon.edit",
        world_id=WORLD,
        actor_user_id=USER,
    )
    assert scoped.world_id == WORLD
    assert isinstance(
        _decide(scoped, _snapshot(_access("canon.edit"), world=None)), WorldAuthorityRequiredError
    )


def test_a_judged_requirement_refuses_with_the_error_of_its_last_decision() -> None:
    errors = iter([ValueError("first"), None, KeyError("third")])
    requirement = judged_requirement("t", lambda _snapshot: next(errors))
    snapshot = _snapshot(None)
    assert requirement.predicate(snapshot) is False
    assert isinstance(requirement.refusal(), ValueError)
    assert requirement.predicate(snapshot) is True
    assert requirement.predicate(snapshot) is False
    assert isinstance(requirement.refusal(), KeyError)


def test_the_edit_requirement_distinguishes_a_caller_who_can_still_read_from_one_who_cannot() -> (
    None
):
    requirement = edit_requirement(USER, CHARACTER)
    editor = _access("canon.edit", "campaign.view")
    assert _decide(requirement, _snapshot(editor, reveal="none")) is None
    deny_edit = _access(
        "canon.edit", "campaign.view", grants={("entity_id", CHARACTER): {"canon.edit": "deny"}}
    )
    # still able to read through reveal authority: 403
    assert isinstance(
        _decide(requirement, _snapshot(deny_edit, reveal="delegation")),
        PublicProfileEditDeniedError,
    )
    # nothing to read it with: 404
    assert isinstance(
        _decide(requirement, _snapshot(deny_edit, reveal="none")), PublicProfileNotFoundError
    )
    deny_view = _access(
        "canon.edit", "campaign.view", grants={("entity_id", CHARACTER): {"campaign.view": "deny"}}
    )
    assert isinstance(
        _decide(requirement, _snapshot(deny_view, reveal="owner")), PublicProfileNotFoundError
    )
    assert isinstance(_decide(requirement, _snapshot(None)), CampaignNotAuthorizedError)


def test_the_reveal_requirement_demands_the_locked_source_and_no_whole_character_deny() -> None:
    membership = uuid.uuid4()
    access = _access("campaign.view")
    locked = reveal_held_requirement(membership, CHARACTER, source="delegation")
    assert _decide(locked, _snapshot(access, reveal="delegation")) is None
    assert isinstance(
        _decide(locked, _snapshot(access, reveal="owner")), CharacterRevealRequiredError
    )
    assert isinstance(
        _decide(locked, _snapshot(access, reveal="none")), CharacterRevealRequiredError
    )
    denied = _access("campaign.view", grants={("entity_id", CHARACTER): {"campaign.view": "deny"}})
    assert isinstance(
        _decide(locked, _snapshot(denied, reveal="delegation")), PublicProfileNotFoundError
    )
    # the route's pre-check names no source: any live authority passes
    precheck = reveal_held_requirement(membership, CHARACTER)
    assert _decide(precheck, _snapshot(access, reveal="owner")) is None
    assert isinstance(
        _decide(precheck, _snapshot(access, reveal="none")), CharacterRevealRequiredError
    )
