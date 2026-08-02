"""Immutability for the remaining rule-definition tables

Revision ID: 036_remaining_rules_immutable
Revises: 035_world_ruleset_concurrency
Create Date: 2026-08-02 23:15:00.000000

Purpose:
    Corrective revision (PHASE4_REMAINING_ISSUES.md §2, post-closeout review).
    DATABASE_MODEL.md §8 states every rule-content row's `ruleset_version_id`
    is immutable identity. Revision 033 implemented that policy for every
    rule-definition table with a *cross-version invariant already checking
    it as a parent* (abilities, species, damage_types, conditions,
    resource_definitions, skills, classes, subclasses, spells,
    proficiency_types), but `rules.creature_types`, `rules.languages`, and
    `rules.feats` have no such invariant today — nothing currently reads
    their `ruleset_version_id` as a parent — so revision 033's own
    enumeration (built by grepping for that pattern) silently missed them.
    They are still rule-definition tables scoped to a ruleset version, so
    the same identity policy applies regardless of whether something
    references them yet; a later phase adding a cross-version check against
    one of them (e.g. a character's known languages, once that gets its own
    ruleset-scoping) must not discover the column was mutable in the
    meantime.

Forward migration:
    - `core.enforce_immutable_columns()` (revision 030/033) attached to
      `rules.creature_types`, `rules.languages`, `rules.feats`, protecting
      `ruleset_version_id` on each — the same trigger, same shape, as every
      other rule-content table.

Rollback:
    Supported. Drops the three new triggers.

Data implications:
    Creates no rows.

Locking considerations:
    Adding a trigger does not rewrite a table.

See: PHASE4_REMAINING_ISSUES.md §2
     docs/architecture/DATABASE_MODEL.md §8 (rules model)
     database/migrations/versions/033_rules_identity_immutability.py
     tests/database/test_phase4_remaining_issues.py (the table-driven
     coverage test this revision closes)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "036_remaining_rules_immutable"
down_revision = "035_world_ruleset_concurrency"
branch_labels = None
depends_on = None

PROTECTED: list[tuple[str, str, str, list[str]]] = [
    ("rules", "creature_types", "tr_creature_types_enforce_immutable", ["ruleset_version_id"]),
    ("rules", "languages", "tr_languages_enforce_immutable", ["ruleset_version_id"]),
    ("rules", "feats", "tr_feats_enforce_immutable", ["ruleset_version_id"]),
]


def upgrade() -> None:
    """Apply the migration."""

    for schema, table, trigger_name, columns in PROTECTED:
        args = ", ".join(f"'{c}'" for c in columns)
        op.execute(f"""
            CREATE TRIGGER {trigger_name}
            BEFORE UPDATE ON {schema}.{table}
            FOR EACH ROW EXECUTE FUNCTION core.enforce_immutable_columns({args});
        """)


def downgrade() -> None:
    """Revert the migration."""

    for schema, table, trigger_name, _columns in reversed(PROTECTED):
        op.execute(f"DROP TRIGGER IF EXISTS {trigger_name} ON {schema}.{table};")
