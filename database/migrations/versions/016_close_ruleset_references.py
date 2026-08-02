"""Close the ruleset forward references

Revision ID: 016_close_ruleset_refs
Revises: 015_ruleset_classes
Create Date: 2026-08-02 14:30:00.000000

Purpose:
    Closes the two forward references deferred until rules.rulesets existed:
    core.worlds.default_ruleset_id (deferred in Phase 2) and
    campaign.campaigns.ruleset_id (deferred in Phase 3). Also delivers
    rules.world_rulesets, which associates a world with the rulesets it
    allows and identifies its default (docs/architecture/DATABASE_MODEL.md
    §8) — the mechanism both deferred columns actually depend on.

Forward migration:
    - rules.world_rulesets
    - core.worlds.default_ruleset_id, with a trigger keeping it in agreement
      with rules.world_rulesets
    - campaign.campaigns.ruleset_id, with a trigger requiring the ruleset be
      allowed for the campaign's world

Rollback:
    Supported. Drops both columns and rules.world_rulesets.

Data implications:
    No existing rows to migrate — no world or campaign has been created yet
    outside test fixtures, which roll back.

Locking considerations:
    ADD COLUMN ... NULL is metadata-only; campaigns.ruleset_id is added NULL
    first and only then set NOT NULL, so it never requires a table rewrite to
    validate existing rows (there are none, but the pattern holds regardless).

See: docs/PLAN.md Phase 4 first-time obligations (close the ruleset forward
     references)
     docs/architecture/DATABASE_MODEL.md §5.1, §6.2, §8
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "016_close_ruleset_refs"
down_revision = "015_ruleset_classes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    # ==========================================================================
    # 1. rules.world_rulesets
    # ==========================================================================
    op.execute("""
        CREATE TABLE rules.world_rulesets (
            world_id    UUID NOT NULL
                       REFERENCES core.worlds(world_id) ON DELETE CASCADE,
            ruleset_id  UUID NOT NULL
                       REFERENCES rules.rulesets(ruleset_id) ON DELETE RESTRICT,
            is_default  BOOLEAN NOT NULL DEFAULT FALSE,
            added_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (world_id, ruleset_id)
        );
    """)
    op.execute("""
        COMMENT ON TABLE rules.world_rulesets IS
        'Associates a world with the rulesets it allows and identifies its default. '
        'A world may allow more than one ruleset; at most one is default.';
    """)
    op.execute("CREATE INDEX ix_world_rulesets_ruleset_id ON rules.world_rulesets (ruleset_id);")
    op.execute("""
        CREATE UNIQUE INDEX ux_world_rulesets_one_default_per_world
        ON rules.world_rulesets (world_id)
        WHERE is_default;
    """)

    # ==========================================================================
    # 2. core.worlds.default_ruleset_id
    # ==========================================================================
    # Deferred from revision 004, which deliberately did not add this as an
    # unconstrained UUID before rules.rulesets existed.
    op.execute("""
        ALTER TABLE core.worlds
        ADD COLUMN default_ruleset_id UUID
        REFERENCES rules.rulesets(ruleset_id) ON DELETE SET NULL;
    """)
    op.execute("""
        COMMENT ON COLUMN core.worlds.default_ruleset_id IS
        'The ruleset to use when none is specified. Must be one of the rulesets the '
        'world allows (rules.world_rulesets) — enforced by trigger.';
    """)
    op.execute(
        "CREATE INDEX ix_worlds_default_ruleset_id ON core.worlds (default_ruleset_id) WHERE default_ruleset_id IS NOT NULL;"
    )

    op.execute("""
        CREATE OR REPLACE FUNCTION core.enforce_world_default_ruleset_allowed()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_allowed BOOLEAN;
        BEGIN
            IF NEW.default_ruleset_id IS NULL THEN
                RETURN NEW;
            END IF;

            SELECT EXISTS (
                SELECT 1 FROM rules.world_rulesets
                WHERE world_id = NEW.world_id AND ruleset_id = NEW.default_ruleset_id
            ) INTO v_allowed;

            IF NOT v_allowed THEN
                RAISE EXCEPTION
                    'Ruleset % is not an allowed ruleset for world % (add it to '
                    'rules.world_rulesets first)',
                    NEW.default_ruleset_id, NEW.world_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION core.enforce_world_default_ruleset_allowed() IS
        'Keeps core.worlds.default_ruleset_id one of the rulesets rules.world_rulesets '
        'says the world allows.';
    """)
    op.execute("""
        CREATE TRIGGER tr_worlds_enforce_default_ruleset_allowed
        BEFORE INSERT OR UPDATE ON core.worlds
        FOR EACH ROW EXECUTE FUNCTION core.enforce_world_default_ruleset_allowed();
    """)

    # ==========================================================================
    # 3. campaign.campaigns.ruleset_id
    # ==========================================================================
    # Deferred from revision 010, which deliberately did not add this as an
    # unconstrained UUID before rules.rulesets existed. NOT NULL: a campaign
    # is played with a definite ruleset, unlike a world's default, which may
    # legitimately be unset until an author chooses one.
    # No existing rows to satisfy: campaign.campaigns is empty outside test
    # fixtures, which roll back, so NOT NULL can be added directly rather than
    # nullable-then-backfill-then-tightened.
    op.execute("""
        ALTER TABLE campaign.campaigns
        ADD COLUMN ruleset_id UUID NOT NULL
        REFERENCES rules.rulesets(ruleset_id) ON DELETE RESTRICT;
    """)
    op.execute("""
        COMMENT ON COLUMN campaign.campaigns.ruleset_id IS
        'The ruleset this campaign is played with. Must be allowed for the campaign''s '
        'world (rules.world_rulesets) — enforced by trigger.';
    """)
    op.execute("CREATE INDEX ix_campaigns_ruleset_id ON campaign.campaigns (ruleset_id);")

    op.execute("""
        CREATE OR REPLACE FUNCTION campaign.enforce_campaign_ruleset_allowed()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_world_id UUID;
            v_allowed  BOOLEAN;
        BEGIN
            SELECT world_id INTO v_world_id
            FROM campaign.timelines WHERE timeline_id = NEW.timeline_id;

            SELECT EXISTS (
                SELECT 1 FROM rules.world_rulesets
                WHERE world_id = v_world_id AND ruleset_id = NEW.ruleset_id
            ) INTO v_allowed;

            IF NOT v_allowed THEN
                RAISE EXCEPTION
                    'Ruleset % is not an allowed ruleset for world % (campaign %''s world, '
                    'via its timeline)',
                    NEW.ruleset_id, v_world_id, NEW.campaign_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION campaign.enforce_campaign_ruleset_allowed() IS
        'Keeps a campaign''s ruleset one of the rulesets its world allows.';
    """)
    op.execute("""
        CREATE TRIGGER tr_campaigns_enforce_ruleset_allowed
        BEFORE INSERT OR UPDATE ON campaign.campaigns
        FOR EACH ROW EXECUTE FUNCTION campaign.enforce_campaign_ruleset_allowed();
    """)


def downgrade() -> None:
    """Revert the migration."""

    op.execute("DROP TRIGGER IF EXISTS tr_campaigns_enforce_ruleset_allowed ON campaign.campaigns;")
    op.execute("DROP FUNCTION IF EXISTS campaign.enforce_campaign_ruleset_allowed();")
    op.execute("ALTER TABLE campaign.campaigns DROP COLUMN IF EXISTS ruleset_id;")

    op.execute("DROP TRIGGER IF EXISTS tr_worlds_enforce_default_ruleset_allowed ON core.worlds;")
    op.execute("DROP FUNCTION IF EXISTS core.enforce_world_default_ruleset_allowed();")
    op.execute("ALTER TABLE core.worlds DROP COLUMN IF EXISTS default_ruleset_id;")

    op.execute("DROP TABLE IF EXISTS rules.world_rulesets;")
