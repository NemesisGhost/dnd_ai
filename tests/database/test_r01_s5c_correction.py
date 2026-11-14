# ruff: noqa: F811, F401, SIM117 - imported fixtures are used by name; nested `with` keeps each expected failure separate
"""R01 S5-C correction: constraint-mode changes on the reservation FK belong to the plan API, and
`bind_unkeyed` cannot follow a recorded reservation.

Guarantee tested: **supported application execution paths**. Every statement here goes through the
application engine (`text()`, `exec_driver_sql`), which is what the guard's `before_cursor_execute` sees.
NOT claimed: a raw DBAPI cursor (`connection.connection.cursor()`), another database session that
cannot affect this transaction anyway, dynamic SQL that assembles `SET CONSTRAINTS` at run time, or
hostile in-process code. Those are outside the supported contract (module docstring of
`dnd_ai.domain.authorization`).
"""

import uuid
from typing import Any

import pytest
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import DBAPIError

from dnd_ai.api.idempotency import IdempotentReplay, IdempotentReservation
from dnd_ai.commands._content import canon_edit_requirement
from dnd_ai.domain.authorization import (
    AuthorizationPlan,
    AuthorizationPlanNotFinalizedError,
    AuthorizationPlanStateError,
    AuthorizationPlanViolationError,
    PlanMode,
    ViolationReason,
    changes_reservation_fk_mode,
    install_authorization_guard,
)
from dnd_ai.domain.reservation_outcome import recorded_reservation_outcome
from tests.database.test_r01_s3_authoring_routes import World, w  # noqa: F401 - fixture by name
from tests.database.test_r01_s5c_reservation_deferral import (
    FK,
    _step,
    assert_next_transaction_is_immediate,
    campaign_b,
    commit_refused,
    complete_first,
    completed,
    declarations,
    finish,
    fresh,
    hold_campaign,
    markers,
    one,
    open_plan,
    release,
    reservations,
    reserve,
    scratch,
    track,
)
from tests.http_race_support import new_key, run_in_thread, wait_until_pid_blocks

pytestmark = pytest.mark.database

R = ViolationReason
TARGET = "idempotent_requests_campaign_id_fkey"

# every spelling that names the reservation campaign FK or every constraint, each in both modes
AFFECTING = [
    "SET CONSTRAINTS ALL DEFERRED",
    "set constraints all immediate",
    f"SET CONSTRAINTS security.{TARGET} DEFERRED",
    f"SET CONSTRAINTS security.{TARGET} IMMEDIATE",
    f'SET CONSTRAINTS "security"."{TARGET}" DEFERRED',
    f'SET CONSTRAINTS "{TARGET}" IMMEDIATE',
    f"SET CONSTRAINTS {TARGET} DEFERRED",
    f"SET CONSTRAINTS some_other.fk, security . {TARGET} DEFERRED",
    f"SET /* c */ CONSTRAINTS security.{TARGET} DEFERRED",
    f"SELECT 1; SET CONSTRAINTS security.{TARGET} DEFERRED",
]


@pytest.mark.parametrize("sql", AFFECTING)
def test_the_classifier_recognizes_every_spelling(sql: str) -> None:
    assert changes_reservation_fk_mode(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1",
        "SET CONSTRAINTS security.some_other_fk DEFERRED",
        'SET CONSTRAINTS "Some_Other", x.y IMMEDIATE',
        f'SET CONSTRAINTS "{TARGET.upper()}" DEFERRED',  # quoted upper case is a different name
        "ALTER TABLE t ADD CONSTRAINT c CHECK (true)",
    ],
)
def test_the_classifier_leaves_other_statements_alone(sql: str) -> None:
    assert not changes_reservation_fk_mode(sql)


def _run(connection: Connection, sql: str, how: str) -> None:
    if how == "text":
        connection.execute(text(sql))
    else:
        connection.exec_driver_sql(sql)


# --- the exact bypass, and its variants ----------------------------------------------------------


@pytest.mark.parametrize("how", ["text", "driver"])
def test_the_exact_raw_deferral_bypass_is_refused_before_it_runs(
    scratch: World, one: Engine, how: str
) -> None:
    """Raw `SET CONSTRAINTS ALL DEFERRED` after the plan opens and before it finalizes is refused before
    the driver sees it, latches the plan, and the reservation FK is still immediate (a held campaign
    `FOR UPDATE` blocks the reservation INSERT, which a deferred constraint would not)."""
    holder, holder_pid = hold_campaign(scratch.engine, scratch.campaign_id)
    connection, plan = open_plan(one, scratch, declarations(), patient=True)
    with pytest.raises(AuthorizationPlanViolationError):
        _run(connection, "SET CONSTRAINTS ALL DEFERRED", how)
    assert plan.violation is R.CONSTRAINT_MODE
    assert not plan.deferred
    key = new_key()
    request = run_in_thread("reserve", lambda: reserve(connection, scratch, key))
    try:
        wait_until_pid_blocks(scratch.engine, holder_pid)  # still immediate: the INSERT waits
    finally:
        release(holder)
    reservation = request.wait("reserved once the holder released")
    # a caller that catches the refusal and carries on gets nowhere: every later call stays refused
    with pytest.raises(AuthorizationPlanViolationError):
        plan.bind_reservation(connection, reservation)
    with pytest.raises(AuthorizationPlanViolationError):
        plan.defer_reservation_campaign_fk(connection)
    with pytest.raises(AuthorizationPlanViolationError):
        plan.finalize(connection)
    commit_refused(connection)
    connection.close()
    assert reservations(scratch.engine, key) == 0


@pytest.mark.parametrize("sql", AFFECTING)
def test_every_spelling_is_refused_and_latches(scratch: World, one: Engine, sql: str) -> None:
    """Explicit target-FK, schema-qualified, quoted, ALL, comment-obfuscated and multi-statement forms,
    DEFERRED and IMMEDIATE."""
    connection, plan = open_plan(one, scratch, declarations())
    with pytest.raises(AuthorizationPlanViolationError):
        connection.exec_driver_sql(sql)
    assert plan.violation is R.CONSTRAINT_MODE
    commit_refused(connection)
    connection.close()


def test_an_unauthorized_immediate_change_after_the_approved_deferral_is_refused(
    scratch: World, one: Engine
) -> None:
    """The approved API deferral works; undoing it (or restating it) from outside is refused and latched,
    so the ordering the plan relies on cannot be silently altered mid-request."""
    connection, plan = open_plan(one, scratch, declarations())
    plan.defer_reservation_campaign_fk(connection)
    assert plan.deferred and plan.violation is None
    with pytest.raises(AuthorizationPlanViolationError):
        connection.exec_driver_sql(f"SET CONSTRAINTS security.{TARGET} IMMEDIATE")
    assert plan.violation is R.CONSTRAINT_MODE
    commit_refused(connection)
    connection.close()


def test_the_approved_api_deferral_still_commits_a_full_request(
    scratch: World, one: Engine
) -> None:
    key = new_key()
    connection, plan, reservation = fresh(one, scratch, key)
    assert plan.deferred and plan.violation is None
    finish(connection, plan, scratch, reservation)
    connection.commit()
    connection.close()
    assert completed(scratch.engine, key) == 1


def test_other_constraints_are_not_touched_by_the_guard(scratch: World, one: Engine) -> None:
    """`SET CONSTRAINTS` on another constraint passes the guard and reaches the database (which here
    rejects it as not deferrable); the plan is not latched by it."""
    connection, plan = open_plan(one, scratch, declarations())
    with pytest.raises(DBAPIError, match="not deferrable"):
        connection.exec_driver_sql(
            "SET CONSTRAINTS security.idempotent_requests_actor_user_id_fkey DEFERRED"
        )
    assert plan.violation is None
    connection.close()


def test_a_change_made_before_the_plan_exists_latches_the_plan_when_it_opens(
    scratch: World, one: Engine
) -> None:
    """Nothing can be protected before a keyed plan exists, so the statement is allowed but marks the
    transaction; a keyed plan opened in it starts latched. A new transaction on the same pooled
    connection is clean."""
    install_authorization_guard(one)  # production installs it when the engine is created (deps.py)
    connection = track(one.connect())
    connection.begin()
    connection.exec_driver_sql("SET CONSTRAINTS ALL DEFERRED")
    plan = AuthorizationPlan.begin(
        connection,
        actor_user_id=scratch.gm_user,
        campaign_id=scratch.campaign_id,
        mode=PlanMode.PRE_WRITE,
        by_outcome=declarations(),
    )
    assert plan.violation is R.CONSTRAINT_MODE
    with pytest.raises(AuthorizationPlanViolationError):
        plan.defer_reservation_campaign_fk(connection)
    commit_refused(connection)
    connection.close()
    assert_next_transaction_is_immediate(one, scratch)

    key = new_key()  # same pooled connection, new transaction: nothing leaked
    connection, plan, reservation = fresh(one, scratch, key)
    assert plan.violation is None
    finish(connection, plan, scratch, reservation)
    connection.commit()
    connection.close()
    assert completed(scratch.engine, key) == 1


def test_a_refusal_rolls_back_and_the_pooled_connection_is_clean(
    scratch: World, one: Engine
) -> None:
    key = new_key()
    connection, plan, reservation = fresh(one, scratch, key)
    with pytest.raises(AuthorizationPlanViolationError):
        connection.exec_driver_sql("SET CONSTRAINTS ALL IMMEDIATE")
    connection.rollback()
    connection.close()
    assert reservations(scratch.engine, key) == 0
    assert_next_transaction_is_immediate(one, scratch)


# --- bind_unkeyed after a recorded reservation -------------------------------------------------------


@pytest.mark.parametrize("defer", [False, True])
def test_bind_unkeyed_after_a_new_reservation_is_refused_and_leaves_the_record(
    scratch: World, one: Engine, defer: bool
) -> None:
    """The server already answered for a key in this transaction, so the request is keyed even though
    `bind_reservation` has not run. The refusal latches, the record is not cleared, and the request
    cannot be re-bound as keyed afterwards."""
    key = new_key()
    connection, plan = open_plan(one, scratch, declarations())
    if defer:  # without it the refusal can only come from the recorded server outcome
        plan.defer_reservation_campaign_fk(connection)
    reservation = reserve(connection, scratch, key)
    assert isinstance(reservation, IdempotentReservation)
    with pytest.raises(AuthorizationPlanStateError):
        plan.bind_unkeyed(connection)
    assert plan.violation is R.OUTCOME
    assert recorded_reservation_outcome(connection) is reservation.outcome
    assert plan.reservation_kind is None
    with pytest.raises(AuthorizationPlanViolationError):  # caught-and-continue goes nowhere
        plan.bind_reservation(connection, reservation)
    commit_refused(connection)
    connection.close()
    assert reservations(scratch.engine, key) == 0


def test_bind_unkeyed_after_a_replay_record_is_refused(scratch: World, one: Engine) -> None:
    key = new_key()
    complete_first(one, scratch, key)
    connection, plan = open_plan(one, scratch, declarations())
    replay = reserve(connection, scratch, key)
    assert isinstance(replay, IdempotentReplay)
    with pytest.raises(AuthorizationPlanStateError):
        plan.bind_unkeyed(connection)
    assert plan.violation is R.OUTCOME
    assert recorded_reservation_outcome(connection) is replay.outcome
    connection.close()


def test_legitimate_unkeyed_execution_and_keyed_replay_still_work(
    scratch: World, one: Engine
) -> None:
    """A record left by an earlier, rolled-back transaction on the pooled connection is not this plan's
    (another transaction), so an unkeyed request binds and commits; a keyed replay still binds, is judged
    by the route requirement and commits with the empty declaration."""
    connection = track(one.connect())
    connection.begin()
    reserve(connection, scratch, new_key())  # leaves a record on the connection
    connection.rollback()
    connection.close()

    connection, plan = open_plan(one, scratch, declarations())
    plan.bind_unkeyed(connection)
    plan.require(connection, canon_edit_requirement(scratch.gm_user, scratch.campaign_id))
    plan.finalize(connection)
    plan.execute(connection, _step(plan, "ins_marker"), {"note": "unkeyed"})
    connection.commit()
    connection.close()
    assert markers(scratch.engine) == 1

    key = new_key()
    complete_first(one, scratch, key)
    connection, plan = open_plan(one, scratch, declarations())
    plan.defer_reservation_campaign_fk(connection)
    plan.bind_reservation(connection, reserve(connection, scratch, key))
    plan.require(connection, canon_edit_requirement(scratch.gm_user, scratch.campaign_id))
    plan.finalize(connection)
    connection.commit()
    connection.close()
    assert (
        markers(scratch.engine) == 2
    )  # the first command's marker plus the unkeyed one; replay wrote none
