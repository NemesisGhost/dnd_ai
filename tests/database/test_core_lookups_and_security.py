"""Constraint tests for revision 003 — lookups, updated_at trigger — and
security.users as reshaped by revision 080.

Every nontrivial constraint gets a positive and a negative test per
docs/DATABASE_CONVENTIONS.md §32.1. All tests run inside the fixture's
transaction and roll back.

The old security.roles / security.user_roles pair (and the old username-based
security.users shape) revision 080 dropped/reshaped had their tests here too —
see tests/database/test_security_identity_and_access.py for the replacement
campaign-scoped security.roles and security.users coverage.
"""

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError

from tests.factories import status_id

pytestmark = pytest.mark.database

LOOKUP_TABLES = ["core.canon_statuses", "core.lifecycle_statuses", "core.source_types"]


@pytest.mark.parametrize("table", LOOKUP_TABLES)
def test_lookup_accepts_valid_row(db_connection: Connection, table: str) -> None:
    db_connection.execute(
        text(f"INSERT INTO {table} (code, display_name) VALUES ('valid_code', 'Valid')")
    )


@pytest.mark.parametrize("table", LOOKUP_TABLES)
def test_lookup_rejects_duplicate_code(db_connection: Connection, table: str) -> None:
    db_connection.execute(
        text(f"INSERT INTO {table} (code, display_name) VALUES ('dupe', 'First')")
    )
    with pytest.raises(IntegrityError):
        db_connection.execute(
            text(f"INSERT INTO {table} (code, display_name) VALUES ('dupe', 'Second')")
        )


@pytest.mark.parametrize("table", LOOKUP_TABLES)
@pytest.mark.parametrize(
    "bad_code", ["Uppercase", "has-hyphen", "9_leading_digit", "has space", ""]
)
def test_lookup_rejects_malformed_code(
    db_connection: Connection, table: str, bad_code: str
) -> None:
    with pytest.raises(IntegrityError):
        db_connection.execute(
            text(f"INSERT INTO {table} (code, display_name) VALUES (:c, 'X')"),
            {"c": bad_code},
        )


@pytest.mark.parametrize("table", LOOKUP_TABLES)
def test_lookup_rejects_negative_sort_order(db_connection: Connection, table: str) -> None:
    """sort_order uses core.nonnegative_integer — the domain does the work."""
    with pytest.raises(IntegrityError):
        db_connection.execute(
            text(f"INSERT INTO {table} (code, display_name, sort_order) VALUES ('neg', 'X', -1)")
        )


@pytest.mark.parametrize("table", LOOKUP_TABLES)
def test_lookup_rejects_null_display_name(db_connection: Connection, table: str) -> None:
    with pytest.raises(IntegrityError):
        db_connection.execute(
            text(f"INSERT INTO {table} (code, display_name) VALUES ('nulldisp', NULL)")
        )


def test_users_accepts_valid_row(db_connection: Connection) -> None:
    db_connection.execute(
        text(
            "INSERT INTO security.users (display_name, lifecycle_status_id) "
            "VALUES ('Alice', :status)"
        ),
        {"status": status_id(db_connection, "lifecycle_statuses", "active")},
    )


def test_users_rejects_null_lifecycle_status(db_connection: Connection) -> None:
    with pytest.raises(IntegrityError):
        db_connection.execute(
            text(
                "INSERT INTO security.users (display_name, lifecycle_status_id) VALUES ('Bob', NULL)"
            )
        )


def test_users_allows_null_email(db_connection: Connection) -> None:
    """Service-linked and imported accounts may have no address."""
    db_connection.execute(
        text(
            "INSERT INTO security.users (display_name, lifecycle_status_id, email) "
            "VALUES ('No Email', :status, NULL)"
        ),
        {"status": status_id(db_connection, "lifecycle_statuses", "active")},
    )


def test_users_allows_null_last_login_at(db_connection: Connection) -> None:
    """A user who has never logged in."""
    value = db_connection.execute(
        text(
            "INSERT INTO security.users (display_name, lifecycle_status_id) "
            "VALUES ('Never Logged In', :status) RETURNING last_login_at"
        ),
        {"status": status_id(db_connection, "lifecycle_statuses", "active")},
    ).scalar()
    assert value is None


@pytest.mark.parametrize("table", [*LOOKUP_TABLES, "security.users"])
def test_updated_at_trigger_overrides_supplied_value(db_connection: Connection, table: str) -> None:
    """The shared core.set_updated_at() trigger (conventions §10.4).

    Asserted by writing a deliberately wrong updated_at and checking the
    trigger replaces it, rather than by expecting the timestamp to advance
    between two statements. The trigger uses now(), which in PostgreSQL is
    *transaction start* time — so inside a single transaction (which is how
    the db_connection fixture runs) two consecutive updates produce the same
    value, and a naive `after > before` assertion fails against a perfectly
    working trigger.
    """
    if table == "security.users":
        insert = text(
            "INSERT INTO security.users (display_name, lifecycle_status_id) "
            "VALUES ('trig', :status)"
        )
        params: dict[str, object] = {
            "status": status_id(db_connection, "lifecycle_statuses", "active")
        }
        where = "display_name = 'trig'"
    else:
        insert = text(f"INSERT INTO {table} (code, display_name) VALUES ('trig', 'T')")
        params = {}
        where = "code = 'trig'"

    db_connection.execute(insert, params)
    db_connection.execute(
        text(f"UPDATE {table} SET updated_at = TIMESTAMPTZ '2000-01-01' WHERE {where}")
    )

    after = db_connection.execute(text(f"SELECT updated_at FROM {table} WHERE {where}")).scalar()
    txn_now = db_connection.execute(text("SELECT now()")).scalar()

    assert after == txn_now, (
        f"core.set_updated_at() did not fire on {table} — updated_at kept the "
        "value supplied by the caller instead of being set to now()."
    )


def test_updated_at_trigger_is_the_shared_function(db_connection: Connection) -> None:
    """Every updated_at trigger uses one function, not per-domain copies (§10.4)."""
    functions = {
        r[0]
        for r in db_connection.execute(
            text("""
                SELECT DISTINCT p.proname
                FROM pg_trigger t
                JOIN pg_proc p ON t.tgfoid = p.oid
                WHERE NOT t.tgisinternal AND t.tgname LIKE '%set_updated_at'
            """)
        )
    }
    assert functions == {"set_updated_at"}, (
        f"Expected all updated_at triggers to use core.set_updated_at(); found {functions}"
    )
