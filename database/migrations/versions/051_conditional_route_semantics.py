"""Define conditional-route column semantics with a CHECK constraint

Revision ID: 051_conditional_route_semantics
Revises: 050_char_location_period_notnull
Create Date: 2026-08-03 13:30:00.000000

Purpose:
    Phase 5 exit review finding: revision 047 added
    world.area_connections.is_conditional and .condition_description without
    any constraint tying them together, so the schema silently permitted two
    contradictory states: is_conditional = true with no description (a
    conditional route with nothing recorded about what the condition is),
    and is_conditional = false with a description (a description with no
    flag saying it matters). No design document establishes a deliberate use
    for either contradictory state — revision 047's own comment describes
    condition_description as "what the condition is" for a route already
    flagged conditional, not an independent free-text note. The unambiguous
    reading is enforced directly: a conditional route must have a non-null,
    non-blank description; an unconditional route must not have one.

Forward migration:
    - CONSTRAINT ck_area_connections_conditional_description_paired on
      world.area_connections: is_conditional = true requires a
      condition_description that is not null and not blank (after
      trimming); is_conditional = false requires condition_description IS
      NULL.

Rollback:
    Supported. Drops the constraint.

Data implications:
    None found in practice. No existing area_connections rows violate this
    (verified by the constraint being added with a full validation scan,
    not NOT VALID) — revision 047 added no rows itself, and no command layer
    writes to this table yet.

Locking considerations:
    ADD CONSTRAINT ... CHECK on this table takes a validating scan (not
    skipped, since this is a new constraint) but the table is not large
    enough at this project stage for that to matter.

See: database/migrations/versions/047_realm_and_conditional_routes.py
     (introduces the two columns this revision constrains)
     docs/DATABASE_CONVENTIONS.md §9 (constraint-based invariants over
     silently permissive columns)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "051_conditional_route_semantics"
down_revision = "050_char_location_period_notnull"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

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


def downgrade() -> None:
    """Revert the migration."""

    op.execute(
        "ALTER TABLE world.area_connections "
        "DROP CONSTRAINT IF EXISTS ck_area_connections_conditional_description_paired;"
    )
    op.execute("""
        COMMENT ON COLUMN world.area_connections.condition_description IS
        'Free-text description of what the condition is (e.g. "requires the brass key" '
        'or "only open while the beacon is lit"). Not yet machine-evaluable — same '
        'placeholder shape as campaign.character_conditions.source_description.';
    """)
