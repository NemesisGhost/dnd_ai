"""Campaign timelines

Revision ID: 008_timelines
Revises: 007_audit_change_log
Create Date: 2026-08-01 21:00:00.000000

Purpose:
    Delivers campaign.timelines, the first table of Phase 3 (docs/PLAN.md
    §5.2). A timeline is the branching chronology a campaign is played on: a
    world has one primary timeline, and any timeline may branch from another
    at a specific world time.

    Delivered before parties because party membership is timeline-scoped
    (ADR 0010) and its exclusion constraint keys on timeline_id.

Forward migration:
    - campaign.timelines
    - campaign.enforce_timeline_branch(), guarding parent/branch-point rules

Rollback:
    Supported. Drops the table and its trigger function.

Data implications:
    Creates no rows. Existing worlds are left without a primary timeline
    rather than having one invented for them; a world's primary timeline is
    a deliberate act, and there is no correct world time to give it here.

Locking considerations:
    None. The table is new and empty.

Deferred to later phases:
    branch_event_id (Phase 6, with narrative.events) — omitted rather than
    stored as an unconstrained UUID, following the precedent Phase 2 set with
    worlds.default_calendar_id. Phase 6 adds the column together with its
    foreign key, the check that the event belongs to the parent timeline at
    or before branch_world_time_id, and the branch-aware effective-history
    query that finally proves rule 7.

See: docs/PLAN.md §5.2 (timelines), Phase 3 exit criteria
     docs/architecture/DATABASE_MODEL.md §6.1
     docs/adr/0010-use-sort-key-ranges-for-fictional-time-intervals.md
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "008_timelines"
down_revision = "007_audit_change_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    # ==========================================================================
    # 1. campaign.timelines
    # ==========================================================================
    # A root timeline has neither a parent nor a branch point; a branch has
    # both. The paired CHECK below is what keeps "branch with no branch point"
    # and "branch point with no parent" out of the table — the second would be
    # a chronology fork with nothing to fork from.
    #
    # ON DELETE RESTRICT for the parent: deleting a timeline that others
    # branched from would orphan their history, and timelines are archived
    # rather than deleted (rule 9).
    op.execute("""
        CREATE TABLE campaign.timelines (
            timeline_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            world_id              UUID NOT NULL
                                  REFERENCES core.worlds(world_id) ON DELETE CASCADE,
            name                  TEXT NOT NULL,
            description           TEXT,
            parent_timeline_id    UUID
                                  REFERENCES campaign.timelines(timeline_id)
                                  ON DELETE RESTRICT,
            branch_world_time_id  UUID
                                  REFERENCES core.world_times(world_time_id)
                                  ON DELETE RESTRICT,
            is_primary            BOOLEAN NOT NULL DEFAULT FALSE,
            lifecycle_status_id   UUID NOT NULL
                                  REFERENCES core.lifecycle_statuses(lifecycle_status_id)
                                  ON DELETE RESTRICT,
            created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT ck_timelines_name_length
                CHECK (char_length(name) BETWEEN 1 AND 200),

            -- Root or branch, never half of one.
            CONSTRAINT ck_timelines_branch_fields_paired
                CHECK (
                    (parent_timeline_id IS NULL AND branch_world_time_id IS NULL)
                    OR
                    (parent_timeline_id IS NOT NULL AND branch_world_time_id IS NOT NULL)
                ),

            -- A timeline cannot branch from itself. Deeper cycles are
            -- prevented by the trigger below.
            CONSTRAINT ck_timelines_no_self_parent
                CHECK (parent_timeline_id IS DISTINCT FROM timeline_id)
        );
    """)
    op.execute("""
        COMMENT ON TABLE campaign.timelines IS
        'A branching chronology within a world. Campaigns are played on a timeline; a '
        'branch inherits parent history only up to its branch point (docs/PLAN.md §5.2).';
    """)
    op.execute("""
        COMMENT ON COLUMN campaign.timelines.branch_world_time_id IS
        'The world time at which this timeline diverged from its parent. NULL only for a '
        'root timeline. The causal branch_event_id arrives in Phase 6 with narrative.events.';
    """)
    op.execute("""
        COMMENT ON COLUMN campaign.timelines.is_primary IS
        'The world''s canonical timeline. At most one per world, enforced by a partial '
        'unique index rather than a CHECK, since the rule spans rows.';
    """)

    op.execute("""
        CREATE TRIGGER tr_timelines_set_updated_at
        BEFORE UPDATE ON campaign.timelines
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)

    # "A world must not have two primary timelines." Spans rows, so it is a
    # partial unique index rather than a CHECK. Partial on is_primary so any
    # number of non-primary timelines coexist.
    op.execute("""
        CREATE UNIQUE INDEX ux_timelines_one_primary_per_world
        ON campaign.timelines (world_id)
        WHERE is_primary;
    """)
    op.execute("CREATE INDEX ix_timelines_world_id ON campaign.timelines (world_id);")
    op.execute("""
        CREATE INDEX ix_timelines_parent_timeline_id
        ON campaign.timelines (parent_timeline_id)
        WHERE parent_timeline_id IS NOT NULL;
    """)
    op.execute(
        "CREATE INDEX ix_timelines_lifecycle_status_id ON campaign.timelines (lifecycle_status_id);"
    )
    op.execute("""
        CREATE INDEX ix_timelines_branch_world_time_id
        ON campaign.timelines (branch_world_time_id)
        WHERE branch_world_time_id IS NOT NULL;
    """)

    # ==========================================================================
    # 2. Branch validation
    # ==========================================================================
    # Three rules that compare across rows and tables, so none is expressible
    # as a CHECK — the same shape as the cross-world guards in Phase 2:
    #
    #   1. A branch belongs to the same world as its parent.
    #   2. Its branch world time belongs to that world too.
    #   3. The parent chain does not form a cycle.
    #
    # Not yet enforceable, and deliberately absent rather than approximated:
    # "a branch point cannot occur after the latest point inherited from the
    # parent". There are no events until Phase 6, so there is no such point to
    # compare against. See docs/PLAN.md Phase 6.
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
        'Keeps a branch in its parent''s world, keeps its branch point in that world, and '
        'keeps the parent chain acyclic. Not expressible as CHECK constraints: all three '
        'compare across rows.';
    """)
    op.execute("""
        CREATE TRIGGER tr_timelines_enforce_branch
        BEFORE INSERT OR UPDATE ON campaign.timelines
        FOR EACH ROW EXECUTE FUNCTION campaign.enforce_timeline_branch();
    """)


def downgrade() -> None:
    """Revert the migration."""

    op.execute("DROP TABLE IF EXISTS campaign.timelines;")
    op.execute("DROP FUNCTION IF EXISTS campaign.enforce_timeline_branch();")
