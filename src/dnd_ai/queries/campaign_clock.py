"""Effective campaign clock (Phase 15 checkpoint 15.2W-2).

A timeline's own `campaign.timeline_clocks` row wins. A timeline without one
inherits its parent's effective clock, bounded by the point where it branched, so
it never shows parent time that lies after the branch (DATABASE_MODEL §6.1/§17).
A branch whose ancestors have no clock at all starts at its branch point; a root
timeline with no row has no clock.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, text

from dnd_ai.domain.world_time import display_text, full_display_text

_ROW_SQL = """
    SELECT wt.world_time_id, wt.sort_key, wt.label, wt.year, wt.day,
           cm.name AS month_name, c.epoch_label
    FROM core.world_times wt
    LEFT JOIN core.calendars c ON c.calendar_id = wt.calendar_id
    LEFT JOIN core.calendar_months cm
      ON cm.calendar_id = wt.calendar_id AND cm.month_number = wt.month_number
    WHERE wt.world_time_id = :t
"""

_FULL_ROW_SQL = """
    SELECT wt.label, wt.year, wt.day, wt.hour, wt.minute, wt.calendar_id,
           c.display_name AS calendar_name, cm.name AS month_name, c.epoch_label
    FROM core.world_times wt
    LEFT JOIN core.calendars c ON c.calendar_id = wt.calendar_id
    LEFT JOIN core.calendar_months cm
      ON cm.calendar_id = wt.calendar_id AND cm.month_number = wt.month_number
    WHERE wt.world_time_id = :t
"""


# Events a clock advance may name as its gameplay cause (CP-9b): recorded events of the
# campaign's own timeline (an ancestor's history is never offered), in its world, that are not
# the clock's own chain and not the bookkeeping event of a correction, and not one the acting
# editor may not read (`:denied`: the caller's `campaign.view` denies, entity or event targeted,
# from `resolve_world_entity_visibility`). Binds :t timeline, :w world, :c campaign, :denied.
ELIGIBLE_CAUSE_FROM_SQL = """
    FROM narrative.events ev
    JOIN core.entities ce ON ce.entity_id = ev.event_id
    JOIN narrative.event_types et ON et.event_type_id = ev.event_type_id
    JOIN narrative.event_statuses es ON es.event_status_id = ev.event_status_id
    JOIN core.world_times wt ON wt.world_time_id = ev.world_time_id
    WHERE ev.timeline_id = :t AND ce.world_id = :w
      AND (ev.campaign_id = :c OR ev.campaign_id IS NULL)
      AND es.code = 'recorded'
      AND NOT (ev.event_id = ANY(CAST(:denied AS uuid[])))
      AND et.code NOT IN ('time_advanced', 'time_corrected')
      AND NOT EXISTS (
          SELECT 1 FROM narrative.event_corrections corr
          WHERE corr.correcting_event_id = ev.event_id
      )
"""

CAUSE_CHOICE_LIMIT = 50


@dataclass(frozen=True)
class ClockCauseChoice:
    event_id: uuid.UUID
    name: str
    in_world_time: str


def list_clock_cause_choices(
    connection: Connection,
    *,
    timeline_id: uuid.UUID,
    world_id: uuid.UUID,
    campaign_id: uuid.UUID,
    denied_event_ids: frozenset[uuid.UUID] = frozenset(),
    not_after_world_time_id: uuid.UUID | None = None,
    search: str | None = None,
) -> list[ClockCauseChoice]:
    """Eligible cause events, newest in-world time first, for the advance form's picker. A
    `not_after_world_time_id` outside the world applies no time filter."""
    params: dict[str, object] = {
        "t": timeline_id,
        "w": world_id,
        "c": campaign_id,
        "denied": list(denied_event_ids),
        "limit": CAUSE_CHOICE_LIMIT,
    }
    extra = ""
    if not_after_world_time_id is not None:
        limit_key = connection.execute(
            text(
                "SELECT sort_key FROM core.world_times WHERE world_time_id = :x AND world_id = :w"
            ),
            {"x": not_after_world_time_id, "w": world_id},
        ).scalar()
        if limit_key is not None:
            params["limit_key"] = limit_key
            extra += " AND wt.sort_key <= :limit_key"
    if search:
        escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        params["search"] = f"%{escaped}%"
        extra += " AND ce.canonical_name ILIKE :search"
    rows = connection.execute(
        text(f"""
            SELECT ev.event_id, ce.canonical_name, ev.world_time_id
            {ELIGIBLE_CAUSE_FROM_SQL}{extra}
            ORDER BY wt.sort_key DESC, ev.created_at DESC, ev.event_id
            LIMIT :limit
        """),
        params,
    ).all()
    return [
        ClockCauseChoice(
            r.event_id, str(r.canonical_name), clock_display(connection, r.world_time_id)
        )
        for r in rows
    ]


@dataclass(frozen=True)
class EffectiveClock:
    world_time_id: uuid.UUID
    sort_key: int
    display: str
    # True when this timeline has its own clock row (and so can be corrected).
    own_row: bool
    # The own row's version, or 0 when the value is inherited or absent.
    row_version: int
    last_event_id: uuid.UUID | None


def clock_display(connection: Connection, world_time_id: uuid.UUID) -> str:
    """The clock's complete reading (calendar, date, clock time and label), which
    keeps every recorded part of the point rather than just its label."""
    row = connection.execute(text(_FULL_ROW_SQL), {"t": world_time_id}).one()
    return (
        full_display_text(
            label=row.label,
            calendar_name=row.calendar_name,
            has_calendar=row.calendar_id is not None,
            year=row.year,
            month_name=row.month_name,
            day=row.day,
            hour=row.hour,
            minute=row.minute,
            epoch_label=row.epoch_label,
        )
        or "Unplaced time"
    )


def world_time_point(connection: Connection, world_time_id: uuid.UUID) -> tuple[int, str]:
    row = connection.execute(text(_ROW_SQL), {"t": world_time_id}).one()
    return int(row.sort_key), display_text(
        label=row.label,
        year=row.year,
        month_name=row.month_name,
        day=row.day,
        epoch_label=row.epoch_label,
    )


def resolve_effective_clock(
    connection: Connection, *, timeline_id: uuid.UUID
) -> EffectiveClock | None:
    own = connection.execute(
        text("""
            SELECT current_world_time_id, row_version, last_event_id
            FROM campaign.timeline_clocks WHERE timeline_id = :t
        """),
        {"t": timeline_id},
    ).one_or_none()
    if own is not None:
        sort_key, _ = world_time_point(connection, own.current_world_time_id)
        display = clock_display(connection, own.current_world_time_id)
        return EffectiveClock(
            own.current_world_time_id,
            sort_key,
            display,
            True,
            int(own.row_version),
            own.last_event_id,
        )
    timeline = connection.execute(
        text("""
            SELECT parent_timeline_id, branch_world_time_id
            FROM campaign.timelines WHERE timeline_id = :t
        """),
        {"t": timeline_id},
    ).one_or_none()
    if timeline is None or timeline.parent_timeline_id is None:
        return None
    parent = resolve_effective_clock(connection, timeline_id=timeline.parent_timeline_id)
    branch_key, _ = world_time_point(connection, timeline.branch_world_time_id)
    if parent is None or parent.sort_key > branch_key:
        world_time_id = timeline.branch_world_time_id
    else:
        world_time_id = parent.world_time_id
    sort_key, _ = world_time_point(connection, world_time_id)
    display = clock_display(connection, world_time_id)
    return EffectiveClock(world_time_id, sort_key, display, False, 0, None)
