"""Timeline read models for the world authoring surfaces (Phase 14).

Authorization is the caller's job: every function here takes an already
authorized `world_id` and returns only that world's timelines. Nothing here
discloses event names, event IDs, or campaign names (a world owner is not
necessarily a campaign member); branch points are exposed only as world-time
labels, which are world-level data.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, text


@dataclass(frozen=True)
class BranchPointSummary:
    world_time_id: uuid.UUID
    label: str | None
    sort_key: int


@dataclass(frozen=True)
class TimelineSummary:
    timeline_id: uuid.UUID
    name: str
    description: str | None
    is_primary: bool
    parent_timeline_id: uuid.UUID | None
    branch_point: BranchPointSummary | None
    lifecycle_status: str
    row_version: int


def _summary_from_row(row: object) -> TimelineSummary:
    branch = None
    if getattr(row, "branch_world_time_id", None) is not None:
        branch = BranchPointSummary(
            world_time_id=row.branch_world_time_id,  # type: ignore[attr-defined]
            label=row.branch_label,  # type: ignore[attr-defined]
            sort_key=int(row.branch_sort_key),  # type: ignore[attr-defined]
        )
    return TimelineSummary(
        timeline_id=row.timeline_id,  # type: ignore[attr-defined]
        name=str(row.name),  # type: ignore[attr-defined]
        description=row.description,  # type: ignore[attr-defined]
        is_primary=bool(row.is_primary),  # type: ignore[attr-defined]
        parent_timeline_id=row.parent_timeline_id,  # type: ignore[attr-defined]
        branch_point=branch,
        lifecycle_status=str(row.lifecycle_code),  # type: ignore[attr-defined]
        row_version=int(row.row_version),  # type: ignore[attr-defined]
    )


_SUMMARY_SELECT = """
    SELECT t.timeline_id, t.name, t.description, t.is_primary, t.parent_timeline_id,
           t.branch_world_time_id, wt.label AS branch_label, wt.sort_key AS branch_sort_key,
           ls.code AS lifecycle_code, t.row_version
    FROM campaign.timelines t
    JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = t.lifecycle_status_id
    LEFT JOIN core.world_times wt ON wt.world_time_id = t.branch_world_time_id
"""


def list_timeline_summaries(
    connection: Connection, *, world_id: uuid.UUID
) -> list[TimelineSummary]:
    """Every timeline of the world (including archived), primary first, then by
    name. Bounded in practice by what a single author creates; not paginated."""
    rows = connection.execute(
        text(
            _SUMMARY_SELECT
            + " WHERE t.world_id = :w ORDER BY t.is_primary DESC, lower(t.name), t.timeline_id"
        ),
        {"w": world_id},
    ).all()
    return [_summary_from_row(row) for row in rows]


def get_timeline_summary(
    connection: Connection, *, world_id: uuid.UUID, timeline_id: uuid.UUID
) -> TimelineSummary | None:
    """The timeline, but only if it belongs to `world_id` (target binding)."""
    row = connection.execute(
        text(_SUMMARY_SELECT + " WHERE t.world_id = :w AND t.timeline_id = :t"),
        {"w": world_id, "t": timeline_id},
    ).one_or_none()
    return None if row is None else _summary_from_row(row)


@dataclass(frozen=True)
class BranchPointOption:
    world_time_id: uuid.UUID
    label: str | None
    year: int | None
    month_number: int | None
    day: int | None
    sort_key: int


def list_branch_points(
    connection: Connection,
    *,
    parent_timeline_id: uuid.UUID,
    limit: int,
    after: tuple[int, uuid.UUID] | None,
) -> list[BranchPointOption]:
    """Branch-point options for `parent_timeline_id`: the distinct world times
    of *recorded* events in its effective history (inherited ancestor history
    included), newest first. Only world-time data is returned -- never an event
    name or ID, because event content belongs to campaigns the world owner may
    not be a member of. Times earlier than the parent's own branch point are
    excluded (a branch cannot precede its parent's branch point). Fetches
    `limit + 1` rows for keyset paging."""
    rows = connection.execute(
        text("""
            SELECT DISTINCT wt.world_time_id, wt.label, wt.year, wt.month_number, wt.day,
                            wt.sort_key
            FROM campaign.effective_events(:p) e
            JOIN core.world_times wt ON wt.world_time_id = e.world_time_id
            WHERE wt.sort_key >= COALESCE(
                    (SELECT bwt.sort_key FROM campaign.timelines t
                     JOIN core.world_times bwt ON bwt.world_time_id = t.branch_world_time_id
                     WHERE t.timeline_id = :p),
                    -9223372036854775808)
              AND (CAST(:after_key AS bigint) IS NULL
                   OR (wt.sort_key, wt.world_time_id)
                      < (CAST(:after_key AS bigint), CAST(:after_id AS uuid)))
            ORDER BY wt.sort_key DESC, wt.world_time_id DESC
            LIMIT :limit
        """),
        {
            "p": parent_timeline_id,
            "after_key": None if after is None else after[0],
            "after_id": None if after is None else after[1],
            "limit": limit + 1,
        },
    ).all()
    return [
        BranchPointOption(
            world_time_id=row.world_time_id,
            label=row.label,
            year=row.year,
            month_number=row.month_number,
            day=row.day,
            sort_key=int(row.sort_key),
        )
        for row in rows
    ]


def list_child_timelines(
    connection: Connection, *, world_id: uuid.UUID, parent_timeline_id: uuid.UUID
) -> list[TimelineSummary]:
    rows = connection.execute(
        text(
            _SUMMARY_SELECT + " WHERE t.world_id = :w AND t.parent_timeline_id = :p "
            "ORDER BY lower(t.name), t.timeline_id"
        ),
        {"w": world_id, "p": parent_timeline_id},
    ).all()
    return [_summary_from_row(row) for row in rows]


def timeline_has_blocking_campaigns(connection: Connection, *, timeline_id: uuid.UUID) -> bool:
    """Any non-archived campaign on this timeline. Boolean only."""
    return bool(
        connection.execute(
            text("""
                SELECT EXISTS (
                    SELECT 1 FROM campaign.campaigns c
                    JOIN core.lifecycle_statuses cls
                      ON cls.lifecycle_status_id = c.lifecycle_status_id
                    WHERE c.timeline_id = :t AND cls.code NOT IN ('archived', 'deleted')
                )
            """),
            {"t": timeline_id},
        ).scalar()
    )
