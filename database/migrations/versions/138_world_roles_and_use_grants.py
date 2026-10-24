"""Add world Editor/Reviewer/Reader roles, multi-role memberships, and world-use grants

Revision ID: 138_world_roles_and_use_grants
Revises: 137_system_roles
Create Date: 2026-10-06 19:00:00.000000

Purpose:
    Scoped-role authorization, checkpoint SR-4
    (docs/SCOPED_ROLE_IMPLEMENTATION_PLAN.md,
    docs/adr/0020-scoped-system-world-and-campaign-roles.md). Authority over a world
    was owner-only and one row per (world, user). This revision lets a user hold
    several world roles at once, adds the Editor, Reviewer and Reader roles, records
    who granted and ended each assignment, and adds a separate world-use grant
    (permission to host a campaign on a world, nothing else).

Forward migration:
    1. Inserts `world_editor`, `world_reviewer` and `world_reader` into
       `security.world_roles` with explicit idempotent INSERTs (the seed file is frozen
       since revision 110; `world_owner` and `world_viewer` are unchanged) and protects
       the five codes from rename, because application code maps capabilities by code.
    2. `security.world_memberships`: adds `granted_by_user_id` and `ended_by_user_id`
       (nullable foreign keys, partial indexes); replaces the "one open row per
       (world, user)" unique index with "one open row per (world, user, role)". The
       owner-retention trigger is unchanged: it already filters on `world_owner`.
    3. `security.world_use_grants`: one open grant per (world, user); revoked rows
       are history. `world_id` and `user_id` are immutable.

Rollback:
    Supported but lossy: deletes every Editor, Reviewer and Reader membership row (the old
    model cannot represent several roles per user; an open Viewer row beside an Owner row
    is closed, not deleted) and every use grant, drops the new columns and table,
    removes the three seeded roles, and restores the original unique index.

Data implications:
    No backfill. Existing owners keep their single `world_owner` row. Nobody gains an
    Editor, Reviewer or Reader role, or a use grant, because of this revision.

Locking considerations:
    New table; ALTER TABLE ... ADD COLUMN (nullable, no rewrite) and an index swap on
    `security.world_memberships`, which is small.

See: docs/adr/0020-scoped-system-world-and-campaign-roles.md
     src/dnd_ai/persistence/tables/security.py (the matching declared tables)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "138_world_roles_and_use_grants"
down_revision = "137_system_roles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""
    # Explicit INSERTs, not an edit of `database/seeds/security.world_roles.yaml`: revision 110
    # consumed that file, so it is frozen (docs/DATABASE_CONVENTIONS.md section 25.4); the same
    # approach revision 136 took for `world_viewer`. Idempotent (`ON CONFLICT (code)`).
    op.execute("""
        INSERT INTO security.world_roles (code, display_name, description, sort_order, is_active)
        VALUES
            ('world_editor', 'World editor',
             'Creates and edits the world''s definitions and manages its timelines. Cannot '
             'approve or publish canon, share the world, or change its settings.', 30, true),
            ('world_reviewer', 'World reviewer',
             'Reads the world''s drafts and revisions and approves, publishes, supersedes, '
             'archives and restores its canon. Cannot create or edit definitions.', 40, true),
            ('world_reader', 'World reader',
             'Reads the world''s published canon in its player-safe form. No drafts, GM-only '
             'fields, revisions, provenance or campaign data.', 50, true)
        ON CONFLICT (code) DO NOTHING;
    """)
    op.execute("""
        CREATE TRIGGER tr_world_roles_enforce_protected_codes
        BEFORE UPDATE ON security.world_roles
        FOR EACH ROW EXECUTE FUNCTION core.enforce_protected_lookup_codes(
            'world_owner', 'world_viewer', 'world_editor', 'world_reviewer', 'world_reader'
        );
    """)
    op.execute("""
        COMMENT ON TABLE security.world_roles IS
        'Roles a user can hold on a world: world_owner, world_viewer, world_editor, world_reviewer, '
        'world_reader. A user may hold several at once. Capabilities are a closed mapping '
        'in application code (dnd_ai.domain.world_authority), not rows in '
        'security.capabilities, which is assignable to campaign roles '
        '(docs/adr/0020-scoped-system-world-and-campaign-roles.md).';
    """)

    op.execute("""
        ALTER TABLE security.world_memberships
            ADD COLUMN granted_by_user_id UUID
                REFERENCES security.users(user_id) ON DELETE RESTRICT,
            ADD COLUMN ended_by_user_id UUID
                REFERENCES security.users(user_id) ON DELETE RESTRICT;
    """)
    op.execute(
        "COMMENT ON COLUMN security.world_memberships.granted_by_user_id IS "
        "'The user who assigned this role; NULL for the world creator, operator claims and "
        "rows that predate this column.';"
    )
    op.execute(
        "COMMENT ON COLUMN security.world_memberships.ended_by_user_id IS "
        "'The user who ended this assignment; NULL while it is open.';"
    )
    op.execute(
        "CREATE INDEX ix_world_memberships_granted_by_user_id "
        "ON security.world_memberships (granted_by_user_id) "
        "WHERE granted_by_user_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_world_memberships_ended_by_user_id "
        "ON security.world_memberships (ended_by_user_id) "
        "WHERE ended_by_user_id IS NOT NULL;"
    )
    op.execute("DROP INDEX security.ux_world_memberships_open;")
    op.execute("""
        CREATE UNIQUE INDEX ux_world_memberships_open
        ON security.world_memberships (world_id, user_id, world_role_id)
        WHERE ended_at IS NULL;
    """)

    op.execute("""
        CREATE TABLE security.world_use_grants (
            world_use_grant_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            world_id            UUID NOT NULL
                                 REFERENCES core.worlds(world_id) ON DELETE CASCADE,
            user_id             UUID NOT NULL
                                 REFERENCES security.users(user_id) ON DELETE RESTRICT,
            granted_by_user_id  UUID NOT NULL
                                 REFERENCES security.users(user_id) ON DELETE RESTRICT,
            granted_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            revoked_at          TIMESTAMPTZ,
            revoked_by_user_id  UUID
                                 REFERENCES security.users(user_id) ON DELETE RESTRICT,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_world_use_grants_revoked_after_granted CHECK (
                revoked_at IS NULL OR revoked_at >= granted_at
            ),
            CONSTRAINT ck_world_use_grants_revoker_requires_revocation CHECK (
                revoked_by_user_id IS NULL OR revoked_at IS NOT NULL
            )
        );
    """)
    op.execute("""
        COMMENT ON TABLE security.world_use_grants IS
        'Permission for a user to host a campaign on a world and nothing else: it confers '
        'world.view and campaign.create (and no canon read, no timeline management). Open '
        'rows (revoked_at IS NULL) authorize; revoking stops new campaigns only -- existing '
        'campaigns are unaffected. Never deleted by commands '
        '(docs/adr/0020-scoped-system-world-and-campaign-roles.md).';
    """)
    op.execute("CREATE INDEX ix_world_use_grants_world_id ON security.world_use_grants (world_id);")
    op.execute("CREATE INDEX ix_world_use_grants_user_id ON security.world_use_grants (user_id);")
    op.execute(
        "CREATE INDEX ix_world_use_grants_granted_by_user_id "
        "ON security.world_use_grants (granted_by_user_id);"
    )
    op.execute(
        "CREATE INDEX ix_world_use_grants_revoked_by_user_id "
        "ON security.world_use_grants (revoked_by_user_id) "
        "WHERE revoked_by_user_id IS NOT NULL;"
    )
    op.execute("""
        CREATE UNIQUE INDEX ux_world_use_grants_open
        ON security.world_use_grants (world_id, user_id)
        WHERE revoked_at IS NULL;
    """)
    op.execute("""
        CREATE TRIGGER tr_world_use_grants_set_updated_at
        BEFORE UPDATE ON security.world_use_grants
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute("""
        CREATE TRIGGER tr_world_use_grants_enforce_immutable
        BEFORE UPDATE ON security.world_use_grants
        FOR EACH ROW EXECUTE FUNCTION core.enforce_immutable_columns('world_id', 'user_id');
    """)


def downgrade() -> None:
    """Revert the migration."""
    op.execute("DROP TABLE IF EXISTS security.world_use_grants;")
    op.execute("""
        DELETE FROM security.world_memberships wm
        USING security.world_roles wr
        WHERE wr.world_role_id = wm.world_role_id
          AND wr.code IN ('world_editor', 'world_reviewer', 'world_reader');
    """)
    # The old index allowed one open row per (world, user): close a viewer row that now sits
    # beside an open owner row of the same user (kept as history, never deleted).
    op.execute("""
        UPDATE security.world_memberships v
        SET ended_at = now()
        FROM security.world_roles vr
        WHERE vr.world_role_id = v.world_role_id AND vr.code = 'world_viewer'
          AND v.ended_at IS NULL
          AND EXISTS (
              SELECT 1 FROM security.world_memberships o
              JOIN security.world_roles orr ON orr.world_role_id = o.world_role_id
              WHERE o.world_id = v.world_id AND o.user_id = v.user_id
                AND o.ended_at IS NULL AND orr.code = 'world_owner'
          );
    """)
    op.execute("DROP INDEX security.ux_world_memberships_open;")
    op.execute("""
        CREATE UNIQUE INDEX ux_world_memberships_open
        ON security.world_memberships (world_id, user_id)
        WHERE ended_at IS NULL;
    """)
    op.execute("DROP INDEX security.ix_world_memberships_ended_by_user_id;")
    op.execute("DROP INDEX security.ix_world_memberships_granted_by_user_id;")
    op.execute("""
        ALTER TABLE security.world_memberships
            DROP COLUMN ended_by_user_id,
            DROP COLUMN granted_by_user_id;
    """)
    op.execute("DROP TRIGGER tr_world_roles_enforce_protected_codes ON security.world_roles;")
    op.execute("""
        DELETE FROM security.world_roles
        WHERE code IN ('world_editor', 'world_reviewer', 'world_reader');
    """)
    op.execute("""
        COMMENT ON TABLE security.world_roles IS
        'Roles a user can hold on a world (world_owner, world_viewer). Capabilities are a '
        'closed mapping in application code (dnd_ai.domain.world_authority), not rows in '
        'security.capabilities, which is assignable to campaign roles '
        '(docs/adr/0014-world-authoring-authority.md, '
        'docs/adr/0019-world-visibility-and-viewer-role.md).';
    """)
