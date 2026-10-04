"""Add per-world authoring authority (security.world_roles, security.world_memberships)

Revision ID: 110_world_authoring_authority
Revises: 109_user_portal_preferences
Create Date: 2026-10-03 12:00:00.000000

Purpose:
    Phase 14 (docs/adr/0014-world-authoring-authority.md). Before this revision
    nothing answered "who may edit this world, add a timeline to it, or start a
    campaign on it": authority existed only inside campaigns. This adds the
    smallest explicit concept -- a per-world membership -- without touching
    `core.worlds` (no new NOT NULL column, so the ~390 factory call sites and
    every populated-upgrade test keep working).

Forward migration:
    `security.world_roles` -- a standard lookup (conventions §11), seeded with
    `world_owner` via apply_seed (`database/seeds/security.world_roles.yaml`).
    The role's *capabilities* are a closed mapping in application code
    (`dnd_ai.domain.world_authority`), deliberately not rows in
    `security.capabilities`, which is assignable to campaign roles.

    `security.world_memberships` -- shaped like `security.campaign_memberships`:
      - open/closed rows that are never deleted by commands;
      - partial unique index "one open row per (world, user)";
      - `world_id` and `user_id` immutable (`core.enforce_immutable_columns`);
      - `ended_at >= joined_at`;
      - a DEFERRABLE INITIALLY DEFERRED constraint trigger that rejects a commit
        leaving a world that had an active owner with none
        (`security.assert_world_retains_owner`). It locks the world row FOR
        UPDATE first, exactly like `security.assert_campaign_retains_access_
        manager`, so two transactions each removing a *different* owner cannot
        both commit. Worlds that never had a membership row (legacy, unclaimed
        worlds) are unaffected.

Rollback:
    Supported but destructive: drops both tables and the guard functions, which
    discards every world ownership row. The deferred constraint trigger is dropped
    together with its table, so no `SET CONSTRAINTS` step is needed.

Data implications:
    No backfill. Existing worlds stay unowned (and therefore un-authorable)
    until an operator runs `scripts/claim_world_ownership.py`.

Locking considerations:
    New tables only. Adding foreign keys briefly takes SHARE ROW EXCLUSIVE on
    `core.worlds` and `security.users`.

See: docs/adr/0014-world-authoring-authority.md
     docs/architecture/DATABASE_MODEL.md (security.world_memberships)
     src/dnd_ai/persistence/tables/security.py (the matching declared tables)
"""

from alembic import op

from dnd_ai.persistence.seeds import apply_seed

# revision identifiers, used by Alembic.
revision = "110_world_authoring_authority"
down_revision = "109_user_portal_preferences"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""
    op.execute("""
        CREATE TABLE security.world_roles (
            world_role_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            code           TEXT NOT NULL,
            display_name   TEXT NOT NULL,
            description    TEXT,
            sort_order     core.nonnegative_integer NOT NULL DEFAULT 0,
            is_active      BOOLEAN NOT NULL DEFAULT true,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ux_world_roles_code UNIQUE (code),
            CONSTRAINT ck_world_roles_code_length CHECK (char_length(code) <= 100),
            CONSTRAINT ck_world_roles_code_format CHECK (code ~ '^[a-z][a-z0-9_]*$')
        );
    """)
    op.execute("""
        COMMENT ON TABLE security.world_roles IS
        'Roles a user can hold on a world (currently world_owner). Capabilities are a '
        'closed mapping in application code (dnd_ai.domain.world_authority), not rows in '
        'security.capabilities, which is assignable to campaign roles '
        '(docs/adr/0014-world-authoring-authority.md).';
    """)
    op.execute("""
        COMMENT ON COLUMN security.world_roles.code IS
        'Stable machine-readable identifier. Application logic may reference '
        'codes, but foreign keys use IDs (conventions §11.1).';
    """)
    op.execute("""
        CREATE TRIGGER tr_world_roles_set_updated_at
        BEFORE UPDATE ON security.world_roles
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    apply_seed(op, "security", "world_roles")

    op.execute("""
        CREATE TABLE security.world_memberships (
            world_membership_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            world_id             UUID NOT NULL
                                  REFERENCES core.worlds(world_id) ON DELETE CASCADE,
            user_id              UUID NOT NULL
                                  REFERENCES security.users(user_id) ON DELETE RESTRICT,
            world_role_id        UUID NOT NULL
                                  REFERENCES security.world_roles(world_role_id)
                                  ON DELETE RESTRICT,
            membership_status_id UUID NOT NULL
                                  REFERENCES security.membership_statuses(membership_status_id)
                                  ON DELETE RESTRICT,
            joined_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
            ended_at             TIMESTAMPTZ,
            created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_world_memberships_ended_after_joined CHECK (
                ended_at IS NULL OR ended_at >= joined_at
            )
        );
    """)
    op.execute("""
        COMMENT ON TABLE security.world_memberships IS
        'A user''s authority over a world (docs/adr/0014-world-authoring-authority.md): '
        'the root of world-level authoring authorization, separate from campaign '
        'membership and from platform administration. Open rows (ended_at IS NULL) with '
        'an active status and role authorize; closed rows are history and are never '
        'deleted by commands. A world with no rows at all is an unclaimed legacy world '
        'that nobody may author until trusted infrastructure claims it.';
    """)
    op.execute(
        "CREATE INDEX ix_world_memberships_world_id ON security.world_memberships (world_id);"
    )
    op.execute("CREATE INDEX ix_world_memberships_user_id ON security.world_memberships (user_id);")
    op.execute(
        "CREATE INDEX ix_world_memberships_world_role_id "
        "ON security.world_memberships (world_role_id);"
    )
    op.execute(
        "CREATE INDEX ix_world_memberships_membership_status_id "
        "ON security.world_memberships (membership_status_id);"
    )
    op.execute("""
        CREATE UNIQUE INDEX ux_world_memberships_open
        ON security.world_memberships (world_id, user_id)
        WHERE ended_at IS NULL;
    """)
    op.execute("""
        CREATE TRIGGER tr_world_memberships_set_updated_at
        BEFORE UPDATE ON security.world_memberships
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute("""
        CREATE TRIGGER tr_world_memberships_enforce_immutable
        BEFORE UPDATE ON security.world_memberships
        FOR EACH ROW EXECUTE FUNCTION core.enforce_immutable_columns('world_id', 'user_id');
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION security.world_has_active_owner(p_world_id UUID)
        RETURNS boolean
        LANGUAGE sql
        STABLE
        AS $$
            SELECT EXISTS (
                SELECT 1
                FROM security.world_memberships wm
                JOIN security.membership_statuses ms
                    ON ms.membership_status_id = wm.membership_status_id
                JOIN security.world_roles wr ON wr.world_role_id = wm.world_role_id
                WHERE wm.world_id = p_world_id
                  AND wm.ended_at IS NULL
                  AND ms.code = 'active'
                  AND ms.is_active
                  AND wr.code = 'world_owner'
                  AND wr.is_active
            );
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION security.world_has_active_owner(UUID) IS
        'Whether the world currently has at least one open, active world_owner '
        'membership. Pure read; callers needing enforcement use '
        'security.assert_world_retains_owner(). Does not consult the owner''s account '
        'state -- that is an application-layer check made on every request.';
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION security.assert_world_retains_owner(p_world_id UUID)
        RETURNS void
        LANGUAGE plpgsql
        AS $$
        BEGIN
            -- Serializes concurrent removals of different owners of the same
            -- world against each other (the same discipline as
            -- security.assert_campaign_retains_access_manager()).
            PERFORM 1 FROM core.worlds WHERE world_id = p_world_id FOR UPDATE;
            IF NOT FOUND THEN
                -- The world itself is gone (cascade); nothing left to protect.
                RETURN;
            END IF;

            IF NOT security.world_has_active_owner(p_world_id) THEN
                RAISE EXCEPTION
                    'World % would be left with no active world_owner membership',
                    p_world_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION security.assert_world_retains_owner(UUID) IS
        'Locks core.worlds for p_world_id (FOR UPDATE), then raises unless the world has '
        'an active world_owner membership. Called only from the DEFERRABLE INITIALLY '
        'DEFERRED constraint trigger on security.world_memberships, so it evaluates the '
        'final state of the transaction.';
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION security.enforce_world_memberships_retain_owner()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_was_active_owner  BOOLEAN;
        BEGIN
            -- Only a row that counted as an active owner before this statement can
            -- take the last owner away. Legacy unowned worlds have no such row.
            SELECT (OLD.ended_at IS NULL AND ms.code = 'active' AND ms.is_active
                    AND wr.code = 'world_owner' AND wr.is_active)
            INTO v_was_active_owner
            FROM security.membership_statuses ms, security.world_roles wr
            WHERE ms.membership_status_id = OLD.membership_status_id
              AND wr.world_role_id = OLD.world_role_id;

            IF COALESCE(v_was_active_owner, false) THEN
                PERFORM security.assert_world_retains_owner(OLD.world_id);
            END IF;

            RETURN NULL;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION security.enforce_world_memberships_retain_owner() IS
        'Deferred guard: closing, suspending, re-roling, or deleting the last active '
        'world_owner membership of a world fails at commit. A database backstop for '
        'direct SQL; Phase 14 has no member-removal command.';
    """)
    op.execute("""
        CREATE CONSTRAINT TRIGGER tr_world_memberships_retain_owner
        AFTER UPDATE OR DELETE ON security.world_memberships
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION security.enforce_world_memberships_retain_owner();
    """)


def downgrade() -> None:
    """Revert the migration."""
    # Dropping the table drops its constraint trigger with it.
    op.execute("DROP TABLE IF EXISTS security.world_memberships;")
    op.execute("DROP FUNCTION IF EXISTS security.enforce_world_memberships_retain_owner();")
    op.execute("DROP FUNCTION IF EXISTS security.assert_world_retains_owner(UUID);")
    op.execute("DROP FUNCTION IF EXISTS security.world_has_active_owner(UUID);")
    op.execute("DROP TABLE IF EXISTS security.world_roles;")
