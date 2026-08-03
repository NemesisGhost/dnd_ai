"""updated_at triggers for the five dungeon timeline-state tables

Revision ID: 046_dungeon_state_updated_at
Revises: 045_knowledge_timestamp_world
Create Date: 2026-08-03 09:45:00.000000

Purpose:
    Phase 5 exit review finding: campaign.location_state,
    .area_connection_state, .area_feature_state, .hazard_state, and
    .interactable_state (revision 040) each carry an updated_at column but
    revision 040 never attached core.set_updated_at() to any of them —
    unlike every other mutable table in the schema, including revision 040's
    own three status lookups, which do have it. updated_at on these five
    tables has been a plain column with a creation-time default and no
    maintenance trigger, silently failing to advance on UPDATE.

Forward migration:
    - core.set_updated_at() attached to campaign.location_state,
      .area_connection_state, .area_feature_state, .hazard_state,
      .interactable_state

Rollback:
    Supported. Drops all five triggers.

Data implications:
    None.

Locking considerations:
    Adding a trigger does not rewrite a table.

See: docs/DATABASE_CONVENTIONS.md §10.4 (updated timestamps)
     database/migrations/versions/040_dungeon_timeline_state.py (the tables
     this revision completes)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "046_dungeon_state_updated_at"
down_revision = "045_knowledge_timestamp_world"
branch_labels = None
depends_on = None

TABLES = [
    "location_state",
    "area_connection_state",
    "area_feature_state",
    "hazard_state",
    "interactable_state",
]


def upgrade() -> None:
    """Apply the migration."""

    for table in TABLES:
        op.execute(f"""
            CREATE TRIGGER tr_{table}_set_updated_at
            BEFORE UPDATE ON campaign.{table}
            FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
        """)


def downgrade() -> None:
    """Revert the migration."""

    for table in reversed(TABLES):
        op.execute(f"DROP TRIGGER IF EXISTS tr_{table}_set_updated_at ON campaign.{table};")
