# ruff: noqa: F811, SIM117, S608 - the imported fixtures are used by name; nested `with` keeps each expected failure separate; scratch DDL
"""R01 O-1 (AM-1): the keyed post-write opt-in (design `R01_AUTHORING_OPT_IN_DESIGN_2026-11-16.md`, section 2.3,
test N-1).

NO production route adopts the capability: every plan here is a synthetic `AuthorizationPlan.begin(...,
keyed_post_write=True)` driven directly, over the real migrated `security.idempotent_requests` and
`campaign.campaigns` tables, with a scratch `marker` table standing in for a command's business write. The
scaffolding is the S5-C module's (a one-connection pool, a held-lock helper, `pg_blocking_pids` waits).

A post-write plan keeps its timing: every write comes *before* `finalize` (the receipt `UPDATE` included), and
no statement may follow it. What AM-1 adds is the reservation deferral, the server-recorded outcome, the
campaign evidence obligation, its COMMIT backstop and the savepoint latch, each reused from S5-C.

Each case asserts the latch reason, that nothing was persisted where it must not be, and (where a connection
is reused) that the pooled connection is immediate again.
"""

import contextlib
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import Connection, Engine, event, text
from sqlalchemy.exc import DBAPIError

from dnd_ai.api.idempotency import (
    IdempotentReplay,
    IdempotentReservation,
    complete_idempotent_request,
)
from dnd_ai.commands._content import canon_edit_requirement
from dnd_ai.domain import authorization
from dnd_ai.domain.authorization import (
    CAMPAIGN_EVIDENCE_LOCK,
    AuthorizationPlan,
    AuthorizationPlanBindingError,
    AuthorizationPlanNotFinalizedError,
    AuthorizationPlanStateError,
    AuthorizationPlanViolationError,
    PlanMode,
    ViolationReason,
)
from tests.database.test_r01_s3_authoring_routes import World, w  # noqa: F401 - fixture by name
from tests.database.test_r01_s5c_reservation_deferral import (
    _OPEN,
    FK,
    SCHEMA,
    _lock_campaign_update_and_commit,
    assert_next_transaction_is_immediate,
    campaign_b,  # noqa: F401 - fixture by name
    commit_refused,
    completed,
    hold_campaign,
    markers,
    no_wait,
    one,  # noqa: F401 - fixture by name
    pid_of,
    release,
    reservations,
    reserve,
    scratch,  # noqa: F401 - fixture by name
    track,
)
from tests.http_race_support import (
    new_key,
    run_in_thread,
    sessions_blocked_by,
    wait_until_pid_blocks,
)

pytestmark = pytest.mark.database

R = ViolationReason

# --- scaffolding -------------------------------------------------------------------------------------


def open_post(
    engine: Engine,
    w: World,
    *,
    keyed: bool = True,
    campaign_id: uuid.UUID | None = None,
    patient: bool = False,
) -> tuple[Connection, AuthorizationPlan]:
    """A post-write plan on a fresh transaction (registered for keyed opt-in unless `keyed=False`). Unless
    `patient`, the transaction cannot wait for a row lock longer than two seconds."""
    connection = engine.connect()
    _OPEN.append(connection)
    connection.begin()
    if not patient:
        no_wait(connection)
    plan = AuthorizationPlan.begin(
        connection,
        actor_user_id=w.gm_user,
        campaign_id=campaign_id or w.campaign_id,
        keyed_post_write=keyed,
    )
    return connection, plan


def fresh_post(
    engine: Engine,
    w: World,
    key: str,
    *,
    defer: bool = True,
    bind: bool = True,
    evidence: bool = True,
    campaign_id: uuid.UUID | None = None,
) -> tuple[Connection, AuthorizationPlan, IdempotentReservation]:
    """The keyed post-write sequence up to (not including) the writes and `finalize`: defer, reserve, bind,
    campaign evidence."""
    connection, plan = open_post(engine, w, campaign_id=campaign_id)
    if defer:
        plan.defer_reservation_campaign_fk(connection)
    reservation = reserve(connection, w, key, campaign_id=campaign_id)
    assert isinstance(reservation, IdempotentReservation)
    if bind:
        plan.bind_reservation(connection, reservation)
    if evidence:
        plan.lock_campaign_evidence(connection)
    return connection, plan, reservation


def write_all(connection: Connection, reservation: IdempotentReservation | None = None) -> None:
    """The command's writes: a business row and the receipt `UPDATE`, both before `finalize`."""
    connection.execute(text(f"INSERT INTO {SCHEMA}.marker (note) VALUES ('n')"))
    if reservation is not None:
        complete_idempotent_request(
            connection,
            idempotent_request_id=reservation.idempotent_request_id,
            response_status_code=201,
            response_body={"ok": True},
        )


def finalize(connection: Connection, plan: AuthorizationPlan, w: World) -> None:
    plan.require(connection, canon_edit_requirement(w.gm_user, w.campaign_id))
    plan.finalize(connection)


def full_request(
    connection: Connection, plan: AuthorizationPlan, w: World, reservation: IdempotentReservation
) -> None:
    write_all(connection, reservation)
    finalize(connection, plan, w)


def complete_first(engine: Engine, w: World, key: str) -> None:
    """A committed request under `key`, so a later request replays it."""
    connection, plan, reservation = fresh_post(engine, w, key)
    full_request(connection, plan, w, reservation)
    connection.commit()
    connection.close()


@contextlib.contextmanager
def listening(engine: Engine, name: str, fn: Any, **kwargs: Any) -> Iterator[None]:
    event.listen(engine, name, fn, **kwargs)
    try:
        yield
    finally:
        with contextlib.suppress(Exception):
            event.remove(engine, name, fn)


# =====================================================================================================
# 1. Finalization and COMMIT: the obligation
# =====================================================================================================


def test_deferral_bind_evidence_then_finalize_and_commit(scratch: World, one: Engine) -> None:
    """plan: the whole keyed post-write sequence commits. The plan deferred, was bound `RESERVED`, holds
    evidence for exactly its own campaign, and the post-write timing is unchanged (writes, then `finalize`)."""
    key = new_key()
    connection, plan, reservation = fresh_post(one, scratch, key)
    assert plan.keyed_post_write and plan.deferred and plan.reservation_kind == "reserved"
    assert plan.evidence(CAMPAIGN_EVIDENCE_LOCK) == {(scratch.campaign_id,)}
    full_request(connection, plan, scratch, reservation)
    assert plan.finalised and plan.violation is None
    connection.commit()
    connection.close()
    assert completed(scratch.engine, key) == 1
    assert markers(scratch.engine) == 1


def test_a_reserved_plan_without_evidence_is_refused_at_finalize_and_nothing_persists(
    scratch: World, one: Engine
) -> None:
    """plan: the obligation is checked at `finalize`, before the snapshot is read, and the plan is not
    finalised by the refusal."""
    key = new_key()
    connection, plan, reservation = fresh_post(one, scratch, key, evidence=False)
    assert plan.owes_campaign_evidence
    write_all(connection, reservation)
    plan.require(connection, canon_edit_requirement(scratch.gm_user, scratch.campaign_id))
    with pytest.raises(AuthorizationPlanViolationError):
        plan.finalize(connection)
    assert plan.violation is R.CAMPAIGN_EVIDENCE
    assert not plan.finalised and plan.snapshot is None
    commit_refused(connection)
    connection.close()
    assert reservations(scratch.engine, key) == 0
    assert markers(scratch.engine) == 0
    assert_next_transaction_is_immediate(one, scratch)


def test_a_caught_finalize_refusal_still_refuses_the_commit(scratch: World, one: Engine) -> None:
    """plan: a route that catches the refusal and carries on gains nothing: the latch stays."""
    key = new_key()
    connection, plan, reservation = fresh_post(one, scratch, key, evidence=False)
    write_all(connection, reservation)
    with contextlib.suppress(AuthorizationPlanViolationError):
        finalize(connection, plan, scratch)
    commit_refused(connection)
    connection.close()
    assert reservations(scratch.engine, key) == 0


def test_the_commit_guard_repeats_the_obligation_independently_of_finalize(
    scratch: World, one: Engine
) -> None:
    """plan (tamper): evidence removed after a successful `finalize` (a defect or hostile code) is refused at
    COMMIT, and so is a reserved plan that never reached `finalize`. This is the backstop mutation (e) cannot
    reach: it does not go through `finalize`'s own check."""
    key = new_key()
    connection, plan, reservation = fresh_post(one, scratch, key)
    full_request(connection, plan, scratch, reservation)
    plan._evidence.clear()
    commit_refused(connection)
    assert plan.violation is R.CAMPAIGN_EVIDENCE
    connection.close()
    assert reservations(scratch.engine, key) == 0

    connection, plan, reservation = fresh_post(one, scratch, new_key())
    write_all(connection, reservation)
    commit_refused(connection)  # reserved, evidence held, never finalised
    assert plan.violation is R.CAMPAIGN_EVIDENCE
    connection.close()
    assert markers(scratch.engine) == 0


def test_a_deferred_plan_with_no_bound_outcome_is_refused_at_finalize_and_commit(
    scratch: World, one: Engine
) -> None:
    """plan: a deferral with no recorded outcome (nothing reserved, or reserved and never bound) never
    commits; the reservation made in between is rolled back with the transaction."""
    connection, plan = open_post(one, scratch)
    plan.defer_reservation_campaign_fk(connection)
    with pytest.raises(AuthorizationPlanViolationError):
        plan.finalize(connection)
    assert plan.violation is R.OUTCOME
    commit_refused(connection)
    connection.close()

    key = new_key()
    connection, plan, reservation = fresh_post(one, scratch, key, bind=False, evidence=False)
    write_all(connection, reservation)
    with pytest.raises(AuthorizationPlanViolationError):
        finalize(connection, plan, scratch)
    assert plan.violation is R.OUTCOME
    commit_refused(connection)
    connection.close()
    assert reservations(scratch.engine, key) == 0
    assert_next_transaction_is_immediate(one, scratch)


def test_a_replay_needs_no_evidence_and_writes_nothing(scratch: World, one: Engine) -> None:
    """plan: the replay's `ON CONFLICT DO NOTHING` inserted no row, so no FK event is queued and nothing is
    owed; `finalize` judges the route's requirements and the receipt is returned."""
    key = new_key()
    complete_first(one, scratch, key)
    connection, plan = open_post(one, scratch)
    plan.defer_reservation_campaign_fk(connection)
    replay = reserve(connection, scratch, key)
    assert isinstance(replay, IdempotentReplay)
    plan.bind_reservation(connection, replay)
    assert plan.reservation_kind == "replay"
    assert not plan.owes_campaign_evidence
    with pytest.raises(AuthorizationPlanStateError):
        plan.lock_campaign_evidence(connection)  # never silently skipped
    assert plan.violation is R.SEQUENCE
    connection.close()

    connection, plan = open_post(one, scratch)
    plan.defer_reservation_campaign_fk(connection)
    replay = reserve(connection, scratch, key)
    assert isinstance(replay, IdempotentReplay)
    plan.bind_reservation(connection, replay)
    finalize(connection, plan, scratch)
    connection.commit()
    connection.close()
    assert markers(scratch.engine) == 1  # only the first request wrote
    assert reservations(scratch.engine, key) == 1


def test_a_reservation_with_no_deferral_stays_immediate_and_owes_nothing(
    scratch: World, one: Engine
) -> None:
    """plan: immediate-by-default. A registered plan that never defers (an unkeyed request) has no outcome
    to bind and no evidence to take, its reservation INSERT waits on a held campaign `FOR UPDATE` exactly as
    before, and `bind_reservation` without a deferral is refused."""
    key = new_key()
    holder, holder_pid = hold_campaign(scratch.engine, scratch.campaign_id)
    connection, plan = open_post(one, scratch, patient=True)
    request = run_in_thread("insert", lambda: reserve(connection, scratch, key))
    try:
        wait_until_pid_blocks(scratch.engine, holder_pid)  # the INSERT itself waits
    finally:
        release(holder)
    reservation = request.wait("reserved after the holder released")
    assert isinstance(reservation, IdempotentReservation)
    assert not plan.deferred and not plan.owes_campaign_evidence
    with pytest.raises(AuthorizationPlanStateError):
        plan.bind_reservation(connection, reservation)  # binds only after a deferral
    assert plan.violation is R.OUTCOME
    connection.close()

    connection, plan = open_post(one, scratch)  # no key at all: nothing reserved, nothing owed
    write_all(connection)
    finalize(connection, plan, scratch)
    connection.commit()
    connection.close()
    assert markers(scratch.engine) == 1


# =====================================================================================================
# 2. Evidence: whose, when, and how it is taken
# =====================================================================================================


def test_evidence_is_for_the_plans_own_campaign_only(
    scratch: World, one: Engine, campaign_b: uuid.UUID
) -> None:
    """plan: the call takes no campaign argument; the parameter is the plan's. A plan for campaign B holds
    evidence for B and none for A, and A's evidence is then not what B's obligation needs."""
    connection, plan, reservation = fresh_post(one, scratch, new_key(), campaign_id=campaign_b)
    assert plan.evidence(CAMPAIGN_EVIDENCE_LOCK) == {(campaign_b,)}
    assert (scratch.campaign_id,) not in plan.evidence(CAMPAIGN_EVIDENCE_LOCK)
    with pytest.raises(TypeError):
        plan.lock_campaign_evidence(connection, scratch.campaign_id)  # type: ignore[call-arg]
    complete_idempotent_request(
        connection,
        idempotent_request_id=reservation.idempotent_request_id,
        response_status_code=201,
        response_body={},
    )
    plan.finalize(connection)  # no requirement registered: nothing to judge, obligations met
    connection.commit()
    connection.close()


def test_missing_or_foreign_evidence_does_not_count(scratch: World, one: Engine) -> None:
    """plan: a campaign lock taken outside the plan (raw SQL), and evidence recorded for another campaign,
    are not this plan's evidence; both are refused at `finalize` and at COMMIT."""
    key = new_key()
    connection, plan, reservation = fresh_post(one, scratch, key, evidence=False)
    connection.execute(
        text("SELECT 1 FROM campaign.campaigns WHERE campaign_id = :c FOR KEY SHARE"),
        {"c": scratch.campaign_id},
    ).all()  # a real lock, but not through the plan
    write_all(connection, reservation)
    with pytest.raises(AuthorizationPlanViolationError):
        finalize(connection, plan, scratch)
    assert plan.violation is R.CAMPAIGN_EVIDENCE
    connection.close()

    connection, plan, reservation = fresh_post(one, scratch, new_key(), evidence=False)
    plan._evidence[CAMPAIGN_EVIDENCE_LOCK] = {(uuid.uuid4(),)}  # tamper: another campaign's key
    write_all(connection, reservation)
    with pytest.raises(AuthorizationPlanViolationError):
        finalize(connection, plan, scratch)
    assert plan.violation is R.CAMPAIGN_EVIDENCE
    commit_refused(connection)
    connection.close()
    assert markers(scratch.engine) == 0


def test_evidence_after_finalize_is_refused_and_a_foreign_connection_is_refused(
    scratch: World, one: Engine
) -> None:
    """plan: after `finalize` the plan owes nothing and the call is refused (`SEQUENCE`), and no statement
    is admitted; a call from another connection is refused as a binding error."""
    connection, plan, reservation = fresh_post(one, scratch, new_key())
    full_request(connection, plan, scratch, reservation)
    with pytest.raises(AuthorizationPlanStateError):
        plan.lock_campaign_evidence(connection)
    assert plan.violation is R.SEQUENCE
    commit_refused(connection)
    connection.close()

    connection, plan, reservation = fresh_post(one, scratch, new_key(), evidence=False)
    other = track(scratch.engine.connect())
    other.begin()
    with pytest.raises(AuthorizationPlanBindingError):
        plan.lock_campaign_evidence(other)
    assert plan.violation is R.BINDING
    other.rollback()
    other.close()
    connection.close()


def test_evidence_is_refused_out_of_sequence(scratch: World, one: Engine) -> None:
    """plan: every state but "deferred, bound RESERVED, unfinalised" latches `SEQUENCE` and is refused:
    before the deferral, after a deferral with no outcome, on a non-registered post-write plan and inside a
    savepoint."""
    connection, plan = open_post(one, scratch)
    with pytest.raises(AuthorizationPlanStateError):
        plan.lock_campaign_evidence(connection)
    assert plan.violation is R.SEQUENCE
    connection.close()

    connection, plan = open_post(one, scratch)
    plan.defer_reservation_campaign_fk(connection)
    with pytest.raises(AuthorizationPlanStateError):
        plan.lock_campaign_evidence(connection)
    assert plan.violation is R.SEQUENCE
    connection.close()

    connection, plan = open_post(one, scratch, keyed=False)
    assert not plan.owes_campaign_evidence
    with pytest.raises(AuthorizationPlanStateError):
        plan.lock_campaign_evidence(connection)
    assert plan.violation is R.SEQUENCE
    connection.close()

    connection, plan, reservation = fresh_post(one, scratch, new_key(), evidence=False)
    nested = connection.begin_nested()
    with pytest.raises(AuthorizationPlanStateError):
        plan.lock_campaign_evidence(connection)
    nested.rollback()
    assert plan.violation is R.SEQUENCE
    connection.close()


# =====================================================================================================
# 3. The evidence flight: identity, rendering, parameters, side executions, listeners
# =====================================================================================================


def test_the_evidence_statement_is_the_declared_one_and_runs_once(
    scratch: World, one: Engine
) -> None:
    """plan: the session validation runs first (its statements precede the lock), then exactly one
    cursor event carries the constant's statement with the plan's parameter, and it is the last."""
    seen: list[tuple[str, Any]] = []

    def record(
        conn: Connection, cursor: Any, statement: str, parameters: Any, context: Any, many: bool
    ) -> None:
        seen.append((statement, parameters))

    connection, plan, reservation = fresh_post(one, scratch, new_key(), evidence=False)
    with listening(one, "before_cursor_execute", record):
        plan.lock_campaign_evidence(connection)
    locks = [i for i, (statement, _) in enumerate(seen) if "FOR KEY SHARE" in statement]
    assert locks == [len(seen) - 1]  # one evidence statement, issued last
    statement, parameters = seen[-1]
    assert "campaign.campaigns" in statement
    assert parameters == {"campaign": scratch.campaign_id}
    assert any("session_replication_role" in s for s, _ in seen[:-1])  # validated before the lock
    connection.close()


def test_a_side_execution_inside_the_flight_is_refused(scratch: World, one: Engine) -> None:
    """plan: a second statement executed by a listener while the flight is open is a side execution."""
    connection, plan, reservation = fresh_post(one, scratch, new_key(), evidence=False)
    armed = [True]

    def side(conn: Connection, element: Any, *_: Any) -> None:
        if armed[0] and element is CAMPAIGN_EVIDENCE_LOCK.statement:
            armed[0] = False
            conn.execute(text("SELECT 1")).all()

    with listening(one, "before_execute", side):
        with pytest.raises(AuthorizationPlanViolationError):
            plan.lock_campaign_evidence(connection)
    assert plan.violation is R.SIDE_EXECUTION
    assert not plan.evidence(CAMPAIGN_EVIDENCE_LOCK)
    commit_refused(connection)
    connection.close()


def test_a_rewritten_statement_or_parameter_is_refused_at_the_driver_hop(
    scratch: World, one: Engine
) -> None:
    """plan: a listener that rewrites the rendered statement or the driver parameters after the guard's
    own `before_cursor_execute` is caught at `do_execute`, before the driver is called."""
    for mode, reason in (("render", R.RENDERING), ("param", R.PARAMETERS)):
        connection, plan, reservation = fresh_post(one, scratch, new_key(), evidence=False)

        def rewrite(
            conn: Connection,
            cursor: Any,
            statement: str,
            parameters: Any,
            context: Any,
            many: bool,
            mode: str = mode,
        ) -> tuple[str, Any]:
            if "FOR KEY SHARE" not in statement:  # only the evidence statement is rewritten
                return statement, parameters
            if mode == "render":
                return statement + " ", parameters
            return statement, {"campaign": uuid.uuid4()}

        with listening(one, "before_cursor_execute", rewrite, retval=True):
            with pytest.raises(AuthorizationPlanViolationError):
                plan.lock_campaign_evidence(connection)
        assert plan.violation is reason, mode
        assert not plan.evidence(CAMPAIGN_EVIDENCE_LOCK)
        commit_refused(connection)
        connection.close()


def test_a_listener_registered_during_the_flight_is_refused(scratch: World, one: Engine) -> None:
    """plan: the topology is compared per flight, so a registration made while the flight is open is
    detected."""
    connection, plan, reservation = fresh_post(one, scratch, new_key(), evidence=False)

    def noop(*_: Any) -> None:
        return None

    armed = [True]

    def register(conn: Connection, element: Any, *_: Any) -> None:
        if armed[0] and element is CAMPAIGN_EVIDENCE_LOCK.statement:
            armed[0] = False
            event.listen(one, "before_cursor_execute", noop)

    try:
        with listening(one, "before_execute", register):
            with pytest.raises(AuthorizationPlanViolationError):
                plan.lock_campaign_evidence(connection)
    finally:
        with contextlib.suppress(Exception):
            event.remove(one, "before_cursor_execute", noop)
    assert plan.violation is R.LISTENER_TOPOLOGY
    commit_refused(connection)
    connection.close()


def test_a_listener_registered_after_the_plan_opened_but_before_the_flight_is_accepted(
    scratch: World, one: Engine
) -> None:
    """plan (AM-1.9, D-6): the established test practice of registering a gate after a post-write plan
    opens keeps working: the topology baseline is per flight, not for the plan's lifetime."""
    seen: list[str] = []

    def gate(
        conn: Connection, cursor: Any, statement: str, parameters: Any, context: Any, many: bool
    ) -> None:
        seen.append(statement)

    key = new_key()
    connection, plan = open_post(one, scratch)
    with listening(one, "before_cursor_execute", gate):
        plan.defer_reservation_campaign_fk(connection)
        reservation = reserve(connection, scratch, key)
        assert isinstance(reservation, IdempotentReservation)
        plan.bind_reservation(connection, reservation)
        plan.lock_campaign_evidence(connection)
        full_request(connection, plan, scratch, reservation)
        connection.commit()
    connection.close()
    assert any("FOR KEY SHARE" in s for s in seen)
    assert completed(scratch.engine, key) == 1


def test_a_failed_evidence_statement_latches_and_a_caught_failure_stays_latched(
    scratch: World, one: Engine
) -> None:
    """plan: the lock cannot be granted (a competitor holds the campaign `FOR UPDATE`; the transaction's
    2 s `lock_timeout` fires). No evidence is recorded, the plan is violated, and catching the error does not
    clear it."""
    key = new_key()
    connection, plan, reservation = fresh_post(one, scratch, key, evidence=False)
    holder, holder_pid = hold_campaign(scratch.engine, scratch.campaign_id)
    try:
        with pytest.raises(DBAPIError):
            plan.lock_campaign_evidence(connection)
    finally:
        release(holder)
    assert plan.violated and plan.violation is R.EXECUTION_FAILED
    assert not plan.evidence(CAMPAIGN_EVIDENCE_LOCK)
    commit_refused(connection)  # the aborted transaction never reaches the database's COMMIT
    connection.close()
    assert reservations(scratch.engine, key) == 0
    assert_next_transaction_is_immediate(one, scratch)


# =====================================================================================================
# 3b. Session validation before the evidence lock (Luna's O-1 finding)
# =====================================================================================================

#: transaction-scoped, so a refusal cannot leave the pooled backend changed (the plan, not the rollback,
#: is what is being tested: the setting is in force when the plan looks)
_BAD_SESSIONS = {
    "explicit_pg_catalog": "SET LOCAL search_path = pg_catalog, public",
    "replica_role": "SET LOCAL session_replication_role = replica",
}


def _campaign_lock_statements(seen: list[str]) -> list[str]:
    return [s for s in seen if "FOR KEY SHARE" in s and "campaigns" in s]


def _recording(one: Engine) -> tuple[list[str], Any]:
    seen: list[str] = []

    def record(
        conn: Connection, cursor: Any, statement: str, parameters: Any, context: Any, many: bool
    ) -> None:
        seen.append(statement)

    return seen, record


def _assert_refused_before_the_lock(
    scratch: World,
    one: Engine,
    connection: Connection,
    plan: AuthorizationPlan,
    key: str,
    seen: list[str],
) -> None:
    """The refusal is `SESSION`, no campaign lock statement reached the driver, no evidence exists, the
    caught refusal stays latched (a second call, `finalize` and COMMIT all refuse) and nothing persists."""
    assert plan.violation is R.SESSION
    assert _campaign_lock_statements(seen) == []
    assert not plan.evidence(CAMPAIGN_EVIDENCE_LOCK)
    with pytest.raises(AuthorizationPlanViolationError):
        plan.lock_campaign_evidence(connection)  # a latched plan refuses again
    with pytest.raises(AuthorizationPlanViolationError):
        finalize(connection, plan, scratch)
    assert not plan.finalised
    commit_refused(connection)
    connection.close()
    assert reservations(scratch.engine, key) == 0
    assert markers(scratch.engine) == 0
    assert_next_transaction_is_immediate(one, scratch)


@pytest.mark.parametrize("setting", list(_BAD_SESSIONS.values()), ids=list(_BAD_SESSIONS))
def test_an_invalid_session_is_refused_before_the_evidence_lock_executes(
    scratch: World, one: Engine, setting: str
) -> None:
    """plan + session guard: `search_path` naming `pg_catalog` and a non-`origin` replication role are refused
    by the plan on the bound connection, before the campaign lock statement is sent; the caught refusal
    stays latched and cannot commit."""
    key = new_key()
    connection, plan, reservation = fresh_post(one, scratch, key, evidence=False)
    seen, record = _recording(one)
    connection.execute(text(setting))
    write_all(connection, reservation)
    with listening(one, "before_cursor_execute", record):
        with pytest.raises(AuthorizationPlanViolationError):
            plan.lock_campaign_evidence(connection)
    _assert_refused_before_the_lock(scratch, one, connection, plan, key, seen)


def test_a_lookalike_comparison_operator_refuses_the_session_before_the_evidence_lock(
    scratch: World, one: Engine
) -> None:
    """plan + session guard: a user-defined `=` for `uuid` (here in the scratch schema, visible to the
    guard's catalogue check wherever it lives) is refused before the evidence lock; once dropped, the same
    flow produces evidence."""
    with scratch.engine.begin() as ddl:
        ddl.execute(
            text(
                f"CREATE FUNCTION {SCHEMA}.eq_uuid(uuid, uuid) RETURNS boolean "
                "LANGUAGE sql IMMUTABLE AS 'SELECT false'"
            )
        )
        ddl.execute(
            text(
                f"CREATE OPERATOR {SCHEMA}.= (LEFTARG = uuid, RIGHTARG = uuid, "
                f"FUNCTION = {SCHEMA}.eq_uuid)"
            )
        )
    key = new_key()
    try:
        connection, plan, reservation = fresh_post(one, scratch, key, evidence=False)
        seen, record = _recording(one)
        write_all(connection, reservation)
        with listening(one, "before_cursor_execute", record):
            with pytest.raises(AuthorizationPlanViolationError):
                plan.lock_campaign_evidence(connection)
        _assert_refused_before_the_lock(scratch, one, connection, plan, key, seen)
    finally:
        with scratch.engine.begin() as ddl:
            ddl.execute(text(f"DROP OPERATOR IF EXISTS {SCHEMA}.= (uuid, uuid)"))
            ddl.execute(text(f"DROP FUNCTION IF EXISTS {SCHEMA}.eq_uuid(uuid, uuid)"))
    connection, plan, reservation = fresh_post(one, scratch, new_key())  # control: valid again
    assert plan.evidence(CAMPAIGN_EVIDENCE_LOCK) == {(scratch.campaign_id,)}
    connection.rollback()
    connection.close()


def test_a_compared_column_of_another_type_refuses_the_session_before_the_evidence_lock(
    scratch: World, one: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """plan + session guard: the evidence statement compares `campaign.campaigns.campaign_id`; the plan
    verifies its actual PostgreSQL type against the catalogue (as it does for a declared lock). A type that
    does not match is refused before the lock. (The catalogue is not altered: the expected type is.)"""
    key = new_key()
    connection, plan, reservation = fresh_post(one, scratch, key, evidence=False)
    seen, record = _recording(one)
    real = authorization.kind_and_pg_type
    monkeypatch.setattr(
        authorization,
        "kind_and_pg_type",
        lambda column: (real(column)[0], real(column)[1], "text"),
    )
    write_all(connection, reservation)
    with listening(one, "before_cursor_execute", record):
        with pytest.raises(AuthorizationPlanViolationError):
            plan.lock_campaign_evidence(connection)
    _assert_refused_before_the_lock(scratch, one, connection, plan, key, seen)


def test_a_valid_session_produces_evidence_and_the_pooled_backend_stays_clean(
    scratch: World, one: Engine
) -> None:
    """plan + session guard: with a valid session the validation statements precede the lock, evidence is for
    the plan's campaign, the request commits, and the same pooled backend then carries nothing over (settings
    are the defaults and the next transaction is immediate)."""
    key = new_key()
    seen, record = _recording(one)
    connection, plan = open_post(one, scratch)
    first_pid = pid_of(connection)
    plan.defer_reservation_campaign_fk(connection)
    reservation = reserve(connection, scratch, key)
    assert isinstance(reservation, IdempotentReservation)
    plan.bind_reservation(connection, reservation)
    with listening(one, "before_cursor_execute", record):
        plan.lock_campaign_evidence(connection)
    assert plan.evidence(CAMPAIGN_EVIDENCE_LOCK) == {(scratch.campaign_id,)}
    assert plan.violation is None
    lock_at = next(i for i, s in enumerate(seen) if "FOR KEY SHARE" in s and "campaigns" in s)
    assert any("session_replication_role" in s for s in seen[:lock_at])  # the session check
    assert any("pg_attribute" in s for s in seen[:lock_at])  # the compared-type check
    assert lock_at == len(seen) - 1
    full_request(connection, plan, scratch, reservation)
    connection.commit()
    connection.close()
    assert completed(scratch.engine, key) == 1

    with one.connect() as next_connection:
        assert pid_of(next_connection) == first_pid
        row = next_connection.execute(
            text(
                "SELECT current_setting('session_replication_role'), current_setting('search_path')"
            )
        ).one()
        assert row[0] == "origin" and "pg_catalog" not in row[1]
        next_connection.rollback()
    assert_next_transaction_is_immediate(one, scratch)


# =====================================================================================================
# 4. Waits: the evidence lock and what follows never wait; the deferred check does when nothing is held
# =====================================================================================================


def test_the_evidence_and_the_following_campaign_statement_do_not_wait_behind_a_queued_for_update(
    scratch: World, one: Engine
) -> None:
    """plan + mechanism: with the evidence held, a competitor's campaign `FOR UPDATE` queues behind the
    request (it waits for the request). The scope's existing `FOR KEY SHARE` re-lock, a second evidence
    call, the writes and the COMMIT then all pass the 2 s `lock_timeout` while the competitor is queued:
    none of them waited. The competitor proceeds afterwards."""
    key = new_key()
    connection, plan, reservation = fresh_post(one, scratch, key)
    own_pid = pid_of(connection)
    competitor = run_in_thread("competitor", lambda: _lock_campaign_update_and_commit(scratch))
    wait_until_pid_blocks(scratch.engine, own_pid)
    connection.execute(
        text("SELECT campaign_id FROM campaign.campaigns WHERE campaign_id = :c FOR KEY SHARE"),
        {"c": scratch.campaign_id},
    ).all()  # the scope's existing statement
    plan.lock_campaign_evidence(connection)
    full_request(connection, plan, scratch, reservation)
    assert not competitor.finished()
    connection.commit()  # the deferred FK check re-acquires a held KEY SHARE
    competitor.wait("the competitor proceeds after the request committed")
    connection.close()
    assert completed(scratch.engine, key) == 1


def test_the_reservation_does_not_wait_and_without_evidence_the_commit_check_would(
    scratch: World, one: Engine
) -> None:
    """mechanism on the plan's own deferral: with a campaign `FOR UPDATE` held elsewhere, the deferred
    reservation INSERT returns at once (it holds no campaign lock). A raw DBAPI COMMIT, which bypasses the
    guard on purpose, then waits at COMMIT: the deferred check takes the lock only then. That wait is
    exactly what the evidence obligation removes."""
    key = new_key()
    connection, plan = open_post(one, scratch, patient=True)
    plan.defer_reservation_campaign_fk(connection)
    holder, holder_pid = hold_campaign(scratch.engine, scratch.campaign_id)
    reservation = reserve(connection, scratch, key)  # would block here without the deferral
    assert isinstance(reservation, IdempotentReservation)
    assert sessions_blocked_by(scratch.engine, holder_pid) == 0
    driver = connection.connection.driver_connection
    assert driver is not None
    request = run_in_thread("raw-commit", driver.commit)
    try:
        wait_until_pid_blocks(scratch.engine, holder_pid)
        assert not request.finished()
    finally:
        release(holder)
    request.wait("the raw COMMIT completes once the holder released")
    connection.close()
    assert reservations(scratch.engine, key) == 1
    with scratch.engine.begin() as cleanup:
        cleanup.execute(
            text("DELETE FROM security.idempotent_requests WHERE idempotency_key = :k"), {"k": key}
        )


# =====================================================================================================
# 5. Savepoints, constraint-mode policing, unsupported calls, unchanged behaviour
# =====================================================================================================


def test_a_savepoint_rollback_after_deferral_outcome_or_evidence_latches(
    scratch: World, one: Engine
) -> None:
    """plan: once the plan holds the deferral, a bound outcome or campaign evidence, rolling a savepoint
    back latches `SAVEPOINT_ROLLBACK` and refuses the commit; a caught rollback stays latched."""
    connection, plan = open_post(one, scratch)
    plan.defer_reservation_campaign_fk(connection)
    nested = connection.begin_nested()
    nested.rollback()
    assert plan.violation is R.SAVEPOINT_ROLLBACK
    connection.close()

    connection, plan = open_post(one, scratch)
    plan.defer_reservation_campaign_fk(connection)
    reservation = reserve(connection, scratch, new_key())
    assert isinstance(reservation, IdempotentReservation)
    plan.bind_reservation(connection, reservation)
    nested = connection.begin_nested()
    nested.rollback()
    assert plan.violation is R.SAVEPOINT_ROLLBACK
    commit_refused(connection)
    connection.close()

    connection, plan, reservation = fresh_post(one, scratch, new_key())
    with contextlib.suppress(Exception):
        with connection.begin_nested() as savepoint:
            savepoint.rollback()
    assert plan.violation is R.SAVEPOINT_ROLLBACK
    write_all(connection, reservation)
    with pytest.raises(AuthorizationPlanViolationError):
        finalize(connection, plan, scratch)  # a latched plan cannot finalize
    commit_refused(connection)
    connection.close()
    assert markers(scratch.engine) == 0
    assert_next_transaction_is_immediate(one, scratch)


def test_a_savepoint_rollback_on_a_plan_that_never_opted_in_is_not_a_violation(
    scratch: World, one: Engine
) -> None:
    """plan (immediate-by-default, S-8 neutrality): a registered plan that holds no deferral, outcome or
    evidence behaves as an ordinary post-write plan; a released savepoint never latches."""
    connection, plan = open_post(one, scratch)
    nested = connection.begin_nested()
    nested.rollback()
    assert plan.violation is None
    write_all(connection)
    finalize(connection, plan, scratch)
    connection.commit()
    connection.close()

    key = new_key()
    connection, plan, reservation = fresh_post(one, scratch, key)
    with connection.begin_nested():
        connection.execute(text("SELECT 1")).all()  # released, not rolled back
    assert plan.violation is None
    full_request(connection, plan, scratch, reservation)
    connection.commit()
    connection.close()
    assert completed(scratch.engine, key) == 1


def test_an_unauthorized_constraint_mode_change_still_latches(scratch: World, one: Engine) -> None:
    """plan (AM-1.10): only the plan's own deferral passes; any other statement that may change the
    reservation FK's mode latches the keyed post-write plan, before and after the opt-in, and a change made
    before the plan exists starts it latched."""
    for statement in (
        f"SET CONSTRAINTS {FK} IMMEDIATE",
        "SET CONSTRAINTS ALL DEFERRED",
    ):
        connection, plan = open_post(one, scratch)
        plan.defer_reservation_campaign_fk(connection)
        with pytest.raises(AuthorizationPlanViolationError):
            connection.execute(text(statement))
        assert plan.violation is R.CONSTRAINT_MODE
        connection.close()

    connection, plan = open_post(one, scratch)
    with pytest.raises(AuthorizationPlanViolationError):
        connection.execute(text(f"SET CONSTRAINTS {FK} DEFERRED"))
    assert plan.violation is R.CONSTRAINT_MODE
    with pytest.raises(AuthorizationPlanViolationError):
        plan.defer_reservation_campaign_fk(connection)
    connection.close()

    connection = track(one.connect())
    connection.begin()
    connection.execute(text(f"SET CONSTRAINTS {FK} DEFERRED"))  # no plan yet: cannot be refused
    plan = AuthorizationPlan.begin(
        connection,
        actor_user_id=scratch.gm_user,
        campaign_id=scratch.campaign_id,
        keyed_post_write=True,
    )
    assert plan.violation is R.CONSTRAINT_MODE
    commit_refused(connection)
    connection.close()


def test_calls_that_belong_to_other_plan_kinds_are_refused(scratch: World, one: Engine) -> None:
    """plan (AM-1.3): `bind_unkeyed` is refused on a keyed post-write plan, `lock` and `execute` (pre-write
    calls) latch `SEQUENCE`, deferral is once-only and never after finalize, and `bind_reservation` needs the
    deferral first."""
    connection, plan = open_post(one, scratch)
    with pytest.raises(AuthorizationPlanStateError):
        plan.bind_unkeyed(connection)
    assert plan.violation is R.OUTCOME
    connection.close()

    connection, plan = open_post(one, scratch)
    with pytest.raises(AuthorizationPlanStateError):
        plan.lock(connection, CAMPAIGN_EVIDENCE_LOCK, {"campaign": scratch.campaign_id})
    assert plan.violation is R.SEQUENCE
    connection.close()

    connection, plan = open_post(one, scratch)
    plan.defer_reservation_campaign_fk(connection)
    with pytest.raises(AuthorizationPlanStateError):
        plan.defer_reservation_campaign_fk(connection)  # once
    assert plan.violation is R.DEFERRAL
    connection.close()

    connection, plan = open_post(one, scratch)
    write_all(connection)
    finalize(connection, plan, scratch)
    with pytest.raises(AuthorizationPlanStateError):
        plan.defer_reservation_campaign_fk(connection)  # after finalize
    assert plan.violation is R.DEFERRAL
    connection.close()

    connection, plan = open_post(one, scratch)
    nested = connection.begin_nested()
    with pytest.raises(AuthorizationPlanStateError):
        plan.defer_reservation_campaign_fk(connection)  # never inside a savepoint
    nested.rollback()
    connection.close()


def test_a_non_registered_post_write_plan_issues_exactly_the_statements_it_always_did(
    scratch: World, one: Engine
) -> None:
    """plan: for a post-write plan that is not registered, the statement list is the ordinary one: no
    deferral statement, no campaign lock, the final snapshot last."""

    def statements(keyed: bool) -> list[str]:
        seen: list[str] = []

        def record(
            conn: Connection, cursor: Any, statement: str, parameters: Any, context: Any, many: bool
        ) -> None:
            seen.append(statement)

        connection, plan = open_post(one, scratch, keyed=keyed)
        with listening(one, "before_cursor_execute", record):
            reservation = reserve(connection, scratch, new_key())
            assert isinstance(reservation, IdempotentReservation)
            full_request(connection, plan, scratch, reservation)
            connection.commit()
        connection.close()
        return seen

    plain = statements(False)
    assert not any("CONSTRAINTS" in s.upper() for s in plain)
    assert not any("campaigns" in s and "FOR KEY SHARE" in s for s in plain)
    reservation_sql = next(s for s in plain if "idempotent_requests" in s)
    assert reservation_sql.lstrip().upper().startswith("INSERT")
    assert "AS relationships" in plain[-1]  # the final snapshot is the last statement
    registered = statements(True)
    assert registered == plain  # a registered plan that does not defer is immediate by default


def test_after_finalize_no_statement_is_admitted(scratch: World, one: Engine) -> None:
    """plan: the post-write rule is unchanged: any statement after `finalize`, even a `SELECT`, latches
    `POST_WRITE_STATEMENT` and refuses the commit."""
    connection, plan, reservation = fresh_post(one, scratch, new_key())
    full_request(connection, plan, scratch, reservation)
    connection.execute(text("SELECT 1")).all()
    assert plan.violation is R.POST_WRITE_STATEMENT
    with pytest.raises(AuthorizationPlanNotFinalizedError):
        connection.commit()
    connection.close()
    assert markers(scratch.engine) == 0


# =====================================================================================================
# 6. Pooled reuse
# =====================================================================================================


def test_the_pooled_connection_is_immediate_again_after_every_ending(
    scratch: World, one: Engine
) -> None:
    """plan: after a committed deferred request, a rolled-back one, a refused `finalize`, a refused COMMIT and a
    failed evidence statement, the same pooled backend is at the immediate default, and a following plan
    starts clean (no state of the previous plan leaks)."""
    pids: set[int] = set()

    connection, plan, reservation = fresh_post(one, scratch, new_key())
    pids.add(pid_of(connection))
    full_request(connection, plan, scratch, reservation)
    connection.commit()
    connection.close()
    assert_next_transaction_is_immediate(one, scratch)

    connection, plan, reservation = fresh_post(one, scratch, new_key())
    pids.add(pid_of(connection))
    connection.rollback()
    connection.close()
    assert_next_transaction_is_immediate(one, scratch)

    connection, plan, reservation = fresh_post(one, scratch, new_key(), evidence=False)
    pids.add(pid_of(connection))
    write_all(connection, reservation)
    with pytest.raises(AuthorizationPlanViolationError):
        finalize(connection, plan, scratch)
    connection.close()
    assert_next_transaction_is_immediate(one, scratch)

    connection, plan, reservation = fresh_post(one, scratch, new_key())
    pids.add(pid_of(connection))
    commit_refused(connection)
    connection.close()
    assert_next_transaction_is_immediate(one, scratch)

    # the next request on the same backend: a registered plan that has not opted in is plain
    connection, plan = open_post(one, scratch)
    assert pid_of(connection) in pids
    assert not plan.deferred and not plan.violated and not plan.evidence(CAMPAIGN_EVIDENCE_LOCK)
    write_all(connection)
    finalize(connection, plan, scratch)
    connection.commit()
    connection.close()
    assert len(pids) == 1  # all of them ran on the one pooled connection


def test_post_write_mode_is_unchanged_for_a_plan_that_is_not_registered(
    scratch: World, one: Engine
) -> None:
    """plan: a default post-write plan has no keyed state: it cannot defer, bind or take evidence."""
    connection, plan = open_post(one, scratch, keyed=False)
    assert plan.mode is PlanMode.POST_WRITE and not plan.keyed_post_write
    with pytest.raises(AuthorizationPlanStateError):
        plan.defer_reservation_campaign_fk(connection)
    assert plan.violation is R.DEFERRAL
    connection.close()
