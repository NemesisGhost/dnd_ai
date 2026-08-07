"""Event provenance on Phase 5 dungeon timeline-state tables

Revision ID: 060_state_event_provenance
Revises: 059_branch_effective_history
Create Date: 2026-08-05 15:00:00.000000

Purpose:
    Closes the other Phase 6 first-time obligation docs/PLAN.md names
    alongside branch_event_id: "extend campaign.location_state/
    .area_connection_state/.area_feature_state/.hazard_state/
    .interactable_state with a last_event_id provenance column, the same
    pattern Phase 4's character-state tables are already expected to receive
    here." docs/architecture/DATABASE_MODEL.md §17 gives the exact shape:
    once narrative.events exists, a current-state row should carry a
    provenance reference to the event that produced it, rather than the full
    effective_from_event_id/effective_to_event_id interval history these
    tables were deliberately NOT built with in Phase 5 (they are single
    current-row snapshots, not interval history — see revision 040's
    docstring and DATABASE_MODEL.md §17's explicit guidance not to retrofit
    that shape now).

    Nullable: rows written before this column existed have none, and rule 6's
    "explicit administrative source" carve-out (docs/architecture/
    DATABASE_MODEL.md rule 6) covers GM/import-driven state changes with no
    causing event at all.

Forward migration:
    - campaign.location_state.last_event_id
    - campaign.area_connection_state.last_event_id
    - campaign.area_feature_state.last_event_id
    - campaign.hazard_state.last_event_id
    - campaign.interactable_state.last_event_id
    All UUID REFERENCES narrative.events(event_id) ON DELETE SET NULL, each
    with a partial index.

Rollback:
    Supported. Drops all five columns.

Data implications:
    None — every existing row gets last_event_id = NULL, which is exactly
    correct (no event produced them; they predate this column).

Locking considerations:
    Five ALTER TABLE ADD COLUMN statements, each a brief metadata-only lock
    (no default, so no table rewrite). All five tables are small.

See: docs/PLAN.md Phase 6 (first-time obligations)
     docs/architecture/DATABASE_MODEL.md §17 (typed timeline state)
     docs/DATABASE_CONVENTIONS.md §13.4 (causality)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "060_state_event_provenance"
down_revision = "059_branch_effective_history"
branch_labels = None
depends_on = None

STATE_TABLES = [
    "location_state",
    "area_connection_state",
    "area_feature_state",
    "hazard_state",
    "interactable_state",
]


def upgrade() -> None:
    """Apply the migration."""

    for table in STATE_TABLES:
        op.execute(f"""
            ALTER TABLE campaign.{table}
            ADD COLUMN last_event_id UUID
                REFERENCES narrative.events(event_id) ON DELETE SET NULL;
        """)
        op.execute(f"""
            COMMENT ON COLUMN campaign.{table}.last_event_id IS
            'The event that produced this row''s current values, when there was '
            'one (conventions §13.4). NULL for rows predating this column and for '
            'administrative/import-driven changes with no causing event.';
        """)
        op.execute(
            f"CREATE INDEX ix_{table}_last_event_id ON campaign.{table} (last_event_id) "
            "WHERE last_event_id IS NOT NULL;"
        )


def downgrade() -> None:
    """Revert the migration."""

    for table in reversed(STATE_TABLES):
        op.execute(f"ALTER TABLE campaign.{table} DROP COLUMN IF EXISTS last_event_id;")
