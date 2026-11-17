# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""R01 E1, residual R-3: three-party queueing on the knowledge item between the human reveal, the proposal review and a
definition edit, over the real routes.

The question (design `docs/R01_E1_REVIEW_ROUTE_DESIGN_2026-11-17.md`, 4.2, residual R-3). Human reveal takes the claim's
`core.entities` row `FOR SHARE` (`_lock_claim`) and *then* the `knowledge.knowledge_items` row `FOR UPDATE OF ki`
(`_lock_knowledge_item`). The review's reveal branch takes them the other way round (`ki FOR UPDATE`, then the entity
`FOR SHARE` in `require_state_targetable`). Two requests alone cannot deadlock on that (`SHARE`/`SHARE` is compatible). A
third, the definition edit, requests the entity `FOR UPDATE` (`lock_entities`), which conflicts with the reveal's `SHARE`.
If a queued `FOR UPDATE` made a *later* `FOR SHARE` request wait behind it, the schedule would close a cycle:

    review --FOR SHARE (entity)--> queued edit --FOR UPDATE (entity)--> reveal --FOR UPDATE (ki)--> review

The schedule is built with statement gates, not sleeps, on the real routes:

1. the human reveal holds the entity `FOR SHARE` and is parked **before** its `ki FOR UPDATE`;
2. the review holds `ki FOR UPDATE` and is parked **before** its entity `FOR SHARE`;
3. the definition edit requests the entity `FOR UPDATE` and is observed queued behind the reveal;
4. the review is released toward its entity lock, then the reveal toward its `ki` lock.

Outcome (observed, pinned by the first test): the edge does **not** form. The review's `FOR SHARE` is compatible with the
reveal's `FOR SHARE`, so it joins the row's share lockers (a multixact) and does not wait behind the queued `FOR UPDATE`;
it commits while the edit is still queued. The second test is the control: the same schedule with an exclusive review lock
does form the cycle, one 40P01.

Every step records the actual SQL of each backend, the lock modes and the queue (`pg_blocking_pids`, `pg_locks`) *before*
anything is released or cleaned up. With `R3_REPORT=<file>` set, each snapshot is appended as one JSON line (evidence only,
never an assertion).
"""

import contextlib
import json
import os
import re
import threading
import time
import uuid
from typing import Any

import pytest
from sqlalchemy import Engine, event, text

from tests.database.test_r01_e1_review_route import (  # noqa: F401
    Scene,
    new_proposal,
    review_call,
    sc,
)
from tests.database.test_r01_s3_authoring_routes import code
from tests.database.test_r01_s5e2_lock_order import (  # noqa: F401 - fixtures by name
    PATIENCE,
    Pool,
    deadlocks_now,
    finish,
    pool,
    post,
    rows,
    settled_deadlock_delta,
)
from tests.factories import make_world_role_assignment
from tests.http_race_support import StatementGate, run_in_thread

pytestmark = pytest.mark.database

# the human reveal's and the review's statement that locks the knowledge row (the same SQL in both: `_lock_knowledge_item`)
KI_FOR_UPDATE = (
    r"FROM knowledge\.knowledge_items ki JOIN core\.entities e ON e\.entity_id = ki\.knowledge_item_id "
    r"WHERE ki\.knowledge_item_id = \S+ FOR UPDATE OF ki$"
)
# the review's entity lock: `require_state_targetable` (an `ANY(...)` id list), not `lock_entities` (one id, with a world)
ENTITY_FOR_SHARE_GUARD = r"FROM core\.entities e WHERE e\.entity_id = ANY\(CAST\(\S+ AS uuid\[\]\)\) ORDER BY e\.entity_id FOR SHARE OF e$"
# the control's variant: the same guard, but with an exclusive lock (see `test_r3_control_...`)
ENTITY_FOR_UPDATE_GUARD = r"FROM core\.entities e WHERE e\.entity_id = ANY\(CAST\(\S+ AS uuid\[\]\)\) ORDER BY e\.entity_id FOR UPDATE OF e$"
ENTITY_FOR_UPDATE = re.compile(
    r"FROM core\.entities e WHERE e\.entity_id = \S+ AND e\.world_id = \S+ FOR UPDATE OF e$"
)


class PidRecorder:
    """Every statement each backend executes, keyed by backend pid, in order (the actual SQL, normalized whitespace)."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.by_pid: dict[int, list[str]] = {}
        self._lock = threading.Lock()

    def _hook(self, conn: Any, _cursor: Any, statement: Any, *_: Any) -> None:
        pid = conn.connection.driver_connection.info.backend_pid
        with self._lock:
            self.by_pid.setdefault(pid, []).append(" ".join(str(statement).split()))

    def __enter__(self) -> "PidRecorder":
        event.listen(self.engine, "before_cursor_execute", self._hook)
        return self

    def __exit__(self, *_: object) -> None:
        with contextlib.suppress(Exception):
            event.remove(self.engine, "before_cursor_execute", self._hook)

    def statements(self, pid: int) -> list[str]:
        with self._lock:
            return list(self.by_pid.get(pid, []))


BACKENDS = r"""
    SELECT pid, state, wait_event_type, wait_event, pg_blocking_pids(pid) AS blockers,
           regexp_replace(query, '\s+', ' ', 'g') AS query
    FROM pg_stat_activity WHERE datname = current_database() AND pid = ANY(:pids)
"""
TUPLE_AND_XID_LOCKS = r"""
    SELECT l.pid, l.locktype, l.mode, l.granted,
           CASE WHEN l.locktype = 'tuple' THEN l.relation::regclass::text END AS relation,
           CASE WHEN l.locktype = 'transactionid' THEN l.transactionid::text END AS xid
    FROM pg_locks l WHERE l.pid = ANY(:pids) AND l.locktype IN ('tuple', 'transactionid')
    ORDER BY l.pid, l.locktype, l.granted DESC
"""
ROW_XMAX = "SELECT xmax::text AS xmax FROM core.entities WHERE entity_id = :e"
# the row-level lockers of the claim's `core.entities` row and their modes (contrib `pgrowlocks`; supporting evidence only,
# skipped without the extension)
ROW_LOCKERS = """
    SELECT multi, modes, pids FROM pgrowlocks('core.entities')
    WHERE locked_row = (SELECT ctid FROM core.entities WHERE entity_id = :e)
"""


class Snapshots:
    """Backend states, queue edges, tuple/xid locks and statements, captured before any release."""

    def __init__(
        self, admin: Engine, names: dict[str, int], recorder: PidRecorder, entity: uuid.UUID
    ) -> None:
        self.admin = admin
        self.names = names
        self.recorder = recorder
        self.entity = entity
        self.taken: list[dict[str, Any]] = []

    def _row_lockers(self, by_pid: dict[int, str]) -> list[dict[str, Any]] | None:
        try:
            with self.admin.begin() as c:
                c.execute(text("CREATE EXTENSION IF NOT EXISTS pgrowlocks"))
            found = rows(self.admin, ROW_LOCKERS, e=self.entity)
        except Exception:  # noqa: BLE001 - supporting evidence; the contrib module may be absent
            return None
        return [
            {
                "multi": f["multi"],
                "modes": f["modes"],
                "backends": [by_pid.get(x, x) for x in f["pids"]],
            }
            for f in found
        ]

    def take(self, step: str) -> dict[str, Any]:
        pids = list(self.names.values())
        by_pid = {pid: name for name, pid in self.names.items()}
        with self.admin.connect() as c:
            backends = [dict(r._mapping) for r in c.execute(text(BACKENDS), {"pids": pids})]
            locks = [dict(r._mapping) for r in c.execute(text(TUPLE_AND_XID_LOCKS), {"pids": pids})]
        snap = {
            "step": step,
            "entity_xmax": rows(self.admin, ROW_XMAX, e=self.entity)[0]["xmax"],
            "entity_row_lockers": self._row_lockers(by_pid),
            "step_statements_by_backend": {
                name: len(self.recorder.statements(pid)) for name, pid in self.names.items()
            },
            "backends": {
                by_pid[b["pid"]]: {
                    "pid": b["pid"],
                    "state": b["state"],
                    "wait": f"{b['wait_event_type']}/{b['wait_event']}",
                    "blocked_by": [by_pid.get(x, x) for x in b["blockers"]],
                    "query": b["query"][:170],
                }
                for b in backends
                if b["pid"] in by_pid
            },
            "locks": [
                {**lk, "pid": by_pid.get(lk["pid"], lk["pid"])}
                for lk in locks
                if lk["locktype"] == "tuple" or lk["granted"] is False
            ],
        }
        self.taken.append(snap)
        report = os.environ.get("R3_REPORT")
        if report:
            with open(report, "a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {"test": os.environ.get("PYTEST_CURRENT_TEST", "").split(" ")[0], **snap},
                        default=str,
                    )
                    + chr(10)
                )
        return snap


def wait_for(predicate: Any, why: str, admin: Engine, seconds: float = PATIENCE) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for: {why}")


def reach(gate: StatementGate, request: Any, what: str) -> int:
    """Waits for the gate, but fails at once (with the answer) if the request finishes without reaching it."""
    deadline = time.monotonic() + PATIENCE
    while time.monotonic() < deadline:
        if gate.reached.wait(0.05):
            assert gate.pid is not None
            return gate.pid
        if request.finished():
            raise AssertionError(
                f"INCOMPATIBLE SCHEDULE (not a finding): {what}: {request.describe()}"
            )
    raise AssertionError(f"{what}: gate not reached: {request.describe()}")


def lock_waiters_not_in(
    admin: Engine, known: set[int], pool_pids: list[int]
) -> list[dict[str, Any]]:
    """Backends of the pool that wait on a lock and are not one of `known` (the definition edit, found by its wait)."""
    with admin.connect() as c:
        return [
            dict(r._mapping)
            for r in c.execute(
                text(
                    r"SELECT pid, pg_blocking_pids(pid) AS blockers, regexp_replace(query, '\s+', ' ', 'g') AS query "
                    "FROM pg_stat_activity WHERE datname = current_database() AND wait_event_type = 'Lock' "
                    "AND pid = ANY(:pids) AND NOT (pid = ANY(:known))"
                ),
                {"pids": pool_pids, "known": list(known)},
            )
        ]


def review_is_lock_waiting(admin: Engine, pid: int) -> bool:
    with admin.connect() as c:
        return bool(
            c.execute(
                text("SELECT wait_event_type = 'Lock' FROM pg_stat_activity WHERE pid = :p"),
                {"p": pid},
            ).scalar()
        )


def human_reveal(sc: Scene, p: Pool) -> Any:
    return post(
        p,
        sc.owner,
        f"{sc.base}/knowledge/{sc.secret_id}/reveal-to-party",
        {
            "party_id": str(sc.f.party_id),
            "awareness_level": "aware",
            "world_time_id": str(sc.f.world_time_id),
        },
        **{"Idempotency-Key": f"r3-reveal-{uuid.uuid4().hex[:10]}"},
    )


def definition_edit(sc: Scene, p: Pool, body: dict[str, Any]) -> Any:
    return post(
        p,
        sc.owner,
        f"{sc.base}/authoring/knowledge/{sc.secret_id}/update",
        body,
        **{"Idempotency-Key": f"r3-edit-{uuid.uuid4().hex[:10]}"},
    )


def edit_body(sc: Scene) -> dict[str, Any]:
    """A sensitivity-only change (a definition edit that is not refused as 'already known' once the item is revealed)."""
    current = rows(
        sc.engine,
        """
        SELECT ki.canonical_statement AS statement, kt.code AS knowledge_type, ts.code AS truth_status,
               ki.sensitivity, ki.subject_entity_id, e.row_version
        FROM knowledge.knowledge_items ki
        JOIN knowledge.knowledge_types kt ON kt.knowledge_type_id = ki.knowledge_type_id
        JOIN knowledge.truth_statuses ts ON ts.truth_status_id = ki.truth_status_id
        JOIN core.entities e ON e.entity_id = ki.knowledge_item_id
        WHERE ki.knowledge_item_id = :k
        """,
        k=sc.secret_id,
    )[0]
    return {
        "statement": current["statement"],
        "knowledge_type": current["knowledge_type"],
        "truth_status": current["truth_status"],
        "sensitivity": "restricted" if current["sensitivity"] != "restricted" else "public",
        "subject_entity_id": str(current["subject_entity_id"]),
        "expected_row_version": current["row_version"],
        "change_note": "R-3 three-party schedule",
    }


def durable_state(sc: Scene, proposal: uuid.UUID) -> dict[str, Any]:
    return rows(
        sc.engine,
        """
        SELECT (SELECT status FROM ai.proposed_changes WHERE ai_proposed_change_id = :p) AS proposal_status,
               (SELECT count(*) FROM ai.change_reviews WHERE ai_proposed_change_id = :p) AS reviews,
               (SELECT count(*) FROM campaign.party_knowledge WHERE knowledge_item_id = :k) AS party_knowledge,
               (SELECT count(*) FROM narrative.events WHERE campaign_id = :c AND event_type_id =
                   (SELECT event_type_id FROM narrative.event_types WHERE code = 'knowledge_revealed')) AS reveal_events,
               (SELECT sensitivity FROM knowledge.knowledge_items WHERE knowledge_item_id = :k) AS sensitivity,
               (SELECT row_version FROM core.entities WHERE entity_id = :k) AS row_version
        """,
        p=proposal,
        c=sc.campaign_id,
        k=sc.secret_id,
    )[0]


@pytest.fixture
def owner_is_world_editor(sc: Scene) -> Any:
    """The definition edit needs `world.canon.edit`: an open `world_editor` assignment for the campaign owner."""
    with sc.engine.begin() as c:
        membership = make_world_role_assignment(
            c, sc.f.world_id, sc.owner, "world_editor", granted_by_user_id=sc.owner
        )
    try:
        yield membership
    finally:
        with sc.engine.begin() as c:
            c.execute(
                text("DELETE FROM security.world_memberships WHERE world_membership_id = :m"),
                {"m": membership},
            )


def run_schedule(sc: Scene, p: Pool, *, exclusive_review_lock: bool = False) -> dict[str, Any]:
    """Steps 1 to 4 of the module docstring; returns everything observed (nothing is asserted here).

    `exclusive_review_lock` is the control only: the review's entity lock is then exclusive (the caller has patched it), so
    in step 4a the review is *expected to wait* instead of finishing."""
    proposal = new_proposal(sc, "reveal")
    body = edit_body(sc)
    before = deadlocks_now(sc.engine)
    seen: dict[str, Any] = {"proposal": proposal, "body_sensitivity": body["sensitivity"]}
    with PidRecorder(p.engine) as recorder, contextlib.ExitStack() as stack:
        names: dict[str, int] = {}
        snaps = Snapshots(sc.engine, names, recorder, sc.secret_id)
        seen["snaps"] = snaps

        # Both gates are armed before any request starts: adding a listener while a request is parked inside the dispatch
        # of another gate mutates the list that request is iterating (RuntimeError on resume: a machinery defect, found
        # in the first exploratory run, never a finding). Neither pattern can fire early: the reveal's own entity lock is
        # `lock_entities` (one id with a world), not the `ANY(...)` guard, and each gate fires once.
        gate_reveal = stack.enter_context(
            StatementGate(p.engine, KI_FOR_UPDATE, hold_seconds=120, strict=True)
        )
        gate_review = stack.enter_context(
            StatementGate(
                p.engine,
                ENTITY_FOR_UPDATE_GUARD if exclusive_review_lock else ENTITY_FOR_SHARE_GUARD,
                hold_seconds=120,
                strict=True,
            )
        )

        # runs first on exit (LIFO): a failure anywhere never leaves a request parked
        stack.callback(lambda: (gate_reveal.release(), gate_review.release()))

        def start(name: str, operation: Any) -> Any:
            request = run_in_thread(name, operation)
            gate_reveal.track(request)
            gate_review.track(request)
            return request

        # 1. the human reveal: entity FOR SHARE held, parked before its ki FOR UPDATE
        reveal = start("reveal", lambda: human_reveal(sc, p))
        names["reveal"] = reach(gate_reveal, reveal, "the reveal never reached its ki lock")
        seen["reveal_gate_statement"] = gate_reveal.matched
        snaps.take("1_reveal_parked_before_ki")

        # 2. the review: ki FOR UPDATE held, parked before its entity FOR SHARE
        review = start("review", lambda: review_call(sc, p, proposal, "approve"))
        names["review"] = reach(gate_review, review, "the review never reached its entity lock")
        seen["review_gate_statement"] = gate_review.matched
        snaps.take("2_review_parked_before_entity")

        # 3. the definition edit: entity FOR UPDATE, queued behind the reveal's FOR SHARE
        edit = start("edit", lambda: definition_edit(sc, p, body))
        edit_pid: list[int] = []

        def edit_queued() -> bool:
            waiters = lock_waiters_not_in(sc.engine, {names["reveal"], names["review"]}, p.pids)
            if waiters:
                edit_pid.append(waiters[0]["pid"])
                seen["edit_waiting_query"] = waiters[0]["query"]
                return True
            return edit.finished()

        wait_for(edit_queued, "the definition edit queued behind the reveal", sc.engine)
        assert edit_pid, f"the definition edit finished instead of queueing: {edit.describe()}"
        names["edit"] = edit_pid[0]
        seen["edit_xmax_row"] = rows(sc.engine, ROW_XMAX, e=sc.secret_id)
        snaps.take("3_edit_queued_behind_reveal")

        # 4a. release the review toward its entity FOR SHARE (the reveal still holds its FOR SHARE, the edit is queued)
        gate_review.release()
        deadline = (
            time.monotonic() + 20.0
        )  # far beyond deadlock_timeout (1 s): a cycle would have been broken by then
        while not review.finished() and time.monotonic() < deadline:
            if exclusive_review_lock and review_is_lock_waiting(sc.engine, names["review"]):
                break
            time.sleep(0.02)
        seen["review_finished_before_reveal_released"] = review.finished()
        seen["edit_finished_before_reveal_released"] = edit.finished()
        snaps.take("4a_review_released_toward_entity")

        # 4b. release the reveal toward its ki FOR UPDATE
        gate_reveal.release()
        seen["results"] = {
            "reveal": finish(reveal, "reveal finishes"),
            "review": finish(review, "review finishes"),
            "edit": finish(edit, "edit finishes"),
        }
        snaps.take("5_all_finished")
        seen["statements"] = {name: recorder.statements(pid) for name, pid in names.items()}
        seen["pids"] = dict(names)
        report = os.environ.get("R3_REPORT")
        if report:
            with open(report, "a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "test": os.environ.get("PYTEST_CURRENT_TEST", "").split(" ")[0],
                            "kind": "statements",
                            "dnd_ai_file": __import__("dnd_ai").__file__,
                            "by_backend": {
                                n: [x[:260] for x in v] for n, v in seen["statements"].items()
                            },
                        }
                    )
                    + chr(10)
                )
    seen["driver_failures"] = list(p.failures)
    seen["deadlock_delta"] = settled_deadlock_delta(sc.engine, p, before)
    seen["durable"] = durable_state(sc, proposal)
    return seen


def index_of(statements: list[str], pattern: str) -> int:
    for position, statement in enumerate(statements):
        if re.search(pattern, statement):
            return position
    raise AssertionError(f"no statement matches {pattern!r}")


def test_r3_a_queued_entity_update_does_not_make_the_review_wait_so_no_cycle_forms(
    sc: Scene, pool: Pool, owner_is_world_editor: uuid.UUID
) -> None:
    """R-3 resolved by observation: the cycle's third edge never forms.

    The review's entity `FOR SHARE` is *compatible* with the reveal's `FOR SHARE` that already sits on the row. PostgreSQL
    grants a compatible row lock by joining the existing lockers (the row's `xmax` becomes a multixact of both) without
    consulting the heavyweight tuple-lock queue, which holds only the queued `FOR UPDATE`. So the review runs to its COMMIT
    while the definition edit is still queued, ki is then free, and the reveal and the edit finish in turn."""
    seen = run_schedule(sc, pool)
    by_step = {snap["step"]: snap for snap in seen["snaps"].taken}
    pids: dict[str, int] = seen["pids"]
    assert len(set(pids.values())) == 3, (
        pids
    )  # three distinct backends: the reveal, the review and the edit

    # the actual SQL: both gated statements are the ones the schedule names
    statements = seen["statements"]
    first, second = by_step["1_reveal_parked_before_ki"], by_step["2_review_parked_before_entity"]
    # the statement each request was parked on is the last one it had issued at that point (recorded before it executes)
    reveal_parked = statements["reveal"][first["step_statements_by_backend"]["reveal"] - 1]
    review_parked = statements["review"][second["step_statements_by_backend"]["review"] - 1]
    assert re.search(KI_FOR_UPDATE, reveal_parked), reveal_parked
    assert re.search(ENTITY_FOR_SHARE_GUARD, review_parked), review_parked
    assert ENTITY_FOR_UPDATE.search(seen["edit_waiting_query"].strip()), seen["edit_waiting_query"]
    # the reveal took the claim's entity row FOR SHARE (lock_entities) before ki; the review took ki FOR UPDATE before the entity
    reveal_entity_share = (
        r"FROM core\.entities e WHERE e\.entity_id = \S+ AND e\.world_id = \S+ FOR SHARE OF e$"
    )
    assert index_of(statements["reveal"], reveal_entity_share) < index_of(
        statements["reveal"], KI_FOR_UPDATE
    )
    assert index_of(statements["review"], KI_FOR_UPDATE) < index_of(
        statements["review"], ENTITY_FOR_SHARE_GUARD
    )
    # the edit asked for the entity FOR UPDATE and nothing else on the way blocked it first
    assert any(ENTITY_FOR_UPDATE.search(s) for s in statements["edit"])

    # step 1 and 2: both parked, holding what the schedule says, waiting for nothing
    assert first["backends"]["reveal"]["blocked_by"] == []
    assert (
        second["backends"]["reveal"]["blocked_by"] == []
        and second["backends"]["review"]["blocked_by"] == []
    )
    if first["entity_row_lockers"] is not None:
        assert first["entity_row_lockers"] == [
            {"multi": False, "modes": ["For Share"], "backends": ["reveal"]}
        ]

    # step 3: the edit is queued on the reveal's transaction id, and holds the queue head (the heavyweight tuple lock)
    queued = by_step["3_edit_queued_behind_reveal"]
    assert queued["backends"]["edit"]["blocked_by"] == ["reveal"], queued
    assert queued["backends"]["edit"]["wait"] == "Lock/transactionid", queued
    assert (
        queued["backends"]["reveal"]["blocked_by"] == []
        and queued["backends"]["review"]["blocked_by"] == []
    )
    tuple_locks = [lk for lk in queued["locks"] if lk["locktype"] == "tuple"]
    assert tuple_locks == [
        {"pid": "edit", "locktype": "tuple", "mode": "AccessExclusiveLock", "granted": True,
         "relation": "core.entities", "xid": None}
    ], queued["locks"]  # fmt: skip
    assert any(
        lk["pid"] == "edit" and lk["locktype"] == "transactionid" and lk["granted"] is False
        for lk in queued["locks"]
    ), queued["locks"]

    # step 4a: the review, released toward its entity FOR SHARE with the edit queued ahead of it, was NOT queued behind the
    # edit: it finished (200) while the edit was still waiting on the reveal and the reveal had not yet asked for ki
    joined = by_step["4a_review_released_toward_entity"]
    assert seen["review_finished_before_reveal_released"], joined
    assert not seen["edit_finished_before_reveal_released"], joined
    assert joined["backends"]["edit"]["blocked_by"] == ["reveal"], joined
    assert joined["backends"]["reveal"]["state"] == "idle in transaction", joined
    assert joined["backends"]["reveal"]["blocked_by"] == [], joined
    assert joined["entity_xmax"] != queued["entity_xmax"], (
        "the row's xmax did not change: no second locker joined"
    )
    if joined["entity_row_lockers"] is not None:
        # a multixact of two FOR SHARE lockers: the reveal and the (already committed, so pid-less) review
        assert [(m["multi"], m["modes"]) for m in joined["entity_row_lockers"]] == [
            (True, ["For Share", "For Share"])
        ], joined["entity_row_lockers"]

    # exact outcomes: no 40P01, no driver failure, the deadlock counter did not move
    assert not seen["driver_failures"], seen["driver_failures"]
    assert seen["deadlock_delta"] == 0, seen["deadlock_delta"]
    results = seen["results"]
    assert code(results["review"]) == 200, results["review"].text
    assert code(results["reveal"]) == 200, results[
        "reveal"
    ].text  # 200: already known (the review revealed it first)
    assert results["reveal"].json()["changed"] is False
    assert code(results["edit"]) == 200, results["edit"].text
    # durable winner state: one review row, applied once (one reveal event, one party_knowledge row), the edit applied once
    durable = seen["durable"]
    assert durable == {
        "proposal_status": "applied",
        "reviews": 1,
        "party_knowledge": 1,
        "reveal_events": 1,
        "sensitivity": seen["body_sensitivity"],
        "row_version": 2,
    }, durable
    assert not pool.failures, pool.failures


def test_r3_control_an_exclusive_review_entity_lock_would_deadlock_on_this_schedule_and_the_harness_sees_it(
    sc: Scene, pool: Pool, owner_is_world_editor: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Harness sensitivity, not production behaviour: with the review's entity lock made **exclusive** (patched in this test
    only), the same schedule closes the cycle R-3 asked about. The review cannot join the share lockers, so it queues
    behind the edit's `FOR UPDATE` (the third edge); the edit waits on the reveal; the reveal, released, waits on the
    review's `ki` lock. The gates, snapshots, driver-failure capture and deadlock counter must each report it, which shows
    the passing R-3 test above is not a vacuous pass."""
    import dnd_ai.commands.knowledge as knowledge_commands

    original = knowledge_commands.require_state_targetable

    first_caller = threading.Lock()
    taken: list[bool] = []

    def exclusive(connection: Any, *entity_ids: uuid.UUID | None) -> None:
        # Only the review is exclusive: it is the first to reach the guard (the reveal is parked before its ki lock), and
        # the reveal's later call keeps the real shared guard, so the one cycle is the one under test.
        with first_caller:
            mine = not taken
            taken.append(True)
        if mine:
            connection.execute(
                text(
                    "SELECT e.entity_id FROM core.entities e WHERE e.entity_id = ANY(CAST(:ids AS uuid[])) "
                    "ORDER BY e.entity_id FOR UPDATE OF e"
                ),
                {"ids": sorted({i for i in entity_ids if i is not None})},
            )
        original(connection, *entity_ids)

    monkeypatch.setattr(knowledge_commands, "require_state_targetable", exclusive)
    seen = run_schedule(sc, pool, exclusive_review_lock=True)
    by_step = {snap["step"]: snap for snap in seen["snaps"].taken}
    waiting = by_step["4a_review_released_toward_entity"]
    # before the reveal was released: the third edge exists. The review is queued behind the *edit* (it did not join the
    # share lockers, its request is exclusive), the edit is queued on the reveal, and the reveal is about to ask for ki
    assert not seen["review_finished_before_reveal_released"], waiting
    assert waiting["backends"]["review"]["wait"].startswith("Lock/"), waiting
    assert waiting["backends"]["review"]["blocked_by"] == ["edit"], waiting
    assert waiting["backends"]["edit"]["blocked_by"] == ["reveal"], waiting
    assert waiting["backends"]["reveal"]["blocked_by"] == [], waiting
    # then 40P01 only (PostgreSQL's victim is not pinned: the queued edit can be the first, after which the review and the
    # reveal still deadlock on the reveal's FOR SHARE and the review's ki lock, so a second abort follows), each on a
    # cycle-edge statement, with one aborted request per deadlock and the counter agreeing with the driver
    failures = seen["driver_failures"]
    assert failures, "no deadlock: the control did not close the cycle"
    assert {state for state, _ in failures} == {"40P01"}, failures
    # (the driver hook keeps 150 characters: the cycle-edge statements are told apart by their first words)
    edges = (
        "SELECT e.entity_id, e.world_id,",  # the edit's `lock_entities` row lock on the claim (FOR UPDATE)
        "SELECT e.world_id FROM knowledge.knowledge_items ki",  # the reveal's ki lock (FOR UPDATE OF ki)
        "SELECT e.entity_id FROM core.entities e WHERE e.entity_id = ANY(",  # the review's exclusive guard (the patch)
    )
    for _, statement in failures:
        assert statement.startswith(edges), statement
    assert seen["deadlock_delta"] == len(failures), (seen["deadlock_delta"], failures)
    results = seen["results"]
    statuses = {name: code(r) for name, r in results.items()}
    assert sum(1 for value in statuses.values() if value >= 500) == len(failures), statuses
    assert any(value < 500 for value in statuses.values()), statuses  # a survivor commits
    # durable state: whichever side won, the reveal happened at most once and nothing is half applied
    durable = seen["durable"]
    assert durable["party_knowledge"] == durable["reveal_events"] <= 1, durable
    assert (durable["proposal_status"], durable["reviews"]) in (("applied", 1), ("pending", 0)), (
        durable
    )
    assert durable["party_knowledge"] == 1 or durable["proposal_status"] == "pending", durable
