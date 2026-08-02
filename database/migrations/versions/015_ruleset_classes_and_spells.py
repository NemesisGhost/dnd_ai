"""Ruleset classes, subclasses, features, feats, and spells

Revision ID: 015_ruleset_classes
Revises: 014_ruleset_content
Create Date: 2026-08-02 14:00:00.000000

Purpose:
    Delivers the remaining rule-content tables from docs/PLAN.md §6.1 that
    cross-reference each other rather than sharing the flat lookup shape
    revision 014 used: rules.classes, rules.subclasses, rules.features,
    rules.feats, rules.spells.

Forward migration:
    - rules.classes
    - rules.subclasses (belongs to a class)
    - rules.features (may belong to a class, subclass, and/or species)
    - rules.feats
    - rules.spells

Rollback:
    Supported. Drops all five tables in dependency order.

Data implications:
    Creates no rows. Seeded once alongside the rest of the initial ruleset.

Locking considerations:
    None. All tables are new and empty.

See: docs/PLAN.md §6.1 (ruleset separation)
     docs/architecture/DATABASE_MODEL.md §8 (rules model)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "015_ruleset_classes"
down_revision = "014_ruleset_content"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    # ==========================================================================
    # 1. rules.classes
    # ==========================================================================
    op.execute("""
        CREATE TABLE rules.classes (
            class_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            ruleset_version_id  UUID NOT NULL
                                REFERENCES rules.ruleset_versions(ruleset_version_id)
                                ON DELETE CASCADE,
            code                TEXT NOT NULL,
            display_name        TEXT NOT NULL,
            description         TEXT,
            hit_die             core.nonnegative_integer NOT NULL,
            primary_ability_id  UUID REFERENCES rules.abilities(ability_id) ON DELETE RESTRICT,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ux_classes_ruleset_version_code UNIQUE (ruleset_version_id, code),
            CONSTRAINT ck_classes_code_format CHECK (code ~ '^[a-z][a-z0-9_]*$'),
            CONSTRAINT ck_classes_hit_die_positive CHECK (hit_die > 0)
        );
    """)
    op.execute("""
        COMMENT ON TABLE rules.classes IS
        'A playable class definition (Fighter, Wizard, ...). character_class_levels '
        'references this to record a character''s levels in it.';
    """)
    op.execute("""
        CREATE TRIGGER tr_classes_set_updated_at
        BEFORE UPDATE ON rules.classes
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute("CREATE INDEX ix_classes_ruleset_version_id ON rules.classes (ruleset_version_id);")
    op.execute("""
        CREATE INDEX ix_classes_primary_ability_id
        ON rules.classes (primary_ability_id)
        WHERE primary_ability_id IS NOT NULL;
    """)

    # ==========================================================================
    # 2. rules.subclasses
    # ==========================================================================
    # Scoped by class_id, not by ruleset_version_id directly: a subclass code
    # ("champion") is naturally unique within its class, not within the whole
    # ruleset. ruleset_version_id is still stored, since content queries filter
    # by version constantly, but a trigger keeps it in agreement with the
    # parent class's version rather than trusting the caller to copy it right.
    op.execute("""
        CREATE TABLE rules.subclasses (
            subclass_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            class_id            UUID NOT NULL
                                REFERENCES rules.classes(class_id) ON DELETE CASCADE,
            ruleset_version_id  UUID NOT NULL
                                REFERENCES rules.ruleset_versions(ruleset_version_id)
                                ON DELETE CASCADE,
            code                TEXT NOT NULL,
            display_name        TEXT NOT NULL,
            description         TEXT,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ux_subclasses_class_code UNIQUE (class_id, code),
            CONSTRAINT ck_subclasses_code_format CHECK (code ~ '^[a-z][a-z0-9_]*$')
        );
    """)
    op.execute("""
        COMMENT ON TABLE rules.subclasses IS
        'A specialization within a class (Champion within Fighter, ...). Unique per '
        'class, not per ruleset version — two different classes may each define their '
        'own subclass with the same code.';
    """)
    op.execute("""
        CREATE TRIGGER tr_subclasses_set_updated_at
        BEFORE UPDATE ON rules.subclasses
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute("CREATE INDEX ix_subclasses_class_id ON rules.subclasses (class_id);")
    op.execute(
        "CREATE INDEX ix_subclasses_ruleset_version_id ON rules.subclasses (ruleset_version_id);"
    )

    op.execute("""
        CREATE OR REPLACE FUNCTION rules.enforce_subclass_ruleset_version()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_class_version UUID;
        BEGIN
            SELECT ruleset_version_id INTO v_class_version
            FROM rules.classes WHERE class_id = NEW.class_id;

            IF v_class_version IS DISTINCT FROM NEW.ruleset_version_id THEN
                RAISE EXCEPTION
                    'Subclass % belongs to ruleset version %, but its class % belongs to '
                    'ruleset version %',
                    NEW.subclass_id, NEW.ruleset_version_id, NEW.class_id, v_class_version
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION rules.enforce_subclass_ruleset_version() IS
        'Keeps a subclass''s stored ruleset_version_id in agreement with its class''s.';
    """)
    op.execute("""
        CREATE TRIGGER tr_subclasses_enforce_ruleset_version
        BEFORE INSERT OR UPDATE ON rules.subclasses
        FOR EACH ROW EXECUTE FUNCTION rules.enforce_subclass_ruleset_version();
    """)

    # ==========================================================================
    # 3. rules.features
    # ==========================================================================
    # A feature may come from a class, a subclass, a species, or stand alone
    # (a generic feature granted by some other future mechanism) — the three
    # associations are independently nullable rather than mutually exclusive,
    # since which combinations are meaningful is a rules-content question, not
    # a structural one this migration should freeze.
    op.execute("""
        CREATE TABLE rules.features (
            feature_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            ruleset_version_id  UUID NOT NULL
                                REFERENCES rules.ruleset_versions(ruleset_version_id)
                                ON DELETE CASCADE,
            class_id             UUID REFERENCES rules.classes(class_id) ON DELETE CASCADE,
            subclass_id          UUID REFERENCES rules.subclasses(subclass_id) ON DELETE CASCADE,
            species_id           UUID REFERENCES rules.species(species_id) ON DELETE CASCADE,
            code                 TEXT NOT NULL,
            display_name         TEXT NOT NULL,
            description          TEXT,
            granted_at_level     core.nonnegative_integer,
            created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ux_features_ruleset_version_code UNIQUE (ruleset_version_id, code),
            CONSTRAINT ck_features_code_format CHECK (code ~ '^[a-z][a-z0-9_]*$')
        );
    """)
    op.execute("""
        COMMENT ON TABLE rules.features IS
        'A granted trait or ability — a class feature, subclass feature, or species '
        'trait. The three associations are independently nullable, not mutually '
        'exclusive: which combinations are meaningful is rules content, not structure.';
    """)
    op.execute("""
        COMMENT ON COLUMN rules.features.granted_at_level IS
        'The class or subclass level at which this feature is gained. NULL for species '
        'traits, which are not level-gated.';
    """)
    op.execute("""
        CREATE TRIGGER tr_features_set_updated_at
        BEFORE UPDATE ON rules.features
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute(
        "CREATE INDEX ix_features_ruleset_version_id ON rules.features (ruleset_version_id);"
    )
    op.execute(
        "CREATE INDEX ix_features_class_id ON rules.features (class_id) WHERE class_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_features_subclass_id ON rules.features (subclass_id) "
        "WHERE subclass_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_features_species_id ON rules.features (species_id) "
        "WHERE species_id IS NOT NULL;"
    )

    # ==========================================================================
    # 4. rules.feats
    # ==========================================================================
    op.execute("""
        CREATE TABLE rules.feats (
            feat_id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            ruleset_version_id         UUID NOT NULL
                                       REFERENCES rules.ruleset_versions(ruleset_version_id)
                                       ON DELETE CASCADE,
            code                       TEXT NOT NULL,
            display_name               TEXT NOT NULL,
            description                TEXT,
            prerequisite_description   TEXT,
            created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ux_feats_ruleset_version_code UNIQUE (ruleset_version_id, code),
            CONSTRAINT ck_feats_code_format CHECK (code ~ '^[a-z][a-z0-9_]*$')
        );
    """)
    op.execute("""
        COMMENT ON TABLE rules.feats IS
        'An optional feat a character may take. prerequisite_description is free text '
        'for now — structured, machine-checkable prerequisites are a later refinement.';
    """)
    op.execute("""
        CREATE TRIGGER tr_feats_set_updated_at
        BEFORE UPDATE ON rules.feats
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute("CREATE INDEX ix_feats_ruleset_version_id ON rules.feats (ruleset_version_id);")

    # ==========================================================================
    # 5. rules.spells
    # ==========================================================================
    # Casting time, range, and duration are free text for now, matching feats'
    # prerequisite_description: enough structure to assemble a character sheet
    # (§6's exit criterion), not a full spellcasting engine.
    op.execute("""
        CREATE TABLE rules.spells (
            spell_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            ruleset_version_id  UUID NOT NULL
                                REFERENCES rules.ruleset_versions(ruleset_version_id)
                                ON DELETE CASCADE,
            code                TEXT NOT NULL,
            display_name        TEXT NOT NULL,
            description         TEXT,
            level               core.nonnegative_integer NOT NULL,
            school              TEXT,
            casting_time        TEXT,
            range               TEXT,
            duration            TEXT,
            damage_type_id       UUID REFERENCES rules.damage_types(damage_type_id) ON DELETE RESTRICT,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ux_spells_ruleset_version_code UNIQUE (ruleset_version_id, code)
        );
    """)
    op.execute("""
        COMMENT ON TABLE rules.spells IS
        'A spell definition. level 0 is a cantrip. damage_type_id is set only for '
        'spells that deal typed damage.';
    """)
    op.execute("""
        CREATE TRIGGER tr_spells_set_updated_at
        BEFORE UPDATE ON rules.spells
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute("CREATE INDEX ix_spells_ruleset_version_id ON rules.spells (ruleset_version_id);")
    op.execute(
        "CREATE INDEX ix_spells_damage_type_id ON rules.spells (damage_type_id) "
        "WHERE damage_type_id IS NOT NULL;"
    )


def downgrade() -> None:
    """Revert the migration."""

    op.execute("DROP TABLE IF EXISTS rules.spells;")
    op.execute("DROP TABLE IF EXISTS rules.feats;")
    op.execute("DROP TABLE IF EXISTS rules.features;")
    op.execute("DROP TABLE IF EXISTS rules.subclasses;")
    op.execute("DROP FUNCTION IF EXISTS rules.enforce_subclass_ruleset_version();")
    op.execute("DROP TABLE IF EXISTS rules.classes;")
