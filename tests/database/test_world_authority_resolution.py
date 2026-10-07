"""resolve_world_authority: authority comes only from an open, active
world_owner membership held by an active account (ADR 0014)."""

import uuid

import pytest
from sqlalchemy import Connection, text

from dnd_ai.queries.world_authority import resolve_world_authority
from tests.factories import make_system_role_assignment, make_user, make_world

pytestmark = pytest.mark.database


def _grant(
    connection: Connection,
    world: uuid.UUID,
    user: uuid.UUID,
    *,
    status: str = "active",
    ended: bool = False,
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO security.world_memberships
                (world_id, user_id, world_role_id, membership_status_id, joined_at, ended_at)
            VALUES (:w, :u,
                (SELECT world_role_id FROM security.world_roles WHERE code = 'world_owner'),
                (SELECT membership_status_id FROM security.membership_statuses WHERE code = :s),
                now(), CASE WHEN :e THEN now() ELSE NULL END)
            RETURNING world_membership_id
        """),
        {"w": world, "u": user, "s": status, "e": ended},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def test_an_active_owner_resolves_with_the_full_capability_set(db_connection: Connection) -> None:
    world = make_world(db_connection, "wa-owner")
    user = make_user(db_connection)
    make_system_role_assignment(db_connection, user, "gm")
    _grant(db_connection, world, user)

    authority = resolve_world_authority(db_connection, user_id=user, world_id=world)
    assert authority is not None
    assert authority.has_capability("world.manage")
    assert authority.has_capability("campaign.create")
    assert authority.world_lifecycle_status == "active"


def test_an_unclaimed_legacy_world_resolves_to_none_for_everyone(
    db_connection: Connection,
) -> None:
    world = make_world(db_connection, "wa-legacy")
    assert (
        resolve_world_authority(db_connection, user_id=make_user(db_connection), world_id=world)
        is None
    )


def test_a_nonexistent_world_resolves_to_none(db_connection: Connection) -> None:
    assert (
        resolve_world_authority(
            db_connection, user_id=make_user(db_connection), world_id=uuid.uuid4()
        )
        is None
    )


def test_another_users_world_resolves_to_none(db_connection: Connection) -> None:
    world = make_world(db_connection, "wa-other")
    _grant(db_connection, world, make_user(db_connection, "Owner"))
    stranger = make_user(db_connection, "Stranger")
    assert resolve_world_authority(db_connection, user_id=stranger, world_id=world) is None


@pytest.mark.parametrize("status", ["suspended", "invited", "revoked", "departed"])
def test_non_active_membership_statuses_do_not_authorize(
    db_connection: Connection, status: str
) -> None:
    world = make_world(db_connection, f"wa-status-{status}")
    keeper = make_user(db_connection, "Keeper")
    _grant(db_connection, world, keeper)
    user = make_user(db_connection)
    _grant(db_connection, world, user, status=status)
    assert resolve_world_authority(db_connection, user_id=user, world_id=world) is None


def test_an_ended_membership_does_not_authorize(db_connection: Connection) -> None:
    world = make_world(db_connection, "wa-ended")
    _grant(db_connection, world, make_user(db_connection, "Keeper"))
    user = make_user(db_connection)
    _grant(db_connection, world, user, ended=True)
    assert resolve_world_authority(db_connection, user_id=user, world_id=world) is None


def test_an_inactive_role_does_not_authorize(db_connection: Connection) -> None:
    world = make_world(db_connection, "wa-role")
    user = make_user(db_connection)
    _grant(db_connection, world, user)
    db_connection.execute(
        text("UPDATE security.world_roles SET is_active = false WHERE code = 'world_owner'")
    )
    assert resolve_world_authority(db_connection, user_id=user, world_id=world) is None


def test_a_disabled_account_does_not_authorize(db_connection: Connection) -> None:
    world = make_world(db_connection, "wa-disabled")
    user = make_user(db_connection)
    _grant(db_connection, world, user)
    db_connection.execute(
        text("""
            UPDATE security.users SET lifecycle_status_id =
                (SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'inactive')
            WHERE user_id = :u
        """),
        {"u": user},
    )
    assert resolve_world_authority(db_connection, user_id=user, world_id=world) is None


def test_platform_administration_grants_no_world_authority(db_connection: Connection) -> None:
    from tests.factories import make_platform_administrator

    world = make_world(db_connection, "wa-admin")
    admin = make_platform_administrator(db_connection)
    assert resolve_world_authority(db_connection, user_id=admin, world_id=world) is None


def test_an_archived_world_still_resolves_with_its_status(db_connection: Connection) -> None:
    world = make_world(db_connection, "wa-archived")
    user = make_user(db_connection)
    _grant(db_connection, world, user)
    db_connection.execute(
        text("""
            UPDATE core.worlds SET lifecycle_status_id =
                (SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'archived')
            WHERE world_id = :w
        """),
        {"w": world},
    )
    authority = resolve_world_authority(db_connection, user_id=user, world_id=world)
    assert authority is not None
    assert authority.world_lifecycle_status == "archived"
