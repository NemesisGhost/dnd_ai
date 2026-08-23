"""Pin campaigns to a ruleset version, not a ruleset family

Revision ID: 024_campaign_ruleset_version
Revises: 023_session_world_time_period
Create Date: 2026-08-02 18:30:00.000000

Purpose:
    Corrective revision (Phase 4 corrections review). campaign.campaigns.ruleset_id
    (revision 016) pinned a campaign to a ruleset *family* (rules.rulesets),
    while character.character_builds.ruleset_version_id (revision 020) pins a
    build to a specific *version* of that family. A campaign whose ruleset
    family has more than one version — exactly what rules.ruleset_versions
    exists to support — could not say which version it was actually played
    with, which breaks reproducibility: replaying or auditing a campaign
    needs a fixed rules configuration, not "whichever version happens to be
    current.rgnow."

    This revision replaces campaign.campaigns.ruleset_id with ruleset_version_id,
    referencing rules.ruleset_versions directly. The world-allowance check
    still operates at the ruleset-family level (a world allows a *ruleset*,
    per rules.world_rulesets — not a specific version), so
    campaign.enforce_campaign_ruleset_allowed() now resolves the campaign's
    ruleset family from its pinned version before checking world_rulesets.

    Also resolves the seed-naming ambiguity this drift exposed: revision 022
    seeded a ruleset coded "dnd5e_2024" with a *version* labeled "2024" —
    embedding the same edition year in both the family code and the version
    label modeled the real distinction (D&D 5e has a 2014 and a 2024 edition)
    twice, ambiguously. Revision 022 itself is not touched (forward-only;
    already applied) — this revision renames the existing seeded ruleset's
    code from "dnd5e_2024" to the edition-neutral "dnd5e" by UPDATE, leaving
    version_label "2024" as the one place the edition distinction lives.

Forward migration:
    - campaign.campaigns.ruleset_id -> ruleset_version_id (FK to
      rules.ruleset_versions), via ADD/backfill/DROP since there are no
      campaign rows outside test fixtures to actually migrate
    - campaign.enforce_campaign_ruleset_allowed() updated to resolve the
      ruleset family from the pinned version
    - rules.rulesets: code 'dnd5e_2024' -> 'dnd5e' (data-only UPDATE)

Rollback:
    Supported. Restores ruleset_id (resolved back from whatever version was
    pinned), restores the ruleset code, and reverts the trigger function.

Data implications:
    No campaign rows exist outside test fixtures (which roll back), so the
    column swap has nothing to backfill in practice; the seed-code rename
    does update the one row revision 022 inserted.

Locking considerations:
    ADD COLUMN ... NULL is metadata-only; the following DROP COLUMN on a
    near-empty table is not a concern at this data volume.

See: docs/DATABASE_CONVENTIONS.md §25.4 (seed idempotency), §16 (provenance)
     database/migrations/versions/016_close_ruleset_references.py
     database/migrations/versions/020_character_builds.py
     database/migrations/versions/022_seed_initial_ruleset.py
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "024_campaign_ruleset_version"
down_revision = "023_session_world_time_period"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    # ==========================================================================
    # 1. campaign.campaigns.ruleset_id -> ruleset_version_id
    # ==========================================================================
    op.execute("""
        ALTER TABLE campaign.campaigns
        ADD COLUMN ruleset_version_id UUID
        REFERENCES rules.ruleset_versions(ruleset_version_id) ON DELETE RESTRICT;
    """)
    # No rows to backfill in a real deployment (campaigns is empty outside test
    # fixtures, which roll back), but if any exist, pin each to its ruleset's
    # current version rather than leave it unresolved.
    op.execute("""
        UPDATE campaign.campaigns c
        SET ruleset_version_id = (
            SELECT rv.ruleset_version_id FROM rules.ruleset_versions rv
            WHERE rv.ruleset_id = c.ruleset_id AND rv.is_current
            LIMIT 1
        )
        WHERE c.ruleset_version_id IS NULL;
    """)
    op.execute("ALTER TABLE campaign.campaigns ALTER COLUMN ruleset_version_id SET NOT NULL;")
    op.execute("""
        COMMENT ON COLUMN campaign.campaigns.ruleset_version_id IS
        'The exact ruleset version this campaign is played with — pinned, not just the '
        'ruleset family, so the campaign''s rules configuration is reproducible. Must '
        'belong to a ruleset allowed for the campaign''s world (rules.world_rulesets) — '
        'enforced by trigger.';
    """)
    op.execute(
        "CREATE INDEX ix_campaigns_ruleset_version_id ON campaign.campaigns (ruleset_version_id);"
    )

    op.execute("DROP TRIGGER IF EXISTS tr_campaigns_enforce_ruleset_allowed ON campaign.campaigns;")
    op.execute("""
        CREATE OR REPLACE FUNCTION campaign.enforce_campaign_ruleset_allowed()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_world_id   UUID;
            v_ruleset_id UUID;
            v_allowed    BOOLEAN;
        BEGIN
            SELECT world_id INTO v_world_id
            FROM campaign.timelines WHERE timeline_id = NEW.timeline_id;

            SELECT ruleset_id INTO v_ruleset_id
            FROM rules.ruleset_versions WHERE ruleset_version_id = NEW.ruleset_version_id;

            SELECT EXISTS (
                SELECT 1 FROM rules.world_rulesets
                WHERE world_id = v_world_id AND ruleset_id = v_ruleset_id
            ) INTO v_allowed;

            IF NOT v_allowed THEN
                RAISE EXCEPTION
                    'Ruleset version % (ruleset %) is not allowed for world % (campaign '
                    '%''s world, via its timeline)',
                    NEW.ruleset_version_id, v_ruleset_id, v_world_id, NEW.campaign_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION campaign.enforce_campaign_ruleset_allowed() IS
        'Keeps a campaign''s pinned ruleset version''s ruleset family one of the rulesets '
        'its world allows.';
    """)
    op.execute("""
        CREATE TRIGGER tr_campaigns_enforce_ruleset_allowed
        BEFORE INSERT OR UPDATE ON campaign.campaigns
        FOR EACH ROW EXECUTE FUNCTION campaign.enforce_campaign_ruleset_allowed();
    """)

    op.execute("ALTER TABLE campaign.campaigns DROP COLUMN ruleset_id;")

    # ==========================================================================
    # 2. Disambiguate the seeded ruleset's code from its version label
    # ==========================================================================
    op.execute("""
        UPDATE rules.rulesets SET code = 'dnd5e'
        WHERE code = 'dnd5e_2024';
    """)


def downgrade() -> None:
    """Revert the migration."""

    op.execute("""
        UPDATE rules.rulesets SET code = 'dnd5e_2024'
        WHERE code = 'dnd5e';
    """)

    op.execute("""
        ALTER TABLE campaign.campaigns
        ADD COLUMN ruleset_id UUID
        REFERENCES rules.rulesets(ruleset_id) ON DELETE RESTRICT;
    """)
    op.execute("""
        UPDATE campaign.campaigns c
        SET ruleset_id = (
            SELECT rv.ruleset_id FROM rules.ruleset_versions rv
            WHERE rv.ruleset_version_id = c.ruleset_version_id
        )
        WHERE c.ruleset_id IS NULL;
    """)
    # The UPDATE above fires tr_campaigns_retain_access_manager (added by
    # revision 080, DEFERRABLE INITIALLY DEFERRED) for any matched rows.
    # Drain those queued firings now so that the ALTER TABLE statement that
    # follows does not fail with "cannot ALTER TABLE because it has pending
    # trigger events" — the same fix applied in revisions 085 and 086 for
    # the identical problem on security.role_capabilities. Unlike 085/086
    # (both > 080, so their downgrade always runs before 080's own
    # downgrade removes the trigger), revision 024 is < 080: in a real
    # sequential `alembic downgrade base`, 080's downgrade already dropped
    # this trigger by the time 024's downgrade runs, so SET CONSTRAINTS
    # would fail with "constraint ... does not exist". Guard on the
    # trigger's actual presence so this is correct both there and when a
    # HEAD-migrated connection invokes 024's downgrade() directly (the
    # trigger still exists then — see tests/database/test_seed_idempotency.py).
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_trigger t
                JOIN pg_class c ON c.oid = t.tgrelid
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'campaign'
                  AND c.relname = 'campaigns'
                  AND t.tgname = 'tr_campaigns_retain_access_manager'
            ) THEN
                EXECUTE 'SET CONSTRAINTS campaign.tr_campaigns_retain_access_manager IMMEDIATE';
            END IF;
        END;
        $$;
    """)
    op.execute("ALTER TABLE campaign.campaigns ALTER COLUMN ruleset_id SET NOT NULL;")
    op.execute("CREATE INDEX ix_campaigns_ruleset_id ON campaign.campaigns (ruleset_id);")

    op.execute("DROP TRIGGER IF EXISTS tr_campaigns_enforce_ruleset_allowed ON campaign.campaigns;")
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

    op.execute("DROP INDEX IF EXISTS campaign.ix_campaigns_ruleset_version_id;")
    op.execute("ALTER TABLE campaign.campaigns DROP COLUMN ruleset_version_id;")
