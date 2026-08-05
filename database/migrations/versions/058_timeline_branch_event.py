"""campaign.timelines.branch_event_id: close Phase 3's branch-causality deferral

Revision ID: 058_timeline_branch_event
Revises: 057_narrative_events
Create Date: 2026-08-05 13:00:00.000000

Purpose:
    docs/PLAN.md's Phase 6 first-time obligations name this explicitly:
    "Close Phase 3's branch-history deferral. Add campaign.timelines.
    branch_event_id with its foreign key and cross-row validation." Revision
    008's own docstring anticipated exactly this: "Phase 6 adds the column
    together with its foreign key, the check that the event belongs to the
    parent timeline at or before branch_world_time_id, and the branch-aware
    effective-history query that finally proves rule 7" (the query itself is
    revision 059). narrative.events now exists (revision 057), so this
    revision closes the deferral.

    Extends campaign.enforce_timeline_branch() (CREATE OR REPLACE) rather than
    adding a second trigger function — the same "one function owns the
    contract" shape used when revision 045 extended the knowledge-domain
    world-agreement functions. The existing tr_timelines_enforce_branch
    trigger already fires BEFORE INSERT OR UPDATE on campaign.timelines and
    needs no change; only the function body gains a new check.

Forward migration:
    - campaign.timelines.branch_event_id UUID REFERENCES narrative.events
      (event_id) ON DELETE RESTRICT
    - campaign.enforce_timeline_branch() extended: whenever branch_event_id is
      set, validate the referenced event belongs to parent_timeline_id and
      occurs at or before branch_world_time_id

Rollback:
    Supported. Restores the revision 008 function body and drops the column.

Data implications:
    None — no existing campaign.timelines row has branch_event_id populated
    (the column is new).

Locking considerations:
    ALTER TABLE ADD COLUMN with no default takes a brief metadata-only lock
    on campaign.timelines; no table rewrite. The table is small (one row per
    timeline) and this is expected to be fast even under load.

Deliberate scoping decisions:
    ON DELETE RESTRICT (not CASCADE or SET NULL): an event that is the
    causal branch point for a timeline is exactly the kind of "shared and
    historical record" conventions §9.2 asks to protect — deleting it out
    from under a live branch would silently orphan the branch's own
    justification. Events are archived, not deleted, per rule 9 in any case
    (docs/ENTITY_LIFECYCLE.md §12), so RESTRICT should never actually block a
    legitimate operation.

See: docs/PLAN.md Phase 6 (first-time obligations)
     docs/architecture/DATABASE_MODEL.md §6.1 (campaign.timelines)
     docs/ENTITY_LIFECYCLE.md §9 (branching timelines)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "058_timeline_branch_event"
down_revision = "057_narrative_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    op.execute("""
        ALTER TABLE campaign.timelines
        ADD COLUMN branch_event_id UUID
            REFERENCES narrative.events(event_id) ON DELETE RESTRICT;
    """)
    op.execute("""
        COMMENT ON COLUMN campaign.timelines.branch_event_id IS
        'The event, on the parent timeline, that caused this branch to diverge. '
        'NULL for a root timeline and for any branch not yet given a causal '
        'event. Must belong to parent_timeline_id and occur at or before '
        'branch_world_time_id — enforced by '
        'campaign.enforce_timeline_branch() (docs/architecture/DATABASE_MODEL.md '
        '§6.1).';
    """)
    op.execute(
        "CREATE INDEX ix_timelines_branch_event_id ON campaign.timelines (branch_event_id) "
        "WHERE branch_event_id IS NOT NULL;"
    )

    # Same function as revision 008, with one new IF block (branch_event_id
    # validation) inserted between the existing branch_world_time_id check and
    # the cycle-detection walk. Everything else is unchanged.
    op.execute("""
        CREATE OR REPLACE FUNCTION campaign.enforce_timeline_branch()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_parent_world      UUID;
            v_branch_time_world UUID;
            v_ancestor          UUID;
            v_event_timeline    UUID;
            v_event_sort_key    BIGINT;
            v_branch_sort_key   BIGINT;
        BEGIN
            IF NEW.parent_timeline_id IS NULL THEN
                IF NEW.branch_event_id IS NOT NULL THEN
                    RAISE EXCEPTION
                        'Timeline % has branch_event_id % but no parent_timeline_id — a '
                        'branch event only makes sense for a non-root timeline',
                        NEW.timeline_id, NEW.branch_event_id
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
                RETURN NEW;
            END IF;

            SELECT world_id INTO v_parent_world
            FROM campaign.timelines WHERE timeline_id = NEW.parent_timeline_id;

            IF v_parent_world IS DISTINCT FROM NEW.world_id THEN
                RAISE EXCEPTION
                    'Timeline % belongs to world %, but its parent % belongs to world %',
                    NEW.timeline_id, NEW.world_id,
                    NEW.parent_timeline_id, v_parent_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            -- Only when there is a branch point to check. A parent without one
            -- is rejected by ck_timelines_branch_fields_paired, and that
            -- constraint should be the thing that reports it — a BEFORE
            -- trigger runs first, so validating a NULL here would mask the
            -- clearer error with a confusing "belongs to world <NULL>".
            IF NEW.branch_world_time_id IS NOT NULL THEN
                SELECT world_id INTO v_branch_time_world
                FROM core.world_times WHERE world_time_id = NEW.branch_world_time_id;

                IF v_branch_time_world IS DISTINCT FROM NEW.world_id THEN
                    RAISE EXCEPTION
                        'Branch world time % belongs to world %, but timeline % belongs to world %',
                        NEW.branch_world_time_id, v_branch_time_world,
                        NEW.timeline_id, NEW.world_id
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            -- New in revision 058: branch_event_id, when set, must belong to
            -- the parent timeline and occur at or before branch_world_time_id
            -- (rule 7 — the branch inherits parent history only through this
            -- point).
            IF NEW.branch_event_id IS NOT NULL THEN
                SELECT timeline_id INTO v_event_timeline
                FROM narrative.events WHERE event_id = NEW.branch_event_id;

                IF v_event_timeline IS DISTINCT FROM NEW.parent_timeline_id THEN
                    RAISE EXCEPTION
                        'Timeline % branch_event_id % belongs to timeline %, but the parent '
                        'timeline is %',
                        NEW.timeline_id, NEW.branch_event_id, v_event_timeline,
                        NEW.parent_timeline_id
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;

                SELECT wt.sort_key INTO v_event_sort_key
                FROM narrative.events e
                JOIN core.world_times wt ON wt.world_time_id = e.world_time_id
                WHERE e.event_id = NEW.branch_event_id;

                SELECT sort_key INTO v_branch_sort_key
                FROM core.world_times WHERE world_time_id = NEW.branch_world_time_id;

                IF v_event_sort_key > v_branch_sort_key THEN
                    RAISE EXCEPTION
                        'Timeline % branch_event_id % occurs after the declared branch point '
                        '(event sort_key %, branch sort_key %)',
                        NEW.timeline_id, NEW.branch_event_id, v_event_sort_key, v_branch_sort_key
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            -- Walk up the parent chain. A cycle would make effective-history
            -- resolution loop forever once Phase 6 starts following it.
            v_ancestor := NEW.parent_timeline_id;
            WHILE v_ancestor IS NOT NULL LOOP
                IF v_ancestor = NEW.timeline_id THEN
                    RAISE EXCEPTION
                        'Timeline % would form a cycle in its parent chain', NEW.timeline_id
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
                SELECT parent_timeline_id INTO v_ancestor
                FROM campaign.timelines WHERE timeline_id = v_ancestor;
            END LOOP;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION campaign.enforce_timeline_branch() IS
        'Keeps a branch in its parent''s world, keeps its branch point in that '
        'world, validates branch_event_id against the parent timeline and '
        'branch_world_time_id (revision 058), and keeps the parent chain '
        'acyclic. Not expressible as CHECK constraints: all compare across rows.';
    """)


def downgrade() -> None:
    """Revert the migration."""

    # Restore the revision 008 function body verbatim (no branch_event_id
    # checks — the column is about to be dropped).
    op.execute("""
        CREATE OR REPLACE FUNCTION campaign.enforce_timeline_branch()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_parent_world      UUID;
            v_branch_time_world UUID;
            v_ancestor          UUID;
        BEGIN
            IF NEW.parent_timeline_id IS NULL THEN
                RETURN NEW;
            END IF;

            SELECT world_id INTO v_parent_world
            FROM campaign.timelines WHERE timeline_id = NEW.parent_timeline_id;

            IF v_parent_world IS DISTINCT FROM NEW.world_id THEN
                RAISE EXCEPTION
                    'Timeline % belongs to world %, but its parent % belongs to world %',
                    NEW.timeline_id, NEW.world_id,
                    NEW.parent_timeline_id, v_parent_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF NEW.branch_world_time_id IS NOT NULL THEN
                SELECT world_id INTO v_branch_time_world
                FROM core.world_times WHERE world_time_id = NEW.branch_world_time_id;

                IF v_branch_time_world IS DISTINCT FROM NEW.world_id THEN
                    RAISE EXCEPTION
                        'Branch world time % belongs to world %, but timeline % belongs to world %',
                        NEW.branch_world_time_id, v_branch_time_world,
                        NEW.timeline_id, NEW.world_id
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            v_ancestor := NEW.parent_timeline_id;
            WHILE v_ancestor IS NOT NULL LOOP
                IF v_ancestor = NEW.timeline_id THEN
                    RAISE EXCEPTION
                        'Timeline % would form a cycle in its parent chain', NEW.timeline_id
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
                SELECT parent_timeline_id INTO v_ancestor
                FROM campaign.timelines WHERE timeline_id = v_ancestor;
            END LOOP;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION campaign.enforce_timeline_branch() IS
        'Keeps a branch in its parent''s world, keeps its branch point in that world, and '
        'keeps the parent chain acyclic. Not expressible as CHECK constraints: all three '
        'compare across rows.';
    """)
    op.execute("ALTER TABLE campaign.timelines DROP COLUMN IF EXISTS branch_event_id;")
