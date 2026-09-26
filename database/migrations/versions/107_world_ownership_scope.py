"""World ownership scope: security.ownership_scopes, .ownership_scope_roles,
.ownership_scope_memberships, and core.worlds.ownership_scope_id.

Revision ID: 107_world_ownership_scope
Revises: 106_access_group_desc_length
Create Date: 2026-09-25 09:00:00.000000

Renumbered from 105 to 107 (originally created before merging main, which
independently added 105_access_group_status/106_access_group_desc_length
on the same 104 parent) — chained after both rather than adding a
separate alembic merge-heads revision, since this revision had not yet
been merged into main and could still be freely retargeted.

Purpose:
    `core.worlds` has never had an owner, creator, or administrator column
    — every world in this codebase is created by a migration, the dev-data
    script, or a test factory issuing a raw INSERT, and world slugs are
    unique globally (`ux_worlds_slug`). ADR 0014
    (docs/adr/0014-world-ownership-scope.md) introduces a neutral,
    non-billing ownership boundary before more schemas and features
    accumulate around `core.worlds`, so retrofitting it later is not
    strictly more expensive than adding it now. See that ADR and
    docs/architecture/DATABASE_MODEL.md §19.9 for the full design and the
    deliberate exclusions (no `create_world` command, no API/UI, no
    transfer command, no RLS, no billing) this revision does not build.

Forward migration:
    - security.ownership_scope_roles (§11 lookup shape, seeded via
      apply_seed(): owner, member)
    - security.ownership_scopes (first-class entity: name,
      lifecycle_status_id reusing core.lifecycle_statuses, timestamps — no
      "personal"/"organization" type column, see ADR 0014)
    - security.ownership_scope_memberships (shaped like
      security.campaign_memberships: user_id ON DELETE RESTRICT, reuses
      security.membership_statuses rather than a parallel status
      vocabulary, at most one open row per (ownership_scope_id, user_id))
    - One legacy security.ownership_scopes row, created with zero
      memberships (see "Existing-data migration" below)
    - core.worlds.ownership_scope_id UUID NOT NULL FK, added nullable,
      backfilled onto the legacy scope, then set NOT NULL
      (expand-and-contract, conventions §25.5 — safe against a populated
      table because the backfill target is unconditional)
    - core.worlds' old global ux_worlds_slug replaced by
      ux_worlds_ownership_scope_id_slug on (ownership_scope_id, slug)

Existing-data migration:
    A populated database cannot safely guess which human should own its
    pre-existing worlds (the earliest-created user is not necessarily the
    intended owner, and a database may have zero users at all). This
    revision creates one explicit legacy ownership scope
    ("Legacy Self-Hosted Worlds (unclaimed)") with **zero memberships**,
    backfills every existing core.worlds row onto it, and leaves it
    deliberately unowned. An operator must explicitly run
    `scripts/claim_legacy_ownership_scope.py` (calls
    `dnd_ai.commands.ownership.add_ownership_scope_member`) after
    upgrading to assign its first owner — documented in
    docs/LOCAL_DEPLOYMENT.md, never silently resolved here. A fresh
    database (the common case in CI and new installs) has zero worlds, so
    the backfill UPDATE is a no-op and the legacy scope is simply unused
    until the first world is ever created directly against it or a new
    scope is created for that world instead.

Rollback:
    Supported. Drops core.worlds.ownership_scope_id and its constraint/
    index (recreating the old global ux_worlds_slug — safe only because
    forward migration guarantees ownership_scope_id was NOT NULL, so no
    world can have acquired a slug colliding with another scope's while
    this revision was applied, other than through the same slug value
    already being globally unique before this revision ran), then drops
    the three new tables in dependency order.

Data implications:
    The ADD COLUMN + UPDATE + SET NOT NULL sequence rewrites core.worlds
    once per statement under an ACCESS EXCLUSIVE lock each time — cheap at
    this codebase's current data volumes (pre-launch, self-hosted), not
    a generally safe pattern at production scale without conventions
    §25.5's fuller expand/contract treatment (a background-batched
    backfill). No other table's data is rewritten.

Locking considerations:
    Every statement against core.worlds takes a brief ACCESS EXCLUSIVE
    lock; negligible at this codebase's current scale. Every other
    statement creates a new, empty object.

See: docs/adr/0014-world-ownership-scope.md
     docs/architecture/DATABASE_MODEL.md §19.9
     docs/DOMAIN_MODEL.md §4.1
     docs/DATABASE_CONVENTIONS.md §11 (lookup tables), §25.4 (seed data),
     §25.5 (backward compatibility / expand-contract)
     database/migrations/versions/080_security_identity_and_access.py
     (security.campaign_memberships — the membership shape this revision
     reuses)
"""

from alembic import op

from dnd_ai.persistence.seeds import apply_seed

# revision identifiers, used by Alembic.
revision = "107_world_ownership_scope"
down_revision = "106_access_group_desc_length"
branch_labels = None
depends_on = None

_LEGACY_OWNERSHIP_SCOPE_NAME = "Legacy Self-Hosted Worlds (unclaimed)"


def upgrade() -> None:
    """Apply the migration."""

    # ==========================================================================
    # 1. security.ownership_scope_roles (lookup)
    # ==========================================================================
    op.execute("""
        CREATE TABLE security.ownership_scope_roles (
            ownership_scope_role_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            code                         TEXT NOT NULL,
            display_name                   TEXT NOT NULL,
            description                       TEXT,
            sort_order                          core.nonnegative_integer NOT NULL DEFAULT 0,
            is_active                              BOOLEAN NOT NULL DEFAULT true,
            created_at                                TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at                                   TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ux_ownership_scope_roles_code UNIQUE (code),
            CONSTRAINT ck_ownership_scope_roles_code_format CHECK (code ~ '^[a-z][a-z0-9_]*$'),
            CONSTRAINT ck_ownership_scope_roles_code_length CHECK (char_length(code) <= 100)
        );
    """)
    op.execute("""
        COMMENT ON TABLE security.ownership_scope_roles IS
        'Role a security.ownership_scope_memberships row holds within its scope — '
        'owner, member (docs/architecture/DATABASE_MODEL.md §19.9). Deliberately not '
        'security.roles: that table''s roles are campaign-scoped or system templates '
        'for campaign authorization, an unrelated concern from world ownership '
        '(ADR 0014).';
    """)
    op.execute("""
        COMMENT ON COLUMN security.ownership_scope_roles.code IS
        'Stable machine-readable identifier. Application logic may reference '
        'codes, but foreign keys use IDs (conventions §11.1).';
    """)
    op.execute("""
        CREATE TRIGGER tr_ownership_scope_roles_set_updated_at
        BEFORE UPDATE ON security.ownership_scope_roles
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    apply_seed(op, "security", "ownership_scope_roles")

    # ==========================================================================
    # 2. security.ownership_scopes
    # ==========================================================================
    op.execute("""
        CREATE TABLE security.ownership_scopes (
            ownership_scope_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name                    TEXT NOT NULL,
            lifecycle_status_id        UUID NOT NULL
                                REFERENCES core.lifecycle_statuses(lifecycle_status_id)
                                ON DELETE RESTRICT,
            created_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at                       TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_ownership_scopes_name_length CHECK (char_length(name) BETWEEN 1 AND 200)
        );
    """)
    op.execute("""
        COMMENT ON TABLE security.ownership_scopes IS
        'A neutral, non-billing boundary grouping the humans who administer a set of '
        'worlds (ADR 0014). Every core.worlds row belongs to exactly one ownership '
        'scope. Not a billing tenant: no plan, quota, or entitlement column exists '
        'here, and none is implied by this table''s shape — a scope with one member '
        'behaves as a personal boundary today, and the same shape supports a shared '
        'organization later without a schema change. Distinct from a campaign: '
        'owning a world grants no campaign membership, role, or character-perspective '
        'knowledge by itself (docs/DOMAIN_MODEL.md §4.1).';
    """)
    op.execute(
        "CREATE INDEX ix_ownership_scopes_lifecycle_status_id "
        "ON security.ownership_scopes (lifecycle_status_id);"
    )
    op.execute("""
        CREATE TRIGGER tr_ownership_scopes_set_updated_at
        BEFORE UPDATE ON security.ownership_scopes
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)

    # ==========================================================================
    # 3. security.ownership_scope_memberships
    # ==========================================================================
    op.execute("""
        CREATE TABLE security.ownership_scope_memberships (
            ownership_scope_membership_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            ownership_scope_id                 UUID NOT NULL
                                    REFERENCES security.ownership_scopes(ownership_scope_id)
                                    ON DELETE CASCADE,
            user_id                               UUID NOT NULL
                                    REFERENCES security.users(user_id) ON DELETE RESTRICT,
            ownership_scope_role_id                 UUID NOT NULL
                                    REFERENCES security.ownership_scope_roles(
                                        ownership_scope_role_id
                                    ) ON DELETE RESTRICT,
            membership_status_id                       UUID NOT NULL
                                    REFERENCES security.membership_statuses(membership_status_id)
                                    ON DELETE RESTRICT,
            joined_at                                      TIMESTAMPTZ,
            ended_at                                          TIMESTAMPTZ,
            ended_by_membership_id                              UUID
                                    REFERENCES security.ownership_scope_memberships(
                                        ownership_scope_membership_id
                                    ) ON DELETE SET NULL,
            created_at                                             TIMESTAMPTZ NOT NULL
                                    DEFAULT now(),
            updated_at                                                TIMESTAMPTZ NOT NULL
                                    DEFAULT now(),
            CONSTRAINT ck_ownership_scope_memberships_ended_after_joined CHECK (
                ended_at IS NULL OR joined_at IS NULL OR ended_at > joined_at
            )
        );
    """)
    op.execute("""
        COMMENT ON TABLE security.ownership_scope_memberships IS
        'The many-to-many association between users and ownership scopes (ADR 0014), '
        'shaped like security.campaign_memberships: user_id is ON DELETE RESTRICT, '
        'not CASCADE — membership history must survive a user delete. '
        'Revoked/departed rows are closed (ended_at set), never deleted. Reuses '
        'security.membership_statuses rather than a parallel status vocabulary — its '
        'invited/active/suspended/revoked/departed codes apply unchanged to this '
        'membership shape.';
    """)
    op.execute("""
        CREATE TRIGGER tr_ownership_scope_memberships_set_updated_at
        BEFORE UPDATE ON security.ownership_scope_memberships
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute(
        "CREATE INDEX ix_ownership_scope_memberships_ownership_scope_id "
        "ON security.ownership_scope_memberships (ownership_scope_id);"
    )
    op.execute(
        "CREATE INDEX ix_ownership_scope_memberships_user_id "
        "ON security.ownership_scope_memberships (user_id);"
    )
    op.execute(
        "CREATE INDEX ix_ownership_scope_memberships_membership_status_id "
        "ON security.ownership_scope_memberships (membership_status_id);"
    )
    op.execute(
        "CREATE INDEX ix_ownership_scope_memberships_ownership_scope_role_id "
        "ON security.ownership_scope_memberships (ownership_scope_role_id);"
    )
    op.execute(
        "CREATE INDEX ix_ownership_scope_memberships_ended_by_membership_id "
        "ON security.ownership_scope_memberships (ended_by_membership_id) "
        "WHERE ended_by_membership_id IS NOT NULL;"
    )
    op.execute("""
        CREATE UNIQUE INDEX ux_ownership_scope_memberships_open
        ON security.ownership_scope_memberships (ownership_scope_id, user_id)
        WHERE ended_at IS NULL;
    """)

    # ==========================================================================
    # 4. Legacy ownership scope for pre-existing worlds — zero memberships,
    #    deliberately unowned. See this revision's "Existing-data migration".
    # ==========================================================================
    op.execute(f"""
        INSERT INTO security.ownership_scopes (name, lifecycle_status_id)
        SELECT '{_LEGACY_OWNERSHIP_SCOPE_NAME}', lifecycle_status_id
        FROM core.lifecycle_statuses WHERE code = 'active';
    """)
    # Deliberately no COMMENT ON TABLE change here — security.ownership_scopes'
    # persisted comment (set in section 2) must match
    # dnd_ai.persistence.tables.security.ownership_scopes' declared comment
    # exactly (`alembic check`'s metadata-parity contract); the legacy row's
    # own purpose is documented in this revision's module docstring instead.

    # ==========================================================================
    # 5. core.worlds.ownership_scope_id — expand, backfill, contract
    # ==========================================================================
    op.execute("""
        ALTER TABLE core.worlds
        ADD COLUMN ownership_scope_id UUID
            REFERENCES security.ownership_scopes(ownership_scope_id) ON DELETE RESTRICT;
    """)
    op.execute(f"""
        UPDATE core.worlds
        SET ownership_scope_id = (
            SELECT ownership_scope_id FROM security.ownership_scopes
            WHERE name = '{_LEGACY_OWNERSHIP_SCOPE_NAME}'
        )
        WHERE ownership_scope_id IS NULL;
    """)
    op.execute("ALTER TABLE core.worlds ALTER COLUMN ownership_scope_id SET NOT NULL;")
    op.execute("CREATE INDEX ix_worlds_ownership_scope_id ON core.worlds (ownership_scope_id);")
    op.execute("ALTER TABLE core.worlds DROP CONSTRAINT ux_worlds_slug;")
    op.execute("""
        ALTER TABLE core.worlds
        ADD CONSTRAINT ux_worlds_ownership_scope_id_slug UNIQUE (ownership_scope_id, slug);
    """)
    op.execute("""
        COMMENT ON COLUMN core.worlds.ownership_scope_id IS
        'The ownership scope administering this world (ADR 0014, '
        'docs/architecture/DATABASE_MODEL.md §19.9) — independent of campaign '
        'membership, campaign roles, and security.users.is_platform_administrator. '
        'ON DELETE RESTRICT: an ownership scope with worlds still attached cannot be '
        'removed.';
    """)
    op.execute("""
        COMMENT ON TABLE core.worlds IS
        'A persistent fictional setting. Owns entity definitions, calendars, and '
        'timelines; outlives any individual campaign. Slugs are unique within a '
        'world''s ownership scope, not globally (ADR 0014).';
    """)


def downgrade() -> None:
    """Revert the migration."""
    op.execute("ALTER TABLE core.worlds DROP CONSTRAINT ux_worlds_ownership_scope_id_slug;")
    op.execute("ALTER TABLE core.worlds ADD CONSTRAINT ux_worlds_slug UNIQUE (slug);")
    op.execute("""
        COMMENT ON TABLE core.worlds IS
        'A persistent fictional setting. Owns entity definitions, calendars, and '
        'timelines; outlives any individual campaign.';
    """)
    op.execute("DROP INDEX core.ix_worlds_ownership_scope_id;")
    op.execute("ALTER TABLE core.worlds DROP COLUMN ownership_scope_id;")

    op.execute("DROP TABLE security.ownership_scope_memberships;")
    op.execute("DROP TABLE security.ownership_scopes;")
    op.execute("DROP TABLE security.ownership_scope_roles;")
