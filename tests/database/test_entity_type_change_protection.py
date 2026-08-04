"""Parent-side entity-type-change protection (revision 048).

core.enforce_entity_subtype() (revision 004) validates from the subtype
side: an INSERT or UPDATE on e.g. world.dungeons checks the owning entity's
type. These tests cover the reverse direction — UPDATE core.entities SET
entity_type_id — which revision 048 closes with two triggers: a generic one
driven by core.entity_types metadata, and a dungeon-specific one for the
"child areas stranded even after the marker row is deleted" case the generic
trigger alone cannot see.
"""

import contextlib
import threading
import time
import uuid
from collections.abc import Callable

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
# (PHASE5_REMAINING_ISSUES.md) required the stronger standard, which every
# test below now meets: keep the second statement genuinely alive on its own
# thread while the first transaction commits, confirm via pg_stat_activity
# that it was truly waiting on a lock (not merely slow), join the thread and
# assert on its actual resumed outcome, and then — on a third, independent
# connection — query the committed database state directly to prove no
# invalid combination survived, regardless of which side won. This reuses
# the pattern already established in
# test_world_ruleset_dependency_and_concurrency.py::_assert_blocked_delete_resumes_and_is_rejected
# (redistributed there from the former test_phase4_remaining_issues.py
# monolith — see DEVELOPMENT.md §2.1) for a FOR SHARE row lock, generalized
# here to pg_advisory_xact_lock.


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


class _BackgroundStatement:
    """Runs `statement(connection)` on its own connection in a background
    thread, inside an explicit transaction committed on success or rolled
    back on failure.

    `__enter__` blocks until the worker's connection is established and its
    backend pid recorded before returning control to the caller. If startup
    fails (or never completes within the startup deadline), the thread is
    joined and `__enter__` raises — a `with` block is never entered with a
    worker of unknown or unowned state.

    `__exit__` guarantees that by the time it returns or raises, the worker
    thread is provably no longer running. If the thread is still alive when
    the `with` block exits — normally, or via an exception raised inside it
    — `__exit__` signals the worker's backend to stop: first
    `pg_terminate_backend()`, whose boolean result is checked rather than
    assumed, falling back to `pg_cancel_backend()` if termination was not
    confirmed; each attempt is followed by a bounded join to verify it
    actually worked, not just that a signal was sent. Ending the backend's
    transaction this way also releases anything it held, including any
    transaction-scoped advisory lock. A final, independent liveness check
    backstops both attempts.

    Cleanup failures are never silently discarded. If an exception was
    already propagating out of the `with` block, the cleanup failure is
    attached to it via `add_note` so the original failure remains the
    reported cause; if nothing was already propagating, the cleanup failure
    is raised directly and becomes the `with` block's failure.
    """

    def __init__(self, engine: Engine, statement: Callable[[Connection], None]) -> None:
        self._engine = engine
        self._statement = statement
        self.outcome: list[tuple[str, Exception | None]] = []
        self.backend_pid: list[int] = []
        self._thread = threading.Thread(target=self._run)

    def _run(self) -> None:
        connection: Connection | None = None
        try:
            connection = self._engine.connect()
            connection.begin()
            self.backend_pid.append(connection.execute(text("SELECT pg_backend_pid()")).scalar())
            try:
                self._statement(connection)
            except Exception as exc:  # noqa: BLE001 - reported via self.outcome, not swallowed
                # This connection may have been externally terminated or
                # canceled by __exit__'s cleanup, or the statement may simply
                # have been rejected by a trigger while the connection itself
                # stays healthy — either way, invalidate rather than pool it.
                # Some server-side disconnect conditions (e.g. psycopg's
                # AdminShutdown, raised by pg_terminate_backend) are not
                # always recognized by SQLAlchemy's own disconnect detection,
                # so relying on plain close() risked silently handing a dead
                # connection to a later, unrelated test.
                with contextlib.suppress(Exception):
                    connection.invalidate()
                self.outcome.append(("failed", exc))
            else:
                connection.commit()
                self.outcome.append(("committed", None))
        except Exception as exc:  # noqa: BLE001 - connecting, begin, or pid lookup failed
            self.outcome.append(("failed", exc))
        finally:
            if connection is not None:
                with contextlib.suppress(Exception):
                    connection.close()

    def __enter__(self) -> "_BackgroundStatement":
        self._thread.start()
        deadline = time.monotonic() + 5.0
        while not self.backend_pid and not self.outcome and time.monotonic() < deadline:
            time.sleep(0.02)
        if self.backend_pid:
            return self
        # No backend pid yet: either startup already failed (self.outcome is
        # populated) or it is hanging. Join before raising so __enter__
        # never returns control — by raising — while a worker might still be
        # running; if it really is hung establishing a connection (not
        # observed against this codebase's Postgres), there is no backend
        # pid yet to cancel and this is a best-effort bound, not a guarantee.
        self._thread.join(timeout=5.0)
        if self.outcome:
            _status, exc = self.outcome[0]
            raise RuntimeError(
                f"background statement failed to establish a connection: {exc}"
            ) from exc
        raise RuntimeError(
            "background statement did not establish a connection within the 5s startup "
            "deadline, and reported no outcome"
        )

    def wait_until_blocked(self, poll_connection: Connection, label: str) -> None:
        """Blocks the caller until pg_stat_activity reports this statement's
        backend genuinely waiting on a lock — proof it is truly blocked, not
        merely running slowly. (`__enter__` already guarantees the backend
        connection itself exists by the time this is called.)"""
        assert self.backend_pid, f"{label}: backend pid missing (invariant violated by __enter__)"
        pid = self.backend_pid[0]

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

    def resume_and_get_outcome(self, label: str) -> tuple[str, Exception | None]:
        """Joins the thread (bounded) after the blocker has committed and
        asserts the original waiting statement actually resumed — not a
        substitute retry — then returns its real outcome."""
        self._thread.join(timeout=10.0)
        assert not self._thread.is_alive(), (
            f"{label} did not resume within 10s of the blocking transaction's commit"
        )
        assert self.outcome, f"{label} thread reported no outcome"
        return self.outcome[0]

    def _force_stop(self, pid: int) -> Exception | None:
        """Best-effort-but-verified attempt to make the worker's backend
        stop: signal it to end (pg_terminate_backend, falling back to
        pg_cancel_backend), then prove via a bounded join that the thread
        actually stopped. Returns None only once that is confirmed;
        otherwise returns an Exception describing every attempt made."""
        attempts: list[str] = []
        for description, sql in (
            ("pg_terminate_backend", "SELECT pg_terminate_backend(:p)"),
            ("pg_cancel_backend", "SELECT pg_cancel_backend(:p)"),
        ):
            canceller: Connection | None = None
            try:
                canceller = self._engine.connect()
                sent = canceller.execute(text(sql), {"p": pid}).scalar()
                canceller.commit()
                canceller.close()
            except Exception as exc:  # noqa: BLE001 - reported, not swallowed
                attempts.append(f"{description} raised {type(exc).__name__}: {exc}")
                if canceller is not None:
                    # Don't let a canceller connection that itself hit an
                    # error be silently returned to the shared pool.
                    with contextlib.suppress(Exception):
                        canceller.invalidate()
                continue
            if not sent:
                attempts.append(f"{description} reported failure (no signalable backend {pid})")
                continue
            self._thread.join(timeout=5.0)
            if not self._thread.is_alive():
                return None
            attempts.append(f"{description} signal accepted but worker did not stop within 5s")
        return RuntimeError(
            f"could not verify backend pid {pid} was stopped: " + "; ".join(attempts)
        )

    def __exit__(self, exc_type: object, exc: BaseException | None, tb: object) -> bool:
        cleanup_error: Exception | None = None
        if self._thread.is_alive():
            pid = self.backend_pid[0]
            cleanup_error = self._force_stop(pid)
        if cleanup_error is None and self._thread.is_alive():
            # Independent final proof point, regardless of what _force_stop
            # believed happened above.
            cleanup_error = RuntimeError(
                "background worker thread is still alive after forced cleanup — a "
                "connection, transaction, or advisory lock may have survived the with block"
            )
        if cleanup_error is None:
            return False
        if exc is not None:
            exc.add_note(f"_BackgroundStatement cleanup also failed: {cleanup_error}")
            return False
        raise cleanup_error


# ---------------------------------------------------------------------------
# _BackgroundStatement's own cleanup contract
# ---------------------------------------------------------------------------
# The helper above is tested in isolation from any production trigger or
# advisory-lock function: a plain pg_advisory_xact_lock stands in for
# whatever a real blocked statement would be waiting on. That keeps these
# tests from depending on (or having to deliberately break) revision 048/053/
# 056's actual locking logic, while still proving the helper's own forced-
# cleanup guarantees hold against a genuinely blocked backend.


class _SentinelFailure(Exception):
    """A synthetic, easily-distinguished failure standing in for "the with
    block's body raised" — used to prove forced cleanup preserves whatever
    exception was already propagating rather than replacing or losing it."""


def _lock_statement(key: int) -> Callable[[Connection], None]:
    def _acquire(conn: Connection) -> None:
        conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": key})

    return _acquire


def test_background_statement_forced_cleanup_terminates_a_genuinely_blocked_worker(
    postgres_engine: Engine,
) -> None:
    """The main thread's transaction never commits — deliberately, since the
    point is proving forced cleanup, not normal resumption — and the `with`
    block exits early via a synthetic failure while the worker is still
    genuinely blocked on the lock. Cleanup must still terminate it."""
    engine = postgres_engine
    lock_key = uuid.uuid4().int % (2**63 - 1)

    with engine.connect() as first:
        first.begin()
        first.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": lock_key})

        worker_pid: int | None = None
        with (
            pytest.raises(_SentinelFailure),
            _BackgroundStatement(engine, _lock_statement(lock_key)) as blocked,
        ):
            blocked.wait_until_blocked(first, "the sentinel-blocked worker")
            worker_pid = blocked.backend_pid[0]
            raise _SentinelFailure("deliberate failure while the worker is still blocked")

        assert worker_pid is not None
        # Checked from a fresh, independent connection rather than `first`:
        # `first` still holds the lock the worker was waiting on, and a
        # backend that dies while queued as a *waiter* on a lock a live
        # session still holds can keep appearing in that same session's view
        # of pg_stat_activity until the lock itself is released — even
        # though the backend is already fully gone from every other
        # connection's point of view. A fresh connection is what proves the
        # worker's backend, connection, transaction, and advisory lock are
        # actually gone, not an artifact of asking the lock holder itself.
        still_present = True
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            with engine.connect() as checker:
                still_present = checker.execute(
                    text("SELECT EXISTS (SELECT 1 FROM pg_stat_activity WHERE pid = :p)"),
                    {"p": worker_pid},
                ).scalar()
            if not still_present:
                break
            time.sleep(0.05)
        assert still_present is False, (
            "forced cleanup must terminate the blocked worker's backend itself, not "
            "merely stop waiting on its thread — otherwise its connection, transaction, "
            "and advisory lock could all outlive the with block"
        )

        first.rollback()


def test_background_statement_reports_cleanup_failure_without_losing_the_original_exception(
    postgres_engine: Engine,
) -> None:
    """Fault injection: once the worker has genuinely connected and blocked,
    corrupt the recorded backend pid so __exit__'s termination/cancellation
    attempts target a backend that does not exist and are guaranteed to
    report failure — a real false result from Postgres, not a mock. The
    with block's own synthetic failure must still be what propagates, with
    the cleanup failure attached rather than discarded."""
    engine = postgres_engine
    lock_key = uuid.uuid4().int % (2**63 - 1)
    real_pid: int | None = None
    blocked: _BackgroundStatement | None = None

    with engine.connect() as first:
        first.begin()
        first.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": lock_key})

        with (
            pytest.raises(_SentinelFailure) as excinfo,
            _BackgroundStatement(engine, _lock_statement(lock_key)) as blocked,
        ):
            blocked.wait_until_blocked(first, "the fault-injected worker")
            real_pid = blocked.backend_pid[0]
            # Corrupt the tracked pid only — the real backend below is
            # untouched by this and is cleaned up directly, below, by
            # this test itself.
            blocked.backend_pid[0] = 2**31 - 1
            raise _SentinelFailure("deliberate failure with a corrupted cleanup target")

        assert isinstance(excinfo.value, _SentinelFailure), (
            "the original sentinel failure must still be what propagates"
        )
        notes = "\n".join(getattr(excinfo.value, "__notes__", []))
        assert "cleanup" in notes.lower() and "fail" in notes.lower(), (
            f"expected the cleanup failure to be reported on the propagated exception "
            f"via add_note, got notes: {notes!r}"
        )

        # Clean up the real worker backend now, while `first` still holds
        # the lock it is blocked on. Doing this before `first.rollback()`
        # is deliberate: once `first` releases the lock, the real
        # (uncorrupted) worker is free to resume and finish — racing this
        # termination against that natural resolution risks killing a
        # connection exactly as it is finishing its own normal close(),
        # which can leave a corrupted connection looking healthy to the
        # pool. Terminating first, while the worker is still guaranteed
        # blocked, is deterministic.
        with contextlib.suppress(Exception), engine.connect() as canceller:
            canceller.execute(text("SELECT pg_terminate_backend(:p)"), {"p": real_pid})
            canceller.commit()
        blocked._thread.join(timeout=5.0)
        assert not blocked._thread.is_alive(), (
            "the real (uncorrupted) worker backend must not survive test teardown"
        )

        first.rollback()


def test_background_statement_cleanup_failure_fails_the_test_when_no_original_exception(
    postgres_engine: Engine,
) -> None:
    """Same fault injection as above, but the with block exits normally —
    no exception of its own — while the worker is still genuinely blocked
    and its cleanup target has been corrupted. __exit__ itself must raise,
    since there is no already-propagating exception for it to attach the
    cleanup failure to."""
    engine = postgres_engine
    lock_key = uuid.uuid4().int % (2**63 - 1)
    real_pid: int | None = None
    blocked: _BackgroundStatement | None = None

    with engine.connect() as first:
        first.begin()
        first.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": lock_key})

        with (
            pytest.raises(RuntimeError, match="could not verify"),
            _BackgroundStatement(engine, _lock_statement(lock_key)) as blocked,
        ):
            blocked.wait_until_blocked(first, "the fault-injected worker")
            real_pid = blocked.backend_pid[0]
            blocked.backend_pid[0] = 2**31 - 1
            # No exception here: the block exits normally while the
            # worker is still blocked, so cleanup failing is the only
            # thing that can fail this test.

        # As above: terminate the real worker deterministically while
        # `first` still holds the lock, before releasing it, to avoid
        # racing a safety-net termination against the worker's own natural
        # resolution and normal connection close.
        with contextlib.suppress(Exception), engine.connect() as canceller:
            canceller.execute(text("SELECT pg_terminate_backend(:p)"), {"p": real_pid})
            canceller.commit()
        blocked._thread.join(timeout=5.0)
        assert not blocked._thread.is_alive(), (
            "the real (uncorrupted) worker backend must not survive test teardown"
        )

        first.rollback()


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
    insert commits, leaving the entity's type and its subtype row in
    agreement."""
    engine = postgres_engine
    slug = f"subtype-lock-generic-{uuid.uuid4().hex[:8]}"
    try:
        with engine.begin() as setup:
            world = make_world(setup, slug=slug)
            dungeon = make_location(setup, world, entity_type_code="dungeon")
            region_type = lookup_id(setup, "core", "entity_types", "entity_type_id", "region")

        def retype(conn: Connection) -> None:
            conn.execute(
                text("UPDATE core.entities SET entity_type_id = :t WHERE entity_id = :e"),
                {"t": region_type, "e": dungeon},
            )

        with engine.connect() as first:
            first.begin()

            # Transaction 1: insert the subtype row. Still uncommitted.
            first.execute(
                text("INSERT INTO world.dungeons (dungeon_id) VALUES (:d)"), {"d": dungeon}
            )

            with _BackgroundStatement(engine, retype) as blocked:
                blocked.wait_until_blocked(first, "the concurrent retype away from 'dungeon'")
                first.commit()
                result, exc = blocked.resume_and_get_outcome("the concurrent retype")

        assert result == "failed", f"expected the resumed retype to be rejected, got: {result}"
        assert "cannot change type" in str(exc)

        with engine.connect() as verify:
            entity_type = verify.execute(
                text(
                    "SELECT et.code FROM core.entities e "
                    "JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id "
                    "WHERE e.entity_id = :e"
                ),
                {"e": dungeon},
            ).scalar()
            has_dungeons_row = verify.execute(
                text("SELECT EXISTS (SELECT 1 FROM world.dungeons WHERE dungeon_id = :d)"),
                {"d": dungeon},
            ).scalar()
        assert entity_type == "dungeon", (
            "the committed subtype insert must have kept the entity dungeon-typed"
        )
        assert has_dungeons_row is True, (
            "the committed world.dungeons subtype row must remain — no subtype row may end up "
            "incompatible with core.entities.entity_type"
        )
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
    the retype commits — leaving no dungeon-area row dependent on an entity
    no longer registered as a dungeon."""
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

        def insert_area(conn: Connection) -> None:
            conn.execute(
                text("INSERT INTO world.dungeon_areas (dungeon_area_id) VALUES (:a)"),
                {"a": area},
            )

        with engine.connect() as first:
            first.begin()

            # Transaction 1: remove the marker, then retype the dungeon
            # away. Still uncommitted.
            first.execute(text("DELETE FROM world.dungeons WHERE dungeon_id = :d"), {"d": dungeon})
            first.execute(
                text("UPDATE core.entities SET entity_type_id = :t WHERE entity_id = :e"),
                {"t": region_type, "e": dungeon},
            )

            with _BackgroundStatement(engine, insert_area) as blocked:
                blocked.wait_until_blocked(first, "the concurrent dungeon_area insert")
                first.commit()
                result, exc = blocked.resume_and_get_outcome("the concurrent dungeon_area insert")

        assert result == "failed", f"expected the resumed insert to be rejected, got: {result}"
        assert "not dungeon" in str(exc)

        with engine.connect() as verify:
            entity_type = verify.execute(
                text(
                    "SELECT et.code FROM core.entities e "
                    "JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id "
                    "WHERE e.entity_id = :e"
                ),
                {"e": dungeon},
            ).scalar()
            has_dungeons_row = verify.execute(
                text("SELECT EXISTS (SELECT 1 FROM world.dungeons WHERE dungeon_id = :d)"),
                {"d": dungeon},
            ).scalar()
            has_area_row = verify.execute(
                text(
                    "SELECT EXISTS (SELECT 1 FROM world.dungeon_areas WHERE dungeon_area_id = :a)"
                ),
                {"a": area},
            ).scalar()
        assert entity_type == "region", "the committed retype must have taken effect"
        assert has_dungeons_row is False, "the committed marker removal must have taken effect"
        assert has_area_row is False, (
            "the rejected dungeon_area insert must not have taken effect — no dungeon-area row "
            "may remain dependent on an entity no longer registered as a dungeon"
        )
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
    resume and be rejected once the reparent commits, leaving the area
    parented under a location that is still genuinely dungeon-typed."""
    engine = postgres_engine
    slug = f"subtype-lock-reparent-{uuid.uuid4().hex[:8]}"
    try:
        with engine.begin() as setup:
            world = make_world(setup, slug=slug)
            old_dungeon = make_dungeon(setup, world, name="Old Dungeon")
            new_dungeon = make_dungeon(setup, world, name="New Dungeon")
            area = make_dungeon_area(setup, old_dungeon)
            region_type = lookup_id(setup, "core", "entity_types", "entity_type_id", "region")

        def retype(conn: Connection) -> None:
            conn.execute(
                text("UPDATE core.entities SET entity_type_id = :t WHERE entity_id = :e"),
                {"t": region_type, "e": new_dungeon},
            )

        with engine.connect() as first:
            first.begin()

            # Transaction 1: reparent the area under new_dungeon. Still
            # uncommitted.
            first.execute(
                text("UPDATE world.locations SET parent_location_id = :d WHERE location_id = :a"),
                {"d": new_dungeon, "a": area},
            )

            with _BackgroundStatement(engine, retype) as blocked:
                blocked.wait_until_blocked(first, "the concurrent retype away from 'dungeon'")
                first.commit()
                result, exc = blocked.resume_and_get_outcome("the concurrent retype")

        assert result == "failed", f"expected the resumed retype to be rejected, got: {result}"
        assert "still has" in str(exc) and "dungeon area" in str(exc)

        with engine.connect() as verify:
            new_dungeon_type = verify.execute(
                text(
                    "SELECT et.code FROM core.entities e "
                    "JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id "
                    "WHERE e.entity_id = :e"
                ),
                {"e": new_dungeon},
            ).scalar()
            area_parent = verify.execute(
                text("SELECT parent_location_id FROM world.locations WHERE location_id = :a"),
                {"a": area},
            ).scalar()
        assert new_dungeon_type == "dungeon", "the rejected retype must not have taken effect"
        assert area_parent == new_dungeon, (
            "the committed reparent must have taken effect, and the area's parent must still be "
            "genuinely dungeon-typed"
        )
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
    committed dungeon area and its parent may not be cleared, so it must
    never end up without a valid dungeon parent."""
    engine = postgres_engine
    slug = f"child-lock-insert-first-{uuid.uuid4().hex[:8]}"
    try:
        with engine.begin() as setup:
            world = make_world(setup, slug=slug)
            dungeon = make_dungeon(setup, world)
            area = make_location(
                setup, world, parent_location_id=dungeon, entity_type_code="dungeon_area"
            )

        def clear_parent(conn: Connection) -> None:
            conn.execute(
                text("UPDATE world.locations SET parent_location_id = NULL WHERE location_id = :a"),
                {"a": area},
            )

        with engine.connect() as first:
            first.begin()

            # Transaction 1: insert the pending dungeon_area row. Still
            # uncommitted.
            first.execute(
                text("INSERT INTO world.dungeon_areas (dungeon_area_id) VALUES (:a)"), {"a": area}
            )

            with _BackgroundStatement(engine, clear_parent) as blocked:
                blocked.wait_until_blocked(first, "the concurrent parent-clearing update")
                first.commit()
                result, exc = blocked.resume_and_get_outcome(
                    "the concurrent parent-clearing update"
                )

        assert result == "failed", f"expected the resumed update to be rejected, got: {result}"
        assert "cannot be cleared" in str(exc)

        with engine.connect() as verify:
            has_area_row = verify.execute(
                text(
                    "SELECT EXISTS (SELECT 1 FROM world.dungeon_areas WHERE dungeon_area_id = :a)"
                ),
                {"a": area},
            ).scalar()
            area_parent = verify.execute(
                text("SELECT parent_location_id FROM world.locations WHERE location_id = :a"),
                {"a": area},
            ).scalar()
        assert has_area_row is True, "the committed dungeon_area insert must have taken effect"
        assert area_parent == dungeon, (
            "the rejected parent-clearing update must not have taken effect — a dungeon area "
            "must never end up without a valid dungeon parent"
        )
    finally:
        _cleanup_world(engine, slug)


def test_a_concurrent_child_parent_clear_and_dungeon_area_insert_is_serialized(
    postgres_engine: Engine,
) -> None:
    """Reverse order: transaction 1 clears L's parent_location_id first
    (L is not yet a dungeon area, so this passes and stays open), then
    commits. Transaction 2's pending dungeon_area insert must resume and be
    rejected — L's parent is now NULL, not a dungeon, so no dungeon-area row
    may end up depending on it."""
    engine = postgres_engine
    slug = f"child-lock-update-first-{uuid.uuid4().hex[:8]}"
    try:
        with engine.begin() as setup:
            world = make_world(setup, slug=slug)
            dungeon = make_dungeon(setup, world)
            area = make_location(
                setup, world, parent_location_id=dungeon, entity_type_code="dungeon_area"
            )

        def insert_area(conn: Connection) -> None:
            conn.execute(
                text("INSERT INTO world.dungeon_areas (dungeon_area_id) VALUES (:a)"),
                {"a": area},
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

            with _BackgroundStatement(engine, insert_area) as blocked:
                blocked.wait_until_blocked(first, "the concurrent dungeon_area insert")
                first.commit()
                result, exc = blocked.resume_and_get_outcome("the concurrent dungeon_area insert")

        assert result == "failed", f"expected the resumed insert to be rejected, got: {result}"
        assert "no parent_location_id" in str(exc)

        with engine.connect() as verify:
            has_area_row = verify.execute(
                text(
                    "SELECT EXISTS (SELECT 1 FROM world.dungeon_areas WHERE dungeon_area_id = :a)"
                ),
                {"a": area},
            ).scalar()
            area_parent = verify.execute(
                text("SELECT parent_location_id FROM world.locations WHERE location_id = :a"),
                {"a": area},
            ).scalar()
        assert area_parent is None, "the committed parent-clearing update must have taken effect"
        assert has_area_row is False, (
            "the rejected dungeon_area insert must not have taken effect — no dungeon-area row "
            "may exist without a valid dungeon parent"
        )
    finally:
        _cleanup_world(engine, slug)
