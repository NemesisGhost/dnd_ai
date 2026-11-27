# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""P15-C11-S02-T02: the OD-4a delegation of `character.assign_control` to an assistant GM (H1-H16, H20, H21).

Every case runs over real HTTP, through the R01 guard, on real committed data (the harness of the T01 file). The
concurrency cases (H17-H19) are in `test_assign_control_delegation_concurrency.py`, the migration (H22) in
`test_assign_control_delegation_migration.py`.

Test-first record (plan section 6): at the T02 baseline neither the table nor the routes exist, so every case but the
reveal half of H20 fails (a 404/405, or a missing relation). Refusal cases that an absent route could also satisfy
(the 404s) first assert a positive control: the same request shape succeeds for a valid recipient.
"""

import json
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError

from dnd_ai.domain.access import read_authority_snapshot, resolve_access_context
from tests.database.test_control_assignment_commands import (  # noqa: F401 - fixtures used by name
    Env,
    Person,
    _person,
    _tidy,
    assign_body,
    assign_path,
    build_env,
    env,
    get,
    post,
    replace_body,
    replace_path,
    revoke_path,
    seed,
)
from tests.database.test_r01_s2_profile_routes import (  # noqa: F401 - fixtures used by name
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
    make_campaign,
    make_campaign_membership,
    make_membership_role,
    make_role,
    make_role_capability,
    make_user,
    system_role_id,
)
from tests.r01_s5d_support import wait_lapsed

pytestmark = pytest.mark.database

Factory = Callable[[uuid.UUID], TestClient]

GRANT_COMMAND = "delegate_character_assign_control"
REVOKE_COMMAND = "revoke_character_assign_control_delegation"
DELEGATION_COMMANDS = (GRANT_COMMAND, REVOKE_COMMAND)
REFUSAL = "character_assign_control_required"
CAPABILITY = "character.assign_control"


@pytest.fixture(autouse=True)
def _tidy_delegation_audit(w: World) -> Any:
    yield
    with w.engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        cleanup.execute(
            text("DELETE FROM audit.change_log WHERE world_id = :w AND command_name = ANY(:c)"),
            {"w": w.world_id, "c": list(DELEGATION_COMMANDS)},
        )


# --- requests and reads ---------------------------------------------------------------------------------------


def grant_path(sc: Scene) -> str:
    return f"{sc.w.base}/assign-control-delegations"


def revoke_delegation_path(sc: Scene, grantee: uuid.UUID) -> str:
    return f"{grant_path(sc)}/{grantee}/revoke"


def grant(
    factory: Factory,
    sc: Scene,
    actor: uuid.UUID,
    grantee: Person | uuid.UUID,
    reason: Any = "Trusted to run the table",
) -> Any:
    member = grantee.membership if isinstance(grantee, Person) else grantee
    body: dict[str, Any] = {"grantee_campaign_membership_id": str(member)}
    if reason is not None:
        body["reason"] = reason
    return post(factory, actor, grant_path(sc), body)


def revoke(
    factory: Factory,
    sc: Scene,
    actor: uuid.UUID,
    grantee: Person | uuid.UUID,
    reason: Any = "No longer needed",
) -> Any:
    member = grantee.membership if isinstance(grantee, Person) else grantee
    body: dict[str, Any] = {} if reason is None else {"reason": reason}
    return post(factory, actor, revoke_delegation_path(sc, member), body)


def delegations(sc: Scene) -> list[dict[str, Any]]:
    with sc.w.engine.connect() as c:
        return [
            dict(r)
            for r in c.execute(
                text(
                    "SELECT character_assign_control_delegation_id AS id, "
                    "grantee_campaign_membership_id AS grantee, assistant_gm_membership_role_id AS bound_role, "
                    "granted_by_membership_id AS granted_by, reason, revoked_at IS NULL AS live, "
                    "revoked_by_membership_id AS revoked_by, revocation_reason, end_reason "
                    "FROM security.character_assign_control_delegations WHERE campaign_id = :c "
                    "ORDER BY granted_at, character_assign_control_delegation_id"
                ),
                {"c": sc.w.campaign_id},
            ).mappings()
        ]


def audits(sc: Scene) -> dict[str, int]:
    with sc.w.engine.connect() as c:
        rows = c.execute(
            text(
                "SELECT command_name, count(*) FROM audit.change_log "
                "WHERE world_id = :w AND command_name = ANY(:c) GROUP BY command_name"
            ),
            {"w": sc.w.world_id, "c": list(DELEGATION_COMMANDS)},
        ).all()
    return {name: int(n) for name, n in rows}


def assistant_row(sc: Scene, who: Person) -> uuid.UUID:
    """The person's live built-in `assistant_gm` assignment."""
    with sc.w.engine.connect() as c:
        return c.execute(
            text(
                "SELECT mr.membership_role_id FROM security.membership_roles mr "
                "JOIN security.roles r ON r.role_id = mr.role_id "
                "WHERE mr.campaign_membership_id = :m AND r.campaign_id IS NULL AND r.code = 'assistant_gm' "
                "AND mr.revoked_at IS NULL"
            ),
            {"m": who.membership},
        ).scalar_one()


def seed_delegation(sc: Scene, who: Person, by: uuid.UUID | None = None) -> uuid.UUID:
    """A live delegation bound to the person's live assistant GM row, written directly (a fixture, not the route)."""
    with sc.w.engine.begin() as c:
        granter = by
        if granter is None:
            granter = c.execute(
                text(
                    "SELECT mr.campaign_membership_id FROM security.membership_roles mr "
                    "JOIN security.roles r ON r.role_id = mr.role_id "
                    "JOIN security.campaign_memberships cm ON cm.campaign_membership_id = mr.campaign_membership_id "
                    "WHERE cm.campaign_id = :c AND r.code = 'campaign_owner' AND r.campaign_id IS NULL "
                    "AND mr.revoked_at IS NULL LIMIT 1"
                ),
                {"c": sc.w.campaign_id},
            ).scalar_one()
        return c.execute(
            text(
                "INSERT INTO security.character_assign_control_delegations "
                "(campaign_id, grantee_campaign_membership_id, assistant_gm_membership_role_id, "
                "granted_by_membership_id, reason) VALUES (:c, :g, :r, :by, 'seeded') "
                "RETURNING character_assign_control_delegation_id"
            ),
            {
                "c": sc.w.campaign_id,
                "g": who.membership,
                "r": assistant_row(sc, who),
                "by": granter,
            },
        ).scalar_one()


def lapse_assistant_role(sc: Scene, who: Person) -> uuid.UUID:
    row = assistant_row(sc, who)
    with sc.w.engine.begin() as c:
        c.execute(
            text(
                "UPDATE security.membership_roles SET revoked_at = now() WHERE membership_role_id = :r"
            ),
            {"r": row},
        )
    return row


def keep_view(sc: Scene, who: Person) -> None:
    """An observer role beside the one the case ends, so the route requirement (`campaign.view`) still passes and the
    refusal under test is the operation's own, not the campaign route's."""
    with sc.w.engine.begin() as c:
        make_membership_role(c, who.membership, sc.observer)


def regrant_assistant_role(sc: Scene, who: Person) -> uuid.UUID:
    with sc.w.engine.begin() as c:
        return make_membership_role(c, who.membership, system_role_id(c, "assistant_gm"))


def second_assistant(sc: Scene, label: str = "Second Assistant") -> Person:
    with sc.w.engine.begin() as c:
        return _person(c, sc, label, system_role_id(c, "assistant_gm"))


def custom_manager(sc: Scene) -> uuid.UUID:
    """A member whose custom role holds `access.manage`, `canon.edit` and `campaign.view`: it can see the campaign but
    holds no assignment authority."""
    with sc.w.engine.begin() as c:
        user = make_user(c, "Delegation Custom Manager")
        membership = make_campaign_membership(c, sc.w.campaign_id, user)
        role = make_role(c, campaign_id=sc.w.campaign_id)
        for capability in ("access.manage", "canon.edit", "campaign.view"):
            make_role_capability(
                c,
                role,
                c.execute(
                    text("SELECT capability_id FROM security.capabilities WHERE code = :c"),
                    {"c": capability},
                ).scalar_one(),
            )
        make_membership_role(c, membership, role)
    return user


def gm_person(sc: Scene) -> Person:
    return Person(sc.w.gm_user, sc.w.gm_membership)


def live_assignments(sc: Scene) -> int:
    with sc.w.engine.connect() as c:
        return int(
            c.execute(
                text(
                    "SELECT count(*) FROM security.membership_character_relationships "
                    "WHERE campaign_id = :c AND is_control_assignment AND revoked_at IS NULL"
                ),
                {"c": sc.w.campaign_id},
            ).scalar_one()
        )


def _snapshot(sc: Scene, user: uuid.UUID, **kw: Any) -> Any:
    with sc.w.engine.connect() as c:
        return read_authority_snapshot(
            c, user_id=user, campaign_id=sc.w.campaign_id, with_assign_control=True, **kw
        )


# --- H1, H2: grants -------------------------------------------------------------------------------------------


def test_h1_the_owner_delegates_to_an_assistant_gm_bound_to_the_role_row(
    s: Scene, env: Env, pooled_factory: Factory
) -> None:
    response = grant(pooled_factory, s, env.owner.user, env.assistant)
    assert code(response) == 201, response.text
    body = response.json()
    assert body["granted"] is True
    assert body["grantee_campaign_membership_id"] == str(env.assistant.membership)
    (row,) = delegations(s)
    assert str(row["id"]) == body["character_assign_control_delegation_id"]
    assert row["live"] is True and row["end_reason"] is None
    assert row["grantee"] == env.assistant.membership
    assert row["bound_role"] == assistant_row(s, env.assistant)
    assert row["granted_by"] == env.owner.membership and row["reason"] == "Trusted to run the table"
    assert audits(s) == {GRANT_COMMAND: 1}
    with s.w.engine.connect() as c:
        record = c.execute(
            text(
                "SELECT table_name, record_id FROM audit.change_log "
                "WHERE world_id = :w AND command_name = :n"
            ),
            {"w": s.w.world_id, "n": GRANT_COMMAND},
        ).one()
    assert record[0] == "character_assign_control_delegations" and record[1] == row["id"]


def test_h2_a_built_in_gm_delegates(s: Scene, env: Env, pooled_factory: Factory) -> None:
    response = grant(pooled_factory, s, s.w.gm_user, env.assistant)
    assert code(response) == 201, response.text
    (row,) = delegations(s)
    assert row["granted_by"] == s.w.gm_membership and row["live"] is True


# --- H3, H4, H5: grant refusals ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "reason", [None, "", "   ", "x" * 1001], ids=["missing", "empty", "blank", "long"]
)
def test_h3_a_missing_blank_or_overlong_reason_is_422_and_writes_nothing(
    s: Scene, env: Env, pooled_factory: Factory, reason: Any
) -> None:
    refused = grant(pooled_factory, s, env.owner.user, env.assistant, reason=reason)
    assert code(refused) == 422, refused.text
    assert delegations(s) == [] and audits(s) == {}
    # the positive control: the same request with a valid reason is the success
    assert code(grant(pooled_factory, s, env.owner.user, env.assistant)) == 201


@pytest.mark.parametrize("who", ["player", "observer", "gm", "owner"])
def test_h4_a_recipient_without_assistant_gm_is_409(
    s: Scene, env: Env, pooled_factory: Factory, who: str
) -> None:
    recipient = {
        "player": env.player,
        "observer": env.observer,
        "gm": gm_person(s),
        "owner": env.owner,
    }[who]
    refused = grant(pooled_factory, s, env.owner.user, recipient)
    assert (
        code(refused) == 409 and error_of(refused) == "assign_control_recipient_not_assistant_gm"
    ), refused.text
    assert delegations(s) == [] and audits(s) == {}
    assert code(grant(pooled_factory, s, env.owner.user, env.assistant)) == 201


def test_h4_an_expired_assistant_gm_row_is_not_a_recipient(
    s: Scene, env: Env, pooled_factory: Factory
) -> None:
    with s.w.engine.begin() as c:
        c.execute(
            text(
                "UPDATE security.membership_roles SET expires_at = clock_timestamp() + interval '2 seconds' "
                "WHERE membership_role_id = :r"
            ),
            {"r": assistant_row(s, env.assistant)},
        )
    wait_lapsed(s.w.engine, assistant_row(s, env.assistant))
    refused = grant(pooled_factory, s, env.owner.user, env.assistant)
    assert code(refused) == 409 and error_of(refused) == "assign_control_recipient_not_assistant_gm"
    assert delegations(s) == []


def test_h5_another_campaigns_membership_is_404_and_an_ended_one_is_409(
    s: Scene, env: Env, pooled_factory: Factory
) -> None:
    with s.w.engine.begin() as c:
        timeline = c.execute(
            text("SELECT timeline_id FROM campaign.campaigns WHERE campaign_id = :c"),
            {"c": s.w.campaign_id},
        ).scalar_one()
        other_campaign = make_campaign(c, timeline, "H5 other campaign")
        other_owner = make_campaign_membership(c, other_campaign, make_user(c, "H5 other owner"))
        make_membership_role(c, other_owner, s.owner)
        stranger = make_campaign_membership(c, other_campaign, make_user(c, "H5 stranger"))
        make_membership_role(c, stranger, system_role_id(c, "assistant_gm"))
    # the positive control: a valid recipient in this campaign succeeds with the same request shape
    assert code(grant(pooled_factory, s, env.owner.user, env.assistant)) == 201
    missing = grant(pooled_factory, s, env.owner.user, stranger)
    assert code(missing) == 404, missing.text
    assert len(delegations(s)) == 1
    second = second_assistant(s)
    with s.w.engine.begin() as c:
        c.execute(
            text(
                "UPDATE security.campaign_memberships SET ended_at = now() WHERE campaign_membership_id = :m"
            ),
            {"m": second.membership},
        )
    ended = grant(pooled_factory, s, env.owner.user, second)
    assert code(ended) == 409, ended.text
    assert len(delegations(s)) == 1


# --- H6, H11, H15: who may grant or revoke ---------------------------------------------------------------------


def test_h6_only_an_owner_or_gm_may_grant(s: Scene, env: Env, pooled_factory: Factory) -> None:
    delegated = second_assistant(s, "Delegated Assistant")
    seed_delegation(s, delegated)
    seed(s, env.p1, env.character, "co_controller", "ongoing")
    callers = {
        "custom access.manage holder": custom_manager(s),
        "assistant without a delegation": env.assistant.user,
        "delegated assistant": delegated.user,
        "controller": env.p1.user,
        "player": env.player.user,
        "observer": env.observer.user,
    }
    for label, user in callers.items():
        refused = grant(pooled_factory, s, user, env.assistant)
        assert code(refused) == 403 and error_of(refused) == REFUSAL, (label, refused.text)
    assert len(delegations(s)) == 1  # only the seeded one
    assert audits(s) == {}
    assert code(grant(pooled_factory, s, env.owner.user, env.assistant)) == 201


def test_h11_a_delegated_assistant_gm_cannot_redelegate(
    s: Scene, env: Env, pooled_factory: Factory
) -> None:
    seed_delegation(s, env.assistant)
    target = second_assistant(s)
    # the positive control: the delegated assistant does hold the assign authority
    assert (
        code(
            post(
                pooled_factory,
                env.assistant.user,
                assign_path(s, env.character),
                assign_body(env.p1, "co_controller"),
            )
        )
        == 201
    )
    refused = grant(pooled_factory, s, env.assistant.user, target)
    assert code(refused) == 403 and error_of(refused) == REFUSAL, refused.text
    assert len(delegations(s)) == 1 and audits(s) == {}


def test_h15_a_revoke_by_the_holder_another_assistant_or_a_player_is_403(
    s: Scene, env: Env, pooled_factory: Factory
) -> None:
    seed_delegation(s, env.assistant)
    other = second_assistant(s)
    seed_delegation(s, other)
    for user in (env.assistant.user, other.user, env.player.user, custom_manager(s)):
        refused = revoke(pooled_factory, s, user, env.assistant)
        assert code(refused) == 403 and error_of(refused) == REFUSAL, refused.text
    assert all(row["live"] for row in delegations(s)) and audits(s) == {}
    assert code(revoke(pooled_factory, s, env.owner.user, env.assistant)) == 200


# --- H7: a repeat grant -----------------------------------------------------------------------------------------


def test_h7_a_repeat_grant_bound_to_the_current_role_row_is_200_with_no_write(
    s: Scene, env: Env, pooled_factory: Factory
) -> None:
    first = grant(pooled_factory, s, env.owner.user, env.assistant)
    assert code(first) == 201
    again = grant(pooled_factory, s, s.w.gm_user, env.assistant, reason="A different reason")
    assert code(again) == 200, again.text
    assert again.json()["granted"] is False
    assert (
        again.json()["character_assign_control_delegation_id"]
        == first.json()["character_assign_control_delegation_id"]
    )
    (row,) = delegations(s)
    assert row["reason"] == "Trusted to run the table" and row["granted_by"] == env.owner.membership
    assert audits(s) == {GRANT_COMMAND: 1}


# --- H8: the bound role row's liveness ---------------------------------------------------------------------------


def test_h8_a_lapsed_role_ends_the_authority_and_a_regranted_role_does_not_restore_it(
    s: Scene, env: Env, pooled_factory: Factory
) -> None:
    assert code(grant(pooled_factory, s, env.owner.user, env.assistant)) == 201
    path = assign_path(s, env.character)
    first = post(pooled_factory, env.assistant.user, path, assign_body(env.p1, "co_controller"))
    assert code(first) == 201, first.text  # the positive control: in force while the role is live
    keep_view(s, env.assistant)
    old_role = lapse_assistant_role(s, env.assistant)
    refused = post(pooled_factory, env.assistant.user, path, assign_body(env.p2, "co_controller"))
    assert code(refused) == 403 and error_of(refused) == REFUSAL
    read = get(pooled_factory, env.owner.user, grant_path(s))
    assert code(read) == 200, read.text
    (row,) = read.json()["delegations"]
    assert row["in_force"] is False
    assert row["status_text"] == "not in force: assistant GM role ended"
    # the role is granted again: a new row, which the old delegation is not bound to
    new_role = regrant_assistant_role(s, env.assistant)
    assert new_role != old_role
    still = post(pooled_factory, env.assistant.user, path, assign_body(env.p2, "co_controller"))
    assert code(still) == 403 and error_of(still) == REFUSAL
    # a fresh grant closes the lapsed row and inserts a new one bound to the new role row
    fresh = grant(pooled_factory, s, env.owner.user, env.assistant)
    assert code(fresh) == 201 and fresh.json()["granted"] is True, fresh.text
    closed, live = delegations(s)
    assert closed["live"] is False and closed["end_reason"] == "assistant_gm_assignment_lapsed"
    assert closed["revoked_by"] is None and closed["revocation_reason"] is None
    assert live["live"] is True and live["bound_role"] == new_role
    back = post(pooled_factory, env.assistant.user, path, assign_body(env.p2, "co_controller"))
    assert code(back) == 201, back.text
    assert audits(s) == {GRANT_COMMAND: 2}


def test_h8_an_expired_role_row_ends_the_authority_without_a_hook(
    s: Scene, env: Env, pooled_factory: Factory
) -> None:
    seed_delegation(s, env.assistant)
    keep_view(s, env.assistant)
    path = assign_path(s, env.character)
    assert code(post(pooled_factory, env.assistant.user, path, assign_body(env.p1))) == 201
    with s.w.engine.begin() as c:
        c.execute(
            text(
                "UPDATE security.membership_roles SET expires_at = clock_timestamp() + interval '2 seconds' "
                "WHERE membership_role_id = :r"
            ),
            {"r": assistant_row(s, env.assistant)},
        )
    wait_lapsed(s.w.engine, assistant_row(s, env.assistant))
    refused = post(pooled_factory, env.assistant.user, path, assign_body(env.p2))
    assert code(refused) == 403 and error_of(refused) == REFUSAL
    (row,) = delegations(s)
    assert row["live"] is True  # nothing closed it: it simply is not in force


# --- H9, H10: the holder's use -------------------------------------------------------------------------------------


def test_h9_the_delegated_assistant_assigns_replaces_and_revokes_audited_as_themself(
    s: Scene, env: Env, pooled_factory: Factory
) -> None:
    assert code(grant(pooled_factory, s, env.owner.user, env.assistant)) == 201
    me = env.assistant
    primary = post(
        pooled_factory,
        me.user,
        assign_path(s, env.character),
        assign_body(env.p1, "primary_controller"),
    )
    assert code(primary) == 201, primary.text
    replaced = post(pooled_factory, me.user, replace_path(s, env.character), replace_body(env.p2))
    assert code(replaced) == 201, replaced.text
    co = post(pooled_factory, me.user, assign_path(s, env.character), assign_body(env.p3))
    assert code(co) == 201, co.text
    # the same authority reads the character's control (T01 read, R-7)
    read = get(
        pooled_factory, me.user, f"{s.w.base}/characters/{env.character}/control-assignments"
    )
    assert code(read) == 200, read.text
    assert read.json()["controller"]["campaign_membership_id"] == str(env.p2.membership)
    revoked = post(
        pooled_factory,
        me.user,
        revoke_path(s, uuid.UUID(co.json()["control_assignment_id"])),
        {"reason": "done"},
    )
    assert code(revoked) == 200 and revoked.json()["revoked"] is True
    with s.w.engine.connect() as c:
        actors = set(
            c.execute(
                text(
                    "SELECT actor_user_id FROM audit.change_log WHERE world_id = :w "
                    "AND command_name = ANY(:n)"
                ),
                {
                    "w": s.w.world_id,
                    "n": [
                        "assign_character_control",
                        "replace_primary_controller",
                        "revoke_character_control",
                    ],
                },
            ).scalars()
        )
        granted_by = set(
            c.execute(
                text(
                    "SELECT DISTINCT granted_by_membership_id FROM security.membership_character_relationships "
                    "WHERE campaign_id = :c AND is_control_assignment"
                ),
                {"c": s.w.campaign_id},
            ).scalars()
        )
    assert actors == {me.user} and granted_by == {me.membership}


def test_h10_the_same_assistant_gm_is_refused_in_another_campaign(
    s: Scene, env: Env, pooled_factory: Factory
) -> None:
    assert code(grant(pooled_factory, s, env.owner.user, env.assistant)) == 201
    with s.w.engine.begin() as c:
        timeline = c.execute(
            text("SELECT timeline_id FROM campaign.campaigns WHERE campaign_id = :c"),
            {"c": s.w.campaign_id},
        ).scalar_one()
        other = make_campaign(c, timeline, "H10 campaign B")
        owner_b = make_campaign_membership(c, other, make_user(c, "H10 owner B"))
        make_membership_role(c, owner_b, s.owner)
        in_b = make_campaign_membership(c, other, env.assistant.user)
        make_membership_role(c, in_b, system_role_id(c, "assistant_gm"))
        target_b = make_campaign_membership(c, other, make_user(c, "H10 player B"))
        make_membership_role(c, target_b, s.player)
    # the positive control: in campaign A the same user succeeds
    assert (
        code(
            post(
                pooled_factory,
                env.assistant.user,
                assign_path(s, env.character),
                assign_body(env.p1),
            )
        )
        == 201
    )
    refused = post(
        pooled_factory,
        env.assistant.user,
        f"/campaigns/{other}/characters/{env.character}/control-assignments",
        {
            "campaign_membership_id": str(target_b),
            "role": "co_controller",
            "assignment_period_kind": "ongoing",
        },
    )
    assert code(refused) == 403 and error_of(refused) == REFUSAL, refused.text
    snapshot_b = None
    with s.w.engine.connect() as c:
        snapshot_b = read_authority_snapshot(
            c, user_id=env.assistant.user, campaign_id=other, with_assign_control=True
        )
    assert snapshot_b.assign_control_authority == "none"


# --- H12: the capability guard -----------------------------------------------------------------------------------


def _capability_id(c: Connection) -> uuid.UUID:
    return c.execute(
        text("SELECT capability_id FROM security.capabilities WHERE code = :c"), {"c": CAPABILITY}
    ).scalar_one()


def test_h12_no_role_relationship_type_or_resource_grant_may_carry_the_capability(
    s: Scene, env: Env, pooled_factory: Factory
) -> None:
    with s.w.engine.connect() as c:
        capability = _capability_id(c)  # the positive control: the vocabulary row exists
        built_in = system_role_id(c, "assistant_gm")
        relationship_type = c.execute(
            text(
                "SELECT character_relationship_type_id FROM security.character_relationship_types LIMIT 1"
            )
        ).scalar_one()
    with s.w.engine.begin() as c:
        custom_role = c.execute(
            text(
                "INSERT INTO security.roles (campaign_id, code, display_name) VALUES (:c, 'h12_custom', 'H12') RETURNING role_id"
            ),
            {"c": s.w.campaign_id},
        ).scalar_one()
    attempts = {
        "built-in role": (
            "INSERT INTO security.role_capabilities (role_id, capability_id) VALUES (:role, :cap)",
            {"role": built_in, "cap": capability},
        ),
        "custom role": (
            "INSERT INTO security.role_capabilities (role_id, capability_id) VALUES (:role, :cap)",
            {"role": custom_role, "cap": capability},
        ),
        "relationship type": (
            "INSERT INTO security.character_relationship_type_capabilities "
            "(character_relationship_type_id, capability_id) VALUES (:type, :cap)",
            {"type": relationship_type, "cap": capability},
        ),
        "resource grant": (
            "INSERT INTO security.resource_grants (campaign_id, timeline_id, grantee_campaign_membership_id, "
            "capability_id, effect, character_id) "
            "SELECT :c, c.timeline_id, :g, :cap, 'allow', :ch FROM campaign.campaigns c WHERE c.campaign_id = :c",
            {"c": s.w.campaign_id, "g": env.p1.membership, "cap": capability, "ch": env.character},
        ),
    }
    for label, (statement, params) in attempts.items():
        with pytest.raises(DBAPIError, match=CAPABILITY), s.w.engine.begin() as c:
            c.execute(text(statement), params)
        assert label
    # the route refuses it too, with a client error and no grant
    response = post(
        pooled_factory,
        env.owner.user,
        f"{s.w.base}/resource-grants",
        {
            "capability_code": CAPABILITY,
            "grantee_campaign_membership_id": str(env.p1.membership),
            "character_id": str(env.character),
        },
    )
    assert 400 <= code(response) < 500, response.text


# --- H13, H14, H16: revocation ----------------------------------------------------------------------------------


def test_h13_a_gm_revokes_with_a_reason_and_the_holders_assignments_stay_in_effect(
    s: Scene, env: Env, pooled_factory: Factory
) -> None:
    assert code(grant(pooled_factory, s, env.owner.user, env.assistant)) == 201
    made = post(
        pooled_factory,
        env.assistant.user,
        assign_path(s, env.character),
        assign_body(env.p1, "primary_controller"),
    )
    assert code(made) == 201
    revoked = revoke(pooled_factory, s, s.w.gm_user, env.assistant, reason="Handing back")
    assert code(revoked) == 200 and revoked.json()["revoked"] is True, revoked.text
    (row,) = delegations(s)
    assert row["live"] is False and row["end_reason"] == "revoked"
    assert row["revoked_by"] == s.w.gm_membership and row["revocation_reason"] == "Handing back"
    assert audits(s) == {GRANT_COMMAND: 1, REVOKE_COMMAND: 1}
    refused = post(
        pooled_factory, env.assistant.user, assign_path(s, env.character), assign_body(env.p2)
    )
    assert code(refused) == 403 and error_of(refused) == REFUSAL
    # T86: what the holder made is untouched and in effect
    assert live_assignments(s) == 1
    with s.w.engine.connect() as c:
        context = resolve_access_context(c, user_id=env.p1.user, campaign_id=s.w.campaign_id)
    assert context is not None and env.character in context.character_capabilities
    read = get(
        pooled_factory,
        env.owner.user,
        f"{s.w.base}/characters/{env.character}/control-assignments",
    )
    assert read.json()["controller"]["campaign_membership_id"] == str(env.p1.membership)


def test_h13_a_revoke_needs_a_reason(s: Scene, env: Env, pooled_factory: Factory) -> None:
    seed_delegation(s, env.assistant)
    for reason in (None, "", "  ", "x" * 1001):
        refused = revoke(pooled_factory, s, env.owner.user, env.assistant, reason=reason)
        assert code(refused) == 422, refused.text
    assert delegations(s)[0]["live"] is True and audits(s) == {}
    assert code(revoke(pooled_factory, s, env.owner.user, env.assistant)) == 200


def test_h14_a_revoke_with_no_live_delegation_is_a_200_no_op(
    s: Scene, env: Env, pooled_factory: Factory
) -> None:
    noop = revoke(pooled_factory, s, env.owner.user, env.assistant)
    assert code(noop) == 200 and noop.json()["revoked"] is False, noop.text
    assert delegations(s) == [] and audits(s) == {}
    # a closed one is no live delegation either
    seed_delegation(s, env.assistant)
    assert code(revoke(pooled_factory, s, env.owner.user, env.assistant)) == 200
    again = revoke(pooled_factory, s, env.owner.user, env.assistant)
    assert code(again) == 200 and again.json()["revoked"] is False
    assert audits(s) == {REVOKE_COMMAND: 1}


def test_h14_another_campaigns_membership_is_a_404_on_revoke(
    s: Scene, env: Env, pooled_factory: Factory
) -> None:
    assert code(revoke(pooled_factory, s, env.owner.user, env.assistant)) == 200  # the control
    missing = revoke(pooled_factory, s, env.owner.user, uuid.uuid4())
    assert code(missing) == 404, missing.text


def test_h16_a_delegation_granted_by_a_gm_survives_that_gm_losing_the_role(
    s: Scene, env: Env, pooled_factory: Factory
) -> None:
    assert code(grant(pooled_factory, s, s.w.gm_user, env.assistant)) == 201
    keep_view(s, gm_person(s))
    with s.w.engine.begin() as c:
        c.execute(
            text(
                "UPDATE security.membership_roles SET revoked_at = now() WHERE membership_role_id = :r"
            ),
            {"r": s.w.gm_role},
        )
    # the grantor no longer holds the authority (the control) ...
    gone = grant(pooled_factory, s, s.w.gm_user, env.assistant)
    assert code(gone) == 403 and error_of(gone) == REFUSAL
    # ... and the delegation it granted is still in force
    kept = post(
        pooled_factory, env.assistant.user, assign_path(s, env.character), assign_body(env.p1)
    )
    assert code(kept) == 201, kept.text
    (row,) = delegations(s)
    assert row["live"] is True and row["granted_by"] == s.w.gm_membership


# --- H20: distinct from reveal delegation ------------------------------------------------------------------------


def test_h20_reveal_half_a_reveal_delegation_confers_no_assignment_authority_of_its_own(
    s: Scene, env: Env, pooled_factory: Factory
) -> None:
    """*Baseline guard*: passes before T02. A reveal delegation binds a GM to `character.reveal`; the GM's assignment
    authority is the GM role's own and the snapshot names it `gm`, never a delegation, and an assistant GM gains
    nothing from the reveal routes."""
    with pooled_factory(env.owner.user) as client:
        granted = client.post(
            f"{s.w.base}/reveal-delegations",
            json={
                "grantee_campaign_membership_id": str(s.w.gm_membership),
                "reason": "H20 reveal half",
            },
        )
    assert code(granted) == 200, granted.text
    with s.w.engine.connect() as c:
        reveal = read_authority_snapshot(
            c,
            user_id=s.w.gm_user,
            campaign_id=s.w.campaign_id,
            with_reveal=True,
            with_assign_control=True,
        )
    assert reveal.reveal_authority == "delegation"
    assert reveal.assign_control_authority == "gm"
    # an assistant GM is refused by the reveal routes, and holds no assign authority without a delegation
    with pooled_factory(env.assistant.user) as client:
        refused = client.post(
            f"{s.w.base}/reveal-delegations",
            json={
                "grantee_campaign_membership_id": str(s.w.gm_membership),
                "reason": "should be refused",
            },
        )
    assert code(refused) == 403, refused.text
    assert _snapshot(s, env.assistant.user).assign_control_authority == "none"


def test_h20_an_assign_delegation_confers_nothing_else(
    s: Scene, env: Env, pooled_factory: Factory
) -> None:
    with s.w.engine.connect() as c:
        before = resolve_access_context(c, user_id=env.assistant.user, campaign_id=s.w.campaign_id)
    assert before is not None
    assert code(grant(pooled_factory, s, env.owner.user, env.assistant)) == 201
    with s.w.engine.connect() as c:
        after = resolve_access_context(c, user_id=env.assistant.user, campaign_id=s.w.campaign_id)
        both = read_authority_snapshot(
            c,
            user_id=env.assistant.user,
            campaign_id=s.w.campaign_id,
            with_reveal=True,
            with_assign_control=True,
        )
    assert after is not None
    # not character.reveal, not access.manage, not an extra read, not a controller operation
    assert both.assign_control_authority == "delegation"
    assert both.reveal_authority == "none"
    assert after.role_capabilities == before.role_capabilities
    assert (
        "access.manage" not in after.role_capabilities
        and "character.reveal" not in after.role_capabilities
    )
    assert after.character_capabilities == before.character_capabilities
    assert after.control_assignments == before.control_assignments
    # the reveal routes and the membership routes still refuse it
    with pooled_factory(env.assistant.user) as client:
        reveal = client.post(
            f"{s.w.base}/reveal-delegations",
            json={
                "grantee_campaign_membership_id": str(s.w.gm_membership),
                "reason": "should be refused",
            },
        )
        members = client.post(
            f"{s.w.base}/memberships/{env.p1.membership}/end",
        )
    assert code(reveal) == 403 and code(members) == 403
    # and the reveal delegation of a GM writes no assign delegation (and the reverse)
    with pooled_factory(env.owner.user) as client:
        granted = client.post(
            f"{s.w.base}/reveal-delegations",
            json={
                "grantee_campaign_membership_id": str(s.w.gm_membership),
                "reason": "H20 distinct",
            },
        )
    assert code(granted) == 200
    assert len(delegations(s)) == 1
    with s.w.engine.connect() as c:
        reveal_rows = c.execute(
            text(
                "SELECT count(*) FROM security.character_reveal_delegations WHERE campaign_id = :c"
            ),
            {"c": s.w.campaign_id},
        ).scalar_one()
    assert reveal_rows == 1


# --- H21: the read -----------------------------------------------------------------------------------------------


def test_h21_owner_and_gm_read_live_and_closed_rows_with_status_reasons_and_actors(
    s: Scene, env: Env, pooled_factory: Factory
) -> None:
    other = second_assistant(s, "Closed Assistant")
    assert code(grant(pooled_factory, s, env.owner.user, other, reason="first")) == 201
    assert code(revoke(pooled_factory, s, s.w.gm_user, other, reason="stepped back")) == 200
    assert code(grant(pooled_factory, s, s.w.gm_user, env.assistant, reason="second")) == 201
    for reader in (env.owner.user, s.w.gm_user):
        read = get(pooled_factory, reader, grant_path(s))
        assert code(read) == 200, read.text
        body = read.json()
        assert body["truncated"] is False
        rows = body["delegations"]
        assert [r["grantee_campaign_membership_id"] for r in rows] == [
            str(env.assistant.membership),
            str(other.membership),
        ]  # newest first
        live, closed = rows
        assert live["in_force"] is True and live["status"] == "in_force"
        assert live["reason"] == "second" and live["granted_by"]
        assert closed["in_force"] is False and closed["status"] == "revoked"
        assert closed["reason"] == "first" and closed["revocation_reason"] == "stepped back"
        assert closed["revoked_by"] and closed["end_reason"] == "revoked"
        assert closed["display_name"] and live["display_name"]


def test_h21_anyone_else_is_refused_with_one_fixed_403(
    s: Scene, env: Env, pooled_factory: Factory
) -> None:
    delegated = second_assistant(s, "Delegated Reader")
    seed_delegation(s, delegated)
    seed(s, env.p1, env.character, "primary_controller", "ongoing")
    assert code(get(pooled_factory, env.owner.user, grant_path(s))) == 200  # the positive control
    bodies = set()
    for user in (
        delegated.user,
        env.assistant.user,
        custom_manager(s),
        env.p1.user,
        env.player.user,
        env.observer.user,
    ):
        refused = get(pooled_factory, user, grant_path(s))
        assert code(refused) == 403 and error_of(refused) == REFUSAL, refused.text
        bodies.add(
            json.dumps(
                {k: v for k, v in refused.json()["error"].items() if k != "correlation_id"},
                sort_keys=True,
            )
        )
    assert len(bodies) == 1
    stranger = make_stranger(s)
    assert code(get(pooled_factory, stranger, grant_path(s))) == 404


def make_stranger(sc: Scene) -> uuid.UUID:
    with sc.w.engine.begin() as c:
        return make_user(c, "H21 stranger")
