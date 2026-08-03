"""Character-location temporal integrity (revision 043).

Phase 5 exit review finding: campaign.character_location_history must obey
the full ADR 0010 interval contract, not just same-world agreement — the
same contract campaign.party_memberships already implements (revision 009).
See tests/database/test_party_memberships.py, which this file mirrors in
structure and reuses the reasoning of throughout.

Intervals are fictional time, not real-world time: endpoints are
core.world_times rows and the constraint runs on location_period, an
INT8RANGE derived from their sort_key values by trigger. Tests assert on the
derived range as well as on accept/reject behaviour.
"""

import uuid

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError, InternalError, ProgrammingError

from tests.factories import (
    make_character,
    make_dungeon,
    make_dungeon_area,
    make_timeline,
    make_world,
    make_world_time,
)

pytestmark = pytest.mark.database

CONSTRAINT_ERRORS = (IntegrityError, InternalError, ProgrammingError)

# Four ordered points in one world's chronology.
K0, K1, K2, K3 = 100, 200, 300, 400


class World:
    """One world with a timeline, a character, a two-room dungeon, and four world times."""

    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        self.character_id = make_character(connection, self.world_id)
        self.dungeon_id = make_dungeon(connection, self.world_id)
        self.area_a = make_dungeon_area(connection, self.dungeon_id, name="Entry Hall")
        self.area_b = make_dungeon_area(connection, self.dungeon_id, name="Corridor")
        self.times = {k: make_world_time(connection, self.world_id, k) for k in (K0, K1, K2, K3)}


@pytest.fixture
def w(db_connection: Connection) -> World:
    return World(db_connection, "location-history-world")


def _move(
    connection: Connection,
    world: World,
    *,
    location_id: uuid.UUID | None = None,
    frm: int = K0,
    to: int | None = None,
    timeline_id: uuid.UUID | None = None,
    character_id: uuid.UUID | None = None,
) -> None:
    connection.execute(
        text("""
            INSERT INTO campaign.character_location_history
                (timeline_id, character_id, location_id,
                 arrived_at_world_time_id, departed_at_world_time_id)
            VALUES (:tl, :c, :l, :f, :t)
        """),
        {
            "tl": timeline_id or world.timeline_id,
            "c": character_id or world.character_id,
            "l": location_id or world.area_a,
            "f": world.times[frm],
            "t": world.times[to] if to is not None else None,
        },
    )


# ---------------------------------------------------------------------------
# Positive cases
# ---------------------------------------------------------------------------


def test_a_valid_closed_history_is_accepted(db_connection: Connection, w: World) -> None:
    _move(db_connection, w, frm=K0, to=K1)

    period = db_connection.execute(
        text("SELECT location_period::text FROM campaign.character_location_history")
    ).scalar()
    assert period == f"[{K0},{K1})"


def test_a_valid_transition_between_adjacent_non_overlapping_locations_is_accepted(
    db_connection: Connection, w: World
) -> None:
    """Leave area_a exactly when arriving at area_b — the multi-room-dungeon
    navigation case Phase 5's exit criterion is about."""
    _move(db_connection, w, location_id=w.area_a, frm=K0, to=K1)
    _move(db_connection, w, location_id=w.area_b, frm=K1, to=K2)

    rows = db_connection.execute(
        text(
            "SELECT location_id, location_period::text FROM campaign.character_location_history "
            "ORDER BY location_period"
        )
    ).all()
    assert [tuple(r) for r in rows] == [
        (w.area_a, f"[{K0},{K1})"),
        (w.area_b, f"[{K1},{K2})"),
    ]


def test_an_open_current_location_is_accepted(db_connection: Connection, w: World) -> None:
    _move(db_connection, w, frm=K0, to=None)

    period = db_connection.execute(
        text("SELECT location_period::text FROM campaign.character_location_history")
    ).scalar()
    assert period == f"[{K0},)"

    current = db_connection.execute(
        text(
            "SELECT location_id FROM campaign.character_location_history "
            "WHERE departed_at_world_time_id IS NULL"
        )
    ).scalar()
    assert current == w.area_a


def test_a_later_return_after_a_gap_is_accepted(db_connection: Connection, w: World) -> None:
    _move(db_connection, w, frm=K0, to=K1)
    _move(db_connection, w, frm=K2, to=K3)


# ---------------------------------------------------------------------------
# World agreement — endpoints
# ---------------------------------------------------------------------------


def test_arrival_from_the_wrong_world_is_rejected(db_connection: Connection, w: World) -> None:
    other_world = make_world(db_connection, slug="location-history-other-world-arrival")
    foreign_time = make_world_time(db_connection, other_world, K0)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("""
                INSERT INTO campaign.character_location_history
                    (timeline_id, character_id, location_id, arrived_at_world_time_id)
                VALUES (:tl, :c, :l, :f)
            """),
            {"tl": w.timeline_id, "c": w.character_id, "l": w.area_a, "f": foreign_time},
        )
    assert "belongs to world" in str(exc.value)


def test_departure_from_the_wrong_world_is_rejected(db_connection: Connection, w: World) -> None:
    other_world = make_world(db_connection, slug="location-history-other-world-departure")
    foreign_time = make_world_time(db_connection, other_world, K1)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("""
                INSERT INTO campaign.character_location_history
                    (timeline_id, character_id, location_id,
                     arrived_at_world_time_id, departed_at_world_time_id)
                VALUES (:tl, :c, :l, :f, :t)
            """),
            {
                "tl": w.timeline_id,
                "c": w.character_id,
                "l": w.area_a,
                "f": w.times[K0],
                "t": foreign_time,
            },
        )
    assert "belongs to world" in str(exc.value)


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------


def test_departure_equal_to_arrival_is_rejected(db_connection: Connection, w: World) -> None:
    """An equal-endpoint '[)' range is empty and would slip past the
    exclusion constraint entirely — rejected before it can be stored."""
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        _move(db_connection, w, frm=K1, to=K1)
    assert "must be later than arrival" in str(exc.value)


def test_departure_earlier_than_arrival_is_rejected(db_connection: Connection, w: World) -> None:
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        _move(db_connection, w, frm=K2, to=K0)
    assert "must be later than arrival" in str(exc.value)


# ---------------------------------------------------------------------------
# Overlap prevention
# ---------------------------------------------------------------------------


def test_two_overlapping_closed_periods_are_rejected(db_connection: Connection, w: World) -> None:
    _move(db_connection, w, location_id=w.area_a, frm=K0, to=K2)

    with pytest.raises(IntegrityError) as exc:
        _move(db_connection, w, location_id=w.area_b, frm=K1, to=K3)  # starts inside the first
    assert "ex_character_location_history_no_overlap" in str(exc.value)


def test_an_open_period_overlapping_a_closed_period_is_rejected(
    db_connection: Connection, w: World
) -> None:
    _move(db_connection, w, location_id=w.area_a, frm=K0, to=None)  # still there

    with pytest.raises(IntegrityError) as exc:
        _move(db_connection, w, location_id=w.area_b, frm=K1, to=K3)
    assert "ex_character_location_history_no_overlap" in str(exc.value)


def test_a_closed_period_overlapping_an_open_period_is_rejected(
    db_connection: Connection, w: World
) -> None:
    _move(db_connection, w, location_id=w.area_a, frm=K1, to=K3)

    with pytest.raises(IntegrityError) as exc:
        _move(db_connection, w, location_id=w.area_b, frm=K0, to=None)
    assert "ex_character_location_history_no_overlap" in str(exc.value)


def test_two_open_ended_locations_conflict(db_connection: Connection, w: World) -> None:
    _move(db_connection, w, location_id=w.area_a, frm=K0, to=None)
    with pytest.raises(IntegrityError) as exc:
        _move(db_connection, w, location_id=w.area_b, frm=K3, to=None)
    assert "ex_character_location_history_no_overlap" in str(exc.value)


def test_boundary_touching_periods_are_accepted(db_connection: Connection, w: World) -> None:
    """Half-open '[)': arriving exactly when the previous period ended is
    ordinary, not an overlap."""
    _move(db_connection, w, location_id=w.area_a, frm=K0, to=K1)
    _move(db_connection, w, location_id=w.area_b, frm=K1, to=K2)

    count = db_connection.execute(
        text("SELECT count(*) FROM campaign.character_location_history WHERE character_id = :c"),
        {"c": w.character_id},
    ).scalar()
    assert count == 2


def test_overlapping_periods_for_different_characters_are_accepted(
    db_connection: Connection, w: World
) -> None:
    other_character = make_character(db_connection, w.world_id, name="Second Character")
    _move(db_connection, w, frm=K0, to=K2)
    _move(db_connection, w, frm=K0, to=K2, character_id=other_character)


def test_the_same_period_in_two_branches_does_not_conflict(
    db_connection: Connection, w: World
) -> None:
    branch = make_timeline(
        db_connection,
        w.world_id,
        name="What if",
        parent_timeline_id=w.timeline_id,
        branch_world_time_id=w.times[K1],
    )
    _move(db_connection, w, frm=K0, to=K2)
    _move(db_connection, w, frm=K0, to=K2, timeline_id=branch)


# ---------------------------------------------------------------------------
# Updates receive the same validation as inserts
# ---------------------------------------------------------------------------


def test_updating_a_history_row_re_derives_its_range(db_connection: Connection, w: World) -> None:
    _move(db_connection, w, frm=K0, to=K1)

    db_connection.execute(
        text("""
            UPDATE campaign.character_location_history
            SET departed_at_world_time_id = :t
        """),
        {"t": w.times[K3]},
    )

    period = db_connection.execute(
        text("SELECT location_period::text FROM campaign.character_location_history")
    ).scalar()
    assert period == f"[{K0},{K3})"


def test_an_update_that_would_create_an_overlap_is_rejected(
    db_connection: Connection, w: World
) -> None:
    _move(db_connection, w, location_id=w.area_a, frm=K0, to=K1)
    _move(db_connection, w, location_id=w.area_b, frm=K2, to=K3)

    with pytest.raises(IntegrityError) as exc:
        db_connection.execute(
            text("""
                UPDATE campaign.character_location_history
                SET departed_at_world_time_id = :t
                WHERE location_id = :l
            """),
            {"t": w.times[K3], "l": w.area_a},
        )
    assert "ex_character_location_history_no_overlap" in str(exc.value)


def test_an_update_introducing_a_bad_order_is_rejected(db_connection: Connection, w: World) -> None:
    _move(db_connection, w, frm=K1, to=K2)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("""
                UPDATE campaign.character_location_history
                SET departed_at_world_time_id = :t
                WHERE location_id = :l
            """),
            {"t": w.times[K0], "l": w.area_a},
        )
    assert "must be later than arrival" in str(exc.value)


# ---------------------------------------------------------------------------
# The one-open-location rule, now a consequence of the exclusion constraint
# ---------------------------------------------------------------------------


def test_only_one_open_location_per_timeline_and_character(
    db_connection: Connection, w: World
) -> None:
    """Two unbounded-upper ranges for the same (timeline, character) always
    overlap, so the exclusion constraint alone reproduces revision 042's
    partial-unique-index rule without a second mechanism."""
    _move(db_connection, w, location_id=w.area_a, frm=K0, to=None)
    with pytest.raises(IntegrityError) as exc:
        _move(db_connection, w, location_id=w.area_b, frm=K1, to=None)
    assert "ex_character_location_history_no_overlap" in str(exc.value)


# ---------------------------------------------------------------------------
# Mutating scope-bearing rows cannot invalidate existing history
# ---------------------------------------------------------------------------


def test_a_world_times_sort_key_cannot_be_changed_after_history_references_it(
    db_connection: Connection, w: World
) -> None:
    """core.world_times.sort_key has been immutable since revision 030 —
    proven here in the location-history context specifically, since a
    mutable sort_key would silently invalidate this table's derived range."""
    _move(db_connection, w, frm=K0, to=K1)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("UPDATE core.world_times SET sort_key = 999 WHERE world_time_id = :t"),
            {"t": w.times[K0]},
        )
    assert "immutable" in str(exc.value)


def test_a_characters_world_cannot_be_changed_after_history_references_it(
    db_connection: Connection, w: World
) -> None:
    """core.entities.world_id has been immutable since revision 030 —
    proven here for a character with existing location history."""
    other_world = make_world(db_connection, slug="location-history-immutable-character-world")
    _move(db_connection, w, frm=K0, to=K1)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("UPDATE core.entities SET world_id = :w WHERE entity_id = :c"),
            {"w": other_world, "c": w.character_id},
        )
    assert "immutable" in str(exc.value)


def test_a_locations_world_cannot_be_changed_after_history_references_it(
    db_connection: Connection, w: World
) -> None:
    other_world = make_world(db_connection, slug="location-history-immutable-location-world")
    _move(db_connection, w, frm=K0, to=K1)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("UPDATE core.entities SET world_id = :w WHERE entity_id = :l"),
            {"w": other_world, "l": w.area_a},
        )
    assert "immutable" in str(exc.value)


def test_a_timelines_world_cannot_be_changed_after_history_references_it(
    db_connection: Connection, w: World
) -> None:
    other_world = make_world(db_connection, slug="location-history-immutable-timeline-world")
    _move(db_connection, w, frm=K0, to=K1)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("UPDATE campaign.timelines SET world_id = :w WHERE timeline_id = :tl"),
            {"w": other_world, "tl": w.timeline_id},
        )
    assert "immutable" in str(exc.value)


# ---------------------------------------------------------------------------
# The interval contract: derived range, client input discarded
# ---------------------------------------------------------------------------


def test_a_client_supplied_range_is_overwritten(db_connection: Connection, w: World) -> None:
    db_connection.execute(
        text("""
            INSERT INTO campaign.character_location_history
                (timeline_id, character_id, location_id,
                 arrived_at_world_time_id, departed_at_world_time_id, location_period)
            VALUES (:tl, :c, :l, :f, :t, '[1,2)'::int8range)
        """),
        {
            "tl": w.timeline_id,
            "c": w.character_id,
            "l": w.area_a,
            "f": w.times[K0],
            "t": w.times[K2],
        },
    )

    period = db_connection.execute(
        text("SELECT location_period::text FROM campaign.character_location_history")
    ).scalar()
    assert period == f"[{K0},{K2})", "trigger did not overwrite the client-supplied range"


def test_arrival_world_time_is_required(db_connection: Connection, w: World) -> None:
    with pytest.raises(IntegrityError):
        db_connection.execute(
            text("""
                INSERT INTO campaign.character_location_history
                    (timeline_id, character_id, location_id, arrived_at_world_time_id)
                VALUES (:tl, :c, :l, NULL)
            """),
            {"tl": w.timeline_id, "c": w.character_id, "l": w.area_a},
        )


def test_migration_produced_the_extension_and_constraint(db_connection: Connection) -> None:
    """Mirrors test_party_memberships.py's equivalent assertion: the
    constraint has the exact shape this revision specifies, not merely one
    that happens to pass the behavioural tests above."""
    assert (
        db_connection.execute(
            text("SELECT 1 FROM pg_extension WHERE extname = 'btree_gist'")
        ).scalar()
        == 1
    )

    definition = db_connection.execute(
        text("""
            SELECT pg_get_constraintdef(oid) FROM pg_constraint
            WHERE conrelid = 'campaign.character_location_history'::regclass
              AND conname = 'ex_character_location_history_no_overlap'
        """)
    ).scalar()
    assert str(definition) == (
        "EXCLUDE USING gist (timeline_id WITH =, character_id WITH =, location_period WITH &&)"
    ), f"constraint shape changed: {definition}"
