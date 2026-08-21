"""ai.proposed_changes.proposal_kind widens to include
'advance_quest_objective' — Phase 12's second proposal-kind vertical slice.

Revision ID: 097_advance_objective_kind
Revises: 096_campaign_scoped_agents
Create Date: 2026-08-20 18:30:00.000000

Purpose:
    093_ai_domain's own docstring named this exactly: "ai.proposed_changes.
    proposal_kind is a single-value closed set today (reveal_knowledge) ...
    extending it is a migration, the same posture narrative.event_types/
    audit.change_actions already take." This is that migration. Phase 12's
    NPC-conversation use case can now also propose completing or failing a
    quest objective the NPC participates in — an approved proposal dispatches
    to the existing dnd_ai.commands.quests._advance_objective_impl canonical
    command (dnd_ai.commands.ai_proposals._apply_proposal's own closed
    dispatch table), never a new or duplicate mutation path.

Forward migration:
    - DROP the existing single-value ck_proposed_changes_kind CHECK
      constraint and re-ADD it widened to
      proposal_kind IN ('reveal_knowledge', 'advance_quest_objective').

Rollback:
    Supported, with the same inherent, accepted narrowing-downgrade property
    every CHECK-narrowing rollback in this project has (matching
    096_campaign_scoped_agents' own NOT-NULL-restoring downgrade note):
    fails if any 'advance_quest_objective' row was created since this
    migration ran. That is correct, not a gap to work around — a downgrade
    that silently deleted or reclassified those rows would destroy proposal
    history a GM may have already reviewed.

Data implications:
    None. No existing row's proposal_kind changes value; the widened CHECK
    only permits a new value going forward.

Locking considerations:
    DROP CONSTRAINT + ADD CONSTRAINT ... CHECK on ai.proposed_changes takes
    an ACCESS EXCLUSIVE lock for the duration of the statement, but the
    table is new (093_ai_domain, this same phase) and low-volume — no
    concurrent-access concern distinct from any other CHECK-constraint
    migration in this project.

See: database/migrations/versions/093_ai_domain.py (this constraint's own
     origin and the "extending it is a migration" note this migration
     closes)
     src/dnd_ai/commands/ai_proposals.py (the dispatch table this proposal
     kind is wired into)
     src/dnd_ai/commands/quests.py (the canonical command applying it calls)
     docs/PLAN.md Phase 12 (Narrow AI/NPC MVP)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "097_advance_objective_kind"
down_revision = "096_campaign_scoped_agents"
branch_labels = None
depends_on = None

_PROPOSAL_KINDS = ("reveal_knowledge", "advance_quest_objective")


def upgrade() -> None:
    """Apply the migration."""

    op.execute("ALTER TABLE ai.proposed_changes DROP CONSTRAINT ck_proposed_changes_kind;")
    op.execute(f"""
        ALTER TABLE ai.proposed_changes
        ADD CONSTRAINT ck_proposed_changes_kind CHECK (proposal_kind IN {_PROPOSAL_KINDS});
    """)


def downgrade() -> None:
    """Revert the migration."""

    op.execute("ALTER TABLE ai.proposed_changes DROP CONSTRAINT ck_proposed_changes_kind;")
    op.execute("""
        ALTER TABLE ai.proposed_changes
        ADD CONSTRAINT ck_proposed_changes_kind CHECK (proposal_kind = 'reveal_knowledge');
    """)
