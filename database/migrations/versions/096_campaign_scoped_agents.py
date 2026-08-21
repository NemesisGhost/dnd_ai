"""ai.agent_assignments.entity_id becomes nullable — campaign-scoped agent
roles with no single in-world entity target.

Revision ID: 096_campaign_scoped_agents
Revises: 095_knowledge_event_target
Create Date: 2026-08-20 15:00:00.000000

Purpose:
    093_ai_domain's own docstring flagged this precisely: "`entity_id`
    NOT NULL — this phase's one wired role always names the NPC entity
    being portrayed; a future role with no natural entity target (a
    campaign-wide summarizer, say) will need its own migration to relax
    this." That future role is this same phase's second use case: the
    audience-aware synthesis service (`dnd_ai.commands.ai_synthesis`,
    `ai.agent_roles` code `session_summarizer`) answers a campaign-wide
    question (a GM brief, a player-character question, an observer
    summary) — there is no single `core.entities` row it is "about" the
    way `npc_portrayal` is about the NPC it portrays.

    An `ai.agent_assignments` row with `entity_id IS NULL` reads as "this
    agent operates for this whole campaign," not "for this specific
    entity" — `ai.enforce_agent_assignment_world()` already only checks
    world agreement when a real entity is named, so no application-visible
    behavior changes for the existing `npc_portrayal` role; only the
    column's own nullability and the trigger's guard against a NULL
    `entity_id` change.

Forward migration:
    - `ALTER TABLE ai.agent_assignments ALTER COLUMN entity_id DROP NOT NULL`
    - `ai.enforce_agent_assignment_world()` (CREATE OR REPLACE): skip the
      entity/world check when `NEW.entity_id IS NULL`

Rollback:
    Supported. Restores `entity_id NOT NULL` (fails if any row with a
    NULL `entity_id` was created since this migration ran — an inherent,
    accepted property of narrowing a column back down, the same as any
    other NOT-NULL-restoring downgrade in this project) and reverts the
    trigger function to its original form.

Data implications:
    None on upgrade. No existing row has a NULL `entity_id`.

Locking considerations:
    `DROP NOT NULL` is metadata-only on PostgreSQL — no table rewrite,
    no full-table scan. `CREATE OR REPLACE FUNCTION` does not lock the
    table it is later invoked against.

See: database/migrations/versions/093_ai_domain.py (this column's own
     origin and the "future role" note this migration closes)
     src/dnd_ai/commands/ai_synthesis.py (this migration's consumer)
     docs/PLAN.md Phase 12 (Narrow AI/NPC MVP)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "096_campaign_scoped_agents"
down_revision = "095_knowledge_event_target"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    op.execute("ALTER TABLE ai.agent_assignments ALTER COLUMN entity_id DROP NOT NULL;")

    op.execute("""
        CREATE OR REPLACE FUNCTION ai.enforce_agent_assignment_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_campaign_world  UUID;
            v_entity_world    UUID;
        BEGIN
            IF NEW.entity_id IS NULL THEN
                RETURN NEW;
            END IF;

            SELECT t.world_id INTO v_campaign_world
            FROM campaign.campaigns c
            JOIN campaign.timelines t ON t.timeline_id = c.timeline_id
            WHERE c.campaign_id = NEW.campaign_id;

            SELECT world_id INTO v_entity_world
            FROM core.entities WHERE entity_id = NEW.entity_id;

            IF v_entity_world IS DISTINCT FROM v_campaign_world THEN
                RAISE EXCEPTION
                    'Agent assignment % belongs to campaign % (world %), but entity % '
                    'belongs to world %',
                    NEW.agent_assignment_id, NEW.campaign_id, v_campaign_world, NEW.entity_id,
                    v_entity_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION ai.enforce_agent_assignment_world() IS
        'Same-world guard for ai.agent_assignments (conventions §9.5): the '
        'assigned entity, when one is named, must belong to the assigning '
        'campaign''s own world. A NULL entity_id (a campaign-scoped agent '
        'role with no single in-world target) skips this check entirely.';
    """)


def downgrade() -> None:
    """Revert the migration."""

    op.execute("""
        CREATE OR REPLACE FUNCTION ai.enforce_agent_assignment_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_campaign_world  UUID;
            v_entity_world    UUID;
        BEGIN
            SELECT t.world_id INTO v_campaign_world
            FROM campaign.campaigns c
            JOIN campaign.timelines t ON t.timeline_id = c.timeline_id
            WHERE c.campaign_id = NEW.campaign_id;

            SELECT world_id INTO v_entity_world
            FROM core.entities WHERE entity_id = NEW.entity_id;

            IF v_entity_world IS DISTINCT FROM v_campaign_world THEN
                RAISE EXCEPTION
                    'Agent assignment % belongs to campaign % (world %), but entity % '
                    'belongs to world %',
                    NEW.agent_assignment_id, NEW.campaign_id, v_campaign_world, NEW.entity_id,
                    v_entity_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION ai.enforce_agent_assignment_world() IS
        'Same-world guard for ai.agent_assignments (conventions §9.5): the '
        'assigned entity must belong to the assigning campaign''s own world.';
    """)

    op.execute("ALTER TABLE ai.agent_assignments ALTER COLUMN entity_id SET NOT NULL;")
