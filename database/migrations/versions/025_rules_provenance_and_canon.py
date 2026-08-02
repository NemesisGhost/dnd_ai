"""Provenance and canon status for rule content

Revision ID: 025_rules_provenance_canon
Revises: 024_campaign_ruleset_version
Create Date: 2026-08-02 19:00:00.000000

Purpose:
    Corrective revision (Phase 4 corrections review). docs/DATABASE_CONVENTIONS.md
    §16.1-16.2 requires world-authored content to carry a canon status and
    AI-generated/imported/integration-created content to always identify a
    source; docs/architecture/DATABASE_MODEL.md §8 says homebrew rule content
    "carr[ies] the same provenance and canon-status metadata as official
    content rather than requiring separate schema." None of Phase 4's rule
    tables actually had both columns: rules.rulesets had source_id but no
    canon_status_id (its own table comment already claimed both existed —
    that comment is corrected to true by this revision rather than watered
    down, since adding the missing column is the right fix), and every
    content table (abilities, skills, species, classes, subclasses,
    features, feats, spells, conditions, creature_types, damage_types,
    languages, proficiency_types, resource_definitions) plus
    rules.ruleset_versions had neither.

    Every table gets both source_id (nullable — official Player's Handbook
    content has no single "user-submitted" source) and canon_status_id (NOT
    NULL, defaulted to 'canon' for existing rows: the seeded D&D 5e (2024)
    content from revision 022 is official published-rules content, not a
    proposal). A future homebrew ruleset can now record its author's source
    and start its content at 'draft' or 'proposed' using these same columns,
    exactly as DATABASE_MODEL.md §8 requires, with no separate schema.

Forward migration:
    - source_id, canon_status_id added to rules.ruleset_versions and every
      rule-content table
    - canon_status_id added to rules.rulesets (source_id already existed)
    - Existing rows backfilled to canon_status_id = 'canon'

Rollback:
    Supported. Drops all added columns.

Data implications:
    Backfills every existing row (the seeded D&D 5e (2024) content) to
    canon_status_id = 'canon'.

Locking considerations:
    Each table here holds at most a few dozen rows (Phase 4's seed content).
    ADD COLUMN NOT NULL requires a full rewrite in general, so this is done
    as ADD (nullable) -> UPDATE -> SET NOT NULL rather than a single
    constrained ADD COLUMN, matching the pattern used for
    campaign.campaigns.ruleset_id in revision 016.

See: docs/DATABASE_CONVENTIONS.md §16 (canon and provenance)
     docs/architecture/DATABASE_MODEL.md §8 (rules model)
     database/migrations/versions/013_rulesets.py
     database/migrations/versions/014_ruleset_content.py
     database/migrations/versions/015_ruleset_classes_and_spells.py
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "025_rules_provenance_canon"
down_revision = "024_campaign_ruleset_version"
branch_labels = None
depends_on = None

# Every rule-content table needing both columns. rules.rulesets is handled
# separately below since it already has source_id.
TABLES_NEEDING_PROVENANCE = [
    "ruleset_versions",
    "abilities",
    "species",
    "damage_types",
    "conditions",
    "creature_types",
    "languages",
    "proficiency_types",
    "resource_definitions",
    "skills",
    "classes",
    "subclasses",
    "features",
    "feats",
    "spells",
]


def _create_default_canon_status_function() -> None:
    # PostgreSQL rejects a bare subquery in a column DEFAULT ("cannot use
    # subquery in DEFAULT expression") — a STABLE SQL function wrapping the
    # same lookup is allowed and is what SET DEFAULT below actually calls.
    op.execute("""
        CREATE OR REPLACE FUNCTION rules.default_canon_status_id()
        RETURNS UUID
        LANGUAGE sql
        STABLE
        AS $$
            SELECT canon_status_id FROM core.canon_statuses WHERE code = 'canon';
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION rules.default_canon_status_id() IS
        'Resolves the canon_statuses row coded ''canon''. Used as the DEFAULT for every '
        'rule-content table''s canon_status_id column, since a bare subquery is not a '
        'valid column default in PostgreSQL.';
    """)


def _add_provenance_columns(table: str) -> None:
    op.execute(f"""
        ALTER TABLE rules.{table}
        ADD COLUMN source_id UUID REFERENCES core.sources(source_id) ON DELETE SET NULL;
    """)
    op.execute(f"""
        ALTER TABLE rules.{table}
        ADD COLUMN canon_status_id UUID
        REFERENCES core.canon_statuses(canon_status_id) ON DELETE RESTRICT;
    """)
    op.execute(f"""
        UPDATE rules.{table} SET canon_status_id = (
            SELECT canon_status_id FROM core.canon_statuses WHERE code = 'canon'
        ) WHERE canon_status_id IS NULL;
    """)
    # Defaulted to 'canon' rather than left caller-mandatory like
    # core.entities.canon_status_id: the overwhelming majority of rule content
    # is officially authored (or migration-seeded) material, and requiring
    # every future INSERT to look up and pass the status explicitly would be
    # pure friction for that common case. Homebrew/proposed content still
    # overrides this explicitly — the default narrows the common case, it
    # does not remove the column's meaning.
    op.execute(f"""
        ALTER TABLE rules.{table}
        ALTER COLUMN canon_status_id SET DEFAULT rules.default_canon_status_id();
    """)
    op.execute(f"ALTER TABLE rules.{table} ALTER COLUMN canon_status_id SET NOT NULL;")
    op.execute(
        f"CREATE INDEX ix_{table}_source_id ON rules.{table} (source_id) "
        f"WHERE source_id IS NOT NULL;"
    )
    op.execute(f"CREATE INDEX ix_{table}_canon_status_id ON rules.{table} (canon_status_id);")
    op.execute(f"""
        COMMENT ON COLUMN rules.{table}.source_id IS
        'Where this definition came from — a rulebook, a homebrew document, an import. '
        'NULL is common for official content with no single authored source record yet.';
    """)
    op.execute(f"""
        COMMENT ON COLUMN rules.{table}.canon_status_id IS
        'How authoritative this definition is. Homebrew content uses the same column, '
        'typically starting at draft/proposed rather than canon '
        '(docs/architecture/DATABASE_MODEL.md §8).';
    """)


def _drop_provenance_columns(table: str) -> None:
    op.execute(f"ALTER TABLE rules.{table} DROP COLUMN IF EXISTS canon_status_id;")
    op.execute(f"ALTER TABLE rules.{table} DROP COLUMN IF EXISTS source_id;")


def upgrade() -> None:
    """Apply the migration."""

    _create_default_canon_status_function()

    for table in TABLES_NEEDING_PROVENANCE:
        _add_provenance_columns(table)

    # rules.rulesets already has source_id (revision 013); only canon_status_id
    # is missing, closing the gap its own table comment already assumed closed.
    op.execute("""
        ALTER TABLE rules.rulesets
        ADD COLUMN canon_status_id UUID
        REFERENCES core.canon_statuses(canon_status_id) ON DELETE RESTRICT;
    """)
    op.execute("""
        UPDATE rules.rulesets SET canon_status_id = (
            SELECT canon_status_id FROM core.canon_statuses WHERE code = 'canon'
        ) WHERE canon_status_id IS NULL;
    """)
    op.execute("""
        ALTER TABLE rules.rulesets
        ALTER COLUMN canon_status_id SET DEFAULT rules.default_canon_status_id();
    """)
    op.execute("ALTER TABLE rules.rulesets ALTER COLUMN canon_status_id SET NOT NULL;")
    op.execute("CREATE INDEX ix_rulesets_canon_status_id ON rules.rulesets (canon_status_id);")
    op.execute("""
        COMMENT ON COLUMN rules.rulesets.canon_status_id IS
        'How authoritative this ruleset is. Homebrew rulesets typically start at '
        'draft/proposed rather than canon (docs/architecture/DATABASE_MODEL.md §8).';
    """)


def downgrade() -> None:
    """Revert the migration."""

    op.execute("DROP INDEX IF EXISTS rules.ix_rulesets_canon_status_id;")
    op.execute("ALTER TABLE rules.rulesets DROP COLUMN IF EXISTS canon_status_id;")

    for table in reversed(TABLES_NEEDING_PROVENANCE):
        _drop_provenance_columns(table)

    # Dropped last: every canon_status_id column's DEFAULT referenced this
    # function, so it must outlive them.
    op.execute("DROP FUNCTION IF EXISTS rules.default_canon_status_id();")
