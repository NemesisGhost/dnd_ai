"""Add the narrative event type character_build_activated

Revision ID: 119_character_build_activated
Revises: 118_campaign_clock
Create Date: 2026-10-05 18:00:00.000000

Purpose:
    Phase 15 checkpoint 15.2B-2 (decision D-9, option a). A character's active
    build is timeline state (`campaign.character_state.character_build_id`). A
    build is immutable once created; changing which one is active is a new
    activation, and every change after the first is a causal event (rule 6). This
    adds the one event type that activation records, which the branch-aware build
    resolver (`queries/character_build_resolution.py`, step 2) already reads
    through `narrative.event_effects.target_component = 'character_build_id'`.

Forward migration:
    One `narrative.event_types` row (`ON CONFLICT (code) DO NOTHING`).

Rollback:
    Supported: deletes the row by code. It fails (foreign key) once any event of
    this type exists, which is the safe outcome; downgrade is intended for
    development databases.

Data implications:
    One new lookup row; nothing references it until the activation command runs.

Locking considerations:
    A single-row insert into a small lookup table.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "119_character_build_activated"
down_revision = "118_campaign_clock"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO narrative.event_types (code, display_name, sort_order)
        VALUES ('character_build_activated', 'Character Build Activated', 124)
        ON CONFLICT (code) DO NOTHING;
    """)


def downgrade() -> None:
    op.execute("DELETE FROM narrative.event_types WHERE code = 'character_build_activated';")
