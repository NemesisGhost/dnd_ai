"""Backfill campaign.character_location_history.location_period for populated upgrades

Revision ID: 052_char_location_backfill
Revises: 049_location_containment_lock
Create Date: 2026-08-03 15:00:00.000000

Purpose:
    Post-merge review finding (PHASE5_REMAINING_ISSUES.md item 3): revision
    043 added the derived, nullable location_period column and the trigger
    that computes it, but a database that already had
    campaign.character_location_history rows from revision 042 — before that
    trigger existed — upgrading through revision 043 would land those rows
    with location_period still NULL: the trigger only fires on INSERT or
    UPDATE, and revision 043 itself performs neither against existing rows.
    Revision 050 (already applied, not touched by this revision) only
    asserts that no row has a NULL location_period and aborts otherwise; it
    never backfilled one, and nothing between 043 and 050 did either. An
    ordinary revision placed after 051 cannot fix this: a database that
    fails during revision 050's guard never reaches any revision after it,
    so the repair has to run before that guard does.

    This revision is therefore spliced into history between 049 and 050 —
    revision 050's own down_revision has been repointed at this revision
    instead of 049_location_containment_lock. That is a narrowly-scoped,
    explicitly recorded exception to this project's forward-only migration
    policy (DATABASE_CONVENTIONS.md §37), justified by two things holding
    together: (1) revision 050 has never actually run against a populated
    database — this project has no production deployment, and every
    environment's history table has been empty at every revision boundary
    so far, so there is no real upgrade path being rewritten, only a
    hypothetical one the review asked to be provably correct; and (2)
    revision 050's own DDL — the NULL assertion, the ALTER COLUMN ... SET
    NOT NULL, the corrected comments — is completely unchanged from what
    merged and passed CI in PR #5. Repointing its down_revision changes only
    what runs immediately before it, not anything it does itself.

    The backfill does not recompute location_period by hand. Revision 043's
    campaign.sync_character_location_period() trigger already fires on every
    INSERT OR UPDATE — not scoped to particular columns — and already
    implements every validation the review asked for: timeline/character/
    location world agreement, both endpoints' world agreement, departure
    strictly later than arrival, and derivation from the endpoints'
    sort_key values, with RAISE EXCEPTION messages already covered by
    tests/database/test_character_location_temporal_integrity.py. A no-op
    UPDATE (setting arrived_at_world_time_id to its own current value) on
    every row where location_period IS NULL re-fires that trigger, reusing
    its exact, already-tested logic instead of duplicating it here. The
    table's own ex_character_location_history_no_overlap exclusion
    constraint (added by revision 043) then catches a genuine overlap
    between two legacy rows exactly the way it catches one on any other
    write — a GiST exclusion constraint does not compare NULL values against
    each other, so nothing here silently bypassed that check; it simply
    could not fire until a real value existed to compare.

    A missing arrival endpoint is not reachable in practice: revision 043
    already made arrived_at_world_time_id NOT NULL for every row (with no
    backfill of its own, since no rows existed when that revision was
    written) — a database with a NULL arrival endpoint at revision 042 would
    already have failed applying revision 043, long before reaching this
    revision. The no-op UPDATE's reliance on that NOT NULL guarantee is kept
    as a defensive backstop rather than assumed permanently safe: if
    arrived_at_world_time_id were ever somehow NULL, the UPDATE itself would
    fail on that column's own NOT NULL constraint with a standard, clear
    PostgreSQL error, not a manufactured or silently wrong range.

Forward migration:
    - UPDATE campaign.character_location_history
      SET arrived_at_world_time_id = arrived_at_world_time_id
      WHERE location_period IS NULL
      — re-fires revision 043's derivation trigger for every legacy row,
      reusing its validation and range derivation unchanged.

Rollback:
    Supported, and a genuine no-op: reversing a backfill that only
    recomputes data already fully implied by existing columns has nothing
    to undo. Included so `alembic downgrade` never errors on this revision,
    not because there is state to restore.

Data implications:
    Rewrites campaign.character_location_history.location_period for any
    row where it is currently NULL. No environment this project has ever
    deployed (including `dev`) has had a row in this table at any point, so
    this UPDATE matches zero rows and is a genuine no-op everywhere it has
    actually run; it exists so the documented upgrade path is correct for a
    database that does have rows, not because a real backfill is pending
    anywhere today.

Locking considerations:
    A conditional UPDATE over a table with zero rows in every environment
    this project has ever deployed. If a populated table is ever
    encountered, row locks are held only for the duration of the UPDATE like
    any other write to this table — no broader lock than an ordinary UPDATE
    already takes.

See: docs/PHASE5_REMAINING_ISSUES.md item 3
     database/migrations/versions/043_character_location_temporal_integrity.py
     (campaign.sync_character_location_period(), reused unchanged here)
     database/migrations/versions/050_character_location_period_not_null.py
     (down_revision repointed to this revision — see its own "Amendment" note)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "052_char_location_backfill"
down_revision = "049_location_containment_lock"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    op.execute("""
        UPDATE campaign.character_location_history
        SET arrived_at_world_time_id = arrived_at_world_time_id
        WHERE location_period IS NULL;
    """)


def downgrade() -> None:
    """Revert the migration — a genuine no-op; see this file's docstring."""
