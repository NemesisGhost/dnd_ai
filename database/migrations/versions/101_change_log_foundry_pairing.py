"""Add audit.change_log.acting_foundry_connection_id/acting_foundry_device_id

Revision ID: 101_change_log_foundry_pairing
Revises: 100_foundry_pairing
Create Date: 2026-08-22 09:00:00.000000

Purpose:
    Phase 11R workstream G (docs/PLAN.md §23.5, Workstream 11R item 4):
    "Update audit attribution to record the authoritative D&D AI user plus
    connection/external system, Foundry user, device, and access-token/
    session identifiers." `acting_external_system_id` (migration 091)
    already covers the "external system" half for both the legacy
    `FoundrySystem` credential and the new paired `FoundryAccess` one —
    `dnd_ai.domain.access.AuthenticatedPrincipal.foundry_external_system_id`
    is populated for both auth methods since Phase 11R workstream C. This
    migration adds the two fields only `FOUNDRY_ACCESS_AUTH_METHOD` carries
    that the legacy credential never had: which `security.foundry_
    connections` row (identity: D&D AI user, campaign, external system,
    Foundry user) and which `security.foundry_devices` row (identity: one
    specific paired browser/device) authenticated the request.

    `acting_foundry_actor_id` (migration 092) is deliberately not extended
    or duplicated for the new credential type: a paired connection already
    names its one Foundry user directly (`security.foundry_connections.
    foundry_user_id`), so there is no "claimed, unverified actor" concept
    the way the legacy shared credential's `X-Foundry-Actor-Id` header
    had — `dnd_ai.domain.access.AuthenticatedPrincipal.__post_init__`
    enforces that `foundry_claimed_actor_id` is `None` for a
    `FOUNDRY_ACCESS_AUTH_METHOD` principal, so this migration adds no new
    column duplicating that already-`None` field.

Forward migration:
    `audit.change_log`:
      - `acting_foundry_connection_id UUID NULL REFERENCES security.
        foundry_connections(foundry_connection_id) ON DELETE SET NULL`
      - `acting_foundry_device_id UUID NULL REFERENCES security.
        foundry_devices(foundry_device_id) ON DELETE SET NULL`
      - `ix_change_log_acting_foundry_connection_id`/`ix_change_log_
        acting_foundry_device_id`: partial indexes (`WHERE ... IS NOT
        NULL`), the identical shape `ix_change_log_acting_external_
        system_id` (migration 091) already established.

Rollback:
    Supported. Drops both indexes then both columns. Any row that had a
    non-NULL value for either loses that fact — audit rows themselves are
    otherwise untouched.

Data implications:
    Every existing `audit.change_log` row gets both new columns `NULL`
    (metadata-only column add, no backfill possible or needed: nothing
    before this migration recorded either fact, and the paired-device
    credential this records did not exist before migration 100).

Locking considerations:
    Identical reasoning to migration 091: both `ADD COLUMN ... UUID` with
    no default are metadata-only changes on PostgreSQL 11+, both `ADD
    CONSTRAINT ... FOREIGN KEY` validation scans resolve every existing
    (NULL) row without consulting the referenced table, and both `CREATE
    INDEX` calls have nothing to build for any pre-migration row under
    their partial predicate.

See: database/migrations/versions/091_change_log_ext_system.py
     (the identical pattern this migration repeats for the new columns)
     database/migrations/versions/100_foundry_pairing.py
     (security.foundry_connections/.foundry_devices — this migration's
     own referenced tables)
     src/dnd_ai/domain/access.py (AuthenticatedPrincipal — this
     migration's conceptual source)
     src/dnd_ai/api/audit.py (record_change_log — these columns' only
     writer)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "101_change_log_foundry_pairing"
down_revision = "100_foundry_pairing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    op.execute("""
        ALTER TABLE audit.change_log
            ADD COLUMN acting_foundry_connection_id UUID
                REFERENCES security.foundry_connections(foundry_connection_id)
                ON DELETE SET NULL;
    """)
    op.execute("""
        COMMENT ON COLUMN audit.change_log.acting_foundry_connection_id IS
        'The security.foundry_connections row that authenticated this change via '
        'a paired FoundryAccess credential (dnd_ai.domain.access.'
        'AuthenticatedPrincipal.foundry_connection_id, Phase 11R workstream G) — '
        'the connection already names the one Foundry user bound to actor_user_id, '
        'so there is no claimed-actor-id concept for this credential type the way '
        'acting_foundry_actor_id is for the legacy one. NULL for every OIDC-, '
        'local-session-, or legacy-FoundrySystem-authenticated change.';
    """)
    op.execute("""
        ALTER TABLE audit.change_log
            ADD COLUMN acting_foundry_device_id UUID
                REFERENCES security.foundry_devices(foundry_device_id) ON DELETE SET NULL;
    """)
    op.execute("""
        COMMENT ON COLUMN audit.change_log.acting_foundry_device_id IS
        'The security.foundry_devices row whose access token authenticated this '
        'change (dnd_ai.domain.access.AuthenticatedPrincipal.foundry_device_id, '
        'Phase 11R workstream G) — set alongside acting_foundry_connection_id, '
        'identifying which of the connection''s possibly-several paired devices '
        'made this specific request. NULL for every change not authenticated via '
        'a paired FoundryAccess credential.';
    """)
    op.execute("""
        CREATE INDEX ix_change_log_acting_foundry_connection_id
        ON audit.change_log (acting_foundry_connection_id)
        WHERE acting_foundry_connection_id IS NOT NULL;
    """)
    op.execute("""
        CREATE INDEX ix_change_log_acting_foundry_device_id
        ON audit.change_log (acting_foundry_device_id)
        WHERE acting_foundry_device_id IS NOT NULL;
    """)


def downgrade() -> None:
    """Revert the migration."""

    op.execute("DROP INDEX IF EXISTS audit.ix_change_log_acting_foundry_device_id;")
    op.execute("DROP INDEX IF EXISTS audit.ix_change_log_acting_foundry_connection_id;")
    op.execute("ALTER TABLE audit.change_log DROP COLUMN IF EXISTS acting_foundry_device_id;")
    op.execute("ALTER TABLE audit.change_log DROP COLUMN IF EXISTS acting_foundry_connection_id;")
