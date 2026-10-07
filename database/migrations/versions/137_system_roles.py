"""Add system-scope roles (security.system_roles, security.user_system_roles); retire is_platform_administrator

Revision ID: 137_system_roles
Revises: 136_world_viewer_role
Create Date: 2026-10-06 18:00:00.000000

Purpose:
    Scoped-role authorization, checkpoint SR-1
    (docs/SCOPED_ROLE_IMPLEMENTATION_PLAN.md,
    docs/adr/0020-scoped-system-world-and-campaign-roles.md). Platform authority was
    one boolean (`security.users.is_platform_administrator`) plus a derived "system GM"
    signal read off campaign role assignments, which let any campaign access manager
    mint platform-wide world creators. This revision introduces an explicit,
    independent system scope: four roles (admin, gm, player, observer) assigned per
    user, with capabilities a closed mapping in application code
    (`dnd_ai.domain.system_authority`).

Forward migration:
    1. `security.system_roles` -- a standard lookup (conventions §11) seeded through
       apply_seed. The four codes are protected from rename
       (`core.enforce_protected_lookup_codes`) because code-side capability mapping
       relies on them by name.
    2. `security.user_system_roles` -- one row per assignment; revoked rows are kept as
       history. At most one unrevoked row per (user, role). `user_id` and
       `system_role_id` are immutable.
    3. Backfill (the policy of plan §9.1, never promoting anyone on the basis of a
       campaign role):
         * every user with `is_platform_administrator = true` (any lifecycle status, so
           a later reactivation restores it) receives `admin` and `gm`;
         * every user with an open, active `world_owner` membership receives `gm`
           (they already passed a creation-eligibility check or an operator claim);
         * every user who received nothing above receives `player`.
       Backfilled rows have `granted_by_user_id IS NULL`.
    4. Drops `security.users.is_platform_administrator` and restates the one column
       comment that named it.

Rollback:
    Supported. Re-adds `is_platform_administrator`, repopulating it from unrevoked
    `admin` assignments, then drops both new tables. `gm`, `player` and `observer`
    assignments are discarded (the old model has no place for them).

Data implications:
    Existing holders of the campaign `gm` template are **not** given system `gm`
    unless they also fall under item 3. They keep every campaign role but lose world
    and campaign creation until an administrator assigns system GM.

Locking considerations:
    New tables only, plus one ALTER TABLE ... DROP COLUMN on `security.users`
    (brief ACCESS EXCLUSIVE lock; no rewrite).

See: docs/adr/0020-scoped-system-world-and-campaign-roles.md
     src/dnd_ai/persistence/tables/security.py (the matching declared tables)
"""

from alembic import op

from dnd_ai.persistence.seeds import apply_seed

# revision identifiers, used by Alembic.
revision = "137_system_roles"
down_revision = "136_world_viewer_role"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""
    op.execute("""
        CREATE TABLE security.system_roles (
            system_role_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            code            TEXT NOT NULL,
            display_name    TEXT NOT NULL,
            description     TEXT,
            sort_order      core.nonnegative_integer NOT NULL DEFAULT 0,
            is_active       BOOLEAN NOT NULL DEFAULT true,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ux_system_roles_code UNIQUE (code),
            CONSTRAINT ck_system_roles_code_length CHECK (char_length(code) <= 100),
            CONSTRAINT ck_system_roles_code_format CHECK (code ~ '^[a-z][a-z0-9_]*$')
        );
    """)
    op.execute("""
        COMMENT ON TABLE security.system_roles IS
        'Platform-level roles a user can hold: admin, gm, player, observer. Capabilities '
        'are a closed mapping in application code (dnd_ai.domain.system_authority), not '
        'rows in security.capabilities. Independent of world roles and campaign roles: '
        'no system role grants campaign or world access '
        '(docs/adr/0020-scoped-system-world-and-campaign-roles.md).';
    """)
    op.execute("""
        COMMENT ON COLUMN security.system_roles.code IS
        'Stable machine-readable identifier. Application logic may reference '
        'codes, but foreign keys use IDs (conventions §11.1).';
    """)
    op.execute("""
        CREATE TRIGGER tr_system_roles_set_updated_at
        BEFORE UPDATE ON security.system_roles
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute("""
        CREATE TRIGGER tr_system_roles_enforce_protected_codes
        BEFORE UPDATE ON security.system_roles
        FOR EACH ROW EXECUTE FUNCTION core.enforce_protected_lookup_codes(
            'admin', 'gm', 'player', 'observer'
        );
    """)
    apply_seed(op, "security", "system_roles")

    op.execute("""
        CREATE TABLE security.user_system_roles (
            user_system_role_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id              UUID NOT NULL
                                  REFERENCES security.users(user_id) ON DELETE RESTRICT,
            system_role_id       UUID NOT NULL
                                  REFERENCES security.system_roles(system_role_id)
                                  ON DELETE RESTRICT,
            granted_by_user_id   UUID
                                  REFERENCES security.users(user_id) ON DELETE RESTRICT,
            granted_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
            revoked_at           TIMESTAMPTZ,
            revoked_by_user_id   UUID
                                  REFERENCES security.users(user_id) ON DELETE RESTRICT,
            created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_user_system_roles_revoked_after_granted CHECK (
                revoked_at IS NULL OR revoked_at >= granted_at
            ),
            CONSTRAINT ck_user_system_roles_revoker_requires_revocation CHECK (
                revoked_by_user_id IS NULL OR revoked_at IS NOT NULL
            )
        );
    """)
    op.execute("""
        COMMENT ON TABLE security.user_system_roles IS
        'A user''s assignment of a system role. Open rows (revoked_at IS NULL) authorize '
        'while the account is active; revoked rows are history and are never deleted by '
        'commands. Never implies membership in any campaign or authority over any world.';
    """)
    op.execute(
        "COMMENT ON COLUMN security.user_system_roles.granted_by_user_id IS "
        "'The administrator who made the assignment; NULL for migration backfill, the "
        "initial-admin bootstrap and operator-script grants.';"
    )
    op.execute("CREATE INDEX ix_user_system_roles_user_id ON security.user_system_roles (user_id);")
    op.execute(
        "CREATE INDEX ix_user_system_roles_system_role_id "
        "ON security.user_system_roles (system_role_id);"
    )
    op.execute(
        "CREATE INDEX ix_user_system_roles_granted_by_user_id "
        "ON security.user_system_roles (granted_by_user_id) "
        "WHERE granted_by_user_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_user_system_roles_revoked_by_user_id "
        "ON security.user_system_roles (revoked_by_user_id) "
        "WHERE revoked_by_user_id IS NOT NULL;"
    )
    op.execute("""
        CREATE UNIQUE INDEX ux_user_system_roles_open
        ON security.user_system_roles (user_id, system_role_id)
        WHERE revoked_at IS NULL;
    """)
    op.execute("""
        CREATE TRIGGER tr_user_system_roles_set_updated_at
        BEFORE UPDATE ON security.user_system_roles
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute("""
        CREATE TRIGGER tr_user_system_roles_enforce_immutable
        BEFORE UPDATE ON security.user_system_roles
        FOR EACH ROW EXECUTE FUNCTION core.enforce_immutable_columns('user_id', 'system_role_id');
    """)

    # Backfill (plan §9.1): administrators -> admin + gm.
    op.execute("""
        INSERT INTO security.user_system_roles (user_id, system_role_id)
        SELECT u.user_id, sr.system_role_id
        FROM security.users u
        JOIN security.system_roles sr ON sr.code IN ('admin', 'gm')
        WHERE u.is_platform_administrator;
    """)
    # Open, active world owners -> gm (unless already granted above).
    op.execute("""
        INSERT INTO security.user_system_roles (user_id, system_role_id)
        SELECT DISTINCT wm.user_id, sr.system_role_id
        FROM security.world_memberships wm
        JOIN security.membership_statuses ms
          ON ms.membership_status_id = wm.membership_status_id
        JOIN security.world_roles wr ON wr.world_role_id = wm.world_role_id
        JOIN security.system_roles sr ON sr.code = 'gm'
        WHERE wm.ended_at IS NULL
          AND ms.code = 'active' AND ms.is_active
          AND wr.code = 'world_owner'
          AND NOT EXISTS (
              SELECT 1 FROM security.user_system_roles e
              WHERE e.user_id = wm.user_id AND e.system_role_id = sr.system_role_id
          );
    """)
    # Everyone left -> player.
    op.execute("""
        INSERT INTO security.user_system_roles (user_id, system_role_id)
        SELECT u.user_id, sr.system_role_id
        FROM security.users u
        JOIN security.system_roles sr ON sr.code = 'player'
        WHERE NOT EXISTS (
            SELECT 1 FROM security.user_system_roles e WHERE e.user_id = u.user_id
        );
    """)

    op.execute("ALTER TABLE security.users DROP COLUMN is_platform_administrator;")
    op.execute(
        "COMMENT ON COLUMN security.password_reset_tokens.requested_by_user_id IS "
        "'The platform administrator (system role admin) who issued this reset token.';"
    )


def downgrade() -> None:
    """Revert the migration."""
    op.execute("""
        ALTER TABLE security.users
            ADD COLUMN is_platform_administrator BOOLEAN NOT NULL DEFAULT false;
    """)
    op.execute("""
        COMMENT ON COLUMN security.users.is_platform_administrator IS
        'A minimal, campaign-independent authorization primitive (revision '
        '099_local_authentication) for account-management operations that have no '
        'campaign_id to scope a role check against.';
    """)
    op.execute("""
        UPDATE security.users u
        SET is_platform_administrator = true
        WHERE EXISTS (
            SELECT 1
            FROM security.user_system_roles usr
            JOIN security.system_roles sr ON sr.system_role_id = usr.system_role_id
            WHERE usr.user_id = u.user_id AND sr.code = 'admin' AND usr.revoked_at IS NULL
        );
    """)
    op.execute(
        "COMMENT ON COLUMN security.password_reset_tokens.requested_by_user_id IS "
        "'The administrator (is_platform_administrator) who issued this reset token.';"
    )
    op.execute("DROP TABLE IF EXISTS security.user_system_roles;")
    op.execute("DROP TABLE IF EXISTS security.system_roles;")
