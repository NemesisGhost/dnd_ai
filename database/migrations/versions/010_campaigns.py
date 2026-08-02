"""Campaigns and campaign-party association

Revision ID: 010_campaigns
Revises: 009_parties_memberships
Create Date: 2026-08-02 10:00:00.000000

Purpose:
    Delivers campaign.campaigns and campaign.campaign_parties (docs/PLAN.md
    §5.3, §5.4), completing the "two campaigns can share one timeline" and
    party-to-campaign association exit criteria for Phase 3.

    A campaign is played on exactly one timeline; several campaigns may share
    one, which is why timeline_id lives on campaign.campaigns rather than the
    other way around. A party is a stable world-level identity (revision 009)
    and campaign_parties is the join that says which campaigns use it —
    membership itself stays timeline-scoped in campaign.party_memberships and
    is not duplicated here.

Forward migration:
    - campaign.campaigns
    - campaign.campaign_parties, with a trigger enforcing that the party and
      the campaign (via its timeline) belong to the same world

Rollback:
    Supported. Drops both tables and the trigger function.

Data implications:
    Creates no rows.

Locking considerations:
    None. Both tables are new and empty.

Deferred to later phases:
    ruleset_id is part of the target model (docs/architecture/DATABASE_MODEL.md
    §6.2) but is omitted until rules.rulesets exists in Phase 4, following the
    precedent Phase 2 set with worlds.default_calendar_id: omit rather than add
    an unconstrained UUID.

See: docs/PLAN.md §5.3 (campaigns), §5.4 (parties), Phase 3 exit criteria
     docs/architecture/DATABASE_MODEL.md §6.2, §6.3
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "010_campaigns"
down_revision = "009_parties_memberships"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    # ==========================================================================
    # 1. campaign.campaigns
    # ==========================================================================
    # timeline_id ON DELETE RESTRICT: timelines are archived rather than
    # physically deleted in ordinary operation (rule 9), and a delete that did
    # happen should not silently cascade away a campaign's own history.
    op.execute("""
        CREATE TABLE campaign.campaigns (
            campaign_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            timeline_id           UUID NOT NULL
                                  REFERENCES campaign.timelines(timeline_id)
                                  ON DELETE RESTRICT,
            name                  TEXT NOT NULL,
            description           TEXT,
            lifecycle_status_id   UUID NOT NULL
                                  REFERENCES core.lifecycle_statuses(lifecycle_status_id)
                                  ON DELETE RESTRICT,
            started_at            TIMESTAMPTZ,
            ended_at              TIMESTAMPTZ,
            created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT ck_campaigns_name_length
                CHECK (char_length(name) BETWEEN 1 AND 200),

            -- An end without a start is not a real interval.
            CONSTRAINT ck_campaigns_ended_requires_started
                CHECK (ended_at IS NULL OR started_at IS NOT NULL),

            CONSTRAINT ck_campaigns_ended_after_started
                CHECK (ended_at IS NULL OR ended_at > started_at)
        );
    """)
    op.execute("""
        COMMENT ON TABLE campaign.campaigns IS
        'A single game''s run on a timeline. Several campaigns may share one timeline '
        '(docs/PLAN.md §5.3). Does not own world entities — it reaches them through '
        'participation, discovery, state, and event records.';
    """)
    op.execute("""
        COMMENT ON COLUMN campaign.campaigns.timeline_id IS
        'The timeline this campaign is played on. Not unique: two campaigns may share '
        'one timeline.';
    """)
    op.execute("""
        CREATE TRIGGER tr_campaigns_set_updated_at
        BEFORE UPDATE ON campaign.campaigns
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute("CREATE INDEX ix_campaigns_timeline_id ON campaign.campaigns (timeline_id);")
    op.execute(
        "CREATE INDEX ix_campaigns_lifecycle_status_id ON campaign.campaigns (lifecycle_status_id);"
    )

    # ==========================================================================
    # 2. campaign.campaign_parties
    # ==========================================================================
    # Pure association: which parties are used by which campaigns. No surrogate
    # key, matching the shape of core.entity_tags — the pair IS the identity,
    # and there is nothing else to key on.
    op.execute("""
        CREATE TABLE campaign.campaign_parties (
            campaign_id  UUID NOT NULL
                        REFERENCES campaign.campaigns(campaign_id) ON DELETE CASCADE,
            party_id     UUID NOT NULL
                        REFERENCES campaign.parties(party_id) ON DELETE CASCADE,
            added_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (campaign_id, party_id)
        );
    """)
    op.execute("""
        COMMENT ON TABLE campaign.campaign_parties IS
        'Associates a world-level party (campaign.parties) with the campaigns that use '
        'it. Membership itself is timeline-scoped state tracked separately in '
        'campaign.party_memberships — this table only says which campaigns a party '
        'participates in.';
    """)
    op.execute("CREATE INDEX ix_campaign_parties_party_id ON campaign.campaign_parties (party_id);")

    # A party and the campaigns that use it must agree on world. Same class of
    # guard as core.enforce_entity_tag_world and
    # campaign.enforce_party_membership's world checks: it compares across
    # rows and tables (a party's world_id against a campaign's world, reached
    # through its timeline), so it cannot be a CHECK.
    op.execute("""
        CREATE OR REPLACE FUNCTION campaign.enforce_campaign_party_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_campaign_world UUID;
            v_party_world    UUID;
        BEGIN
            SELECT t.world_id INTO v_campaign_world
            FROM campaign.campaigns c
            JOIN campaign.timelines t ON t.timeline_id = c.timeline_id
            WHERE c.campaign_id = NEW.campaign_id;

            SELECT world_id INTO v_party_world
            FROM campaign.parties WHERE party_id = NEW.party_id;

            IF v_party_world IS DISTINCT FROM v_campaign_world THEN
                RAISE EXCEPTION
                    'Party % belongs to world %, but campaign % belongs to world %',
                    NEW.party_id, v_party_world, NEW.campaign_id, v_campaign_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION campaign.enforce_campaign_party_world() IS
        'Keeps a campaign from using a party that belongs to a different world.';
    """)
    op.execute("""
        CREATE TRIGGER tr_campaign_parties_enforce_world
        BEFORE INSERT OR UPDATE ON campaign.campaign_parties
        FOR EACH ROW EXECUTE FUNCTION campaign.enforce_campaign_party_world();
    """)


def downgrade() -> None:
    """Revert the migration."""

    op.execute("DROP TABLE IF EXISTS campaign.campaign_parties;")
    op.execute("DROP FUNCTION IF EXISTS campaign.enforce_campaign_party_world();")
    op.execute("DROP TABLE IF EXISTS campaign.campaigns;")
