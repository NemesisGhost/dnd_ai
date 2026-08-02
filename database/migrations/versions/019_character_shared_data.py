"""Character descriptions, languages, senses, and movement

Revision ID: 019_character_shared_data
Revises: 018_party_membership_char
Create Date: 2026-08-02 16:00:00.000000

Purpose:
    Delivers the remaining flat shared-character-data tables from
    docs/PLAN.md §7.2 that are not part of a versioned build:
    character.character_descriptions, character.character_languages,
    character.character_senses, character.character_movements.

    character.character_religious_affiliations is NOT here — it references
    world.religions, which does not exist until Phase 8. Deferred, per the
    same pattern as every other forward reference this project has made.

Forward migration:
    - character.character_descriptions (one-to-one with a character)
    - character.character_languages (many-to-many with rules.languages)
    - character.character_senses (darkvision, blindsight, ...)
    - character.character_movements (walk, fly, swim, ...)

Rollback:
    Supported. Drops all four tables.

Data implications:
    Creates no rows.

Locking considerations:
    None. All tables are new and empty.

Deferred to later phases:
    character.character_religious_affiliations — Phase 8, which builds
    world.religions.

See: docs/PLAN.md §7.2 (shared character data)
     docs/architecture/DATABASE_MODEL.md §7.1
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "019_character_shared_data"
down_revision = "018_party_membership_char"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    # ==========================================================================
    # 1. character.character_descriptions
    # ==========================================================================
    # One-to-one with a character: the primary key IS the character's own
    # UUID, same as every class-table inheritance level, even though this
    # isn't a subtype row (no entity_type/enforce_entity_subtype involvement —
    # a character does not stop being one for lacking prose).
    op.execute("""
        CREATE TABLE character.character_descriptions (
            character_id  UUID PRIMARY KEY
                         REFERENCES character.characters(character_id) ON DELETE CASCADE,
            background    TEXT,
            appearance    TEXT,
            notes         TEXT,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)
    op.execute("""
        COMMENT ON TABLE character.character_descriptions IS
        'Free-text background, appearance, and notes that do not drive mechanics '
        '(docs/PLAN.md §7.2). Optional: a character need not have one yet.';
    """)
    op.execute("""
        CREATE TRIGGER tr_character_descriptions_set_updated_at
        BEFORE UPDATE ON character.character_descriptions
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)

    # ==========================================================================
    # 2. character.character_languages
    # ==========================================================================
    op.execute("""
        CREATE TABLE character.character_languages (
            character_id  UUID NOT NULL
                         REFERENCES character.characters(character_id) ON DELETE CASCADE,
            language_id   UUID NOT NULL
                         REFERENCES rules.languages(language_id) ON DELETE RESTRICT,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (character_id, language_id)
        );
    """)
    op.execute("""
        COMMENT ON TABLE character.character_languages IS
        'Languages a character knows. Pure association — a character may know '
        'languages from more than one ruleset''s content.';
    """)
    op.execute(
        "CREATE INDEX ix_character_languages_language_id ON character.character_languages (language_id);"
    )

    # ==========================================================================
    # 3. character.character_senses
    # ==========================================================================
    # sense_type is free text rather than a lookup table: unlike size_category
    # (a truly fixed, universal vocabulary), senses are exactly the kind of
    # thing homebrew invents new instances of, but this project does not yet
    # have a documented rules.senses table to point at, and adding one
    # unprompted would recreate the exact PLAN/DATABASE_MODEL drift this
    # project just spent effort reconciling. Revisit if a real need for a
    # controlled sense vocabulary appears.
    op.execute("""
        CREATE TABLE character.character_senses (
            character_id  UUID NOT NULL
                         REFERENCES character.characters(character_id) ON DELETE CASCADE,
            sense_type    TEXT NOT NULL,
            range_feet    core.nonnegative_integer NOT NULL,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (character_id, sense_type),
            CONSTRAINT ck_character_senses_range_positive CHECK (range_feet > 0)
        );
    """)
    op.execute("""
        COMMENT ON TABLE character.character_senses IS
        'A special sense a character has (darkvision, blindsight, ...) and its range.';
    """)

    # ==========================================================================
    # 4. character.character_movements
    # ==========================================================================
    op.execute("""
        CREATE TABLE character.character_movements (
            character_id   UUID NOT NULL
                          REFERENCES character.characters(character_id) ON DELETE CASCADE,
            movement_type  TEXT NOT NULL,
            speed_feet     core.nonnegative_integer NOT NULL,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (character_id, movement_type),
            CONSTRAINT ck_character_movements_speed_positive CHECK (speed_feet > 0)
        );
    """)
    op.execute("""
        COMMENT ON TABLE character.character_movements IS
        'A movement mode a character has (walk, fly, swim, ...) and its speed.';
    """)


def downgrade() -> None:
    """Revert the migration."""

    op.execute("DROP TABLE IF EXISTS character.character_movements;")
    op.execute("DROP TABLE IF EXISTS character.character_senses;")
    op.execute("DROP TABLE IF EXISTS character.character_languages;")
    op.execute("DROP TABLE IF EXISTS character.character_descriptions;")
