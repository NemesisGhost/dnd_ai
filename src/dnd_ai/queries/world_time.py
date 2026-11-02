"""Read models for calendars and world-time points (Phase 15 checkpoint 15.2W-1).

World times belong to a world; the portal reads them through a campaign of that
world (GM tooling, `canon.edit`), so no point of another world is ever listed.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, text

from dnd_ai.domain.world_time import display_text


@dataclass(frozen=True)
class MonthView:
    month_number: int
    name: str
    day_count: int


@dataclass(frozen=True)
class CalendarView:
    calendar_id: uuid.UUID
    code: str
    name: str
    description: str | None
    days_per_week: int | None
    epoch_label: str | None
    months: tuple[MonthView, ...]


@dataclass(frozen=True)
class WorldTimeRow:
    world_time_id: uuid.UUID
    calendar_id: uuid.UUID | None
    year: int | None
    month_number: int | None
    day: int | None
    hour: int | None
    minute: int | None
    label: str | None
    precision: str
    sort_key: int
    display: str


def list_calendars(connection: Connection, *, world_id: uuid.UUID) -> list[CalendarView]:
    calendars = connection.execute(
        text("""
            SELECT calendar_id, code, display_name, description, days_per_week, epoch_label
            FROM core.calendars WHERE world_id = :w ORDER BY display_name, calendar_id
        """),
        {"w": world_id},
    ).all()
    months: dict[uuid.UUID, list[MonthView]] = {}
    for row in connection.execute(
        text("""
            SELECT cm.calendar_id, cm.month_number, cm.name, cm.day_count
            FROM core.calendar_months cm
            JOIN core.calendars c ON c.calendar_id = cm.calendar_id
            WHERE c.world_id = :w ORDER BY cm.calendar_id, cm.month_number
        """),
        {"w": world_id},
    ):
        months.setdefault(row.calendar_id, []).append(
            MonthView(int(row.month_number), str(row.name), int(row.day_count))
        )
    return [
        CalendarView(
            calendar_id=c.calendar_id,
            code=str(c.code),
            name=str(c.display_name),
            description=c.description,
            days_per_week=c.days_per_week,
            epoch_label=c.epoch_label,
            months=tuple(months.get(c.calendar_id, [])),
        )
        for c in calendars
    ]


def list_world_times(
    connection: Connection,
    *,
    world_id: uuid.UUID,
    limit: int,
    after: tuple[int, uuid.UUID] | None,
) -> list[WorldTimeRow]:
    """Latest first (`sort_key` descending, id as the tiebreak); over-fetches
    one row so the caller can build a keyset page."""
    rows = connection.execute(
        text("""
            SELECT wt.world_time_id, wt.calendar_id, wt.year, wt.month_number, wt.day,
                   wt.hour, wt.minute, wt.label, p.code AS precision, wt.sort_key,
                   cm.name AS month_name, c.epoch_label
            FROM core.world_times wt
            JOIN core.world_time_precisions p
              ON p.world_time_precision_id = wt.world_time_precision_id
            LEFT JOIN core.calendars c ON c.calendar_id = wt.calendar_id
            LEFT JOIN core.calendar_months cm
              ON cm.calendar_id = wt.calendar_id AND cm.month_number = wt.month_number
            WHERE wt.world_id = :w
              AND (CAST(:after_key AS bigint) IS NULL
                   OR (wt.sort_key, wt.world_time_id) < (CAST(:after_key AS bigint),
                                                         CAST(:after_id AS uuid)))
            ORDER BY wt.sort_key DESC, wt.world_time_id DESC
            LIMIT :n
        """),
        {
            "w": world_id,
            "after_key": None if after is None else after[0],
            "after_id": None if after is None else after[1],
            "n": limit + 1,
        },
    ).all()
    return [
        WorldTimeRow(
            world_time_id=r.world_time_id,
            calendar_id=r.calendar_id,
            year=r.year,
            month_number=r.month_number,
            day=r.day,
            hour=r.hour,
            minute=r.minute,
            label=r.label,
            precision=str(r.precision),
            sort_key=int(r.sort_key),
            display=display_text(
                label=r.label,
                year=r.year,
                month_name=r.month_name,
                day=r.day,
                epoch_label=r.epoch_label,
            ),
        )
        for r in rows
    ]
