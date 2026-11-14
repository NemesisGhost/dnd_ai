# ruff: noqa: F811 - the imported fixture `w` is used by name
"""R01 S5-D amendment: `PerEvidence`, an INSERT cardinality derived from the evidence of one declared lock
(plan section 6.25.5).

One returned evidence row requires exactly one INSERT; a lock that executed and returned zero rows permits
none; a lock that never executed successfully is not empty evidence. These tests drive `AuthorizationPlan`
directly, against scratch tables, so each rule is shown on its own, apart from any route. Evidence classes:

- **plan**: the S1/S5-C API on a real connection and transaction;
- **declaration**: the validation of a declaration at construction (no database).

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

from dnd_ai.domain.authorization import (
    AuthorizationPlan,
    AuthorizationPlanNotFinalizedError,
    AuthorizationPlanStateError,
    AuthorizationPlanViolationError,
    PlanMode,
    ViolationReason,
)
from dnd_ai.domain.authorization_steps import (
    Between,
    DeclarationError,
    EachLockedRow,
    Exactly,
    KeyBind,
    PerEvidence,
    PreLock,
    PreWriteDeclaration,
    WriteStep,
)
from tests.database.test_r01_s3_authoring_routes import World, w  # noqa: F401 - fixture by name

pytestmark = pytest.mark.database

R = ViolationReason
SCHEMA = "r01_s5d_ev"

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
INS = WriteStep(
    name="ins_marker",
    statement=insert(marker).values(note=bindparam("note")).returning(marker.c.marker_id),
    cardinality=PerEvidence(ONE_LOCK),
    value_binds=frozenset({"note"}),
)
DECLARATION = PreWriteDeclaration(locks=(ONE_LOCK, OTHER_LOCK), steps=(INS,))
INS_EXACT = WriteStep(
    name="ins_exact",
    statement=insert(marker).values(note=bindparam("note")).returning(marker.c.marker_id),
    cardinality=Exactly(1),
    value_binds=frozenset({"note"}),
)
INS_BETWEEN = WriteStep(
    name="ins_between",
    statement=insert(marker).values(note=bindparam("note")).returning(marker.c.marker_id),
    cardinality=Between(0, 1),
    value_binds=frozenset({"note"}),
)
UPD_BY_EVIDENCE = WriteStep(
    name="upd_gate",
    statement=update(gate)
    .where(gate.c.gate_id == bindparam("g"))
    .values(flag=bindparam("new_flag"))
    .returning(gate.c.gate_id),
    cardinality=EachLockedRow(complete=True),
    target=(KeyBind(gate.c.gate_id, "g"),),
    target_lock=ONE_LOCK,
    value_binds=frozenset({"new_flag"}),
)
MIXED = PreWriteDeclaration(
    locks=(ONE_LOCK, OTHER_LOCK), steps=(INS, INS_EXACT, INS_BETWEEN, UPD_BY_EVIDENCE)
)

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
    engine: Engine, w: World, declaration: PreWriteDeclaration = DECLARATION
) -> tuple[Connection, AuthorizationPlan]:
    """A pre-write plan on a fresh transaction. A recorder (`Statements`) must be entered *before* this call:
    listener registrations are fixed from plan creation, and a later one is refused (`LISTENER_TOPOLOGY`)."""
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


class Statements:
    """Every statement the engine hands the driver, in order. It is registered when the pooled engine is
    created (the `one` fixture), before any plan exists: listener registrations are fixed from plan
    creation, and a later one would itself be refused (`LISTENER_TOPOLOGY`)."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.seen: list[str] = []
        event.listen(engine, "before_cursor_execute", self._hook)

    def _hook(self, _c: Any, _cursor: Any, statement: Any, *_: Any) -> None:
        self.seen.append(" ".join(str(statement).split()))

    def mark(self) -> int:
        return len(self.seen)

    def inserts_since(self, mark: int) -> int:
        return sum(1 for s in self.seen[mark:] if s.startswith(f"INSERT INTO {SCHEMA}.marker"))


RECORDERS: dict[Engine, Statements] = {}


def commit_refused(connection: Connection) -> None:
    with pytest.raises(AuthorizationPlanNotFinalizedError):
        connection.commit()


def lock(
    connection: Connection, plan: AuthorizationPlan, flag: str, which: PreLock = ONE_LOCK
) -> Any:
    return plan.lock(connection, which, {"f": flag})


def run_insert(connection: Connection, plan: AuthorizationPlan, note: str = "n") -> Any:
    return plan.execute(connection, INS, {"note": note})


# --- one row of evidence: exactly one INSERT -------------------------------------------------------------------------


def test_one_evidence_row_and_one_insert_commits(ev: World, one: Engine) -> None:
    """plan: the positive case. The lock returned one row, the INSERT ran once, COMMIT is accepted."""
    connection, plan = begin(one, ev)
    assert len(lock(connection, plan, "one")) == 1
    plan.finalize(connection)
    run_insert(connection, plan)
    connection.commit()
    assert markers(ev.engine) == 1


def test_one_evidence_row_and_an_omitted_insert_is_refused_at_commit_and_rolls_back(
    ev: World, one: Engine
) -> None:
    """plan: the completeness obligation. Positive evidence with no INSERT cannot commit."""
    connection, plan = begin(one, ev)
    lock(connection, plan, "one")
    plan.finalize(connection)
    commit_refused(connection)
    assert plan.violation is R.INCOMPLETE
    connection.close()
    assert markers(ev.engine) == 0


def test_a_second_insert_on_one_evidence_row_is_refused_before_the_driver_and_latches(
    ev: World, one: Engine
) -> None:
    """plan: extra INSERTs refuse (`COUNT`); the refusal latches even when the caller catches it, so the
    otherwise complete request cannot commit."""
    connection, plan = begin(one, ev)
    lock(connection, plan, "one")
    plan.finalize(connection)
    run_insert(connection, plan)
    mark = RECORDERS[one].mark()
    with pytest.raises(AuthorizationPlanViolationError):
        run_insert(connection, plan, "again")
    assert RECORDERS[one].inserts_since(mark) == 0 and plan.violation is R.COUNT
    commit_refused(connection)
    connection.close()
    assert markers(ev.engine) == 0


# --- zero rows of (successfully executed) evidence: no INSERT --------------------------------------------------------


def test_empty_evidence_and_no_insert_commits(ev: World, one: Engine) -> None:
    """plan: a lock that ran and returned nothing is *evidence of absence*: nothing is owed."""
    connection, plan = begin(one, ev)
    assert lock(connection, plan, "none") == ()
    plan.finalize(connection)
    connection.commit()
    assert markers(ev.engine) == 0


def test_an_insert_on_empty_evidence_is_refused_before_the_driver_and_latches(
    ev: World, one: Engine
) -> None:
    connection, plan = begin(one, ev)
    lock(connection, plan, "none")
    plan.finalize(connection)
    mark = RECORDERS[one].mark()
    with pytest.raises(AuthorizationPlanViolationError):
        run_insert(connection, plan)
    assert RECORDERS[one].inserts_since(mark) == 0, "the INSERT must never reach the driver"
    assert plan.violation is R.EVIDENCE
    commit_refused(connection)  # caught or not, the latch refuses the commit
    connection.close()
    assert markers(ev.engine) == 0
    assert plan.attempts(INS) == 0


# --- more than one row: unsupported, never silently accepted ---------------------------------------------------------


def test_two_evidence_rows_are_unsupported_for_both_the_insert_and_its_omission(
    ev: World, one: Engine
) -> None:
    """plan: the rule is zero-or-one. Two rows refuse the INSERT (`EVIDENCE`) and, without it, the commit."""
    connection, plan = begin(one, ev)
    assert len(lock(connection, plan, "two")) == 2
    plan.finalize(connection)
    mark = RECORDERS[one].mark()
    with pytest.raises(AuthorizationPlanViolationError):
        run_insert(connection, plan)
    assert RECORDERS[one].inserts_since(mark) == 0 and plan.violation is R.EVIDENCE
    commit_refused(connection)
    connection.close()

    connection, plan = begin(one, ev)
    lock(connection, plan, "two")
    plan.finalize(connection)  # nothing attempted: incomplete, not accepted as "zero"
    commit_refused(connection)
    connection.close()
    assert markers(ev.engine) == 0


def test_a_second_call_of_the_lock_that_adds_a_row_makes_the_evidence_unsupported(
    ev: World, one: Engine
) -> None:
    """plan: evidence is the union over calls; a later call that adds a second key is not a single row."""
    connection, plan = begin(one, ev)
    lock(connection, plan, "one")
    lock(connection, plan, "two")
    plan.finalize(connection)
    with pytest.raises(AuthorizationPlanViolationError):
        run_insert(connection, plan)
    connection.close()
    assert markers(ev.engine) == 0


# --- evidence that never existed, failed, or belongs elsewhere ------------------------------------------------------


def test_a_lock_that_never_ran_is_not_empty_evidence(ev: World, one: Engine) -> None:
    """plan: no lock call at all. The INSERT is refused (`EVIDENCE`) and, with no INSERT, the commit is too:
    absent evidence is neither "none" (which would permit omission) nor "one"."""
    connection, plan = begin(one, ev)
    plan.finalize(connection)
    with pytest.raises(AuthorizationPlanViolationError):
        run_insert(connection, plan)
    assert plan.violation is R.EVIDENCE
    connection.close()

    connection, plan = begin(one, ev)
    plan.finalize(connection)
    commit_refused(connection)
    assert plan.violation is R.INCOMPLETE
    connection.close()
    assert markers(ev.engine) == 0


def test_a_lock_that_failed_leaves_no_evidence_and_latches(ev: World, one: Engine) -> None:
    """plan: a lock call refused for its parameters records nothing; it cannot count as empty evidence."""
    connection, plan = begin(one, ev)
    with pytest.raises(AuthorizationPlanViolationError):
        plan.lock(connection, ONE_LOCK, {"f": 1})  # not text: refused before the driver
    assert plan.evidence(ONE_LOCK) == frozenset()
    assert plan.violation is not None
    commit_refused(connection)
    connection.close()


def test_evidence_of_another_lock_object_does_not_satisfy_the_obligation(
    ev: World, one: Engine
) -> None:
    """plan: evidence is bound to the declared lock *object*. A second lock with identical SQL is another
    lock: its row does not permit this step's INSERT."""
    connection, plan = begin(one, ev)
    assert len(lock(connection, plan, "one", OTHER_LOCK)) == 1
    plan.finalize(connection)
    with pytest.raises(AuthorizationPlanViolationError):
        run_insert(connection, plan)
    assert plan.violation is R.EVIDENCE
    connection.close()
    assert markers(ev.engine) == 0


def test_evidence_of_another_plan_or_transaction_cannot_satisfy_this_one(
    ev: World, one: Engine
) -> None:
    """plan: plan A holds one row; plan B (another transaction on the same pooled connection, no lock call)
    cannot use it. A plan also refuses a connection that is not its own."""
    first, plan_a = begin(one, ev)
    lock(first, plan_a, "one")
    plan_a.finalize(first)
    run_insert(first, plan_a)
    first.commit()
    first.close()
    second, plan_b = begin(one, ev)
    plan_b.finalize(second)
    with pytest.raises(AuthorizationPlanViolationError):
        run_insert(second, plan_b)
    commit_refused(second)
    second.close()
    other = ev.engine.connect()
    _OPEN.append(other)
    other.begin()
    with pytest.raises(Exception, match="") as raised:
        plan_b.execute(other, INS, {"note": "x"})
    assert raised.value is not None
    other.close()
    assert markers(ev.engine) == 1


def test_evidence_cannot_be_added_after_finalize(ev: World, one: Engine) -> None:
    """plan: evidence is fixed before finalization (`LOCK_AFTER_FINALIZE`)."""
    connection, plan = begin(one, ev)
    plan.finalize(connection)
    with pytest.raises(AuthorizationPlanStateError):
        lock(connection, plan, "one")
    assert plan.violation is R.LOCK_AFTER_FINALIZE
    connection.close()


# --- savepoints, caught refusals, clean reuse -------------------------------------------------------------------------


@pytest.mark.parametrize("flag", ("one", "none"))
def test_a_savepoint_rollback_after_evidence_latches_even_for_empty_evidence(
    flag: str, ev: World, one: Engine
) -> None:
    """plan: a rolled-back savepoint can discard the lock behind evidence; evidence that a lock returned
    nothing is equally unsafe to keep (it forbids the INSERT), so it latches too."""
    connection, plan = begin(one, ev)
    lock(connection, plan, flag)
    with connection.begin_nested() as savepoint:
        savepoint.rollback()
    assert plan.violation is R.SAVEPOINT_ROLLBACK
    commit_refused(connection)
    connection.close()


def test_a_released_savepoint_is_not_a_violation(ev: World, one: Engine) -> None:
    connection, plan = begin(one, ev)
    lock(connection, plan, "one")
    with connection.begin_nested():
        connection.execute(text("SELECT 1")).all()
    assert plan.violation is None
    plan.finalize(connection)
    run_insert(connection, plan)
    connection.commit()
    connection.close()
    assert markers(ev.engine) == 1


def test_a_caught_refusal_stays_latched_and_the_pooled_connection_is_clean_for_the_next_transaction(
    ev: World, one: Engine
) -> None:
    """plan: whatever the caller catches, the plan stays violated and the commit is refused; the one pooled
    connection then serves a plain transaction that commits only its own work."""
    connection, plan = begin(one, ev)
    lock(connection, plan, "none")
    plan.finalize(connection)
    with contextlib.suppress(AuthorizationPlanViolationError):
        run_insert(connection, plan)
    assert plan.violated
    commit_refused(connection)
    connection.close()
    assert markers(ev.engine) == 0
    with one.begin() as plain:
        plain.execute(text(f"INSERT INTO {SCHEMA}.marker (note) VALUES ('plain')"))
    assert markers(ev.engine) == 1


# --- declaration validation -------------------------------------------------------------------------------------------


@pytest.mark.parametrize("bad", (None, "lock", 1))
def test_per_evidence_needs_a_prelock(bad: Any) -> None:
    """declaration"""
    with pytest.raises(DeclarationError):
        PerEvidence(bad)


def test_per_evidence_is_refused_on_an_update() -> None:
    """declaration: an UPDATE already has `EachLockedRow`."""
    with pytest.raises(DeclarationError, match="INSERT only"):
        WriteStep(
            name="bad_update",
            statement=update(gate)
            .where(gate.c.gate_id == bindparam("g"))
            .values(flag=bindparam("new_flag"))
            .returning(gate.c.gate_id),
            cardinality=PerEvidence(ONE_LOCK),
            target=(KeyBind(gate.c.gate_id, "g"),),
            target_lock=ONE_LOCK,
            value_binds=frozenset({"new_flag"}),
        )


def test_the_evidence_lock_must_be_one_of_the_declarations_locks() -> None:
    """declaration"""
    with pytest.raises(DeclarationError, match="not in locks"):
        PreWriteDeclaration(locks=(OTHER_LOCK,), steps=(INS,))


def test_the_other_cardinalities_are_unchanged_in_a_mixed_declaration() -> None:
    """declaration: `Exactly`, `Between` and `EachLockedRow` keep their meaning beside `PerEvidence`."""
    assert [type(s.cardinality) for s in MIXED.steps] == [
        PerEvidence,
        Exactly,
        Between,
        EachLockedRow,
    ]


def test_exact_and_between_steps_still_enforce_their_bounds_beside_per_evidence(
    ev: World, one: Engine
) -> None:
    """plan: existing lower bounds are not affected by the new rule."""
    connection, plan = begin(one, ev, MIXED)
    lock(connection, plan, "none")
    plan.finalize(connection)
    commit_refused(connection)  # `Exactly(1)` unmet, though the PerEvidence step is skippable
    assert plan.violation is R.INCOMPLETE
    connection.close()
    connection, plan = begin(one, ev, MIXED)
    lock(connection, plan, "none")
    plan.finalize(connection)
    plan.execute(connection, INS_EXACT, {"note": "e"})
    connection.commit()
    connection.close()
    assert markers(ev.engine) == 1
