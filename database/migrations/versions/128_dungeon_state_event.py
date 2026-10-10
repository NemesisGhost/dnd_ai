"""Add the narrative event type dungeon_state_changed

Revision ID: 128_dungeon_state_event
Revises: 127_knowledge_runtime
Create Date: 2026-10-06 15:00:00.000000

Purpose:
    Phase 15 checkpoint 15.3A-1 (decision D-31). A dungeon's runtime state (a connection
    open or locked, a hazard armed or triggered, an interactable activated, a feature
    destroyed, an area searched or on alert) is timeline state, and every change needs a
    causal event (rule 6). The interaction commands already record their own events when a
    check resolves; this adds the one event type the GM's explicit state command records.
    The state tables already carry `last_event_id`, so nothing else changes in the schema.

Forward migration:
    One `narrative.event_types` row (`ON CONFLICT (code) DO NOTHING`).

Rollback:
    Supported: deletes the row by code. It fails (foreign key) once any event of this type
    exists, which is the safe outcome; downgrade is intended for development databases.

Data implications:
    One new lookup row; nothing references it until the state command runs.

Locking considerations:
    A single-row insert into a small lookup table.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "128_dungeon_state_event"
down_revision = "127_knowledge_runtime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO narrative.event_types (code, display_name, sort_order)
        VALUES ('dungeon_state_changed', 'Dungeon State Changed', 150)
        ON CONFLICT (code) DO NOTHING;
    """)


def downgrade() -> None:
    op.execute("DELETE FROM narrative.event_types WHERE code = 'dungeon_state_changed';")
