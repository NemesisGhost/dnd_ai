"""Rulesets and ruleset versions

Revision ID: 013_rulesets
Revises: 012_entity_name_timelines
Create Date: 2026-08-02 13:00:00.000000

Purpose:
    Delivers rules.rulesets and rules.ruleset_versions (docs/PLAN.md §6.1),
    the identity and versioning layer every other rule-content table hangs
    off. Rule definitions must not be embedded directly in world instances
    (§6.1) — this is what makes "abilities", "classes", "spells", and so on
    reusable definitions rather than per-world copies.

    Homebrew uses these same tables (§6.2): a homebrew ruleset is a normal
    row here with its own source and canon status, not a parallel structure.

Forward migration:
    - rules.rulesets — the named rule system (e.g. "D&D 5e (2024)")
    - rules.ruleset_versions — versions within a ruleset; content tables
      reference a version, not a ruleset directly, since two versions of the
      same ruleset may define the same-named thing differently

Rollback:
    Supported. Drops both tables.

Data implications:
    Creates no rows. The initial ruleset is seeded once its content tables
    exist, in the revision that closes Phase 4's "first substantial seed
    content" obligation.

Locking considerations:
    None. Both tables are new and empty.

See: docs/PLAN.md §6.1 (ruleset separation), §6.2 (homebrew support)
     docs/architecture/DATABASE_MODEL.md §8 (rules model)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "013_rulesets"
down_revision = "012_entity_name_timelines"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    # ==========================================================================
    # 1. rules.rulesets
    # ==========================================================================
    op.execute("""
        CREATE TABLE rules.rulesets (
            ruleset_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            code          TEXT NOT NULL,
            display_name  TEXT NOT NULL,
            description   TEXT,
            source_id     UUID REFERENCES core.sources(source_id) ON DELETE SET NULL,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ux_rulesets_code UNIQUE (code),
            CONSTRAINT ck_rulesets_code_format CHECK (code ~ '^[a-z][a-z0-9_]*$'),
            CONSTRAINT ck_rulesets_name_length CHECK (char_length(display_name) BETWEEN 1 AND 200)
        );
    """)
    op.execute("""
        COMMENT ON TABLE rules.rulesets IS
        'A named rule system (e.g. "D&D 5e (2024)"). Homebrew rulesets are ordinary rows '
        'here with their own source and canon status (docs/PLAN.md §6.2) — not a separate '
        'structure.';
    """)
    op.execute("""
        CREATE TRIGGER tr_rulesets_set_updated_at
        BEFORE UPDATE ON rules.rulesets
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute(
        "CREATE INDEX ix_rulesets_source_id ON rules.rulesets (source_id) WHERE source_id IS NOT NULL;"
    )

    # ==========================================================================
    # 2. rules.ruleset_versions
    # ==========================================================================
    # Content tables (abilities, classes, spells, ...) reference a version, not
    # a ruleset directly: "All rule definitions must identify their ruleset
    # and version" (§6.1), because two versions of one ruleset may define the
    # same-named thing differently (a 2014 Fireball and a 2024 Fireball).
    op.execute("""
        CREATE TABLE rules.ruleset_versions (
            ruleset_version_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            ruleset_id          UUID NOT NULL
                                REFERENCES rules.rulesets(ruleset_id) ON DELETE CASCADE,
            version_label       TEXT NOT NULL,
            description         TEXT,
            is_current          BOOLEAN NOT NULL DEFAULT FALSE,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ux_ruleset_versions_ruleset_label UNIQUE (ruleset_id, version_label),
            CONSTRAINT ck_ruleset_versions_label_length
                CHECK (char_length(version_label) BETWEEN 1 AND 50)
        );
    """)
    op.execute("""
        COMMENT ON TABLE rules.ruleset_versions IS
        'A version within a ruleset. Rule-content tables reference a version rather than '
        'a bare ruleset, since two versions of the same ruleset may define the same-named '
        'thing differently.';
    """)
    op.execute("""
        COMMENT ON COLUMN rules.ruleset_versions.is_current IS
        'The version to use when none is pinned explicitly. At most one per ruleset, '
        'enforced by a partial unique index rather than a CHECK, since the rule spans rows.';
    """)
    op.execute("""
        CREATE TRIGGER tr_ruleset_versions_set_updated_at
        BEFORE UPDATE ON rules.ruleset_versions
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute(
        "CREATE INDEX ix_ruleset_versions_ruleset_id ON rules.ruleset_versions (ruleset_id);"
    )
    op.execute("""
        CREATE UNIQUE INDEX ux_ruleset_versions_one_current_per_ruleset
        ON rules.ruleset_versions (ruleset_id)
        WHERE is_current;
    """)


def downgrade() -> None:
    """Revert the migration."""

    op.execute("DROP TABLE IF EXISTS rules.ruleset_versions;")
    op.execute("DROP TABLE IF EXISTS rules.rulesets;")
