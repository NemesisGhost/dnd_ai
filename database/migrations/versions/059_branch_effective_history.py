"""campaign.effective_events(): branch-aware effective event history

Revision ID: 059_branch_effective_history
Revises: 058_timeline_branch_event
Create Date: 2026-08-05 14:00:00.000000

Purpose:
    Closes Phase 6's central exit criterion: "A branch inherits parent events
    only through its branch point; a parent event after that point is absent
    from the branch's effective history." Revision 008 deferred this exact
    query pending narrative.events (revision 057) and branch_event_id
    (revision 058); both now exist.

    campaign.effective_events(p_timeline_id) walks the parent_timeline_id
    chain and returns every narrative.events row visible to that timeline:
    the timeline's own full local history (unbounded), plus each ancestor's
    history bounded by the world-time sort_key at which the *next timeline
    down* actually branched off it. Climbing from a target timeline C through
    parent P to grandparent G: C's own events are unbounded; P's events are
    capped at C's branch point (C.branch_world_time_id); G's events are
    capped at P's branch point (P.branch_world_time_id), not C's — P itself
    only ever inherited G's history up to that point, so nothing beyond it
    was ever part of P's timeline to inherit further. The recursive CTE
    carries this forward one level at a time rather than reusing a single
    cutoff for every ancestor.

    Only event_status_id = 'recorded' rows are returned — draft events are
    not yet historical fact, and voided/corrected events are explicitly
    excluded from effective state (docs/ENTITY_LIFECYCLE.md §15).

    This is the persistence-layer "effective timeline-state function"
    docs/architecture/SYSTEM_ARCHITECTURE.md §5.5/§9 calls for. It is a
    building block, not the full Timeline and State Service that document
    describes — that service (a later increment's application-layer code)
    should call this rather than reimplementing the ancestry walk.

Forward migration:
    - campaign.effective_events(p_timeline_id UUID) RETURNS SETOF
      narrative.events, LANGUAGE sql STABLE

Rollback:
    Supported. Drops the function.

Data implications:
    None. Read-only function, no schema change to any table.

Locking considerations:
    None.

See: docs/PLAN.md Phase 6 exit criteria (branch-aware inherited history)
     docs/architecture/SYSTEM_ARCHITECTURE.md §9 (effective timeline state)
     docs/ENTITY_LIFECYCLE.md §9 (branching timelines), §15 (event lifecycle)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "059_branch_effective_history"
down_revision = "058_timeline_branch_event"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    op.execute("""
        CREATE OR REPLACE FUNCTION campaign.effective_events(p_timeline_id UUID)
        RETURNS SETOF narrative.events
        LANGUAGE sql
        STABLE
        AS $$
            WITH RECURSIVE ancestry AS (
                -- Base case: the target timeline itself. Unbounded — its full
                -- local history is always effective. own_branch_sort_key is
                -- carried forward as the cutoff to apply to ITS parent, one
                -- level up.
                SELECT
                    t.timeline_id,
                    t.parent_timeline_id,
                    NULL::bigint AS upper_bound_sort_key,
                    bwt.sort_key AS own_branch_sort_key
                FROM campaign.timelines t
                LEFT JOIN core.world_times bwt ON bwt.world_time_id = t.branch_world_time_id
                WHERE t.timeline_id = p_timeline_id

                UNION ALL

                -- Recursive step: climb to the parent. The parent's own
                -- events are capped at the CHILD's branch point (where the
                -- child actually diverged from this parent) — not at the
                -- target's original branch point, which only ever bounds the
                -- immediate parent. The parent's own branch_world_time_id
                -- becomes the next level's cutoff.
                SELECT
                    parent.timeline_id,
                    parent.parent_timeline_id,
                    child.own_branch_sort_key AS upper_bound_sort_key,
                    parent_bwt.sort_key AS own_branch_sort_key
                FROM ancestry child
                JOIN campaign.timelines parent ON parent.timeline_id = child.parent_timeline_id
                LEFT JOIN core.world_times parent_bwt
                    ON parent_bwt.world_time_id = parent.branch_world_time_id
            )
            SELECT e.*
            FROM ancestry a
            JOIN narrative.events e ON e.timeline_id = a.timeline_id
            JOIN narrative.event_statuses es
                ON es.event_status_id = e.event_status_id AND es.code = 'recorded'
            JOIN core.world_times ewt ON ewt.world_time_id = e.world_time_id
            WHERE a.upper_bound_sort_key IS NULL OR ewt.sort_key <= a.upper_bound_sort_key;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION campaign.effective_events(UUID) IS
        'Branch-aware effective event history for a timeline: its own full '
        'local history plus each ancestor''s history up through the point the '
        'next timeline down actually branched off it (rule 7). Only '
        'event_status_id = recorded rows are returned. '
        '(docs/architecture/SYSTEM_ARCHITECTURE.md §9)';
    """)


def downgrade() -> None:
    """Revert the migration."""

    op.execute("DROP FUNCTION IF EXISTS campaign.effective_events(UUID);")
