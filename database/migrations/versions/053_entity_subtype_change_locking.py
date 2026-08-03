"""Serialize entity-type changes against subtype and dungeon-area writes

Revision ID: 053_entity_subtype_change_lock
Revises: 051_conditional_route_semantics
Create Date: 2026-08-03 16:00:00.000000

Purpose:
    Post-merge review finding (PHASE5_REMAINING_ISSUES.md item 1): revision
    048 added checks on both sides of the "entity_type_id matches its
    subtype rows" invariant — core.enforce_entity_subtype() (revision 004)
    checks from the subtype-row side, core.enforce_entity_type_change() and
    world.enforce_dungeon_type_change_preserves_areas() (both revision 048)
    check from the parent-entity-type side — but neither side takes a lock
    shared with the other. Under READ COMMITTED, two concurrent transactions
    can each validate against a snapshot that does not yet include the
    other's uncommitted write, and both commit:

    - Transaction A inserts a subtype row (e.g. world.dungeons); transaction
      B concurrently retypes the same entity away from the type that row
      requires. Each reads a snapshot where the other's write has not
      happened yet, so both pass.
    - Transaction A inserts a world.dungeon_areas row parented under dungeon
      X; transaction B concurrently retypes X away from 'dungeon' (having
      already removed its world.dungeons marker, which conventions §7.5
      permits deleting). A's check (is X dungeon-typed?) and B's check (does
      X have dungeon-area children?) each read a pre-write snapshot of the
      other side.

    This is exactly the write-skew shape revision 049 already fixed for
    location containment, closed the same way: a transaction-scoped advisory
    lock, acquired before the relevant read, shared by every write path that
    can create, remove, or invalidate the protected relationship. The lock
    key is the entity_id whose subtype-consistency is being validated —
    every function below acquires it on the *same* entity_id for the *same*
    conceptual relationship, so a writer on either side of a given
    relationship blocks behind the other instead of each reading a stale
    snapshot:

    - core.enforce_entity_subtype() (revision 004) — locks the subtype row's
      own owning entity_id, matching core.enforce_entity_type_change()'s
      lock on that same entity_id. This is the generic, table-agnostic pair
      that covers every registered subtype (character/npc/player_character,
      location/settlement/building/dungeon/dungeon_area, knowledge_item),
      not only dungeons — the review explicitly asked that the generic
      core.enforce_entity_subtype() race not be left unfixed while only
      world.dungeons was patched.
    - core.enforce_entity_type_change() (revision 048) — locks NEW.entity_id,
      the entity being retyped, matching the row above.
    - world.enforce_dungeon_type_change_preserves_areas() (revision 048) —
      locks NEW.entity_id (the same key as the row above; both fire on the
      same UPDATE OF entity_type_id event and a transaction may reacquire
      its own advisory lock any number of times at no extra cost).
    - world.enforce_dungeon_area_parent_dungeon() (revision 039) — locks the
      proposed parent dungeon's own entity_id, matching the row above from
      the opposite direction: "does this dungeon still claim to be a
      dungeon" (checked here) and "does this dungeon still have area
      children" (checked by world.enforce_dungeon_type_change_preserves_
      areas() above) are the same relationship, contended from either
      direction on the dungeon's own entity_id.
    - world.enforce_dungeon_area_parent_dungeon_on_update() (revision 044) —
      locks NEW.parent_location_id, the dungeon a dungeon area is being
      reparented under, the same key as the row above.

    No function here ever acquires more than one advisory lock, so — unlike
    revision 049's location-cycle check, which locks two worlds and needs a
    sorted acquisition order to rule out deadlock between them — there is no
    equivalent ordering hazard to construct here. A genuine deadlock between
    two transactions contending for two different entities' locks in
    opposite order remains possible in principle (as with any lock) and is
    handled the ordinary way: PostgreSQL detects it and aborts one
    transaction, which is standard, expected behavior, not a correctness gap
    — the invariant this revision protects only requires that the two sides
    of one entity's subtype relationship cannot both proceed from
    conflicting snapshots, not that unrelated entities never contend at all.

    A type correction made before any subtype row exists remains allowed,
    unchanged from revision 048 — this revision only adds locking around the
    existing reads, it does not change what any function decides.

Forward migration:
    - CREATE OR REPLACE on all five functions above, adding a
      pg_advisory_xact_lock() acquisition (keyed by
      hashtextextended('core.entities.subtype:' || <entity_id>::text, 0))
      immediately before each function's first read of the data the other
      side of its relationship writes. No trigger attachments change; each
      function keeps the trigger revision that created it.

Rollback:
    Supported. Restores all five functions to their exact bodies as of
    revisions 004, 039, 044, and 048 (the versions already merged and
    CI-verified in PR #5) — no locking, identical validation logic
    otherwise.

Data implications:
    None. Function bodies only.

Locking considerations:
    Replacing a function body takes no table lock. The advisory locks these
    functions now acquire are transaction-scoped (pg_advisory_xact_lock) and
    release automatically at commit or rollback.

See: docs/PHASE5_REMAINING_ISSUES.md item 1
     database/migrations/versions/049_location_containment_locking.py
     (the same advisory-lock pattern, first used for location containment)
     database/migrations/versions/004_worlds_and_entities.py
     database/migrations/versions/039_dungeon_structures.py
     database/migrations/versions/044_dungeon_structural_mutation_safety.py
     database/migrations/versions/048_entity_type_change_protection.py
     (the five functions this revision extends)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "053_entity_subtype_change_lock"
down_revision = "051_conditional_route_semantics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    # ==========================================================================
    # 1. core.enforce_entity_subtype() (revision 004) — subtype-row side
    # ==========================================================================
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

            -- Serialize against core.enforce_entity_type_change() /
            -- world.enforce_dungeon_type_change_preserves_areas() validating
            -- the same entity's type from the other side (revision 053).
            PERFORM pg_advisory_xact_lock(
                hashtextextended('core.entities.subtype:' || v_entity_id::text, 0)
            );

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
        'the subtype primary-key column name as the trigger argument. See conventions §7.4. '
        'Acquires a per-entity advisory lock before reading core.entities, shared with '
        'core.enforce_entity_type_change() (revision 053), so a concurrent parent-side type '
        'change cannot validate against a stale snapshot of this table.';
    """)

    # ==========================================================================
    # 2. core.enforce_entity_type_change() (revision 048) — parent-type side
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

            -- Serialize against core.enforce_entity_subtype() validating this
            -- same entity's subtype rows from the other side (revision 053).
            PERFORM pg_advisory_xact_lock(
                hashtextextended('core.entities.subtype:' || NEW.entity_id::text, 0)
            );

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
        'it protects every registered subtype without a per-subtype trigger. Acquires '
        'a per-entity advisory lock before reading any subtype table, shared with '
        'core.enforce_entity_subtype() (revision 053), so a concurrent subtype-row '
        'write cannot validate against a stale snapshot of this entity''s type.';
    """)

    # ==========================================================================
    # 3. world.enforce_dungeon_type_change_preserves_areas() (revision 048)
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

            -- Serialize against world.enforce_dungeon_area_parent_dungeon() /
            -- ..._on_update() validating this same dungeon's type from the
            -- opposite direction (revision 053). Same lock key as
            -- core.enforce_entity_type_change() above — both fire on the same
            -- UPDATE OF entity_type_id event; reacquiring within one
            -- transaction is a no-op, not a second lock.
            PERFORM pg_advisory_xact_lock(
                hashtextextended('core.entities.subtype:' || NEW.entity_id::text, 0)
            );

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
        'object even though the area-parentage rule (revision 039) still would. '
        'Acquires the same per-entity advisory lock as world.enforce_dungeon_area_'
        'parent_dungeon() (revision 053), so a concurrent dungeon-area write cannot '
        'validate against a stale snapshot of this dungeon''s type.';
    """)

    # ==========================================================================
    # 4. world.enforce_dungeon_area_parent_dungeon() (revision 039)
    # ==========================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION world.enforce_dungeon_area_parent_dungeon()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_parent_location_id  UUID;
            v_parent_type_code    TEXT;
        BEGIN
            SELECT parent_location_id INTO v_parent_location_id
            FROM world.locations WHERE location_id = NEW.dungeon_area_id;

            IF v_parent_location_id IS NULL THEN
                RAISE EXCEPTION
                    'Dungeon area % has no parent_location_id — every dungeon area '
                    'must belong to a dungeon',
                    NEW.dungeon_area_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            -- Serialize against world.enforce_dungeon_type_change_preserves_areas()
            -- validating this same dungeon's type from the opposite direction
            -- (revision 053).
            PERFORM pg_advisory_xact_lock(
                hashtextextended('core.entities.subtype:' || v_parent_location_id::text, 0)
            );

            SELECT et.code INTO v_parent_type_code
            FROM core.entities e
            JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id
            WHERE e.entity_id = v_parent_location_id;

            IF v_parent_type_code IS DISTINCT FROM 'dungeon' THEN
                RAISE EXCEPTION
                    'Dungeon area % parent location % is of type %, not dungeon',
                    NEW.dungeon_area_id, v_parent_location_id, v_parent_type_code
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION world.enforce_dungeon_area_parent_dungeon() IS
        'Requires a dungeon area''s world.locations.parent_location_id to reference a '
        'dungeon-typed location. Checked here rather than in world.locations itself '
        'since the rule is specific to the dungeon_area subtype. Acquires a per-entity '
        'advisory lock (keyed on the parent dungeon) before checking its type, shared '
        'with world.enforce_dungeon_type_change_preserves_areas() (revision 053).';
    """)

    # ==========================================================================
    # 5. world.enforce_dungeon_area_parent_dungeon_on_update() (revision 044)
    # ==========================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION world.enforce_dungeon_area_parent_dungeon_on_update()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_is_dungeon_area    BOOLEAN;
            v_parent_type_code   TEXT;
        BEGIN
            SELECT EXISTS (
                SELECT 1 FROM world.dungeon_areas WHERE dungeon_area_id = NEW.location_id
            ) INTO v_is_dungeon_area;

            IF NOT v_is_dungeon_area THEN
                RETURN NEW;
            END IF;

            IF NEW.parent_location_id IS NULL THEN
                RAISE EXCEPTION
                    'Dungeon area %''s parent_location_id cannot be cleared — every '
                    'dungeon area must belong to a dungeon',
                    NEW.location_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            -- Serialize against world.enforce_dungeon_type_change_preserves_areas()
            -- validating this same dungeon's type from the opposite direction
            -- (revision 053).
            PERFORM pg_advisory_xact_lock(
                hashtextextended('core.entities.subtype:' || NEW.parent_location_id::text, 0)
            );

            SELECT et.code INTO v_parent_type_code
            FROM core.entities e
            JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id
            WHERE e.entity_id = NEW.parent_location_id;

            IF v_parent_type_code IS DISTINCT FROM 'dungeon' THEN
                RAISE EXCEPTION
                    'Dungeon area % parent location % is of type %, not dungeon',
                    NEW.location_id, NEW.parent_location_id, v_parent_type_code
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION world.enforce_dungeon_area_parent_dungeon_on_update() IS
        'Re-runs revision 039''s dungeon-area-must-have-a-dungeon-parent rule whenever '
        'parent_location_id changes on a row that already has a world.dungeon_areas '
        'row, closing the gap left by that revision''s trigger only firing from the '
        'dungeon_areas side. Acquires the same per-entity advisory lock as '
        'world.enforce_dungeon_area_parent_dungeon() (revision 053).';
    """)


def downgrade() -> None:
    """Revert the migration — restores all five functions to their pre-053 bodies."""

    op.execute("""
        CREATE OR REPLACE FUNCTION world.enforce_dungeon_area_parent_dungeon_on_update()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_is_dungeon_area    BOOLEAN;
            v_parent_type_code   TEXT;
        BEGIN
            SELECT EXISTS (
                SELECT 1 FROM world.dungeon_areas WHERE dungeon_area_id = NEW.location_id
            ) INTO v_is_dungeon_area;

            IF NOT v_is_dungeon_area THEN
                RETURN NEW;
            END IF;

            IF NEW.parent_location_id IS NULL THEN
                RAISE EXCEPTION
                    'Dungeon area %''s parent_location_id cannot be cleared — every '
                    'dungeon area must belong to a dungeon',
                    NEW.location_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            SELECT et.code INTO v_parent_type_code
            FROM core.entities e
            JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id
            WHERE e.entity_id = NEW.parent_location_id;

            IF v_parent_type_code IS DISTINCT FROM 'dungeon' THEN
                RAISE EXCEPTION
                    'Dungeon area % parent location % is of type %, not dungeon',
                    NEW.location_id, NEW.parent_location_id, v_parent_type_code
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION world.enforce_dungeon_area_parent_dungeon_on_update() IS
        'Re-runs revision 039''s dungeon-area-must-have-a-dungeon-parent rule whenever '
        'parent_location_id changes on a row that already has a world.dungeon_areas '
        'row, closing the gap left by that revision''s trigger only firing from the '
        'dungeon_areas side.';
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION world.enforce_dungeon_area_parent_dungeon()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_parent_location_id  UUID;
            v_parent_type_code    TEXT;
        BEGIN
            SELECT parent_location_id INTO v_parent_location_id
            FROM world.locations WHERE location_id = NEW.dungeon_area_id;

            IF v_parent_location_id IS NULL THEN
                RAISE EXCEPTION
                    'Dungeon area % has no parent_location_id — every dungeon area '
                    'must belong to a dungeon',
                    NEW.dungeon_area_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            SELECT et.code INTO v_parent_type_code
            FROM core.entities e
            JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id
            WHERE e.entity_id = v_parent_location_id;

            IF v_parent_type_code IS DISTINCT FROM 'dungeon' THEN
                RAISE EXCEPTION
                    'Dungeon area % parent location % is of type %, not dungeon',
                    NEW.dungeon_area_id, v_parent_location_id, v_parent_type_code
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION world.enforce_dungeon_area_parent_dungeon() IS
        'Requires a dungeon area''s world.locations.parent_location_id to reference a '
        'dungeon-typed location. Checked here rather than in world.locations itself '
        'since the rule is specific to the dungeon_area subtype.';
    """)

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
