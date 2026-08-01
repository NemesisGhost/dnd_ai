"""Constraint tests for revision 003 — lookups, security tables, updated_at trigger.

Every nontrivial constraint gets a positive and a negative test per
docs/DATABASE_CONVENTIONS.md §32.1. All tests run inside the fixture's
transaction and roll back.
"""

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError

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
        text("INSERT INTO security.users (username, display_name) VALUES ('alice', 'Alice')")
    )


def test_users_rejects_duplicate_username(db_connection: Connection) -> None:
    db_connection.execute(
        text("INSERT INTO security.users (username, display_name) VALUES ('bob', 'Bob')")
    )
    with pytest.raises(IntegrityError):
        db_connection.execute(
            text("INSERT INTO security.users (username, display_name) VALUES ('bob', 'Bob 2')")
        )


def test_users_rejects_empty_username(db_connection: Connection) -> None:
    with pytest.raises(IntegrityError):
        db_connection.execute(
            text("INSERT INTO security.users (username, display_name) VALUES ('', 'Empty')")
        )


def test_users_allows_null_email(db_connection: Connection) -> None:
    """Service-linked and imported accounts may have no address."""
    db_connection.execute(
        text(
            "INSERT INTO security.users (username, display_name, email) "
            "VALUES ('noemail', 'No Email', NULL)"
        )
    )


def test_user_roles_rejects_unknown_user(db_connection: Connection) -> None:
    role_id = db_connection.execute(
        text(
            "INSERT INTO security.roles (code, display_name) VALUES ('tester', 'Tester') "
            "RETURNING role_id"
        )
    ).scalar()
    with pytest.raises(IntegrityError):
        db_connection.execute(
            text(
                "INSERT INTO security.user_roles (user_id, role_id) VALUES (gen_random_uuid(), :r)"
            ),
            {"r": role_id},
        )


def test_user_roles_rejects_duplicate_assignment(db_connection: Connection) -> None:
    user_id = db_connection.execute(
        text(
            "INSERT INTO security.users (username, display_name) VALUES ('carol', 'Carol') "
            "RETURNING user_id"
        )
    ).scalar()
    role_id = db_connection.execute(
        text(
            "INSERT INTO security.roles (code, display_name) VALUES ('dupe_role', 'Dupe') "
            "RETURNING role_id"
        )
    ).scalar()
    db_connection.execute(
        text("INSERT INTO security.user_roles (user_id, role_id) VALUES (:u, :r)"),
        {"u": user_id, "r": role_id},
    )
    with pytest.raises(IntegrityError):
        db_connection.execute(
            text("INSERT INTO security.user_roles (user_id, role_id) VALUES (:u, :r)"),
            {"u": user_id, "r": role_id},
        )


def test_deleting_user_cascades_to_role_assignments(db_connection: Connection) -> None:
    user_id = db_connection.execute(
        text(
            "INSERT INTO security.users (username, display_name) VALUES ('dave', 'Dave') "
            "RETURNING user_id"
        )
    ).scalar()
    role_id = db_connection.execute(
        text(
            "INSERT INTO security.roles (code, display_name) VALUES ('cascade_role', 'C') "
            "RETURNING role_id"
        )
    ).scalar()
    db_connection.execute(
        text("INSERT INTO security.user_roles (user_id, role_id) VALUES (:u, :r)"),
        {"u": user_id, "r": role_id},
    )

    db_connection.execute(text("DELETE FROM security.users WHERE user_id = :u"), {"u": user_id})

    remaining = db_connection.execute(
        text("SELECT count(*) FROM security.user_roles WHERE user_id = :u"), {"u": user_id}
    ).scalar()
    assert remaining == 0


def test_deleting_role_in_use_is_restricted(db_connection: Connection) -> None:
    """ON DELETE RESTRICT: a role cannot vanish out from under its holders."""
    user_id = db_connection.execute(
        text(
            "INSERT INTO security.users (username, display_name) VALUES ('erin', 'Erin') "
            "RETURNING user_id"
        )
    ).scalar()
    role_id = db_connection.execute(
        text(
            "INSERT INTO security.roles (code, display_name) VALUES ('inuse', 'In Use') "
            "RETURNING role_id"
        )
    ).scalar()
    db_connection.execute(
        text("INSERT INTO security.user_roles (user_id, role_id) VALUES (:u, :r)"),
        {"u": user_id, "r": role_id},
    )

    with pytest.raises(IntegrityError):
        db_connection.execute(text("DELETE FROM security.roles WHERE role_id = :r"), {"r": role_id})


@pytest.mark.parametrize("table", [*LOOKUP_TABLES, "security.users", "security.roles"])
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
        insert = f"INSERT INTO {table} (username, display_name) VALUES ('trig', 'T')"
        where = "username = 'trig'"
    else:
        insert = f"INSERT INTO {table} (code, display_name) VALUES ('trig', 'T')"
        where = "code = 'trig'"

    db_connection.execute(text(insert))
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
