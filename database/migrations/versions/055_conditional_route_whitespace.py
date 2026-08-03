"""Treat all whitespace-only conditional-route descriptions as blank

Revision ID: 055_conditional_route_whitespace
Revises: 054_location_cycle_detection
Create Date: 2026-08-03 17:00:00.000000

Purpose:
    Post-merge review finding (PHASE5_REMAINING_ISSUES.md item 4): revision
    051's ck_area_connections_conditional_description_paired uses
    trim(both ' ' from condition_description) to decide whether a
    condition_description is "blank." PostgreSQL's trim() strips only the
    exact character(s) named — an ordinary space, here — so a description
    containing only a tab, a newline, a carriage return, or any mix of
    whitespace characters still has a positive char_length() after that
    trim and satisfies the constraint's "nonblank" clause, even though it
    displays as nothing and carries no actual information about what the
    condition is.

    Fixed by testing for the presence of at least one non-whitespace
    character directly, condition_description ~ '\\S', instead of trimming
    one specific character and measuring what is left. \\S is PostgreSQL's
    POSIX regex shorthand for "not a whitespace character" (space, tab,
    newline, carriage return, form feed, vertical tab) — this is a positive
    test for "has real content," not an enumeration of characters to strip,
    so it does not need to name every whitespace character to reject a
    string made only of them.

Forward migration:
    - Drop and recreate ck_area_connections_conditional_description_paired
      with condition_description ~ '\\S' in place of
      char_length(trim(both ' ' from condition_description)) > 0. The
      pairing logic (conditional requires a real description; unconditional
      requires none) is otherwise unchanged.

Rollback:
    Supported. Restores revision 051's exact constraint definition.

Data implications:
    None found in practice — no command layer writes to this table yet, and
    revision 051 itself added no rows. Adding the replacement constraint
    performs a full validation scan of existing rows (not NOT VALID), which
    is safe at this table's current size.

Locking considerations:
    DROP CONSTRAINT + ADD CONSTRAINT ... CHECK takes a validating scan of
    world.area_connections; harmless at this project's current data volume.

See: docs/PHASE5_REMAINING_ISSUES.md item 4
     database/migrations/versions/051_conditional_route_semantics.py
     (introduces the constraint this revision corrects)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "055_conditional_route_whitespace"
down_revision = "054_location_cycle_detection"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    op.execute(
        "ALTER TABLE world.area_connections "
        "DROP CONSTRAINT ck_area_connections_conditional_description_paired;"
    )
    op.execute(r"""
        ALTER TABLE world.area_connections
        ADD CONSTRAINT ck_area_connections_conditional_description_paired
            CHECK (
                (
                    is_conditional
                    AND condition_description IS NOT NULL
                    AND condition_description ~ '\S'
                )
                OR (
                    NOT is_conditional
                    AND condition_description IS NULL
                )
            );
    """)
    op.execute("""
        COMMENT ON COLUMN world.area_connections.condition_description IS
        'Free-text description of what the condition is (e.g. "requires the brass key" '
        'or "only open while the beacon is lit"). Required when is_conditional is true, '
        'and must contain at least one non-whitespace character — space, tab, newline, '
        'and carriage-return-only values are all treated as blank and rejected '
        '(ck_area_connections_conditional_description_paired). Must be NULL when '
        'is_conditional is false. Not yet machine-evaluable — same placeholder shape as '
        'campaign.character_conditions.source_description.';
    """)


def downgrade() -> None:
    """Revert the migration."""

    op.execute(
        "ALTER TABLE world.area_connections "
        "DROP CONSTRAINT ck_area_connections_conditional_description_paired;"
    )
    op.execute("""
        ALTER TABLE world.area_connections
        ADD CONSTRAINT ck_area_connections_conditional_description_paired
            CHECK (
                (
                    is_conditional
                    AND condition_description IS NOT NULL
                    AND char_length(trim(both ' ' from condition_description)) > 0
                )
                OR (
                    NOT is_conditional
                    AND condition_description IS NULL
                )
            );
    """)
    op.execute("""
        COMMENT ON COLUMN world.area_connections.condition_description IS
        'Free-text description of what the condition is (e.g. "requires the brass key" '
        'or "only open while the beacon is lit"). Required and non-blank when '
        'is_conditional is true; must be NULL when is_conditional is false '
        '(ck_area_connections_conditional_description_paired). Not yet machine-'
        'evaluable — same placeholder shape as '
        'campaign.character_conditions.source_description.';
    """)
