"""Edition-neutral ruleset family display data

Revision ID: 034_ruleset_family_neutral
Revises: 033_rules_identity_immutable
Create Date: 2026-08-02 22:45:00.000000

Purpose:
    Corrective revision (PHASE4_REMAINING_ISSUES.md §5). Revision 024
    renamed the seeded family's *code* from "dnd5e_2024" to the
    edition-neutral "dnd5e", but its display_name ("D&D 5e (2024)") and
    description ("The 2024 revision of the fifth-edition rules.") still
    named the 2024 edition at the family level — the exact double
    modeling revision 024 otherwise fixed, just left in two more columns.
    revision 022 itself is not touched (forward-only; already applied): this
    revision UPDATEs the row it seeded, the same pattern 024 used for the
    code rename.

    "2024" now lives in exactly one place: rules.ruleset_versions
    .version_label, whose own description takes the edition-specific text
    the family used to carry.

Forward migration:
    - rules.rulesets: display_name 'D&D 5e (2024)' -> 'D&D 5e', description
      -> a family-level (edition-spanning) description, for code = 'dnd5e'
    - rules.ruleset_versions: description -> the edition-specific text that
      used to live on the family row, for the '2024' version of 'dnd5e'

Rollback:
    Supported. Restores both original strings on the same rows.

Data implications:
    Updates the single ruleset and ruleset_version row revision 022 seeded
    (by code/version_label, not by any hardcoded id) and nothing else.

Locking considerations:
    Two single-row UPDATEs.

See: PHASE4_REMAINING_ISSUES.md §5
     database/migrations/versions/022_seed_initial_ruleset.py
     database/migrations/versions/024_campaign_ruleset_version.py
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "034_ruleset_family_neutral"
down_revision = "033_rules_identity_immutable"
branch_labels = None
depends_on = None

FAMILY_DISPLAY_NAME = "D&D 5e"
FAMILY_DESCRIPTION = (
    "The fifth-edition Dungeons & Dragons ruleset family, spanning multiple published "
    "editions (e.g. 2014, 2024)."
)
VERSION_DESCRIPTION = "The 2024 revision of the fifth-edition rules."

OLD_FAMILY_DISPLAY_NAME = "D&D 5e (2024)"
OLD_FAMILY_DESCRIPTION = "The 2024 revision of the fifth-edition rules."
OLD_VERSION_DESCRIPTION = "Initial seeded content."


def upgrade() -> None:
    """Apply the migration."""

    op.execute(f"""
        UPDATE rules.rulesets
        SET display_name = '{FAMILY_DISPLAY_NAME}', description = '{FAMILY_DESCRIPTION}'
        WHERE code = 'dnd5e';
    """)
    op.execute(f"""
        UPDATE rules.ruleset_versions rv
        SET description = '{VERSION_DESCRIPTION}'
        FROM rules.rulesets r
        WHERE rv.ruleset_id = r.ruleset_id AND r.code = 'dnd5e' AND rv.version_label = '2024';
    """)
    op.execute("""
        COMMENT ON TABLE rules.rulesets IS
        'A named, edition-neutral rule-system family (e.g. "D&D 5e") — a specific '
        'edition or revision is recorded on rules.ruleset_versions.version_label and '
        'description, not here. Homebrew rulesets are ordinary rows here with their own '
        'source and canon status (docs/PLAN.md §6.2) — not a separate structure.';
    """)


def downgrade() -> None:
    """Revert the migration."""

    op.execute("""
        COMMENT ON TABLE rules.rulesets IS
        'A named rule system (e.g. "D&D 5e (2024)"). Homebrew rulesets are ordinary rows '
        'here with their own source and canon status (docs/PLAN.md §6.2) — not a separate '
        'structure.';
    """)
    op.execute(f"""
        UPDATE rules.ruleset_versions rv
        SET description = '{OLD_VERSION_DESCRIPTION}'
        FROM rules.rulesets r
        WHERE rv.ruleset_id = r.ruleset_id AND r.code = 'dnd5e' AND rv.version_label = '2024';
    """)
    op.execute(f"""
        UPDATE rules.rulesets
        SET display_name = '{OLD_FAMILY_DISPLAY_NAME}', description = '{OLD_FAMILY_DESCRIPTION}'
        WHERE code = 'dnd5e';
    """)
