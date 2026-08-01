"""Worlds, entity types, entities, sources, and centralized subtype enforcement

Revision ID: 004_worlds_and_entities
Revises: 003_core_lookups_and_security
Create Date: 2026-08-01 16:00:00.000000

Purpose:
    The structural heart of Phase 2 (docs/PLAN.md §23). Creates the world
    container, the entity type registry, the class-table-inheritance root
    `core.entities`, and the provenance table every authored record points at.

    Also adds core.enforce_entity_subtype(), the single centralized mechanism
    for the invariant in docs/DATABASE_CONVENTIONS.md §7.4 and invariant 1-2
    of docs/architecture/DATABASE_MODEL.md §21. No subtype tables exist yet —
    the first arrive in Phase 4 — so this revision builds and tests the
    mechanism against a synthetic subtype rather than a real one. Phase 2's
    exit criteria say so explicitly.

Forward migration:
    - core.worlds — the persistent setting container
    - core.entity_types — the allowed entity type hierarchy, self-referencing
    - core.sources — provenance for authored and imported facts (§4.5)
    - core.entities — stable identity for important world objects (§5.3)
    - core.enforce_entity_subtype() trigger function (§7.4)

Rollback:
    Supported. Drops in FK-dependency order, then the trigger function.

Data implications:
    Creates no rows. core.entity_types is deliberately left unseeded — see the
    note in section 2.

Locking considerations:
    None. All tables are new and empty.

See: docs/PLAN.md §4.3 (foundation tables), §4.5 (provenance), §5.1 (worlds)
     docs/architecture/DATABASE_MODEL.md §5, §21
     docs/DATABASE_CONVENTIONS.md §7 (inheritance), §10 (common columns)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "004_worlds_and_entities"
down_revision = "003_core_lookups_and_security"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    # ==========================================================================
    # 1. core.worlds
    # ==========================================================================
    # DATABASE_MODEL.md §5.1 also lists default_calendar_id and
    # default_ruleset_id. Both are deliberately omitted here rather than added
    # as unconstrained UUID columns: core.calendars arrives later in Phase 2
    # and rules.rulesets in Phase 4, and a UUID column with no foreign key
    # behind it is exactly the kind of thing that quietly accumulates invalid
    # references. Each is added, with its constraint, by the revision that
    # creates the table it points at.
    op.execute("""
        CREATE TABLE core.worlds (
            world_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name                 TEXT NOT NULL,
            slug                 TEXT NOT NULL,
            description          TEXT,
            lifecycle_status_id  UUID NOT NULL
                                 REFERENCES core.lifecycle_statuses(lifecycle_status_id)
                                 ON DELETE RESTRICT,
            created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ux_worlds_slug UNIQUE (slug),
            CONSTRAINT ck_worlds_slug_format CHECK (slug ~ '^[a-z][a-z0-9-]*$'),
            CONSTRAINT ck_worlds_name_length CHECK (char_length(name) BETWEEN 1 AND 200)
        );
    """)
    op.execute("""
        COMMENT ON TABLE core.worlds IS
        'A persistent fictional setting. Owns entity definitions, calendars, and '
        'timelines; outlives any individual campaign.';
    """)
    op.execute("""
        COMMENT ON COLUMN core.worlds.slug IS
        'Stable URL-safe identifier. Distinct from name, which may be renamed freely.';
    """)
    op.execute("""
        CREATE TRIGGER tr_worlds_set_updated_at
        BEFORE UPDATE ON core.worlds
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute("CREATE INDEX ix_worlds_lifecycle_status_id ON core.worlds (lifecycle_status_id);")

    # ==========================================================================
    # 2. core.entity_types
    # ==========================================================================
    # Deliberately unseeded. docs/PLAN.md §4.4 specifies seeding the canon
    # statuses and says nothing about entity types, and the inheritance tree in
    # §2.2 names subtype tables that do not exist until Phases 4, 5, and 9.
    # Seeding them now would forward-declare rows pointing at absent tables and
    # invite drift when those phases land. Each phase registers the types it
    # actually builds.
    op.execute("""
        CREATE TABLE core.entity_types (
            entity_type_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            code                   TEXT NOT NULL,
            display_name           TEXT NOT NULL,
            description            TEXT,
            parent_entity_type_id  UUID
                                   REFERENCES core.entity_types(entity_type_id)
                                   ON DELETE RESTRICT,
            required_subtype_table TEXT,
            is_abstract            BOOLEAN NOT NULL DEFAULT false,
            created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ux_entity_types_code UNIQUE (code),
            CONSTRAINT ck_entity_types_code_format CHECK (code ~ '^[a-z][a-z0-9_]*$'),
            CONSTRAINT ck_entity_types_not_own_parent
                CHECK (parent_entity_type_id IS DISTINCT FROM entity_type_id),
            CONSTRAINT ck_entity_types_subtype_table_qualified
                CHECK (
                    required_subtype_table IS NULL
                    OR required_subtype_table ~ '^[a-z][a-z0-9_]*\\.[a-z][a-z0-9_]*$'
                )
        );
    """)
    op.execute("""
        COMMENT ON TABLE core.entity_types IS
        'The allowed entity type hierarchy. Each phase registers the types it '
        'builds; rows are not seeded ahead of the subtype tables they name.';
    """)
    op.execute("""
        COMMENT ON COLUMN core.entity_types.required_subtype_table IS
        'Schema-qualified subtype table an entity of this type must have a row in, '
        'e.g. "character.npcs". NULL for types with no subtype table. Enforced by '
        'core.enforce_entity_subtype().';
    """)
    op.execute("""
        COMMENT ON COLUMN core.entity_types.is_abstract IS
        'True when no entity may be created with this type directly — it exists only '
        'as a parent of concrete types.';
    """)
    op.execute("""
        CREATE TRIGGER tr_entity_types_set_updated_at
        BEFORE UPDATE ON core.entity_types
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute(
        "CREATE INDEX ix_entity_types_parent_entity_type_id "
        "ON core.entity_types (parent_entity_type_id);"
    )

    # ==========================================================================
    # 3. core.sources
    # ==========================================================================
    op.execute("""
        CREATE TABLE core.sources (
            source_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            world_id            UUID
                                REFERENCES core.worlds(world_id) ON DELETE CASCADE,
            source_type_id      UUID NOT NULL
                                REFERENCES core.source_types(source_type_id)
                                ON DELETE RESTRICT,
            title               TEXT NOT NULL,
            reference           TEXT,
            description         TEXT,
            created_by_user_id  UUID REFERENCES security.users(user_id) ON DELETE SET NULL,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_sources_title_length CHECK (char_length(title) BETWEEN 1 AND 500)
        );
    """)
    op.execute("""
        COMMENT ON TABLE core.sources IS
        'Where an authored or imported fact came from. Every meaningful authored '
        'record should reference one where practical (docs/PLAN.md §4.5).';
    """)
    op.execute("""
        COMMENT ON COLUMN core.sources.world_id IS
        'NULL for sources that are not world-specific, such as a published rulebook '
        'shared across every world.';
    """)
    op.execute("""
        COMMENT ON COLUMN core.sources.reference IS
        'Locator within the source — page number, URL, message id, timestamp.';
    """)
    op.execute("""
        CREATE TRIGGER tr_sources_set_updated_at
        BEFORE UPDATE ON core.sources
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute("CREATE INDEX ix_sources_world_id ON core.sources (world_id);")
    op.execute("CREATE INDEX ix_sources_source_type_id ON core.sources (source_type_id);")
    op.execute("CREATE INDEX ix_sources_created_by_user_id ON core.sources (created_by_user_id);")

    # ==========================================================================
    # 4. core.entities
    # ==========================================================================
    # The class-table inheritance root (§7.1). Subtype tables take this table's
    # entity_id as their own primary key — they never generate a new UUID.
    #
    # ON DELETE RESTRICT against worlds and entity_types is deliberate: entities
    # are archived, not deleted (rule 9 in CLAUDE.md), so a cascade from either
    # parent would be a silent mass deletion of canon.
    op.execute("""
        CREATE TABLE core.entities (
            entity_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            world_id             UUID NOT NULL
                                 REFERENCES core.worlds(world_id) ON DELETE RESTRICT,
            entity_type_id       UUID NOT NULL
                                 REFERENCES core.entity_types(entity_type_id)
                                 ON DELETE RESTRICT,
            canonical_name       TEXT NOT NULL,
            summary              TEXT,
            canon_status_id      UUID NOT NULL
                                 REFERENCES core.canon_statuses(canon_status_id)
                                 ON DELETE RESTRICT,
            lifecycle_status_id  UUID NOT NULL
                                 REFERENCES core.lifecycle_statuses(lifecycle_status_id)
                                 ON DELETE RESTRICT,
            source_id            UUID REFERENCES core.sources(source_id) ON DELETE SET NULL,
            created_by_user_id   UUID REFERENCES security.users(user_id) ON DELETE SET NULL,
            created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
            archived_at          TIMESTAMPTZ,
            CONSTRAINT ck_entities_canonical_name_length
                CHECK (char_length(canonical_name) BETWEEN 1 AND 500)
        );
    """)
    op.execute("""
        COMMENT ON TABLE core.entities IS
        'Stable identity for important world objects, and the root of the class-table '
        'inheritance chain. Definition only — what an entity IS. What is currently true '
        'about it in a timeline lives in campaign state, not here.';
    """)
    op.execute("""
        COMMENT ON COLUMN core.entities.archived_at IS
        'Set when the entity is archived. Persistent world entities are archived rather '
        'than deleted (docs/ENTITY_LIFECYCLE.md §12).';
    """)
    op.execute("""
        COMMENT ON COLUMN core.entities.summary IS
        'Short human-readable description. A derived, revisable convenience field — not '
        'authoritative world data.';
    """)
    op.execute("""
        CREATE TRIGGER tr_entities_set_updated_at
        BEFORE UPDATE ON core.entities
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    for column in (
        "world_id",
        "entity_type_id",
        "canon_status_id",
        "lifecycle_status_id",
        "source_id",
        "created_by_user_id",
    ):
        op.execute(f"CREATE INDEX ix_entities_{column} ON core.entities ({column});")

    # Entities are looked up by name within a world constantly; this is the one
    # composite index worth having before there is query evidence (§33.1).
    op.execute("""
        CREATE INDEX ix_entities_world_id_canonical_name
        ON core.entities (world_id, canonical_name);
    """)

    # ==========================================================================
    # 5. Centralized subtype enforcement
    # ==========================================================================
    # DATABASE_CONVENTIONS.md §7.4 requires validating that
    # core.entities.entity_type_id matches the subtype row, and explicitly asks
    # for a maintainable centralized solution rather than one bespoke trigger
    # per subtype. This is that: ONE function, attached to each subtype table as
    # it is created, taking the subtype's primary-key column name as an
    # argument.
    #
    # The match is against the type's ANCESTRY, not just its own row. An entity
    # of type `npc` has rows in character.characters and character.npcs, and the
    # characters table is named by the parent type — so walking up the
    # parent_entity_type_id chain is what makes a multi-level chain valid.
    #
    # No subtype table exists yet (the first arrive in Phase 4), so this is
    # exercised by tests against a synthetic subtype table rather than a real
    # one. Attach it in the revision that creates each subtype table:
    #
    #   CREATE TRIGGER tr_npcs_enforce_subtype
    #   AFTER INSERT OR UPDATE ON character.npcs
    #   FOR EACH ROW EXECUTE FUNCTION core.enforce_entity_subtype('npc_id');
    op.execute("""
        CREATE OR REPLACE FUNCTION core.enforce_entity_subtype()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_pk_column      TEXT := TG_ARGV[0];
            v_entity_id      UUID;
            v_this_table     TEXT := TG_TABLE_SCHEMA || '.' || TG_TABLE_NAME;
            v_entity_type    TEXT;
            v_matched        BOOLEAN;
        BEGIN
            v_entity_id := (to_jsonb(NEW) ->> v_pk_column)::uuid;

            IF v_entity_id IS NULL THEN
                RAISE EXCEPTION
                    'Subtype row in % has no value for primary-key column %',
                    v_this_table, v_pk_column;
            END IF;

            SELECT et.code INTO v_entity_type
            FROM core.entities e
            JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id
            WHERE e.entity_id = v_entity_id;

            IF v_entity_type IS NULL THEN
                RAISE EXCEPTION
                    'Subtype row %.% = % has no matching core.entities row',
                    v_this_table, v_pk_column, v_entity_id;
            END IF;

            -- Walk the entity type ancestry looking for one that names this table.
            WITH RECURSIVE ancestry AS (
                SELECT et.entity_type_id, et.parent_entity_type_id, et.required_subtype_table
                FROM core.entities e
                JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id
                WHERE e.entity_id = v_entity_id
                UNION ALL
                SELECT p.entity_type_id, p.parent_entity_type_id, p.required_subtype_table
                FROM core.entity_types p
                JOIN ancestry a ON a.parent_entity_type_id = p.entity_type_id
            )
            SELECT EXISTS (
                SELECT 1 FROM ancestry WHERE required_subtype_table = v_this_table
            ) INTO v_matched;

            IF NOT v_matched THEN
                RAISE EXCEPTION
                    'Entity % is of type %, which does not require a row in %',
                    v_entity_id, v_entity_type, v_this_table
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION core.enforce_entity_subtype() IS
        'Trigger function enforcing that a subtype row belongs to an entity whose type '
        '(or an ancestor of it) requires this table. Attach to each subtype table with '
        'the subtype primary-key column name as the trigger argument. See conventions §7.4.';
    """)


def downgrade() -> None:
    """Revert the migration."""

    op.execute("DROP FUNCTION IF EXISTS core.enforce_entity_subtype();")

    # FK dependency order: entities references everything; sources references worlds.
    op.execute("DROP TABLE IF EXISTS core.entities;")
    op.execute("DROP TABLE IF EXISTS core.sources;")
    op.execute("DROP TABLE IF EXISTS core.entity_types;")
    op.execute("DROP TABLE IF EXISTS core.worlds;")
