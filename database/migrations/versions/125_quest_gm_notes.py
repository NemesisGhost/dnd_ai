"""Add narrative.quests.gm_notes (GM-only planning text)

Revision ID: 125_quest_gm_notes
Revises: 124_event_corrections
Create Date: 2026-10-06 21:00:00.000000

Purpose:
    Phase 15 checkpoint 15.2E-2a (decision D-29). A GM plans a quest (twists, secrets,
    what the players do not know yet) in text that must never reach a player. This adds
    the column; it is classified GM-only in `dnd_ai.domain.data_classification`, never
    selected by any audience-safe read, redacted in audit, and held in revision history
    only through the GM-only authoring view.

Forward migration:
    `narrative.quests.gm_notes TEXT NULL` with a 4000-character bound.

Rollback:
    Drops the column; planning notes are lost (development databases only).

Data implications:
    Existing quests get NULL.

Locking considerations:
    ADD COLUMN without a default is metadata-only.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "125_quest_gm_notes"
down_revision = "124_event_corrections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE narrative.quests
        ADD COLUMN gm_notes TEXT,
        ADD CONSTRAINT ck_quests_gm_notes_length
            CHECK (gm_notes IS NULL OR char_length(gm_notes) <= 4000);
    """)
    op.execute("""
        COMMENT ON COLUMN narrative.quests.gm_notes IS
        'GM-only planning text for the quest. Never shown to a player, never in an audience-safe '
        'read, preview, or audit value.';
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE narrative.quests
        DROP CONSTRAINT IF EXISTS ck_quests_gm_notes_length,
        DROP COLUMN IF EXISTS gm_notes;
    """)
