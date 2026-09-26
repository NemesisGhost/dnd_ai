"""World-ownership-scope invariants (ADR 0014,
docs/architecture/DATABASE_MODEL.md §19.9): `dnd_ai.commands.ownership` and
`dnd_ai.domain.access.is_world_administrator`, plus the database
constraints backing them (per-scope slug uniqueness, `ownership_scope_id
NOT NULL`).

Deliberately proves ownership is independent of every other authorization
primitive in this codebase — campaign membership/roles
(`security.campaign_memberships`/`.roles`) and
`security.users.is_platform_administrator` — never combined with it, in
either direction.
"""

import uuid

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError

from dnd_ai.commands.ownership import (
    LastActiveOwnerError,
    OwnershipScopeMembershipNotFoundError,
    add_ownership_scope_member,
    create_ownership_scope,
    remove_ownership_scope_member,
)
from dnd_ai.domain.access import is_world_administrator
from tests.factories import (
    make_campaign,
    make_campaign_membership,
    make_membership_role,
    make_ownership_scope,
    make_platform_administrator,
    make_role,
    make_timeline,
    make_user,
    make_world,
)

pytestmark = pytest.mark.database


def _backdate_joined_at(connection: Connection, ownership_scope_membership_id: uuid.UUID) -> None:
    """`now()` is transaction-start time in PostgreSQL, so a plain `now()` in
    `remove_ownership_scope_member`'s `ended_at = now()` would equal
    `joined_at`'s own `now()` from a create/add call earlier in this same
    test transaction and fail `ck_ownership_scope_memberships_ended_after_
    joined` (strictly `>`, not `>=`) — mirrors
    `tests/database/test_security_identity_and_access.py`'s identical
    documented workaround for `security.campaign_memberships`."""
    connection.execute(
        text(
            "UPDATE security.ownership_scope_memberships "
            "SET joined_at = now() - interval '1 second' "
            "WHERE ownership_scope_membership_id = :m"
        ),
        {"m": ownership_scope_membership_id},
    )


def test_world_cannot_exist_without_an_ownership_scope(db_connection: Connection) -> None:
    with pytest.raises(IntegrityError):
        db_connection.execute(
            text("""
                INSERT INTO core.worlds (name, slug, lifecycle_status_id)
                VALUES (
                    'No Owner', 'no-owner-world',
                    (SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'active')
                )
            """)
        )


def test_two_ownership_scopes_may_each_own_a_world_with_the_same_slug(
    db_connection: Connection,
) -> None:
    scope_a = make_ownership_scope(db_connection, "Scope A")
    scope_b = make_ownership_scope(db_connection, "Scope B")

    world_a = make_world(db_connection, "shared-slug", ownership_scope_id=scope_a)
    world_b = make_world(db_connection, "shared-slug", ownership_scope_id=scope_b)

    assert world_a != world_b


def test_two_worlds_in_the_same_ownership_scope_cannot_share_a_slug(
    db_connection: Connection,
) -> None:
    scope = make_ownership_scope(db_connection)
    make_world(db_connection, "duplicate-slug", ownership_scope_id=scope)

    with pytest.raises(IntegrityError):
        make_world(db_connection, "duplicate-slug", ownership_scope_id=scope)


def test_a_user_may_belong_to_multiple_ownership_scopes(db_connection: Connection) -> None:
    user_id = make_user(db_connection)

    result_a = create_ownership_scope(db_connection, name="First Scope", owner_user_id=user_id)
    result_b = create_ownership_scope(db_connection, name="Second Scope", owner_user_id=user_id)

    assert result_a.ownership_scope_id != result_b.ownership_scope_id

    scope_count = db_connection.execute(
        text(
            "SELECT count(*) FROM security.ownership_scope_memberships "
            "WHERE user_id = :user AND ended_at IS NULL"
        ),
        {"user": user_id},
    ).scalar_one()
    assert scope_count == 2


def test_campaign_gm_status_alone_does_not_create_world_ownership(
    db_connection: Connection,
) -> None:
    scope = make_ownership_scope(db_connection)
    world_id = make_world(db_connection, "gm-test-world", ownership_scope_id=scope)
    timeline_id = make_timeline(db_connection, world_id)
    campaign_id = make_campaign(db_connection, timeline_id, lifecycle_status_code="pending")

    gm_user_id = make_user(db_connection, "GM")
    membership_id = make_campaign_membership(db_connection, campaign_id, gm_user_id)
    gm_role_id = make_role(db_connection, campaign_id=campaign_id, code="gm")
    make_membership_role(db_connection, membership_id, gm_role_id)

    assert is_world_administrator(db_connection, world_id=world_id, user_id=gm_user_id) is False


def test_world_ownership_grants_no_campaign_membership(db_connection: Connection) -> None:
    owner_user_id = make_user(db_connection)
    result = create_ownership_scope(db_connection, name="Owner Scope", owner_user_id=owner_user_id)
    world_id = make_world(
        db_connection, "owner-only-world", ownership_scope_id=result.ownership_scope_id
    )

    assert is_world_administrator(db_connection, world_id=world_id, user_id=owner_user_id) is True

    campaign_membership_count = db_connection.execute(
        text("SELECT count(*) FROM security.campaign_memberships WHERE user_id = :user"),
        {"user": owner_user_id},
    ).scalar_one()
    assert campaign_membership_count == 0


def test_platform_administrator_is_not_silently_a_world_owner(db_connection: Connection) -> None:
    admin_user_id = make_platform_administrator(db_connection)
    other_owner_id = make_user(db_connection)
    scope = make_ownership_scope(db_connection)
    add_ownership_scope_member(
        db_connection,
        ownership_scope_id=scope,
        user_id=other_owner_id,
        role_code="owner",
        actor_user_id=other_owner_id,
    )
    world_id = make_world(db_connection, "admin-excluded-world", ownership_scope_id=scope)

    assert is_world_administrator(db_connection, world_id=world_id, user_id=admin_user_id) is False
    assert is_world_administrator(db_connection, world_id=world_id, user_id=other_owner_id) is True


def test_revoked_membership_does_not_authorize_ownership_actions(
    db_connection: Connection,
) -> None:
    owner_user_id = make_user(db_connection)
    result = create_ownership_scope(db_connection, name="Two Owners", owner_user_id=owner_user_id)
    second_owner_id = make_user(db_connection)
    added = add_ownership_scope_member(
        db_connection,
        ownership_scope_id=result.ownership_scope_id,
        user_id=second_owner_id,
        role_code="owner",
        actor_user_id=owner_user_id,
    )
    world_id = make_world(
        db_connection, "revoked-member-world", ownership_scope_id=result.ownership_scope_id
    )

    _backdate_joined_at(db_connection, added.ownership_scope_membership_id)
    remove_ownership_scope_member(
        db_connection,
        ownership_scope_membership_id=added.ownership_scope_membership_id,
        actor_user_id=owner_user_id,
    )

    assert (
        is_world_administrator(db_connection, world_id=world_id, user_id=second_owner_id) is False
    )
    with pytest.raises(OwnershipScopeMembershipNotFoundError):
        remove_ownership_scope_member(
            db_connection,
            ownership_scope_membership_id=added.ownership_scope_membership_id,
            actor_user_id=owner_user_id,
        )


def test_final_active_owner_cannot_be_removed(db_connection: Connection) -> None:
    owner_user_id = make_user(db_connection)
    result = create_ownership_scope(db_connection, name="Sole Owner", owner_user_id=owner_user_id)

    with pytest.raises(LastActiveOwnerError):
        remove_ownership_scope_member(
            db_connection,
            ownership_scope_membership_id=result.ownership_scope_membership_id,
            actor_user_id=owner_user_id,
        )

    # Adding a second owner makes removing the first one safe.
    second_owner_id = make_user(db_connection)
    added = add_ownership_scope_member(
        db_connection,
        ownership_scope_id=result.ownership_scope_id,
        user_id=second_owner_id,
        role_code="owner",
        actor_user_id=owner_user_id,
    )
    _backdate_joined_at(db_connection, result.ownership_scope_membership_id)
    remove_ownership_scope_member(
        db_connection,
        ownership_scope_membership_id=result.ownership_scope_membership_id,
        actor_user_id=second_owner_id,
    )
    assert (
        is_world_administrator(
            db_connection,
            world_id=make_world(db_connection, ownership_scope_id=result.ownership_scope_id),
            user_id=second_owner_id,
        )
        is True
    )
    assert added.ownership_scope_membership_id != result.ownership_scope_membership_id


def test_ownership_changes_produce_audit_history(db_connection: Connection) -> None:
    owner_user_id = make_user(db_connection)
    result = create_ownership_scope(
        db_connection, name="Audited Scope", owner_user_id=owner_user_id
    )

    second_user_id = make_user(db_connection)
    added = add_ownership_scope_member(
        db_connection,
        ownership_scope_id=result.ownership_scope_id,
        user_id=second_user_id,
        role_code="member",
        actor_user_id=owner_user_id,
    )
    _backdate_joined_at(db_connection, added.ownership_scope_membership_id)
    remove_ownership_scope_member(
        db_connection,
        ownership_scope_membership_id=added.ownership_scope_membership_id,
        actor_user_id=owner_user_id,
    )

    rows = (
        db_connection.execute(
            text("""
                SELECT command_name, record_id, actor_user_id
                FROM audit.change_log
                WHERE record_id IN (:created, :added)
                ORDER BY change_log_id
            """),
            {
                "created": result.ownership_scope_membership_id,
                "added": added.ownership_scope_membership_id,
            },
        )
        .mappings()
        .all()
    )
    command_names = [row["command_name"] for row in rows]
    assert command_names == [
        "create_ownership_scope",
        "add_ownership_scope_member",
        "remove_ownership_scope_member",
    ]
    for row in rows:
        assert row["actor_user_id"] == owner_user_id


def test_cross_owner_world_administration_check_returns_false(db_connection: Connection) -> None:
    scope_a_owner = make_user(db_connection)
    scope_a = create_ownership_scope(
        db_connection, name="Scope A", owner_user_id=scope_a_owner
    ).ownership_scope_id
    scope_b_owner = make_user(db_connection)
    scope_b = create_ownership_scope(
        db_connection, name="Scope B", owner_user_id=scope_b_owner
    ).ownership_scope_id

    world_a = make_world(db_connection, "world-a", ownership_scope_id=scope_a)
    world_b = make_world(db_connection, "world-b", ownership_scope_id=scope_b)

    assert is_world_administrator(db_connection, world_id=world_a, user_id=scope_b_owner) is False
    assert is_world_administrator(db_connection, world_id=world_b, user_id=scope_a_owner) is False
    assert is_world_administrator(db_connection, world_id=world_a, user_id=uuid.uuid4()) is False
