"""Parent-side entity-type-change protection (revision 048).

core.enforce_entity_subtype() (revision 004) validates from the subtype
side: an INSERT or UPDATE on e.g. world.dungeons checks the owning entity's
type. These tests cover the reverse direction — UPDATE core.entities SET
entity_type_id — which revision 048 closes with two triggers: a generic one
driven by core.entity_types metadata, and a dungeon-specific one for the
"child areas stranded even after the marker row is deleted" case the generic
trigger alone cannot see.
"""

import threading
import time
import uuid

import pytest
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import IntegrityError

from tests.factories import (
    lookup_id,
    make_dungeon,
    make_dungeon_area,
    make_location,
    make_world,
)

pytestmark = pytest.mark.database


def _entity_type_id(connection: Connection, code: str) -> object:
    return lookup_id(connection, "core", "entity_types", "entity_type_id", code)


def test_a_dungeon_cannot_be_retyped_to_region(db_connection: Connection) -> None:
    world = make_world(db_connection, slug="retype-dungeon-region")
    dungeon = make_dungeon(db_connection, world)

    with pytest.raises(IntegrityError) as exc:
        db_connection.execute(
            text("UPDATE core.entities SET entity_type_id = :t WHERE entity_id = :e"),
            {"t": _entity_type_id(db_connection, "region"), "e": dungeon},
        )
    assert "cannot change type" in str(exc.value)


def test_a_dungeon_cannot_be_retyped_to_building(db_connection: Connection) -> None:
    """A second, differently-shaped incompatible type — not just the one above."""
    world = make_world(db_connection, slug="retype-dungeon-building")
    dungeon = make_dungeon(db_connection, world)

    with pytest.raises(IntegrityError) as exc:
        db_connection.execute(
            text("UPDATE core.entities SET entity_type_id = :t WHERE entity_id = :e"),
            {"t": _entity_type_id(db_connection, "building"), "e": dungeon},
        )
    assert "cannot change type" in str(exc.value)


def test_a_dungeon_area_cannot_be_retyped_away_while_its_parent_needs_it(
    db_connection: Connection,
) -> None:
    """The subtype-side analogue: dungeon_area is also protected, not just dungeon."""
    world = make_world(db_connection, slug="retype-dungeon-area")
    dungeon = make_dungeon(db_connection, world)
    area = make_dungeon_area(db_connection, dungeon)

    with pytest.raises(IntegrityError) as exc:
        db_connection.execute(
            text("UPDATE core.entities SET entity_type_id = :t WHERE entity_id = :e"),
            {"t": _entity_type_id(db_connection, "region"), "e": area},
        )
    assert "cannot change type" in str(exc.value)


def test_updating_an_entity_without_changing_its_type_is_unaffected(
    db_connection: Connection,
) -> None:
    """A valid, ordinary update — renaming — must not be blocked by this trigger."""
    world = make_world(db_connection, slug="retype-noop")
    dungeon = make_dungeon(db_connection, world, name="Old Name")

    db_connection.execute(
        text("UPDATE core.entities SET canonical_name = 'New Name' WHERE entity_id = :e"),
        {"e": dungeon},
    )
    name = db_connection.execute(
        text("SELECT canonical_name FROM core.entities WHERE entity_id = :e"), {"e": dungeon}
    ).scalar()
    assert name == "New Name"


def test_setting_entity_type_id_to_its_current_value_is_a_no_op(
    db_connection: Connection,
) -> None:
    """UPDATE ... OF entity_type_id fires whenever the column is named in the SET
    list, even if the value does not change — the trigger must not treat that as
    a real change and go looking for orphaned subtype rows."""
    world = make_world(db_connection, slug="retype-same-value")
    dungeon = make_dungeon(db_connection, world)
    current_type = db_connection.execute(
        text("SELECT entity_type_id FROM core.entities WHERE entity_id = :e"), {"e": dungeon}
    ).scalar()

    db_connection.execute(
        text("UPDATE core.entities SET entity_type_id = :t WHERE entity_id = :e"),
        {"t": current_type, "e": dungeon},
    )


def test_a_bare_location_can_be_retyped_before_any_subtype_row_exists(
    db_connection: Connection,
) -> None:
    """A type change that strands nothing remains allowed — this is a correction
    guard, not a blanket immutability lock like world_id's."""
    world = make_world(db_connection, slug="retype-bare-location")
    location = make_location(db_connection, world, entity_type_code="location")

    db_connection.execute(
        text("UPDATE core.entities SET entity_type_id = :t WHERE entity_id = :e"),
        {"t": _entity_type_id(db_connection, "district"), "e": location},
    )
    code = db_connection.execute(
        text(
            "SELECT et.code FROM core.entities e "
            "JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id "
            "WHERE e.entity_id = :e"
        ),
        {"e": location},
    ).scalar()
    assert code == "district"


def test_removing_the_dungeon_row_first_still_does_not_permit_stranding_its_areas(
    db_connection: Connection,
) -> None:
    """Lifecycle-then-retype: deleting world.dungeons (permitted per conventions
    §7.5) removes the row the generic trigger looks for, but the dungeon-specific
    trigger must still reject the type change while dungeon_area children exist —
    this is the "existing child areas cannot be stranded" case, distinct from the
    generic subtype-row check."""
    world = make_world(db_connection, slug="retype-after-marker-removed")
    dungeon = make_dungeon(db_connection, world)
    make_dungeon_area(db_connection, dungeon)

    db_connection.execute(text("DELETE FROM world.dungeons WHERE dungeon_id = :d"), {"d": dungeon})

    with pytest.raises(IntegrityError) as exc:
        db_connection.execute(
            text("UPDATE core.entities SET entity_type_id = :t WHERE entity_id = :e"),
            {"t": _entity_type_id(db_connection, "region"), "e": dungeon},
        )
    assert "still has" in str(exc.value) and "dungeon area" in str(exc.value)


def test_a_dungeon_with_no_areas_can_be_retyped_once_its_marker_row_is_removed(
    db_connection: Connection,
) -> None:
    """The negative-of-the-negative: once world.dungeons is gone and there are no
    dungeon_area children, the type change is legitimate and must succeed."""
    world = make_world(db_connection, slug="retype-after-marker-removed-empty")
    dungeon = make_dungeon(db_connection, world)

    db_connection.execute(text("DELETE FROM world.dungeons WHERE dungeon_id = :d"), {"d": dungeon})

    db_connection.execute(
        text("UPDATE core.entities SET entity_type_id = :t WHERE entity_id = :e"),
        {"t": _entity_type_id(db_connection, "region"), "e": dungeon},
    )
    code = db_connection.execute(
        text(
            "SELECT et.code FROM core.entities e "
            "JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id "
            "WHERE e.entity_id = :e"
        ),
        {"e": dungeon},
    ).scalar()
    assert code == "region"


def test_a_character_npc_cannot_be_retyped_to_bare_character(db_connection: Connection) -> None:
    """The generic mechanism protects Phase 4 subtypes too, not just Phase 5's."""
    from tests.factories import make_character

    world = make_world(db_connection, slug="retype-npc")
    npc = make_character(db_connection, world, entity_type_code="npc")
    db_connection.execute(text("INSERT INTO character.npcs (npc_id) VALUES (:n)"), {"n": npc})

    with pytest.raises(IntegrityError) as exc:
        db_connection.execute(
            text("UPDATE core.entities SET entity_type_id = :t WHERE entity_id = :e"),
            {"t": _entity_type_id(db_connection, "character"), "e": npc},
        )
    assert "cannot change type" in str(exc.value)


# ---------------------------------------------------------------------------
# Concurrency safety of the parent-side/subtype-side checks (revisions 053, 056)
# ---------------------------------------------------------------------------
# Two real connections. Earlier versions of these tests proved blocking by
# setting a short lock_timeout on the second statement, letting it fail, and
# retrying in a fresh third connection — useful lock-attachment evidence, but
# not proof that the *original* waiting statement itself ever resumes and
# revalidates against the newly committed state. A post-merge review
# (PHASE5_REMAINING_ISSUES.md) required the stronger standard: keep the
# second statement genuinely alive on its own thread while the first
# transaction commits, confirm via pg_stat_activity that it was truly
# waiting on a lock (not merely slow), then join the thread and assert on
# its actual outcome. This reuses the pattern already established in
# test_phase4_remaining_issues.py::_assert_blocked_delete_resumes_and_is_rejected
# for a FOR SHARE row lock, generalized here to pg_advisory_xact_lock.


def _cleanup_world(engine: Engine, slug: str) -> None:
    with engine.begin() as cleanup:
        params = {"s": slug}
        cleanup.execute(
            text(
                "DELETE FROM core.entities WHERE world_id IN "
                "(SELECT world_id FROM core.worlds WHERE slug = :s)"
            ),
            params,
        )
        cleanup.execute(text("DELETE FROM core.worlds WHERE slug = :s"), params)


def _run_blocked_statement(
    engine: Engine, statement: object
) -> tuple[threading.Thread, list[tuple[str, Exception | None]], list[int]]:
    """Starts `statement(connection)` on its own connection in a background
    thread, inside an explicit transaction that is committed on success or
    rolled back on failure. Returns the thread (not yet joined), a list that
    will hold exactly one (outcome, exception) pair once the thread finishes,
    and a list that will hold the connection's backend pid as soon as it is
    known (before the statement is even issued, so callers can poll
    pg_stat_activity for it)."""
    outcome: list[tuple[str, Exception | None]] = []
    backend_pid: list[int] = []

    def run() -> None:
        with engine.connect() as second:
            second.begin()
            backend_pid.append(second.execute(text("SELECT pg_backend_pid()")).scalar())
            try:
                statement(second)  # type: ignore[operator]
            except Exception as exc:  # noqa: BLE001 - reported to the main thread, not swallowed
                second.rollback()
                outcome.append(("failed", exc))
            else:
                second.commit()
                outcome.append(("committed", None))

    thread = threading.Thread(target=run)
    thread.start()
    return thread, outcome, backend_pid


def _wait_until_genuinely_waiting_on_a_lock(
    poll_connection: Connection, backend_pid: list[int], label: str
) -> None:
    """Blocks the caller until the background thread's connection both
    exists and pg_stat_activity reports it waiting on a lock — proof it is
    truly blocked behind the advisory lock, not merely running slowly."""
    deadline = time.monotonic() + 5.0
    while not backend_pid and time.monotonic() < deadline:
        time.sleep(0.05)
    assert backend_pid, f"{label} thread never reported its backend pid"
    pid = backend_pid[0]

    waiting = False
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        wait_event_type = poll_connection.execute(
            text("SELECT wait_event_type FROM pg_stat_activity WHERE pid = :p"), {"p": pid}
        ).scalar()
        if wait_event_type == "Lock":
            waiting = True
            break
        time.sleep(0.05)
    assert waiting, f"expected {label} to be genuinely waiting on a lock"


def test_a_concurrent_subtype_insert_and_type_change_is_serialized(
    postgres_engine: Engine,
) -> None:
    """The generic race: one transaction inserts a subtype row
    (world.dungeons) for an entity while another concurrently retypes that
    same entity away from 'dungeon'. core.enforce_entity_subtype() (the
    generic, table-agnostic check every subtype table shares) and
    core.enforce_entity_type_change() must serialize on the same entity,
    not just the dungeon-specific pair — and the retype, left genuinely
    waiting rather than timed out, must resume and be rejected once the
    insert commits."""
    engine = postgres_engine
    slug = f"subtype-lock-generic-{uuid.uuid4().hex[:8]}"
    try:
        with engine.begin() as setup:
            world = make_world(setup, slug=slug)
            dungeon = make_location(setup, world, entity_type_code="dungeon")
            region_type = lookup_id(setup, "core", "entity_types", "entity_type_id", "region")

        with engine.connect() as first:
            first.begin()

            # Transaction 1: insert the subtype row. Still uncommitted.
            first.execute(
                text("INSERT INTO world.dungeons (dungeon_id) VALUES (:d)"), {"d": dungeon}
            )

            def retype(conn: Connection) -> None:
                conn.execute(
                    text("UPDATE core.entities SET entity_type_id = :t WHERE entity_id = :e"),
                    {"t": region_type, "e": dungeon},
                )

            thread, outcome, backend_pid = _run_blocked_statement(engine, retype)
            _wait_until_genuinely_waiting_on_a_lock(
                first, backend_pid, "the concurrent retype away from 'dungeon'"
            )

            first.commit()

            thread.join(timeout=10.0)
            assert not thread.is_alive(), (
                "the blocked retype did not resume within 10s of the insert's commit"
            )

        assert outcome, "blocked retype thread reported no outcome"
        result, exc = outcome[0]
        assert result == "failed", f"expected the resumed retype to be rejected, got: {result}"
        assert "cannot change type" in str(exc)
    finally:
        _cleanup_world(engine, slug)


def test_a_concurrent_dungeon_area_insert_and_marker_removal_plus_retype_is_serialized(
    postgres_engine: Engine,
) -> None:
    """The compound race the review named explicitly: one transaction
    removes world.dungeons (permitted per conventions §7.5) and retypes the
    parent away from 'dungeon' while another concurrently inserts a new
    dungeon_area parented under that same entity. world.enforce_dungeon_
    area_parent_dungeon() (checking "is my parent dungeon-typed") and
    world.enforce_dungeon_type_change_preserves_areas() (checking "do I have
    dungeon-area children") must serialize on the dungeon's own entity_id,
    and the insert, left genuinely waiting, must resume and be rejected once
    the retype commits."""
    engine = postgres_engine
    slug = f"subtype-lock-area-insert-{uuid.uuid4().hex[:8]}"
    try:
        with engine.begin() as setup:
            world = make_world(setup, slug=slug)
            dungeon = make_location(setup, world, entity_type_code="dungeon")
            setup.execute(
                text("INSERT INTO world.dungeons (dungeon_id) VALUES (:d)"), {"d": dungeon}
            )
            area = make_location(
                setup, world, parent_location_id=dungeon, entity_type_code="dungeon_area"
            )
            region_type = lookup_id(setup, "core", "entity_types", "entity_type_id", "region")

        with engine.connect() as first:
            first.begin()

            # Transaction 1: remove the marker, then retype the dungeon
            # away. Still uncommitted.
            first.execute(text("DELETE FROM world.dungeons WHERE dungeon_id = :d"), {"d": dungeon})
            first.execute(
                text("UPDATE core.entities SET entity_type_id = :t WHERE entity_id = :e"),
                {"t": region_type, "e": dungeon},
            )

            def insert_area(conn: Connection) -> None:
                conn.execute(
                    text("INSERT INTO world.dungeon_areas (dungeon_area_id) VALUES (:a)"),
                    {"a": area},
                )

            thread, outcome, backend_pid = _run_blocked_statement(engine, insert_area)
            _wait_until_genuinely_waiting_on_a_lock(
                first, backend_pid, "the concurrent dungeon_area insert"
            )

            first.commit()

            thread.join(timeout=10.0)
            assert not thread.is_alive(), (
                "the blocked insert did not resume within 10s of the retype's commit"
            )

        assert outcome, "blocked insert thread reported no outcome"
        result, exc = outcome[0]
        assert result == "failed", f"expected the resumed insert to be rejected, got: {result}"
        assert "not dungeon" in str(exc)
    finally:
        _cleanup_world(engine, slug)


def test_a_concurrent_dungeon_area_reparent_and_retype_is_serialized(
    postgres_engine: Engine,
) -> None:
    """Reparenting an existing dungeon_area under a dungeon while another
    transaction concurrently retypes that same dungeon away — the two sides
    of "does this dungeon still have area children," contended from
    opposite directions, must serialize rather than each reading a stale
    snapshot of the other, and the retype, left genuinely waiting, must
    resume and be rejected once the reparent commits."""
    engine = postgres_engine
    slug = f"subtype-lock-reparent-{uuid.uuid4().hex[:8]}"
    try:
        with engine.begin() as setup:
            world = make_world(setup, slug=slug)
            old_dungeon = make_dungeon(setup, world, name="Old Dungeon")
            new_dungeon = make_dungeon(setup, world, name="New Dungeon")
            area = make_dungeon_area(setup, old_dungeon)
            region_type = lookup_id(setup, "core", "entity_types", "entity_type_id", "region")

        with engine.connect() as first:
            first.begin()

            # Transaction 1: reparent the area under new_dungeon. Still
            # uncommitted.
            first.execute(
                text("UPDATE world.locations SET parent_location_id = :d WHERE location_id = :a"),
                {"d": new_dungeon, "a": area},
            )

            def retype(conn: Connection) -> None:
                conn.execute(
                    text("UPDATE core.entities SET entity_type_id = :t WHERE entity_id = :e"),
                    {"t": region_type, "e": new_dungeon},
                )

            thread, outcome, backend_pid = _run_blocked_statement(engine, retype)
            _wait_until_genuinely_waiting_on_a_lock(
                first, backend_pid, "the concurrent retype away from 'dungeon'"
            )

            first.commit()

            thread.join(timeout=10.0)
            assert not thread.is_alive(), (
                "the blocked retype did not resume within 10s of the reparent's commit"
            )

        assert outcome, "blocked retype thread reported no outcome"
        result, exc = outcome[0]
        assert result == "failed", f"expected the resumed retype to be rejected, got: {result}"
        assert "still has" in str(exc) and "dungeon area" in str(exc)
    finally:
        _cleanup_world(engine, slug)


# ---------------------------------------------------------------------------
# Concurrency safety of the child-location lock (revision 056)
# ---------------------------------------------------------------------------
# The race PHASE5_REMAINING_ISSUES.md's schema blocker named: inserting
# world.dungeon_areas for child location L versus directly changing that
# same L's parent_location_id. Revision 053's locking did not cover this
# path at all — the insert locked only the proposed parent, and the
# location-update side never acquired any shared lock before its early
# return. Both possible starting orders are covered, since the review noted
# the race exists either way.


def test_a_concurrent_dungeon_area_insert_and_child_parent_clear_is_serialized(
    postgres_engine: Engine,
) -> None:
    """Insert starts first: transaction 1 inserts the dungeon_area row for L
    (validating L's current parent while transaction 2 waits), then commits.
    Transaction 2's clear must resume and be rejected — L is now a
    committed dungeon area and its parent may not be cleared."""
    engine = postgres_engine
    slug = f"child-lock-insert-first-{uuid.uuid4().hex[:8]}"
    try:
        with engine.begin() as setup:
            world = make_world(setup, slug=slug)
            dungeon = make_dungeon(setup, world)
            area = make_location(
                setup, world, parent_location_id=dungeon, entity_type_code="dungeon_area"
            )

        with engine.connect() as first:
            first.begin()

            # Transaction 1: insert the pending dungeon_area row. Still
            # uncommitted.
            first.execute(
                text("INSERT INTO world.dungeon_areas (dungeon_area_id) VALUES (:a)"), {"a": area}
            )

            def clear_parent(conn: Connection) -> None:
                conn.execute(
                    text(
                        "UPDATE world.locations SET parent_location_id = NULL "
                        "WHERE location_id = :a"
                    ),
                    {"a": area},
                )

            thread, outcome, backend_pid = _run_blocked_statement(engine, clear_parent)
            _wait_until_genuinely_waiting_on_a_lock(
                first, backend_pid, "the concurrent parent-clearing update"
            )

            first.commit()

            thread.join(timeout=10.0)
            assert not thread.is_alive(), (
                "the blocked parent-clearing update did not resume within 10s of the insert's "
                "commit"
            )

        assert outcome, "blocked parent-clearing update thread reported no outcome"
        result, exc = outcome[0]
        assert result == "failed", f"expected the resumed update to be rejected, got: {result}"
        assert "cannot be cleared" in str(exc)
    finally:
        _cleanup_world(engine, slug)


def test_a_concurrent_child_parent_clear_and_dungeon_area_insert_is_serialized(
    postgres_engine: Engine,
) -> None:
    """Reverse order: transaction 1 clears L's parent_location_id first
    (L is not yet a dungeon area, so this passes and stays open), then
    commits. Transaction 2's pending dungeon_area insert must resume and be
    rejected — L's parent is now NULL, not a dungeon."""
    engine = postgres_engine
    slug = f"child-lock-update-first-{uuid.uuid4().hex[:8]}"
    try:
        with engine.begin() as setup:
            world = make_world(setup, slug=slug)
            dungeon = make_dungeon(setup, world)
            area = make_location(
                setup, world, parent_location_id=dungeon, entity_type_code="dungeon_area"
            )

        with engine.connect() as first:
            first.begin()

            # Transaction 1: clear the parent before `area` has a
            # world.dungeon_areas row at all, so this is currently valid and
            # passes immediately. Held open (uncommitted) rather than
            # committed right away, so the advisory lock it took stays held
            # while transaction 2 attempts the insert below.
            first.execute(
                text("UPDATE world.locations SET parent_location_id = NULL WHERE location_id = :a"),
                {"a": area},
            )

            def insert_area(conn: Connection) -> None:
                conn.execute(
                    text("INSERT INTO world.dungeon_areas (dungeon_area_id) VALUES (:a)"),
                    {"a": area},
                )

            thread, outcome, backend_pid = _run_blocked_statement(engine, insert_area)
            _wait_until_genuinely_waiting_on_a_lock(
                first, backend_pid, "the concurrent dungeon_area insert"
            )

            first.commit()

            thread.join(timeout=10.0)
            assert not thread.is_alive(), (
                "the blocked insert did not resume within 10s of the parent-clearing update's "
                "commit"
            )

        assert outcome, "blocked insert thread reported no outcome"
        result, exc = outcome[0]
        assert result == "failed", f"expected the resumed insert to be rejected, got: {result}"
        assert "no parent_location_id" in str(exc)
    finally:
        _cleanup_world(engine, slug)
