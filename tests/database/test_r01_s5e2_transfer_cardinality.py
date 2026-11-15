# ruff: noqa: F811 - the imported fixture `w` is used by name
"""R01 S5-E2 ownership-transfer amendment: `PerAbsence`, `AnyConfirmed` and the savepoint latch (plan 6.27.4).

`PerAbsence(lock)` owes exactly one INSERT on *proven-empty* evidence of one declared lock; `AnyConfirmed(steps)`
owes exactly one INSERT iff any named earlier step confirmed a key. These tests drive `AuthorizationPlan`
directly against scratch tables, so each rule is shown apart from any route. Evidence classes:

- **plan**: the S1/S5-C API on a real connection and transaction;
- **declaration**: validation at construction (no database).

An INSERT refused before the driver call is proved by the recorded statement stream, not assumed.
"""

import contextlib
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import (
    Column,
    Connection,
    Engine,
    Identity,
    Integer,
    MetaData,
    Table,
    Text,
    Uuid,
    bindparam,
    create_engine,
    event,
    insert,
    select,
    text,
    update,
)

from dnd_ai.commands._pre_write_steps import RECEIPT_STEP
from dnd_ai.domain.authorization import (
    AuthorizationPlan,
    AuthorizationPlanNotFinalizedError,
    AuthorizationPlanStateError,
    AuthorizationPlanViolationError,
    PlanMode,
    ViolationReason,
)
from dnd_ai.domain.authorization_steps import (
    AnyConfirmed,
    Between,
    DeclarationError,
    EachLockedRow,
    Exactly,
    KeyBind,
    PerAbsence,
    PerEvidence,
    PreLock,
    PreWriteDeclaration,
    RowExpectation,
    WriteStep,
)
from tests.database.test_r01_s3_authoring_routes import World, w  # noqa: F401 - fixture by name

pytestmark = pytest.mark.database

R = ViolationReason
SCHEMA = "r01_s5e2_abs"

_meta = MetaData()
gate = Table(
    "gate",
    _meta,
    Column("gate_id", Uuid, primary_key=True),
    Column("flag", Text, nullable=False),
    schema=SCHEMA,
)
marker = Table(
    "marker",
    _meta,
    Column("marker_id", Integer, Identity(), primary_key=True),
    Column("note", Text, nullable=False),
    schema=SCHEMA,
)

ONE_LOCK = PreLock(
    "one_lock",
    select(gate.c.gate_id).where(gate.c.flag == bindparam("f")).with_for_update(),
)
OTHER_LOCK = PreLock(
    "other_lock",
    select(gate.c.gate_id).where(gate.c.flag == bindparam("f")).with_for_update(),
)
INS_ABSENT = WriteStep(
    name="ins_absent",
    statement=insert(marker).values(note=bindparam("note")).returning(marker.c.marker_id),
    cardinality=PerAbsence(ONE_LOCK),
    value_binds=frozenset({"note"}),
)
ABSENCE = PreWriteDeclaration(locks=(ONE_LOCK, OTHER_LOCK), steps=(INS_ABSENT,))

UPD_A = WriteStep(
    name="upd_a",
    statement=update(gate)
    .where(gate.c.gate_id == bindparam("g"))
    .values(flag=bindparam("new_flag"))
    .returning(gate.c.gate_id),
    cardinality=EachLockedRow(complete=True),
    target=(KeyBind(gate.c.gate_id, "g"),),
    target_lock=ONE_LOCK,
    value_binds=frozenset({"new_flag"}),
)
#: attempted, possibly confirming nothing (`ZERO_OR_ONE`): the guard on `flag` keeps the row out
UPD_B = WriteStep(
    name="upd_b",
    statement=update(gate)
    .where(gate.c.gate_id == bindparam("g"))
    .where(gate.c.flag == "never")
    .values(flag=bindparam("new_flag"))
    .returning(gate.c.gate_id),
    cardinality=Between(0, 1),
    rows=RowExpectation.ZERO_OR_ONE,
    target=(KeyBind(gate.c.gate_id, "g"),),
    target_lock=ONE_LOCK,
    value_binds=frozenset({"new_flag"}),
)
UPD_C = WriteStep(
    name="upd_c",
    statement=update(gate)
    .where(gate.c.gate_id == bindparam("g"))
    .values(flag=bindparam("new_flag"))
    .returning(gate.c.gate_id),
    cardinality=Between(0, 2),
    target=(KeyBind(gate.c.gate_id, "g"),),
    target_lock=OTHER_LOCK,
    value_binds=frozenset({"new_flag"}),
)
INS_ANY = WriteStep(
    name="ins_any",
    statement=insert(marker).values(note=bindparam("note")).returning(marker.c.marker_id),
    cardinality=AnyConfirmed((UPD_A, UPD_C)),
    value_binds=frozenset({"note"}),
)
INS_ANY_UNCONFIRMED = WriteStep(
    name="ins_any_unconfirmed",
    statement=insert(marker).values(note=bindparam("note")).returning(marker.c.marker_id),
    cardinality=AnyConfirmed((UPD_B,)),
    value_binds=frozenset({"note"}),
)
INS_EXACT = WriteStep(
    name="ins_exact",
    statement=insert(marker).values(note=bindparam("note")).returning(marker.c.marker_id),
    cardinality=Exactly(1),
    value_binds=frozenset({"note"}),
)
ANY = PreWriteDeclaration(locks=(ONE_LOCK, OTHER_LOCK), steps=(UPD_A, UPD_C, INS_ANY))
ANY_UNCONFIRMED = PreWriteDeclaration(locks=(ONE_LOCK,), steps=(UPD_B, INS_ANY_UNCONFIRMED))
EXACT_ONLY = PreWriteDeclaration(locks=(), steps=(INS_EXACT,))

_OPEN: list[Connection] = []


@pytest.fixture
def ev(w: World) -> Iterator[World]:
    """Scratch tables: `gate` holds the evidence rows (flag `one`: one row, `two`: two rows, `none`: none)."""
    admin = w.engine.execution_options(isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE"))
        connection.execute(text(f"CREATE SCHEMA {SCHEMA}"))
        connection.execute(
            text(f"CREATE TABLE {SCHEMA}.gate (gate_id uuid PRIMARY KEY, flag text NOT NULL)")
        )
        connection.execute(
            text(
                f"CREATE TABLE {SCHEMA}.marker (marker_id int GENERATED ALWAYS AS IDENTITY "
                "PRIMARY KEY, note text NOT NULL)"
            )
        )
        for flag in ("one", "two", "two"):
            connection.execute(
                text(f"INSERT INTO {SCHEMA}.gate VALUES (:g, :f)"), {"g": uuid.uuid4(), "f": flag}
            )
    try:
        yield w
    finally:
        for connection in _OPEN:
            with contextlib.suppress(Exception):
                connection.invalidate()
            with contextlib.suppress(Exception):
                connection.close()
        _OPEN.clear()
        with admin.connect() as connection:
            connection.execute(text(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE"))


class Statements:
    """Every statement the engine hands the driver, in order (registered before any plan exists)."""

    def __init__(self, engine: Engine) -> None:
        self.seen: list[str] = []
        event.listen(engine, "before_cursor_execute", self._hook)

    def _hook(self, _c: Any, _cursor: Any, statement: Any, *_: Any) -> None:
        self.seen.append(" ".join(str(statement).split()))

    def mark(self) -> int:
        return len(self.seen)

    def inserts_since(self, mark: int) -> int:
        return sum(1 for s in self.seen[mark:] if s.startswith(f"INSERT INTO {SCHEMA}.marker"))


RECORDERS: dict[Engine, Statements] = {}


@pytest.fixture
def one(ev: World) -> Iterator[Engine]:
    """A one-connection pool: the next transaction reuses the connection the previous one left."""
    engine = create_engine(ev.engine.url, pool_size=1, max_overflow=0)
    RECORDERS[engine] = Statements(engine)
    try:
        yield engine
    finally:
        RECORDERS.pop(engine, None)
        engine.dispose()


def begin(
    engine: Engine, w: World, declaration: PreWriteDeclaration = ABSENCE
) -> tuple[Connection, AuthorizationPlan]:
    connection = engine.connect()
    _OPEN.append(connection)
    connection.begin()
    connection.execute(text("SET LOCAL lock_timeout = '2s'"))
    plan = AuthorizationPlan.begin(
        connection,
        actor_user_id=w.gm_user,
        campaign_id=w.campaign_id,
        mode=PlanMode.PRE_WRITE,
        pre_write=declaration,
    )
    return connection, plan


def markers(engine: Engine) -> int:
    with engine.connect() as connection:
        return int(connection.execute(text(f"SELECT count(*) FROM {SCHEMA}.marker")).scalar_one())


def commit_refused(connection: Connection) -> None:
    with pytest.raises(AuthorizationPlanNotFinalizedError):
        connection.commit()


def lock(
    connection: Connection, plan: AuthorizationPlan, flag: str, which: PreLock = ONE_LOCK
) -> Any:
    return plan.lock(connection, which, {"f": flag})


def run_absent(connection: Connection, plan: AuthorizationPlan, note: str = "n") -> Any:
    return plan.execute(connection, INS_ABSENT, {"note": note})


def run_update(connection: Connection, plan: AuthorizationPlan, step: WriteStep, key: Any) -> Any:
    return plan.execute(connection, step, {"g": key[0], "new_flag": "changed"})


# =====================================================================================================
# PerAbsence
# =====================================================================================================


def test_empty_evidence_requires_exactly_one_insert_and_one_commits(ev: World, one: Engine) -> None:
    """plan: the positive case. The lock ran and returned nothing; the INSERT ran once; COMMIT is accepted."""
    connection, plan = begin(one, ev)
    assert lock(connection, plan, "none") == ()
    plan.finalize(connection)
    outcome = run_absent(connection, plan)
    assert len(outcome.keys) == 1
    connection.commit()
    assert markers(ev.engine) == 1


def test_empty_evidence_and_an_omitted_insert_is_refused_at_commit_and_rolls_back(
    ev: World, one: Engine
) -> None:
    """plan: the completeness obligation, the converse of `PerEvidence`: proven absence with no INSERT."""
    connection, plan = begin(one, ev)
    lock(connection, plan, "none")
    plan.finalize(connection)
    commit_refused(connection)
    assert plan.violation is R.INCOMPLETE
    connection.close()
    assert markers(ev.engine) == 0


def test_a_second_insert_on_empty_evidence_is_refused_before_the_driver_and_latches(
    ev: World, one: Engine
) -> None:
    connection, plan = begin(one, ev)
    lock(connection, plan, "none")
    plan.finalize(connection)
    run_absent(connection, plan)
    mark = RECORDERS[one].mark()
    with pytest.raises(AuthorizationPlanViolationError):
        run_absent(connection, plan, "again")
    assert RECORDERS[one].inserts_since(mark) == 0 and plan.violation is R.COUNT
    commit_refused(connection)
    connection.close()
    assert markers(ev.engine) == 0


def test_one_evidence_row_forbids_the_insert_and_owes_nothing(ev: World, one: Engine) -> None:
    """plan: a row exists, so nothing is inserted: the attempt is refused (`EVIDENCE`) before the driver; without
    it the plan commits."""
    connection, plan = begin(one, ev)
    assert len(lock(connection, plan, "one")) == 1
    plan.finalize(connection)
    mark = RECORDERS[one].mark()
    with pytest.raises(AuthorizationPlanViolationError):
        run_absent(connection, plan)
    assert RECORDERS[one].inserts_since(mark) == 0 and plan.violation is R.EVIDENCE
    commit_refused(connection)  # caught or not, the latch refuses the commit
    connection.close()

    connection, plan = begin(one, ev)
    lock(connection, plan, "one")
    plan.finalize(connection)
    connection.commit()
    connection.close()
    assert markers(ev.engine) == 0


def test_two_evidence_rows_are_unsupported_for_both_the_insert_and_its_omission(
    ev: World, one: Engine
) -> None:
    """plan: the rule is zero-or-one. Two rows refuse the INSERT (`EVIDENCE`) and, without it, the commit."""
    connection, plan = begin(one, ev)
    assert len(lock(connection, plan, "two")) == 2
    plan.finalize(connection)
    mark = RECORDERS[one].mark()
    with pytest.raises(AuthorizationPlanViolationError):
        run_absent(connection, plan)
    assert RECORDERS[one].inserts_since(mark) == 0 and plan.violation is R.EVIDENCE
    commit_refused(connection)
    connection.close()

    connection, plan = begin(one, ev)
    lock(connection, plan, "two")
    plan.finalize(connection)
    commit_refused(connection)  # not accepted as "zero"
    assert plan.violation is R.INCOMPLETE
    connection.close()
    assert markers(ev.engine) == 0


def test_a_second_call_that_adds_a_row_to_empty_evidence_makes_it_unsupported(
    ev: World, one: Engine
) -> None:
    """plan: evidence is the union over calls: empty then one row is a row (forbidden), empty then two is two."""
    connection, plan = begin(one, ev)
    lock(connection, plan, "none")
    lock(connection, plan, "two")
    plan.finalize(connection)
    with pytest.raises(AuthorizationPlanViolationError):
        run_absent(connection, plan)
    commit_refused(connection)
    connection.close()
    assert markers(ev.engine) == 0


def test_a_lock_that_never_ran_is_missing_evidence_not_empty_evidence(
    ev: World, one: Engine
) -> None:
    """plan: no lock call at all. The INSERT is refused (`EVIDENCE`) and, with no INSERT, so is the commit: missing
    evidence is neither "empty" (which would owe an INSERT that could then be forged by skipping the lock) nor "one"."""
    connection, plan = begin(one, ev)
    plan.finalize(connection)
    mark = RECORDERS[one].mark()
    with pytest.raises(AuthorizationPlanViolationError):
        run_absent(connection, plan)
    assert RECORDERS[one].inserts_since(mark) == 0 and plan.violation is R.EVIDENCE
    connection.close()

    connection, plan = begin(one, ev)
    plan.finalize(connection)
    commit_refused(connection)
    assert plan.violation is R.INCOMPLETE
    connection.close()
    assert markers(ev.engine) == 0


def test_a_lock_that_failed_leaves_no_evidence_and_latches(ev: World, one: Engine) -> None:
    connection, plan = begin(one, ev)
    with pytest.raises(AuthorizationPlanViolationError):
        plan.lock(connection, ONE_LOCK, {"f": 1})  # not text: refused before the driver
    assert plan.evidence(ONE_LOCK) == frozenset()
    commit_refused(connection)
    connection.close()


def test_evidence_of_another_lock_object_does_not_satisfy_the_obligation(
    ev: World, one: Engine
) -> None:
    """plan: evidence is bound to the declared lock *object*; identical SQL on another object is missing evidence."""
    connection, plan = begin(one, ev)
    assert lock(connection, plan, "none", OTHER_LOCK) == ()
    plan.finalize(connection)
    with pytest.raises(AuthorizationPlanViolationError):
        run_absent(connection, plan)
    assert plan.violation is R.EVIDENCE
    connection.close()
    assert markers(ev.engine) == 0


def test_evidence_of_another_plan_or_transaction_cannot_satisfy_this_one(
    ev: World, one: Engine
) -> None:
    first, plan_a = begin(one, ev)
    lock(first, plan_a, "none")
    plan_a.finalize(first)
    run_absent(first, plan_a)
    first.commit()
    first.close()
    second, plan_b = begin(one, ev)
    plan_b.finalize(second)
    with pytest.raises(AuthorizationPlanViolationError):
        run_absent(second, plan_b)
    commit_refused(second)
    second.close()
    other = ev.engine.connect()
    _OPEN.append(other)
    other.begin()
    with pytest.raises(Exception, match="") as raised:
        plan_b.execute(other, INS_ABSENT, {"note": "x"})
    assert raised.value is not None
    other.close()
    assert markers(ev.engine) == 1


def test_evidence_cannot_be_added_after_finalize(ev: World, one: Engine) -> None:
    connection, plan = begin(one, ev)
    plan.finalize(connection)
    with pytest.raises(AuthorizationPlanStateError):
        lock(connection, plan, "none")
    assert plan.violation is R.LOCK_AFTER_FINALIZE
    connection.close()


def test_a_savepoint_rollback_after_empty_evidence_latches_and_a_released_one_does_not(
    ev: World, one: Engine
) -> None:
    """plan: a rolled-back savepoint can discard the lock behind evidence of absence, which owes an INSERT."""
    connection, plan = begin(one, ev)
    lock(connection, plan, "none")
    with connection.begin_nested() as savepoint:
        savepoint.rollback()
    assert plan.violation is R.SAVEPOINT_ROLLBACK
    commit_refused(connection)
    connection.close()

    connection, plan = begin(one, ev)
    lock(connection, plan, "none")
    with connection.begin_nested():
        connection.execute(text("SELECT 1")).all()
    assert plan.violation is None
    plan.finalize(connection)
    run_absent(connection, plan)
    connection.commit()
    connection.close()
    assert markers(ev.engine) == 1


def test_a_caught_refusal_stays_latched_and_the_pooled_connection_is_clean_afterwards(
    ev: World, one: Engine
) -> None:
    connection, plan = begin(one, ev)
    lock(connection, plan, "one")
    plan.finalize(connection)
    with contextlib.suppress(AuthorizationPlanViolationError):
        run_absent(connection, plan)
    assert plan.violated
    commit_refused(connection)
    connection.close()
    assert markers(ev.engine) == 0
    with one.begin() as plain:
        plain.execute(text(f"INSERT INTO {SCHEMA}.marker (note) VALUES ('plain')"))
    assert markers(ev.engine) == 1


# =====================================================================================================
# AnyConfirmed
# =====================================================================================================


def _keys(connection: Connection, plan: AuthorizationPlan, which: PreLock = ONE_LOCK) -> list[Any]:
    flag = "one" if which is ONE_LOCK else "two"
    return sorted(lock(connection, plan, flag, which))


def test_no_named_step_confirmed_forbids_the_insert_and_owes_nothing(
    ev: World, one: Engine
) -> None:
    """plan: nothing changed, so nothing is audited: the INSERT is refused before the driver and the plan commits
    without it. (Both named updates have empty evidence, so they are skippable.)"""
    connection, plan = begin(one, ev, ANY)
    assert lock(connection, plan, "none") == ()
    assert lock(connection, plan, "none", OTHER_LOCK) == ()
    plan.finalize(connection)
    mark = RECORDERS[one].mark()
    with pytest.raises(AuthorizationPlanViolationError):
        plan.execute(connection, INS_ANY, {"note": "n"})
    assert RECORDERS[one].inserts_since(mark) == 0 and plan.violation is R.EVIDENCE
    connection.close()

    connection, plan = begin(one, ev, ANY)
    lock(connection, plan, "none")
    lock(connection, plan, "none", OTHER_LOCK)
    plan.finalize(connection)
    connection.commit()
    connection.close()
    assert markers(ev.engine) == 0


def test_one_confirmed_named_step_owes_exactly_one_insert(ev: World, one: Engine) -> None:
    connection, plan = begin(one, ev, ANY)
    key = _keys(connection, plan)[0]
    lock(connection, plan, "none", OTHER_LOCK)
    plan.finalize(connection)
    run_update(connection, plan, UPD_A, key)
    plan.execute(connection, INS_ANY, {"note": "n"})
    connection.commit()
    connection.close()
    assert markers(ev.engine) == 1


def test_an_omitted_insert_after_a_confirmed_named_step_is_refused_at_commit(
    ev: World, one: Engine
) -> None:
    connection, plan = begin(one, ev, ANY)
    key = _keys(connection, plan)[0]
    lock(connection, plan, "none", OTHER_LOCK)
    plan.finalize(connection)
    run_update(connection, plan, UPD_A, key)
    commit_refused(connection)
    assert plan.violation is R.INCOMPLETE
    connection.close()
    assert markers(ev.engine) == 0


def test_the_second_named_step_alone_also_owes_the_insert(ev: World, one: Engine) -> None:
    """plan: `any`, not `all`: `UPD_C` confirming on its own (`UPD_A` has empty evidence) is enough."""
    connection, plan = begin(one, ev, ANY)
    lock(connection, plan, "none")
    other = _keys(connection, plan, OTHER_LOCK)[0]
    plan.finalize(connection)
    plan.execute(connection, UPD_C, {"g": other[0], "new_flag": "x"})
    plan.execute(connection, INS_ANY, {"note": "n"})
    connection.commit()
    connection.close()
    assert markers(ev.engine) == 1


def test_two_confirmed_named_steps_still_owe_one_insert_and_a_second_is_a_count_violation(
    ev: World, one: Engine
) -> None:
    connection, plan = begin(one, ev, ANY)
    key = _keys(connection, plan)[0]
    other = _keys(connection, plan, OTHER_LOCK)
    plan.finalize(connection)
    run_update(connection, plan, UPD_A, key)
    plan.execute(connection, UPD_C, {"g": other[0][0], "new_flag": "x"})
    plan.execute(connection, INS_ANY, {"note": "n"})
    mark = RECORDERS[one].mark()
    with pytest.raises(AuthorizationPlanViolationError):
        plan.execute(connection, INS_ANY, {"note": "again"})
    assert RECORDERS[one].inserts_since(mark) == 0 and plan.violation is R.COUNT
    commit_refused(connection)
    connection.close()
    assert markers(ev.engine) == 0


def test_two_confirmed_named_steps_and_one_insert_commit(ev: World, one: Engine) -> None:
    connection, plan = begin(one, ev, ANY)
    key = _keys(connection, plan)[0]
    other = _keys(connection, plan, OTHER_LOCK)
    plan.finalize(connection)
    run_update(connection, plan, UPD_A, key)
    plan.execute(connection, UPD_C, {"g": other[0][0], "new_flag": "x"})
    plan.execute(connection, INS_ANY, {"note": "n"})
    connection.commit()
    connection.close()
    assert markers(ev.engine) == 1


def test_an_attempted_but_unconfirmed_named_step_does_not_count(ev: World, one: Engine) -> None:
    """plan: `UPD_B` is attempted and matches no row (`ZERO_OR_ONE`): attempted, never confirmed. The audit
    INSERT is therefore forbidden and the plan commits without it."""
    connection, plan = begin(one, ev, ANY_UNCONFIRMED)
    key = _keys(connection, plan)[0]
    plan.finalize(connection)
    outcome = plan.execute(connection, UPD_B, {"g": key[0], "new_flag": "x"})
    assert outcome.keys == ()
    assert plan.attempts(UPD_B) == 1 and plan.confirmed(UPD_B) == ()
    mark = RECORDERS[one].mark()
    with pytest.raises(AuthorizationPlanViolationError):
        plan.execute(connection, INS_ANY_UNCONFIRMED, {"note": "n"})
    assert RECORDERS[one].inserts_since(mark) == 0 and plan.violation is R.EVIDENCE
    connection.close()

    connection, plan = begin(one, ev, ANY_UNCONFIRMED)
    key = _keys(connection, plan)[0]
    plan.finalize(connection)
    plan.execute(connection, UPD_B, {"g": key[0], "new_flag": "x"})
    connection.commit()
    connection.close()
    assert markers(ev.engine) == 0


def test_a_named_step_cannot_run_after_the_insert_that_reads_it(ev: World, one: Engine) -> None:
    """plan: the confirmed set is final when the cursor reaches the INSERT: a named step run afterwards is
    refused (`ORDER`)."""
    connection, plan = begin(one, ev, ANY)
    key = _keys(connection, plan)[0]
    other = _keys(connection, plan, OTHER_LOCK)
    plan.finalize(connection)
    run_update(connection, plan, UPD_A, key)
    plan.execute(connection, INS_ANY, {"note": "n"})
    with pytest.raises(AuthorizationPlanViolationError):
        plan.execute(connection, UPD_C, {"g": other[0][0], "new_flag": "late"})
    assert plan.violation is R.ORDER
    commit_refused(connection)
    connection.close()
    assert markers(ev.engine) == 0


def test_skipping_a_required_named_step_refuses_the_later_insert(ev: World, one: Engine) -> None:
    """plan: `UPD_A` is `EachLockedRow(complete)` over one row of evidence: it cannot be skipped to reach the
    INSERT (`ORDER`)."""
    connection, plan = begin(one, ev, ANY)
    _keys(connection, plan)
    lock(connection, plan, "none", OTHER_LOCK)
    plan.finalize(connection)
    with pytest.raises(AuthorizationPlanViolationError):
        plan.execute(connection, INS_ANY, {"note": "n"})
    assert plan.violation is R.ORDER
    commit_refused(connection)
    connection.close()


def test_a_savepoint_rollback_after_an_attempted_step_latches_without_any_evidence(
    ev: World, one: Engine
) -> None:
    """plan (T3): the declaration has no lock, no deferral and no outcome, so only the attempted step can tell.
    The savepoint is opened before `finalize` (a `SAVEPOINT` after it is itself refused as an undeclared
    statement), a step is attempted inside it and the rollback event latches `SAVEPOINT_ROLLBACK` *first*: the
    rollback statement that follows is then refused as well, but the first reason is the one recorded. Without
    the attempted-step condition the first reason would be `UNCONTROLLED`."""
    connection, plan = begin(one, ev, EXACT_ONLY)
    savepoint = connection.begin_nested()
    plan.finalize(connection)
    plan.execute(connection, INS_EXACT, {"note": "n"})
    with contextlib.suppress(AuthorizationPlanViolationError):
        savepoint.rollback()
    assert plan.violation is R.SAVEPOINT_ROLLBACK
    commit_refused(connection)
    connection.close()
    assert markers(ev.engine) == 0


def test_a_savepoint_rollback_before_any_step_or_evidence_does_not_latch(
    ev: World, one: Engine
) -> None:
    """plan (T3 is narrow): with nothing attempted, nothing locked, deferred or bound, there is nothing to lose."""
    connection, plan = begin(one, ev, EXACT_ONLY)
    with connection.begin_nested() as savepoint:
        savepoint.rollback()
    assert plan.violation is None
    plan.finalize(connection)
    plan.execute(connection, INS_EXACT, {"note": "n"})
    connection.commit()
    connection.close()
    assert markers(ev.engine) == 1


# =====================================================================================================
# declaration validation
# =====================================================================================================


@pytest.mark.parametrize("bad", (None, "lock", 1))
def test_per_absence_needs_a_prelock(bad: Any) -> None:
    """declaration"""
    with pytest.raises(DeclarationError):
        PerAbsence(bad)


def test_per_absence_is_refused_on_an_update() -> None:
    """declaration: an UPDATE already has `EachLockedRow`."""
    with pytest.raises(DeclarationError, match="INSERT only"):
        WriteStep(
            name="bad_update",
            statement=update(gate)
            .where(gate.c.gate_id == bindparam("g"))
            .values(flag=bindparam("new_flag"))
            .returning(gate.c.gate_id),
            cardinality=PerAbsence(ONE_LOCK),
            target=(KeyBind(gate.c.gate_id, "g"),),
            target_lock=ONE_LOCK,
            value_binds=frozenset({"new_flag"}),
        )


def test_the_absence_lock_must_be_one_of_the_declarations_locks() -> None:
    """declaration"""
    with pytest.raises(DeclarationError, match="not in locks"):
        PreWriteDeclaration(locks=(OTHER_LOCK,), steps=(INS_ABSENT,))


@pytest.mark.parametrize("bad", ((), None, "steps", [UPD_A], (UPD_A, UPD_A), (1,)))
def test_any_confirmed_needs_a_non_empty_tuple_of_distinct_steps(bad: Any) -> None:
    """declaration: empty, non-tuple, non-step and duplicate arguments are refused."""
    with pytest.raises(DeclarationError):
        AnyConfirmed(bad)


def test_any_confirmed_is_refused_on_an_update() -> None:
    """declaration"""
    with pytest.raises(DeclarationError, match="INSERT only"):
        WriteStep(
            name="bad_update_any",
            statement=update(gate)
            .where(gate.c.gate_id == bindparam("g"))
            .values(flag=bindparam("new_flag"))
            .returning(gate.c.gate_id),
            cardinality=AnyConfirmed((UPD_A,)),
            target=(KeyBind(gate.c.gate_id, "g"),),
            target_lock=ONE_LOCK,
            value_binds=frozenset({"new_flag"}),
        )


def test_any_confirmed_must_name_steps_strictly_earlier_in_the_same_declaration() -> None:
    """declaration: a step missing from the declaration, a later step and the step itself are all refused."""
    with pytest.raises(DeclarationError, match="not earlier"):
        PreWriteDeclaration(
            locks=(ONE_LOCK,), steps=(INS_ANY,)
        )  # names steps that are not declared
    with pytest.raises(DeclarationError, match="not earlier"):
        PreWriteDeclaration(
            locks=(ONE_LOCK,), steps=(INS_ANY, UPD_A, UPD_C)
        )  # named steps come later


def test_any_confirmed_may_not_name_another_any_confirmed_step() -> None:
    """declaration: no chains."""
    chained = WriteStep(
        name="ins_chained",
        statement=insert(marker).values(note=bindparam("note")).returning(marker.c.marker_id),
        cardinality=AnyConfirmed((INS_ANY,)),
        value_binds=frozenset({"note"}),
    )
    with pytest.raises(DeclarationError, match="AnyConfirmed"):
        PreWriteDeclaration(locks=(ONE_LOCK, OTHER_LOCK), steps=(UPD_A, UPD_C, INS_ANY, chained))


def test_any_confirmed_may_not_name_the_receipt_step() -> None:
    """declaration: the receipt is not a business change."""
    named = WriteStep(
        name="ins_names_receipt",
        statement=insert(marker).values(note=bindparam("note")).returning(marker.c.marker_id),
        cardinality=AnyConfirmed((RECEIPT_STEP,)),
        value_binds=frozenset({"note"}),
    )
    with pytest.raises(DeclarationError):
        PreWriteDeclaration(locks=(ONE_LOCK,), steps=(RECEIPT_STEP, named))


def test_the_other_cardinalities_are_unchanged_beside_the_new_ones() -> None:
    """declaration: `Exactly`, `Between`, `EachLockedRow` and `PerEvidence` keep their meaning in a mixed declaration."""
    per_evidence = WriteStep(
        name="ins_per_evidence",
        statement=insert(marker).values(note=bindparam("note")).returning(marker.c.marker_id),
        cardinality=PerEvidence(ONE_LOCK),
        value_binds=frozenset({"note"}),
    )
    mixed = PreWriteDeclaration(
        locks=(ONE_LOCK,), steps=(UPD_A, UPD_B, per_evidence, INS_ABSENT, INS_EXACT)
    )
    assert [type(s.cardinality) for s in mixed.steps] == [
        EachLockedRow,
        Between,
        PerEvidence,
        PerAbsence,
        Exactly,
    ]
    assert uuid.UUID(int=0)  # keep `uuid` used on every path
