# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""R1 and R2 over real HTTP, in both orders (P03-A A5b, design sections 9.2 and 10.4).

Both races run the real routes through `TestClient`, each request on its own thread and connection.
`tests/http_race_support.py::StatementGate` stops the first request at a named statement, while it
holds the locks it took before it, and the test observes through `pg_blocking_pids` that the second
request is genuinely waiting on that session before anything is released. Each case asserts the status
codes (no deadlock, no 5xx), the draft row (`row_version`, text, origin, provenance pair and watermark),
the release rows, the audit and receipt counts, and that the losing request wrote nothing.

The source profile is written by the fixture helper and the `player_profile` draft field by the
A5b seeding helper; nothing else in the test writes either.

R1  an unkeyed release of a draft with an uncovered player-profile field by a reveal holder, against a
    `canon.edit` deny on that releaser through the real resource-grant route.
R2  a permitted GM's edit of a released player-profile field, against a restricted releaser releasing
    the earlier draft version.
"""

import threading
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from tests.database.test_campaign_owner_gate import (  # noqa: F401 - fixtures used by name
    Gate,
    client_factory,
    g,
)
from tests.database.test_character_public_profile_api import (
    body,
    code,
    counts,
    error_code,
    read,
    release,
    release_rows,
    save,
)
from tests.database.test_character_public_profile_grant_denies import post_grant
from tests.database.test_character_public_profile_restrictions import npc  # noqa: F401 - fixture
from tests.database.test_character_reveal_delegation import (  # noqa: F401 - fixtures used by name
    Members,
    m,
)
from tests.database.test_player_profile_provenance_restrictions import (
    EXCERPT,
    copy_in,
    draft_state,
    release_provenance,
    source,  # noqa: F401 - fixture
)
from tests.database.test_r01_s2_profile_routes import idle_in_transaction
from tests.http_race_support import (
    WAIT_SECONDS,
    StatementGate,
    activity_report,
    run_in_thread,
    sessions_blocked_by,
    wait_until_blocked,
)

pytestmark = pytest.mark.database

Factory = Callable[[uuid.UUID], TestClient]

RELEASE_INSERT = r"INSERT INTO campaign\.character_public_profile_releases"
GRANT_INSERT = r"INSERT INTO security\.resource_grants"
DRAFT_UPDATE = r"UPDATE campaign\.character_public_profiles SET"


def _denies(engine: Engine, g: Gate, membership: uuid.UUID) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                text("""
                    SELECT count(*) FROM security.resource_grants rg
                    JOIN security.capabilities c ON c.capability_id = rg.capability_id
                    WHERE rg.campaign_id = :c AND rg.grantee_campaign_membership_id = :m
                      AND c.code = 'canon.edit' AND rg.effect = 'deny' AND rg.revoked_at IS NULL
                """),
                {"c": g.campaign_id, "m": membership},
            ).scalar_one()
        )


def _receipts(engine: Engine) -> int:
    """Stored idempotency receipts, over every receipt table."""
    with engine.connect() as connection:
        tables = connection.execute(
            text(
                "SELECT table_schema, table_name FROM information_schema.tables "
                "WHERE table_name LIKE '%idempot%' AND table_type = 'BASE TABLE'"
            )
        ).all()
        return sum(
            int(connection.execute(text(f"SELECT count(*) FROM {s}.{t}")).scalar_one())  # noqa: S608
            for s, t in tables
        )


def _grant(factory: Factory, g: Gate, npc: uuid.UUID) -> Callable[[], Any]:
    return lambda: post_grant(factory, g.o2_user_id, g, "canon.edit", npc, member=g.o1)


# --- R1 ---------------------------------------------------------------------------------------------------------


def test_r1_release_first_the_grant_waits_and_the_release_commits(
    client_factory: Factory, postgres_engine: Engine, g: Gate, npc: uuid.UUID, source: dict[str, str]
) -> None:  # fmt: skip
    assert copy_in(postgres_engine, g, npc, "public_appearance", "personality") == 1
    before = (counts(postgres_engine, g), _receipts(postgres_engine))
    with StatementGate(postgres_engine, RELEASE_INSERT) as gate:
        releasing = run_in_thread(
            "release", lambda: release(client_factory, g.o1_user_id, g, npc, 1)
        )
        gate.wait_reached()  # the release holds the draft FOR UPDATE and its membership lock
        granting = run_in_thread("grant", _grant(client_factory, g, npc))
        wait_until_blocked(postgres_engine, gate)  # the grant is waiting on the release's session
        assert not granting.finished() and not releasing.finished()
        gate.release()
        released, granted = releasing.wait("release"), granting.wait("grant")
    assert code(released) == 201, body(released)
    assert code(granted) == 201, body(granted)
    rows = release_rows(postgres_engine, g, npc)
    assert [r["version_number"] for r in rows] == [1] and rows[0]["public_appearance"] == source[
        "personality"
    ]
    assert release_provenance(postgres_engine, g, npc)[0]["appearance_origin"] == "player_profile"
    assert _denies(postgres_engine, g, g.o1) == 1
    state = draft_state(postgres_engine, g, npc)
    assert state["row_version"] == 1 and state["public_appearance"] == source["personality"]
    assert state["appearance_origin"] == "player_profile" and state["appearance_mark"] == 1
    # Afterwards the deny holds: the field the release covered is no longer restricted, so o1 reads it
    # and can release again; but a new copy is restricted and withheld from them.
    assert copy_in(postgres_engine, g, npc, "public_appearance", "goals") == 2
    view = body(read(client_factory, g.o1_user_id, g, npc))
    assert view["draft"]["public_appearance"] is None and view["can_release"] is False
    after = counts(postgres_engine, g)
    assert after[1] == before[0][1] + 1  # exactly one release


def test_r1_grant_first_the_release_waits_and_is_refused_after_the_deny_commits(
    client_factory: Factory, postgres_engine: Engine, g: Gate, npc: uuid.UUID, source: dict[str, str]
) -> None:  # fmt: skip
    assert copy_in(postgres_engine, g, npc, "public_appearance", "personality") == 1
    before_counts, before_receipts = counts(postgres_engine, g), _receipts(postgres_engine)
    before_state = draft_state(postgres_engine, g, npc)
    with StatementGate(postgres_engine, GRANT_INSERT) as gate:
        granting = run_in_thread("grant", _grant(client_factory, g, npc))
        gate.wait_reached()  # the grant holds the membership and the campaign locks it needs
        releasing = run_in_thread(
            "release", lambda: release(client_factory, g.o1_user_id, g, npc, 1)
        )
        wait_until_blocked(postgres_engine, gate)  # the release is waiting on the grant's session
        assert not releasing.finished()
        gate.release()
        granted, released = granting.wait("grant"), releasing.wait("release")
    assert code(granted) == 201, body(granted)
    # The release re-resolved the caller after its wait and found the deny: nothing was written.
    assert (code(released), error_code(released)) == (403, "public_profile_field_withheld")
    assert source["personality"] not in released.text
    assert release_rows(postgres_engine, g, npc) == []
    assert _denies(postgres_engine, g, g.o1) == 1
    assert draft_state(postgres_engine, g, npc) == before_state
    after_counts = counts(postgres_engine, g)
    # No draft row, release, save/release audit row or entity revision was added; the grant's own
    # audit row is not one of the counted profile commands.
    assert after_counts == before_counts
    assert _receipts(postgres_engine) == before_receipts  # an unkeyed release stores no receipt


# --- R2 ---------------------------------------------------------------------------------------------------------


def _released_pp_copy_with_a_later_authored_edit(
    client_factory: Factory, engine: Engine, g: Gate, m: Members, npc: uuid.UUID
) -> int:
    """Draft 1: the copied appearance. Release 1 by the permitted `o2` covers it. The permitted GM
    then edits the authored background (draft 2), so the restricted `o1` (which holds a `canon.edit`
    deny) may release draft 2: the player-profile field is covered. Returns 2."""
    assert copy_in(engine, g, npc, "public_appearance", "personality") == 1
    assert code(release(client_factory, g.o2_user_id, g, npc, 1)) == 201
    resp = post_grant(client_factory, g.o2_user_id, g, "canon.edit", npc, member=g.o1)
    assert code(resp) == 201, body(resp)
    edited = save(
        client_factory,
        m.gm_user_id,
        g,
        npc,
        {"expected_row_version": 1, "public_background": "authored"},
    )
    assert code(edited) == 200, body(edited)
    view = body(read(client_factory, g.o1_user_id, g, npc))
    assert view["draft"]["public_appearance_withheld"] is False and view["can_release"] is True
    return 2


#: The edit's gate must outlive the blocking wait it supports: `wait_until_blocked` may take up to `WAIT_SECONDS` (15 s)
#: after the release request has started, and the release request starts only after the edit has reached its gate. The
#: hold is therefore that wait plus a stated margin for the release request's own start (thread, client, routing); it is
#: **strict**, so a hold that still runs out fails the parked edit visibly instead of releasing it silently.
EDIT_HOLD_SECONDS = WAIT_SECONDS + 20.0


def _database_clock(engine: Engine) -> Any:
    with engine.connect() as connection:
        return connection.execute(text("SELECT clock_timestamp()")).scalar_one()


def _let_the_database_clock_pass(engine: Engine, seconds: float, *, stages: list[str]) -> None:
    """Hold the test until the **database's own clock** has advanced `seconds` since the call (polled, not a sleep of
    the test's choosing): the deliberate scheduling delay at the formerly vulnerable boundary."""
    start = _database_clock(engine)
    stages.append(f"delay begins at database time {start.isoformat()}")
    tick = threading.Event()
    while not tick.wait(0.1):
        now = _database_clock(engine)
        if (now - start).total_seconds() >= seconds:
            stages.append(f"delay ends at database time {now.isoformat()}")
            return


def _capture(
    engine: Engine,
    g: Gate,
    npc: uuid.UUID,
    gate: StatementGate,
    requests: tuple[Any, ...],
    stages: list[str],
) -> str:
    """Everything a failed setup needs, taken **before** cleanup changes it: stages, request outcomes, the gate, the
    backends and the pool, and the durable records."""
    parts = ["STAGES: " + " | ".join(stages), f"GATE: {gate.describe()}"]
    parts += [f"REQUEST: {r.describe()}" for r in requests if r is not None]
    parts.append(activity_report(engine))
    parts.append(f"POOL: {engine.pool.status()}")  # type: ignore[attr-defined]
    try:
        parts.append(f"DRAFT: {draft_state(engine, g, npc)}")
        parts.append(f"RELEASES: {release_rows(engine, g, npc)}")
        parts.append(f"RECEIPTS: {_receipts(engine)}  COUNTS: {counts(engine, g)}")
    except Exception as exc:  # noqa: BLE001 - a diagnostic never masks the failure
        parts.append(f"durable records unavailable: {exc!r}")
    return "\n".join(parts)


@pytest.mark.parametrize("scheduling", ("prompt", "delayed"))
def test_r2_edit_first_the_release_of_the_earlier_version_is_stale_and_writes_nothing(
    scheduling: str, client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members,
    npc: uuid.UUID, source: dict[str, str],
) -> None:  # fmt: skip
    """R2, edit first. The edit is parked at its draft `UPDATE` (it holds the draft `FOR UPDATE`); the release request is
    then started and **observed blocked behind that backend** (`pg_blocking_pids`) before anything is released.

    Synchronization: the edit's gate is strict and holds `EDIT_HOLD_SECONDS`, longer than the blocking wait it supports, so
    it cannot be released by timeout while the block is still being established (the weakness of the earlier version: a
    15-second hold that began at the gate and a 15-second blocking wait that began later, so on a loaded machine the gate
    released the edit at about the moment the wait expired). The wait is still bounded by `WAIT_SECONDS`; the hold by its
    own budget. A failure captures stages, request outcomes, the gate, backends, pool and durable records before the gate
    is released and both workers have been joined; the listener is removed only after both have finished.

    `scheduling="delayed"` inserts a deliberate delay at the formerly vulnerable boundary: the release request is not
    started until the *database clock* shows more than the old 15-second hold has passed with the edit parked. With the
    old gate the edit would have been released silently before the release request even began."""
    version = _released_pp_copy_with_a_later_authored_edit(
        client_factory, postgres_engine, g, m, npc
    )
    releases_before, receipts_before, counts_before = (
        release_rows(postgres_engine, g, npc),
        _receipts(postgres_engine),
        counts(postgres_engine, g),
    )
    stages: list[str] = []
    with StatementGate(
        postgres_engine, DRAFT_UPDATE, hold_seconds=EDIT_HOLD_SECONDS, strict=True
    ) as gate:
        editing = releasing = None
        try:
            editing = run_in_thread(
                "edit",
                lambda: save(
                    client_factory, m.gm_user_id, g, npc,
                    {"expected_row_version": version, "public_appearance": EXCERPT}, key="r2-edit-1",
                ),
            )  # fmt: skip
            gate.track(editing)
            gate.wait_reached()  # the edit holds the draft FOR UPDATE
            stages.append(f"edit parked at the draft UPDATE on pid {gate.pid}")
            if scheduling == "delayed":
                _let_the_database_clock_pass(postgres_engine, WAIT_SECONDS + 2.0, stages=stages)
                assert not gate.expired, (
                    f"the strict gate expired during the delay: {gate.describe()}"
                )
            releasing = run_in_thread(
                "release", lambda: release(client_factory, g.o1_user_id, g, npc, version)
            )
            gate.track(releasing)
            stages.append("release request started")
            wait_until_blocked(postgres_engine, gate)
            assert gate.pid is not None
            blocked_behind_edit = sessions_blocked_by(postgres_engine, gate.pid)
            stages.append(f"release observed blocked behind pid {gate.pid} ({blocked_behind_edit})")
            assert blocked_behind_edit >= 1 and not gate.expired and gate.released_by is None, (
                gate.describe()
            )
            gate.release()
        except BaseException as exc:
            # before cleanup changes anything: capture, then release and join both workers (bounded)
            note = _capture(postgres_engine, g, npc, gate, (editing, releasing), stages)
            exc.add_note(note)
            gate.release()
            raise  # the gate's __exit__ now waits (bounded) for the tracked workers and keeps the listener if one is active
        edited, released = editing.wait("edit"), releasing.wait("release")
        assert (
            editing.done.is_set() and releasing.done.is_set()
        )  # both finished before the listener is removed
    assert gate.released_by == "test" and not gate.expired, gate.describe()
    assert code(edited) == 200 and body(edited)["row_version"] == version + 1, body(edited)
    # The restricted releaser never saw the new text: the release names a draft version that is gone.
    assert (code(released), error_code(released)) == (409, "stale_write"), released.text
    assert EXCERPT not in released.text
    # no prohibited release write: no release row; the edit's own audit row only
    assert release_rows(postgres_engine, g, npc) == releases_before
    assert _receipts(postgres_engine) == receipts_before + 1  # the edit's receipt only
    drafts, releases, audits, revisions = counts(postgres_engine, g)
    assert (drafts, releases) == counts_before[:2] and audits == counts_before[2] + 1, (
        counts_before,
        (drafts, releases, audits, revisions),
    )
    state = draft_state(postgres_engine, g, npc)
    assert state["row_version"] == version + 1 and state["public_appearance"] == EXCERPT
    assert (
        state["appearance_origin"] == "player_profile" and state["appearance_mark"] == version + 1
    )
    assert state["a_pp_version"] is not None and state["a_pp_field"] is not None
    # Afterwards the field is withheld from the restricted reader and visible to the permitted one.
    restricted = body(read(client_factory, g.o1_user_id, g, npc))["draft"]
    assert (
        restricted["public_appearance"] is None and restricted["public_appearance_withheld"] is True
    )
    permitted = body(read(client_factory, g.o2_user_id, g, npc))["draft"]
    assert permitted["public_appearance"] == EXCERPT


def test_r2_release_first_covers_only_the_earlier_text_and_the_edit_restricts_again(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, npc: uuid.UUID,
    source: dict[str, str],
) -> None:  # fmt: skip
    version = _released_pp_copy_with_a_later_authored_edit(
        client_factory, postgres_engine, g, m, npc
    )
    with StatementGate(postgres_engine, RELEASE_INSERT) as gate:
        releasing = run_in_thread(
            "release", lambda: release(client_factory, g.o1_user_id, g, npc, version)
        )
        gate.wait_reached()  # the release holds the draft FOR UPDATE
        editing = run_in_thread(
            "edit",
            lambda: save(
                client_factory, m.gm_user_id, g, npc,
                {"expected_row_version": version, "public_appearance": EXCERPT},
            ),
        )  # fmt: skip
        wait_until_blocked(postgres_engine, gate)  # the edit waits on the draft row
        assert not editing.finished()
        gate.release()
        released, edited = releasing.wait("release"), editing.wait("edit")
    assert code(released) == 201 and body(released)["version_number"] == 2, body(released)
    assert code(edited) == 200 and body(edited)["row_version"] == version + 1, body(edited)
    rows = release_rows(postgres_engine, g, npc)
    assert [r["public_appearance"] for r in rows] == [source["personality"], source["personality"]]
    assert [r["appearance_origin"] for r in release_provenance(postgres_engine, g, npc)] == [
        "player_profile"
    ] * 2
    state = draft_state(postgres_engine, g, npc)
    assert state["public_appearance"] == EXCERPT and state["appearance_mark"] == version + 1
    assert state["row_version"] == version + 1
    # The new text is past release 2 (draft 2): restricted again, withheld from o1, readable by o2.
    restricted = body(read(client_factory, g.o1_user_id, g, npc))
    assert restricted["draft"]["public_appearance"] is None and restricted["can_release"] is False
    assert EXCERPT not in str(restricted)
    assert body(read(client_factory, g.o2_user_id, g, npc))["draft"]["public_appearance"] == EXCERPT


class _ControlledWorker:
    """A stand-in worker whose completion the test controls with an event (no sleeps)."""

    def __init__(self) -> None:
        self.name = "controlled"
        self.done = threading.Event()

    def describe(self) -> str:
        return f"controlled: {'finished' if self.done.is_set() else 'still running'}"


def _park_edit_and_block_release(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, npc: uuid.UUID, version: int,
    gate: StatementGate,
) -> tuple[Any, Any]:  # fmt: skip
    editing = run_in_thread(
        "edit",
        lambda: save(
            client_factory, m.gm_user_id, g, npc,
            {"expected_row_version": version, "public_appearance": EXCERPT}, key="r2-cleanup-1",
        ),
    )  # fmt: skip
    gate.track(editing)
    gate.wait_reached()
    releasing = run_in_thread(
        "release", lambda: release(client_factory, g.o1_user_id, g, npc, version)
    )
    gate.track(releasing)
    wait_until_blocked(postgres_engine, gate)
    return editing, releasing


def test_a_failure_after_the_block_is_established_finishes_both_workers_before_the_listener_is_removed(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, npc: uuid.UUID,
    source: dict[str, str],
) -> None:  # fmt: skip
    """*cleanup path*: the test body fails while the edit is parked and the release is blocked behind it. The original
    failure is the one that propagates; the gate is released, **both workers finish** (edit 200, release 409, no leaked
    transaction, no checked-out connection) and only then is the listener removed."""
    from sqlalchemy import event

    version = _released_pp_copy_with_a_later_authored_edit(
        client_factory, postgres_engine, g, m, npc
    )
    seen: dict[str, Any] = {}

    class Injected(RuntimeError):
        pass

    with (
        pytest.raises(Injected) as raised,
        StatementGate(
            postgres_engine, DRAFT_UPDATE, hold_seconds=EDIT_HOLD_SECONDS, strict=True
        ) as gate,
    ):
        seen["gate"] = gate
        try:
            editing, releasing = _park_edit_and_block_release(
                client_factory, postgres_engine, g, m, npc, version, gate
            )
            seen["workers"] = (editing, releasing)
            raise Injected("the test's own failure while the block is established")
        except BaseException as exc:
            exc.add_note("diagnostics captured here, before cleanup")
            gate.release()
            raise
    assert "diagnostics captured here, before cleanup" in raised.value.__notes__
    editing, releasing = seen["workers"]
    gate = seen["gate"]
    assert editing.done.is_set() and releasing.done.is_set(), (
        "both workers finished before the listener went"
    )
    assert (code(editing.result), code(releasing.result)) == (200, 409)
    assert not gate.listener_retained and gate.listener_removed.is_set()
    assert not event.contains(postgres_engine, "before_cursor_execute", gate._hook)
    assert idle_in_transaction(postgres_engine) == 0
    assert postgres_engine.pool.checkedout() == 0  # type: ignore[attr-defined]


def test_a_worker_still_active_after_the_cleanup_wait_keeps_the_listener_until_it_finishes(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, npc: uuid.UUID,
    source: dict[str, str],
) -> None:  # fmt: skip
    """*cleanup path, controlled*: the real workers finish, but a third tracked worker is held unfinished by an event
    beyond the (short) cleanup wait. The unfinished state is detected and explicit, the original failure still
    propagates, the listener **stays installed**, and it is removed only after the worker is let go. A genuine cleanup
    failure (no other exception in flight) is an `AssertionError`, not a silent pass."""
    from sqlalchemy import event

    version = _released_pp_copy_with_a_later_authored_edit(
        client_factory, postgres_engine, g, m, npc
    )
    stuck = _ControlledWorker()
    seen: dict[str, Any] = {}

    with (
        pytest.raises(RuntimeError, match="the test's own failure") as raised,
        StatementGate(
            postgres_engine,
            DRAFT_UPDATE,
            hold_seconds=EDIT_HOLD_SECONDS,
            strict=True,
            cleanup_seconds=3.0,
        ) as gate,
    ):
        seen["gate"] = gate
        gate.track(stuck)
        try:
            _park_edit_and_block_release(client_factory, postgres_engine, g, m, npc, version, gate)
            raise RuntimeError("the test's own failure")
        except BaseException:
            gate.release()
            raise
    gate = seen["gate"]
    assert gate.listener_retained and not gate.listener_removed.is_set()
    assert any(
        "RETAINED" in note and "controlled: still running" in note
        for note in raised.value.__notes__
    )
    assert event.contains(postgres_engine, "before_cursor_execute", gate._hook), (
        "installed while a worker is active"
    )
    stuck.done.set()  # the worker finishes: removal is now permitted
    assert gate.listener_removed.wait(WAIT_SECONDS)
    assert not event.contains(postgres_engine, "before_cursor_execute", gate._hook)
    assert idle_in_transaction(postgres_engine) == 0
    assert postgres_engine.pool.checkedout() == 0  # type: ignore[attr-defined]

    # no other failure in flight: the unfinished worker is itself the failure
    stuck_again = _ControlledWorker()
    with (
        pytest.raises(AssertionError, match="RETAINED"),
        StatementGate(postgres_engine, DRAFT_UPDATE, cleanup_seconds=0.2) as later,
    ):
        later.track(stuck_again)
    assert later.listener_retained and event.contains(
        postgres_engine, "before_cursor_execute", later._hook
    )
    stuck_again.done.set()
    assert later.listener_removed.wait(WAIT_SECONDS)
