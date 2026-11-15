# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""R01 S5-E2 E10 correction (plan 6.29): ownership transfer against keyed authoring, per transfer branch, per author,
both transaction orderings.

Design: docs/R01_S5E2_E10_CORRECTION_DESIGN_2026-11-15.md (sections 2, 3, 4, 7). Every case drives real routes over
real connections: the keyed authoring request (`POST .../authoring/dungeons`, the reservation INSERT takes the campaign
row FOR KEY SHARE) against `POST .../ownership-transfer`. Author = `w.gm_user` (holds `gm`): it is either the
transferring owner ("actor") or the recipient.

Two orderings, the only meaningful ones:

* **order A** - the authoring request is parked at its `core.worlds ... FOR SHARE` statement (after the reservation
  INSERT, so it holds the campaign row KEY SHARE); the transfer runs; the authoring is released.
* **order T** - the transfer is parked at its actor-account statement (after its role-class, membership and account
  passes, before its campaign lock); the authoring runs; the transfer is released.

Two kinds of test live here, and they must not be confused:

1. **New-cycle regressions** (`test_new_cycle_*`): 14 cases that deadlocked at HEAD `45dab7d` and are clean at the
   untouched baseline `0edb94d`. After TA-E10-1 / TA-E10-2 (M2 / M1) they are ordinary passing tests: no driver
   exception, no deadlock, exact statuses, exact queueing statements, exact final state.
2. **Baseline-cycle characterizations** (`test_baseline_cycle_*`, `test_f_*`): cycles that also deadlock at the baseline
   and are *deferred* (DEF-019 authoring opt-in; plan 6.29, CL-E10-1). They PASS while the known defect is present.
   **A pass means the defect was characterized, not fixed.** When the cycle is fixed they fail on "exactly one 40P01",
   which forces the reclassification. They assert the failed transaction exactly (statement, SQLSTATE, response),
   but not *which* request is the victim, which PostgreSQL chooses (design 3.1: 2 of 66 probe cases inverted the usual
   one).
"""

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest
from sqlalchemy import text

from tests.database.test_r01_s3_authoring_routes import (  # noqa: F401 - fixture by name
    World,
    code,
    error_of,
    w,
)
from tests.database.test_r01_s5e2_lock_order import (  # noqa: F401 - fixture by name
    ACTOR_ACCOUNT,
    AUTHOR_MEMBERSHIP,
    MEMBERSHIP_ROW,
    OK201,
    PATIENCE,
    ROLE_ROW,
    NthGate,
    Pool,
    blocked_view,
    deadlocks_now,
    finish,
    held_mode,
    insert_role,
    pool,
    post,
    rows,
    settled_deadlock_delta,
    tag,
    transfer_audits,
    transfer_body,
)
from tests.deadline_diagnostics import deadline_message
from tests.factories import make_campaign_membership, make_user, system_role_id
from tests.http_race_support import run_in_thread, sessions_blocked_by
from tests.r01_s5d_support import make_managers

pytestmark = pytest.mark.database

#: Order-A gate: the keyed authoring request, after its reservation INSERT (campaign KEY SHARE held).
AUTHORING_WORLD = r"^SELECT lifecycle_status_id FROM core\.worlds WHERE world_id = \S+ FOR SHARE$"
CAMPAIGN_ROW = ("campaign.campaigns", "campaign_id")

# What a queued request waits on (prefixes: the driver-failure list keeps 150 characters of a statement).
WAIT_CAMPAIGN_UPDATE = re.compile(
    r"^SELECT campaign\.campaigns\.campaign_id FROM campaign\.campaigns WHERE .*FOR UPDATE$"
)
WAIT_AUTHOR_ROLES = re.compile(
    r"^SELECT mr\.membership_role_id FROM security\.membership_roles mr JOIN"
)
WAIT_AUTHOR_MEMBERSHIP = re.compile(
    r"^SELECT cm\.campaign_membership_id FROM security\.campaign_memberships cm WHERE cm\.campaign_i"
)

#: Every statement a deadlock of this family may abort: the writer's campaign `FOR UPDATE`, or one of the authoring
#: request's two role-class waits (its role rows, its open membership).
CYCLE_EDGE_WRITER = (WAIT_CAMPAIGN_UPDATE,)
CYCLE_EDGE_AUTHOR = (WAIT_AUTHOR_ROLES, WAIT_AUTHOR_MEMBERSHIP)

OK_TRANSFER = (200, None)
OK_AUTHORING = (201, None)
INTERNAL = (500, "internal_error")


# -- scenes ------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Branch:
    """A transfer branch. `relinquish` is the request flag; `self_transfer` makes the recipient the actor."""

    key: str
    relinquish: bool
    recipient_owner: str  # "none" | "live" | "expired"
    self_transfer: bool = False
    assigned: bool = False  # the response's `assigned`
    relinquished: bool = False
    audits: int = 0  # transfer audit rows the request writes
    replaced_expired: bool = False


BRANCHES = {
    "noop": Branch("noop", False, "live"),
    "insert": Branch("insert", False, "none", assigned=True, audits=1),
    "expired": Branch("expired", False, "expired", assigned=True, audits=1, replaced_expired=True),
    "self": Branch("self", False, "live", self_transfer=True),
    "self_flag": Branch("self_flag", True, "live", self_transfer=True),
    "rel_already": Branch("rel_already", True, "live", relinquished=True, audits=1),
    "rel_insert": Branch("rel_insert", True, "none", assigned=True, relinquished=True, audits=1),
}


@dataclass
class Scene:
    branch: Branch
    author: str  # "actor" | "recipient"
    actor_user: uuid.UUID
    actor_m: uuid.UUID
    rec_m: uuid.UUID
    name: str
    key: str

    def authoring(self, p: Pool, w: World) -> Any:
        return post(
            p,
            w.gm_user,
            f"{w.base}/authoring/dungeons",
            {"name": self.name, "summary": None},
            **{"Idempotency-Key": self.key},
        )

    def transfer(self, p: Pool, w: World) -> Any:
        return post(
            p,
            self.actor_user,
            f"{w.base}/ownership-transfer",
            transfer_body(self.rec_m, self.branch.relinquish),
        )


def expired_owner(c: Any, membership: uuid.UUID) -> uuid.UUID:
    rid = uuid.uuid4()
    c.execute(
        text(
            "INSERT INTO security.membership_roles (membership_role_id, campaign_membership_id, role_id, "
            "granted_at, expires_at) VALUES (:r, :m, :role, now() - interval '2 hours', now() - interval '1 hour')"
        ),
        {"r": rid, "m": membership, "role": system_role_id(c, "campaign_owner")},
    )
    return rid


def build_scene(w: World, branch: Branch, author: str) -> Scene:
    make_managers(w.engine, w.campaign_id, label="X")
    with w.engine.begin() as c:
        owner_role = system_role_id(c, "campaign_owner")
        if author == "actor":
            actor_user, actor_m = w.gm_user, w.gm_membership
            insert_role(c, None, actor_m, owner_role)
            if branch.self_transfer:
                rec_m = actor_m
            else:
                rec_user = make_user(c, "X recipient")
                rec_m = make_campaign_membership(c, w.campaign_id, rec_user)
                insert_role(c, None, rec_m, system_role_id(c, "player"))
        else:
            actor_user = make_user(c, "X owner")
            actor_m = make_campaign_membership(c, w.campaign_id, actor_user)
            insert_role(c, None, actor_m, owner_role)
            rec_m = w.gm_membership
        if not branch.self_transfer:
            if branch.recipient_owner == "live":
                insert_role(c, None, rec_m, owner_role)
            elif branch.recipient_owner == "expired":
                expired_owner(c, rec_m)
    return Scene(
        branch, author, actor_user, actor_m, rec_m, f"E10 {uuid.uuid4().hex[:8]}", str(uuid.uuid4())
    )


def owner_rows(w: World, m: uuid.UUID) -> list[tuple[uuid.UUID, bool, bool]]:
    """(id, unrevoked, unexpired) of every owner row of the membership, ordered by id."""
    return [
        (r["id"], r["unrevoked"], r["unexpired"])
        for r in rows(
            w.engine,
            "SELECT mr.membership_role_id AS id, (mr.revoked_at IS NULL) AS unrevoked, "
            "(mr.expires_at IS NULL OR mr.expires_at > clock_timestamp()) AS unexpired "
            "FROM security.membership_roles mr JOIN security.roles r ON r.role_id = mr.role_id "
            "WHERE r.code = 'campaign_owner' AND mr.campaign_membership_id = :m ORDER BY 1",
            m=m,
        )
    ]


def live_owner(w: World, m: uuid.UUID) -> bool:
    return any(unrevoked and unexpired for _, unrevoked, unexpired in owner_rows(w, m))


def dungeons(w: World, name: str) -> int:
    return int(
        rows(w.engine, "SELECT count(*) AS n FROM core.entities WHERE canonical_name = :n", n=name)[
            0
        ]["n"]
    )


def reservations(w: World, key: str) -> int:
    return int(
        rows(
            w.engine,
            "SELECT count(*) AS n FROM security.idempotent_requests WHERE idempotency_key = :k",
            k=key,
        )[0]["n"]
    )


def non_transfer_audits(w: World) -> int:
    return int(
        rows(
            w.engine,
            "SELECT count(*) AS n FROM audit.change_log WHERE world_id = :w "
            "AND command_name <> 'transfer_campaign_ownership'",
            w=w.world_id,
        )[0]["n"]
    )


def only_transfer_audit(w: World) -> dict[str, Any]:
    found = rows(
        w.engine,
        "SELECT changed_fields FROM audit.change_log WHERE world_id = :w "
        "AND command_name = 'transfer_campaign_ownership'",
        w=w.world_id,
    )
    assert len(found) == 1, f"exactly one transfer audit row: {found}"
    return found[0]["changed_fields"]


@dataclass
class Snapshot:
    actor_owner: list[tuple[uuid.UUID, bool, bool]]
    rec_owner: list[tuple[uuid.UUID, bool, bool]]
    transfer_audits: int
    non_transfer_audits: int
    dungeons: int
    reservations: int


def snapshot(w: World, s: Scene) -> Snapshot:
    return Snapshot(
        owner_rows(w, s.actor_m),
        owner_rows(w, s.rec_m),
        transfer_audits(w.engine),
        non_transfer_audits(w),
        dungeons(w, s.name),
        reservations(w, s.key),
    )


# -- the race ----------------------------------------------------------------------------------------------------


@dataclass
class Run:
    order: str
    gate_statement: str | None
    modes: dict[str, str]
    queued: (
        list[dict[str, Any]] | None
    )  # what the second request waited on behind the parked backend; None = it did not queue
    statuses: dict[str, tuple[int, str | None]]
    transfer_body: dict[str, Any] | None
    failures: list[tuple[str | None, str]]
    deadlock_delta: int
    before: Snapshot
    after: Snapshot
    victim_statement_class: str | None = field(default=None)

    def summary(self) -> str:
        return json.dumps(
            {
                "order": self.order,
                "gate": self.gate_statement,
                "modes": self.modes,
                "queued": [q["query"][:120] for q in (self.queued or [])],
                "statuses": self.statuses,
                "failures": self.failures,
                "deadlock_delta": self.deadlock_delta,
            },
            default=str,
        )


def run_scene(w: World, p: Pool, s: Scene, order: str) -> Run:
    """Park one request, start the other, observe whether and on what it queues, release, collect (no retry)."""
    probes = {
        "campaign": (CAMPAIGN_ROW, w.campaign_id),
        "actor_membership": (MEMBERSHIP_ROW, s.actor_m),
        "recipient_membership": (MEMBERSHIP_ROW, s.rec_m),
        "author_gm_role": (ROLE_ROW, w.gm_role),
    }
    if order == "A":
        gate_pattern, parked_fn, second_fn = (
            AUTHORING_WORLD,
            lambda: s.authoring(p, w),
            lambda: s.transfer(p, w),
        )
        names = ("authoring", "transfer")
    else:
        gate_pattern, parked_fn, second_fn = (
            ACTOR_ACCOUNT,
            lambda: s.transfer(p, w),
            lambda: s.authoring(p, w),
        )
        names = ("transfer", "authoring")
    before = snapshot(w, s)
    deadlocks_before = deadlocks_now(w.engine)
    with NthGate(p.engine, gate_pattern, 1) as gate:
        first = run_in_thread("parked", parked_fn)
        if not gate.reached.wait(PATIENCE):
            gate.release()
            finish(first, "parked request finishes")
            raise AssertionError(
                f"INCOMPATIBLE GATE (not a deadlock finding): {gate_pattern!r} never executed"
            )
        statement = gate.matched
        modes = {label: held_mode(w.engine, *spec) for label, spec in probes.items()}
        later = run_in_thread("second", second_fn)
        queued: list[dict[str, Any]] | None = None
        assert gate.pid is not None
        deadline = time.monotonic() + PATIENCE
        while time.monotonic() < deadline:
            if sessions_blocked_by(w.engine, gate.pid) >= 1:
                queued = blocked_view(w.engine, gate.pid)
                break
            if later.finished():
                break
            time.sleep(0.02)
        else:
            raise AssertionError(
                "the second request neither queued behind the parked one nor finished"
                f"{deadline_message('second request neither queued nor finished', engine=w.engine)}"
            )
        gate.release()
        r1 = finish(first, "parked finishes")
        r2 = finish(later, "second finishes")
    responses = {names[0]: r1, names[1]: r2}
    delta = settled_deadlock_delta(w.engine, p, deadlocks_before)
    failures = list(p.failures)
    after = snapshot(w, s)
    transfer = responses["transfer"]
    return Run(
        order,
        statement,
        modes,
        queued,
        {n: (code(r), error_of(r)) for n, r in responses.items()},
        transfer.json() if code(transfer) == 200 else None,
        failures,
        delta,
        before,
        after,
    )


def retry(w: World, p: Pool, s: Scene, which: str) -> tuple[int, str | None]:
    """Re-issue one request on a fresh pool: authoring with the SAME Idempotency-Key, or the transfer again."""
    p.failures.clear()
    p.engine.dispose()
    response = s.authoring(p, w) if which == "authoring" else s.transfer(p, w)
    return (code(response), error_of(response))


# -- shared assertions -------------------------------------------------------------------------------------------


def assert_waited_on(
    run: Run, expected: re.Pattern[str] | None, parked_pid_only: bool = True
) -> None:
    """`expected` None: the second request did not queue behind the parked backend; otherwise it queued on that
    statement and every blocked session's only direct blocker was the parked backend."""
    if expected is None:
        assert run.queued is None, f"the second request queued: {run.summary()}"
        return
    assert run.queued, f"the second request never queued: {run.summary()}"
    for row in run.queued:
        if parked_pid_only:
            assert len(row["blockers"]) == 1, f"more than one blocker: {run.summary()}"
        assert expected.search(row["query"].strip()), (
            f"waited on {row['query']!r}, not {expected.pattern!r}"
        )


def assert_transfer_effects(w: World, s: Scene, run: Run, *, replay: bool = False) -> None:
    """The transfer branch's exact result against the pre-race state (`run.before`): rows, audit, response flags."""
    b, before, after = s.branch, run.before, run.after
    assert after.transfer_audits - before.transfer_audits == b.audits, run.summary()
    if run.transfer_body is not None:
        assert run.transfer_body["assigned"] is b.assigned, run.summary()
        assert run.transfer_body["relinquished"] is b.relinquished, run.summary()
    if b.audits:
        changed = only_transfer_audit(w)
        assert changed["assigned"] is b.assigned
        assert changed["relinquished"] is b.relinquished
        assert changed["replaced_expired_assignment"] is b.replaced_expired
    if not b.assigned:
        # no recipient row is written: the recipient's rows are exactly as before the race
        assert owner_rows(w, s.rec_m) == run.before.rec_owner
    if b.assigned:
        live = [r for r in owner_rows(w, s.rec_m) if r[1] and r[2]]
        assert len(live) == 1, (
            f"the recipient must hold exactly one live owner row: {owner_rows(w, s.rec_m)}"
        )
        if b.replaced_expired:
            assert [r for r in owner_rows(w, s.rec_m) if r[1] and not r[2]] == [], (
                "the expired row was closed"
            )
    assert live_owner(w, s.rec_m), "the recipient is a live owner"
    assert live_owner(w, s.actor_m) == (not b.relinquished), (
        "the actor keeps ownership unless it relinquished"
    )


def assert_authoring_effects(w: World, s: Scene, run: Run) -> None:
    assert dungeons(w, s.name) == 1, run.summary()
    assert reservations(w, s.key) == 1, run.summary()


# ======================================================================================================================
# 1. The 14 new-cycle regressions (clean at the baseline, deadlocked at HEAD 45dab7d, clean after M1 + M2)
# ======================================================================================================================

#: (branch, author) -> who queues behind the parked request, per order. `None` = the second request finishes while
#: the other is parked. Exact statements of design 7.2.
NEW_CASES: dict[tuple[str, str], dict[str, re.Pattern[str] | None]] = {
    ("noop", "actor"): {"A": None, "T": None},
    ("noop", "recipient"): {"A": None, "T": WAIT_AUTHOR_MEMBERSHIP},
    ("insert", "actor"): {"A": None, "T": None},
    ("insert", "recipient"): {"A": None, "T": WAIT_AUTHOR_MEMBERSHIP},
    ("expired", "actor"): {"A": WAIT_CAMPAIGN_UPDATE, "T": None},
    ("self", "actor"): {"A": None, "T": WAIT_AUTHOR_MEMBERSHIP},
    ("self_flag", "actor"): {"A": None, "T": WAIT_AUTHOR_MEMBERSHIP},
}


@pytest.mark.parametrize("order", ("A", "T"))
@pytest.mark.parametrize(("branch", "author"), list(NEW_CASES))
def test_new_cycle_transfer_and_keyed_authoring_do_not_deadlock(
    branch: str, author: str, order: str, w: World, pool: Pool
) -> None:
    """One of the 14 cases that deadlocked at HEAD: both requests succeed, nothing waits in a cycle, and the final
    state is exactly the serial one."""
    s = build_scene(w, BRANCHES[branch], author)
    run = run_scene(w, pool, s, order)
    # 1. the premise held at the gate (otherwise the case proves nothing)
    if order == "A":
        assert run.modes["campaign"] == "KS", (
            f"the authoring reservation holds the campaign KS: {run.summary()}"
        )
    else:
        assert run.modes["actor_membership"] in ("S", "U"), run.summary()
        assert run.modes["recipient_membership"] == "U", run.summary()
        if author == "actor":
            assert run.modes["author_gm_role"] == "KS", (
                f"M2: the actor's rows are KEY SHARE: {run.summary()}"
            )
    # 2. no driver exception, no deadlock
    assert not run.failures, f"driver exceptions (40P01 = deadlock): {run.summary()}"
    assert run.deadlock_delta == 0, run.summary()
    # 3. who queued, exactly
    assert_waited_on(run, NEW_CASES[(branch, author)][order])
    # 4. exact statuses
    assert run.statuses == {"transfer": OK_TRANSFER, "authoring": OK_AUTHORING}, run.summary()
    # 5. durable state
    assert_transfer_effects(w, s, run)
    assert_authoring_effects(w, s, run)


# ======================================================================================================================
# 2. Baseline-cycle characterizations (pre-existing at 0edb94d; deferred to the authoring opt-in slice)
# ======================================================================================================================


def victim_from(failures: list[tuple[str | None, str]], summary: str) -> str:
    """The request whose statement PostgreSQL aborted: `writer` (its campaign FOR UPDATE) or `authoring` (one of its
    two role-class waits). Anything else is a different failure and fails the characterization."""
    assert len(failures) == 1, f"expected exactly one driver failure: {summary}"
    sqlstate, statement = failures[0]
    assert sqlstate == "40P01", f"the failure is not a deadlock: {summary}"
    if any(p.search(statement) for p in CYCLE_EDGE_WRITER):
        return "writer"
    if any(p.search(statement) for p in CYCLE_EDGE_AUTHOR):
        return "authoring"
    raise AssertionError(f"the deadlock aborted a statement that is not a cycle edge: {summary}")


def victim_of(run: Run) -> str:
    return "transfer" if victim_from(run.failures, run.summary()) == "writer" else "authoring"


def characterize(w: World, p: Pool, s: Scene, run: Run) -> str:
    """Assert one aborted transaction, its rollback and its recovery. Returns the victim ("transfer"|"authoring")."""
    victim = victim_of(run)
    winner = "authoring" if victim == "transfer" else "transfer"
    assert run.deadlock_delta == 1, f"expected exactly one deadlock: {run.summary()}"
    assert run.statuses[victim] == INTERNAL, f"the victim answers 500: {run.summary()}"
    assert run.statuses[winner] == (OK_TRANSFER if winner == "transfer" else OK_AUTHORING), (
        run.summary()
    )
    b, before, after = s.branch, run.before, run.after
    if victim == "transfer":
        # nothing of the transfer survived: no role row changed, no audit; the winner (authoring) committed
        assert after.transfer_audits == before.transfer_audits, run.summary()
        assert after.actor_owner == before.actor_owner and after.rec_owner == before.rec_owner, (
            run.summary()
        )
        assert after.dungeons == 1 and after.reservations == 1, run.summary()
        status = retry(w, p, s, "transfer")
        assert status == OK_TRANSFER, "the re-posted transfer succeeds"
        final = snapshot(w, s)
        assert final.transfer_audits - before.transfer_audits == b.audits
        assert live_owner(w, s.rec_m) and live_owner(w, s.actor_m) == (not b.relinquished)
        assert dungeons(w, s.name) == 1
    else:
        # nothing of the authoring survived: no authored row, no reservation for its key, no non-transfer audit
        # row; the winner (transfer) committed in full
        assert after.dungeons == 0, run.summary()
        assert after.reservations == 0, (
            f"the reservation rolled back with the victim: {run.summary()}"
        )
        assert after.non_transfer_audits == before.non_transfer_audits, run.summary()
        assert after.transfer_audits - before.transfer_audits == b.audits, run.summary()
        status = retry(w, p, s, "authoring")
        assert status == OK_AUTHORING, "the same Idempotency-Key is reusable after the rollback"
        assert dungeons(w, s.name) == 1 and reservations(w, s.key) == 1
        assert live_owner(w, s.rec_m) and live_owner(w, s.actor_m) == (not b.relinquished)
    return victim


#: The 10 retained baseline cases: (branch, author). Each is run in both orders.
BASELINE_CASES = [
    ("expired", "recipient"),
    ("rel_already", "actor"),
    ("rel_already", "recipient"),
    ("rel_insert", "actor"),
    ("rel_insert", "recipient"),
]


@pytest.mark.parametrize("order", ("A", "T"))
@pytest.mark.parametrize(("branch", "author"), BASELINE_CASES)
def test_baseline_cycle_is_characterized_not_fixed(
    branch: str, author: str, order: str, w: World, pool: Pool
) -> None:
    """DEFERRED, NOT FIXED (DEF-019, CL-E10-1): relinquishing transfers, and the replacement of the *recipient-author's*
    expired owner row, deadlock with keyed authoring exactly as at the baseline `0edb94d`. This test passes while
    that is true. If it fails on `exactly one driver failure`, the cycle is gone: reclassify, do not 'fix' the test."""
    s = build_scene(w, BRANCHES[branch], author)
    run = run_scene(w, pool, s, order)
    characterize(w, pool, s, run)


# ======================================================================================================================
# 3. Test F's two deferred peers, characterized (both positions of the author's other role row)
# ======================================================================================================================

MEMBERSHIP_STATEMENT = (
    r"SELECT security\.campaign_memberships\.campaign_membership_id FROM security\.campaign_memberships "
    r"WHERE .* FOR (SHARE|UPDATE)$"
)


@pytest.mark.parametrize("other_row", ("below_gX", "above_gX"))
@pytest.mark.parametrize("peer", ("change", "transfer_to_expired_owner"))
def test_f_the_deferred_cycle_is_characterized(
    peer: str, other_row: str, w: World, pool: Pool
) -> None:
    """DEFERRED, NOT FIXED (DEF-019): X (`w.gm_user`) authors while a `change` of X's `gm` row, or a transfer that
    replaces X's expired owner row, holds X's role rows and then wants the campaign row `FOR UPDATE`, which X's
    authoring request already holds `FOR KEY SHARE`. Passing means the baseline defect was characterized."""
    from tests.database.test_r01_s5e2_lock_order import race

    m = make_managers(w.engine, w.campaign_id, label="F")
    other = tag("low" if other_row == "below_gX" else "high", "01")
    name, key = f"F {uuid.uuid4().hex[:8]}", str(uuid.uuid4())
    with w.engine.begin() as c:
        c_user = make_user(c, "F C")
        c_m = make_campaign_membership(c, w.campaign_id, c_user)
        insert_role(c, None, c_m, system_role_id(c, "campaign_owner"))
        insert_role(c, other, w.gm_membership, system_role_id(c, "player"))
        observer = system_role_id(c, "observer")
        if peer == "transfer_to_expired_owner":
            c.execute(
                text(
                    "INSERT INTO security.membership_roles (membership_role_id, campaign_membership_id, "
                    "role_id, granted_at, expires_at) VALUES (:r, :m, :role, "
                    "now() - interval '2 hours', now() - interval '1 hour')"
                ),
                {
                    "r": tag("high", "e1"),
                    "m": w.gm_membership,
                    "role": system_role_id(c, "campaign_owner"),
                },
            )

    def authoring() -> Any:
        return post(
            pool,
            w.gm_user,
            f"{w.base}/authoring/dungeons",
            {"name": name, "summary": None},
            **{"Idempotency-Key": key},
        )

    def writer() -> Any:
        if peer == "change":
            return post(
                pool,
                m.manager_user,
                f"{w.base}/memberships/roles/{w.gm_role}/change",
                {"new_role_id": str(observer)},
            )
        return post(
            pool, c_user, f"{w.base}/ownership-transfer", transfer_body(w.gm_membership, False)
        )

    audits_before = transfer_audits(w.engine)
    gm_rows_before = rows(
        w.engine,
        "SELECT membership_role_id AS id, revoked_at IS NULL AS live FROM security.membership_roles "
        "WHERE campaign_membership_id = :m ORDER BY 1",
        m=w.gm_membership,
    )
    o = race(
        w,
        pool,
        gate_pattern=MEMBERSHIP_STATEMENT,
        parked=writer,
        second=authoring,
    )
    summary = o.summary()
    victim = victim_from(o.failures, summary)
    assert o.deadlock_delta == 1, summary
    win_writer = OK201 if peer == "change" else OK_TRANSFER
    victim_request = "parked" if victim == "writer" else "second"
    winner_request = "second" if victim == "writer" else "parked"
    assert o.status(victim_request) == INTERNAL, summary
    assert o.status(winner_request) == (OK_AUTHORING if victim == "writer" else win_writer), summary
    gm_rows_after = rows(
        w.engine,
        "SELECT membership_role_id AS id, revoked_at IS NULL AS live FROM security.membership_roles "
        "WHERE campaign_membership_id = :m ORDER BY 1",
        m=w.gm_membership,
    )
    pool.failures.clear()
    pool.engine.dispose()
    if victim == "writer":
        assert gm_rows_after == gm_rows_before, "the aborted writer changed no role row"
        assert transfer_audits(w.engine) == audits_before
        assert dungeons_named(w, name) == 1 and reservations_for(w, key) == 1
        again = writer()
        assert (code(again), error_of(again)) == win_writer, "the re-posted writer succeeds"
    else:
        assert dungeons_named(w, name) == 0, "no authored row survived the aborted authoring"
        assert reservations_for(w, key) == 0, "the reservation rolled back with the victim"
        again = authoring()
        if peer == "change":
            # the change committed: the author lost `gm` (and `canon.edit`): the same key is reusable, and refused
            assert code(again) == 403, (
                f"the retry executes (not a replay) and is refused: {again.text}"
            )
            assert dungeons_named(w, name) == 0
        else:
            assert (code(again), error_of(again)) == OK_AUTHORING
            assert dungeons_named(w, name) == 1 and reservations_for(w, key) == 1


def dungeons_named(w: World, name: str) -> int:
    return int(
        rows(w.engine, "SELECT count(*) AS n FROM core.entities WHERE canonical_name = :n", n=name)[
            0
        ]["n"]
    )


def reservations_for(w: World, key: str) -> int:
    return reservations(w, key)
