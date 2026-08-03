"""Parent-side entity-type-change protection

Revision ID: 048_entity_type_change_protect
Revises: 047_realm_conditional_routes
Create Date: 2026-08-03 12:00:00.000000

Purpose:
    Phase 5 exit review finding: core.enforce_entity_subtype() (revision 004)
    validates from the *subtype* side — INSERT or UPDATE on e.g.
    world.dungeons checks that the owning entity's type requires that table.
    Nothing validates the reverse direction: UPDATE core.entities SET
    entity_type_id = <region's type> WHERE entity_id = <a dungeon> touches
    only core.entities, so no subtype-table trigger fires, and a
    world.dungeons row (with world.dungeon_areas rows depending on it via
    world.enforce_dungeon_area_parent_dungeon()'s "parent must be
    dungeon-typed" rule) is left behind describing an entity that no longer
    claims to be a dungeon at all. The same gap applies to every other
    subtype registered so far (character/npc/player_character, location/
    settlement/building, knowledge_item) — not just dungeons — since
    core.entities.entity_type_id is generic and none of those subtypes'
    tables re-validate on a parent-side change either.

    Fixed once, generically, on the parent side: core.entity_types gains an
    explicit required_subtype_pk_column (the subtype table's primary-key
    column name — e.g. 'dungeon_id' for 'world.dungeons'), paired with
    required_subtype_table the same way every entity-type row already pairs
    a code with a display_name. This is deliberately a stored column rather
    than derived by stripping a trailing "s" from the table name: the schema
    has no rule that subtype tables are named by regular pluralization
    (nothing enforces it, and knowledge.knowledge_items would still work by
    luck rather than rule), and DATABASE_CONVENTIONS.md's own anti-pattern
    guidance is to store a fact explicitly rather than infer it by string
    surgery. A new BEFORE UPDATE OF entity_type_id trigger on core.entities
    walks both the OLD and NEW type's ancestry (the same recursive-ancestry
    shape core.enforce_entity_subtype() already uses) and rejects the change
    if any subtype table required by the OLD ancestry but not the NEW one
    still has a row for this entity — "reject the incompatible type change
    while a subtype row exists" rather than stranding it, per the review's
    stated preference. Because this walks entity_types data rather than
    naming any specific table, it automatically covers dungeons, every other
    Phase 5 subtype, and every Phase 4 character subtype in one mechanism,
    and will keep covering whatever subtype tables later phases register —
    provided they set required_subtype_pk_column when they do (documented in
    DATABASE_CONVENTIONS.md §7.4 in this same change).

    A type change that does NOT strand any existing subtype row (e.g.
    correcting a bare 'location'-typed entity's type before any subtype row
    exists) remains allowed — this is not a blanket immutability lock like
    core.enforce_immutable_columns() applies to world_id elsewhere, because
    entity_type_id legitimately needs to be correctable before a subtype
    row is attached.

    core.enforce_entity_type_change() alone is not sufficient for dungeons
    specifically. §7.5 permits deleting a subtype row (world.dungeons is not
    protected against DELETE), and doing so first removes the very thing the
    generic check looks for — after that, changing the entity's type away
    from 'dungeon' would sail through the generic trigger even though
    world.dungeon_areas rows still point at it via parent_location_id and
    still depend on world.enforce_dungeon_area_parent_dungeon() (revision
    039) finding a dungeon-typed parent. This is the "existing child areas
    ... cannot be stranded" case called out explicitly in review, and it is
    a genuinely different failure mode from the generic one (it survives
    even once the subtype row itself is gone), so it gets its own dedicated
    check — world.enforce_dungeon_type_change_preserves_areas() — the same
    way dungeon-area parentage already has its own dedicated trigger rather
    than a generic one (revision 039's world.enforce_dungeon_area_parent_
    dungeon(), revision 044's _on_update() counterpart). A review of every
    other Phase 4/5 subtype relationship found no equivalent "a child row's
    validity depends on its parent *remaining* a specific entity type" rule
    — dungeon_area's dependency on its parent being dungeon-typed is the
    only one of its kind in the schema as of this revision, so no further
    dedicated trigger is added here.

Forward migration:
    - core.entity_types.required_subtype_pk_column TEXT, paired with
      required_subtype_table via a CHECK (both NULL or both set) and a
      format CHECK matching the existing code-format rule
    - Backfilled for all nine existing subtyped rows (character, npc,
      player_character, location, settlement, building, dungeon,
      dungeon_area, knowledge_item)
    - core.enforce_entity_type_change(), a BEFORE UPDATE OF entity_type_id
      trigger on core.entities, attached as tr_entities_enforce_type_change
    - world.enforce_dungeon_type_change_preserves_areas(), a second BEFORE
      UPDATE OF entity_type_id trigger on core.entities, attached as
      tr_entities_enforce_dungeon_type_change: specifically blocks moving an
      entity away from the 'dungeon' type while it still has
      world.dungeon_areas children

Rollback:
    Supported. Drops both triggers and both functions, then the column (and
    its CHECK constraints, dropped implicitly with it).

Data implications:
    Backfills nine existing core.entity_types rows. No core.entities rows
    are touched.

Locking considerations:
    ADD COLUMN with no default and backfill-by-UPDATE on a nine-row table is
    negligible. No table this touches is large.

See: docs/DATABASE_CONVENTIONS.md §7.4 (subtype consistency)
     database/migrations/versions/004_worlds_and_entities.py
     (core.enforce_entity_subtype(), the subtype-side half of this invariant)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "048_entity_type_change_protect"
down_revision = "047_realm_conditional_routes"
branch_labels = None
depends_on = None

# (entity_type code, subtype primary-key column)
SUBTYPE_PK_COLUMNS: list[tuple[str, str]] = [
    ("character", "character_id"),
    ("npc", "npc_id"),
    ("player_character", "player_character_id"),
    ("location", "location_id"),
    ("settlement", "settlement_id"),
    ("building", "building_id"),
    ("dungeon", "dungeon_id"),
    ("dungeon_area", "dungeon_area_id"),
    ("knowledge_item", "knowledge_item_id"),
]


def upgrade() -> None:
    """Apply the migration."""

    op.execute("ALTER TABLE core.entity_types ADD COLUMN required_subtype_pk_column TEXT;")
    op.execute("""
        COMMENT ON COLUMN core.entity_types.required_subtype_pk_column IS
        'Primary-key column name of required_subtype_table (e.g. "dungeon_id" for '
        '"world.dungeons"). Set together with required_subtype_table — never one '
        'without the other. Lets core.enforce_entity_type_change() check for an '
        'existing subtype row without guessing a column name from the table name.';
    """)

    # Backfill before adding the pairing CHECK below — every existing row
    # with a required_subtype_table set currently has a NULL pk column, which
    # would violate that constraint if added first.
    for code, pk_column in SUBTYPE_PK_COLUMNS:
        op.execute(f"""
            UPDATE core.entity_types
            SET required_subtype_pk_column = '{pk_column}'
            WHERE code = '{code}';
        """)

    op.execute("""
        ALTER TABLE core.entity_types
        ADD CONSTRAINT ck_entity_types_subtype_pk_column_paired
            CHECK ((required_subtype_table IS NULL) = (required_subtype_pk_column IS NULL));
    """)
    op.execute("""
        ALTER TABLE core.entity_types
        ADD CONSTRAINT ck_entity_types_subtype_pk_column_format
            CHECK (required_subtype_pk_column ~ '^[a-z][a-z0-9_]*$');
    """)

    # ==========================================================================
    # Parent-side enforcement: reject an entity_type_id change that would
    # strand an existing subtype row.
    # ==========================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION core.enforce_entity_type_change()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_orphan     RECORD;
            v_exists     BOOLEAN;
        BEGIN
            IF OLD.entity_type_id IS NOT DISTINCT FROM NEW.entity_type_id THEN
                RETURN NEW;
            END IF;

            FOR v_orphan IN
                WITH RECURSIVE old_ancestry AS (
                    SELECT entity_type_id, parent_entity_type_id, required_subtype_table,
                           required_subtype_pk_column, 1 AS depth
                    FROM core.entity_types WHERE entity_type_id = OLD.entity_type_id
                    UNION ALL
                    SELECT p.entity_type_id, p.parent_entity_type_id, p.required_subtype_table,
                           p.required_subtype_pk_column, a.depth + 1
                    FROM core.entity_types p
                    JOIN old_ancestry a ON a.parent_entity_type_id = p.entity_type_id
                    WHERE a.depth < 100
                ),
                new_ancestry AS (
                    SELECT entity_type_id, parent_entity_type_id, required_subtype_table,
                           1 AS depth
                    FROM core.entity_types WHERE entity_type_id = NEW.entity_type_id
                    UNION ALL
                    SELECT p.entity_type_id, p.parent_entity_type_id, p.required_subtype_table,
                           a.depth + 1
                    FROM core.entity_types p
                    JOIN new_ancestry a ON a.parent_entity_type_id = p.entity_type_id
                    WHERE a.depth < 100
                )
                SELECT DISTINCT o.required_subtype_table AS subtype_table,
                                 o.required_subtype_pk_column AS pk_column
                FROM old_ancestry o
                WHERE o.required_subtype_table IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM new_ancestry n
                      WHERE n.required_subtype_table = o.required_subtype_table
                  )
            LOOP
                EXECUTE format(
                    'SELECT EXISTS (SELECT 1 FROM %s WHERE %I = $1)',
                    v_orphan.subtype_table, v_orphan.pk_column
                ) INTO v_exists USING NEW.entity_id;

                IF v_exists THEN
                    RAISE EXCEPTION
                        'Entity % cannot change type: it has a row in %, which its new '
                        'type no longer requires. Remove that subtype row before '
                        'changing the entity''s type.',
                        NEW.entity_id, v_orphan.subtype_table
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END LOOP;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION core.enforce_entity_type_change() IS
        'Parent-side counterpart to core.enforce_entity_subtype(): rejects an UPDATE '
        'of core.entities.entity_type_id that would strand an existing subtype row '
        '(one whose table is required by the OLD type''s ancestry but not the NEW '
        'type''s). Table-agnostic — driven entirely by core.entity_types metadata, so '
        'it protects every registered subtype without a per-subtype trigger.';
    """)
    op.execute("""
        CREATE TRIGGER tr_entities_enforce_type_change
        BEFORE UPDATE OF entity_type_id ON core.entities
        FOR EACH ROW EXECUTE FUNCTION core.enforce_entity_type_change();
    """)

    # ==========================================================================
    # Dungeon-specific enforcement: a type change away from 'dungeon' must not
    # strand world.dungeon_areas children, even once world.dungeons itself has
    # been deleted (§7.5 permits that; the generic check above only looks at
    # subtype rows that still exist).
    # ==========================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION world.enforce_dungeon_type_change_preserves_areas()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_was_dungeon  BOOLEAN;
            v_has_areas    BOOLEAN;
        BEGIN
            IF OLD.entity_type_id IS NOT DISTINCT FROM NEW.entity_type_id THEN
                RETURN NEW;
            END IF;

            SELECT (code = 'dungeon') INTO v_was_dungeon
            FROM core.entity_types WHERE entity_type_id = OLD.entity_type_id;

            IF NOT v_was_dungeon THEN
                RETURN NEW;
            END IF;

            SELECT EXISTS (
                SELECT 1
                FROM world.locations l
                JOIN world.dungeon_areas da ON da.dungeon_area_id = l.location_id
                WHERE l.parent_location_id = NEW.entity_id
            ) INTO v_has_areas;

            IF v_has_areas THEN
                RAISE EXCEPTION
                    'Entity % cannot change type away from dungeon: it still has '
                    'dungeon area children whose parent must be a dungeon-typed '
                    'location (world.enforce_dungeon_area_parent_dungeon). Remove or '
                    'reparent those areas first.',
                    NEW.entity_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION world.enforce_dungeon_type_change_preserves_areas() IS
        'Blocks changing an entity''s type away from dungeon while it still has '
        'world.dungeon_areas children — closes the gap left when world.dungeons '
        '(deletable per conventions §7.5) has already been removed, so '
        'core.enforce_entity_type_change() alone would no longer see a reason to '
        'object even though the area-parentage rule (revision 039) still would.';
    """)
    op.execute("""
        CREATE TRIGGER tr_entities_enforce_dungeon_type_change
        BEFORE UPDATE OF entity_type_id ON core.entities
        FOR EACH ROW EXECUTE FUNCTION world.enforce_dungeon_type_change_preserves_areas();
    """)


def downgrade() -> None:
    """Revert the migration."""

    op.execute("DROP TRIGGER IF EXISTS tr_entities_enforce_dungeon_type_change ON core.entities;")
    op.execute("DROP FUNCTION IF EXISTS world.enforce_dungeon_type_change_preserves_areas();")
    op.execute("DROP TRIGGER IF EXISTS tr_entities_enforce_type_change ON core.entities;")
    op.execute("DROP FUNCTION IF EXISTS core.enforce_entity_type_change();")
    op.execute("ALTER TABLE core.entity_types DROP COLUMN IF EXISTS required_subtype_pk_column;")
