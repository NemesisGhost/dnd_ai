"""Serialize dungeon-area creation with the same child location's parent change

Revision ID: 056_dungeon_area_child_lock
Revises: 055_conditional_route_whitespace
Create Date: 2026-08-03 21:00:00.000000

Purpose:
    Post-merge review finding (PHASE5_REMAINING_ISSUES.md, "Current schema
    blocker" item 1, opened after revision 053 shipped): revision 053 added
    per-entity advisory locking to five functions, closing every write-skew
    path it targeted between an entity's type and its subtype rows. It did
    not, however, coordinate the two sides of the dungeon-area/child-location
    relationship *itself*:

    - world.enforce_dungeon_area_parent_dungeon() (revision 039, fires on
      INSERT/UPDATE of world.dungeon_areas) reads the child location's
      parent_location_id, then locks the *proposed parent's* entity_id
      (revision 053) before checking that parent is dungeon-typed. It never
      locks the child location whose parent_location_id it just read.
    - world.enforce_dungeon_area_parent_dungeon_on_update() (revision 044,
      fires on UPDATE OF parent_location_id on world.locations) first checks
      whether NEW.location_id already has a world.dungeon_areas row. If the
      concurrent INSERT above is still uncommitted, that check reads a
      pre-write snapshot, sees no dungeon_areas row, and returns immediately
      — never acquiring any lock at all, let alone one shared with the
      insert.

    Consequently, with child location L already parented under dungeon D:

    - Transaction A: INSERT INTO world.dungeon_areas (dungeon_area_id)
      VALUES (L) — reads L.parent_location_id = D, locks D, confirms D is
      dungeon-typed, passes. Still uncommitted.
    - Transaction B (concurrently): UPDATE world.locations SET
      parent_location_id = NULL WHERE location_id = L — checks "does L have
      a dungeon_areas row?", sees none (A hasn't committed), returns
      immediately with no rejection and no lock taken.

    Either order can commit first; both commit; the final state is a
    dungeon_area row for L whose parent is NULL — invalid, and neither
    function ever objected. This is write skew, the same shape revision 049
    fixed for containment and revision 053 fixed for the entity-type/subtype
    pairs it covered, just on a path revision 053 didn't reach.

    Fix, following the established pattern exactly: acquire a
    pg_advisory_xact_lock keyed on the *child location's own id* as the
    first action in both functions, before either one reads anything, and
    re-read the protected state (the child's parent_location_id in the
    insert-side function; whether the child has a dungeon_areas row in the
    update-side function) only after the lock is held. Whichever transaction
    acquires the child lock first now forces the other to wait until it
    commits or rolls back, and the waiter's post-lock re-read always sees
    that outcome rather than a stale pre-write snapshot — closing the race
    from either starting order.

    Lock key and ordering:
        The child-location lock uses a distinct namespace,
        'world.locations.dungeon_area_parent:' || <location_id>::text, from
        revision 053's entity-subtype namespace ('core.entities.subtype:').
        Different namespace strings hash to different pg_advisory_xact_lock
        keys even for the same UUID, so a child-location lock on location X
        and an entity-subtype lock on that same X's entity_id never
        contend with each other — they are simply different lock objects.

        Both functions below that need a second lock (the proposed/new
        parent dungeon's revision-053 entity-subtype lock) acquire the new
        child-location lock strictly *before* it:

        - world.enforce_dungeon_area_parent_dungeon(): locks the child
          (NEW.dungeon_area_id) first, then (as revision 053 already does)
          locks the parent dungeon (v_parent_location_id) second.
        - world.enforce_dungeon_area_parent_dungeon_on_update(): locks the
          child (NEW.location_id) first, then (as revision 053 already
          does) locks the new parent (NEW.parent_location_id) second.

        No function here ever holds two locks from the same namespace at
        once — each touches exactly one child and, when it gets that far,
        exactly one parent — so this "child-namespace before parent-
        namespace" rule is a total order over every lock any transaction in
        this pair of functions can hold, which is sufficient to rule out a
        deadlock cycle between them (the standard resource-ordering
        argument: two transactions can only deadlock if each holds
        something the other is waiting for, which requires at least one of
        them to acquire its locks out of the shared order). A genuine
        deadlock between unrelated transactions contending for two
        different entities' locks in opposite order remains possible in
        principle, as with any lock, and is handled the ordinary way —
        PostgreSQL detects it and aborts one transaction.

    Behavior preserved, not changed:
        This revision only adds locking around existing reads; it does not
        change what either function decides. Clearing a dungeon area's
        parent, or moving it beneath a non-dungeon, is still rejected;
        reparenting to another dungeon, and ordinary reparenting of
        locations that are not dungeon areas, is still permitted. The
        existing sequential tests in test_dungeon_structural_mutation_safety.py
        (clearing rejected, non-dungeon parent rejected, reparent to another
        dungeon accepted, non-dungeon-area locations freely reparented) are
        unchanged by this revision and continue to pass.

    Review of other Phase 4/5 subtype relationships for the same gap:
        world.settlements and world.buildings (revision 038) have no rule
        coupling their subtype validity to their parent_location_id's type
        at all — any location may be their parent, checked only for
        same-world membership (world.enforce_location_parent_world(),
        revision 038), which does not read or depend on subtype state.
        character.npcs/character.player_characters (revision 017) and
        knowledge.knowledge_items (revision 041) have no parent_location_id
        or equivalent structural-parent column whatsoever. world.dungeon_
        areas is the only Phase 4/5 subtype table whose validity depends on
        its structural parent's *type*, so it is the only relationship this
        fix (or revision 053's) needs to cover. Recorded here per the
        review's explicit request to confirm this even when no further
        function requires changes.

Forward migration:
    CREATE OR REPLACE on world.enforce_dungeon_area_parent_dungeon()
    (revision 039) and world.enforce_dungeon_area_parent_dungeon_on_update()
    (revision 044), each gaining the child-location advisory lock described
    above as its first statement, with its existing read re-ordered to
    happen after the lock is acquired. No trigger attachments change.

Rollback:
    Supported. Restores both functions to their exact bodies as of revision
    053 (which changed the second function's body to add the revision-053
    parent lock, and left the first function's revision-053 body — parent
    lock only — unchanged from revision 039).

Data implications:
    None. Function bodies only.

Locking considerations:
    Replacing a function body takes no table lock. The advisory lock this
    revision adds is transaction-scoped (pg_advisory_xact_lock) and
    releases automatically at commit or rollback, the same as every lock
    revisions 049 and 053 already use.

See: docs/PHASE5_REMAINING_ISSUES.md, "Current schema blocker" item 1
     database/migrations/versions/053_entity_subtype_change_locking.py
     (the entity-subtype lock namespace and pattern this revision extends)
     database/migrations/versions/039_dungeon_structures.py
     database/migrations/versions/044_dungeon_structural_mutation_safety.py
     (the two functions this revision changes)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "056_dungeon_area_child_lock"
down_revision = "055_conditional_route_whitespace"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    # ==========================================================================
    # 1. world.enforce_dungeon_area_parent_dungeon() (revisions 039, 053)
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
            -- Serialize against world.enforce_dungeon_area_parent_dungeon_on_update()
            -- validating this same child location's parent from the opposite
            -- direction (revision 056). Acquired before any read so neither
            -- side can validate against a snapshot that predates the other's
            -- uncommitted write.
            PERFORM pg_advisory_xact_lock(
                hashtextextended(
                    'world.locations.dungeon_area_parent:' || NEW.dungeon_area_id::text, 0
                )
            );

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
        'since the rule is specific to the dungeon_area subtype. Acquires a per-child-'
        'location advisory lock before reading parent_location_id, shared with world.'
        'enforce_dungeon_area_parent_dungeon_on_update() (revision 056), then a '
        'per-entity advisory lock (keyed on the parent dungeon) before checking its '
        'type, shared with world.enforce_dungeon_type_change_preserves_areas() '
        '(revision 053).';
    """)

    # ==========================================================================
    # 2. world.enforce_dungeon_area_parent_dungeon_on_update() (revisions 044, 053)
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
            -- Serialize against world.enforce_dungeon_area_parent_dungeon()
            -- validating this same child location's parent from the opposite
            -- direction (revision 056). Acquired before any read, matching the
            -- row above, so a concurrent dungeon_areas INSERT for this same
            -- location cannot validate against a snapshot that predates this
            -- update, or vice versa.
            PERFORM pg_advisory_xact_lock(
                hashtextextended(
                    'world.locations.dungeon_area_parent:' || NEW.location_id::text, 0
                )
            );

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
        'dungeon_areas side. Acquires a per-child-location advisory lock before '
        'checking whether this row is a dungeon area, shared with world.enforce_'
        'dungeon_area_parent_dungeon() (revision 056), then the same per-entity '
        'advisory lock as that function (revision 053).';
    """)


def downgrade() -> None:
    """Revert the migration — restores both functions to their revision-053 bodies."""

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
