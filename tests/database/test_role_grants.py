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
    ("campaign", "timelines"),
    ("campaign", "parties"),
    ("campaign", "party_memberships"),
    ("campaign", "campaigns"),
    ("campaign", "campaign_parties"),
    ("campaign", "sessions"),
    ("rules", "rulesets"),
    ("rules", "ruleset_versions"),
    ("rules", "world_rulesets"),
    ("rules", "abilities"),
    ("rules", "species"),
    ("rules", "damage_types"),
    ("rules", "conditions"),
    ("rules", "creature_types"),
    ("rules", "languages"),
    ("rules", "proficiency_types"),
    ("rules", "resource_definitions"),
    ("rules", "skills"),
    ("rules", "classes"),
    ("rules", "subclasses"),
    ("rules", "features"),
    ("rules", "feats"),
    ("rules", "spells"),
    ("character", "characters"),
    ("character", "npcs"),
    ("character", "player_characters"),
    ("character", "character_descriptions"),
    ("character", "character_languages"),
    ("character", "character_senses"),
    ("character", "character_movements"),
    ("character", "character_builds"),
    ("character", "character_ability_scores"),
    ("character", "character_class_levels"),
    ("character", "character_proficiencies"),
    ("character", "character_features"),
    ("character", "character_spellcasting_profiles"),
    ("character", "character_known_spells"),
    ("character", "character_prepared_spells"),
    ("campaign", "character_state"),
    ("campaign", "character_conditions"),
    ("campaign", "character_resources"),
    # Phase 5 — locations and dungeon structure
    ("world", "locations"),
    ("world", "settlements"),
    ("world", "buildings"),
    ("world", "dungeons"),
    ("world", "dungeon_areas"),
    ("world", "connection_types"),
    ("world", "area_connections"),
    ("world", "area_features"),
    ("world", "area_hazards"),
    ("world", "area_interactables"),
    ("campaign", "character_location_history"),
    ("campaign", "location_state"),
    ("campaign", "connection_statuses"),
    ("campaign", "area_connection_state"),
    ("campaign", "area_feature_state"),
    ("campaign", "hazard_statuses"),
    ("campaign", "hazard_state"),
    ("campaign", "interactable_statuses"),
    ("campaign", "interactable_state"),
    # Phase 5 — knowledge (pulled forward from Phase 7)
    ("knowledge", "knowledge_types"),
    ("knowledge", "truth_statuses"),
    ("knowledge", "knowledge_items"),
    ("knowledge", "entity_knowledge"),
    ("knowledge", "party_discoveries"),
    # Phase 6 — narrative events
    ("narrative", "event_statuses"),
    ("narrative", "event_types"),
    ("narrative", "event_participant_roles"),
    ("narrative", "events"),
    ("narrative", "event_participants"),
    ("narrative", "event_locations"),
    ("narrative", "event_causes"),
    ("narrative", "event_effects"),
    ("narrative", "event_observations"),
    # Phase 6 — interactions
    ("interaction", "interaction_types"),
    ("interaction", "interactions"),
    ("interaction", "actions"),
    ("interaction", "targets"),
    ("interaction", "check_requests"),
    ("interaction", "check_results"),
    ("interaction", "consequences"),
    ("interaction", "external_messages"),
    # Phase 7 — quests and knowledge
    ("narrative", "story_arcs"),
    ("narrative", "quests"),
    ("narrative", "quest_stages"),
    ("narrative", "objective_types"),
    ("narrative", "quest_objectives"),
    ("narrative", "objective_dependencies"),
    ("narrative", "quest_participants"),
    ("narrative", "quest_outcomes"),
    ("narrative", "quest_rewards"),
    ("campaign", "quest_statuses"),
    ("campaign", "quest_state"),
    ("campaign", "objective_statuses"),
    ("campaign", "objective_state"),
    ("knowledge", "knowledge_versions"),
    ("knowledge", "expertise_domains"),
    ("knowledge", "character_expertise"),
    ("knowledge", "information_transfers"),
    ("knowledge", "public_knowledge"),
    ("campaign", "party_knowledge"),
    # Phase 8 — relationships and organizations
    ("world", "relationship_types"),
    ("world", "relationship_participant_roles"),
    ("world", "relationships"),
    ("world", "relationship_participants"),
    ("world", "relationship_perspectives"),
    ("world", "organization_types"),
    ("world", "organizations"),
    ("world", "businesses"),
    ("world", "governments"),
    ("world", "military_units"),
    ("world", "political_factions"),
    ("world", "religions"),
    ("world", "religious_organizations"),
    ("character", "character_religious_affiliations"),
    ("world", "organization_memberships"),
    ("world", "employment_relationships"),
    ("world", "ownership_relationships"),
    ("world", "family_relationships"),
    ("world", "political_relationships"),
    ("campaign", "organization_statuses"),
    ("campaign", "organization_state"),
    ("campaign", "relationship_statuses"),
    ("campaign", "relationship_state"),
    # Phase 9 — item domain
    ("rules", "item_categories"),
    ("rules", "item_definitions"),
    ("world", "item_instances"),
    ("world", "item_containers"),
    ("campaign", "item_state"),
    ("campaign", "item_ownership"),
    ("campaign", "inventory_entries"),
    ("campaign", "item_attunements"),
    ("knowledge", "item_identification"),
    # Phase 9 — encounter domain
    ("narrative", "encounters"),
    ("narrative", "encounter_participants"),
    ("narrative", "encounter_rounds"),
    ("interaction", "combat_actions"),
    ("narrative", "encounter_turns"),
    # Phase 10, workstream 1 — security, identity, and access
    ("security", "membership_statuses"),
    ("security", "character_relationship_types"),
    ("security", "capabilities"),
    ("security", "external_identities"),
    ("security", "service_accounts"),
    ("security", "campaign_memberships"),
    ("security", "campaign_invitations"),
    ("security", "role_capabilities"),
    ("security", "membership_roles"),
    ("security", "membership_character_relationships"),
    ("security", "character_relationship_type_capabilities"),
    ("security", "access_groups"),
    ("security", "access_group_memberships"),
    ("security", "resource_grants"),
    # Phase 10, workstream 6 correction pass — durable command idempotency
    ("security", "idempotent_requests"),
]

# audit.change_log is deliberately excluded from MANAGED_TABLES: it is
# append-only to application roles (conventions §24.2), so the blanket
# "app_read_write holds full DML" expectation below does not apply to it.
# Its grants are asserted in test_audit_change_log.py instead.
#
# Every other table above holds the standard full-DML grant even where a
# *trigger* also makes it conditionally append-only (narrative.event_
# participants/_locations/_causes/_observations once their event leaves
# draft, revision 065; interaction.actions/targets/check_requests/
# check_results/external_messages once their interaction leaves initiated,
# revision 067). Those triggers enforce a state-dependent invariant business
# logic owns; unlike change_log, there is no state in which app_read_write
# should structurally lack UPDATE/DELETE on these tables — narrowing the
# GRANT itself would also block the legitimate pre-lock case (a still-draft
# event, a still-initiated interaction) the triggers are designed to allow.
EXCLUDED_TABLES: dict[tuple[str, str], str] = {
    ("audit", "change_log"): (
        "append-only to application roles at the grant level (conventions §24.2) — "
        "narrower grants than the standard set, asserted in test_audit_change_log.py"
    ),
    ("core", "alembic_version"): (
        "Alembic's own migration-bookkeeping table, not project data — owned and used "
        "by migration_runner/migration_owner only, never by an application role"
    ),
}

# Schemas MANAGED_TABLES claims full coverage of. Used only by the
# completeness tripwire below — a schema not listed here is out of scope for
# this file (e.g. a future 'ai' or 'quests' schema would get its own grants
# test file when it lands, the same way test_audit_change_log.py already
# does for one append-only table).
MANAGED_SCHEMAS = [
    "core",
    "security",
    "audit",
    "campaign",
    "rules",
    "character",
    "world",
    "knowledge",
    "narrative",
    "interaction",
]

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


# ---------------------------------------------------------------------------
# app_read_write's privilege boundaries — the constrained identity the
# containerized `api` service connects as (compose.yaml's own comment on
# that service). Static, catalog-level checks only; a real authenticated
# connection as app_read_write, proving these boundaries are enforced in
# practice rather than merely declared, lives in
# tests/database/test_app_read_write_role.py.
# ---------------------------------------------------------------------------


def test_app_read_write_is_not_a_superuser(db_connection: Connection) -> None:
    is_superuser = db_connection.execute(
        text("SELECT rolsuper FROM pg_roles WHERE rolname = 'app_read_write'")
    ).scalar()
    assert is_superuser is False


def test_app_read_write_cannot_create_databases(db_connection: Connection) -> None:
    can_createdb = db_connection.execute(
        text("SELECT rolcreatedb FROM pg_roles WHERE rolname = 'app_read_write'")
    ).scalar()
    assert can_createdb is False


def test_app_read_write_cannot_create_roles(db_connection: Connection) -> None:
    can_createrole = db_connection.execute(
        text("SELECT rolcreaterole FROM pg_roles WHERE rolname = 'app_read_write'")
    ).scalar()
    assert can_createrole is False


def test_app_read_write_cannot_bypass_row_level_security(db_connection: Connection) -> None:
    can_bypass_rls = db_connection.execute(
        text("SELECT rolbypassrls FROM pg_roles WHERE rolname = 'app_read_write'")
    ).scalar()
    assert can_bypass_rls is False


def test_app_read_write_is_not_a_member_of_migration_owner(db_connection: Connection) -> None:
    is_member = db_connection.execute(
        text("""
            SELECT EXISTS (
                SELECT 1 FROM pg_auth_members m
                JOIN pg_roles r ON r.oid = m.roleid
                JOIN pg_roles mem ON mem.oid = m.member
                WHERE r.rolname = 'migration_owner' AND mem.rolname = 'app_read_write'
            )
        """)
    ).scalar()
    assert is_member is False, (
        "app_read_write is a member of migration_owner — it would inherit every "
        "privilege migration_owner has, including implicit ownership of everything "
        "migration_owner owns, defeating the entire ADR 0009 split for this role."
    )


def test_app_read_write_owns_no_schema(db_connection: Connection) -> None:
    owned_schemas = [
        row.schema_name
        for row in db_connection.execute(
            text(
                "SELECT nspname AS schema_name FROM pg_namespace n "
                "JOIN pg_roles r ON r.oid = n.nspowner WHERE r.rolname = 'app_read_write'"
            )
        )
    ]
    assert not owned_schemas, (
        f"app_read_write owns schema(s) {owned_schemas} — schema objects must be owned by "
        "migration_owner only (ADR 0009), never a login role."
    )


def test_managed_tables_covers_every_table_in_every_managed_schema(
    db_connection: Connection,
) -> None:
    """The recurring gap this file itself once had (docs/PLAN.md §23.1): a
    table added to a managed schema without a matching MANAGED_TABLES/
    EXCLUDED_TABLES entry silently gets no coverage above, and nothing failed
    to say so. MANAGED_TABLES stays a static, `parametrize`-compatible list
    (pytest collects parametrize arguments before any fixture, including a
    database connection, exists), but this one schema-driven test closes the
    completeness gap: it fails, by name, the moment a table exists in a
    managed schema that neither list accounts for.
    """
    live_tables = {
        (row.schemaname, row.tablename)
        for row in db_connection.execute(
            text("SELECT schemaname, tablename FROM pg_tables WHERE schemaname = ANY(:schemas)"),
            {"schemas": MANAGED_SCHEMAS},
        )
    }
    covered = set(MANAGED_TABLES) | set(EXCLUDED_TABLES)
    missing = live_tables - covered
    assert not missing, (
        f"tables present in a managed schema but missing from MANAGED_TABLES/"
        f"EXCLUDED_TABLES in test_role_grants.py: {sorted(missing)}"
    )

    stale = covered - live_tables
    assert not stale, (
        f"MANAGED_TABLES/EXCLUDED_TABLES in test_role_grants.py names a table that no "
        f"longer exists: {sorted(stale)}"
    )
