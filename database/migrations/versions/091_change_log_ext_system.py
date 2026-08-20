"""Add audit.change_log.acting_external_system_id

Revision ID: 091_change_log_ext_system
Revises: 090_character_state_event_types
Create Date: 2026-08-19 15:00:00.000000

Purpose:
    Phase 11 workstream 2 correction: closes a critical Foundry-adapter
    authentication scope defect (docs/PHASE11_VERIFICATION.md /
    `src/dnd_ai/domain/access.py`'s `AuthenticatedPrincipal` docstring have
    the full account). Part of that correction restricts a `FoundrySystem`
    credential to a narrow, explicitly opted-in set of adapter-facing
    routes and binds it to the world it actually authenticated as — but
    conventions §24.3 also requires audit records to identify "user,
    service, AI agent, integration ... where applicable" (plural: an
    adapter-delegated change genuinely has both an identity — the linked
    `actor_user_id` `link_foundry_identity` established — and a delegating
    integration that isn't itself a person). `audit.change_log.
    actor_service` (migration 007) is documented as "set instead of
    actor_user_id" — the wrong shape for this case, which must keep the
    real linked actor_user_id *and* additionally record which
    `integration.external_systems` row authenticated the request, so
    operators can distinguish an ordinary OIDC user action from one made
    through a delegated Foundry credential without losing either fact.

Forward migration:
    `audit.change_log`:
      - `acting_external_system_id UUID NULL REFERENCES integration.
        external_systems(external_system_id) ON DELETE SET NULL` — the
        `integration.external_systems` row that authenticated the request
        via a `FoundrySystem` credential
        (`dnd_ai.domain.access.AuthenticatedPrincipal.
        foundry_external_system_id`), NULL for every OIDC-authenticated
        change (the overwhelming majority, and every row recorded before
        this migration). `ON DELETE SET NULL`, not `RESTRICT` or
        `CASCADE`: `audit.change_log` rows outlive the records — and, by
        the same reasoning, the external-system registrations — they
        describe (migration 007's own table comment), so deleting an
        `integration.external_systems` row must never cascade into
        deleting audit history, nor block the deletion because old audit
        rows still reference it.
      - `ix_change_log_acting_external_system_id`: a partial index (`WHERE
        acting_external_system_id IS NOT NULL`), mirroring `ix_change_log_
        source_id`'s own shape — supports "show me every change a given
        Foundry adapter made" without indexing the NULL-for-almost-every-row
        common case.

Rollback:
    Supported. Drops the index then the column. Any row that had a non-NULL
    `acting_external_system_id` loses that fact — audit rows themselves are
    otherwise untouched.

Data implications:
    Every existing `audit.change_log` row gets `acting_external_system_id
    = NULL` (metadata-only column add, no backfill possible or needed:
    nothing before this migration recorded which system authenticated a
    request).

Locking considerations:
    `ADD COLUMN ... UUID` with no default is a metadata-only change on
    PostgreSQL 11+ (no table rewrite). The `ADD CONSTRAINT ... FOREIGN KEY`
    requires a validation scan of `audit.change_log`, which can be a large,
    high-volume append-only table (migration 007's own description) — but
    every existing row is NULL for this new column, so the FK validation
    scan has nothing to check per row beyond "is this NULL," which
    PostgreSQL resolves without consulting the referenced table at all;
    this is not expected to hold a lock for material duration even on a
    large table. `CREATE INDEX` (not `CREATE INDEX CONCURRENTLY`) does take
    a table-level lock for its own duration — acceptable here since the
    partial predicate means the index has nothing to build for any
    pre-migration row.

See: database/migrations/versions/007_audit_change_log.py
     (audit.change_log's own creation, and actor_service's "instead of"
     semantics this column deliberately does not reuse)
     database/migrations/versions/079_integration_domain.py
     (integration.external_systems' own creation)
     src/dnd_ai/domain/access.py (AuthenticatedPrincipal — this column's
     conceptual source)
     src/dnd_ai/api/audit.py (record_change_log — this column's only
     writer)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "091_change_log_ext_system"
down_revision = "090_character_state_event_types"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    op.execute("""
        ALTER TABLE audit.change_log
            ADD COLUMN acting_external_system_id UUID
                REFERENCES integration.external_systems(external_system_id) ON DELETE SET NULL;
    """)
    op.execute("""
        COMMENT ON COLUMN audit.change_log.acting_external_system_id IS
        'The integration.external_systems row that authenticated this change '
        'via a FoundrySystem credential (dnd_ai.domain.access.'
        'AuthenticatedPrincipal.foundry_external_system_id), when it was made '
        'through a delegated adapter credential rather than directly by the '
        'person actor_user_id represents. NULL for every OIDC-authenticated '
        'change. Distinct from actor_service, which is set instead of '
        'actor_user_id for a non-human actor with no linked user at all — '
        'this column is set alongside actor_user_id, never instead of it.';
    """)
    op.execute("""
        CREATE INDEX ix_change_log_acting_external_system_id
        ON audit.change_log (acting_external_system_id)
        WHERE acting_external_system_id IS NOT NULL;
    """)


def downgrade() -> None:
    """Revert the migration."""

    op.execute("DROP INDEX IF EXISTS audit.ix_change_log_acting_external_system_id;")
    op.execute("""
        ALTER TABLE audit.change_log
            DROP COLUMN IF EXISTS acting_external_system_id;
    """)
