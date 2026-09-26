"""Correction pass on `107_world_ownership_scope` (ADR 0014):
`108_ownership_scope_guards` adds membership-identity immutability and a
final-owner retention invariant for `security.ownership_scope_memberships`
that neither the original migration nor `dnd_ai.commands.ownership` ever
enforced at the database boundary.

Deferred constraint triggers only fire at COMMIT (or an explicit
`SET CONSTRAINTS ALL IMMEDIATE`) — the shared `db_connection` fixture wraps
every test in a transaction that always rolls back and never commits, so
every retention-invariant test below calls `SET CONSTRAINTS ALL IMMEDIATE`
after the mutating statement to force evaluation without needing to
actually commit, mirroring `tests/database/
test_security_access_control_invariants.py`'s identical established
pattern for the campaign-owner retention invariant this file's own trigger
was modeled on.
"""

import uuid

import pytest
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import IntegrityError, InternalError, ProgrammingError

from tests.factories import (
    make_ownership_scope,
    make_ownership_scope_membership,
    make_user,
    status_id,
)

pytestmark = pytest.mark.database

CONSTRAINT_ERRORS = (IntegrityError, InternalError, ProgrammingError)


def _immediate(connection: Connection) -> None:
    connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


def _archive_scope(connection: Connection, ownership_scope_id: uuid.UUID) -> None:
    connection.execute(
        text(
            "UPDATE security.ownership_scopes SET lifecycle_status_id = :s "
            "WHERE ownership_scope_id = :scope"
        ),
        {"s": status_id(connection, "lifecycle_statuses", "archived"), "scope": ownership_scope_id},
    )


# ---------------------------------------------------------------------------
# Membership identity immutability
# ---------------------------------------------------------------------------


def test_ownership_scope_id_is_immutable(db_connection: Connection) -> None:
    scope_a = make_ownership_scope(db_connection, "Scope A")
    scope_b = make_ownership_scope(db_connection, "Scope B")
    user_id = make_user(db_connection)
    membership_id = make_ownership_scope_membership(db_connection, scope_a, user_id)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "UPDATE security.ownership_scope_memberships SET ownership_scope_id = :new "
                "WHERE ownership_scope_membership_id = :m"
            ),
            {"new": scope_b, "m": membership_id},
        )
    assert "immutable" in str(exc.value)


def test_user_id_is_immutable(db_connection: Connection) -> None:
    scope = make_ownership_scope(db_connection)
    user_a = make_user(db_connection, "User A")
    user_b = make_user(db_connection, "User B")
    membership_id = make_ownership_scope_membership(db_connection, scope, user_a)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "UPDATE security.ownership_scope_memberships SET user_id = :new "
                "WHERE ownership_scope_membership_id = :m"
            ),
            {"new": user_b, "m": membership_id},
        )
    assert "immutable" in str(exc.value)


# ---------------------------------------------------------------------------
# Final-owner retention for established active scopes
# ---------------------------------------------------------------------------


def test_normal_ownership_transfer_succeeds(db_connection: Connection) -> None:
    """Revoking the old owner and adding a new one, in one transaction,
    must not be rejected on the momentarily owner-less intermediate state
    — the whole point of DEFERRABLE INITIALLY DEFERRED."""
    scope = make_ownership_scope(db_connection)
    old_user = make_user(db_connection, "Old Owner")
    new_user = make_user(db_connection, "New Owner")
    old_membership = make_ownership_scope_membership(db_connection, scope, old_user)

    db_connection.execute(
        text(
            "UPDATE security.ownership_scope_memberships "
            "SET ended_at = now() + interval '1 second' "
            "WHERE ownership_scope_membership_id = :m"
        ),
        {"m": old_membership},
    )
    make_ownership_scope_membership(db_connection, scope, new_user)
    _immediate(db_connection)


def test_direct_sql_revocation_of_sole_owner_is_rejected(db_connection: Connection) -> None:
    scope = make_ownership_scope(db_connection)
    user_id = make_user(db_connection)
    membership_id = make_ownership_scope_membership(db_connection, scope, user_id)

    db_connection.execute(
        text(
            "UPDATE security.ownership_scope_memberships "
            "SET ended_at = now() + interval '1 second' "
            "WHERE ownership_scope_membership_id = :m"
        ),
        {"m": membership_id},
    )
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        _immediate(db_connection)
    assert "no active owner" in str(exc.value)


def test_direct_sql_delete_of_sole_owner_is_rejected(db_connection: Connection) -> None:
    scope = make_ownership_scope(db_connection)
    user_id = make_user(db_connection)
    membership_id = make_ownership_scope_membership(db_connection, scope, user_id)

    db_connection.execute(
        text(
            "DELETE FROM security.ownership_scope_memberships WHERE ownership_scope_membership_id = :m"
        ),
        {"m": membership_id},
    )
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        _immediate(db_connection)
    assert "no active owner" in str(exc.value)


def test_suspending_the_sole_owner_is_rejected(db_connection: Connection) -> None:
    """Suspended is an open (ended_at IS NULL) but non-authorizing status
    (docs/architecture/DATABASE_MODEL.md §19.2) — it must not count as a
    retained owner."""
    scope = make_ownership_scope(db_connection)
    user_id = make_user(db_connection)
    membership_id = make_ownership_scope_membership(db_connection, scope, user_id)

    db_connection.execute(
        text(
            "UPDATE security.ownership_scope_memberships SET membership_status_id = "
            "(SELECT membership_status_id FROM security.membership_statuses WHERE code = 'suspended') "
            "WHERE ownership_scope_membership_id = :m"
        ),
        {"m": membership_id},
    )
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        _immediate(db_connection)
    assert "no active owner" in str(exc.value)


def test_demoting_the_sole_owner_to_member_is_rejected(db_connection: Connection) -> None:
    scope = make_ownership_scope(db_connection)
    user_id = make_user(db_connection)
    membership_id = make_ownership_scope_membership(db_connection, scope, user_id)

    db_connection.execute(
        text(
            "UPDATE security.ownership_scope_memberships SET ownership_scope_role_id = "
            "(SELECT ownership_scope_role_id FROM security.ownership_scope_roles WHERE code = 'member') "
            "WHERE ownership_scope_membership_id = :m"
        ),
        {"m": membership_id},
    )
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        _immediate(db_connection)
    assert "no active owner" in str(exc.value)


def test_archived_scope_may_lose_its_last_owner(db_connection: Connection) -> None:
    """Only an *active* ownership scope must retain an owner — mirrors
    security.campaign_has_access_manager()'s identical active-only gate."""
    scope = make_ownership_scope(db_connection)
    user_id = make_user(db_connection)
    membership_id = make_ownership_scope_membership(db_connection, scope, user_id)
    _archive_scope(db_connection, scope)

    db_connection.execute(
        text(
            "UPDATE security.ownership_scope_memberships "
            "SET ended_at = now() + interval '1 second' "
            "WHERE ownership_scope_membership_id = :m"
        ),
        {"m": membership_id},
    )
    _immediate(db_connection)


def test_unclaimed_scope_with_zero_memberships_is_unaffected(db_connection: Connection) -> None:
    """A scope with zero membership rows (migration 107's legacy-scope
    shape) has nothing for this trigger to fire on at all — it stays a
    legitimate, non-authorizing, explicitly unclaimed state."""
    make_ownership_scope(db_connection, "Unclaimed Scope")
    _immediate(db_connection)  # nothing queued; must not raise


def test_concurrent_removal_of_both_owners_cannot_both_commit(postgres_engine: Engine) -> None:
    """Two simultaneous transactions each ending a *different* owning
    membership of the same scope. The row lock security.
    assert_ownership_scope_retains_owner() takes on security.
    ownership_scopes serializes them: the second to reach the check blocks
    on the first, and once unblocked it re-evaluates live, post-commit
    state and correctly rejects the resulting zero-owner outcome.

    Takes the session engine rather than the db_connection fixture — needs
    real concurrent transactions and committed setup data; db_connection's
    transaction always rolls back, and deferred constraint triggers never
    fire on rollback at all."""
    engine = postgres_engine
    label = f"ownership-guard-concurrency-{uuid.uuid4().hex[:8]}"
    try:
        with engine.begin() as setup:
            scope = make_ownership_scope(setup, label)
            user_a = make_user(setup, f"{label}-a")
            user_b = make_user(setup, f"{label}-b")
            membership_a = make_ownership_scope_membership(setup, scope, user_a)
            membership_b = make_ownership_scope_membership(setup, scope, user_b)

        with engine.connect() as first, engine.connect() as second:
            first.begin()
            second.begin()

            first.execute(
                text(
                    "UPDATE security.ownership_scope_memberships "
                    "SET ended_at = now() + interval '1 second' "
                    "WHERE ownership_scope_membership_id = :m"
                ),
                {"m": membership_a},
            )
            first.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))  # owner B still active — passes

            second.execute(text("SET LOCAL lock_timeout = '2s'"))
            second.execute(
                text(
                    "UPDATE security.ownership_scope_memberships "
                    "SET ended_at = now() + interval '1 second' "
                    "WHERE ownership_scope_membership_id = :m"
                ),
                {"m": membership_b},
            )
            with pytest.raises(Exception) as exc:
                second.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))

            message = str(exc.value)
            assert (
                "lock_timeout" in message
                or "canceling statement" in message
                or "could not obtain lock" in message
            ), f"expected a lock-contention error, got: {message}"

            second.rollback()
            first.commit()

            with engine.begin() as third:
                third.execute(
                    text(
                        "UPDATE security.ownership_scope_memberships "
                        "SET ended_at = now() + interval '1 second' "
                        "WHERE ownership_scope_membership_id = :m"
                    ),
                    {"m": membership_b},
                )
                with pytest.raises(IntegrityError) as exc2:
                    third.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
                assert "no active owner" in str(exc2.value)
    finally:
        with engine.begin() as cleanup:
            cleanup.execute(
                text(
                    "DELETE FROM security.ownership_scope_memberships WHERE ownership_scope_id IN "
                    "(SELECT ownership_scope_id FROM security.ownership_scopes WHERE name = :name)"
                ),
                {"name": label},
            )
            cleanup.execute(
                text("DELETE FROM security.ownership_scopes WHERE name = :name"), {"name": label}
            )
