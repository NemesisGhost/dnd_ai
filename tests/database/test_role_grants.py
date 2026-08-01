"""Tests for the ADR 0009 ownership chain and the grants that depend on it.

These exist because the failure they catch is silent. If `SET ROLE
migration_owner` stops holding, tables come out owned by whoever connected,
`ALTER DEFAULT PRIVILEGES FOR ROLE migration_owner` never fires for them, and
the application roles receive nothing — while migrations succeed, every test
using the admin connection passes, and CI goes green. Only the running
application notices, in a later phase that did not cause the problem.

Parameterized over every table rather than a sample, so a table added without
the right ownership is caught by the suite rather than by production.

See docs/PLAN.md §23.1 (recurring obligations) and
docs/adr/0009-separate-owning-role-from-login-roles.md.
"""

import pytest
from sqlalchemy import Connection, text

pytestmark = pytest.mark.database

# Every table the project has created so far. Add to this when adding tables —
# the point is total coverage, not a representative sample.
MANAGED_TABLES = [
    ("core", "canon_statuses"),
    ("core", "lifecycle_statuses"),
    ("core", "source_types"),
    ("security", "users"),
    ("security", "roles"),
    ("security", "user_roles"),
    ("core", "worlds"),
    ("core", "entity_types"),
    ("core", "sources"),
    ("core", "entities"),
    ("core", "name_types"),
    ("core", "entity_names"),
    ("core", "tags"),
    ("core", "entity_tags"),
    ("core", "world_time_precisions"),
    ("core", "calendars"),
    ("core", "calendar_months"),
    ("core", "world_times"),
    ("audit", "change_actions"),
    ("campaign", "parties"),
    ("campaign", "party_memberships"),
]

# audit.change_log is deliberately excluded from MANAGED_TABLES: it is
# append-only to application roles (conventions §24.2), so the blanket
# "app_read_write holds full DML" expectation below does not apply to it.
# Its grants are asserted in test_audit_change_log.py instead.

# Privileges each application role must hold on every managed table.
EXPECTED_GRANTS = {
    "app_read_write": {"SELECT", "INSERT", "UPDATE", "DELETE"},
    "app_read_only": {"SELECT"},
}


@pytest.mark.parametrize(("schema", "table"), MANAGED_TABLES)
def test_table_is_owned_by_migration_owner(
    db_connection: Connection, schema: str, table: str
) -> None:
    owner = db_connection.execute(
        text("SELECT tableowner FROM pg_tables WHERE schemaname = :s AND tablename = :t"),
        {"s": schema, "t": table},
    ).scalar()
    assert owner == "migration_owner", (
        f"{schema}.{table} is owned by {owner!r}, not migration_owner. "
        "SET ROLE is not holding — the application roles will silently have no "
        "access to this table. See ADR 0009."
    )


@pytest.mark.parametrize(("schema", "table"), MANAGED_TABLES)
@pytest.mark.parametrize("role", sorted(EXPECTED_GRANTS))
def test_application_role_has_expected_grants(
    db_connection: Connection, schema: str, table: str, role: str
) -> None:
    granted = {
        r[0]
        for r in db_connection.execute(
            text("""
                SELECT privilege_type
                FROM information_schema.role_table_grants
                WHERE table_schema = :s AND table_name = :t AND grantee = :g
            """),
            {"s": schema, "t": table, "g": role},
        )
    }
    expected = EXPECTED_GRANTS[role]
    assert expected <= granted, (
        f"{role} is missing {sorted(expected - granted)} on {schema}.{table}. "
        "ALTER DEFAULT PRIVILEGES did not fire — most likely the table was not "
        "created by migration_owner."
    )


@pytest.mark.parametrize(("schema", "table"), MANAGED_TABLES)
def test_read_only_role_cannot_write(db_connection: Connection, schema: str, table: str) -> None:
    """app_read_only must hold no write privilege — the negative half of §32.1."""
    writes = {
        r[0]
        for r in db_connection.execute(
            text("""
                SELECT privilege_type
                FROM information_schema.role_table_grants
                WHERE table_schema = :s AND table_name = :t AND grantee = 'app_read_only'
            """),
            {"s": schema, "t": table},
        )
    } & {"INSERT", "UPDATE", "DELETE", "TRUNCATE"}
    assert not writes, f"app_read_only has write privileges {sorted(writes)} on {schema}.{table}"


def test_migration_owner_cannot_log_in(db_connection: Connection) -> None:
    """The property the whole ADR 0009 split rests on."""
    can_login = db_connection.execute(
        text("SELECT rolcanlogin FROM pg_roles WHERE rolname = 'migration_owner'")
    ).scalar()
    assert can_login is False, (
        "migration_owner can log in. Granting it rds_iam would then force IAM "
        "auth on every role inheriting it, including the RDS master user."
    )
