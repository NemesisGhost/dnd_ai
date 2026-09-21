"""Add lifecycle_status_id to security.access_groups

Revision ID: 105_access_group_status
Revises: 104_audit_history_indexes
Create Date: 2026-09-20 09:00:00.000000

Purpose:
    Phase 13E-B checkpoint 6 (campaign access-group management). Revision
    080 created `security.access_groups` with no operational lifecycle
    column at all — only `campaign_id`, `name`, `description`, and the
    shared `created_at`/`updated_at` pair. That left no way to deactivate a
    group without physically deleting it (CLAUDE.md rule 9: persistent
    world entities are archived, not deleted) and no way to tell an active
    group from a retired one on any read path.

    This revision adds `lifecycle_status_id`, referencing the same shared
    `core.lifecycle_statuses` lookup every other long-lived entity in this
    schema already uses (`campaign.campaigns`, `campaign.timelines`,
    `campaign.sessions`, `core.entities`, `security.users`) — not a new,
    bespoke boolean or a second lifecycle vocabulary. `dnd_ai.commands.
    access_groups.create_access_group()` sets it to `active` at creation;
    `deactivate_access_group()`/`reactivate_access_group()` (checkpoint 6)
    move it to `archived`/back to `active` — the identical archive/restore
    pattern docs/ENTITY_LIFECYCLE.md §12/§13 already documents for every
    other archivable entity, applied here for the first time to a security
    concept rather than a world one. No new lookup codes are introduced;
    `pending`/`inactive`/`deleted` remain legal at the database layer (the
    same full lookup table every other lifecycle_status_id column
    references) even though this checkpoint's own commands only ever write
    `active`/`archived` — the same "FK to the shared lookup, application
    layer governs the meaningful subset of transitions" convention
    `campaign.campaigns.lifecycle_status_id` already establishes.

    Reactivating a group only ever flips this one column back to `active`
    — `dnd_ai.commands.access_groups.reactivate_access_group()` touches no
    other row. Deactivation closes every open `security.
    access_group_memberships` row and revokes every active `security.
    resource_grants` row owned by the group in the same transaction as the
    status change (checkpoint 6's own command, not this migration), so a
    later reactivation starts from an empty, powerless group exactly as
    docs/ENTITY_LIFECYCLE.md §13 requires ("restoring... does not
    automatically reverse" other state) — never a silent restoration of
    pre-deactivation access.

Forward migration:
    - `security.access_groups`: `ADD COLUMN lifecycle_status_id UUID
      REFERENCES core.lifecycle_statuses(lifecycle_status_id) ON DELETE
      RESTRICT`, backfilled to the seeded `active` row for every existing
      group (there are none outside test fixtures, which roll back, but a
      real deployment's rows — if any — must not end up excluded from
      every list this checkpoint's read contract returns), then `SET NOT
      NULL`.
    - `ix_access_groups_lifecycle_status_id` — matches every other
      `lifecycle_status_id` column's own indexing convention
      (`ix_campaigns_lifecycle_status_id`, `ix_users_lifecycle_status_id`,
      ...), needed for `dnd_ai.commands.access_groups.
      deactivate_access_group()`/`reactivate_access_group()`'s own `WHERE
      lifecycle_status_id = ...` row lookups and the read query's `WHERE
      ls.code = ...` filters.

Rollback:
    Supported. Drops the index, then the column. No other schema object
    depends on this column yet (checkpoint 6's own commands/queries are
    application code, not schema).

Data implications:
    No `security.access_groups` rows exist outside test fixtures today, so
    the backfill has nothing to actually migrate in practice — the `UPDATE`
    is included for correctness against a future real deployment that has
    since created groups, mirroring `024_campaign_ruleset_version`'s
    identical "no rows today, but backfill anyway" reasoning.

Locking considerations:
    `ADD COLUMN ... NULL` is metadata-only. The following `UPDATE`/`SET NOT
    NULL` pair touches at most a handful of rows on a pre-production schema
    with no live deployment yet — not a concern at this data volume,
    matching this codebase's own established convention for a plain
    (non-`CONCURRENTLY`) index addition after a table already exists (e.g.
    `098_ai_domain_fk_indexes`, `104_audit_history_indexes`).

See: src/dnd_ai/persistence/tables/security.py (the matching declared
     column/index)
     src/dnd_ai/commands/access_groups.py (checkpoint 6's own lifecycle
     commands)
     docs/ENTITY_LIFECYCLE.md §12/§13 (archive/restore)
     docs/DATABASE_CONVENTIONS.md §11 (lookup tables)
     database/migrations/versions/080_security_identity_and_access.py (the
     table this revision extends)
     database/migrations/versions/024_campaign_ruleset_version.py (the
     identical add/backfill/not-null precedent this migration follows)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "105_access_group_status"
down_revision = "104_audit_history_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""
    op.execute("""
        ALTER TABLE security.access_groups
        ADD COLUMN lifecycle_status_id UUID
        REFERENCES core.lifecycle_statuses(lifecycle_status_id) ON DELETE RESTRICT;
    """)
    op.execute("""
        UPDATE security.access_groups
        SET lifecycle_status_id = (
            SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'active'
        )
        WHERE lifecycle_status_id IS NULL;
    """)
    op.execute("ALTER TABLE security.access_groups ALTER COLUMN lifecycle_status_id SET NOT NULL;")
    op.execute("""
        COMMENT ON COLUMN security.access_groups.lifecycle_status_id IS
        'Whether this group is currently active or has been deactivated/archived '
        '(docs/ENTITY_LIFECYCLE.md §12/§13). Deactivation closes the group''s open '
        'memberships and revokes its active resource grants in the same transaction '
        '(dnd_ai.commands.access_groups.deactivate_access_group) rather than deleting the '
        'group row; reactivation only ever flips this column back — it never restores '
        'those closed memberships or revoked grants.';
    """)
    op.execute(
        "CREATE INDEX ix_access_groups_lifecycle_status_id "
        "ON security.access_groups (lifecycle_status_id);"
    )


def downgrade() -> None:
    """Revert the migration."""
    op.execute("DROP INDEX IF EXISTS security.ix_access_groups_lifecycle_status_id;")
    op.execute("ALTER TABLE security.access_groups DROP COLUMN lifecycle_status_id;")
