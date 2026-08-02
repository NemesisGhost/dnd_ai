"""Single source of truth for a world's default ruleset

Revision ID: 027_world_ruleset_default
Revises: 026_ruleset_version_checks
Create Date: 2026-08-02 20:00:00.000000

Purpose:
    Corrective revision (Phase 4 corrections review). Revision 016 gave a
    world's default ruleset two independent representations that could
    disagree: rules.world_rulesets.is_default (a partial-unique-per-world
    flag) and core.worlds.default_ruleset_id (a direct FK, trigger-checked
    only to be one of the world's allowed rulesets — not checked against
    is_default at all). Nothing kept the two in sync: setting
    default_ruleset_id never touched is_default, and vice versa.

    core.worlds.default_ruleset_id becomes the sole source of truth.
    rules.world_rulesets.is_default is dropped along with its partial unique
    index — the "allowed ruleset" association table goes back to being a
    pure allow-list, per its own original description in
    docs/architecture/DATABASE_MODEL.md §8 ("associates a world with one or
    more allowed rulesets and identifies its default"); the *identifies its
    default* half of that now lives exclusively on core.worlds.

    This revision also closes a second gap the same drift exposed: nothing
    stopped DELETE FROM rules.world_rulesets from removing a world's current
    default (or a ruleset a campaign is actively pinned to), leaving
    core.worlds.default_ruleset_id or campaign.campaigns.ruleset_version_id
    dangling in spirit even though the FK itself doesn't fire (dangling
    world_rulesets *membership*, not a dangling row). A BEFORE DELETE OR
    UPDATE OF (world_id, ruleset_id) trigger now rejects removing an
    association still relied on either way.

Forward migration:
    - Drop rules.world_rulesets.is_default and its partial unique index
    - rules.enforce_world_ruleset_still_in_use(), a BEFORE DELETE OR UPDATE
      trigger on rules.world_rulesets

Rollback:
    Supported. Restores is_default (defaulted from whether the row currently
    matches its world's default_ruleset_id) and the partial unique index;
    drops the new protection trigger.

Data implications:
    Backfills is_default on downgrade only, from core.worlds.default_ruleset_id
    (which was already the more-trusted value in practice, per the module
    docstring).

Locking considerations:
    rules.world_rulesets holds at most a handful of rows per world in
    practice; dropping a column and adding a trigger are both cheap here.

See: docs/architecture/DATABASE_MODEL.md §8 (rules model)
     database/migrations/versions/016_close_ruleset_references.py
     database/migrations/versions/024_campaign_ruleset_version.py
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "027_world_ruleset_default"
down_revision = "026_ruleset_version_checks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    op.execute("DROP INDEX IF EXISTS rules.ux_world_rulesets_one_default_per_world;")
    op.execute("ALTER TABLE rules.world_rulesets DROP COLUMN IF EXISTS is_default;")
    op.execute("""
        COMMENT ON TABLE rules.world_rulesets IS
        'Associates a world with the rulesets it allows. A world may allow more than one '
        'ruleset; its default is core.worlds.default_ruleset_id alone (not represented '
        'here — see the reconciliation note in revision 027).';
    """)

    # A world's default and a campaign's pinned ruleset version both depend on
    # a world_rulesets row continuing to exist; removing (or repointing) one
    # out from under either must be rejected rather than silently orphaning
    # the dependent reference in spirit.
    op.execute("""
        CREATE OR REPLACE FUNCTION rules.enforce_world_ruleset_still_in_use()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_is_default    BOOLEAN;
            v_campaign_uses BOOLEAN;
        BEGIN
            SELECT EXISTS (
                SELECT 1 FROM core.worlds
                WHERE world_id = OLD.world_id AND default_ruleset_id = OLD.ruleset_id
            ) INTO v_is_default;

            IF v_is_default THEN
                RAISE EXCEPTION
                    'Ruleset % cannot be removed from world %''s allowed rulesets: it is '
                    'that world''s default (change the world''s default_ruleset_id first)',
                    OLD.ruleset_id, OLD.world_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            SELECT EXISTS (
                SELECT 1 FROM campaign.campaigns c
                JOIN campaign.timelines t ON t.timeline_id = c.timeline_id
                JOIN rules.ruleset_versions rv ON rv.ruleset_version_id = c.ruleset_version_id
                WHERE t.world_id = OLD.world_id AND rv.ruleset_id = OLD.ruleset_id
            ) INTO v_campaign_uses;

            IF v_campaign_uses THEN
                RAISE EXCEPTION
                    'Ruleset % cannot be removed from world %''s allowed rulesets: at '
                    'least one campaign in that world is still pinned to a version of it',
                    OLD.ruleset_id, OLD.world_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN OLD;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION rules.enforce_world_ruleset_still_in_use() IS
        'Rejects removing (or repointing) a world_rulesets association while the world''s '
        'default_ruleset_id or a campaign in that world still depends on it.';
    """)
    op.execute("""
        CREATE TRIGGER tr_world_rulesets_enforce_still_in_use
        BEFORE DELETE OR UPDATE OF world_id, ruleset_id ON rules.world_rulesets
        FOR EACH ROW EXECUTE FUNCTION rules.enforce_world_ruleset_still_in_use();
    """)


def downgrade() -> None:
    """Revert the migration."""

    op.execute(
        "DROP TRIGGER IF EXISTS tr_world_rulesets_enforce_still_in_use ON rules.world_rulesets;"
    )
    op.execute("DROP FUNCTION IF EXISTS rules.enforce_world_ruleset_still_in_use();")

    op.execute(
        "ALTER TABLE rules.world_rulesets ADD COLUMN is_default BOOLEAN NOT NULL DEFAULT FALSE;"
    )
    op.execute("""
        UPDATE rules.world_rulesets wr SET is_default = TRUE
        FROM core.worlds w
        WHERE w.world_id = wr.world_id AND w.default_ruleset_id = wr.ruleset_id;
    """)
    op.execute("""
        CREATE UNIQUE INDEX ux_world_rulesets_one_default_per_world
        ON rules.world_rulesets (world_id)
        WHERE is_default;
    """)
    op.execute("""
        COMMENT ON TABLE rules.world_rulesets IS
        'Associates a world with the rulesets it allows and identifies its default. '
        'A world may allow more than one ruleset; at most one is default.';
    """)
