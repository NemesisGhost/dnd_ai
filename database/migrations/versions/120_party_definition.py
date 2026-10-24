"""Add party versioning and lifecycle (campaign.parties)

Revision ID: 120_party_definition
Revises: 119_character_build_activated
Create Date: 2026-10-05 20:00:00.000000

Purpose:
    Phase 15 checkpoint 15.2C-1 (decision D-30, option a). A GM creates, edits,
    archives, and restores a party and attaches it to a campaign. That needs the
    optimistic-concurrency token and the operational lifecycle the other authored
    records already carry (`row_version`, `lifecycle_status_id`, `archived_at`,
    `created_by_user_id`). Membership stays timeline state in
    `campaign.party_memberships` (checkpoint 15.2C-2).

Forward migration:
    On `campaign.parties`:
    - `row_version BIGINT NOT NULL DEFAULT 1` (CHECK >= 1), bumped by the shared
      `core.bump_row_version()` trigger.
    - `lifecycle_status_id UUID NOT NULL REFERENCES core.lifecycle_statuses`,
      backfilled to `active` for every existing party. A `BEFORE INSERT` trigger
      fills a NULL value with `active`, so inserts that predate this revision (test
      factories, operator scripts) keep working; the authoring commands set it
      explicitly.
    - `archived_at TIMESTAMPTZ NULL`, set when archived and cleared on restore.
    - `created_by_user_id UUID NULL REFERENCES security.users ON DELETE SET NULL`.
    - Indexes for the two new foreign keys.

Rollback:
    Supported. Drops the trigger, function, columns, and indexes. Lifecycle state
    and versions are lost (archived parties become indistinguishable from active
    ones); downgrade is intended for development databases.

Data implications:
    Existing parties become `active`, version 1, no creator.

Locking considerations:
    ADD COLUMN with a constant default is metadata-only; the NOT NULL backfill of
    `lifecycle_status_id` rewrites the (small) parties table once.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "120_party_definition"
down_revision = "119_character_build_activated"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE campaign.parties
        ADD COLUMN row_version BIGINT NOT NULL DEFAULT 1,
        ADD CONSTRAINT ck_parties_row_version_positive CHECK (row_version >= 1),
        ADD COLUMN lifecycle_status_id UUID
            REFERENCES core.lifecycle_statuses(lifecycle_status_id) ON DELETE RESTRICT,
        ADD COLUMN archived_at TIMESTAMPTZ,
        ADD COLUMN created_by_user_id UUID
            REFERENCES security.users(user_id) ON DELETE SET NULL;
    """)
    op.execute("""
        UPDATE campaign.parties
        SET lifecycle_status_id = (
            SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'active'
        );
    """)
    op.execute("ALTER TABLE campaign.parties ALTER COLUMN lifecycle_status_id SET NOT NULL;")
    op.execute("""
        COMMENT ON COLUMN campaign.parties.row_version IS
        'Optimistic-concurrency token, incremented by every UPDATE '
        '(core.bump_row_version()). Authoring commands require the caller''s '
        'expected_row_version to equal it under a row lock and reject a stale write.';
    """)
    op.execute("""
        COMMENT ON COLUMN campaign.parties.lifecycle_status_id IS
        'Operational lifecycle (active or archived). An archived party stays referenced by '
        'its history, is hidden from pickers, and takes no new membership or knowledge writes.';
    """)
    op.execute("""
        COMMENT ON COLUMN campaign.parties.archived_at IS
        'When the party was archived; NULL while active.';
    """)
    op.execute("""
        COMMENT ON COLUMN campaign.parties.created_by_user_id IS
        'The authenticated human who created the party through the authoring command; NULL '
        'for parties created before revision 120 or by operator tooling.';
    """)
    op.execute(
        "CREATE INDEX ix_parties_lifecycle_status_id ON campaign.parties (lifecycle_status_id);"
    )
    op.execute(
        "CREATE INDEX ix_parties_created_by_user_id ON campaign.parties (created_by_user_id) "
        "WHERE created_by_user_id IS NOT NULL;"
    )
    op.execute("""
        CREATE TRIGGER tr_parties_bump_row_version
        BEFORE UPDATE ON campaign.parties
        FOR EACH ROW EXECUTE FUNCTION core.bump_row_version();
    """)
    op.execute("""
        CREATE FUNCTION campaign.default_party_lifecycle()
        RETURNS trigger LANGUAGE plpgsql AS $fn$
        BEGIN
            IF NEW.lifecycle_status_id IS NULL THEN
                SELECT lifecycle_status_id INTO NEW.lifecycle_status_id
                FROM core.lifecycle_statuses WHERE code = 'active';
            END IF;
            RETURN NEW;
        END
        $fn$;
    """)
    op.execute("""
        COMMENT ON FUNCTION campaign.default_party_lifecycle() IS
        'A party inserted without a lifecycle status starts active.';
    """)
    op.execute("""
        CREATE TRIGGER tr_parties_default_lifecycle
        BEFORE INSERT ON campaign.parties
        FOR EACH ROW EXECUTE FUNCTION campaign.default_party_lifecycle();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS tr_parties_default_lifecycle ON campaign.parties;")
    op.execute("DROP FUNCTION IF EXISTS campaign.default_party_lifecycle();")
    op.execute("DROP TRIGGER IF EXISTS tr_parties_bump_row_version ON campaign.parties;")
    op.execute("DROP INDEX IF EXISTS campaign.ix_parties_created_by_user_id;")
    op.execute("DROP INDEX IF EXISTS campaign.ix_parties_lifecycle_status_id;")
    op.execute("""
        ALTER TABLE campaign.parties
        DROP COLUMN IF EXISTS created_by_user_id,
        DROP COLUMN IF EXISTS archived_at,
        DROP COLUMN IF EXISTS lifecycle_status_id,
        DROP CONSTRAINT IF EXISTS ck_parties_row_version_positive,
        DROP COLUMN IF EXISTS row_version;
    """)
