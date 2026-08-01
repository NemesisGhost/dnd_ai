"""Constraint tests for revision 006 — calendars, months, world times.

Positive and negative per docs/DATABASE_CONVENTIONS.md §32.1. Everything runs
inside the fixture's transaction and rolls back.

The precision-cascade constraints get particular attention: they are what stop
a world time from claiming a day without a month, which would make it sort and
display as something it is not.
"""

import uuid

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError, InternalError, ProgrammingError

from tests.factories import lookup_id, make_world

pytestmark = pytest.mark.database

CONSTRAINT_ERRORS = (IntegrityError, InternalError, ProgrammingError)


def _precision_id(connection: Connection, code: str) -> uuid.UUID:
    return lookup_id(connection, "core", "world_time_precisions", "world_time_precision_id", code)


def _make_calendar(connection: Connection, world_id: uuid.UUID, code: str = "common") -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO core.calendars (world_id, code, display_name)
            VALUES (:w, :c, 'Common Reckoning')
            RETURNING calendar_id
        """),
        {"w": world_id, "c": code},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def _insert_world_time(connection: Connection, world_id: uuid.UUID, **kwargs: object) -> None:
    params: dict[str, object] = {
        "world": world_id,
        "calendar": None,
        "precision": _precision_id(connection, "exact"),
        "year": 1000,
        "month": None,
        "day": None,
        "hour": None,
        "minute": None,
        "label": None,
        "sort_key": 1,
    }
    params.update(kwargs)
    connection.execute(
        text("""
            INSERT INTO core.world_times
                (world_id, calendar_id, world_time_precision_id, year, month_number,
                 day, hour, minute, label, sort_key)
            VALUES (:world, :calendar, :precision, :year, :month, :day, :hour, :minute,
                    :label, :sort_key)
        """),
        params,
    )


# ---------------------------------------------------------------------------
# core.world_time_precisions
# ---------------------------------------------------------------------------


def test_seeded_precisions_match_the_documented_forms(db_connection: Connection) -> None:
    """DOMAIN_MODEL.md §6.2 lists exactly these four forms."""
    codes = {
        r[0] for r in db_connection.execute(text("SELECT code FROM core.world_time_precisions"))
    }
    assert codes == {"exact", "partial", "approximate", "narrative"}


# ---------------------------------------------------------------------------
# core.calendars
# ---------------------------------------------------------------------------


def test_calendar_can_be_created(db_connection: Connection) -> None:
    world = make_world(db_connection, slug="cal-world")
    assert _make_calendar(db_connection, world) is not None


def test_world_may_define_several_calendars(db_connection: Connection) -> None:
    world = make_world(db_connection, slug="multi-cal")
    _make_calendar(db_connection, world, code="common")
    _make_calendar(db_connection, world, code="elvish")


def test_calendar_code_unique_within_world(db_connection: Connection) -> None:
    world = make_world(db_connection, slug="cal-dupe")
    _make_calendar(db_connection, world, code="common")
    with pytest.raises(IntegrityError):
        _make_calendar(db_connection, world, code="common")


def test_two_worlds_may_share_a_calendar_code(db_connection: Connection) -> None:
    first = make_world(db_connection, slug="cal-w1")
    second = make_world(db_connection, slug="cal-w2")
    _make_calendar(db_connection, first, code="common")
    _make_calendar(db_connection, second, code="common")


def test_calendar_rejects_zero_days_per_week(db_connection: Connection) -> None:
    world = make_world(db_connection, slug="cal-zero-week")
    with pytest.raises(IntegrityError):
        db_connection.execute(
            text("""
                INSERT INTO core.calendars (world_id, code, display_name, days_per_week)
                VALUES (:w, 'broken', 'Broken', 0)
            """),
            {"w": world},
        )


def test_deleting_world_cascades_to_calendars(db_connection: Connection) -> None:
    world = make_world(db_connection, slug="cal-cascade")
    _make_calendar(db_connection, world)
    db_connection.execute(text("DELETE FROM core.worlds WHERE world_id = :w"), {"w": world})
    remaining = db_connection.execute(
        text("SELECT count(*) FROM core.calendars WHERE world_id = :w"), {"w": world}
    ).scalar()
    assert remaining == 0


# ---------------------------------------------------------------------------
# core.calendar_months
# ---------------------------------------------------------------------------


def _add_month(
    connection: Connection,
    calendar_id: uuid.UUID,
    number: int,
    name: str,
    days: int = 30,
) -> None:
    connection.execute(
        text("""
            INSERT INTO core.calendar_months (calendar_id, month_number, name, day_count)
            VALUES (:c, :n, :name, :d)
        """),
        {"c": calendar_id, "n": number, "name": name, "d": days},
    )


def test_calendar_months_can_be_added_in_order(db_connection: Connection) -> None:
    world = make_world(db_connection, slug="months-ok")
    calendar = _make_calendar(db_connection, world)
    _add_month(db_connection, calendar, 1, "Frostmoon")
    _add_month(db_connection, calendar, 2, "Thawtide")


def test_calendar_month_number_unique_within_calendar(db_connection: Connection) -> None:
    world = make_world(db_connection, slug="months-dupe-num")
    calendar = _make_calendar(db_connection, world)
    _add_month(db_connection, calendar, 1, "First")
    with pytest.raises(IntegrityError):
        _add_month(db_connection, calendar, 1, "Also First")


def test_calendar_month_name_unique_within_calendar(db_connection: Connection) -> None:
    world = make_world(db_connection, slug="months-dupe-name")
    calendar = _make_calendar(db_connection, world)
    _add_month(db_connection, calendar, 1, "Frostmoon")
    with pytest.raises(IntegrityError):
        _add_month(db_connection, calendar, 2, "Frostmoon")


@pytest.mark.parametrize(("number", "days"), [(0, 30), (1, 0)])
def test_calendar_month_rejects_non_positive_values(
    db_connection: Connection, number: int, days: int
) -> None:
    world = make_world(db_connection, slug=f"months-bad-{number}-{days}")
    calendar = _make_calendar(db_connection, world)
    with pytest.raises(IntegrityError):
        _add_month(db_connection, calendar, number, "Bad", days=days)


# ---------------------------------------------------------------------------
# core.world_times
# ---------------------------------------------------------------------------


def test_world_time_accepts_a_full_date(db_connection: Connection) -> None:
    world = make_world(db_connection, slug="wt-full")
    calendar = _make_calendar(db_connection, world)
    _insert_world_time(
        db_connection,
        world,
        calendar=calendar,
        year=1247,
        month=3,
        day=14,
        hour=9,
        minute=30,
        sort_key=1247_03_14_0930,
    )


def test_world_time_accepts_a_negative_year(db_connection: Connection) -> None:
    """Fictional calendars count backwards from their epoch too."""
    world = make_world(db_connection, slug="wt-negative")
    _insert_world_time(db_connection, world, year=-300, sort_key=-300)


def test_world_time_accepts_a_narrative_label_without_a_year(
    db_connection: Connection,
) -> None:
    world = make_world(db_connection, slug="wt-narrative")
    _insert_world_time(
        db_connection,
        world,
        precision=_precision_id(db_connection, "narrative"),
        year=None,
        label="long before the founding",
        sort_key=-999999,
    )


def test_world_time_requires_a_year_or_a_label(db_connection: Connection) -> None:
    """A world time has to be *something*."""
    world = make_world(db_connection, slug="wt-empty")
    with pytest.raises(IntegrityError):
        _insert_world_time(db_connection, world, year=None, label=None)


@pytest.mark.parametrize(
    ("kwargs", "why"),
    [
        ({"year": None, "month": 3, "label": "x"}, "month without year"),
        ({"month": None, "day": 14}, "day without month"),
        ({"month": 3, "day": None, "hour": 9}, "hour without day"),
        ({"month": 3, "day": 14, "hour": None, "minute": 30}, "minute without hour"),
    ],
)
def test_world_time_precision_cascades(
    db_connection: Connection, kwargs: dict[str, object], why: str
) -> None:
    """A finer component is meaningless without the coarser one above it."""
    world = make_world(db_connection, slug=f"wt-cascade-{abs(hash(why)) % 10000}")
    with pytest.raises(IntegrityError):
        _insert_world_time(db_connection, world, **kwargs)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"month": 0},
        {"month": 3, "day": 0},
        {"month": 3, "day": 14, "hour": 24},
        {"month": 3, "day": 14, "hour": 9, "minute": 60},
    ],
)
def test_world_time_rejects_out_of_range_components(
    db_connection: Connection, kwargs: dict[str, object]
) -> None:
    world = make_world(db_connection, slug=f"wt-range-{abs(hash(str(kwargs))) % 10000}")
    with pytest.raises(IntegrityError):
        _insert_world_time(db_connection, world, **kwargs)


def test_world_time_requires_a_sort_key(db_connection: Connection) -> None:
    """NOT NULL on purpose — an unorderable world time is useless to timeline queries."""
    world = make_world(db_connection, slug="wt-nosort")
    with pytest.raises(IntegrityError):
        _insert_world_time(db_connection, world, sort_key=None)


def test_world_time_cannot_use_another_worlds_calendar(db_connection: Connection) -> None:
    """The cross-world guard. Not expressible as an FK — calendar_id is nullable."""
    calendar_world = make_world(db_connection, slug="wt-cal-owner")
    other_world = make_world(db_connection, slug="wt-cal-other")
    foreign_calendar = _make_calendar(db_connection, calendar_world)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        _insert_world_time(db_connection, other_world, calendar=foreign_calendar)
    assert "belongs to world" in str(exc.value)


def test_world_times_order_by_sort_key(db_connection: Connection) -> None:
    """The access pattern every timeline query depends on."""
    world = make_world(db_connection, slug="wt-ordering")
    for year, key in ((1200, 1200), (-50, -50), (900, 900)):
        _insert_world_time(db_connection, world, year=year, sort_key=key)

    ordered = [
        r[0]
        for r in db_connection.execute(
            text("SELECT year FROM core.world_times WHERE world_id = :w ORDER BY sort_key"),
            {"w": world},
        )
    ]
    assert ordered == [-50, 900, 1200]


# ---------------------------------------------------------------------------
# core.worlds.default_calendar_id (added by this revision)
# ---------------------------------------------------------------------------


def test_world_can_reference_a_default_calendar(db_connection: Connection) -> None:
    world = make_world(db_connection, slug="wt-default-cal")
    calendar = _make_calendar(db_connection, world)
    db_connection.execute(
        text("UPDATE core.worlds SET default_calendar_id = :c WHERE world_id = :w"),
        {"c": calendar, "w": world},
    )
    stored = db_connection.execute(
        text("SELECT default_calendar_id FROM core.worlds WHERE world_id = :w"), {"w": world}
    ).scalar()
    assert stored == calendar


def test_world_default_calendar_must_exist(db_connection: Connection) -> None:
    world = make_world(db_connection, slug="wt-bad-default")
    with pytest.raises(IntegrityError):
        db_connection.execute(
            text(
                "UPDATE core.worlds SET default_calendar_id = gen_random_uuid() WHERE world_id = :w"
            ),
            {"w": world},
        )
