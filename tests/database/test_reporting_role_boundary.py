"""app_read_only is deny-by-default (migration 115, checkpoint 15.2A-2).

The shared test database is already at head. The probe table and the real
`SET ROLE` reads run inside the rolled-back test transaction; the
upgrade/downgrade round trip uses a throwaway database paused at revision 114.
"""

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.exc import ProgrammingError

from tests.database.test_organization_hierarchy_migration import _alembic
from tests.database.test_phase8_populated_upgrade import (
    _alembic_upgrade,
    _connect_args,
    _drop_database,
    _provision_database,
)

pytestmark = pytest.mark.database

_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "migrations"
    / "versions"
    / "115_reporting_role_boundary.py"
)


def _migration_module():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("reporting_boundary_migration", _MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_module = _migration_module()
ALLOWLIST: frozenset[str] = frozenset(_module.REPORTING_READABLE_TABLES)
SCHEMAS: tuple[str, ...] = _module._SCHEMAS

# Tables that must never be generally reportable: credential and token hashes,
# session/CSRF storage, idempotency request/response storage, unrestricted audit
# metadata, AI prompt/context storage, and GM-only authored content.
NEVER_READABLE = (
    "security.local_credentials",
    "security.user_activation_tokens",
    "security.password_reset_tokens",
    "security.browser_sessions",
    "security.invitation_onboarding_sessions",
    "security.campaign_invitations",
    "security.foundry_pairing_codes",
    "security.foundry_devices",
    "security.foundry_access_tokens",
    "security.idempotent_requests",
    "security.actor_idempotent_requests",
    "security.campaign_creation_reservations",
    "integration.external_systems",
    "audit.change_log",
    "ai.context_requests",
    "ai.context_snapshots",
    "ai.generated_outputs",
    "ai.prompt_fragments",
    "ai.prompt_templates",
    "ai.reference_retrievals",
    "world.organizations",
    "character.character_descriptions",
    "knowledge.knowledge_items",
    "narrative.quests",
    "core.entities",
)


def _can_select(connection: Connection, role: str, table: str) -> bool:
    return bool(
        connection.execute(
            text("SELECT has_table_privilege(:r, :t, 'SELECT')"), {"r": role, "t": table}
        ).scalar()
    )


def _all_tables(connection: Connection) -> list[str]:
    return [
        f"{s}.{t}"
        for s, t in connection.execute(
            text("""
                SELECT schemaname, tablename FROM pg_tables
                WHERE schemaname = ANY(:schemas) AND tablename <> 'alembic_version'
                ORDER BY 1, 2
            """),
            {"schemas": list(SCHEMAS)},
        )
    ]


@pytest.mark.parametrize("table", NEVER_READABLE)
def test_sensitive_tables_are_not_readable_by_app_read_only(
    db_connection: Connection, table: str
) -> None:
    assert not _can_select(db_connection, "app_read_only", table)


def test_every_table_outside_the_allowlist_is_denied(db_connection: Connection) -> None:
    readable = {
        t for t in _all_tables(db_connection) if _can_select(db_connection, "app_read_only", t)
    }
    assert readable == ALLOWLIST & set(_all_tables(db_connection))


def test_every_allowlisted_table_exists_and_is_readable(db_connection: Connection) -> None:
    existing = set(_all_tables(db_connection))
    assert existing >= ALLOWLIST, sorted(ALLOWLIST - existing)
    assert all(_can_select(db_connection, "app_read_only", t) for t in ALLOWLIST)


def test_the_allowlist_holds_no_scoped_or_authored_content_table() -> None:
    for table in ALLOWLIST:
        assert not table.startswith(("character.", "campaign.sessions", "narrative.events"))
    assert "rules.item_definitions" not in ALLOWLIST
    assert "rules.world_rulesets" not in ALLOWLIST


def test_a_real_read_as_app_read_only_is_refused_for_secrets_and_allowed_for_lookups(
    db_connection: Connection,
) -> None:
    with db_connection.begin_nested():
        db_connection.execute(text("SET LOCAL ROLE app_read_only"))
        assert db_connection.execute(text("SELECT count(*) FROM core.canon_statuses")).scalar()
        db_connection.execute(text("RESET ROLE"))
    for secret in (
        "security.local_credentials",
        "security.idempotent_requests",
        "audit.change_log",
    ):
        with (
            pytest.raises(ProgrammingError, match="permission denied"),
            db_connection.begin_nested(),
        ):
            db_connection.execute(text("SET LOCAL ROLE app_read_only"))
            db_connection.execute(text(f"SELECT 1 FROM {secret} LIMIT 1"))


def test_a_new_table_created_by_the_owner_is_not_readable_by_app_read_only(
    db_connection: Connection,
) -> None:
    """Default privileges no longer grant SELECT, so a future table in any
    schema (for example a Phase 16 `collaboration` schema) is denied until a
    migration grants it deliberately, while `app_read_write` still gets DML."""
    db_connection.execute(text("SET LOCAL ROLE migration_owner"))
    for schema in ("security", "core", "campaign"):
        db_connection.execute(text(f"CREATE TABLE {schema}.zz_boundary_probe (x integer)"))
        assert not _can_select(db_connection, "app_read_only", f"{schema}.zz_boundary_probe")
        assert _can_select(db_connection, "app_read_write", f"{schema}.zz_boundary_probe")
    db_connection.execute(text("RESET ROLE"))


def test_runtime_and_worker_roles_are_unchanged(db_connection: Connection) -> None:
    for table in ("security.local_credentials", "security.idempotent_requests", "core.entities"):
        for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            assert db_connection.execute(
                text("SELECT has_table_privilege('app_read_write', :t, :p)"),
                {"t": table, "p": privilege},
            ).scalar()
    assert db_connection.execute(
        text("SELECT has_schema_privilege('app_read_only', 'security', 'USAGE')")
    ).scalar()


def test_upgrade_restricts_and_downgrade_restores_the_previous_grants() -> None:
    admin_url, test_url = _provision_database()
    try:
        _alembic_upgrade(test_url, "114_relationship_defaults")
        engine = create_engine(test_url, connect_args=_connect_args())
        with engine.connect() as connection:
            assert _can_select(connection, "app_read_only", "security.local_credentials")
        _alembic_upgrade(test_url, "115_reporting_role_boundary")
        with engine.connect() as connection:
            assert not _can_select(connection, "app_read_only", "security.local_credentials")
            assert _can_select(connection, "app_read_only", "core.canon_statuses")
        downgraded = _alembic(test_url, "downgrade", "114_relationship_defaults")
        assert downgraded.returncode == 0, downgraded.stderr
        with engine.connect() as connection:
            assert _can_select(connection, "app_read_only", "security.local_credentials")
        _alembic_upgrade(test_url, "head")
        checked = _alembic(test_url, "check")
        assert checked.returncode == 0, checked.stdout + checked.stderr
        engine.dispose()
    finally:
        _drop_database(admin_url, test_url)
