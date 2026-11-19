# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""R01 S5-E5: the six access-group routes as keyed-optional pre-write plans, over real HTTP and real connections.

The six routes (`dnd_ai.commands.access_group_plans`) take the actor's role rows `FOR SHARE`, then (update, deactivate,
reactivate, add) the group `FOR UPDATE` (AO-1), the memberships and accounts, the campaign `FOR KEY SHARE` (CA-1: create and
reactivate too), the dependents / links, [the receipt], judge authority at `plan.finalize` and only then write through declared
steps. Evidence classes (labelled in each docstring), as in the S5-E4 module:

- **route**: a real HTTP request through the guard on a one-connection pool.
- **sql**: the recorded statement stream of such a request (`Recorder`).
- **probe**: the request is parked at its final authority statement and the held row locks are read with `NOWAIT` probes
  from an independent connection.
- **mutation (test-side)**: `AuthorizationPlan.execute` / `.lock` is wrapped to omit, repeat or misdirect a call, to show that
  the declared obligations (and H-1) refuse it. Nothing production-side is changed.

The behaviour of every refusal (error classes, precedence, response bodies) is held by the pre-existing
`test_api_access_groups.py`, which runs unchanged against the migrated routes; this module adds what only a pre-write plan has,
and the contract of the bulk add (all-or-nothing) and of the deactivation cascade.
"""

import dataclasses
import datetime
import re
import time
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from dnd_ai.api import access_groups as api_module
from dnd_ai.commands import access_group_plans as plans
from dnd_ai.commands.character_public_profile import (
    release_character_public_profile,
    save_character_public_profile_draft,
)
from dnd_ai.domain.authorization import AuthorizationPlan, StepOutcome
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
from tests.database.test_r01_s5e2_lock_order import (  # noqa: F401 - fixture by name
    MEMBERSHIP_ROW,
    ROLE_ROW,
    Pool,
    held_mode,
    pool,
    post,
    rows,
)
from tests.database.test_r01_s5e2_membership_routes import (  # noqa: F401 - fixtures used by name
    Scene,
    m,
    pooled2,
    pooled2_factory,
    s,
)
from tests.database.test_r01_s5e4_access_grants import (
    ACCOUNT_KS,
    ACCOUNT_S,
    AUDIT_INSERT,
    CAMPAIGN_KS,
    CAMPAIGN_U,
    GROUP_U,
    KEY_LOCK,
    MEMBERSHIP_S,
    RECEIPT_U,
    RECEIPT_UPDATE,
    ROLES_S,
    business_writes,
    index,
    writes_of,
)
from tests.factories import (
    make_access_group,
    make_access_group_membership,
    make_campaign,
    make_campaign_membership,
    make_character,
    make_membership_role,
    make_resource_grant,
    make_user,
)
from tests.http_race_support import StatementGate, new_key, run_in_thread
from tests.r01_s5d_support import revoke_role
from tests.r01_support import fixture_plan

pytestmark = pytest.mark.database

Factory = Callable[[uuid.UUID], TestClient]
KEYED = pytest.mark.parametrize("keyed", (True, False), ids=("keyed", "unkeyed"))

GROUP_ROW = ("security.access_groups", "access_group_id")
USER_ROW = ("security.users", "user_id")
CAMPAIGN_ROW = ("campaign.campaigns", "campaign_id")
LINK_ROW = ("security.access_group_memberships", "access_group_membership_id")
MEMBER_NKU = r"FROM security\.campaign_memberships WHERE .* FOR NO KEY UPDATE$"
LINKS_U = r"FROM security\.access_group_memberships WHERE .* FOR UPDATE$"
GRANTS_U = r"FROM security\.resource_grants WHERE .* FOR UPDATE$"
REVELATIONS_U = r"FROM security\.character_revelations WHERE .* FOR UPDATE$"
INSERT_GROUP = r"^INSERT INTO security\.access_groups"
UPDATE_GROUP = r"^UPDATE security\.access_groups"
INSERT_LINK = r"^INSERT INTO security\.access_group_memberships"
UPDATE_LINK = r"^UPDATE security\.access_group_memberships"
UPDATE_GRANT = r"^UPDATE security\.resource_grants"
UPDATE_REVELATION = r"^UPDATE security\.character_revelations"

COMMANDS = (
    "create_access_group",
    "update_access_group",
    "deactivate_access_group",
    "reactivate_access_group",
    "add_access_group_member",
    "remove_access_group_member",
)


# --- the scene -----------------------------------------------------------------------------------------------------


@dataclasses.dataclass
class GEnv:
    """A group with an open link (member 0), a grant and a live revelation; an archived group; three more eligible
    members; a second group with the same dependents (it must stay untouched)."""

    label: str
    group: uuid.UUID
    archived: uuid.UUID
    other_group: uuid.UUID
    members: list[uuid.UUID]
    users: list[uuid.UUID]
    link: uuid.UUID
    grant: uuid.UUID
    revelation: uuid.UUID
    other_link: uuid.UUID
    other_grant: uuid.UUID
    other_revelation: uuid.UUID
    character: uuid.UUID
    capability: uuid.UUID
    new_name: str

    def ids(self, *indexes: int) -> list[str]:
        return [str(self.members[i]) for i in indexes]


def make_group_revelation(
    c: Any, campaign: uuid.UUID, character: uuid.UUID, group: uuid.UUID, creator: uuid.UUID
) -> uuid.UUID:
    value = c.execute(
        text(
            "INSERT INTO security.character_revelations (campaign_id, character_id, "
            "revelation_audience_kind_id, target_access_group_id, created_by_membership_id, "
            "authority_source_code, reason) VALUES (:campaign, :character, (SELECT "
            "revelation_audience_kind_id FROM security.revelation_audience_kinds WHERE code = "
            "'access_group'), :group, :creator, 'owner', 'because') RETURNING character_revelation_id"
        ),
        {"campaign": campaign, "character": character, "group": group, "creator": creator},
    ).scalar_one()
    assert isinstance(value, uuid.UUID)
    return value


def release_profile(sc: Scene, character: uuid.UUID) -> None:
    """A released public profile, so a revelation of the character is a legitimate row (the database refuses one without)."""
    owner_membership = rows(
        sc.w.engine,
        "SELECT campaign_membership_id AS id FROM security.campaign_memberships "
        "WHERE campaign_id = :c AND user_id = :u",
        c=sc.w.campaign_id,
        u=sc.w.owner,
    )[0]["id"]
    with sc.w.engine.begin() as c:
        save_character_public_profile_draft(
            c,
            campaign_id=sc.w.campaign_id,
            character_id=character,
            actor_user_id=sc.w.owner,
            expected_row_version=None,
            fields={"public_appearance": "A released face"},
            plan=fixture_plan(c, sc.w.campaign_id),
        )
    with sc.w.engine.begin() as c:
        release_character_public_profile(
            c,
            campaign_id=sc.w.campaign_id,
            character_id=character,
            actor_membership_id=owner_membership,
            expected_draft_row_version=1,
            release_note=None,
            plan=fixture_plan(c, sc.w.campaign_id),
        )


def build_genv(sc: Scene, label: str = "S5E5") -> GEnv:
    tag = uuid.uuid4().hex[:8]
    with sc.w.engine.begin() as c:
        character = make_character(c, sc.w.world_id, name=f"{label} character {tag}")
    release_profile(sc, character)
    with sc.w.engine.begin() as c:
        users = [make_user(c, f"{label} member {i}") for i in range(4)]
        members = [make_campaign_membership(c, sc.w.campaign_id, user) for user in users]
        for membership in members:
            make_membership_role(c, membership, sc.player)
        group = make_access_group(c, sc.w.campaign_id, name=f"{label} group {tag}")
        other_group = make_access_group(c, sc.w.campaign_id, name=f"{label} other {tag}")
        archived = make_access_group(
            c, sc.w.campaign_id, name=f"{label} archived {tag}", lifecycle_status_code="archived"
        )
        capability = c.execute(
            text(
                "SELECT capability_id FROM security.capabilities WHERE code = 'character.view_summary'"
            )
        ).scalar_one()
        link = make_access_group_membership(c, group, members[0])
        other_link = make_access_group_membership(c, other_group, members[0])
        grant = make_resource_grant(
            c,
            sc.w.campaign_id,
            capability,
            grantee_access_group_id=group,
            character_id=character,
            granted_by_membership_id=sc.m.keeper_membership,
        )
        other_grant = make_resource_grant(
            c,
            sc.w.campaign_id,
            capability,
            grantee_access_group_id=other_group,
            character_id=character,
            granted_by_membership_id=sc.m.keeper_membership,
        )
        revelation = make_group_revelation(
            c, sc.w.campaign_id, character, group, sc.m.keeper_membership
        )
        other_revelation = make_group_revelation(
            c, sc.w.campaign_id, character, other_group, sc.m.keeper_membership
        )
    return GEnv(
        label,
        group,
        archived,
        other_group,
        members,
        users,
        link,
        grant,
        revelation,
        other_link,
        other_grant,
        other_revelation,
        character,
        capability,
        f"{label} new {tag}",
    )


@pytest.fixture
def e(s: Scene) -> GEnv:
    return build_genv(s)


@pytest.fixture(autouse=True)
def _tidy(w: World) -> Any:
    yield
    with w.engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        cleanup.execute(
            text("DELETE FROM audit.change_log WHERE world_id = :w AND command_name = ANY(:c)"),
            {"w": w.world_id, "c": list(COMMANDS)},
        )


# --- the six routes, as data -------------------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Route:
    name: str
    command: str
    status: int
    steps: tuple[str, ...]
    make: Callable[[Scene, GEnv], tuple[str, dict[str, Any]]]
    #: audit rows one successful request writes
    audits: int
    business_pattern: str


def _create(sc: Scene, g: GEnv) -> tuple[str, dict[str, Any]]:
    return f"{sc.w.base}/access-groups", {"name": g.new_name, "description": "  a description  "}


def _update(sc: Scene, g: GEnv) -> tuple[str, dict[str, Any]]:
    return f"{sc.w.base}/access-groups/{g.group}/update", {
        "name": f"{g.new_name} renamed",
        "description": "changed",
    }


def _deactivate(sc: Scene, g: GEnv) -> tuple[str, dict[str, Any]]:
    return f"{sc.w.base}/access-groups/{g.group}/deactivate", {}


def _reactivate(sc: Scene, g: GEnv) -> tuple[str, dict[str, Any]]:
    return f"{sc.w.base}/access-groups/{g.archived}/reactivate", {}


def _add(sc: Scene, g: GEnv) -> tuple[str, dict[str, Any]]:
    return f"{sc.w.base}/access-groups/{g.group}/members", {"campaign_membership_ids": g.ids(1, 2)}


def _remove(sc: Scene, g: GEnv) -> tuple[str, dict[str, Any]]:
    return f"{sc.w.base}/access-group-memberships/{g.link}/remove", {}


ROUTES = (
    Route(
        "create",
        "create_access_group",
        201,
        ("insert_access_group", "audit_group_created"),
        _create,
        1,
        INSERT_GROUP,
    ),
    Route(
        "update",
        "update_access_group",
        200,
        ("update_access_group", "audit_group_updated"),
        _update,
        1,
        UPDATE_GROUP,
    ),
    Route(
        "deactivate",
        "deactivate_access_group",
        200,
        (
            "archive_access_group",
            "close_group_links",
            "revoke_group_grants",
            "close_group_revelations",
            "audit_group_deactivated",
        ),
        _deactivate,
        1,
        UPDATE_GROUP,
    ),
    Route(
        "reactivate",
        "reactivate_access_group",
        200,
        ("reactivate_access_group", "audit_group_reactivated"),
        _reactivate,
        1,
        UPDATE_GROUP,
    ),
    Route(
        "add",
        "add_access_group_member",
        201,
        ("insert_group_link", "audit_group_link_created"),
        _add,
        2,
        INSERT_LINK,
    ),
    Route(
        "remove",
        "remove_access_group_member",
        200,
        ("remove_group_link", "audit_group_link_removed"),
        _remove,
        1,
        UPDATE_LINK,
    ),
)
ROUTE = pytest.mark.parametrize("route", ROUTES, ids=[r.name for r in ROUTES])
BY_NAME = {r.name: r for r in ROUTES}


def send(
    factory: Factory,
    sc: Scene,
    route: Route,
    g: GEnv,
    *,
    key: str | None = None,
    actor: uuid.UUID | None = None,
    path_body: tuple[str, dict[str, Any]] | None = None,
) -> Any:
    path, body = path_body or route.make(sc, g)
    headers = {"Idempotency-Key": key} if key else {}
    with factory(actor or sc.m.manager_user) as client:
        return client.post(path, json=body, headers=headers)


@dataclasses.dataclass
class Snap:
    groups: tuple[Any, ...]
    links: tuple[Any, ...]
    grants: tuple[Any, ...]
    revelations: tuple[Any, ...]
    audits: tuple[Any, ...]
    receipt: tuple[Any, ...]


def snap(sc: Scene, key: str | None = None) -> Snap:
    def q(sql: str, **params: Any) -> tuple[Any, ...]:
        with sc.w.engine.connect() as c:
            return tuple(tuple(r) for r in c.execute(text(sql), params))

    campaign = {"c": sc.w.campaign_id}
    return Snap(
        q(
            "SELECT access_group_id, name, description, lifecycle_status_id FROM security.access_groups "
            "WHERE campaign_id = :c ORDER BY 1",
            **campaign,
        ),
        q(
            "SELECT agm.access_group_membership_id, agm.removed_at, agm.added_by_membership_id "
            "FROM security.access_group_memberships agm JOIN security.access_groups ag USING (access_group_id) "
            "WHERE ag.campaign_id = :c ORDER BY 1",
            **campaign,
        ),
        q(
            "SELECT resource_grant_id, revoked_at FROM security.resource_grants WHERE campaign_id = :c ORDER BY 1",
            **campaign,
        ),
        q(
            "SELECT character_revelation_id, ended_at, end_reason FROM security.character_revelations "
            "WHERE campaign_id = :c ORDER BY 1",
            **campaign,
        ),
        q(
            "SELECT command_name, table_name, record_id, previous_status, new_status, changed_fields "
            "FROM audit.change_log WHERE world_id = :w AND command_name = ANY(:names) ORDER BY change_log_id",
            w=sc.w.world_id,
            names=list(COMMANDS),
        ),
        q(
            "SELECT response_status_code, response_body, completed_at IS NOT NULL "
            "FROM security.idempotent_requests WHERE campaign_id = :c AND idempotency_key = :k",
            c=sc.w.campaign_id,
            k=key,
        )
        if key
        else (),
    )


def audits_of(sc: Scene, route: Route) -> list[tuple[Any, ...]]:
    return [a for a in snap(sc).audits if a[0] == route.command]


# --- success, the declared statement order, receipts --------------------------------------------------------------------


@KEYED
@ROUTE
def test_a_route_succeeds_writes_exactly_its_rows_and_its_audit_rows_and_a_keyed_one_stores_its_receipt(
    route: Route, keyed: bool, s: Scene, e: GEnv, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route*: the documented status and body; exactly the declared rows; exactly the declared number of audit rows naming
    the command, with the legacy payloads; a receipt (the response body, completed) only for a keyed request."""
    key = new_key() if keyed else None
    before = snap(s, key)
    response = send(pooled_factory, s, route, e, key=key)
    assert code(response) == route.status, response.text
    body = response.json()
    after = snap(s, key)
    assert after.receipt == (((route.status, body, True),) if keyed else ())
    mine = [a for a in after.audits if a[0] == route.command]
    assert len(mine) == route.audits and len(after.audits) == len(before.audits) + route.audits
    if route.name == "create":
        assert body["name"] == e.new_name
        assert len(after.groups) == len(before.groups) + 1
        [(_, table, record, _p, _n, changed)] = mine
        assert table == "access_groups" and str(record) == body["access_group_id"]
        assert changed == {"name": e.new_name, "description": "a description"}
    if route.name == "update":
        assert body == {"access_group_id": str(e.group), "name": f"{e.new_name} renamed"}
        [(_, table, _record, previous, new, changed)] = mine
        assert (previous, new) == (f"{e.label} group {e.new_name[-8:]}", f"{e.new_name} renamed")
        assert changed == {"description": "changed"} and table == "access_groups"
    if route.name == "deactivate":
        [(_, _t, record, previous, new, changed)] = mine
        assert (str(record), previous, new) == (str(e.group), "active", "archived")
        assert changed == {
            "removed_access_group_memberships": {
                "count": 1,
                "sample_ids": [str(e.link)],
                "sample_truncated": False,
            },
            "revoked_resource_grants": {
                "count": 1,
                "sample_ids": [str(e.grant)],
                "sample_truncated": False,
            },
            "closed_character_revelations": {
                "count": 1,
                "sample_ids": [str(e.revelation)],
                "sample_truncated": False,
            },
        }
    if route.name == "reactivate":
        [(_, _t, record, previous, new, changed)] = mine
        assert (str(record), previous, new, changed) == (
            str(e.archived),
            "archived",
            "active",
            None,
        )
    if route.name == "add":
        assert body["added_count"] == 2 and body["access_group_membership_id"] is None
        assert len(body["access_group_membership_ids"]) == 2
        recorded = [str(a[2]) for a in mine]
        assert (
            recorded == body["access_group_membership_ids"]
        )  # ascending member order, one audit row per link
        assert [a[5] for a in mine] == [
            {"access_group_id": str(e.group), "campaign_membership_id": member}
            for member in sorted(e.ids(1, 2), key=lambda value: uuid.UUID(value).int)
        ]
    if route.name == "remove":
        assert body["access_group_membership_id"] == str(e.link)
        [(_, _t, record, _p, _n, changed)] = mine
        assert str(record) == str(e.link)
        assert changed == {
            "access_group_id": str(e.group),
            "campaign_membership_id": str(e.members[0]),
        }
    assert idle_in_transaction(s.w.engine) == 0


@KEYED
@ROUTE
def test_the_route_runs_its_statements_in_the_declared_order(
    route: Route, keyed: bool, s: Scene, e: GEnv, pooled: Engine, pooled_factory: Factory
) -> None:
    """*sql* (AO-1, CA-1): [key lock, deferral, reservation,] the actor's role rows S first, **then the group U** (every route that
    has a group), the memberships and accounts, the campaign `FOR KEY SHARE` (never U, for create and reactivate too), the
    dependents, [the receipt row,] the one final authority statement, and only after it the declared writes, COMMIT last, no row
    lock after the final statement, and the role rows are the first row lock of every request."""
    key = new_key() if keyed else None
    with Recorder(pooled) as recorded:
        response = send(pooled_factory, s, route, e, key=key)
    assert code(response) == route.status, response.text
    ev = recorded.events
    final = index(ev, FINAL)
    chain: list[int] = [index(ev, ROLES_S)]
    if route.name in ("update", "deactivate", "reactivate", "add"):
        chain.append(index(ev, GROUP_U))
    if route.name == "add":
        # members NKU and the actor S in one ascending pass, then the accounts, then the campaign
        passes = [i for i, x in enumerate(ev) if re.search(MEMBER_NKU, x)]
        assert len(passes) == 2, ev
        accounts = [
            i for i, x in enumerate(ev) if re.search(ACCOUNT_S, x) or re.search(ACCOUNT_KS, x)
        ]
        assert len(accounts) == 3, ev  # the actor S, two members KS
        assert max(passes) < min(accounts) < index(ev, CAMPAIGN_KS)
        chain.append(max(passes))
    elif route.name in ("update", "deactivate", "reactivate", "create", "remove"):
        chain += [index(ev, MEMBERSHIP_S), index(ev, ACCOUNT_S)]
    chain.append(index(ev, CAMPAIGN_KS))
    if route.name == "deactivate":
        chain += [index(ev, LINKS_U), index(ev, GRANTS_U), index(ev, REVELATIONS_U)]
    if route.name == "remove":
        chain.append(index(ev, LINKS_U))
    if keyed:
        chain.append(index(ev, RECEIPT_U))
    chain.append(final)
    chain += [index(ev, route.business_pattern), index(ev, AUDIT_INSERT)]
    if keyed:
        chain.append(index(ev, RECEIPT_UPDATE))
    assert chain == sorted(chain), (chain, ev)
    assert ev[-1] == "COMMIT"
    assert not any(re.search(CAMPAIGN_U, x) for x in ev), (
        "the campaign is never taken FOR UPDATE (CA-1)"
    )
    assert not [
        x for x in ev[final:] if re.search(r"\bFOR (KEY SHARE|SHARE|UPDATE|NO KEY UPDATE)\b", x)
    ]
    first_lock = min(i for i, x in enumerate(ev) if re.search(r"FOR (KEY SHARE|SHARE|UPDATE)", x))
    assert first_lock == index(ev, ROLES_S)
    if route.name == "deactivate":
        # the group row twice (the second is the "this request archives" evidence), then the dependents, ascending
        second = index(ev, GROUP_U, index(ev, GROUP_U) + 1)
        assert second < index(ev, MEMBERSHIP_S)
    if route.name == "add":
        assert len([x for x in ev if re.search(INSERT_LINK, x)]) == 2
    if keyed:
        assert (
            index(ev, r"SET CONSTRAINTS security\.idempotent_requests_campaign_id_fkey DEFERRED")
            < index(ev, KEY_LOCK)
            < index(ev, r"^INSERT INTO security\.idempotent_requests")
            < index(ev, ROLES_S)
        )
    else:
        assert not [
            x for x in ev if re.search(r"pg_advisory|idempotent_requests|SET CONSTRAINTS", x)
        ]
    assert len([x for x in ev if re.search(AUDIT_INSERT, x)]) == route.audits


# --- the legitimate no-ops -----------------------------------------------------------------------------------------------


@KEYED
@pytest.mark.parametrize("route_name", ("deactivate", "reactivate", "remove"))
def test_a_no_op_writes_nothing_and_a_keyed_one_completes_its_receipt_and_replays(
    route_name: str, keyed: bool, s: Scene, e: GEnv, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route* and *sql*: deactivating an archived group, reactivating an active one and removing a removed link are 200 with
    no write and no audit row (and no dependent lock, no H-1 read); the campaign is locked `FOR KEY SHARE`; a fresh keyed no-op
    still completes its receipt exactly once and replays it. Stray open rows of an archived group are preserved (the legacy
    no-op)."""
    route = BY_NAME[route_name]
    target = {"deactivate": e.archived, "reactivate": e.group, "remove": e.link}[route_name]
    if route_name == "remove":
        assert code(send(pooled_factory, s, route, e)) == 200  # the real removal first
    if route_name == "deactivate":
        with (
            s.w.engine.begin() as c
        ):  # a stray open link on the archived group, written outside the application
            make_access_group_membership(c, e.archived, e.members[3])
    path = {
        "deactivate": f"{s.w.base}/access-groups/{target}/deactivate",
        "reactivate": f"{s.w.base}/access-groups/{target}/reactivate",
        "remove": f"{s.w.base}/access-group-memberships/{target}/remove",
    }[route_name]
    before = snap(s)
    key = new_key() if keyed else None
    with Recorder(pooled) as recorded:
        response = send(pooled_factory, s, route, e, key=key, path_body=(path, {}))
    assert code(response) == 200, response.text
    after = snap(s, key)
    assert (after.groups, after.links, after.grants, after.revelations, after.audits) == (
        before.groups,
        before.links,
        before.grants,
        before.revelations,
        before.audits,
    )
    assert business_writes(recorded.events) == []
    assert len([x for x in recorded.events if re.search(RECEIPT_UPDATE, x)]) == (1 if keyed else 0)
    assert any(re.search(CAMPAIGN_KS, x) for x in recorded.events)
    assert not any(re.search(CAMPAIGN_U, x) for x in recorded.events)
    assert not any(
        re.search(pattern, x) for pattern in (GRANTS_U, REVELATIONS_U) for x in recorded.events
    )
    if route_name == "deactivate":
        assert not any(re.search(LINKS_U, x) for x in recorded.events)
        assert snap(s).links == before.links  # the stray row is still open
    if keyed:
        assert after.receipt == ((200, response.json(), True),)
        again = send(pooled_factory, s, route, e, key=key, path_body=(path, {}))
        assert code(again) == 200 and again.json() == response.json()
        assert snap(s, key).audits == before.audits


# --- refusals before the final statement --------------------------------------------------------------------------------------


def _other_campaign_group(sc: Scene) -> uuid.UUID:
    with sc.w.engine.begin() as c:
        timeline = c.execute(
            text("SELECT timeline_id FROM campaign.campaigns WHERE campaign_id = :c"),
            {"c": sc.w.campaign_id},
        ).scalar_one()
        other_campaign = make_campaign(c, timeline, lifecycle_status_code="pending")
        return make_access_group(c, other_campaign, name=f"foreign {uuid.uuid4().hex[:6]}")


@KEYED
@pytest.mark.parametrize("route_name", ("update", "deactivate", "reactivate", "add", "remove"))
def test_a_group_or_link_of_another_campaign_is_the_unchanged_404_persists_nothing_and_the_key_is_reusable(
    route_name: str, keyed: bool, s: Scene, e: GEnv, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route* and *sql*: a group or link that does not exist, or belongs to another campaign, is the 404 raised before the
    final statement (no foreign row is locked: the predicate binds the campaign, and the link is discovered unlocked first);
    nothing persists; the keyed reservation rolls back with the request and the key is reusable."""
    route = BY_NAME[route_name]
    foreign = _other_campaign_group(s)
    path, body = route.make(s, e)
    path = {
        "update": f"{s.w.base}/access-groups/{foreign}/update",
        "deactivate": f"{s.w.base}/access-groups/{foreign}/deactivate",
        "reactivate": f"{s.w.base}/access-groups/{foreign}/reactivate",
        "add": f"{s.w.base}/access-groups/{foreign}/members",
        "remove": f"{s.w.base}/access-group-memberships/{uuid.uuid4()}/remove",
    }[route_name]
    key = new_key() if keyed else None
    before = snap(s, key)
    with Recorder(pooled) as recorded:
        response = send(pooled_factory, s, route, e, key=key, path_body=(path, body))
    assert code(response) == 404, response.text
    assert snap(s, key) == before and idle_in_transaction(s.w.engine) == 0
    assert not any(FINAL_RE.search(x) for x in recorded.events)
    assert business_writes(recorded.events) == []
    assert code(send(pooled_factory, s, route, e, key=key)) == route.status


@KEYED
@pytest.mark.parametrize(
    ("route_name", "case", "expected"),
    (
        ("create", "blank", 422),
        ("create", "campaign_inactive", 409),
        ("create", "duplicate", 409),
        ("update", "inactive_group", 409),
        ("update", "blank", 422),
        ("update", "no_op", 422),
        ("update", "duplicate", 409),
        ("reactivate", "campaign_inactive", 409),
        ("add", "inactive_group", 409),
        ("add", "campaign_inactive", 409),
    ),
)
def test_every_other_refusal_is_the_unchanged_status_persists_nothing_and_the_key_is_reusable(
    route_name: str,
    case: str,
    expected: int,
    keyed: bool,
    s: Scene,
    e: GEnv,
    pooled: Engine,
    pooled_factory: Factory,
) -> None:
    """*route*: the refusals of design section 3 in their documented statuses. The 422 no-op is a refusal: it never stores
    a receipt, so the key stays reusable for a corrected request. A duplicate name is refused by the unique index at the
    declared INSERT / UPDATE (after the final statement) and rolls everything back."""
    route = BY_NAME[route_name]
    path, body = route.make(s, e)
    if case == "blank":
        body = {**body, "name": "   "}
    if case == "no_op":
        with s.w.engine.connect() as c:
            current = c.execute(
                text(
                    "SELECT name, description FROM security.access_groups WHERE access_group_id = :g"
                ),
                {"g": e.group},
            ).one()
        body = {"name": f"  {current[0]}  ", "description": current[1]}
    if case == "duplicate":
        with s.w.engine.connect() as c:
            taken = c.execute(
                text("SELECT name FROM security.access_groups WHERE access_group_id = :g"),
                {"g": e.other_group},
            ).scalar_one()
        body = {**body, "name": taken}
    if case == "inactive_group":
        path = path.replace(str(e.group), str(e.archived))
    deactivate_campaign = case == "campaign_inactive"
    if deactivate_campaign:
        with s.w.engine.begin() as c:
            c.execute(
                text(
                    "UPDATE campaign.campaigns SET lifecycle_status_id = (SELECT lifecycle_status_id "
                    "FROM core.lifecycle_statuses WHERE code = 'pending') WHERE campaign_id = :c"
                ),
                {"c": s.w.campaign_id},
            )
    key = new_key() if keyed else None
    before = snap(s, key)
    response = send(pooled_factory, s, route, e, key=key, path_body=(path, body))
    assert code(response) == expected, response.text
    assert snap(s, key) == before and idle_in_transaction(s.w.engine) == 0
    if deactivate_campaign:
        with s.w.engine.begin() as c:
            c.execute(
                text(
                    "UPDATE campaign.campaigns SET lifecycle_status_id = (SELECT lifecycle_status_id "
                    "FROM core.lifecycle_statuses WHERE code = 'active') WHERE campaign_id = :c"
                ),
                {"c": s.w.campaign_id},
            )
        assert code(send(pooled_factory, s, route, e, key=key)) == route.status
    elif case in ("blank", "no_op", "duplicate", "inactive_group"):
        # the corrected request succeeds with the very same key
        fixed = {
            "blank": route.make(s, e),
            "no_op": route.make(s, e),
            "duplicate": route.make(s, e),
            "inactive_group": (
                f"{s.w.base}/access-groups/{e.group}/{'update' if route_name == 'update' else 'members'}",
                route.make(s, e)[1],
            ),
        }[case]
        assert code(send(pooled_factory, s, route, e, key=key, path_body=fixed)) == route.status


@ROUTE
def test_a_caller_without_access_manage_is_refused_before_anything_is_looked_up(
    route: Route, s: Scene, e: GEnv, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route*: precedence is unchanged. A player learns nothing: the same 403 or 404 for a real target as for a missing one."""
    before = snap(s)
    real = send(pooled_factory, s, route, e, actor=e.users[3])
    path, body = route.make(s, e)
    for known in (e.group, e.archived, e.link):
        path = path.replace(str(known), str(uuid.uuid4()))
    missing = send(pooled_factory, s, route, e, actor=e.users[3], path_body=(path, body))
    assert code(real) == code(missing) and code(real) in (403, 404), (real.text, missing.text)
    assert error_of(real) == error_of(missing)
    assert snap(s) == before


# --- replay, key reuse, authority ---------------------------------------------------------------------------------------------


@ROUTE
def test_an_authorized_replay_returns_the_stored_receipt_without_a_lock_or_a_write(
    route: Route, s: Scene, e: GEnv, pooled: Engine, pooled_factory: Factory
) -> None:
    key = new_key()
    first = send(pooled_factory, s, route, e, key=key)
    assert code(first) == route.status
    stored = snap(s, key)
    with Recorder(pooled) as recorded:
        replay = send(pooled_factory, s, route, e, key=key)
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


def test_a_reordered_or_duplicated_member_set_is_the_same_request_and_replays(
    s: Scene, e: GEnv, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route*: the request's id set is deduplicated and sorted before it is fingerprinted, so a reordered or repeated
    set carries the same fingerprint and replays the stored response, adding nothing."""
    route = BY_NAME["add"]
    key = new_key()
    ids = e.ids(1, 2)
    path = f"{s.w.base}/access-groups/{e.group}/members"
    first = send(
        pooled_factory, s, route, e, key=key, path_body=(path, {"campaign_membership_ids": ids})
    )
    assert code(first) == 201
    stored = snap(s, key)
    again = send(
        pooled_factory,
        s,
        route,
        e,
        key=key,
        path_body=(path, {"campaign_membership_ids": [ids[1], ids[0], ids[1]]}),
    )
    assert code(again) == 201 and again.json() == first.json()
    assert snap(s, key) == stored


@ROUTE
def test_a_replay_after_authority_loss_is_refused_and_returns_nothing_from_the_receipt(
    route: Route, s: Scene, e: GEnv, pooled: Engine, pooled_factory: Factory
) -> None:
    key = new_key()
    first = send(pooled_factory, s, route, e, key=key)
    assert code(first) == route.status
    stored = snap(s, key)
    revoke_role(s.w.engine, s.m.manager_role)
    again = send(pooled_factory, s, route, e, key=key)
    assert code(again) in (403, 404), again.text
    for value in first.json().values():
        if isinstance(value, str):
            assert value not in again.text
    assert snap(s, key) == stored


@ROUTE
def test_a_reused_key_with_another_target_is_the_same_conflict_and_changes_nothing(
    route: Route, s: Scene, e: GEnv, pooled: Engine, pooled_factory: Factory
) -> None:
    key = new_key()
    assert code(send(pooled_factory, s, route, e, key=key)) == route.status
    other = build_genv(s, "S5E5 Second")
    stored = snap(s, key)
    response = send(pooled_factory, s, route, other, key=key)
    assert code(response) == 409 and error_of(response) == "conflict", response.text
    assert snap(s, key) == stored


@KEYED
@ROUTE
def test_a_role_that_lapses_before_the_final_statement_refuses_the_route_and_rolls_everything_back(
    route: Route, keyed: bool, s: Scene, e: GEnv, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route* (expiry at the authorization boundary): the manager's role is valid for every early check and has lapsed when
    the final authority statement runs, every lock already held. Nothing persists; the key is reusable."""
    from tests.r01_s5d_support import run_with_role_lapsing_before_final

    key = new_key() if keyed else None
    before = snap(s, key)
    response = run_with_role_lapsing_before_final(
        s.w.engine,
        pooled,
        s.m.manager_role,
        lambda: send(pooled_factory, s, route, e, key=key),
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
    assert code(send(pooled_factory, s, route, e, key=key)) == route.status


# --- held modes, probed while the request is parked at its final statement -------------------------------------------------------


@pytest.mark.parametrize(
    "route_name", ("create", "update", "deactivate", "reactivate", "add", "remove")
)
def test_the_request_holds_each_row_at_the_mode_it_needs_when_it_reaches_its_final_statement(
    route_name: str, s: Scene, e: GEnv, pooled: Engine, pooled_factory: Factory
) -> None:
    """*probe*: parked at the final authority statement (every lock held), `NOWAIT` probes from another connection: the actor's
    role row and membership and account `FOR SHARE`; the group `FOR UPDATE` (every route that has one); the campaign `FOR KEY
    SHARE` (never stronger: CA-1); for add the members `FOR NO KEY UPDATE` and their accounts `FOR KEY SHARE`; for deactivate every
    dependent `FOR UPDATE`; for remove the link `FOR UPDATE`."""
    route = BY_NAME[route_name]
    admin = s.w.engine
    with StatementGate(pooled, FINAL) as gate:
        request = run_in_thread("probe", lambda: send(pooled_factory, s, route, e))
        gate.wait_reached()
        modes = {
            "role": held_mode(admin, ROLE_ROW, s.m.manager_role),
            "membership": held_mode(admin, MEMBERSHIP_ROW, s.m.manager_membership),
            "account": held_mode(admin, USER_ROW, s.m.manager_user),
            "campaign": held_mode(admin, CAMPAIGN_ROW, s.w.campaign_id),
        }
        if route_name in ("update", "deactivate", "add"):
            modes["group"] = held_mode(admin, GROUP_ROW, e.group)
        if route_name == "reactivate":
            modes["group"] = held_mode(admin, GROUP_ROW, e.archived)
        if route_name == "add":
            modes["member1"] = held_mode(admin, MEMBERSHIP_ROW, e.members[1])
            modes["member1_account"] = held_mode(admin, USER_ROW, e.users[1])
        if route_name == "deactivate":
            modes["link"] = held_mode(admin, LINK_ROW, e.link)
            modes["grant"] = held_mode(
                admin, ("security.resource_grants", "resource_grant_id"), e.grant
            )
            modes["revelation"] = held_mode(
                admin, ("security.character_revelations", "character_revelation_id"), e.revelation
            )
        if route_name == "remove":
            modes["link"] = held_mode(admin, LINK_ROW, e.link)
        gate.release()
        response = request.wait("the request finishes")
    assert code(response) == route.status, response.text
    expected = {"role": "S", "membership": "S", "account": "S", "campaign": "KS"}
    if route_name in ("update", "deactivate", "reactivate", "add"):
        expected["group"] = "U"
    if route_name == "add":
        expected |= {"member1": "NKU", "member1_account": "KS"}
    if route_name in ("deactivate", "remove"):
        expected |= {"link": "U"}
    if route_name == "deactivate":
        expected |= {"grant": "U", "revelation": "U"}
    assert modes == expected


# --- the plan's obligations -------------------------------------------------------------------------------------------------------


@KEYED
@ROUTE
def test_a_handler_that_forgets_to_finalize_is_a_sanitized_500_that_persists_nothing(
    route: Route,
    keyed: bool,
    s: Scene,
    e: GEnv,
    pooled: Engine,
    pooled_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = new_key() if keyed else None
    before = snap(s, key)
    monkeypatch.setattr(AuthorizationPlan, "finalize", lambda self, connection: None)
    response = send(pooled_factory, s, route, e, key=key)
    monkeypatch.undo()
    assert code(response) == 500 and error_of(response) == "internal_error"
    assert snap(s, key) == before and idle_in_transaction(s.w.engine) == 0
    assert code(send(pooled_factory, s, route, e, key=key)) == route.status


def _wrap(
    monkeypatch: pytest.MonkeyPatch,
    *,
    skip: dict[str, set[int]] | None = None,
    repeat: dict[str, set[int]] | None = None,
    after: dict[str, tuple[Any, dict[str, Any]]] | None = None,
    redirect: dict[str, tuple[int, dict[str, Any]]] | None = None,
) -> None:
    """Test-side mutation of `AuthorizationPlan.execute`: omit the n-th execution of a step, run it twice, run another declared
    step right after it, or run it with other parameters (the n-th time). The n-th is counted per step name, from 1."""
    original = AuthorizationPlan.execute
    seen: dict[str, int] = {}

    def wrapper(self: AuthorizationPlan, connection: Any, step: Any, params: Any) -> Any:
        seen[step.name] = seen.get(step.name, 0) + 1
        n = seen[step.name]
        if skip and n in skip.get(step.name, set()):
            return StepOutcome(step=step.name, keys=())
        if redirect and step.name in redirect and redirect[step.name][0] == n:
            params = {**params, **redirect[step.name][1]}
        outcome = original(self, connection, step, params)
        if repeat and n in repeat.get(step.name, set()):
            original(self, connection, step, params)
        if after and step.name in after and n == 1:
            extra_step, extra_params = after[step.name]
            original(self, connection, extra_step, extra_params)
        return outcome

    monkeypatch.setattr(AuthorizationPlan, "execute", wrapper)


def _declared_steps() -> list[tuple[str, str]]:
    return [(r.name, step) for r in ROUTES for step in r.steps]


@KEYED
@pytest.mark.parametrize(("route_name", "step"), (*_declared_steps(), ("create", "receipt")))
def test_an_omitted_required_write_is_refused_at_commit_and_rolls_everything_back(
    route_name: str,
    step: str,
    keyed: bool,
    s: Scene,
    e: GEnv,
    pooled: Engine,
    pooled_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """*mutation (test-side)* **omission**: every business write, every audit row and (keyed) the receipt is owed by the locked
    state. A request that never runs one cannot commit: the guard refuses the incomplete plan (sanitized 500), everything
    rolls back, the key is reusable, the connection is clean."""
    if step == "receipt" and not keyed:
        pytest.skip("an unkeyed request has no receipt")
    route = BY_NAME[route_name]
    key = new_key() if keyed else None
    before = snap(s, key)
    _wrap(monkeypatch, skip={step: {1}})
    response = send(pooled_factory, s, route, e, key=key)
    monkeypatch.undo()
    assert code(response) == 500 and error_of(response) == "internal_error", (step, response.text)
    assert snap(s, key) == before and idle_in_transaction(s.w.engine) == 0, step
    assert code(send(pooled_factory, s, route, e, key=key)) == route.status


@KEYED
@pytest.mark.parametrize(("route_name", "step"), _declared_steps())
def test_a_repeated_write_is_refused_and_the_whole_request_rolls_back(
    route_name: str,
    step: str,
    keyed: bool,
    s: Scene,
    e: GEnv,
    pooled: Engine,
    pooled_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """*mutation (test-side)* **commission**: a second insert, a second update of a row or a second audit row is a forbidden
    extra write: the second attempt is refused before the driver and nothing persists."""
    route = BY_NAME[route_name]
    key = new_key() if keyed else None
    before = snap(s, key)
    _wrap(monkeypatch, repeat={step: {1}})
    response = send(pooled_factory, s, route, e, key=key)
    monkeypatch.undo()
    assert code(response) == 500, (step, response.text)
    assert snap(s, key) == before and idle_in_transaction(s.w.engine) == 0


@pytest.mark.parametrize(
    ("route_name", "first", "victim_step", "victim_params"),
    (
        ("update", "update_access_group", "update_access_group", "other_group"),
        ("deactivate", "archive_access_group", "archive_access_group", "other_group"),
        ("deactivate", "close_group_links", "close_group_links", "other_link"),
        ("deactivate", "revoke_group_grants", "revoke_group_grants", "other_grant"),
        ("deactivate", "close_group_revelations", "close_group_revelations", "other_revelation"),
        ("reactivate", "reactivate_access_group", "reactivate_access_group", "other_group"),
        ("remove", "remove_group_link", "remove_group_link", "other_link"),
    ),
)
def test_a_write_to_a_row_the_request_did_not_lock_is_refused_and_nothing_persists(
    route_name: str,
    first: str,
    victim_step: str,
    victim_params: str,
    s: Scene,
    e: GEnv,
    pooled: Engine,
    pooled_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """*mutation (test-side)* **commission, an unlocked row**: right after the genuine write the request tries the same kind of
    write against a row of **another group** that it never locked: refused (`TARGET_NOT_LOCKED`), the whole request rolls back and
    the other group's rows stay as they were."""
    declared = {
        step.name: step
        for declarations in (
            plans.UPDATE_DECLARATIONS,
            plans.DEACTIVATE_DECLARATIONS,
            plans.REACTIVATE_DECLARATIONS,
            plans.REMOVE_DECLARATIONS,
        )
        for step in declarations.unkeyed.steps
    }
    victim = getattr(e, victim_params)
    extra: dict[str, Any] = {"target": victim}
    if victim_step == "archive_access_group":
        extra["status"] = uuid.uuid4()
    if victim_step == "reactivate_access_group":
        extra["status"] = uuid.uuid4()
    if victim_step == "update_access_group":
        extra |= {"name": "x", "description": None}
    route = BY_NAME[route_name]
    _wrap(monkeypatch, after={first: (declared[victim_step], extra)})
    before = snap(s)
    response = send(pooled_factory, s, route, e)
    monkeypatch.undo()
    assert code(response) == 500, response.text
    assert snap(s) == before and idle_in_transaction(s.w.engine) == 0


def _fail_step(monkeypatch: pytest.MonkeyPatch, step_name: str) -> None:
    original = AuthorizationPlan.execute

    def wrapper(self: AuthorizationPlan, connection: Any, step: Any, params: Any) -> Any:
        if step.name == step_name:
            raise RuntimeError("injected failure")
        return original(self, connection, step, params)

    monkeypatch.setattr(AuthorizationPlan, "execute", wrapper)


@pytest.mark.parametrize("failing", ("audit", "receipt"))
@ROUTE
def test_a_failure_at_the_audit_or_receipt_step_rolls_back_every_write_the_audit_rows_and_the_receipt(
    route: Route,
    failing: str,
    s: Scene,
    e: GEnv,
    pooled: Engine,
    pooled_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """*route* (complete rollback): the business rows were written when the last declared step fails; a sanitized 500 and
    nothing persists: no group, link, grant or revelation change, no audit row, no receipt; the connection is clean and the key
    is reusable afterwards."""
    key = new_key()
    before = snap(s, key)
    _fail_step(monkeypatch, route.steps[-1] if failing == "audit" else "receipt")
    response = send(pooled_factory, s, route, e, key=key)
    monkeypatch.undo()
    assert code(response) == 500 and error_of(response) == "internal_error", response.text
    assert snap(s, key) == before and idle_in_transaction(s.w.engine) == 0
    assert code(send(pooled_factory, s, route, e, key=key)) == route.status


@KEYED
@pytest.mark.parametrize("route_name", ("deactivate", "reactivate", "remove"))
def test_a_write_attempted_on_a_no_op_path_is_refused_and_nothing_persists(
    route_name: str,
    keyed: bool,
    s: Scene,
    e: GEnv,
    pooled: Engine,
    pooled_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """*mutation (test-side)* **commission on the legitimate no-op**: the archive and the audit row of a deactivation of an
    already-archived group, the reactivation and its audit row of an already-active group, the closing update and the audit row of
    an already-removed link are *forbidden* (the lock's evidence is empty), so a handler that forgets its no-op branch cannot
    write: refused before the driver, a sanitized 500, nothing persisted, the key reusable."""
    route = BY_NAME[route_name]
    target = {"deactivate": e.archived, "reactivate": e.group, "remove": e.link}[route_name]
    if route_name == "remove":
        assert code(send(pooled_factory, s, route, e)) == 200  # the real removal first
    path = {
        "deactivate": f"{s.w.base}/access-groups/{target}/deactivate",
        "reactivate": f"{s.w.base}/access-groups/{target}/reactivate",
        "remove": f"{s.w.base}/access-group-memberships/{target}/remove",
    }[route_name]
    original = getattr(
        api_module, f"write_{route_name}_group" if route_name != "remove" else "write_remove_member"
    )
    attr = f"write_{route_name}_group" if route_name != "remove" else "write_remove_member"

    def forced(connection: Any, plan: Any, prepared: Any, **kwargs: Any) -> Any:
        return original(connection, plan, dataclasses.replace(prepared, will_write=True), **kwargs)

    key = new_key() if keyed else None
    before = snap(s, key)
    monkeypatch.setattr(api_module, attr, forced)
    response = send(pooled_factory, s, route, e, key=key, path_body=(path, {}))
    monkeypatch.undo()
    assert code(response) == 500 and error_of(response) == "internal_error", response.text
    assert snap(s, key) == before and idle_in_transaction(s.w.engine) == 0
    assert code(send(pooled_factory, s, route, e, key=key, path_body=(path, {}))) == 200


def test_a_one_connection_pool_serves_every_route_noops_refusals_and_a_replay_without_leaking_state(
    s: Scene, e: GEnv, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route*: one pooled connection, reused for all six routes, a no-op, a 404, a 403 and a replay in turn. Each answers as it
    would alone, the connection is never left in a transaction, and nothing one request held reaches the next."""
    key = new_key()
    # the add comes before the deactivation (an archived group refuses it)
    for name in ("create", "update", "add", "remove", "deactivate", "reactivate"):
        route = BY_NAME[name]
        assert (
            code(send(pooled_factory, s, route, e, key=key if route.name == "remove" else None))
            == route.status
        )
        assert idle_in_transaction(s.w.engine) == 0
    assert code(send(pooled_factory, s, BY_NAME["remove"], e)) == 200  # the no-op
    assert code(send(pooled_factory, s, BY_NAME["remove"], e, actor=e.users[3])) in (403, 404)
    assert code(send(pooled_factory, s, BY_NAME["remove"], e, key=key)) == 200  # the replay
    assert (
        code(
            send(
                pooled_factory,
                s,
                BY_NAME["remove"],
                e,
                path_body=(f"{s.w.base}/access-group-memberships/{uuid.uuid4()}/remove", {}),
            )
        )
        == 404
    )
    assert idle_in_transaction(s.w.engine) == 0
    for route in ROUTES:
        assert len(audits_of(s, route)) == route.audits


def test_the_declarations_hold_against_the_live_catalogue(w: World) -> None:
    """The S1 catalogue helper checks every assumption a declaration makes about the database (triggers pinned by
    function-source hash, unique waits, FK match type and order, defaults, CHECK expressions, the `greatest()` column types).
    An empty list is the only passing answer."""
    from tests.r01_pre_write_catalogue import check_declaration

    problems: list[str] = []
    with w.engine.connect() as connection:
        for name in (
            "CREATE_DECLARATIONS",
            "UPDATE_DECLARATIONS",
            "DEACTIVATE_DECLARATIONS",
            "REACTIVATE_DECLARATIONS",
            "ADD_DECLARATIONS",
            "REMOVE_DECLARATIONS",
        ):
            declarations = getattr(plans, name)
            for kind, decl in (
                ("reserved", declarations.reserved),
                ("unkeyed", declarations.unkeyed),
            ):
                assert decl is not None
                problems += [f"{name} {kind}: {x}" for x in check_declaration(connection, decl)]
    assert problems == [], chr(10).join(problems)


# --- unique waits ---------------------------------------------------------------------------------------------------------------


def test_a_competing_group_name_is_a_unique_wait(
    s: Scene, e: GEnv, pooled: Engine, pooled_factory: Factory
) -> None:
    """*race*, `ux_access_groups_campaign_name` on the create's INSERT: a competitor inserting the same name while the request is
    parked at its audit insert (its row inserted, uncommitted) queues behind *the request* on the index key; when the request
    commits the competitor fails on the unique index (409-class), never a second group of that name."""
    from tests.database.test_r01_s5e2_membership_routes import waiting_statement
    from tests.lock_race_support import LockRace

    route = BY_NAME["create"]

    def competitor(c: Any) -> Any:
        return make_access_group(c, s.w.campaign_id, name=e.new_name)

    with StatementGate(pooled, AUDIT_INSERT) as gate:
        request = run_in_thread("create", lambda: send(pooled_factory, s, route, e))
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


def test_a_competing_open_link_is_a_unique_wait(
    s: Scene, e: GEnv, pooled: Engine, pooled_factory: Factory
) -> None:
    """*race*, `ux_access_group_memberships_open` on the add's INSERT: a competitor inserting the same open link while the add is
    parked at its first audit insert queues behind *the add*; when the add commits the competitor fails on the unique index."""
    from tests.database.test_r01_s5e2_membership_routes import waiting_statement
    from tests.lock_race_support import LockRace

    route = BY_NAME["add"]

    def competitor(c: Any) -> Any:
        return make_access_group_membership(c, e.group, e.members[1])

    with StatementGate(pooled, AUDIT_INSERT) as gate:
        request = run_in_thread("add", lambda: send(pooled_factory, s, route, e))
        gate.wait_reached()
        assert gate.pid is not None
        with LockRace(s.w.engine) as race:
            queued = race.start("insert", competitor)
            race.wait_blocked_by(gate, expected=1)
            assert re.search(r"INSERT INTO security\.", waiting_statement(s.w.engine, gate.pid))
            gate.release()
            response = request.wait("the add finishes")
            race.join_all()
    assert code(response) == 201
    assert isinstance(queued.error, IntegrityError), queued.error


# --- the bulk add: all-or-nothing -----------------------------------------------------------------------------------------------


def test_adding_a_duplicate_open_link_refuses_the_whole_batch_and_persists_nothing(
    s: Scene, e: GEnv, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route*: member 0 already has an open link; the batch {member 1, member 0, member 2} is refused (409 at that member's
    INSERT, after member 1's INSERT ran), nothing is skipped and nothing persists, and the key is reusable."""
    route = BY_NAME["add"]
    key = new_key()
    body = {"campaign_membership_ids": e.ids(1, 0, 2)}
    path = f"{s.w.base}/access-groups/{e.group}/members"
    before = snap(s, key)
    response = send(pooled_factory, s, route, e, key=key, path_body=(path, body))
    assert code(response) == 409, response.text
    assert snap(s, key) == before and idle_in_transaction(s.w.engine) == 0
    good = send(
        pooled_factory,
        s,
        route,
        e,
        key=key,
        path_body=(path, {"campaign_membership_ids": e.ids(1, 2)}),
    )
    assert code(good) == 201 and good.json()["added_count"] == 2


@pytest.mark.parametrize(
    "case", ("ended", "suspended", "inactive_account", "foreign", "nonexistent")
)
def test_an_ineligible_member_refuses_the_whole_batch_and_persists_nothing(
    case: str, s: Scene, e: GEnv, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route*: an ended or suspended membership, an inactive account (409) and a foreign or nonexistent membership (404) each
    refuse the entire batch, whichever position they take in the ascending order."""
    route = BY_NAME["add"]
    bad = e.members[2]
    if case == "ended":
        with s.w.engine.begin() as c:
            c.execute(
                text(
                    "UPDATE security.campaign_memberships SET ended_at = now() + interval '1 microsecond', "
                    "membership_status_id = (SELECT membership_status_id FROM security.membership_statuses "
                    "WHERE code = 'departed') WHERE campaign_membership_id = :m"
                ),
                {"m": bad},
            )
    if case == "suspended":
        with s.w.engine.begin() as c:
            c.execute(
                text(
                    "UPDATE security.campaign_memberships SET membership_status_id = (SELECT membership_status_id "
                    "FROM security.membership_statuses WHERE code = 'suspended') WHERE campaign_membership_id = :m"
                ),
                {"m": bad},
            )
    if case == "inactive_account":
        with s.w.engine.begin() as c:
            c.execute(
                text(
                    "UPDATE security.users SET lifecycle_status_id = (SELECT lifecycle_status_id FROM "
                    "core.lifecycle_statuses WHERE code = 'inactive') WHERE user_id = :u"
                ),
                {"u": e.users[2]},
            )
    ids = e.ids(1, 3)
    if case == "foreign":
        with s.w.engine.begin() as c:
            timeline = c.execute(
                text("SELECT timeline_id FROM campaign.campaigns WHERE campaign_id = :c"),
                {"c": s.w.campaign_id},
            ).scalar_one()
            other = make_campaign(c, timeline, lifecycle_status_code="pending")
            ids.append(str(make_campaign_membership(c, other, make_user(c, "foreign member"))))
    elif case == "nonexistent":
        ids.append(str(uuid.uuid4()))
    else:
        ids.append(str(bad))
    expected = 404 if case in ("foreign", "nonexistent") else 409
    key = new_key()
    before = snap(s, key)
    response = send(
        pooled_factory,
        s,
        route,
        e,
        key=key,
        path_body=(f"{s.w.base}/access-groups/{e.group}/members", {"campaign_membership_ids": ids}),
    )
    assert code(response) == expected, response.text
    assert snap(s, key) == before and idle_in_transaction(s.w.engine) == 0


def test_a_removed_link_may_be_re_added_and_a_reactivated_group_starts_empty(
    s: Scene, e: GEnv, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route*: a removed link is historical (the partial unique index allows a new open row); deactivate, reactivate, add
    yields new rows while the links, grants and revelations the deactivation closed stay closed."""
    assert code(send(pooled_factory, s, BY_NAME["remove"], e)) == 200
    readd = send(
        pooled_factory,
        s,
        BY_NAME["add"],
        e,
        path_body=(
            f"{s.w.base}/access-groups/{e.group}/members",
            {"campaign_membership_ids": e.ids(0)},
        ),
    )
    assert code(readd) == 201 and readd.json()["access_group_membership_id"] not in (
        None,
        str(e.link),
    )
    assert code(send(pooled_factory, s, BY_NAME["deactivate"], e)) == 200
    closed = snap(s)
    reactivate = send(
        pooled_factory,
        s,
        BY_NAME["reactivate"],
        e,
        path_body=(f"{s.w.base}/access-groups/{e.group}/reactivate", {}),
    )
    assert code(reactivate) == 200
    after_reactivation = snap(s)
    assert after_reactivation.links == closed.links  # the closed links stay closed
    assert after_reactivation.grants == closed.grants
    assert after_reactivation.revelations == closed.revelations
    again = send(
        pooled_factory,
        s,
        BY_NAME["add"],
        e,
        path_body=(
            f"{s.w.base}/access-groups/{e.group}/members",
            {"campaign_membership_ids": e.ids(0, 1)},
        ),
    )
    assert code(again) == 201 and again.json()["added_count"] == 2


def test_the_legacy_single_id_field_a_self_add_and_a_batch_of_one_hundred(
    s: Scene, e: GEnv, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route*: the legacy `campaign_membership_id` field is a batch of one (the response carries the id); the actor may add
    itself (its membership row is locked once, `FOR NO KEY UPDATE`, then `FOR SHARE` lands on the held row); a batch of 100
    members is one transaction with 100 links and 100 audit rows, ascending."""
    route = BY_NAME["add"]
    path = f"{s.w.base}/access-groups/{e.group}/members"
    legacy = send(
        pooled_factory, s, route, e, path_body=(path, {"campaign_membership_id": e.ids(1)[0]})
    )
    assert code(legacy) == 201 and legacy.json()["added_count"] == 1
    assert (
        legacy.json()["access_group_membership_id"]
        == legacy.json()["access_group_membership_ids"][0]
    )
    with Recorder(pooled) as recorded:
        selfadd = send(
            pooled_factory,
            s,
            route,
            e,
            path_body=(path, {"campaign_membership_ids": [str(s.m.manager_membership)]}),
        )
    assert code(selfadd) == 201, selfadd.text
    ev = recorded.events
    assert len([x for x in ev if re.search(MEMBER_NKU, x)]) == 1  # the actor's row once at NKU
    assert not [x for x in ev if re.search(MEMBERSHIP_S, x) and "FOR NO KEY" in x]
    with s.w.engine.begin() as c:
        many = []
        for index_ in range(100):
            user = make_user(c, f"bulk {index_}")
            many.append(str(make_campaign_membership(c, s.w.campaign_id, user)))
    big = send(pooled_factory, s, route, e, path_body=(path, {"campaign_membership_ids": many}))
    assert code(big) == 201 and big.json()["added_count"] == 100
    assert big.json()["access_group_membership_id"] is None
    assert len(audits_of(s, route)) == 1 + 1 + 100
    with s.w.engine.connect() as c:
        assert (
            c.execute(
                text(
                    "SELECT count(*) FROM security.access_group_memberships WHERE access_group_id = :g "
                    "AND removed_at IS NULL"
                ),
                {"g": e.group},
            ).scalar_one()
            == 1 + 1 + 1 + 100
        )  # the fixture's link, the legacy add, the self-add and the batch


# --- the deactivation cascade -------------------------------------------------------------------------------------------------------


def test_a_deactivation_closes_every_dependent_with_the_right_reason_and_leaves_other_groups_untouched(
    s: Scene, e: GEnv, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route*: every open link, unrevoked grant and live revelation of the group is closed (the revelation with
    `access_group_deactivated`); the other group's rows are untouched; a deactivation with more than 20 dependents samples the
    first 20 ids ascending with the exact count and `sample_truncated`."""
    with s.w.engine.begin() as c:
        for index_ in range(21):
            user = make_user(c, f"cascade {index_}")
            member = make_campaign_membership(c, s.w.campaign_id, user)
            make_access_group_membership(c, e.group, member)
    response = send(pooled_factory, s, BY_NAME["deactivate"], e)
    assert code(response) == 200, response.text
    with s.w.engine.connect() as c:
        open_links = c.execute(
            text(
                "SELECT count(*) FROM security.access_group_memberships WHERE access_group_id = :g AND removed_at IS NULL"
            ),
            {"g": e.group},
        ).scalar_one()
        open_grants = c.execute(
            text(
                "SELECT count(*) FROM security.resource_grants WHERE grantee_access_group_id = :g AND revoked_at IS NULL"
            ),
            {"g": e.group},
        ).scalar_one()
        revelation = c.execute(
            text(
                "SELECT ended_at, end_reason, created_at FROM security.character_revelations WHERE character_revelation_id = :r"
            ),
            {"r": e.revelation},
        ).one()
        untouched = c.execute(
            text(
                "SELECT (SELECT removed_at FROM security.access_group_memberships WHERE access_group_membership_id = :l), "
                "(SELECT revoked_at FROM security.resource_grants WHERE resource_grant_id = :g), "
                "(SELECT ended_at FROM security.character_revelations WHERE character_revelation_id = :r), "
                "(SELECT ls.code FROM security.access_groups ag JOIN core.lifecycle_statuses ls "
                " ON ls.lifecycle_status_id = ag.lifecycle_status_id WHERE ag.access_group_id = :og)"
            ),
            {"l": e.other_link, "g": e.other_grant, "r": e.other_revelation, "og": e.other_group},
        ).one()
    assert open_links == 0 and open_grants == 0
    assert revelation.ended_at is not None and revelation.end_reason == "access_group_deactivated"
    assert revelation.ended_at >= revelation.created_at
    assert tuple(untouched) == (None, None, None, "active")
    [audit] = audits_of(s, BY_NAME["deactivate"])
    changed = audit[5]
    links = changed["removed_access_group_memberships"]
    assert (
        links["count"] == 22
        and links["sample_truncated"] is True
        and len(links["sample_ids"]) == 20
    )
    assert links["sample_ids"] == sorted(
        links["sample_ids"], key=lambda value: uuid.UUID(value).int
    )


@pytest.mark.parametrize(
    "omitted", ("group_open_links", "group_active_grants", "group_live_revelations")
)
def test_h1_a_dependent_lock_call_that_is_omitted_is_a_500_and_nothing_persists(
    omitted: str,
    s: Scene,
    e: GEnv,
    pooled: Engine,
    pooled_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """*mutation (test-side)*, H-1: the handler's lock call for one dependent class never happens. The mechanism cannot see it
    (D-1: `EachLockedRow(complete=True)` treats a lock that never ran as empty), but the route's own comparison of the group's open
    dependents with the keys it received does: a fixed 500, a full rollback, the key reusable."""
    original = AuthorizationPlan.lock

    def wrapper(self: AuthorizationPlan, connection: Any, prelock: Any, params: Any) -> Any:
        if prelock.name == omitted:
            return ()
        return original(self, connection, prelock, params)

    key = new_key()
    before = snap(s, key)
    monkeypatch.setattr(AuthorizationPlan, "lock", wrapper)
    response = send(pooled_factory, s, BY_NAME["deactivate"], e, key=key)
    monkeypatch.undo()
    assert code(response) == 500 and error_of(response) == "internal_error", response.text
    assert snap(s, key) == before and idle_in_transaction(s.w.engine) == 0
    assert code(send(pooled_factory, s, BY_NAME["deactivate"], e, key=key)) == 200


@pytest.mark.parametrize("which", ("skipped_lock", "narrowed_lock"))
def test_an_add_whose_member_lock_call_is_skipped_or_narrowed_is_a_500_and_nothing_persists(
    which: str,
    s: Scene,
    e: GEnv,
    pooled: Engine,
    pooled_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """*mutation (test-side)*: one member's lock call never happens (or is made for another membership): the handler's
    cross-check of the member keys with the requested set refuses (a fixed 500), nothing persists, the key is reusable."""
    original = AuthorizationPlan.lock
    victim = e.members[2]

    def wrapper(self: AuthorizationPlan, connection: Any, prelock: Any, params: Any) -> Any:
        if prelock.name == "group_member_no_key_update" and params["member"] == victim:
            if which == "skipped_lock":
                return ()
            params = {**params, "member": e.members[3]}
        return original(self, connection, prelock, params)

    key = new_key()
    before = snap(s, key)
    monkeypatch.setattr(AuthorizationPlan, "lock", wrapper)
    response = send(pooled_factory, s, BY_NAME["add"], e, key=key)
    monkeypatch.undo()
    assert code(response) == 500 and error_of(response) == "internal_error", response.text
    assert snap(s, key) == before and idle_in_transaction(s.w.engine) == 0
    assert code(send(pooled_factory, s, BY_NAME["add"], e, key=key)) == 201


def test_an_add_with_an_insert_outside_the_request_or_a_second_insert_for_one_member_is_refused(
    s: Scene,
    e: GEnv,
    pooled: Engine,
    pooled_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """*mutation (test-side)* **commission**: an INSERT for an eligible membership outside the request is not in the evidence
    (`FK_NOT_LOCKED`); a second INSERT for one member is a duplicate carried value (`DUPLICATE_TARGET`). Both are refused before
    the driver, and nothing persists."""
    route = BY_NAME["add"]
    before = snap(s)
    outside = e.members[3]
    _wrap(monkeypatch, redirect={"insert_group_link": (2, {"member": outside})})
    response = send(pooled_factory, s, route, e)
    monkeypatch.undo()
    assert code(response) == 500 and snap(s) == before
    ids = sorted(e.ids(1, 2), key=lambda value: uuid.UUID(value).int)
    _wrap(monkeypatch, redirect={"insert_group_link": (2, {"member": uuid.UUID(ids[0])})})
    response = send(pooled_factory, s, route, e)
    monkeypatch.undo()
    assert code(response) == 500 and snap(s) == before


def test_an_audit_naming_another_link_twice_or_an_unconfirmed_id_is_refused(
    s: Scene,
    e: GEnv,
    pooled: Engine,
    pooled_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """*mutation (test-side)* **audit identity** (I-2): the second audit row naming the first link again is a duplicate target;
    an audit naming an id that is not a link this request confirmed is the wrong-identity refusal; each rolls back."""
    route = BY_NAME["add"]
    before = snap(s)
    original = AuthorizationPlan.execute
    seen_links: list[Any] = []

    def duplicate(self: AuthorizationPlan, connection: Any, step: Any, params: Any) -> Any:
        outcome = original(self, connection, step, params)
        if step.name == "insert_group_link":
            seen_links.append(outcome.keys[0][0])
        return outcome

    def audit_wrapper(mode: str) -> Any:
        count = {"audit": 0}

        def run(self: AuthorizationPlan, connection: Any, step: Any, params: Any) -> Any:
            if step.name == "audit_group_link_created":
                count["audit"] += 1
                if count["audit"] == 2:
                    params = {
                        **params,
                        "record": seen_links[0] if mode == "twice" else uuid.uuid4(),
                    }
            return duplicate(self, connection, step, params)

        return run

    for mode in ("twice", "unconfirmed"):
        seen_links.clear()
        monkeypatch.setattr(AuthorizationPlan, "execute", audit_wrapper(mode))
        response = send(pooled_factory, s, route, e)
        monkeypatch.undo()
        assert code(response) == 500, (mode, response.text)
        assert snap(s) == before, mode
    assert idle_in_transaction(s.w.engine) == 0


# --- timestamps (I-3, B-5) -----------------------------------------------------------------------------------------------------------


def test_a_future_dated_revelation_and_grant_are_clamped_and_the_commit_succeeds(
    s: Scene, e: GEnv, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route*, **labelled raw-SQL fixtures** (rows written outside any application path): a revelation whose `created_at` and a
    grant whose `granted_at` lie in the future are closed at exactly the stored value (`GREATEST(clock_timestamp(), ...)`), so
    `ck_..._ended_after_created` and `ck_resource_grants_revoked_after_granted` hold and the deactivation commits (a plain `now()`
    or `clock_timestamp()` would have been earlier and been refused). Ordinary rows are closed at a time after their creation;
    the group links close at `now()`."""
    with s.w.engine.begin() as c:
        c.execute(
            text("SET LOCAL session_replication_role = replica")
        )  # a future-dated fixture, outside the application
        c.execute(
            text(
                "UPDATE security.character_revelations SET created_at = now() + interval '30 days', "
                "updated_at = now() + interval '30 days' WHERE character_revelation_id = :r"
            ),
            {"r": e.revelation},
        )
        c.execute(
            text(
                "UPDATE security.resource_grants SET granted_at = now() + interval '30 days' "
                "WHERE resource_grant_id = :g"
            ),
            {"g": e.grant},
        )
    response = send(pooled_factory, s, BY_NAME["deactivate"], e)
    assert code(response) == 200, response.text
    with s.w.engine.connect() as c:
        revelation = c.execute(
            text(
                "SELECT created_at, ended_at FROM security.character_revelations WHERE character_revelation_id = :r"
            ),
            {"r": e.revelation},
        ).one()
        grant = c.execute(
            text(
                "SELECT granted_at, revoked_at FROM security.resource_grants WHERE resource_grant_id = :g"
            ),
            {"g": e.grant},
        ).one()
        link = c.execute(
            text(
                "SELECT added_at, removed_at FROM security.access_group_memberships WHERE access_group_membership_id = :l"
            ),
            {"l": e.link},
        ).one()
    assert revelation.ended_at == revelation.created_at  # clamped to the stored value
    assert grant.revoked_at == grant.granted_at
    assert link.removed_at is not None and link.removed_at >= link.added_at


def test_b5_the_reproduction_schedule_through_the_migrated_route_is_a_200_with_the_clamp(
    s: Scene, e: GEnv, pool: Pool
) -> None:
    """*route* (B-5, after): the schedule of `test_r01_s5e5_b5_reproduction.py` -- the deactivation's transaction starts first
    (parked before its group lock), a group-grantee grant then starts and commits, the deactivation resumes -- failed on the
    unmodified source with SQLSTATE 23514 on `ck_resource_grants_revoked_after_granted`. Through the migrated route the grant is
    revoked at `GREATEST(clock_timestamp(), granted_at)`: a 200, `revoked_at >= granted_at`, nothing refused. (It needs a pool
    with a second connection: the one-connection pool of the other tests would queue the grant behind the parked request.)"""
    character = make_new_character(s)
    with StatementGate(pool.engine, GROUP_U) as gate:
        request = run_in_thread(
            "deactivate",
            lambda: post(pool, s.w.owner, f"{s.w.base}/access-groups/{e.group}/deactivate", {}),
        )
        gate.wait_reached()
        started = rows(s.w.engine, "SELECT clock_timestamp() AS t")[0]["t"]
        while rows(s.w.engine, "SELECT clock_timestamp() AS t")[0][
            "t"
        ] - started < datetime.timedelta(milliseconds=300):
            time.sleep(0.05)  # the database clock passes the deactivation transaction's start
        grant = post(
            pool,
            s.w.owner,
            f"{s.w.base}/resource-grants",
            {
                "capability_code": "character.view_summary",
                "grantee_access_group_id": str(e.group),
                "character_id": str(character),
            },
        )
        gate.release()
        response = request.wait("the deactivation finishes")
    assert code(grant) == 201, grant.text
    assert code(response) == 200, response.text
    with s.w.engine.connect() as c:
        pairs = c.execute(
            text(
                "SELECT granted_at, revoked_at FROM security.resource_grants "
                "WHERE grantee_access_group_id = :g"
            ),
            {"g": e.group},
        ).all()
    assert len(pairs) == 2 and all(
        revoked is not None and revoked >= granted for granted, revoked in pairs
    )


def make_new_character(sc: Scene) -> uuid.UUID:
    with sc.w.engine.begin() as c:
        return make_character(c, sc.w.world_id, name=f"B5 {uuid.uuid4().hex[:6]}")


def test_removing_the_link_with_a_concurrent_re_add_waits_on_the_unique_index_then_succeeds(
    s: Scene, e: GEnv, pool: Pool
) -> None:
    """*race*: an add of the member whose open link a remove is closing (parked at its audit insert) queues on the unique index
    behind the remove (observed through `pg_blocking_pids`) and succeeds (201) once the remove commits: the closing UPDATE leaves
    the partial index."""
    with StatementGate(pool.engine, AUDIT_INSERT) as gate:
        request = run_in_thread(
            "remove",
            lambda: post(
                pool, s.m.manager_user, f"{s.w.base}/access-group-memberships/{e.link}/remove", {}
            ),
        )
        gate.wait_reached()
        assert gate.pid is not None
        readd = run_in_thread(
            "readd",
            lambda: post(
                pool,
                s.m.manager_user,
                f"{s.w.base}/access-groups/{e.group}/members",
                {"campaign_membership_ids": e.ids(0)},
            ),
        )
        deadline = time.monotonic() + 30
        waiting = None
        while time.monotonic() < deadline and waiting is None:
            blocked = rows(
                s.w.engine,
                "SELECT pid, query FROM pg_stat_activity WHERE datname = current_database() "
                "AND :holder = ANY(pg_blocking_pids(pid))",
                holder=gate.pid,
            )
            waiting = blocked[0] if blocked else None
            time.sleep(0.05)
        assert waiting is not None, "the add never queued behind the remove"
        assert re.search(r"INSERT INTO security\.access_group_memberships", waiting["query"])
        gate.release()
        removed = request.wait("the remove finishes")
        added = readd.wait("the add finishes")
    assert code(removed) == 200 and code(added) == 201, (removed.text, added.text)
