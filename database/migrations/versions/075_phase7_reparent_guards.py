"""Phase 7 correction: immutable parent-scope identity columns for the
quest and knowledge domain

Revision ID: 075_phase7_reparent_guards
Revises: 074_phase7_correction_pass
Create Date: 2026-08-07 00:00:00.000000

Purpose:
    Deployable-integrity gap left open by the Phase 7 correction pass
    (revision 074): every same-world/same-scope trigger revision 073 built
    for the quest and knowledge domain validates on INSERT and UPDATE of the
    *child* row only, exactly the class of gap revision 030 already fixed
    once for core.world_times/core.entities/campaign.timelines/.parties/
    .campaigns. None of Phase 7's own guards re-run when a *parent* row's
    own scope identity changes out from under already-valid dependents:

    1. narrative.story_arcs.world_id can change after narrative.quests
       reference the arc (narrative.enforce_quest_story_arc_world() only
       fires on narrative.quests INSERT/UPDATE).
    2. narrative.quest_stages.quest_id can change after narrative.
       quest_objectives, narrative.objective_dependencies, campaign.
       objective_state, and narrative.event_effects reference the stage
       (transitively, through quest_objectives); narrative.quest_objectives.
       quest_stage_id can change after those same dependents reference the
       objective directly.
    3. narrative.quest_outcomes.quest_id can change after narrative.
       quest_rewards reference the outcome (narrative.
       enforce_quest_reward_world() only fires on narrative.quest_rewards
       INSERT/UPDATE).
    4. knowledge.entity_knowledge.timeline_id can change after knowledge.
       information_transfers reference it as source_entity_knowledge_id
       (knowledge.enforce_information_transfer_world() only fires on
       knowledge.information_transfers INSERT/UPDATE).
    5. campaign.objective_state.timeline_id can change after interaction.
       consequences references it through
       resulting_quest_objective_state_id (interaction.
       enforce_consequence_world() only fires on interaction.consequences
       INSERT/UPDATE).

    None of these six columns represent a legitimate "move" operation — a
    story arc's owning world, a stage's owning quest, an objective's owning
    stage, a quest outcome's owning quest, a knowledge belief's owning
    timeline, and an objective-state row's owning timeline are all identity,
    not configuration (grepped src/dnd_ai/commands and tests/factories
    before writing this revision: nothing in this repository updates any of
    these six columns after insert). The fix reuses revision 030's own
    core.enforce_immutable_columns() — a generic BEFORE UPDATE trigger
    function taking one or more protected column names as trigger arguments
    — rather than building six bespoke reverse-guard triggers or a
    transactional revalidate-and-rebuild path for a change that should not
    happen in the first place.

Forward migration:
    - core.enforce_immutable_columns() attached to: narrative.story_arcs
      (world_id), narrative.quest_stages (quest_id), narrative.
      quest_objectives (quest_stage_id), narrative.quest_outcomes
      (quest_id), knowledge.entity_knowledge (timeline_id), campaign.
      objective_state (timeline_id)

Rollback:
    Supported. Drops all six triggers. Does not touch core.
    enforce_immutable_columns() itself — owned by, and dropped only by,
    revision 030's own downgrade.

Data implications:
    Creates no rows. No test fixture in this project updates any of these
    six columns after insert, so nothing existing breaks.

Locking considerations:
    Adding a trigger does not rewrite a table.

See: docs/DATABASE_CONVENTIONS.md §9.5 (same-world consistency)
     docs/architecture/DATABASE_MODEL.md §14 (quest and story model),
     §15 (knowledge model)
     database/migrations/versions/030_parent_scope_immutability.py
     (the precedent this revision reuses)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "075_phase7_reparent_guards"
down_revision = "074_phase7_correction_pass"
branch_labels = None
depends_on = None

# (schema, table, trigger_name, [protected columns])
PROTECTED: list[tuple[str, str, str, list[str]]] = [
    ("narrative", "story_arcs", "tr_story_arcs_enforce_immutable", ["world_id"]),
    ("narrative", "quest_stages", "tr_quest_stages_enforce_immutable", ["quest_id"]),
    (
        "narrative",
        "quest_objectives",
        "tr_quest_objectives_enforce_immutable",
        ["quest_stage_id"],
    ),
    ("narrative", "quest_outcomes", "tr_quest_outcomes_enforce_immutable", ["quest_id"]),
    (
        "knowledge",
        "entity_knowledge",
        "tr_entity_knowledge_enforce_immutable",
        ["timeline_id"],
    ),
    (
        "campaign",
        "objective_state",
        "tr_objective_state_enforce_immutable",
        ["timeline_id"],
    ),
]


def upgrade() -> None:
    """Apply the migration."""

    for schema, table, trigger_name, columns in PROTECTED:
        args = ", ".join(f"'{c}'" for c in columns)
        op.execute(f"""
            CREATE TRIGGER {trigger_name}
            BEFORE UPDATE ON {schema}.{table}
            FOR EACH ROW EXECUTE FUNCTION core.enforce_immutable_columns({args});
        """)


def downgrade() -> None:
    """Revert the migration."""

    for schema, table, trigger_name, _columns in reversed(PROTECTED):
        op.execute(f"DROP TRIGGER IF EXISTS {trigger_name} ON {schema}.{table};")
