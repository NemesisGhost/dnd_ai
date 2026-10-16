"""Add the narrative event types for quest and objective runtime changes

Revision ID: 126_quest_runtime_events
Revises: 125_quest_gm_notes
Create Date: 2026-10-06 09:00:00.000000

Purpose:
    Phase 15 checkpoint 15.2E-2b (decision D-16, option a: explicit GM commands only).
    Quest progress is timeline state (`campaign.quest_state`, `campaign.objective_state`)
    and every change needs a causal event (rule 6). This adds the event types the
    runtime commands record: a quest is activated, completed, suspended,
    resumed or abandoned (`quest_failed` already exists), and an objective is activated or skipped (completing or
    failing an objective keeps its existing `objective_completed` / `objective_failed`).

Forward migration:
    Seven `narrative.event_types` rows (`ON CONFLICT (code) DO NOTHING`).

Rollback:
    Supported: deletes the rows by code. It fails (foreign key) once any event of these
    types exists, which is the safe outcome; downgrade is intended for development
    databases.

Data implications:
    Seven new lookup rows; nothing references them until the runtime commands run.

Locking considerations:
    A small insert into a small lookup table.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "126_quest_runtime_events"
down_revision = "125_quest_gm_notes"
branch_labels = None
depends_on = None

_EVENT_TYPES = (
    ("quest_activated", "Quest Activated", 130),
    ("quest_completed", "Quest Completed", 131),
    ("quest_suspended", "Quest Suspended", 133),
    ("quest_resumed", "Quest Resumed", 134),
    ("quest_abandoned", "Quest Abandoned", 135),
    ("objective_activated", "Objective Activated", 136),
    ("objective_skipped", "Objective Skipped", 137),
)


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
