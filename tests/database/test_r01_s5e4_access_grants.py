# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""R01 S5-E4: resource grants and character relationships as keyed-optional pre-write plans, over real HTTP and
real connections.

The five routes (`dnd_ai.commands.access_grant_plans`) take the actor's role rows `FOR SHARE`, the actor's open
membership `FOR SHARE` and the target membership `FOR UPDATE` (ascending id), the accounts, the campaign (`FOR UPDATE`
to write a new row, `FOR KEY SHARE` to revoke), the catalogue row and the target rows, [the receipt], judge authority at
`plan.finalize` and only then write through declared steps. A **group** grantee's row is locked before every other row.

Evidence classes (labelled in each docstring), as in the S5-E2/E3 modules:

- **route**: a real HTTP request through the guard on a one-connection pool.
- **sql**: the recorded statement stream of such a request (`Recorder`).
- **race**: a route request on one side and a competitor on the other, each held on a named statement or an open
  transaction; every wait is observed through `pg_blocking_pids`, never assumed.
- **mutation (test-side)**: `AuthorizationPlan.execute` is wrapped to omit, repeat or misdirect a write, to show that
  the declared obligations refuse it. Nothing production-side is changed.

The behaviour of every refusal (the error classes, precedence and response bodies of the commands) is held by the
pre-existing `test_api_access_grants.py`, which runs unchanged against the migrated routes; this module adds what only a
pre-write plan has. The shared authoring harness cannot establish transaction, deferral, lock or COMMIT guarantees
(it shares one transaction and never commits); none of this module uses it.
"""

import dataclasses
import re
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from dnd_ai.domain.authorization import AuthorizationPlan
from tests.database.test_r01_s2_profile_routes import (  # noqa: F401 - fixtures used by name
    FINAL,
    FINAL_RE,
    Recorder,
    idle_in_transaction,
    pooled,
    pooled_factory,
)
from tests.database.test_r01_s3_authoring_routes import (  # noqa: F401 - fixtures used by name
    World,
    code,
    error_of,
    w,
)
from tests.database.test_r01_s5e2_membership_routes import (  # noqa: F401 - fixtures used by name
    Scene,
    m,
    pooled2,
    pooled2_factory,
    s,
)
from tests.factories import (
    make_access_group,
    make_campaign,
    make_campaign_membership,
    make_character,
    make_membership_character_relationship,
    make_membership_role,
    make_resource_grant,
    make_user,
)
from tests.http_race_support import new_key
from tests.r01_s5d_support import revoke_role

pytestmark = pytest.mark.database

Factory = Callable[[uuid.UUID], TestClient]
KEYED = pytest.mark.parametrize("keyed", (True, False), ids=("keyed", "unkeyed"))

KEY_LOCK = r"pg_advisory_xact_lock"
ROLES_S = r"FROM security\.membership_roles WHERE .* FOR SHARE$"
MEMBERSHIP_S = r"FROM security\.campaign_memberships WHERE .* FOR SHARE$"
MEMBERSHIP_U = r"FROM security\.campaign_memberships WHERE .* FOR UPDATE$"
ACCOUNT_S = r"FROM security\.users WHERE .* FOR SHARE$"
ACCOUNT_KS = r"FROM security\.users WHERE .* FOR KEY SHARE$"
CAMPAIGN_U = r"FROM campaign\.campaigns WHERE campaign\.campaigns\.campaign_id = %\(campaign\)s::UUID FOR UPDATE$"
CAMPAIGN_KS = r"FROM campaign\.campaigns WHERE .* FOR KEY SHARE$"
TYPE_U = r"FROM security\.character_relationship_types WHERE .* FOR UPDATE$"
CAPABILITY_U = r"FROM security\.capabilities WHERE .* FOR UPDATE$"
ENTITY_U = r"FROM core\.entities WHERE .* FOR UPDATE$"
CHARACTER_KS = r"FROM character\.characters WHERE .* FOR KEY SHARE$"
GROUP_U = r"FROM security\.access_groups WHERE .* FOR UPDATE$"
RELATIONSHIP_U = r"FROM security\.membership_character_relationships WHERE .* FOR UPDATE$"
GRANT_U = r"FROM security\.resource_grants WHERE .* FOR UPDATE$"
RECEIPT_U = r"FROM security\.idempotent_requests WHERE .*idempotent_request_id = %\(receipt\)s::UUID FOR UPDATE"
AUDIT_INSERT = r"^INSERT INTO audit\.change_log"
RECEIPT_UPDATE = r"^UPDATE security\.idempotent_requests"
INSERT_RELATIONSHIP = r"^INSERT INTO security\.membership_character_relationships"
UPDATE_RELATIONSHIP = r"^UPDATE security\.membership_character_relationships"
INSERT_GRANT = r"^INSERT INTO security\.resource_grants"
UPDATE_GRANT = r"^UPDATE security\.resource_grants"


# --- the scene -----------------------------------------------------------------------------------------------------


@dataclasses.dataclass
class Env:
    """A fresh member with a relationship and a grant, a second character, a group, and the seeded type ids."""

    user: uuid.UUID
    membership: uuid.UUID
    character: uuid.UUID
    other_character: uuid.UUID
    portrayer: uuid.UUID
    co_controller: uuid.UUID
    relationship: uuid.UUID
    grant: uuid.UUID
    group: uuid.UUID
    capability: uuid.UUID


def build_env(sc: Scene, label: str = "S5E4") -> Env:
    with sc.w.engine.begin() as c:
        user = make_user(c, label)
        membership = make_campaign_membership(c, sc.w.campaign_id, user)
        make_membership_role(c, membership, sc.player)
        character = make_character(c, sc.w.world_id, name=f"{label} character")
        other = make_character(c, sc.w.world_id, name=f"{label} other character")
        types = {
            row[0]: row[1]
            for row in c.execute(
                text(
                    "SELECT code, character_relationship_type_id FROM security.character_relationship_types "
                    "WHERE code IN ('portrayer', 'co_controller')"
                )
            )
        }
        relationship = make_membership_character_relationship(
            c,
            membership,
            character,
            types["portrayer"],
            granted_by_membership_id=sc.m.keeper_membership,
        )
        capability = c.execute(
            text(
                "SELECT capability_id FROM security.capabilities WHERE code = 'character.view_summary'"
            )
        ).scalar_one()
        grant = make_resource_grant(
            c,
            sc.w.campaign_id,
            capability,
            grantee_campaign_membership_id=membership,
            character_id=character,
            granted_by_membership_id=sc.m.keeper_membership,
        )
        group = make_access_group(c, sc.w.campaign_id, name=f"{label} group")
    return Env(
        user,
        membership,
        character,
        other,
        types["portrayer"],
        types["co_controller"],
        relationship,
        grant,
        group,
        capability,
    )


@pytest.fixture
def env(s: Scene) -> Env:
    return build_env(s)


@pytest.fixture(autouse=True)
def _tidy(w: World) -> Any:
    yield
    with w.engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        cleanup.execute(
            text("DELETE FROM audit.change_log WHERE world_id = :w AND command_name = ANY(:c)"),
            {"w": w.world_id, "c": [r.command for r in ROUTES]},
        )


# --- the five routes, as data -------------------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Route:
    name: str
    command: str
    status: int
    steps: tuple[str, ...]
    make: Callable[[Scene, Env], tuple[str, dict[str, Any]]]
    #: the id the response echoes (a new row, or the target of a revoke)
    echo: str
    #: the kind of the declared write for the repeat/unlocked mutations
    business_pattern: str


def _grant_relationship(sc: Scene, e: Env) -> tuple[str, dict[str, Any]]:
    return f"{sc.w.base}/memberships/{e.membership}/character-relationships", {
        "character_id": str(e.other_character),
        "relationship_type_code": "viewer",
    }


def _change_relationship(sc: Scene, e: Env) -> tuple[str, dict[str, Any]]:
    return f"{sc.w.base}/character-relationships/{e.relationship}/change", {
        "new_relationship_type_id": str(e.co_controller)
    }


def _revoke_relationship(sc: Scene, e: Env) -> tuple[str, dict[str, Any]]:
    return f"{sc.w.base}/character-relationships/{e.relationship}/revoke", {}


def _create_grant(sc: Scene, e: Env) -> tuple[str, dict[str, Any]]:
    return f"{sc.w.base}/resource-grants", {
        "capability_code": "character.view_summary",
        "grantee_campaign_membership_id": str(e.membership),
        "character_id": str(e.other_character),
        "reason": "S5-E4",
    }


def _create_group_grant(sc: Scene, e: Env) -> tuple[str, dict[str, Any]]:
    return f"{sc.w.base}/resource-grants", {
        "capability_code": "character.view_summary",
        "grantee_access_group_id": str(e.group),
        "character_id": str(e.other_character),
    }


def _revoke_grant(sc: Scene, e: Env) -> tuple[str, dict[str, Any]]:
    return f"{sc.w.base}/resource-grants/{e.grant}/revoke", {}


ROUTES = (
    Route(
        "grant_relationship",
        "grant_character_relationship",
        201,
        ("insert_relationship", "audit_relationship_created"),
        _grant_relationship,
        "membership_character_relationship_id",
        INSERT_RELATIONSHIP,
    ),
    Route(
        "change_relationship",
        "change_character_relationship",
        201,
        ("revoke_old_relationship", "insert_changed_relationship", "audit_relationship_changed"),
        _change_relationship,
        "membership_character_relationship_id",
        INSERT_RELATIONSHIP,
    ),
    Route(
        "revoke_relationship",
        "revoke_character_relationship",
        200,
        ("revoke_relationship", "audit_relationship_revoked"),
        _revoke_relationship,
        "membership_character_relationship_id",
        UPDATE_RELATIONSHIP,
    ),
    Route(
        "create_grant",
        "create_resource_grant",
        201,
        ("insert_resource_grant", "audit_grant_created"),
        _create_grant,
        "resource_grant_id",
        INSERT_GRANT,
    ),
    Route(
        "revoke_grant",
        "revoke_resource_grant",
        200,
        ("revoke_resource_grant", "audit_grant_revoked"),
        _revoke_grant,
        "resource_grant_id",
        UPDATE_GRANT,
    ),
)
ROUTE = pytest.mark.parametrize("route", ROUTES, ids=[r.name for r in ROUTES])
GROUP_ROUTE = Route(
    "create_group_grant",
    "create_resource_grant",
    201,
    ("insert_resource_grant", "audit_grant_created"),
    _create_group_grant,
    "resource_grant_id",
    INSERT_GRANT,
)


def send(
    factory: Factory,
    sc: Scene,
    route: Route,
    e: Env,
    *,
    key: str | None = None,
    actor: uuid.UUID | None = None,
    path_body: tuple[str, dict[str, Any]] | None = None,
) -> Any:
    path, body = path_body or route.make(sc, e)
    headers = {"Idempotency-Key": key} if key else {}
    with factory(actor or sc.m.manager_user) as client:
        return client.post(path, json=body, headers=headers)


@dataclasses.dataclass
class Snap:
    relationships: tuple[Any, ...]
    grants: tuple[Any, ...]
    audits: tuple[Any, ...]
    receipt: tuple[Any, ...]


def snap(sc: Scene, key: str | None = None) -> Snap:
    with sc.w.engine.connect() as c:
        relationships = tuple(
            tuple(r)
            for r in c.execute(
                text(
                    "SELECT mcr.membership_character_relationship_id, mcr.revoked_at IS NOT NULL, "
                    "mcr.character_relationship_type_id, mcr.granted_by_membership_id "
                    "FROM security.membership_character_relationships mcr "
                    "JOIN security.campaign_memberships cm USING (campaign_membership_id) "
                    "WHERE cm.campaign_id = :c ORDER BY 1"
                ),
                {"c": sc.w.campaign_id},
            )
        )
        grants = tuple(
            tuple(r)
            for r in c.execute(
                text(
                    "SELECT resource_grant_id, revoked_at IS NOT NULL, effect, granted_by_membership_id "
                    "FROM security.resource_grants WHERE campaign_id = :c ORDER BY 1"
                ),
                {"c": sc.w.campaign_id},
            )
        )
        audits = tuple(
            tuple(r)
            for r in c.execute(
                text(
                    "SELECT command_name, table_name, record_id, previous_status, new_status, "
                    "changed_fields FROM audit.change_log WHERE world_id = :w "
                    "AND command_name = ANY(:names) ORDER BY change_log_id"
                ),
                {"w": sc.w.world_id, "names": [r.command for r in ROUTES]},
            )
        )
        receipt = (
            tuple(
                c.execute(
                    text(
                        "SELECT response_status_code, response_body, completed_at IS NOT NULL "
                        "FROM security.idempotent_requests WHERE campaign_id = :c AND idempotency_key = :k"
                    ),
                    {"c": sc.w.campaign_id, "k": key},
                ).one_or_none()
                or ()
            )
            if key
            else ()
        )
    return Snap(relationships, grants, audits, receipt)


def index(events: list[str], pattern: str, start: int = 0) -> int:
    matches = [i for i, x in enumerate(events) if i >= start and re.search(pattern, x)]
    assert matches, f"no statement matches {pattern!r}: {events}"
    return matches[0]


def writes_of(events: list[str]) -> list[str]:
    return [x for x in events if x.startswith(("INSERT", "UPDATE", "DELETE"))]


def business_writes(events: list[str]) -> list[str]:
    return [x for x in writes_of(events) if "idempotent_requests" not in x]


def audit_count(sc: Scene, route: Route) -> int:
    return sum(1 for a in snap(sc).audits if a[0] == route.command)


# --- success, the declared statement order, receipts -----------------------------------------------------------------


@KEYED
@ROUTE
def test_a_route_succeeds_writes_exactly_its_rows_and_one_audit_row_and_a_keyed_one_stores_its_receipt(
    route: Route, keyed: bool, s: Scene, env: Env, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route*: the documented status and echoed id; exactly the declared rows (a new relationship or grant, or the
    revoked old row), exactly one audit row naming the command, actor and the written record; a receipt (the response
    body, completed) only for a keyed request."""
    key = new_key() if keyed else None
    before = snap(s, key)
    response = send(pooled_factory, s, route, env, key=key)
    assert code(response) == route.status, response.text
    echoed = response.json()[route.echo]
    after = snap(s, key)
    assert len(after.audits) == len(before.audits) + 1
    command, _table, record, *_ = after.audits[-1]
    assert command == route.command and str(record) == echoed
    assert after.receipt == ((route.status, response.json(), True) if keyed else ())
    if route.name == "grant_relationship":
        assert len(after.relationships) == len(before.relationships) + 1
        assert after.relationships[-1][1:] == (False,) + after.relationships[-1][2:]
    if route.name == "change_relationship":
        assert (env.relationship, True) == after.relationships[0][:2] or any(
            r[0] == env.relationship and r[1] for r in after.relationships
        )
        assert len(after.relationships) == len(before.relationships) + 1
        [(_, _, _, previous, new, changed)] = [a for a in after.audits if a[0] == route.command]
        assert (previous, new) == ("portrayer", "co_controller")
        assert changed == {"previous_membership_character_relationship_id": str(env.relationship)}
    if route.name == "revoke_relationship":
        assert any(r[0] == env.relationship and r[1] for r in after.relationships)
    if route.name == "create_grant":
        assert len(after.grants) == len(before.grants) + 1
        [(_, _, _, _, _, changed)] = [a for a in after.audits if a[0] == route.command]
        assert changed["capability_code"] == "character.view_summary"
        assert changed["target_kind"] == "character_id" and "reason" not in changed
    if route.name == "revoke_grant":
        assert any(g[0] == env.grant and g[1] for g in after.grants)
        [(_, _, _, _, _, changed)] = [a for a in after.audits if a[0] == route.command]
        assert changed["target_id"] == str(env.character) and changed["effect"] == "allow"
    assert idle_in_transaction(s.w.engine) == 0


@KEYED
@pytest.mark.parametrize(
    "route", (*ROUTES, GROUP_ROUTE), ids=[r.name for r in (*ROUTES, GROUP_ROUTE)]
)
def test_the_route_runs_its_statements_in_the_declared_order(
    route: Route, keyed: bool, s: Scene, env: Env, pooled: Engine, pooled_factory: Factory
) -> None:
    """*sql*: [key lock, deferral, reservation,] [the group row,] the actor's role rows S, the memberships, the
    actor's account, [the target's account KS,] the campaign, the catalogue and target rows, [our receipt row,] the one
    final authority statement, and only after it the declared writes (business rows, the audit row, [the receipt]),
    COMMIT last, no row lock after the final statement."""
    key = new_key() if keyed else None
    with Recorder(pooled) as recorded:
        response = send(pooled_factory, s, route, env, key=key)
    assert code(response) == route.status, response.text
    ev = recorded.events
    final = index(ev, FINAL)
    chain: list[int] = [index(ev, ROLES_S)]
    if route is GROUP_ROUTE:
        # R01 S5-E4 correction SA-1 (order AO-1): the actor's role rows, then the group row, then the membership class
        chain += [index(ev, GROUP_U), index(ev, MEMBERSHIP_S)]
    chain.append(index(ev, ACCOUNT_S))
    creating = route.name in (
        "grant_relationship",
        "change_relationship",
        "create_grant",
        "create_group_grant",
    )
    chain.append(index(ev, CAMPAIGN_U if creating else CAMPAIGN_KS))
    if route.name in ("grant_relationship", "change_relationship"):
        chain += [index(ev, TYPE_U), index(ev, ENTITY_U), index(ev, CHARACTER_KS)]
    if route.name.startswith("create"):
        chain += [index(ev, CAPABILITY_U), index(ev, ENTITY_U), index(ev, CHARACTER_KS)]
    if route.name == "revoke_relationship":
        chain.append(index(ev, RELATIONSHIP_U))
    if route.name == "revoke_grant":
        chain.append(index(ev, GRANT_U))
    if route.name == "change_relationship":
        chain.append(index(ev, RELATIONSHIP_U))
    if keyed:
        chain.append(index(ev, RECEIPT_U))
    chain.append(final)
    chain += [index(ev, route.business_pattern), index(ev, AUDIT_INSERT)]
    if keyed:
        chain.append(index(ev, RECEIPT_UPDATE))
    assert chain == sorted(chain), (chain, ev)
    assert ev[-1] == "COMMIT"
    assert not [
        x for x in ev[final:] if re.search(r"\bFOR (KEY SHARE|SHARE|UPDATE|NO KEY UPDATE)\b", x)
    ]
    if keyed:
        assert (
            index(ev, r"SET CONSTRAINTS security\.idempotent_requests_campaign_id_fkey DEFERRED")
            < index(ev, KEY_LOCK)
            < index(ev, r"^INSERT INTO security\.idempotent_requests")
            < min(i for i, x in enumerate(ev) if re.search(ROLES_S, x))
        )
    else:
        assert not [
            x for x in ev if re.search(r"pg_advisory|idempotent_requests|SET CONSTRAINTS", x)
        ]
    # the actor's role rows are the first row lock for every route (a group grantee's group row follows them)
    first_lock = min(i for i, x in enumerate(ev) if re.search(r"FOR (KEY SHARE|SHARE|UPDATE)", x))
    assert first_lock == index(
        ev, ROLES_S
    )  # the role rows come first for every route, a group grantee's included
    assert len([x for x in ev if re.search(AUDIT_INSERT, x)]) == 1


@KEYED
@pytest.mark.parametrize("route_name", ("revoke_relationship", "revoke_grant"))
def test_revoking_an_already_revoked_row_writes_nothing_and_a_keyed_one_completes_its_receipt(
    route_name: str, keyed: bool, s: Scene, env: Env, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route* and *sql*: the legitimate no-op. No update, no audit row; the campaign is locked `FOR KEY SHARE`; a fresh
    keyed no-op still completes its receipt exactly once and replays it; one real revocation never leaves a second audit
    row."""
    route = next(r for r in ROUTES if r.name == route_name)
    assert code(send(pooled_factory, s, route, env, key=new_key())) == 200
    after_first = snap(s)
    key = new_key() if keyed else None
    with Recorder(pooled) as recorded:
        response = send(pooled_factory, s, route, env, key=key)
    assert code(response) == 200
    after = snap(s, key)
    assert after.audits == after_first.audits
    assert after.relationships == after_first.relationships and after.grants == after_first.grants
    assert business_writes(recorded.events) == []
    assert len([x for x in recorded.events if re.search(RECEIPT_UPDATE, x)]) == (1 if keyed else 0)
    assert any(re.search(CAMPAIGN_KS, x) for x in recorded.events)
    assert not any(re.search(CAMPAIGN_U, x) for x in recorded.events)
    if keyed:
        assert after.receipt == (200, response.json(), True)
        again = send(pooled_factory, s, route, env, key=key)
        assert code(again) == 200 and again.json() == response.json()
        assert snap(s, key).audits == after_first.audits


# --- refusals before the final statement ------------------------------------------------------------------------------


@KEYED
@ROUTE
def test_a_target_outside_the_campaign_is_the_unchanged_refusal_persists_nothing_and_the_key_is_reusable(
    route: Route, keyed: bool, s: Scene, env: Env, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route* and *sql*: a target that does not exist or belongs to another campaign is refused before the final
    statement, after the caller's own authority is judged by the dependency; nothing persists (the keyed reservation
    rolls back with the request) and the key is reusable by the corrected request."""
    with s.w.engine.begin() as c:
        timeline = c.execute(
            text("SELECT timeline_id FROM campaign.campaigns WHERE campaign_id = :c"),
            {"c": s.w.campaign_id},
        ).scalar_one()
        other_campaign = make_campaign(c, timeline, lifecycle_status_code="pending")
        foreign_membership = make_campaign_membership(
            c, other_campaign, make_user(c, "S5E4 Foreign")
        )
    key = new_key() if keyed else None
    foreign_env = dataclasses.replace(env, membership=foreign_membership)
    path, body = route.make(s, foreign_env)
    if route.name in ("change_relationship", "revoke_relationship"):
        path = path.replace(str(env.relationship), str(uuid.uuid4()))
    if route.name == "revoke_grant":
        path = path.replace(str(env.grant), str(uuid.uuid4()))
    before = snap(s, key)
    with Recorder(pooled) as recorded:
        response = send(pooled_factory, s, route, env, key=key, path_body=(path, body))
    assert code(response) in (404, 409), response.text
    assert snap(s, key) == before and idle_in_transaction(s.w.engine) == 0
    assert not any(FINAL_RE.search(x) for x in recorded.events), (
        "refused before the final statement"
    )
    assert business_writes(recorded.events) == []
    assert code(send(pooled_factory, s, route, env, key=key)) == route.status


@ROUTE
def test_a_caller_without_access_manage_is_refused_before_anything_is_looked_up(
    route: Route, s: Scene, env: Env, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route*: precedence is unchanged. A player learns nothing: the same 403 or 404 for a real target as for a missing
    one, and nothing persists."""
    before = snap(s)
    real = send(pooled_factory, s, route, env, actor=env.user)
    path, body = route.make(s, env)
    for known in (env.relationship, env.grant):
        path = path.replace(str(known), str(uuid.uuid4()))
    missing = send(pooled_factory, s, route, env, actor=env.user, path_body=(path, body))
    assert code(real) == code(missing) and code(real) in (403, 404), (real.text, missing.text)
    assert error_of(real) == error_of(missing)
    assert snap(s) == before


# --- shapes the INSERT's constraint refused ---------------------------------------------------------------------------------


@KEYED
@pytest.mark.parametrize(
    "case",
    (
        "no_grantee",
        "two_grantees",
        "no_target",
        "two_targets",
        "target_is_not_a_character",
    ),
)
def test_a_grant_shape_the_constraint_refused_is_still_a_400_refused_before_the_final_statement(
    case: str, keyed: bool, s: Scene, env: Env, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route* and *sql*: the exactly-one grantee and target `CHECK`s and the child-row foreign key refused these as a 400
    after the INSERT. A declared INSERT cannot be given a foreign key whose lock never returned the row, so the plan
    refuses them **before** `finalize` with the same public 400 `validation_failed`; nothing persists; the constraints
    stay the backstop."""
    body: dict[str, Any] = {
        "capability_code": "character.view_summary",
        "grantee_campaign_membership_id": str(env.membership),
        "character_id": str(env.other_character),
    }
    if case == "no_grantee":
        del body["grantee_campaign_membership_id"]
    if case == "two_grantees":
        body["grantee_access_group_id"] = str(env.group)
    if case == "no_target":
        del body["character_id"]
    if case == "two_targets":
        body["quest_id"] = str(uuid.uuid4())  # only the first target is validated, as before
    if case == "target_is_not_a_character":
        # an entity that exists in the world and is active but is not a character: a quest's entity id is refused by
        # the character child table's foreign key
        with s.w.engine.begin() as c:
            item = c.execute(
                text(
                    "SELECT entity_id FROM core.entities e JOIN core.entity_types et USING (entity_type_id) "
                    "WHERE e.world_id = :w AND et.code NOT IN ('character', 'npc', 'player_character') "
                    "LIMIT 1"
                ),
                {"w": s.w.world_id},
            ).scalar_one_or_none()
        if item is None:
            pytest.skip("the world has no non-character entity to name")
        body["character_id"] = str(item)
    key = new_key() if keyed else None
    before = snap(s, key)
    with Recorder(pooled) as recorded:
        response = send(
            pooled_factory,
            s,
            ROUTES[3],
            env,
            key=key,
            path_body=(f"{s.w.base}/resource-grants", body),
        )
    assert code(response) == 400 and error_of(response) == "validation_failed", response.text
    assert snap(s, key) == before and idle_in_transaction(s.w.engine) == 0
    assert not any(FINAL_RE.search(x) for x in recorded.events)
    assert business_writes(recorded.events) == []


# --- replay, key reuse, authority --------------------------------------------------------------------------------------------


@ROUTE
def test_an_authorized_replay_returns_the_stored_receipt_without_a_lock_or_a_write(
    route: Route, s: Scene, env: Env, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route* and *sql*: the stored body and status, no row lock, no write, and the final authority statement last
    before COMMIT (the receipt does not leave before the check). The replay does not re-run the command."""
    key = new_key()
    first = send(pooled_factory, s, route, env, key=key)
    assert code(first) == route.status
    stored = snap(s, key)
    with Recorder(pooled) as recorded:
        replay = send(pooled_factory, s, route, env, key=key)
    assert code(replay) == route.status and replay.json() == first.json()
    assert snap(s, key) == stored
    finals = [x for x in recorded.events if FINAL_RE.search(x)]
    assert len(finals) == 1 and recorded.events[-2:] == [finals[0], "COMMIT"]
    assert not [
        x for x in recorded.events if re.search(r"FOR (KEY SHARE|SHARE|UPDATE|NO KEY UPDATE)", x)
    ]
    assert all(
        "idempotent_requests" in x and "ON CONFLICT" in x for x in writes_of(recorded.events)
    )


@ROUTE
def test_a_replay_after_authority_loss_is_refused_and_returns_nothing_from_the_receipt(
    route: Route, s: Scene, env: Env, pooled: Engine, pooled_factory: Factory
) -> None:
    key = new_key()
    first = send(pooled_factory, s, route, env, key=key)
    assert code(first) == route.status
    stored = snap(s, key)
    revoke_role(s.w.engine, s.m.manager_role)
    again = send(pooled_factory, s, route, env, key=key)
    assert code(again) in (403, 404), again.text
    for value in first.json().values():
        assert str(value) not in again.text
    assert snap(s, key) == stored


@ROUTE
def test_a_reused_key_with_another_target_is_the_same_conflict_and_changes_nothing(
    route: Route, s: Scene, env: Env, pooled: Engine, pooled_factory: Factory
) -> None:
    key = new_key()
    assert code(send(pooled_factory, s, route, env, key=key)) == route.status
    other = build_env(s, "S5E4 Second")
    stored = snap(s, key)
    response = send(pooled_factory, s, route, other, key=key)
    assert code(response) == 409 and error_of(response) == "conflict", response.text
    assert snap(s, key) == stored


@KEYED
@ROUTE
def test_a_role_that_lapses_before_the_final_statement_refuses_the_route_and_rolls_everything_back(
    route: Route, keyed: bool, s: Scene, env: Env, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route* (race, expiry at the authorization boundary): the manager's role is valid for every early check and has
    lapsed (a DATABASE condition, polled) when the final authority statement runs, every lock already held. Nothing
    persists; the key is reusable."""
    from tests.r01_s5d_support import run_with_role_lapsing_before_final

    key = new_key() if keyed else None
    before = snap(s, key)
    response = run_with_role_lapsing_before_final(
        s.w.engine,
        pooled,
        s.m.manager_role,
        lambda: send(pooled_factory, s, route, env, key=key),
        first_gate=KEY_LOCK if keyed else r"FROM security\.membership_roles WHERE",
    )
    assert code(response) in (403, 404), response.text
    assert snap(s, key) == before and idle_in_transaction(s.w.engine) == 0
    with s.w.engine.begin() as c:
        c.execute(
            text(
                "UPDATE security.membership_roles SET expires_at = NULL WHERE membership_role_id = :r"
            ),
            {"r": s.m.manager_role},
        )
    assert code(send(pooled_factory, s, route, env, key=key)) == route.status


@ROUTE
def test_a_role_revoked_before_the_request_is_refused_early_and_writes_nothing(
    route: Route, s: Scene, env: Env, pooled: Engine, pooled_factory: Factory
) -> None:
    revoke_role(s.w.engine, s.m.manager_role)
    before = snap(s)
    response = send(pooled_factory, s, route, env)
    assert code(response) in (403, 404), response.text
    assert snap(s) == before


# --- the plan's obligations ---------------------------------------------------------------------------------------------------


@KEYED
@ROUTE
def test_a_handler_that_forgets_to_finalize_is_a_sanitized_500_that_persists_nothing(
    route: Route,
    keyed: bool,
    s: Scene,
    env: Env,
    pooled: Engine,
    pooled_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = new_key() if keyed else None
    before = snap(s, key)
    monkeypatch.setattr(AuthorizationPlan, "finalize", lambda self, connection: None)
    response = send(pooled_factory, s, route, env, key=key)
    monkeypatch.undo()
    assert code(response) == 500 and error_of(response) == "internal_error"
    assert snap(s, key) == before and idle_in_transaction(s.w.engine) == 0
    assert code(send(pooled_factory, s, route, env, key=key)) == route.status


def _wrap(
    monkeypatch: pytest.MonkeyPatch,
    *,
    skip: tuple[str, ...] = (),
    repeat: tuple[str, ...] = (),
    after: dict[str, tuple[Any, dict[str, Any]]] | None = None,
) -> None:
    """Test-side mutation of `AuthorizationPlan.execute`: omit a step, run it twice, or run another declared step
    (with its own parameters) right after one."""
    original = AuthorizationPlan.execute

    def wrapper(self: AuthorizationPlan, connection: Any, step: Any, params: Any) -> Any:
        if step.name in skip:
            from dnd_ai.domain.authorization import StepOutcome

            return StepOutcome(step=step.name, keys=())
        outcome = original(self, connection, step, params)
        if step.name in repeat:
            original(self, connection, step, params)
        if after and step.name in after:
            extra_step, extra_params = after[step.name]
            original(self, connection, extra_step, extra_params)
        return outcome

    monkeypatch.setattr(AuthorizationPlan, "execute", wrapper)


def _skippable_steps() -> list[tuple[str, str]]:
    return [(r.name, step) for r in ROUTES for step in r.steps]


@KEYED
@pytest.mark.parametrize(
    ("route_name", "step"), (*_skippable_steps(), ("grant_relationship", "receipt"))
)
def test_an_omitted_required_write_is_refused_at_commit_and_rolls_everything_back(
    route_name: str,
    step: str,
    keyed: bool,
    s: Scene,
    env: Env,
    pooled: Engine,
    pooled_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """*mutation (test-side)*: every business write, the audit row and (keyed) the receipt is owed by the locked state.
    A request that never runs one cannot commit: the guard refuses the incomplete plan (sanitized 500), everything rolls
    back, the key is reusable, the connection is clean."""
    if step == "receipt" and not keyed:
        pytest.skip("an unkeyed request has no receipt")
    route = next(r for r in ROUTES if r.name == route_name)
    key = new_key() if keyed else None
    before = snap(s, key)
    _wrap(monkeypatch, skip=(step,))
    response = send(pooled_factory, s, route, env, key=key)
    monkeypatch.undo()
    assert code(response) == 500 and error_of(response) == "internal_error", (step, response.text)
    assert snap(s, key) == before and idle_in_transaction(s.w.engine) == 0, step
    assert code(send(pooled_factory, s, route, env, key=key)) == route.status


@KEYED
@pytest.mark.parametrize(("route_name", "step"), _skippable_steps())
def test_a_repeated_write_is_refused_and_the_whole_request_rolls_back(
    route_name: str,
    step: str,
    keyed: bool,
    s: Scene,
    env: Env,
    pooled: Engine,
    pooled_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """*mutation (test-side)*: a second insert, a second update of a row or a second audit row is a forbidden extra
    write: the second attempt is refused before the driver and nothing persists."""
    route = next(r for r in ROUTES if r.name == route_name)
    key = new_key() if keyed else None
    before = snap(s, key)
    _wrap(monkeypatch, repeat=(step,))
    response = send(pooled_factory, s, route, env, key=key)
    monkeypatch.undo()
    assert code(response) == 500, (step, response.text)
    assert snap(s, key) == before and idle_in_transaction(s.w.engine) == 0


@pytest.mark.parametrize(
    "route_name", ("revoke_relationship", "revoke_grant", "change_relationship")
)
def test_a_write_to_a_row_the_request_did_not_lock_is_refused_and_nothing_persists(
    route_name: str,
    s: Scene,
    env: Env,
    pooled: Engine,
    pooled_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """*mutation (test-side)*: right after the genuine write the request tries the same kind of write against another
    row it never locked: refused (it is not in the lock evidence), the whole request rolls back, and the other row
    stays open."""
    from dnd_ai.commands import access_grant_plans as plans

    other = build_env(s, "S5E4 Unlocked")
    route = next(r for r in ROUTES if r.name == route_name)
    declared = {item.name: item for item in plans.CHANGE_RELATIONSHIP_DECLARATIONS.unkeyed.steps}
    declared |= {item.name: item for item in plans.REVOKE_RELATIONSHIP_DECLARATIONS.unkeyed.steps}
    declared |= {item.name: item for item in plans.REVOKE_GRANT_DECLARATIONS.unkeyed.steps}
    first, victim_step, victim = {
        "revoke_relationship": ("revoke_relationship", "revoke_relationship", other.relationship),
        "revoke_grant": ("revoke_resource_grant", "revoke_resource_grant", other.grant),
        "change_relationship": (
            "revoke_old_relationship",
            "revoke_old_relationship",
            other.relationship,
        ),
    }[route_name]
    _wrap(monkeypatch, after={first: (declared[victim_step], {"target": victim})})
    before = snap(s)
    response = send(pooled_factory, s, route, env)
    monkeypatch.undo()
    assert code(response) == 500, response.text
    assert snap(s) == before and idle_in_transaction(s.w.engine) == 0


def _fail_step(monkeypatch: pytest.MonkeyPatch, step_name: str) -> None:
    """Make the declared step raise when the plan is asked to run it (a driver-level failure at that point)."""
    original = AuthorizationPlan.execute

    def wrapper(self: AuthorizationPlan, connection: Any, step: Any, params: Any) -> Any:
        if step.name == step_name:
            raise RuntimeError("injected failure")
        return original(self, connection, step, params)

    monkeypatch.setattr(AuthorizationPlan, "execute", wrapper)


@pytest.mark.parametrize("failing", ("audit", "receipt"))
@ROUTE
def test_a_failure_at_the_audit_or_receipt_step_rolls_back_the_business_write_the_audit_row_and_the_receipt(
    route: Route,
    failing: str,
    s: Scene,
    env: Env,
    pooled: Engine,
    pooled_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """*route* (complete rollback): the business rows (and, for the receipt case, the audit row too) were written when the
    last declared step fails; the request answers a sanitized 500 and nothing persists: no relationship or grant row change,
    no audit row, no receipt; the key is reusable afterwards. (The receipt step exists only for a keyed request.)"""
    key = new_key()
    before = snap(s, key)
    _fail_step(monkeypatch, route.steps[-1] if failing == "audit" else "receipt")
    response = send(pooled_factory, s, route, env, key=key)
    monkeypatch.undo()
    assert code(response) == 500 and error_of(response) == "internal_error", response.text
    assert snap(s, key) == before and idle_in_transaction(s.w.engine) == 0
    assert code(send(pooled_factory, s, route, env, key=key)) == route.status


def test_a_one_connection_pool_serves_every_route_noops_refusals_and_a_replay_without_leaking_state(
    s: Scene, env: Env, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route*: one pooled connection, reused for all five routes, a no-op, a 404, a 403 and a replay in turn. Each
    answers as it would alone, the connection is never left in a transaction, and nothing one request held reaches the
    next."""
    key = new_key()
    for route in ROUTES:
        assert (
            code(send(pooled_factory, s, route, env, key=key if route is ROUTES[2] else None))
            == route.status
        )
        assert idle_in_transaction(s.w.engine) == 0
    assert code(send(pooled_factory, s, ROUTES[2], env)) == 200  # the no-op
    assert code(send(pooled_factory, s, ROUTES[2], env, actor=env.user)) in (403, 404)
    assert code(send(pooled_factory, s, ROUTES[2], env, key=key)) == 200  # the replay
    assert (
        code(
            send(
                pooled_factory,
                s,
                ROUTES[2],
                env,
                path_body=(f"{s.w.base}/character-relationships/{uuid.uuid4()}/revoke", {}),
            )
        )
        == 404
    )
    assert idle_in_transaction(s.w.engine) == 0
    for route in ROUTES:
        # the change closed the relationship the revoke then found already closed (the no-op: no audit row)
        assert audit_count(s, route) == (0 if route is ROUTES[2] else 1)


def test_the_declarations_hold_against_the_live_catalogue(w: World) -> None:
    """The S1 catalogue helper checks every assumption a declaration makes about the database (triggers pinned by
    function-source hash, unique waits, FK match type and order, defaults, CHECK expressions). An empty list is the only
    passing answer."""
    from dnd_ai.commands import access_grant_plans as plans
    from tests.r01_pre_write_catalogue import check_declaration

    problems: list[str] = []
    with w.engine.connect() as connection:
        for name in (
            "GRANT_RELATIONSHIP_DECLARATIONS",
            "CHANGE_RELATIONSHIP_DECLARATIONS",
            "REVOKE_RELATIONSHIP_DECLARATIONS",
            "CREATE_GRANT_DECLARATIONS",
            "REVOKE_GRANT_DECLARATIONS",
        ):
            declarations = getattr(plans, name)
            for kind, decl in (
                ("reserved", declarations.reserved),
                ("unkeyed", declarations.unkeyed),
            ):
                assert decl is not None
                problems += [f"{name} {kind}: {x}" for x in check_declaration(connection, decl)]
    assert problems == [], chr(10).join(problems)


# --- time: a relationship that expires while the request waits ----------------------------------------------------------------------


def test_a_relationship_that_expires_while_the_change_waits_is_refused_and_nothing_persists(
    s: Scene, env: Env, pooled: Engine, pooled_factory: Factory
) -> None:
    """*race* (expiry across a lock wait): the relationship is valid at the start of the request and has expired (a
    DATABASE condition) when the eligibility read runs after the last lock wait. The command judged `expires_at` at the
    transaction start; the plan judges it at a fresh `clock_timestamp()` after the waits (DEF-013 style), so the change
    is refused with the unchanged 409 `conflict` and nothing persists."""
    from tests.http_race_support import StatementGate, run_in_thread

    with s.w.engine.begin() as c:
        c.execute(
            text(
                "UPDATE security.membership_character_relationships SET expires_at = now() + interval '1 hour' "
                "WHERE membership_character_relationship_id = :r"
            ),
            {"r": env.relationship},
        )
    before = snap(s)
    route = ROUTES[1]
    with StatementGate(pooled, FINAL) as gate:
        request = run_in_thread("change", lambda: send(pooled_factory, s, route, env))
        gate.wait_reached()
        gate.release()
        response = request.wait("the change finishes")
    assert code(response) == route.status  # not expired at the read: it commits (the control)
    assert snap(s) != before
    # the same request on a relationship that expires between the early checks and the eligibility read
    other = build_env(s, "S5E4 Expiring")
    with s.w.engine.begin() as c:
        c.execute(
            text(
                "UPDATE security.membership_character_relationships SET expires_at = now() + interval '1 second' "
                "WHERE membership_character_relationship_id = :r"
            ),
            {"r": other.relationship},
        )
    before = snap(s)
    with StatementGate(pooled, RELATIONSHIP_U) as gate:
        request = run_in_thread("change", lambda: send(pooled_factory, s, route, other))
        gate.wait_reached()
        import time

        time.sleep(1.2)  # the relationship expires while the request is parked before its row lock
        gate.release()
        response = request.wait("the change finishes")
    assert code(response) == 409 and error_of(response) == "conflict", response.text
    assert snap(s) == before and idle_in_transaction(s.w.engine) == 0


# --- unique waits ----------------------------------------------------------------------------------------------------------------


def test_a_competing_active_relationship_of_the_same_type_is_a_unique_wait(
    s: Scene, env: Env, pooled: Engine, pooled_factory: Factory
) -> None:
    """*race*, `ux_membership_character_relationships_active_type` on the grant's INSERT: a competitor inserting the
    same (membership, character, type) while the request is parked at its audit insert (its row inserted, uncommitted)
    queues behind *the request* on the index key; when the request commits the competitor fails on the unique index
    (409-class), never a second active row."""
    from sqlalchemy.exc import IntegrityError

    from tests.database.test_r01_s5e2_membership_routes import waiting_statement
    from tests.http_race_support import StatementGate, run_in_thread
    from tests.lock_race_support import LockRace

    viewer = s_type(s, "viewer")

    def competitor(c: Any) -> Any:
        return make_membership_character_relationship(
            c, env.membership, env.other_character, viewer
        )

    with StatementGate(pooled, AUDIT_INSERT) as gate:
        request = run_in_thread("grant", lambda: send(pooled_factory, s, ROUTES[0], env))
        gate.wait_reached()
        assert gate.pid is not None
        with LockRace(s.w.engine) as race:
            queued = race.start("insert", competitor)
            race.wait_blocked_by(gate, expected=1)
            assert re.search(r"INSERT INTO security\.", waiting_statement(s.w.engine, gate.pid))
            gate.release()
            response = request.wait("the grant finishes")
            race.join_all()
    assert code(response) == 201
    assert isinstance(queued.error, IntegrityError), queued.error


def test_a_competing_active_grant_of_the_same_key_is_a_unique_wait(
    s: Scene, env: Env, pooled: Engine, pooled_factory: Factory
) -> None:
    """*race*, `ux_resource_grants_active` on the create's INSERT: the same competitor shape for a resource grant."""
    from sqlalchemy.exc import IntegrityError

    from tests.database.test_r01_s5e2_membership_routes import waiting_statement
    from tests.http_race_support import StatementGate, run_in_thread
    from tests.lock_race_support import LockRace

    def competitor(c: Any) -> Any:
        return make_resource_grant(
            c,
            s.w.campaign_id,
            env.capability,
            grantee_campaign_membership_id=env.membership,
            character_id=env.other_character,
        )

    with StatementGate(pooled, AUDIT_INSERT) as gate:
        request = run_in_thread("create", lambda: send(pooled_factory, s, ROUTES[3], env))
        gate.wait_reached()
        assert gate.pid is not None
        with LockRace(s.w.engine) as race:
            queued = race.start("insert", competitor)
            race.wait_blocked_by(gate, expected=1)
            assert re.search(r"INSERT INTO security\.", waiting_statement(s.w.engine, gate.pid))
            gate.release()
            response = request.wait("the create finishes")
            race.join_all()
    assert code(response) == 201
    assert isinstance(queued.error, IntegrityError), queued.error


def s_type(sc: Scene, type_code: str) -> uuid.UUID:
    with sc.w.engine.connect() as c:
        return c.execute(
            text(
                "SELECT character_relationship_type_id FROM security.character_relationship_types "
                "WHERE code = :c"
            ),
            {"c": type_code},
        ).scalar_one()


def _competing_insert(sc: Scene, e: Env, index_name: str) -> Callable[[Any], Any]:
    def run(c: Any) -> Any:
        if index_name == "relationship":
            return make_membership_character_relationship(c, e.membership, e.character, e.portrayer)
        return make_resource_grant(
            c,
            sc.w.campaign_id,
            e.capability,
            grantee_campaign_membership_id=e.membership,
            character_id=e.character,
        )

    return run


@pytest.mark.parametrize("index_name", ("relationship", "grant"))
def test_an_update_leaving_a_partial_unique_index_never_waits_for_a_competing_insert(
    index_name: str, s: Scene, env: Env, pooled: Engine, pooled_factory: Factory
) -> None:
    """*race*, `ux_membership_character_relationships_active_type` and `ux_resource_grants_active`: each closing `UPDATE`
    (a revoke, or the change's closing of the old row) leaves its partial index, so it takes no unique wait. A competitor
    inserting the same key while the request is parked at its audit insert (every update done, uncommitted) queues behind
    *the request* (blocked by its pid); the request finishes while the competitor is still queued, then the competitor
    completes (the key is free)."""
    from tests.database.test_r01_s5e2_membership_routes import waiting_statement
    from tests.http_race_support import StatementGate, run_in_thread
    from tests.lock_race_support import LockRace

    route = ROUTES[2] if index_name == "relationship" else ROUTES[4]
    with StatementGate(pooled, AUDIT_INSERT) as gate:
        request = run_in_thread("revoke", lambda: send(pooled_factory, s, route, env))
        gate.wait_reached()
        assert gate.pid is not None
        with LockRace(s.w.engine) as race:
            competitor = race.start("insert", _competing_insert(s, env, index_name))
            race.wait_blocked_by(gate, expected=1)
            assert re.search(r"INSERT INTO security\.", waiting_statement(s.w.engine, gate.pid))
            gate.release()
            response = request.wait("the revoke finishes while the competitor is queued")
            race.join_all()
    assert code(response) == 200 and competitor.error is None


# --- the group grantee and the other kinds of target -----------------------------------------------------------------------------------------


def test_a_group_grantee_is_locked_after_the_actor_role_rows_and_a_deactivated_group_is_the_unchanged_409(
    s: Scene, env: Env, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route* and *sql*: for a group grantee the first row lock is the actor's role rows `FOR SHARE`, then the group `FOR UPDATE`,
    then the actor's membership (AO-1, correction SA-1: a transaction holding a group row never waits for a role row); no
    membership of the grantee to lock; the target's account is not locked; a deactivated group is refused before `finalize` with the unchanged 409
    and nothing persists."""
    with Recorder(pooled) as recorded:
        response = send(pooled_factory, s, GROUP_ROUTE, env)
    assert code(response) == 201, response.text
    ev = recorded.events
    assert index(ev, ROLES_S) < index(ev, GROUP_U) < index(ev, MEMBERSHIP_S)
    assert not any(re.search(ACCOUNT_KS, x) for x in ev), "a group has no account to lock"
    assert not any(re.search(MEMBERSHIP_U, x) for x in ev), "no grantee membership to lock"
    with s.w.engine.begin() as c:
        c.execute(
            text(
                "UPDATE security.access_groups SET lifecycle_status_id = (SELECT lifecycle_status_id "
                "FROM core.lifecycle_statuses WHERE code = 'archived') WHERE access_group_id = :g"
            ),
            {"g": env.group},
        )
    before = snap(s)
    again = send(pooled_factory, s, GROUP_ROUTE, env)
    assert code(again) == 409, again.text
    assert snap(s) == before


@pytest.mark.parametrize(
    "kind",
    ("character_id", "entity_id_deny", "session_id", "quest_id", "knowledge_item_id", "event_id"),
)
def test_each_target_kind_takes_its_own_locks_and_creates_one_grant(
    kind: str, s: Scene, env: Env, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route* and *sql*: the entity row `FOR UPDATE` and the kind's child row `FOR KEY SHARE` (or the session row
    `FOR UPDATE`) precede the final statement; one grant is written. Kinds with no fixture in this world are skipped."""
    import random  # noqa: PLC0415

    from tests.factories import (  # noqa: PLC0415
        make_event,
        make_knowledge_item,
        make_quest,
        make_session,
    )

    body: dict[str, Any] = {
        "grantee_campaign_membership_id": str(env.membership),
        "capability_code": "campaign.view",
    }
    with s.w.engine.begin() as c:
        if kind == "character_id":
            body |= {
                "character_id": str(env.other_character),
                "capability_code": "character.view_summary",
            }
        elif kind == "entity_id_deny":
            body |= {"entity_id": str(env.other_character), "effect": "deny"}
        elif kind == "session_id":
            body["session_id"] = str(make_session(c, s.w.campaign_id, random.randint(1000, 10**6)))
        elif kind == "quest_id":
            body["quest_id"] = str(make_quest(c, s.w.world_id))
        elif kind == "knowledge_item_id":
            body["knowledge_item_id"] = str(make_knowledge_item(c, s.w.world_id))
        else:
            timeline, world_time = c.execute(
                text(
                    "SELECT c.timeline_id, (SELECT world_time_id FROM core.world_times WHERE world_id = :w "
                    "ORDER BY sort_key LIMIT 1) FROM campaign.campaigns c WHERE c.campaign_id = :c"
                ),
                {"w": s.w.world_id, "c": s.w.campaign_id},
            ).one()
            if world_time is None:
                pytest.skip("the world has no world time to date an event")
            body["event_id"] = str(
                make_event(c, s.w.world_id, timeline, world_time, campaign_id=s.w.campaign_id)
            )
    with Recorder(pooled) as recorded:
        response = send(
            pooled_factory,
            s,
            ROUTES[3],
            env,
            path_body=(f"{s.w.base}/resource-grants", body),
        )
    assert code(response) == 201, response.text
    ev = recorded.events
    final = index(ev, FINAL)
    if kind == "session_id":
        assert index(ev, r"FROM campaign\.sessions WHERE .* FOR UPDATE$") < final
    else:
        assert index(ev, ENTITY_U) < final
    assert len([x for x in ev if re.search(INSERT_GRANT, x)]) == 1


# --- the lock modes held at the final statement --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "route_name",
    (
        "grant_relationship",
        "change_relationship",
        "create_grant",
        "create_group_grant",
        "revoke_relationship",
        "revoke_grant",
    ),
)
def test_each_route_holds_its_rows_at_the_modes_it_needs_at_the_final_statement(
    route_name: str, s: Scene, env: Env, pool: Any
) -> None:
    """*race* (mode probes through `NOWAIT`, the S5-E2 `held_mode`): at the final authority statement the route holds the
    actor's membership `FOR SHARE` and account `FOR SHARE`, the target membership `FOR UPDATE` and its account `FOR KEY
    SHARE` (the creating routes with a membership grantee, and the change), the campaign `FOR UPDATE` (creating) or `FOR KEY
    SHARE` (revoking), the group `FOR UPDATE` (a group grantee), and the row it will close `FOR UPDATE`; and nothing stronger
    than it needs on the actor."""
    from tests.database.test_r01_s5e2_lock_order import (
        CAMPAIGN_ROW,
        MEMBERSHIP_ROW,
        park_and_probe,
        post,
    )

    route = (
        GROUP_ROUTE
        if route_name == "create_group_grant"
        else next(r for r in ROUTES if r.name == route_name)
    )
    path, body = route.make(s, env)
    actor = rows_membership_of(s, s.w.owner)
    actor_user = s.w.owner
    probes: dict[str, tuple[tuple[str, str], uuid.UUID]] = {
        "actor_membership": (MEMBERSHIP_ROW, actor),
        "actor_account": (("security.users", "user_id"), actor_user),
        "campaign": (CAMPAIGN_ROW, s.w.campaign_id),
    }
    if route_name in ("grant_relationship", "change_relationship", "create_grant"):
        probes["target_membership"] = (MEMBERSHIP_ROW, env.membership)
        probes["target_account"] = (("security.users", "user_id"), env.user)
    if route_name == "create_group_grant":
        probes["group"] = (("security.access_groups", "access_group_id"), env.group)
    if route_name in ("revoke_relationship", "change_relationship"):
        probes["relationship"] = (
            ("security.membership_character_relationships", "membership_character_relationship_id"),
            env.relationship,
        )
    if route_name == "revoke_grant":
        probes["grant"] = (("security.resource_grants", "resource_grant_id"), env.grant)
    response, modes = park_and_probe(
        s.w,
        pool,
        gate_pattern=FINAL,
        request=lambda: post(pool, s.w.owner, path, body),
        probes=probes,
    )
    assert code(response) == route.status, response.text
    assert modes["actor_membership"] == "S", modes
    assert modes["actor_account"] == "S", modes
    expected = {
        "target_membership": "U",
        "target_account": "KS",
        "group": "U",
        "relationship": "U",
        "grant": "U",
    }
    for label, mode in expected.items():
        if label in modes:
            assert modes[label] == mode, (label, modes)
    creating = route_name not in ("revoke_relationship", "revoke_grant")
    assert modes["campaign"] == ("U" if creating else "KS"), modes


def rows_membership_of(sc: Scene, user: uuid.UUID) -> uuid.UUID:
    with sc.w.engine.connect() as c:
        return c.execute(
            text(
                "SELECT campaign_membership_id FROM security.campaign_memberships "
                "WHERE campaign_id = :c AND user_id = :u"
            ),
            {"c": sc.w.campaign_id, "u": user},
        ).scalar_one()


# fixtures used by name in the mode test above
from tests.database.test_r01_s5e2_lock_order import pool  # noqa: E402, F401
