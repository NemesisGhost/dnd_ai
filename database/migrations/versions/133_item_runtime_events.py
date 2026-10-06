"""Add the narrative event types for item runtime operations

Revision ID: 133_item_runtime_events
Revises: 132_item_definition_authoring
Create Date: 2026-10-06 18:00:00.000000

Purpose:
    Phase 15 checkpoint 15.3B-1b. The item operations (equip, unequip, consume, damage,
    repair, attune, end attunement) each record one causal event. `item_acquired` (award) and
    `item_destroyed` (destroy) already exist from revision 057, and `item_transferred` and
    `item_identified` from revision 077, and are reused. No table changes: every item state
    table already carries `last_event_id`.

Forward migration:
    Seven `narrative.event_types` rows (`ON CONFLICT (code) DO NOTHING`).

Rollback:
    Supported: deletes the rows by code. It fails (foreign key) once any event of these types
    exists, which is the safe outcome; downgrade is intended for development databases.

Data implications:
    Seven new lookup rows; nothing references them until the item commands run.

Locking considerations:
    A small insert into a small lookup table.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "133_item_runtime_events"
down_revision = "132_item_definition_authoring"
branch_labels = None
depends_on = None

_EVENT_TYPES = [
    ("item_equipped", "Item Equipped", 170),
    ("item_unequipped", "Item Unequipped", 171),
    ("item_consumed", "Item Consumed", 172),
    ("item_damaged", "Item Damaged", 173),
    ("item_repaired", "Item Repaired", 174),
    ("item_attuned", "Item Attuned", 175),
    ("item_attunement_ended", "Item Attunement Ended", 176),
]


def upgrade() -> None:
    for code, display_name, sort_order in _EVENT_TYPES:
        op.execute(f"""
            INSERT INTO narrative.event_types (code, display_name, sort_order)
            VALUES ('{code}', '{display_name}', {sort_order})
            ON CONFLICT (code) DO NOTHING;
        """)


def downgrade() -> None:
    codes = ", ".join(f"'{code}'" for code, _, _ in _EVENT_TYPES)
    op.execute(f"DELETE FROM narrative.event_types WHERE code IN ({codes});")
