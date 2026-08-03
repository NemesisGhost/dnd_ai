"""Concurrency-safe location containment-cycle prevention

Revision ID: 049_location_containment_lock
Revises: 048_entity_type_change_protect
Create Date: 2026-08-03 12:30:00.000000

Purpose:
    Phase 5 exit review finding: revision 044's
    world.enforce_location_no_cycle() reads the current ancestry with a plain
    recursive CTE and rejects the write if it finds a cycle, but takes no
    lock before that read. Under READ COMMITTED (this project's default,
    unchanged from every other trigger here), two concurrent transactions —
    one setting A's parent to B, the other setting B's parent to A — touch
    disjoint rows, so nothing else serializes them: each reads the
    pre-change acyclic hierarchy, each sees no cycle, and both can commit,
    together producing A -> B -> A that neither transaction alone would have
    created. This is classic write skew, not a bug in the ancestry logic
    itself.

    Fixed with a transaction-scoped advisory lock, per-world rather than
    global (a location and its parent already must share a world — revision
    038's tr_locations_enforce_parent_world — so a world-scoped lock is
    exactly as narrow as the invariant it protects, and does not serialize
    unrelated worlds' containment changes against each other). Locked in
    sorted order across both the mover's world and the target parent's world
    when they are looked up independently (normally the same value, but this
    trigger does not depend on tr_locations_enforce_parent_world having
    already run in the same statement — trigger firing order among multiple
    BEFORE triggers on the same table is alphabetical by trigger name, not
    something to build a locking protocol's correctness on) so that two
    transactions naming the same two worlds can never deadlock against each
    other by acquiring them in opposite orders.

    world.locations.parent_location_id is the only column that can change
    containment, and this trigger already fires on every INSERT or UPDATE OF
    that column (revision 044), so one function, one trigger, covers every
    write capable of changing containment — there is no second path that
    would need the same locking protocol applied separately.

    The recursive ancestry walk itself gets a depth bound. It did not have
    one before: correct data can never actually contain a cycle once this
    trigger is enforced, so the walk always terminated in practice, but nothing
    stopped a hypothetical pre-existing cycle (bypassed constraints, restored
    from a bad backup, manually edited) from making the CTE recurse forever
    instead of failing with a clear, bounded error.

Forward migration:
    - CREATE OR REPLACE FUNCTION world.enforce_location_no_cycle(): adds the
      per-world advisory-lock acquisition before the ancestry read, and a
      depth bound on the recursive walk. Same trigger attachment as revision
      044 (BEFORE INSERT OR UPDATE OF parent_location_id ON world.locations)
      — unchanged, not recreated here.

Rollback:
    Supported. Restores revision 044's original function body (no locking,
    no depth bound) via CREATE OR REPLACE — the trigger itself is left alone
    since revision 044 owns creating and dropping it.

Data implications:
    None.

Locking considerations:
    Replacing a function body does not lock or rewrite any table. The
    advisory lock the new function body itself takes is transaction-scoped
    (pg_advisory_xact_lock) and released automatically at commit or
    rollback — no session-level lock survives a transaction.

See: docs/DATABASE_CONVENTIONS.md §9.5 (same-world consistency)
     database/migrations/versions/044_dungeon_structural_mutation_safety.py
     (the function this revision extends)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "049_location_containment_lock"
down_revision = "048_entity_type_change_protect"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    op.execute("""
        CREATE OR REPLACE FUNCTION world.enforce_location_no_cycle()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_own_world     UUID;
            v_parent_world  UUID;
            v_scope         UUID;
            v_found         BOOLEAN;
        BEGIN
            IF NEW.parent_location_id IS NULL THEN
                RETURN NEW;
            END IF;

            SELECT world_id INTO v_own_world
            FROM core.entities WHERE entity_id = NEW.location_id;

            SELECT world_id INTO v_parent_world
            FROM core.entities WHERE entity_id = NEW.parent_location_id;

            -- Serialize containment changes per world before inspecting the
            -- hierarchy (revision 049) — see this revision's docstring for
            -- why a per-world lock, sorted across both worlds involved, is
            -- necessary and sufficient here.
            FOR v_scope IN
                SELECT DISTINCT w FROM unnest(ARRAY[v_own_world, v_parent_world]) AS w
                WHERE w IS NOT NULL
                ORDER BY w
            LOOP
                PERFORM pg_advisory_xact_lock(
                    hashtextextended('world.locations.containment:' || v_scope::text, 0)
                );
            END LOOP;

            WITH RECURSIVE ancestry AS (
                SELECT l.location_id, l.parent_location_id, 1 AS depth
                FROM world.locations l
                WHERE l.location_id = NEW.parent_location_id
                UNION ALL
                SELECT l.location_id, l.parent_location_id, a.depth + 1
                FROM world.locations l
                JOIN ancestry a ON l.location_id = a.parent_location_id
                WHERE a.depth < 10000
            )
            SELECT EXISTS (
                SELECT 1 FROM ancestry WHERE location_id = NEW.location_id
            ) INTO v_found;

            IF v_found THEN
                RAISE EXCEPTION
                    'Location % cannot be parented under %: % is already an ancestor of '
                    'itself through that chain, which would create a containment cycle',
                    NEW.location_id, NEW.parent_location_id, NEW.location_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION world.enforce_location_no_cycle() IS
        'Walks parent_location_id ancestry from the proposed parent and rejects the '
        'write if it ever reaches this row''s own location_id — a cycle of any length, '
        'not just direct self-parenting. Acquires a per-world transaction-scoped '
        'advisory lock (sorted across both worlds involved) before reading the '
        'ancestry, so concurrent transactions that would together form a cycle are '
        'serialized rather than each observing a stale acyclic snapshot (revision '
        '049). The recursive walk is depth-bounded so a hypothetical pre-existing '
        'cycle in the data fails with a bounded error instead of looping forever.';
    """)


def downgrade() -> None:
    """Revert the migration — restores revision 044's original function body."""

    op.execute("""
        CREATE OR REPLACE FUNCTION world.enforce_location_no_cycle()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_found BOOLEAN;
        BEGIN
            IF NEW.parent_location_id IS NULL THEN
                RETURN NEW;
            END IF;

            WITH RECURSIVE ancestry AS (
                SELECT l.location_id, l.parent_location_id
                FROM world.locations l
                WHERE l.location_id = NEW.parent_location_id
                UNION ALL
                SELECT l.location_id, l.parent_location_id
                FROM world.locations l
                JOIN ancestry a ON l.location_id = a.parent_location_id
            )
            SELECT EXISTS (
                SELECT 1 FROM ancestry WHERE location_id = NEW.location_id
            ) INTO v_found;

            IF v_found THEN
                RAISE EXCEPTION
                    'Location % cannot be parented under %: % is already an ancestor of '
                    'itself through that chain, which would create a containment cycle',
                    NEW.location_id, NEW.parent_location_id, NEW.location_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION world.enforce_location_no_cycle() IS
        'Walks parent_location_id ancestry from the proposed parent and rejects the '
        'write if it ever reaches this row''s own location_id — a cycle of any length, '
        'not just direct self-parenting.';
    """)
