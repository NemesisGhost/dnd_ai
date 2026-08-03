"""Make containment-cycle validation complete and corruption-safe

Revision ID: 054_location_cycle_detection
Revises: 053_entity_subtype_change_lock
Create Date: 2026-08-03 16:30:00.000000

Purpose:
    Post-merge review finding (PHASE5_REMAINING_ISSUES.md item 2): revision
    044's world.enforce_location_no_cycle() (revision 049 added locking
    around it, unchanged otherwise) walks ancestry with a plain
    WITH RECURSIVE ... UNION ALL and a depth<10000 cutoff, then checks
    whether NEW.location_id ever appears in the 10,000 rows produced. Two
    distinct correctness gaps follow from that shape:

    1. If the ancestry chain contains a cycle that does NOT include
       NEW.location_id (pre-existing data corruption unrelated to this
       write — bypassed constraints, a restored backup, a manual edit), the
       recursive term loops around that cycle indefinitely. UNION ALL keeps
       no memory of rows already produced, so nothing stops it — the walk
       just keeps re-visiting the same handful of rows until the depth
       cutoff silently stops it at row 10,000, and NEW.location_id is
       correctly reported as "not found" even though the chain never
       actually terminates. The write is wrongly accepted.
    2. If the real, non-cyclic ancestor the write would conflict with lies
       beyond the 10,000-row cutoff (an extreme case, but the function's own
       comment claims "a cycle of any length"), the cutoff silently stops
       the walk before reaching it and the write is again wrongly accepted.

    Both are the same root cause: depth-bounding a recursive walk and
    treating "not found within the bound" as proof of anything, when it is
    only proof that the search stopped early.

    Fixed with PostgreSQL's native recursive-query cycle detection (the
    CYCLE clause, available since PostgreSQL 14; this project targets 15).
    CYCLE location_id SET is_cycle USING path tracks every location_id
    already visited on the current path and marks a row is_cycle = true
    instead of recursing through it again — this is real repeated-node
    detection, not a depth heuristic, so a corrupt pre-existing cycle is
    caught regardless of whether NEW.location_id is anywhere in it, and
    regardless of how deep it takes to find. The function now checks two
    conditions separately: NEW.location_id appearing in the ancestry (the
    original "this write would create a cycle" case, unchanged in meaning)
    and is_cycle being set anywhere in the ancestry (a pre-existing cycle,
    a new failure mode this revision adds detection for).

    The depth cutoff is kept, not removed — an extremely deep but genuinely
    non-cyclic ancestor chain is a real (if unlikely) resource concern the
    CYCLE clause does not address, since CYCLE only bounds *cyclic* paths,
    not merely deep ones. What changes is what happens when the cutoff is
    reached: previously, hitting it and finding nothing was silently treated
    as "acyclic." Now, hitting it raises a clear integrity error instead —
    "the walk did not complete" is never again interpreted as "the walk
    proved anything."

    The trigger attachment, the per-world advisory locking revision 049
    added, and the acceptable-cases behavior (two-node cycles, multi-node
    cycles, valid reparenting) are all unchanged — only the ancestry query
    and what it does with an incomplete or corrupt result are replaced.

Forward migration:
    - CREATE OR REPLACE FUNCTION world.enforce_location_no_cycle(): the
      ancestry CTE gains CYCLE location_id SET is_cycle USING path; the
      function now distinguishes "NEW.location_id found" (existing
      behavior), "a pre-existing cycle detected via is_cycle" (new), and
      "the depth cutoff was reached without the walk completing" (new — now
      a raised error instead of silent truncation).

Rollback:
    Supported. Restores the exact function body from revision 049 (locking,
    no CYCLE clause, cutoff-as-silent-truncation).

Data implications:
    None. Function body only.

Locking considerations:
    Replacing a function body takes no table lock.

See: docs/PHASE5_REMAINING_ISSUES.md item 2
     database/migrations/versions/044_dungeon_structural_mutation_safety.py
     (introduces the function)
     database/migrations/versions/049_location_containment_locking.py
     (adds the per-world advisory locking this revision keeps unchanged)
     https://www.postgresql.org/docs/current/queries-with.html#QUERIES-WITH-CYCLE
     (the CYCLE clause this revision adopts)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "054_location_cycle_detection"
down_revision = "053_entity_subtype_change_lock"
branch_labels = None
depends_on = None

_DEPTH_BOUND = 10000


def upgrade() -> None:
    """Apply the migration."""

    op.execute(f"""
        CREATE OR REPLACE FUNCTION world.enforce_location_no_cycle()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_own_world             UUID;
            v_parent_world          UUID;
            v_scope                 UUID;
            v_found_target          BOOLEAN;
            v_found_existing_cycle  BOOLEAN;
            v_max_depth             INTEGER;
        BEGIN
            IF NEW.parent_location_id IS NULL THEN
                RETURN NEW;
            END IF;

            SELECT world_id INTO v_own_world
            FROM core.entities WHERE entity_id = NEW.location_id;

            SELECT world_id INTO v_parent_world
            FROM core.entities WHERE entity_id = NEW.parent_location_id;

            -- Serialize containment changes per world before inspecting the
            -- hierarchy (revision 049) — unchanged by this revision.
            FOR v_scope IN
                SELECT DISTINCT w FROM unnest(ARRAY[v_own_world, v_parent_world]) AS w
                WHERE w IS NOT NULL
                ORDER BY w
            LOOP
                PERFORM pg_advisory_xact_lock(
                    hashtextextended('world.locations.containment:' || v_scope::text, 0)
                );
            END LOOP;

            -- Real repeated-node detection (revision 054), not a depth
            -- heuristic: CYCLE tracks every location_id already visited on
            -- the current path and marks is_cycle instead of recursing
            -- through it again, so a pre-existing corrupt cycle is caught
            -- even when NEW.location_id is not part of it. The depth<{_DEPTH_BOUND}
            -- cutoff remains as a resource bound for a genuinely deep,
            -- non-cyclic chain — CYCLE does not bound those — but hitting it
            -- is now a raised error, not a silently-accepted "not found."
            WITH RECURSIVE ancestry AS (
                SELECT l.location_id, l.parent_location_id, 1 AS depth
                FROM world.locations l
                WHERE l.location_id = NEW.parent_location_id
                UNION ALL
                SELECT l.location_id, l.parent_location_id, a.depth + 1
                FROM world.locations l
                JOIN ancestry a ON l.location_id = a.parent_location_id
                WHERE a.depth < {_DEPTH_BOUND}
            )
            CYCLE location_id SET is_cycle USING path
            SELECT
                bool_or(location_id = NEW.location_id),
                bool_or(is_cycle),
                max(depth)
            INTO v_found_target, v_found_existing_cycle, v_max_depth
            FROM ancestry;

            IF v_found_target THEN
                RAISE EXCEPTION
                    'Location % cannot be parented under %: % is already an ancestor of '
                    'itself through that chain, which would create a containment cycle',
                    NEW.location_id, NEW.parent_location_id, NEW.location_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF v_found_existing_cycle THEN
                RAISE EXCEPTION
                    'Location %''s proposed parent chain (starting at %) already contains '
                    'a pre-existing containment cycle unrelated to this update; refusing '
                    'to modify containment until that corruption is repaired',
                    NEW.location_id, NEW.parent_location_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF v_max_depth >= {_DEPTH_BOUND} THEN
                RAISE EXCEPTION
                    'Location %''s proposed parent chain (starting at %) exceeds % '
                    'ancestors without completing — cannot prove the hierarchy is '
                    'acyclic this deep, refusing rather than assuming it is',
                    NEW.location_id, NEW.parent_location_id, {_DEPTH_BOUND}
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION world.enforce_location_no_cycle() IS
        'Walks parent_location_id ancestry from the proposed parent and rejects the '
        'write if NEW.location_id is among its ancestors — a cycle of any length this '
        'write would create. Also rejects the write outright if the ancestry walk '
        'itself finds a pre-existing repeated node (a corrupt cycle already present in '
        'the data, detected via the CYCLE clause''s is_cycle marker, independent of '
        'whether NEW.location_id is part of it), and raises rather than silently '
        'truncating if the walk exceeds its depth safety bound before completing. '
        'Acquires a per-world transaction-scoped advisory lock (sorted across both '
        'worlds involved) before reading the ancestry, so concurrent transactions that '
        'would together form a cycle are serialized rather than each observing a stale '
        'acyclic snapshot (revision 049).';
    """)


def downgrade() -> None:
    """Revert the migration — restores revision 049's function body."""

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
