"""Entity names, name types, tags, and entity tagging

Revision ID: 005_names_and_tags
Revises: 004_worlds_and_entities
Create Date: 2026-08-01 17:00:00.000000

Purpose:
    Continues Phase 2 (docs/PLAN.md §23) with the naming and tagging tables
    from §4.3: core.name_types, core.entity_names, core.tags, core.entity_tags.

Forward migration:
    - core.name_types — lookup, seeded from docs/DOMAIN_MODEL.md §4.4
    - core.entity_names — alternate and historical names, at most one primary
      per entity (partial unique index)
    - core.tags — platform-wide or world-owned, per conventions §11.3
    - core.entity_tags — the join, with a trigger keeping world-owned tags from
      being applied across worlds

Rollback:
    Supported. Drops in FK-dependency order, then the trigger function.

Data implications:
    Seeds ten name types. No other rows created.

Locking considerations:
    None. All tables are new and empty.

See: docs/DOMAIN_MODEL.md §4.4 (name types)
     docs/architecture/DATABASE_MODEL.md §5.4
     docs/DATABASE_CONVENTIONS.md §11.3 (extensible vs world-owned lookups)
"""

from alembic import op

from dnd_ai.persistence.seeds import apply_seed

# revision identifiers, used by Alembic.
revision = "005_names_and_tags"
down_revision = "004_worlds_and_entities"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    # ==========================================================================
    # 1. core.name_types
    # ==========================================================================
    op.execute("""
        CREATE TABLE core.name_types (
            name_type_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            code          TEXT NOT NULL,
            display_name  TEXT NOT NULL,
            description   TEXT,
            sort_order    core.nonnegative_integer NOT NULL DEFAULT 0,
            is_active     BOOLEAN NOT NULL DEFAULT true,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ux_name_types_code UNIQUE (code),
            CONSTRAINT ck_name_types_code_format CHECK (code ~ '^[a-z][a-z0-9_]*$')
        );
    """)
    op.execute("""
        COMMENT ON TABLE core.name_types IS
        'Kinds of alternate or historical name an entity can carry — see '
        'docs/DOMAIN_MODEL.md §4.4.';
    """)
    op.execute("""
        COMMENT ON COLUMN core.name_types.code IS
        'Stable machine-readable identifier. Application logic may reference '
        'codes, but foreign keys use IDs (conventions §11.1).';
    """)
    op.execute("""
        CREATE TRIGGER tr_name_types_set_updated_at
        BEFORE UPDATE ON core.name_types
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)

    # ==========================================================================
    # 2. core.entity_names
    # ==========================================================================
    # DATABASE_MODEL.md §5.4 notes names may optionally be timeline-scoped, for
    # a name that only exists after some historical event. That needs
    # campaign.timelines (Phase 3) and core.world_times (later this phase), so
    # the scoping columns are added by the revision that introduces them rather
    # than as unconstrained UUIDs now.
    op.execute("""
        CREATE TABLE core.entity_names (
            entity_name_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            entity_id       UUID NOT NULL
                            REFERENCES core.entities(entity_id) ON DELETE CASCADE,
            name_type_id    UUID NOT NULL
                            REFERENCES core.name_types(name_type_id) ON DELETE RESTRICT,
            name            TEXT NOT NULL,
            language        TEXT,
            notes           TEXT,
            is_primary      BOOLEAN NOT NULL DEFAULT false,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_entity_names_name_length
                CHECK (char_length(name) BETWEEN 1 AND 500)
        );
    """)
    op.execute("""
        COMMENT ON TABLE core.entity_names IS
        'Alternate and historical names for an entity. core.entities.canonical_name '
        'stays the single denormalized display name; this table holds everything else.';
    """)
    op.execute("""
        COMMENT ON COLUMN core.entity_names.is_primary IS
        'At most one per entity, enforced by a partial unique index. Marks the name to '
        'prefer when several of the same type exist.';
    """)
    op.execute("""
        COMMENT ON COLUMN core.entity_names.language IS
        'In-world or real-world language tag, for translated names. NULL when not applicable.';
    """)
    op.execute("""
        CREATE TRIGGER tr_entity_names_set_updated_at
        BEFORE UPDATE ON core.entity_names
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute("CREATE INDEX ix_entity_names_entity_id ON core.entity_names (entity_id);")
    op.execute("CREATE INDEX ix_entity_names_name_type_id ON core.entity_names (name_type_id);")

    # A partial unique index, not a plain UNIQUE: only one row per entity may be
    # primary, but any number may be non-primary.
    op.execute("""
        CREATE UNIQUE INDEX ux_entity_names_one_primary_per_entity
        ON core.entity_names (entity_id)
        WHERE is_primary;
    """)

    # Names are searched by text constantly; pg_trgm is enabled in 001 for this.
    op.execute("""
        CREATE INDEX ix_entity_names_name_trgm
        ON core.entity_names USING gin (name gin_trgm_ops);
    """)

    # ==========================================================================
    # 3. core.tags
    # ==========================================================================
    # Conventions §11.3 separates platform lookups from world-owned definitions.
    # Tags are both: world_id NULL is a platform tag available everywhere, and a
    # set world_id is a tag that world defines for itself.
    op.execute("""
        CREATE TABLE core.tags (
            tag_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            world_id      UUID REFERENCES core.worlds(world_id) ON DELETE CASCADE,
            code          TEXT NOT NULL,
            display_name  TEXT NOT NULL,
            description   TEXT,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_tags_code_format CHECK (code ~ '^[a-z][a-z0-9_]*$')
        );
    """)
    op.execute("""
        COMMENT ON TABLE core.tags IS
        'Free-form classification. world_id NULL means a platform tag usable by every '
        'world; a set world_id means the world owns it (conventions §11.3).';
    """)
    op.execute("""
        CREATE TRIGGER tr_tags_set_updated_at
        BEFORE UPDATE ON core.tags
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute("CREATE INDEX ix_tags_world_id ON core.tags (world_id);")

    # Two partial unique indexes rather than one UNIQUE (world_id, code): SQL
    # treats NULLs as distinct, so a plain constraint would happily allow several
    # platform tags sharing a code.
    op.execute("""
        CREATE UNIQUE INDEX ux_tags_platform_code
        ON core.tags (code)
        WHERE world_id IS NULL;
    """)
    op.execute("""
        CREATE UNIQUE INDEX ux_tags_world_code
        ON core.tags (world_id, code)
        WHERE world_id IS NOT NULL;
    """)

    # ==========================================================================
    # 4. core.entity_tags
    # ==========================================================================
    op.execute("""
        CREATE TABLE core.entity_tags (
            entity_id         UUID NOT NULL
                              REFERENCES core.entities(entity_id) ON DELETE CASCADE,
            tag_id            UUID NOT NULL
                              REFERENCES core.tags(tag_id) ON DELETE CASCADE,
            tagged_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
            tagged_by_user_id UUID REFERENCES security.users(user_id) ON DELETE SET NULL,
            PRIMARY KEY (entity_id, tag_id)
        );
    """)
    op.execute("""
        COMMENT ON TABLE core.entity_tags IS
        'Applies a tag to an entity. A world-owned tag may only be applied to entities '
        'in that world — enforced by core.enforce_entity_tag_world().';
    """)
    op.execute("CREATE INDEX ix_entity_tags_tag_id ON core.entity_tags (tag_id);")
    op.execute(
        "CREATE INDEX ix_entity_tags_tagged_by_user_id ON core.entity_tags (tagged_by_user_id);"
    )

    # DATABASE_MODEL.md §21 invariants 3-5 all say the same thing in different
    # places: references must not cross worlds. A world-owned tag applied to
    # another world's entity is the same error, and cannot be expressed as a
    # foreign key because tags.world_id is nullable for platform tags.
    op.execute("""
        CREATE OR REPLACE FUNCTION core.enforce_entity_tag_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_tag_world    UUID;
            v_entity_world UUID;
        BEGIN
            SELECT world_id INTO v_tag_world FROM core.tags WHERE tag_id = NEW.tag_id;

            -- Platform tags (NULL world) apply anywhere.
            IF v_tag_world IS NULL THEN
                RETURN NEW;
            END IF;

            SELECT world_id INTO v_entity_world
            FROM core.entities WHERE entity_id = NEW.entity_id;

            IF v_entity_world IS DISTINCT FROM v_tag_world THEN
                RAISE EXCEPTION
                    'Tag % belongs to world %, but entity % belongs to world %',
                    NEW.tag_id, v_tag_world, NEW.entity_id, v_entity_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION core.enforce_entity_tag_world() IS
        'Keeps a world-owned tag from being applied to an entity in a different world. '
        'Platform tags (tags.world_id IS NULL) are unrestricted.';
    """)
    op.execute("""
        CREATE TRIGGER tr_entity_tags_enforce_world
        BEFORE INSERT OR UPDATE ON core.entity_tags
        FOR EACH ROW EXECUTE FUNCTION core.enforce_entity_tag_world();
    """)

    # ==========================================================================
    # 5. Seeds
    # ==========================================================================
    apply_seed(op, "core", "name_types")


def downgrade() -> None:
    """Revert the migration."""

    op.execute("DROP TABLE IF EXISTS core.entity_tags;")
    op.execute("DROP FUNCTION IF EXISTS core.enforce_entity_tag_world();")
    op.execute("DROP TABLE IF EXISTS core.tags;")
    op.execute("DROP TABLE IF EXISTS core.entity_names;")
    op.execute("DROP TABLE IF EXISTS core.name_types;")
