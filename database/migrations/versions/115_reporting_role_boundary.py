"""Make app_read_only deny-by-default (reporting-role boundary)

Revision ID: 115_reporting_role_boundary
Revises: 114_relationship_defaults
Create Date: 2026-10-05 13:00:00.000000

Purpose:
    Phase 15 checkpoint 15.2A-2 (docs/DATABASE_CONVENTIONS.md §27.1, §27.4).
    Revision 001 granted `app_read_only` SELECT on every present and future
    table. That made it an unrestricted read path to password hashes, activation/
    reset/invitation/onboarding/session token hashes and stored CSRF values,
    Foundry pairing and device secrets, integration key hashes, every idempotency
    request and replay body, the audit log, AI prompt and context tables, and all
    GM-only authored content -- and it would have been a read path to any future
    private table.

    Consumer inventory (checked 2026-10-05): the role has no runtime consumer.
    `compose.yaml`'s `api` service connects as `app_read_write`;
    `scripts/operations/database_recovery.py` only asserts the role exists and is
    a LOGIN role; `terraform/modules/database/variables.tf` lists it for IAM
    login; the rest are documentation and grant tests. Nothing reads data as it.

Target design (decision D-5, option a: deny by default):
    `app_read_only` holds SELECT only on an explicit allowlist of lookup and
    seeded rules-reference tables (`REPORTING_READABLE_TABLES` below). Every
    other present table is revoked, and default privileges for tables that
    `migration_owner` creates in any schema no longer grant SELECT to it, so a
    future table (including a Phase 16 `collaboration` schema) is denied until a
    migration grants it deliberately. Reporting that needs more goes through
    reviewed views in a future `reporting` schema; none is needed today. No
    row-level security is introduced (no demonstrated need; it would add
    per-session policy context to every runtime query).

    Administrator and migration authority are unchanged and are separate from
    reporting access: `admin_maintenance` (break-glass human access) and
    `migration_owner`/`migration_runner` keep their existing privileges, and
    `app_read_write` and `integration_worker` are untouched. Sequences are left
    as granted (a sequence value is not sensitive).

Forward migration:
    For every application schema: REVOKE SELECT on all tables from
    `app_read_only`; ALTER DEFAULT PRIVILEGES FOR ROLE migration_owner ... REVOKE
    SELECT ON TABLES FROM app_read_only. Then GRANT SELECT on the allowlist.

Rollback:
    Restores revision 001's behaviour: grants SELECT on all tables in every
    application schema to `app_read_only` and restores the default privilege.

Data implications:
    None (privileges only).

Locking considerations:
    GRANT/REVOKE take brief catalog locks. No table rewrite.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "115_reporting_role_boundary"
down_revision = "114_relationship_defaults"
branch_labels = None
depends_on = None

_SCHEMAS = (
    "core",
    "security",
    "audit",
    "rules",
    "character",
    "world",
    "campaign",
    "narrative",
    "knowledge",
    "interaction",
    "ai",
    "import",
    "integration",
)

# Lookup tables (code/display-name vocabularies, no world/campaign/user scope)
# and seeded, ruleset-wide reference content. Deliberately excluded:
# `rules.item_definitions` (gains world-owned homebrew in Phase 15) and
# `rules.world_rulesets` (world configuration).
REPORTING_READABLE_TABLES = (
    "ai.agent_roles",
    "audit.change_actions",
    "campaign.connection_statuses",
    "campaign.hazard_statuses",
    "campaign.interactable_statuses",
    "campaign.objective_statuses",
    "campaign.organization_statuses",
    "campaign.quest_statuses",
    "campaign.relationship_statuses",
    "core.canon_statuses",
    "core.lifecycle_statuses",
    "core.name_types",
    "core.source_types",
    "core.world_time_precisions",
    "interaction.interaction_types",
    "knowledge.expertise_domains",
    "knowledge.knowledge_types",
    "knowledge.truth_statuses",
    "narrative.event_participant_roles",
    "narrative.event_statuses",
    "narrative.event_types",
    "narrative.objective_types",
    "rules.item_categories",
    "security.capabilities",
    "security.character_relationship_types",
    "security.membership_statuses",
    "security.world_roles",
    "world.connection_types",
    "world.organization_types",
    "world.relationship_participant_roles",
    "world.relationship_types",
    "rules.abilities",
    "rules.classes",
    "rules.conditions",
    "rules.creature_types",
    "rules.damage_types",
    "rules.feats",
    "rules.features",
    "rules.languages",
    "rules.proficiency_types",
    "rules.resource_definitions",
    "rules.ruleset_versions",
    "rules.rulesets",
    "rules.skills",
    "rules.species",
    "rules.spells",
    "rules.subclasses",
)


def upgrade() -> None:
    for schema in _SCHEMAS:
        op.execute(f'REVOKE SELECT ON ALL TABLES IN SCHEMA "{schema}" FROM app_read_only;')
        op.execute(
            f'ALTER DEFAULT PRIVILEGES FOR ROLE migration_owner IN SCHEMA "{schema}" '
            "REVOKE SELECT ON TABLES FROM app_read_only;"
        )
    for table in REPORTING_READABLE_TABLES:
        op.execute(f"GRANT SELECT ON {table} TO app_read_only;")


def downgrade() -> None:
    for schema in _SCHEMAS:
        op.execute(f'GRANT SELECT ON ALL TABLES IN SCHEMA "{schema}" TO app_read_only;')
        op.execute(
            f'ALTER DEFAULT PRIVILEGES FOR ROLE migration_owner IN SCHEMA "{schema}" '
            "GRANT SELECT ON TABLES TO app_read_only;"
        )
