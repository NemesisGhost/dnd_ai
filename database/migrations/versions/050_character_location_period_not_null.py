"""Make character_location_history.location_period structurally NOT NULL

Revision ID: 050_char_location_period_notnull
Revises: 049_location_containment_lock
Create Date: 2026-08-03 13:00:00.000000

Purpose:
    Phase 5 exit review finding: revision 043 gave
    campaign.character_location_history a derived location_period column and
    a BEFORE INSERT OR UPDATE trigger (campaign.sync_character_location_period)
    that unconditionally sets it on every row, but never declared the column
    NOT NULL — unlike campaign.party_memberships.effective_period (revision
    009), the ADR 0010 pattern this table is supposed to match exactly. The
    trigger already makes a NULL value unreachable through normal writes; the
    column's own nullability just never caught up to that guarantee, leaving
    the schema silently weaker than the invariant it already enforces.

Forward migration:
    - Backfill guard: assert no existing row has a NULL location_period
      before altering the column (belt-and-suspenders — the revision 043
      trigger already prevents this on any row written after it existed, and
      no command layer writes to this table yet, but the check makes the
      migration correct regardless of what data exists when it runs, per
      DATABASE_CONVENTIONS.md's migration-safety expectations, rather than
      assuming the current dev state).
    - ALTER COLUMN location_period SET NOT NULL
    - Corrects the table's own COMMENT, which still described the
      superseded revision-042 partial-unique-index design instead of the
      revision-043 derived-range/exclusion-constraint contract this table
      has actually enforced since that revision landed

Rollback:
    Supported. Drops the NOT NULL constraint. The derivation trigger and
    exclusion constraint are untouched by either direction — this revision
    only tightens nullability.

Data implications:
    None found in practice (asserted, not assumed — see above). No backfill
    UPDATE is needed because every existing row already has a derived range.

Locking considerations:
    SET NOT NULL on Postgres 12+ can use an existing CHECK constraint to
    skip the full-table scan, but none applies here (there is no
    "location_period IS NOT NULL" CHECK), so this performs a table scan to
    verify the constraint. Harmless at this table's current size; worth
    revisiting if this table becomes very large before Phase 6 event-sourced
    writes exist.

See: docs/adr/0010-use-sort-key-ranges-for-fictional-time-intervals.md
     database/migrations/versions/043_character_location_temporal_integrity.py
     (introduces location_period; this revision only tightens it)
     database/migrations/versions/009_parties_and_memberships.py
     (effective_period, NOT NULL from the start — the pattern this closes the gap with)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "050_char_location_period_notnull"
down_revision = "049_location_containment_lock"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    op.execute("""
        DO $$
        DECLARE
            v_null_count BIGINT;
        BEGIN
            SELECT count(*) INTO v_null_count
            FROM campaign.character_location_history
            WHERE location_period IS NULL;

            IF v_null_count > 0 THEN
                RAISE EXCEPTION
                    'Cannot make location_period NOT NULL: % existing row(s) have a NULL '
                    'location_period. Backfill them before re-running this migration.',
                    v_null_count;
            END IF;
        END;
        $$;
    """)

    op.execute(
        "ALTER TABLE campaign.character_location_history ALTER COLUMN location_period SET NOT NULL;"
    )
    op.execute("""
        COMMENT ON COLUMN campaign.character_location_history.location_period IS
        'Derived, never client-authoritative: an INT8RANGE over '
        'arrived_at_world_time_id/departed_at_world_time_id''s sort_key values, rebuilt '
        'by trigger on every INSERT and UPDATE — same role and same NOT NULL contract '
        'as campaign.party_memberships.effective_period (ADR 0010).';
    """)
    op.execute("""
        COMMENT ON TABLE campaign.character_location_history IS
        'Where a character has been on a timeline. The row with '
        'departed_at_world_time_id IS NULL is the character''s current location — the '
        'single current-location representation, enforced by the derived '
        'location_period range together with the '
        'ex_character_location_history_no_overlap exclusion constraint over '
        '(timeline_id, character_id, location_period), the same ADR 0010 shape as '
        'campaign.party_memberships. Deferred from Phase 4 until world.locations '
        'existed (docs/architecture/DATABASE_MODEL.md §17).';
    """)


def downgrade() -> None:
    """Revert the migration."""

    op.execute("""
        COMMENT ON TABLE campaign.character_location_history IS
        'Where a character has been on a timeline. The row with '
        'departed_at_world_time_id IS NULL is the character''s current location — at '
        'most one per (timeline, character), enforced by a partial unique index. '
        'Deferred from Phase 4 until world.locations existed '
        '(docs/architecture/DATABASE_MODEL.md §17).';
    """)
    op.execute("""
        COMMENT ON COLUMN campaign.character_location_history.location_period IS
        'Derived, never client-authoritative: an INT8RANGE over '
        'arrived_at_world_time_id/departed_at_world_time_id''s sort_key values, '
        'rebuilt by trigger on every INSERT and UPDATE — same role as '
        'campaign.party_memberships.effective_period (ADR 0010).';
    """)
    op.execute(
        "ALTER TABLE campaign.character_location_history "
        "ALTER COLUMN location_period DROP NOT NULL;"
    )
