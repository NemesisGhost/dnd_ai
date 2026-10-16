"""Calendar and world-time authoring (Phase 15 checkpoint 15.2W-1).

- `create_calendar` -- a world-scoped definition (authority: `world.manage`,
  re-resolved under the world row lock). There is no update command: a calendar
  is created whole with its months, and editing one after points reference it is
  deferred (calendar structure changes would silently re-mean existing points).
- `create_world_time` -- a campaign operation (authority: `canon.edit`). Points
  are never edited and are permanent once referenced. The sort key follows
  `dnd_ai.domain.world_time`; allocation of a narrative key runs under a per-world
  advisory lock (`core.world_times.sort:<world>`, last in the lock order) so two
  concurrent placements in the same gap serialize and stay ordered.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, text

from dnd_ai.domain.authoring import (
    AuthoringValidationError,
    WorldArchivedError,
    WorldNotAuthorizedError,
)
from dnd_ai.domain.data_classification import audit_initial
from dnd_ai.domain.world_authority import WORLD_MANAGE
from dnd_ai.domain.world_time import (
    PRECISION_NARRATIVE,
    CalendarDate,
    CalendarInvalidError,
    CalendarSpec,
    WorldTimeReferenceInvalidError,
    allocate_narrative_sort_key,
    calendar_code,
    calendar_precision,
    calendar_sort_key,
    normalize_calendar,
    normalize_label,
)
from dnd_ai.queries.world_authority import resolve_world_authority

from ._operations import lock_operation_scope
from ._shared import lifecycle_code, lookup_id


@dataclass(frozen=True)
class CreateCalendarResult:
    calendar_id: uuid.UUID
    world_id: uuid.UUID
    code: str
    changed_fields: dict[str, object]


@dataclass(frozen=True)
class CreateWorldTimeResult:
    world_time_id: uuid.UUID
    world_id: uuid.UUID
    sort_key: int
    precision_code: str
    changed_fields: dict[str, object]


def create_calendar(
    connection: Connection,
    *,
    world_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    name: str,
    description: str | None,
    days_per_week: int | None,
    epoch_label: str | None,
    months: list[tuple[str, int]],
) -> CreateCalendarResult:
    spec = normalize_calendar(
        name=name,
        description=description,
        days_per_week=days_per_week,
        epoch_label=epoch_label,
        months=months,
    )
    # Lock order: world (FOR SHARE keeps it active), then authority re-check.
    world = connection.execute(
        text("SELECT lifecycle_status_id FROM core.worlds WHERE world_id = :w FOR SHARE"),
        {"w": world_id},
    ).one_or_none()
    if world is None:
        raise WorldNotAuthorizedError(f"world {world_id} does not exist")
    authority = resolve_world_authority(connection, user_id=actor_user_id, world_id=world_id)
    if authority is None or not authority.has_capability(WORLD_MANAGE):
        raise WorldNotAuthorizedError(f"user {actor_user_id} lacks world.manage on {world_id}")
    if lifecycle_code(connection, world.lifecycle_status_id) != "active":
        raise WorldArchivedError(f"world {world_id} is not active")
    return _insert_calendar(connection, world_id=world_id, spec=spec)


def _insert_calendar(
    connection: Connection, *, world_id: uuid.UUID, spec: CalendarSpec
) -> CreateCalendarResult:
    taken = {
        str(c)
        for c in connection.execute(
            text("SELECT code FROM core.calendars WHERE world_id = :w"), {"w": world_id}
        ).scalars()
    }
    code = calendar_code(spec.name, taken)
    calendar_id = connection.execute(
        text("""
            INSERT INTO core.calendars
                (world_id, code, display_name, description, days_per_week, epoch_label)
            VALUES (:w, :code, :name, :description, :dpw, :epoch)
            RETURNING calendar_id
        """),
        {
            "w": world_id,
            "code": code,
            "name": spec.name,
            "description": spec.description,
            "dpw": spec.days_per_week,
            "epoch": spec.epoch_label,
        },
    ).scalar()
    assert isinstance(calendar_id, uuid.UUID)
    for number, month in enumerate(spec.months, start=1):
        connection.execute(
            text("""
                INSERT INTO core.calendar_months (calendar_id, month_number, name, day_count)
                VALUES (:c, :n, :name, :days)
            """),
            {"c": calendar_id, "n": number, "name": month.name, "days": month.day_count},
        )
    return CreateCalendarResult(
        calendar_id=calendar_id,
        world_id=world_id,
        code=code,
        changed_fields=audit_initial(
            {
                "name": spec.name,
                "description": spec.description,
                "days_per_week": spec.days_per_week,
                "epoch_label": spec.epoch_label,
                "month_count": len(spec.months),
            }
        ),
    )


def _lock_sort_order(connection: Connection, world_id: uuid.UUID) -> None:
    """Per-world advisory lock for sort-key allocation (taken last)."""
    connection.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:name, 0))"),
        {"name": f"core.world_times.sort:{world_id}"},
    )


def _world_time_key(
    connection: Connection, *, world_id: uuid.UUID, world_time_id: uuid.UUID
) -> int:
    """The sort key of a point in this world; any other id is one non-disclosing
    error."""
    key = connection.execute(
        text("SELECT sort_key FROM core.world_times WHERE world_time_id = :t AND world_id = :w"),
        {"t": world_time_id, "w": world_id},
    ).scalar()
    if key is None:
        raise WorldTimeReferenceInvalidError(f"world time {world_time_id} is not in {world_id}")
    assert isinstance(key, int)
    return key


def create_world_time(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    calendar_id: uuid.UUID | None = None,
    year: int | None = None,
    month_number: int | None = None,
    day: int | None = None,
    hour: int | None = None,
    minute: int | None = None,
    approximate: bool = False,
    label: str | None = None,
    after_world_time_id: uuid.UUID | None = None,
    before_world_time_id: uuid.UUID | None = None,
) -> CreateWorldTimeResult:
    """Record a point in fictional time. Either a calendar date (`calendar_id`
    and `year`, optionally finer) or a narrative placement (`label` and
    `after_world_time_id`, optionally `before_world_time_id`)."""
    scope = lock_operation_scope(connection, campaign_id=campaign_id, actor_user_id=actor_user_id)
    clean_label = normalize_label(label, required=calendar_id is None)
    if calendar_id is not None:
        if year is None or after_world_time_id is not None or before_world_time_id is not None:
            raise AuthoringValidationError("a calendar time needs a year and no narrative anchor")
        months = _calendar_months(connection, world_id=scope.world_id, calendar_id=calendar_id)
        date = CalendarDate(year, month_number, day, hour, minute)
        sort_key = calendar_sort_key(date, [d for _n, d in months])
        precision = calendar_precision(date, approximate=approximate)
        _lock_sort_order(connection, scope.world_id)
    else:
        if after_world_time_id is None:
            raise AuthoringValidationError("a narrative time is placed after another time")
        if any(v is not None for v in (year, month_number, day, hour, minute)):
            raise AuthoringValidationError("a narrative time has no calendar date")
        _lock_sort_order(connection, scope.world_id)
        after_key = _world_time_key(
            connection, world_id=scope.world_id, world_time_id=after_world_time_id
        )
        before_key = (
            None
            if before_world_time_id is None
            else _world_time_key(
                connection, world_id=scope.world_id, world_time_id=before_world_time_id
            )
        )
        next_key = connection.execute(
            text("""
                SELECT min(sort_key) FROM core.world_times
                WHERE world_id = :w AND sort_key > :k
            """),
            {"w": scope.world_id, "k": after_key},
        ).scalar()
        sort_key = allocate_narrative_sort_key(
            after_key,
            next_key=next_key if isinstance(next_key, int) else None,
            before_key=before_key,
        )
        precision = PRECISION_NARRATIVE
    world_time_id = connection.execute(
        text("""
            INSERT INTO core.world_times
                (world_id, calendar_id, world_time_precision_id, year, month_number, day,
                 hour, minute, label, sort_key)
            VALUES (:w, :cal, :precision, :year, :month, :day, :hour, :minute, :label, :key)
            RETURNING world_time_id
        """),
        {
            "w": scope.world_id,
            "cal": calendar_id,
            "precision": lookup_id(
                connection, "core", "world_time_precisions", "world_time_precision_id", precision
            ),
            "year": year if calendar_id is not None else None,
            "month": month_number,
            "day": day,
            "hour": hour,
            "minute": minute,
            "label": clean_label,
            "key": sort_key,
        },
    ).scalar()
    assert isinstance(world_time_id, uuid.UUID)
    return CreateWorldTimeResult(
        world_time_id=world_time_id,
        world_id=scope.world_id,
        sort_key=sort_key,
        precision_code=precision,
        changed_fields=audit_initial(
            {
                "calendar_id": None if calendar_id is None else str(calendar_id),
                "year": year,
                "month_number": month_number,
                "day": day,
                "hour": hour,
                "minute": minute,
                "label": clean_label,
                "precision": precision,
                "sort_key": sort_key,
            }
        ),
    )


def _calendar_months(
    connection: Connection, *, world_id: uuid.UUID, calendar_id: uuid.UUID
) -> list[tuple[int, int]]:
    """`[(month_number, day_count)]` for a calendar of this world, share-locked so
    it cannot change under the command. Another world's or a missing calendar is
    one non-disclosing error."""
    owner = connection.execute(
        text("SELECT world_id FROM core.calendars WHERE calendar_id = :c FOR SHARE"),
        {"c": calendar_id},
    ).scalar()
    if owner != world_id:
        raise CalendarInvalidError(f"calendar {calendar_id} is not in world {world_id}")
    rows = connection.execute(
        text("""
            SELECT month_number, day_count FROM core.calendar_months
            WHERE calendar_id = :c ORDER BY month_number
        """),
        {"c": calendar_id},
    ).all()
    return [(int(n), int(d)) for n, d in rows]
