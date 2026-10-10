"""Add event provenance and event types for the knowledge runtime

Revision ID: 127_knowledge_runtime
Revises: 126_quest_runtime_events
Create Date: 2026-10-06 12:00:00.000000

Purpose:
    Phase 15 checkpoint 15.2E-3 (decision D-17: character, party, NPC, organization and
    public-at-location audiences, all on existing tables). Who knows a claim is per-knower
    timeline state, so every change needs a causal event (rule 6), and an event correction
    must be able to find the rows an event wrote and tell whether they have changed since.
    `campaign.party_knowledge` already carries `last_event_id`; this gives the other two
    state tables the same column and the shared same-timeline guard.

Forward migration:
    - `narrative.event_types`: `knowledge_learned`, `knowledge_transferred`,
      `belief_changed`, `knowledge_made_public` (`ON CONFLICT (code) DO NOTHING`).
    - `knowledge.entity_knowledge.last_event_id` and
      `knowledge.public_knowledge.last_event_id`: nullable foreign keys to
      `narrative.events` (`ON DELETE SET NULL`), each with a partial index, and the shared
      `campaign.enforce_state_event_timeline()` trigger so the cited event must belong to
      the row's own timeline. Rows created before this revision keep NULL.

Rollback:
    Supported. Drops the triggers, indexes and columns and deletes the event types. The
    event-type delete fails (foreign key) once any event of those types exists, which is
    the safe outcome; downgrade is intended for development databases.

Data implications:
    Four lookup rows and two NULL columns on existing rows.

Locking considerations:
    ADD COLUMN without a default is metadata-only; the partial indexes cover only NULL-free
    rows, so they are empty on creation.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "127_knowledge_runtime"
down_revision = "126_quest_runtime_events"
branch_labels = None
depends_on = None

_EVENT_TYPES = (
    ("knowledge_learned", "Knowledge Learned", 140),
    ("knowledge_transferred", "Knowledge Transferred", 141),
    ("belief_changed", "Belief Changed", 142),
    ("knowledge_made_public", "Knowledge Made Public", 143),
)

_TABLES = (
    ("entity_knowledge", "knowledge"),
    ("public_knowledge", "knowledge"),
)


def upgrade() -> None:
    for code, display_name, sort_order in _EVENT_TYPES:
        op.execute(f"""
            INSERT INTO narrative.event_types (code, display_name, sort_order)
            VALUES ('{code}', '{display_name}', {sort_order})
            ON CONFLICT (code) DO NOTHING;
        """)
    for table, schema in _TABLES:
        op.execute(f"""
            ALTER TABLE {schema}.{table}
            ADD COLUMN last_event_id UUID REFERENCES narrative.events(event_id) ON DELETE SET NULL;
        """)
        op.execute(f"""
            COMMENT ON COLUMN {schema}.{table}.last_event_id IS
            'The event that last wrote this row (same timeline); NULL for rows created '
            'before revision 127 or written administratively.';
        """)
        op.execute(
            f"CREATE INDEX ix_{table}_last_event_id ON {schema}.{table} (last_event_id) "
            "WHERE last_event_id IS NOT NULL;"
        )
        op.execute(f"""
            CREATE TRIGGER tr_{table}_enforce_event_timeline
            BEFORE INSERT OR UPDATE ON {schema}.{table}
            FOR EACH ROW EXECUTE FUNCTION campaign.enforce_state_event_timeline();
        """)


def downgrade() -> None:
    for table, schema in _TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS tr_{table}_enforce_event_timeline ON {schema}.{table};")
        op.execute(f"DROP INDEX IF EXISTS {schema}.ix_{table}_last_event_id;")
        op.execute(f"ALTER TABLE {schema}.{table} DROP COLUMN IF EXISTS last_event_id;")
    codes = ", ".join(f"'{code}'" for code, _, _ in _EVENT_TYPES)
    op.execute(f"DELETE FROM narrative.event_types WHERE code IN ({codes});")
