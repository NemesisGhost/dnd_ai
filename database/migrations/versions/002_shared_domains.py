"""Add shared domain types

Revision ID: 002_shared_domains
Revises: 001_bootstrap
Create Date: 2026-07-31 00:01:00.000000

Purpose:
    Create reusable PostgreSQL domain types for common numeric constraints used
    throughout the schema. These domains provide consistent validation and semantics
    for ratings, percentages, and non-negative values.

Forward migration:
    - core.rating_1_10: smallint constrained to [1, 10]
    - core.percentage_0_100: smallint constrained to [0, 100]
    - core.nonnegative_integer: integer constrained to >= 0

    Used for:
    - NPC importance ratings
    - Condition/resource percentages
    - Confidence scores
    - Affinity measurements
    - Non-negative counts and quantities

Rollback:
    Supported. Drops the three domains.
    Cannot be run if any tables use these domains.

Data implications:
    None. No tables exist yet that would use these domains.

Locking considerations:
    None. Domain creation does not lock anything.

See: docs/PLAN.md §4.2 (Shared domains)
     docs/DATABASE_CONVENTIONS.md §8 (Domain types)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "002_shared_domains"
down_revision = "001_bootstrap"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create shared domain types."""

    # rating_1_10: Used for importance, priority, difficulty, threat levels
    op.execute("""
        CREATE DOMAIN core.rating_1_10 AS smallint
        CHECK (VALUE BETWEEN 1 AND 10);
    """)
    op.execute("""
        COMMENT ON DOMAIN core.rating_1_10 IS
        'Integer rating from 1 (lowest) to 10 (highest). Used for importance, '
        'priority, difficulty, and similar subjective measurements.';
    """)

    # percentage_0_100: Used for completion, confidence, resource levels
    op.execute("""
        CREATE DOMAIN core.percentage_0_100 AS smallint
        CHECK (VALUE BETWEEN 0 AND 100);
    """)
    op.execute("""
        COMMENT ON DOMAIN core.percentage_0_100 IS
        'Integer percentage from 0 to 100. Used for completion rates, confidence '
        'scores, resource levels (HP, spell slots), and probability estimates.';
    """)

    # nonnegative_integer: Used for counts, quantities, distances
    op.execute("""
        CREATE DOMAIN core.nonnegative_integer AS integer
        CHECK (VALUE >= 0);
    """)
    op.execute("""
        COMMENT ON DOMAIN core.nonnegative_integer IS
        'Non-negative integer (>= 0). Used for counts, quantities, gold pieces, '
        'experience points, and similar values that cannot be negative.';
    """)


def downgrade() -> None:
    """Drop shared domain types."""

    # Drop in reverse order (though order doesn't matter for domains without dependencies)
    op.execute("DROP DOMAIN IF EXISTS core.nonnegative_integer;")
    op.execute("DROP DOMAIN IF EXISTS core.percentage_0_100;")
    op.execute("DROP DOMAIN IF EXISTS core.rating_1_10;")
