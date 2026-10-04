"""security.world_roles / security.world_memberships (revision 110).

Per-world authoring authority (docs/adr/0014-world-authoring-authority.md):
open-membership uniqueness, immutable identity, the closed-after-joined CHECK,
and the deferred owner-retention guard — including that a legacy world with no
membership rows at all is unaffected.
"""

import uuid

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from tests.factories import make_user, make_world

pytestmark = pytest.mark.database


def _membership(
    connection: Connection,
    world_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    status: str = "active",
    ended: bool = False,
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO security.world_memberships
                (world_id, user_id, world_role_id, membership_status_id, joined_at, ended_at)
            VALUES (
                :w, :u,
                (SELECT world_role_id FROM security.world_roles WHERE code = 'world_owner'),
                (SELECT membership_status_id FROM security.membership_statuses WHERE code = :s),
                now(),
                CASE WHEN :ended THEN now() ELSE NULL END
            )
            RETURNING world_membership_id
        """),
        {"w": world_id, "u": user_id, "s": status, "ended": ended},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def test_world_owner_role_is_seeded(db_connection: Connection) -> None:
    row = db_connection.execute(
        text("SELECT is_active FROM security.world_roles WHERE code = 'world_owner'")
    ).one()
    assert row.is_active is True


def test_only_one_open_membership_per_world_and_user(db_connection: Connection) -> None:
    world = make_world(db_connection, "wm-open-unique")
    user = make_user(db_connection)
    _membership(db_connection, world, user)

    with pytest.raises(IntegrityError) as exc:
        _membership(db_connection, world, user)
    assert "ux_world_memberships_open" in str(exc.value)


def test_a_closed_membership_does_not_block_a_new_open_one(db_connection: Connection) -> None:
    world = make_world(db_connection, "wm-reopen")
    user = make_user(db_connection)
    _membership(db_connection, world, user, ended=True)
    _membership(db_connection, world, user)


def test_the_same_user_may_own_two_worlds(db_connection: Connection) -> None:
    user = make_user(db_connection)
    _membership(db_connection, make_world(db_connection, "wm-a"), user)
    _membership(db_connection, make_world(db_connection, "wm-b"), user)


def test_ended_at_may_not_precede_joined_at(db_connection: Connection) -> None:
    world = make_world(db_connection, "wm-ended-before-joined")
    user = make_user(db_connection)
    with pytest.raises(IntegrityError) as exc:
        db_connection.execute(
            text("""
                INSERT INTO security.world_memberships
                    (world_id, user_id, world_role_id, membership_status_id,
                     joined_at, ended_at)
                VALUES (
                    :w, :u,
                    (SELECT world_role_id FROM security.world_roles WHERE code = 'world_owner'),
                    (SELECT membership_status_id FROM security.membership_statuses
                     WHERE code = 'revoked'),
                    now(), now() - interval '1 hour'
                )
            """),
            {"w": world, "u": user},
        )
    assert "ck_world_memberships_ended_after_joined" in str(exc.value)


@pytest.mark.parametrize("column", ["world_id", "user_id"])
def test_membership_identity_columns_are_immutable(db_connection: Connection, column: str) -> None:
    world = make_world(db_connection, "wm-immutable")
    other_world = make_world(db_connection, "wm-immutable-other")
    user = make_user(db_connection)
    other_user = make_user(db_connection, "Other")
    membership = _membership(db_connection, world, user)

    new_value = other_world if column == "world_id" else other_user
    with pytest.raises(DBAPIError) as exc:
        db_connection.execute(
            text(
                f"UPDATE security.world_memberships SET {column} = :v "
                "WHERE world_membership_id = :m"
            ),
            {"v": new_value, "m": membership},
        )
    assert "immutable" in str(exc.value)


def test_last_active_owner_cannot_be_removed(db_connection: Connection) -> None:
    world = make_world(db_connection, "wm-retain-owner")
    user = make_user(db_connection)
    membership = _membership(db_connection, world, user)
    db_connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))

    with pytest.raises(DBAPIError) as exc:
        db_connection.execute(
            text(
                "UPDATE security.world_memberships SET ended_at = now() "
                "WHERE world_membership_id = :m"
            ),
            {"m": membership},
        )
    assert "no active world_owner" in str(exc.value)


@pytest.mark.parametrize("status", ["suspended", "revoked"])
def test_suspending_the_last_owner_is_rejected(db_connection: Connection, status: str) -> None:
    world = make_world(db_connection, f"wm-status-{status}")
    user = make_user(db_connection)
    membership = _membership(db_connection, world, user)
    db_connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))

    with pytest.raises(DBAPIError) as exc:
        db_connection.execute(
            text("""
                UPDATE security.world_memberships
                SET membership_status_id =
                    (SELECT membership_status_id FROM security.membership_statuses
                     WHERE code = :s)
                WHERE world_membership_id = :m
            """),
            {"s": status, "m": membership},
        )
    assert "no active world_owner" in str(exc.value)


def test_deleting_the_last_owner_membership_is_rejected(db_connection: Connection) -> None:
    world = make_world(db_connection, "wm-delete-owner")
    membership = _membership(db_connection, world, make_user(db_connection))
    db_connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))

    with pytest.raises(DBAPIError) as exc:
        db_connection.execute(
            text("DELETE FROM security.world_memberships WHERE world_membership_id = :m"),
            {"m": membership},
        )
    assert "no active world_owner" in str(exc.value)


def test_an_owner_may_be_removed_while_another_remains(db_connection: Connection) -> None:
    world = make_world(db_connection, "wm-two-owners")
    first = _membership(db_connection, world, make_user(db_connection, "First"))
    _membership(db_connection, world, make_user(db_connection, "Second"))
    db_connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))

    db_connection.execute(
        text(
            "UPDATE security.world_memberships SET ended_at = now() WHERE world_membership_id = :m"
        ),
        {"m": first},
    )


def test_ownership_may_be_handed_over_inside_one_transaction(db_connection: Connection) -> None:
    """The guard is deferred: close the old owner and open the new one in either
    order, and only the final state is judged."""
    world = make_world(db_connection, "wm-handover")
    old = _membership(db_connection, world, make_user(db_connection, "Old"))
    db_connection.execute(
        text(
            "UPDATE security.world_memberships SET ended_at = now() WHERE world_membership_id = :m"
        ),
        {"m": old},
    )
    _membership(db_connection, world, make_user(db_connection, "New"))
    db_connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


def test_a_legacy_world_without_memberships_is_unaffected(db_connection: Connection) -> None:
    make_world(db_connection, "wm-legacy")
    db_connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    count = db_connection.execute(
        text("""
            SELECT count(*) FROM security.world_memberships wm
            JOIN core.worlds w ON w.world_id = wm.world_id WHERE w.slug = 'wm-legacy'
        """)
    ).scalar()
    assert count == 0


def test_deleting_a_world_cascades_its_memberships_without_tripping_the_guard(
    db_connection: Connection,
) -> None:
    world = make_world(db_connection, "wm-world-delete")
    _membership(db_connection, world, make_user(db_connection))
    db_connection.execute(text("DELETE FROM core.worlds WHERE world_id = :w"), {"w": world})
    db_connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


def test_world_has_active_owner_ignores_ended_and_suspended_rows(
    db_connection: Connection,
) -> None:
    world = make_world(db_connection, "wm-has-owner")
    assert (
        db_connection.execute(
            text("SELECT security.world_has_active_owner(:w)"), {"w": world}
        ).scalar()
        is False
    )
    _membership(db_connection, world, make_user(db_connection, "Gone"), ended=True)
    _membership(db_connection, world, make_user(db_connection, "Paused"), status="suspended")
    assert (
        db_connection.execute(
            text("SELECT security.world_has_active_owner(:w)"), {"w": world}
        ).scalar()
        is False
    )
    _membership(db_connection, world, make_user(db_connection, "Live"))
    assert (
        db_connection.execute(
            text("SELECT security.world_has_active_owner(:w)"), {"w": world}
        ).scalar()
        is True
    )
