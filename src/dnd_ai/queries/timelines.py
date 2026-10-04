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
