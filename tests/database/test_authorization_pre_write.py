# ruff: noqa: F811, B007, B023, SIM117, S608 - nested `with` keeps each expected failure separate; synthetic DDL/DML
"""R01 S1-C: pre-write admission by statement identity, the controlled `plan.execute` / `plan.lock`
API, frozen parameter snapshots, row accounting, session and listener assumptions (plan 6.9-6.11).

Every refusal test asserts its specific `plan.violation`, E-driver +0 and E-server +0 (unless stated),
after a positive control on a seeded would-change target (tests/r01_pre_write_evidence.py). Each test
uses its own schema, sequences and one-connection engine. Consolidated PW mapping:

- PW-1/7/8: `test_undeclared_statements_are_refused_after_finalize`, `test_a_distinct_object_...`
- PW-2: `test_the_snapshot_is_immutable_...`; PW-22-24: `test_a_listener_mutating_...`
- PW-3/4: composite keys and groups; PW-5/6: parameters and options; PW-10/11: order, counts, completion
- PW-12/13/15: failures and caught refusals; PW-14: N-1; PW-16/17: lock evidence
- PW-18: valid operations; PW-25: listener order and topology; PW-26: row accounting; PW-28: locks
- session assumptions, duplicate-target policy, result cleanup
"""

import datetime
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import (
    Connection,
    Engine,
    Update,
    bindparam,
    event,
    func,
    insert,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.engine.result import Result as _Result
from sqlalchemy.exc import ArgumentError, DBAPIError

import dnd_ai.api.deps as deps
from dnd_ai.api.errors import install_error_handlers
from dnd_ai.commands.authorized_transaction import authorized_transaction
from dnd_ai.domain import authorization
from dnd_ai.domain.authorization import (
    AuthorizationPlan,
    AuthorizationPlanBindingError,
    AuthorizationPlanNotFinalizedError,
    AuthorizationPlanStateError,
    AuthorizationPlanViolationError,
    PlanMode,
    StepOutcome,
    ViolationReason,
    install_authorization_guard,
)
from dnd_ai.domain.authorization_steps import (
    Between,
    EachLockedRow,
    Exactly,
    FkBinding,
    KeyBind,
    PreLock,
    PreWriteDeclaration,
    RowExpectation,
    UniqueWait,
    WriteStep,
)
from tests.r01_pre_write_evidence import Synthetic, driver_calls, new_id, synthetic  # noqa: F401

pytestmark = pytest.mark.database

R = ViolationReason


# --- declarations -------------------------------------------------------------------------------


class Kit:
    """The declarations of one test's schema: pre-locks, and factories for steps."""

    def __init__(self, s: Synthetic) -> None:
        self.s = s
        t = s.tables
        self.t = t
        tgt, cpk, parent, ref = t["target"], t["cpk"], t["parent"], t["ref"]
        self.lock_parent = PreLock(
            "parent_share",
            select(parent.c.parent_id)
            .where(parent.c.parent_id == bindparam("p"))
            .with_for_update(read=True),
        )
        self.lock_targets = PreLock(
            "targets_of_parent",
            select(tgt.c.target_id)
            .where(tgt.c.parent_id == bindparam("p"))
            .order_by(tgt.c.target_id)
            .with_for_update(key_share=True),
        )
        self.lock_one = PreLock(
            "target_one",
            select(tgt.c.target_id)
            .where(tgt.c.target_id == bindparam("k"))
            .with_for_update(key_share=True),
        )
        self.lock_share = PreLock(
            "target_share",
            select(tgt.c.target_id)
            .where(tgt.c.target_id == bindparam("k"))
            .with_for_update(read=True),
        )
        self.lock_cpk = PreLock(
            "cpk_of_a",
            select(cpk.c.a, cpk.c.b).where(cpk.c.a == bindparam("a")).with_for_update(),
        )
        self.lock_ref = PreLock(
            "ref_one",
            select(ref.c.r_id, ref.c.scope, ref.c.other)
            .where(ref.c.r_id == bindparam("r"))
            .with_for_update(read=True),
        )
        self.locks = (
            self.lock_parent,
            self.lock_targets,
            self.lock_one,
            self.lock_share,
            self.lock_cpk,
            self.lock_ref,
        )

    def upd(
        self,
        cardinality: Any = None,
        rows: RowExpectation = RowExpectation.ONE,
        *,
        narrow: bool = False,
        lock: PreLock | None = None,
        name: str = "upd",
    ) -> WriteStep:
        tgt = self.t["target"]
        where = [tgt.c.target_id == bindparam("k")]
        if narrow:
            where.append(tgt.c.active.is_(True))
        return WriteStep(
            name=name,
            statement=update(tgt)
            .where(*where)
            .values(v=bindparam("nv"), stamp=func.pg_catalog.now())
            .returning(tgt.c.target_id),
            cardinality=cardinality if cardinality is not None else EachLockedRow(complete=True),
            target=(KeyBind(tgt.c.target_id, "k"),),
            target_lock=lock or self.lock_targets,
            value_binds=frozenset({"nv"}),
            rows=rows,
        )

    def rich(self, cardinality: Any = None) -> WriteStep:
        tgt = self.t["target"]
        return WriteStep(
            name="rich",
            statement=update(tgt)
            .where(tgt.c.target_id == bindparam("k"))
            .values(
                note=bindparam("note"),
                tags=bindparam("tags"),
                stamp=bindparam("ts"),
                rng=bindparam("rng"),
                meta=bindparam("meta"),
                active=bindparam("active"),
            )
            .returning(tgt.c.target_id),
            cardinality=cardinality or Exactly(1),
            target=(KeyBind(tgt.c.target_id, "k"),),
            target_lock=self.lock_one,
            value_binds=frozenset({"note", "tags", "ts", "rng", "meta", "active"}),
        )

    def ins_log(self, cardinality: Any = None, *, lock: PreLock | None = None) -> WriteStep:
        log = self.t["log"]
        constraint = next(iter(log.foreign_key_constraints))
        return WriteStep(
            name="ins_log",
            statement=insert(log)
            .values(parent_id=bindparam("parent_id"), msg=bindparam("msg"))
            .returning(log.c.log_id),
            cardinality=cardinality or Exactly(1),
            fks=(
                FkBinding(
                    constraint, (KeyBind(log.c.parent_id, "parent_id"),), lock or self.lock_parent
                ),
            ),
            value_binds=frozenset({"msg"}),
        )

    def ins_audit(self, cardinality: Any = None) -> WriteStep:
        audit = self.t["audit"]
        return WriteStep(
            name="ins_audit",
            statement=insert(audit)
            .values(parent_id=bindparam("pid"), note=bindparam("note"))
            .returning(audit.c.audit_id),
            cardinality=cardinality or Exactly(1),
            value_binds=frozenset({"pid", "note"}),
        )

    def ins_skip(self) -> WriteStep:
        skip = self.t["skip"]
        return WriteStep(
            name="ins_skip",
            statement=insert(skip).values(msg=bindparam("msg")).returning(skip.c.skip_id),
            cardinality=Exactly(1),
            value_binds=frozenset({"msg"}),
        )

    def ins_label(self) -> WriteStep:
        tgt = self.t["target"]
        constraint = next(iter(tgt.foreign_key_constraints))
        return WriteStep(
            name="ins_label",
            statement=insert(tgt)
            .values(
                parent_id=bindparam("parent_id"),
                v=bindparam("v"),
                active=bindparam("active"),
                label=bindparam("label"),
            )
            .returning(tgt.c.target_id),
            cardinality=Exactly(1),
            fks=(
                FkBinding(constraint, (KeyBind(tgt.c.parent_id, "parent_id"),), self.lock_parent),
            ),
            value_binds=frozenset({"v", "active", "label"}),
            unique_waits=frozenset({UniqueWait(f"{self.s.schema}.ux_target_label", "S5")}),
        )

    def upd_cpk(self, cardinality: Any = None) -> WriteStep:
        cpk = self.t["cpk"]
        return WriteStep(
            name="upd_cpk",
            statement=update(cpk)
            .where(cpk.c.a == bindparam("ka"), cpk.c.b == bindparam("kb"))
            .values(v=bindparam("nv"))
            .returning(cpk.c.a, cpk.c.b),
            cardinality=cardinality or EachLockedRow(complete=True),
            target=(KeyBind(cpk.c.a, "ka"), KeyBind(cpk.c.b, "kb")),
            target_lock=self.lock_cpk,
            value_binds=frozenset({"nv"}),
        )

    def decl(self, *steps: WriteStep) -> PreWriteDeclaration:
        return PreWriteDeclaration(locks=self.locks, steps=tuple(steps))


@dataclass
class Seed:
    p1: uuid.UUID
    p2: uuid.UUID
    t1: uuid.UUID
    t2: uuid.UUID
    t3: uuid.UUID  # another parent's target: seeded, never locked
    cpk_a: uuid.UUID
    cpk_b1: uuid.UUID
    cpk_b2: uuid.UUID


def seed(s: Synthetic, *, t1_active: bool = True, t2_active: bool = True) -> Seed:
    d = Seed(*(new_id() for _ in range(8)))
    s.run(f"INSERT INTO {s.schema}.parent VALUES (:a, 'one'), (:b, 'two')", a=d.p1, b=d.p2)
    s.run(
        f"INSERT INTO {s.schema}.target (target_id, parent_id, v, active) VALUES "
        "(:t1, :p1, 1, :a1), (:t2, :p1, 2, :a2), (:t3, :p2, 3, true)",
        t1=d.t1,
        t2=d.t2,
        t3=d.t3,
        p1=d.p1,
        p2=d.p2,
        a1=t1_active,
        a2=t2_active,
    )
    s.run(
        f"INSERT INTO {s.schema}.cpk VALUES (:a, :b1, 10), (:a, :b2, 20)",
        a=d.cpk_a,
        b1=d.cpk_b1,
        b2=d.cpk_b2,
    )
    return d


def open_plan(
    s: Synthetic, declaration: PreWriteDeclaration
) -> tuple[Connection, AuthorizationPlan]:
    install_authorization_guard(s.engine)
    connection = s.engine.connect()
    connection.begin()
    plan = AuthorizationPlan.begin(
        connection,
        actor_user_id=new_id(),
        campaign_id=new_id(),
        mode=PlanMode.PRE_WRITE,
        pre_write=declaration,
    )
    return connection, plan


def pid(connection: Connection) -> int:
    return int(connection.execute(text("SELECT pg_backend_pid()")).scalar_one())


def lock_family(connection: Connection, plan: AuthorizationPlan, kit: Kit, d: Seed) -> None:
    plan.lock(connection, kit.lock_parent, {"p": d.p1})
    plan.lock(connection, kit.lock_targets, {"p": d.p1})


def committed(s: Synthetic, sql: str, **params: Any) -> list[tuple[Any, ...]]:
    return s.rows(sql, **params)


class Observe:
    """E-driver and E-server deltas around an attempt."""

    def __init__(self, s: Synthetic, connection: Connection, *tables: str) -> None:
        self.s, self.connection, self.tables = s, connection, tables or ("target",)

    def __enter__(self) -> "Observe":
        self.d0 = driver_calls(self.connection)
        self.c0 = {t: self.s.server_count(t) for t in self.tables}
        return self

    def __exit__(self, *_: object) -> None:
        pass

    def driver(self) -> int:
        return driver_calls(self.connection) - self.d0

    def server(self, table: str) -> int:
        return self.s.server_count(table) - self.c0[table]


def refused(
    s: Synthetic,
    connection: Connection,
    plan: AuthorizationPlan,
    reason: ViolationReason,
    attempt: Callable[[], object],
    *tables: str,
    driver: int = 0,
    exc: type[BaseException] = AuthorizationPlanViolationError,
) -> None:
    with Observe(s, connection, *tables) as o:
        with pytest.raises(exc):
            attempt()
    assert plan.violation is reason
    assert o.driver() == driver, "E-driver"
    for table in o.tables:
        assert o.server(table) == (0 if not driver else o.server(table)), "E-server"


def control_update(s: Synthetic, stmt: Update, params: dict[str, Any], *, rows: int = 1) -> None:
    """The positive control: the same object and parameters on a plain connection change the row
    (E-driver +1, E-server +1, expected rowcount), then roll back."""
    table = stmt.table.name
    before = s.server_count(table)
    with s.plain.connect() as c:
        d0 = driver_calls(c)
        result = c.execute(stmt, params)
        assert result.rowcount == rows
        assert driver_calls(c) == d0 + 1
        c.rollback()
    assert s.server_count(table) == before + 1


def commit(connection: Connection) -> None:
    deps.finish_connection_transaction(connection, commit=True)


# --- valid operations (PW-16/18), pooled reuse -------------------------------------------------------


def test_a_valid_operation_commits_and_the_pool_stays_clean(synthetic: Synthetic) -> None:
    s = synthetic
    kit = Kit(s)
    d = seed(s)
    decl = kit.decl(kit.upd(), kit.ins_log(), kit.ins_audit())
    pids: list[int] = []
    before = {t: s.server_count(t) for t in ("target", "log", "audit")}
    connection, plan = open_plan(s, decl)
    pids.append(pid(connection))
    keys = plan.lock(connection, kit.lock_targets, {"p": d.p1})
    assert sorted(keys) == sorted([(d.t1,), (d.t2,)])
    plan.lock(connection, kit.lock_parent, {"p": d.p1})
    assert plan.evidence(kit.lock_targets) == frozenset({(d.t1,), (d.t2,)})
    plan.finalize(connection)
    for i, key in enumerate(sorted(keys)):
        outcome = plan.execute(connection, decl.steps[0], {"k": key[0], "nv": 100 + i})
        assert isinstance(outcome, StepOutcome) and outcome.keys == (key,)
    log = plan.execute(connection, decl.steps[1], {"parent_id": d.p1, "msg": "hello"})
    audit = plan.execute(connection, decl.steps[2], {"pid": d.p1, "note": "n"})
    assert type(log.keys[0][0]) is uuid.UUID and audit.keys[0][0] > 0
    assert plan.attempts(decl.steps[0]) == 2 and len(plan.confirmed(decl.steps[0])) == 2
    commit(connection)
    assert sorted(
        r[0] for r in committed(s, f"SELECT v FROM {s.schema}.target WHERE parent_id=:p", p=d.p1)
    ) == [
        100,
        101,
    ]
    assert committed(s, f"SELECT count(*) FROM {s.schema}.log")[0][0] == 1
    assert committed(s, f"SELECT note FROM {s.schema}.audit")[0][0] == "n"
    assert s.server_count("target") - before["target"] == 2  # exactly the two declared updates
    assert s.server_count("log") - before["log"] == 1
    assert s.server_count("audit") - before["audit"] == 1
    # the decoy was never locked or written
    assert committed(s, f"SELECT v FROM {s.schema}.target WHERE target_id=:t", t=d.t3)[0][0] == 3

    # the same pooled backend: a refused request, then a valid one; never idle in transaction
    connection, plan = open_plan(s, decl)
    pids.append(pid(connection))
    plan.finalize(connection)
    with pytest.raises(AuthorizationPlanViolationError):
        connection.execute(text("SELECT 1"))
    with pytest.raises(AuthorizationPlanNotFinalizedError):
        connection.commit()
    deps._discard(connection)
    assert (
        s.rows(
            "SELECT count(*) FROM pg_stat_activity WHERE state LIKE 'idle in transaction%'"
            " AND datname = current_database()"
        )[0][0]
        == 0
    )
    only_upd = kit.decl(kit.upd())
    connection, plan = open_plan(s, only_upd)
    pids.append(pid(connection))
    lock_family(connection, plan, kit, d)
    plan.finalize(connection)
    for key in sorted(plan.evidence(kit.lock_targets)):
        plan.execute(connection, only_upd.steps[0], {"k": key[0], "nv": 7})
    commit(connection)
    assert len(set(pids)) == 1, "the pooled backend was not reused"


def test_composite_primary_keys_and_grouped_foreign_keys(synthetic: Synthetic) -> None:
    s = synthetic
    kit = Kit(s)
    d = seed(s)
    step = kit.upd_cpk()
    connection, plan = open_plan(s, kit.decl(step))
    assert sorted(plan.lock(connection, kit.lock_cpk, {"a": d.cpk_a})) == sorted(
        [(d.cpk_a, d.cpk_b1), (d.cpk_a, d.cpk_b2)]
    )
    plan.finalize(connection)
    out = [
        plan.execute(connection, step, {"ka": d.cpk_a, "kb": b, "nv": 5})
        for b in (d.cpk_b1, d.cpk_b2)
    ]
    assert [o.keys for o in out] == [((d.cpk_a, d.cpk_b1),), ((d.cpk_a, d.cpk_b2),)]
    commit(connection)
    assert {r[0] for r in committed(s, f"SELECT v FROM {s.schema}.cpk")} == {5}

    # composite target: only one of two keys locked -> the other is TARGET_NOT_LOCKED
    s.run(f"UPDATE {s.schema}.cpk SET v = 10")
    one_lock = PreLock(
        "cpk_one",
        select(s.tables["cpk"].c.a, s.tables["cpk"].c.b)
        .where(s.tables["cpk"].c.a == bindparam("a"), s.tables["cpk"].c.b == bindparam("b"))
        .with_for_update(),
    )
    cpk = s.tables["cpk"]
    step2 = WriteStep(
        name="upd_cpk",
        statement=update(cpk)
        .where(cpk.c.a == bindparam("ka"), cpk.c.b == bindparam("kb"))
        .values(v=bindparam("nv"))
        .returning(cpk.c.a, cpk.c.b),
        cardinality=Between(0, 2),
        target=(KeyBind(cpk.c.a, "ka"), KeyBind(cpk.c.b, "kb")),
        target_lock=one_lock,
        value_binds=frozenset({"nv"}),
    )
    decl = PreWriteDeclaration(locks=(one_lock,), steps=(step2,))
    connection, plan = open_plan(s, decl)
    try:
        plan.lock(connection, one_lock, {"a": d.cpk_a, "b": d.cpk_b1})
        plan.finalize(connection)
        control_update(s, step2.statement, {"ka": d.cpk_a, "kb": d.cpk_b2, "nv": 1})  # type: ignore[arg-type]
        refused(
            s, connection, plan, R.TARGET_NOT_LOCKED,
            lambda: plan.execute(connection, step2, {"ka": d.cpk_a, "kb": d.cpk_b2, "nv": 1}),
            "cpk",
        )  # fmt: skip
    finally:
        deps._discard(connection)


def test_composite_foreign_keys_reference_a_unique_key_with_grouped_evidence(
    synthetic: Synthetic,
) -> None:
    s = synthetic
    kit = Kit(s)
    child, childf = s.tables["child"], s.tables["childf"]
    r1, sc, ot, r2 = new_id(), new_id(), new_id(), new_id()
    s.run(
        f"INSERT INTO {s.schema}.ref VALUES (:r1,:sc,:ot), (:r2,:sc,:ot)",
        r1=r1,
        sc=sc,
        ot=ot,
        r2=r2,
    )

    def ins(table: Any, lock: PreLock | None = None) -> WriteStep:
        constraint = next(iter(table.foreign_key_constraints))
        return WriteStep(
            name=f"ins_{table.name}",
            statement=insert(table)
            .values(
                child_id=bindparam("cid"),
                r_id=bindparam("r"),
                scope=bindparam("sc"),
                other=bindparam("ot"),
            )
            .returning(table.c.child_id),
            cardinality=Between(0, 5),
            fks=(
                FkBinding(
                    constraint,
                    tuple(
                        KeyBind(table.c[c], b)
                        for c, b in (("r_id", "r"), ("scope", "sc"), ("other", "ot"))
                    ),
                    lock or kit.lock_ref,
                ),
            ),
            value_binds=frozenset({"cid"}),
        )

    simple, full = ins(child), ins(childf)
    decl = PreWriteDeclaration(locks=kit.locks, steps=(simple, full))

    def run(table_step: WriteStep, params: dict[str, Any]) -> Any:
        return plan.execute(connection, table_step, {"cid": new_id(), **params})

    connection, plan = open_plan(s, decl)
    try:
        plan.lock(connection, kit.lock_ref, {"r": r1})  # evidence: (r1, sc, ot) only
        plan.finalize(connection)
        assert run(simple, {"r": r1, "sc": sc, "ot": ot}).keys  # (a) a full tuple in evidence
        assert run(simple, {"r": None, "sc": None, "ot": None}).keys  # (c) all NULL: no RI check
        # (d) partial NULL, under MATCH SIMPLE and MATCH FULL, refused before SQLAlchemy
        for step in (simple, full):
            refused(
                s, connection, plan, R.FK_PARTIAL_NULL,
                lambda step=step: run(step, {"r": r1, "sc": None, "ot": ot}),
                "child", "childf",
            )  # fmt: skip
            plan._violated = False  # the next case needs a fresh latch
            plan._violation = None
        # (b) one element changed to another seeded, unlocked tuple
        refused(
            s, connection, plan, R.FK_NOT_LOCKED,
            lambda: run(simple, {"r": r2, "sc": sc, "ot": ot}), "child",
        )  # fmt: skip
    finally:
        deps._discard(connection)


# --- the snapshot is the only authority (PW-2, PW-22-24) -----------------------------------------------


class MutableZone(datetime.tzinfo):
    """A caller-owned, mutable tzinfo."""

    def __init__(self, hours: int) -> None:
        self.hours = hours

    def utcoffset(self, dt: datetime.datetime | None) -> datetime.timedelta:
        return datetime.timedelta(hours=self.hours)

    def dst(self, dt: datetime.datetime | None) -> datetime.timedelta:
        return datetime.timedelta(0)

    def tzname(self, dt: datetime.datetime | None) -> str:
        return "mutable"


def test_the_snapshot_is_immutable_after_validation_including_nested_objects_and_tzinfo(
    synthetic: Synthetic,
) -> None:
    s = synthetic
    kit = Kit(s)
    d = seed(s)
    step = kit.rich()
    zone = MutableZone(2)
    ts = datetime.datetime(2026, 1, 1, 12, 0, tzinfo=zone)
    meta: dict[str, Any] = {"a": [1, {"b": 2}]}
    tags = ["x", "y"]
    caller: dict[str, Any] = {
        "k": d.t1, "note": "n", "tags": tags, "ts": ts, "rng": Range(1, 5), "meta": meta, "active": False,
    }  # fmt: skip

    install_authorization_guard(s.engine)

    def mutate_callers_objects(_c: Any, element: Any, *_: object) -> None:
        """Runs after the guard's `before_execute`: everything the caller passed is mutated."""
        if not isinstance(element, Update):
            return
        caller["k"] = d.t2
        caller["note"] = "changed"
        tags.append("z")
        meta["a"].append(3)
        meta["c"] = 1
        zone.hours = 9

    event.listen(s.engine, "before_execute", mutate_callers_objects)
    connection, plan = open_plan(s, kit.decl(step))
    plan.lock(connection, kit.lock_one, {"k": d.t1})
    plan.finalize(connection)
    plan.execute(connection, step, caller)
    commit(connection)
    row = committed(
        s,
        f"SELECT note, tags, stamp, rng::text, meta, active FROM {s.schema}.target WHERE target_id=:t",
        t=d.t1,
    )[0]
    assert row[0] == "n" and row[1] == ["x", "y"]
    assert row[2] == datetime.datetime(2026, 1, 1, 10, 0, tzinfo=datetime.UTC)  # 12:00 at +02:00
    assert row[3] == "[1,5)" and row[4] == {"a": [1, {"b": 2}]} and row[5] is False
    # the other target was not touched
    assert (
        committed(s, f"SELECT note FROM {s.schema}.target WHERE target_id=:t", t=d.t2)[0][0] is None
    )


def _mutator_case(
    synthetic: Synthetic,
    register: Callable[[Engine, Seed], None],
    reason: ViolationReason,
) -> None:
    s = synthetic
    kit = Kit(s)
    d = seed(s)
    step = kit.upd(EachLockedRow(complete=False), lock=kit.lock_one)
    install_authorization_guard(s.engine)
    register(s.engine, d)  # registered AFTER the guard, BEFORE the plan
    connection, plan = open_plan(s, kit.decl(step))
    try:
        plan.lock(connection, kit.lock_one, {"k": d.t1})
        plan.finalize(connection)
        control_update(s, step.statement, {"k": d.t2, "nv": 99})  # type: ignore[arg-type]
        refused(
            s, connection, plan, reason,
            lambda: plan.execute(connection, step, {"k": d.t1, "nv": 50}), "target",
        )  # fmt: skip
        assert (
            committed(s, f"SELECT v FROM {s.schema}.target WHERE target_id=:t", t=d.t2)[0][0] == 2
        )
        with pytest.raises(AuthorizationPlanNotFinalizedError):
            connection.commit()
    finally:
        deps._discard(connection)


def test_a_listener_mutating_before_execute_params_is_refused_before_the_driver(
    synthetic: Synthetic,
) -> None:
    def register(engine: Engine, d: Seed) -> None:
        def mutate(_c: Any, element: Any, _m: Any, params: Any, _o: Any) -> None:
            if isinstance(element, Update) and "k" in params:
                params["k"] = d.t2

        event.listen(engine, "before_execute", mutate)

    _mutator_case(synthetic, register, R.PARAMETERS)


def test_a_listener_mutating_cursor_parameters_in_place_is_refused_at_the_last_hop(
    synthetic: Synthetic,
) -> None:
    def register(engine: Engine, d: Seed) -> None:
        def mutate(_c: Any, _cur: Any, _s: Any, parameters: Any, _ctx: Any, _m: Any) -> None:
            if isinstance(parameters, dict) and "k" in parameters and "nv" in parameters:
                parameters["k"] = d.t2

        event.listen(engine, "before_cursor_execute", mutate)

    _mutator_case(synthetic, register, R.PARAMETERS)


def test_retval_listeners_replacing_parameters_or_sql_are_refused_at_the_last_hop(
    synthetic: Synthetic,
) -> None:
    def new_params(engine: Engine, d: Seed) -> None:
        def swap(_c: Any, _cur: Any, statement: Any, parameters: Any, _ctx: Any, _m: Any) -> Any:
            if isinstance(parameters, dict) and "k" in parameters and "nv" in parameters:
                return statement, {**parameters, "k": d.t2}
            return statement, parameters

        event.listen(engine, "before_cursor_execute", swap, retval=True)

    _mutator_case(synthetic, new_params, R.PARAMETERS)


def test_retval_listener_changing_sql_text_is_refused(synthetic: Synthetic) -> None:
    def new_sql(engine: Engine, d: Seed) -> None:
        def swap(_c: Any, _cur: Any, statement: Any, parameters: Any, _ctx: Any, _m: Any) -> Any:
            if isinstance(parameters, dict) and "k" in parameters and "nv" in parameters:
                return statement.replace("RETURNING", "/* x */ RETURNING"), parameters
            return statement, parameters

        event.listen(engine, "before_cursor_execute", swap, retval=True)

    _mutator_case(synthetic, new_sql, R.RENDERING)


def test_a_later_do_execute_listener_never_runs_and_the_statement_uses_the_snapshot(
    synthetic: Synthetic,
) -> None:
    s = synthetic
    kit = Kit(s)
    d = seed(s)
    step = kit.upd(EachLockedRow(complete=False), lock=kit.lock_one)
    install_authorization_guard(s.engine)
    calls: list[int] = []
    holder: list[AuthorizationPlan] = []

    def later(*_: Any) -> bool:
        if holder and holder[0]._flight is not None:
            calls.append(1)  # only a call during a controlled execution matters
        return False

    event.listen(s.engine, "do_execute", later)
    connection, plan = open_plan(s, kit.decl(step))
    holder.append(plan)
    plan.lock(connection, kit.lock_one, {"k": d.t1})
    plan.finalize(connection)
    plan.execute(connection, step, {"k": d.t1, "nv": 55})
    assert calls == [], "the guard's True ends do_execute dispatch"
    commit(connection)
    assert committed(s, f"SELECT v FROM {s.schema}.target WHERE target_id=:t", t=d.t1)[0][0] == 55


def test_a_do_execute_listener_registered_before_the_guard_is_refused_by_listener_order(
    synthetic: Synthetic, postgres_engine: Engine
) -> None:
    s = synthetic
    kit = Kit(s)
    d = seed(s)
    calls: list[int] = []

    def early(cursor: Any, statement: Any, parameters: Any, context: Any) -> bool:
        calls.append(1)
        return False

    install_authorization_guard(s.engine)
    dialect_class = type(s.engine.dialect)
    event.listen(dialect_class, "do_execute", early, insert=True)  # a class-level listener
    try:
        assert list(s.engine.dialect.dispatch.do_execute)[0] is early
        _listener_order_case(s, kit, d, calls)
    finally:
        event.remove(dialect_class, "do_execute", early)


def _listener_order_case(s: Synthetic, kit: Kit, d: Seed, calls: list[int]) -> None:
    step = kit.upd(EachLockedRow(complete=False), lock=kit.lock_one)
    connection, plan = open_plan(s, kit.decl(step))  # the guard is installed here, after `early`
    try:
        refused(
            s, connection, plan, R.LISTENER_ORDER,
            lambda: plan.lock(connection, kit.lock_one, {"k": d.t1}),
            "target",
        )  # fmt: skip
        assert plan.violation is R.LISTENER_ORDER  # E-driver +0 was asserted by `refused`
    finally:
        deps._discard(connection)


def test_c4_detects_a_bypass_after_execution_and_refuses_the_commit(synthetic: Synthetic) -> None:
    """C4 is detect-only: a unit case with a flight whose statement was never dispatched by the guard."""
    s = synthetic
    kit = Kit(s)
    step = kit.upd(EachLockedRow(complete=False), lock=kit.lock_one)
    connection, plan = open_plan(s, kit.decl(step))
    try:
        plan.finalize(connection)
        flight = authorization._Flight(
            kind="step", subject=step, names=("k", "nv"), specs=step.specs, frozen={},
            call_params={}, canon=authorization._canon_for(step, connection.dialect, ("k", "nv")),
            topology=authorization._topology(connection),
        )  # fmt: skip
        plan._flight = flight
        authorization._on_after_cursor_execute(connection, None, "", None, None, False)
        plan._flight = None
        assert plan.violation is R.DISPATCH_BYPASSED
        with pytest.raises(AuthorizationPlanNotFinalizedError):
            connection.commit()
    finally:
        deps._discard(connection)


def test_a_registration_after_the_plan_began_is_refused_and_one_during_a_permit_is_caught(
    synthetic: Synthetic,
) -> None:
    s = synthetic
    kit = Kit(s)
    d = seed(s)
    step = kit.upd(EachLockedRow(complete=False), lock=kit.lock_one)
    connection, plan = open_plan(s, kit.decl(step))
    try:
        event.listen(s.engine, "before_execute", lambda *_: None)  # after the plan began
        refused(
            s, connection, plan, R.LISTENER_TOPOLOGY,
            lambda: plan.lock(connection, kit.lock_one, {"k": d.t1}), "target",
        )  # fmt: skip
        with pytest.raises(AuthorizationPlanNotFinalizedError):
            connection.commit()
    finally:
        deps._discard(connection)

    # registered from inside a controlled execution, after the guard's own cursor hook: the last hop
    # still sees the changed topology and refuses before the driver
    install_authorization_guard(s.engine)
    added: list[Callable[..., Any]] = []
    holder: list[AuthorizationPlan] = []

    def register_during(*_: Any) -> None:
        flight = holder[0]._flight if holder else None
        if flight is not None and flight.kind == "step" and not added:
            added.append(lambda *_a: None)
            event.listen(s.engine, "after_execute", added[0])

    event.listen(s.engine, "before_cursor_execute", register_during)
    step2 = kit.upd(EachLockedRow(complete=False), lock=kit.lock_one)
    connection, plan = open_plan(s, kit.decl(step2))
    holder.append(plan)
    try:
        plan.lock(connection, kit.lock_one, {"k": d.t1})
        plan.finalize(connection)
        refused(
            s, connection, plan, R.LISTENER_TOPOLOGY,
            lambda: plan.execute(connection, step2, {"k": d.t1, "nv": 1}), "target",
        )  # fmt: skip
    finally:
        if added:
            event.remove(s.engine, "after_execute", added[0])
        deps._discard(connection)


# --- undeclared statements after finalize (PW-1, PW-7, PW-8) -----------------------------------------------


def test_undeclared_statements_are_refused_after_finalize(synthetic: Synthetic) -> None:
    s = synthetic
    kit = Kit(s)
    d = seed(s)
    step = kit.upd(EachLockedRow(complete=False), lock=kit.lock_one)
    tgt = s.tables["target"]
    twin = (
        update(tgt)
        .where(tgt.c.target_id == bindparam("k"))
        .values(v=bindparam("nv"), stamp=func.pg_catalog.now())
        .returning(tgt.c.target_id)
    )
    exact_sql = str(step.statement.compile(dialect=s.engine.dialect))
    cases: dict[str, Callable[[Connection], object]] = {
        "twin": lambda c: c.execute(twin, {"k": d.t1, "nv": 5}),
        "text_exact_sql": lambda c: c.execute(text(exact_sql.replace("%(k)s::UUID", ":k").replace("%(nv)s::INTEGER", ":nv")), {"k": d.t1, "nv": 5}),
        "declared_object_directly": lambda c: c.execute(step.statement, {"k": d.t1, "nv": 5}),
        "select": lambda c: c.execute(text("SELECT 1")),
        "for_update_other": lambda c: c.execute(text(f"SELECT n FROM {s.schema}.other FOR UPDATE")),
        "advisory": lambda c: c.execute(text("SELECT pg_advisory_xact_lock(918273)")),
        "set_local": lambda c: c.execute(text("SET LOCAL lock_timeout = '5s'")),
        "lock_table": lambda c: c.execute(text(f"LOCK TABLE {s.schema}.other IN ACCESS SHARE MODE")),
        "undeclared_text_insert": lambda c: c.execute(text(f"INSERT INTO {s.schema}.other VALUES (1)")),
        "undeclared_core_insert": lambda c: c.execute(insert(s.tables["other"]).values(n=1)),
        "cte": lambda c: c.execute(text("WITH x AS (SELECT 1) SELECT * FROM x")),
        "data_modifying_cte": lambda c: c.execute(
            text(f"WITH u AS (UPDATE {s.schema}.target SET v = 9 WHERE target_id = :k RETURNING 1) SELECT * FROM u"),
            {"k": d.t1},
        ),
        "exec_driver_sql": lambda c: c.exec_driver_sql("SELECT 1"),
        "exec_driver_sql_many": lambda c: c.exec_driver_sql("SELECT %s", [(1,), (2,)]),
        "begin_nested": lambda c: c.begin_nested(),
        "executemany_direct": lambda c: c.execute(step.statement, [{"k": d.t1, "nv": 1}, {"k": d.t2, "nv": 2}]),
    }  # fmt: skip
    # positive controls: the twin's change on a plain connection really changes the seeded row
    control_update(s, twin, {"k": d.t1, "nv": 5})
    for name, attempt in cases.items():
        connection, plan = open_plan(s, kit.decl(step))
        try:
            plan.lock(connection, kit.lock_one, {"k": d.t1})
            plan.finalize(connection)
            before = {t: s.server_count(t) for t in ("target", "other")}
            d0 = driver_calls(connection)
            with pytest.raises(AuthorizationPlanViolationError):
                attempt(connection)
            assert plan.violation is R.UNCONTROLLED, name
            assert driver_calls(connection) == d0, name
            assert {t: s.server_count(t) for t in before} == before, name
            with pytest.raises(AuthorizationPlanNotFinalizedError):
                connection.commit()
        finally:
            deps._discard(connection)
    # nothing leaked: no row of the decoy changed, no advisory lock survived a rolled back session
    assert committed(s, f"SELECT v FROM {s.schema}.target WHERE target_id=:t", t=d.t1)[0][0] == 1
    assert (
        s.rows("SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND objid = 918273")[0][0]
        == 0
    )


def test_a_swapped_element_inside_plan_execute_is_refused_at_the_cursor(
    synthetic: Synthetic,
) -> None:
    s = synthetic
    kit = Kit(s)
    d = seed(s)
    step = kit.upd(EachLockedRow(complete=False), lock=kit.lock_one)
    tgt = s.tables["target"]
    twin = (
        update(tgt)
        .where(tgt.c.target_id == bindparam("k"))
        .values(v=bindparam("nv"), stamp=func.pg_catalog.now())
        .returning(tgt.c.target_id)
    )
    install_authorization_guard(s.engine)

    def swap(_c: Any, element: Any, multiparams: Any, params: Any, _o: Any) -> Any:
        return (
            (twin, multiparams, params)
            if element is step.statement
            else (element, multiparams, params)
        )

    event.listen(s.engine, "before_execute", swap, retval=True)
    control_update(s, twin, {"k": d.t1, "nv": 5})
    connection, plan = open_plan(s, kit.decl(step))
    try:
        plan.lock(connection, kit.lock_one, {"k": d.t1})
        plan.finalize(connection)
        refused(
            s, connection, plan, R.IDENTITY,
            lambda: plan.execute(connection, step, {"k": d.t1, "nv": 5}), "target",
        )  # fmt: skip
    finally:
        deps._discard(connection)


def test_executemany_and_execution_options_are_refused(synthetic: Synthetic) -> None:
    s = synthetic
    kit = Kit(s)
    d = seed(s)
    step = kit.upd(EachLockedRow(complete=False), lock=kit.lock_targets)
    options: dict[str, dict[str, Any]] = {
        "logging_token": {"logging_token": "x"},
        "schema_translate_map": {"schema_translate_map": {None: s.schema}},
        "stream_results": {"stream_results": True},
    }
    for name, opts in options.items():
        connection, plan = open_plan(s, kit.decl(step))
        try:
            plan.lock(connection, kit.lock_targets, {"p": d.p1})
            plan.finalize(connection)
            connection.execution_options(**opts)
            refused(
                s, connection, plan, R.EXECUTION_OPTIONS,
                lambda: plan.execute(connection, step, {"k": d.t1, "nv": 5}), "target",
            )  # fmt: skip
        finally:
            deps._discard(connection)
    # a list of mappings instead of a mapping, before SQLAlchemy
    connection, plan = open_plan(s, kit.decl(step))
    try:
        plan.lock(connection, kit.lock_targets, {"p": d.p1})
        plan.finalize(connection)
        refused(
            s, connection, plan, R.PARAMETERS,
            lambda: plan.execute(connection, step, [{"k": d.t1, "nv": 1}, {"k": d.t2, "nv": 2}]),  # type: ignore[arg-type]
            "target",
        )  # fmt: skip
    finally:
        deps._discard(connection)
    control_update(s, step.statement, {"k": d.t1, "nv": 1})  # type: ignore[arg-type]


# --- parameters (PW-2, PW-5) ---------------------------------------------------------------------------


def test_parameters_are_exact_before_sqlalchemy(synthetic: Synthetic) -> None:
    s = synthetic
    kit = Kit(s)
    d = seed(s)
    step = kit.upd(Between(0, 20), lock=kit.lock_targets)
    bad: dict[str, dict[str, Any]] = {
        "missing_key": {"k": d.t1},
        "unexpected_key": {"k": d.t1, "nv": 1, "other": 2},
        "unexpected_column_key": {"k": d.t1, "nv": 1, "note": "x"},
        "str_uuid": {"k": str(d.t1), "nv": 1},
        "bool_for_int": {"k": d.t1, "nv": True},
        "int4_overflow": {"k": d.t1, "nv": 2**31},
        "none_for_not_null": {"k": d.t1, "nv": None},
        "none_key": {"k": None, "nv": 1},
    }
    control_update(s, step.statement, {"k": d.t1, "nv": 1})  # type: ignore[arg-type]
    connection, plan = open_plan(s, kit.decl(step))
    try:
        plan.lock(connection, kit.lock_targets, {"p": d.p1})
        plan.finalize(connection)
        for name, params in bad.items():
            plan._violated = False
            plan._violation = None
            refused(
                s, connection, plan, R.PARAMETERS,
                lambda params=params: plan.execute(connection, step, params), "target",
            )  # fmt: skip
        # TARGET_NOT_LOCKED: the unlocked decoy
        plan._violated = False
        plan._violation = None
        refused(
            s, connection, plan, R.TARGET_NOT_LOCKED,
            lambda: plan.execute(connection, step, {"k": d.t3, "nv": 1}), "target",
        )  # fmt: skip
    finally:
        deps._discard(connection)


# --- order, counts, completion, duplicates (PW-10, PW-11) ----------------------------------------------


def test_order_counts_duplicates_and_completion(synthetic: Synthetic) -> None:
    s = synthetic
    kit = Kit(s)
    d = seed(s)
    step_a = kit.upd(Exactly(1), lock=kit.lock_targets, name="a")
    step_b = kit.ins_log(Exactly(1))
    decl = kit.decl(step_a, step_b)

    def fresh() -> tuple[Connection, AuthorizationPlan]:
        connection, plan = open_plan(s, decl)
        lock_family(connection, plan, kit, d)
        plan.finalize(connection)
        return connection, plan

    # order: step b before a required step a
    connection, plan = fresh()
    try:
        refused(
            s, connection, plan, R.ORDER,
            lambda: plan.execute(connection, step_b, {"parent_id": d.p1, "msg": "m"}), "log",
        )  # fmt: skip
    finally:
        deps._discard(connection)
    # count: Exactly(1) twice; and the duplicate-target policy for the same key
    connection, plan = fresh()
    try:
        plan.execute(connection, step_a, {"k": d.t1, "nv": 1})
        refused(
            s, connection, plan, R.COUNT,
            lambda: plan.execute(connection, step_a, {"k": d.t2, "nv": 1}), "target",
        )  # fmt: skip
    finally:
        deps._discard(connection)
    # incomplete: a required step never ran
    connection, plan = fresh()
    try:
        plan.execute(connection, step_a, {"k": d.t1, "nv": 1})
        with pytest.raises(AuthorizationPlanNotFinalizedError):
            connection.commit()
        assert plan.violation is R.INCOMPLETE
    finally:
        deps._discard(connection)
    assert committed(s, f"SELECT v FROM {s.schema}.target WHERE target_id=:t", t=d.t1)[0][0] == 1
    # complete -> commits
    connection, plan = fresh()
    plan.execute(connection, step_a, {"k": d.t1, "nv": 1})
    plan.execute(connection, step_b, {"parent_id": d.p1, "msg": "m"})
    commit(connection)

    # EachLockedRow(complete=True): one of two locked keys unwritten -> INCOMPLETE
    each = kit.upd(EachLockedRow(complete=True), lock=kit.lock_targets, name="each")
    connection, plan = open_plan(s, kit.decl(each))
    try:
        lock_family(connection, plan, kit, d)
        plan.finalize(connection)
        plan.execute(connection, each, {"k": d.t1, "nv": 1})
        with pytest.raises(AuthorizationPlanNotFinalizedError):
            connection.commit()
        assert plan.violation is R.INCOMPLETE
    finally:
        deps._discard(connection)


@pytest.mark.parametrize(
    "cardinality",
    [Exactly(2), Between(0, 3), EachLockedRow(complete=False), EachLockedRow(complete=True)],
    ids=["exactly", "between", "each_incomplete", "each_complete"],
)
def test_a_repeated_target_key_in_one_step_is_refused_for_every_cardinality(
    synthetic: Synthetic, cardinality: Any
) -> None:
    s = synthetic
    kit = Kit(s)
    d = seed(s)
    step = kit.upd(cardinality, lock=kit.lock_targets)
    connection, plan = open_plan(s, kit.decl(step))
    try:
        lock_family(connection, plan, kit, d)
        plan.finalize(connection)
        plan.execute(connection, step, {"k": d.t1, "nv": 1})
        assert plan.confirmed(step) == ((d.t1,),)
        refused(
            s, connection, plan, R.DUPLICATE_TARGET,
            lambda: plan.execute(connection, step, {"k": d.t1, "nv": 2}), "target",
        )  # fmt: skip
        assert plan.attempts(step) == 1 and plan.confirmed(step) == ((d.t1,),)
        with pytest.raises(AuthorizationPlanNotFinalizedError):
            connection.commit()
    finally:
        deps._discard(connection)


def test_the_same_key_may_be_written_by_two_different_declared_steps(synthetic: Synthetic) -> None:
    s = synthetic
    kit = Kit(s)
    d = seed(s)
    first = kit.upd(Exactly(1), lock=kit.lock_targets, name="first")
    second = kit.upd(Exactly(1), lock=kit.lock_targets, name="second")
    connection, plan = open_plan(s, kit.decl(first, second))
    lock_family(connection, plan, kit, d)
    plan.finalize(connection)
    plan.execute(connection, first, {"k": d.t1, "nv": 1})
    plan.execute(connection, second, {"k": d.t1, "nv": 2})
    commit(connection)
    assert committed(s, f"SELECT v FROM {s.schema}.target WHERE target_id=:t", t=d.t1)[0][0] == 2


# --- row accounting (PW-26) ----------------------------------------------------------------------------


def test_row_accounting_one_zero_or_one_and_triggers(synthetic: Synthetic) -> None:
    s = synthetic
    kit = Kit(s)
    d = seed(s, t1_active=False)  # t1 is a seeded locked row whose narrowing predicate is false
    # (a) ONE + narrowing false -> ROWCOUNT, E-server +1 (it executed)
    step = kit.upd(Between(0, 3), lock=kit.lock_targets, narrow=True)
    control_update(s, kit.upd(Between(0, 3), lock=kit.lock_targets).statement, {"k": d.t1, "nv": 5})  # type: ignore[arg-type]
    connection, plan = open_plan(s, kit.decl(step))
    try:
        lock_family(connection, plan, kit, d)
        plan.finalize(connection)
        positive = plan.execute(connection, step, {"k": d.t2, "nv": 5})  # an active row: confirmed
        assert positive.keys == ((d.t2,),)
        refused(
            s, connection, plan, R.ROWCOUNT,
            lambda: plan.execute(connection, step, {"k": d.t1, "nv": 5}), "target", driver=1,
        )  # fmt: skip
        # (d) the caller catches it and attempts COMMIT
        with pytest.raises(AuthorizationPlanNotFinalizedError):
            connection.commit()
        assert plan.violation is R.ROWCOUNT
    finally:
        deps._discard(connection)

    # (b) ZERO_OR_ONE: zero rows is attempted, never confirmed; the lower bound is 0
    zstep = kit.upd(Between(0, 3), RowExpectation.ZERO_OR_ONE, lock=kit.lock_targets, narrow=True)
    connection, plan = open_plan(s, kit.decl(zstep))
    lock_family(connection, plan, kit, d)
    plan.finalize(connection)
    out = plan.execute(connection, zstep, {"k": d.t1, "nv": 5})
    assert out.keys == () and plan.attempts(zstep) == 1 and plan.confirmed(zstep) == ()
    assert plan.execute(connection, zstep, {"k": d.t2, "nv": 6}).keys == ((d.t2,),)
    commit(connection)

    # (e) EachLockedRow(complete=True) where one locked key is narrowed to zero rows
    each = kit.upd(EachLockedRow(complete=True), lock=kit.lock_targets, narrow=True)
    connection, plan = open_plan(s, kit.decl(each))
    try:
        lock_family(connection, plan, kit, d)
        plan.finalize(connection)
        plan.execute(connection, each, {"k": d.t2, "nv": 5})
        refused(
            s, connection, plan, R.ROWCOUNT,
            lambda: plan.execute(connection, each, {"k": d.t1, "nv": 5}), "target", driver=1,
        )  # fmt: skip
        with pytest.raises(AuthorizationPlanNotFinalizedError):
            connection.commit()
    finally:
        deps._discard(connection)

    # (c) a BEFORE ROW trigger returning NULL on INSERT: zero rows -> ROWCOUNT
    skip = kit.ins_skip()
    connection, plan = open_plan(s, kit.decl(skip))
    try:
        plan.finalize(connection)
        refused(
            s, connection, plan, R.ROWCOUNT,
            lambda: plan.execute(connection, skip, {"msg": "skip"}), "skip", driver=1,
        )  # fmt: skip
    finally:
        deps._discard(connection)
    # positive control for (c): a non-skipped insert returns its key
    connection, plan = open_plan(s, kit.decl(skip))
    plan.finalize(connection)
    assert len(plan.execute(connection, skip, {"msg": "keep"}).keys) == 1
    commit(connection)


def test_zero_or_one_is_only_declarable_with_a_lower_bound_of_zero(synthetic: Synthetic) -> None:
    kit = Kit(synthetic)
    for bad in (Exactly(1), Between(1, 2), EachLockedRow(complete=True)):
        with pytest.raises(ValueError):
            kit.upd(bad, RowExpectation.ZERO_OR_ONE, lock=kit.lock_targets)
    kit.upd(Between(0, 2), RowExpectation.ZERO_OR_ONE, lock=kit.lock_targets)
    kit.upd(EachLockedRow(complete=False), RowExpectation.ZERO_OR_ONE, lock=kit.lock_targets)


# --- failures (PW-12, PW-13, PW-15) -----------------------------------------------------------------------


def test_a_caught_execution_failure_latches_and_keeps_the_original_error(
    synthetic: Synthetic,
) -> None:
    s = synthetic
    kit = Kit(s)
    d = seed(s)
    s.run(f"UPDATE {s.schema}.target SET label = 'taken' WHERE target_id = :t", t=d.t3)
    step = kit.ins_label()
    connection, plan = open_plan(s, kit.decl(step))
    try:
        plan.lock(connection, kit.lock_parent, {"p": d.p1})
        plan.finalize(connection)
        with Observe(s, connection, "target") as o:
            with pytest.raises(DBAPIError) as caught:
                plan.execute(
                    connection, step, {"parent_id": d.p1, "v": 1, "active": True, "label": "taken"}
                )
        assert type(caught.value).__name__ == "IntegrityError"  # the class is unchanged
        assert plan.violation is R.EXECUTION_FAILED and o.driver() == 1 and o.server("target") == 1
        with pytest.raises(AuthorizationPlanNotFinalizedError):
            connection.commit()
    finally:
        deps._discard(connection)

    # through authorized_transaction: the original error is re-raised unchanged; the pool is clean
    with pytest.raises(DBAPIError) as again:
        with authorized_transaction(
            s.engine, new_id(), new_id(), mode=PlanMode.PRE_WRITE, pre_write=kit.decl(step)
        ) as (c, p):
            p.lock(c, kit.lock_parent, {"p": d.p1})
            p.finalize(c)
            p.execute(c, step, {"parent_id": d.p1, "v": 1, "active": True, "label": "taken"})
    assert type(again.value).__name__ == "IntegrityError"
    assert (
        s.rows(
            "SELECT count(*) FROM pg_stat_activity WHERE state LIKE 'idle in transaction%' AND datname = current_database()"
        )[0][0]
        == 0
    )


def test_failures_before_the_cursor_inside_plan_execute_latch(
    synthetic: Synthetic, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = synthetic
    kit = Kit(s)
    d = seed(s)
    step = kit.ins_audit()
    # (c) a value psycopg cannot adapt: E-driver +1 (client-side), E-server +0
    connection, plan = open_plan(s, kit.decl(step))
    try:
        plan.finalize(connection)
        with Observe(s, connection, "audit") as o:
            with pytest.raises(Exception) as caught:  # noqa: PT011
                plan.execute(connection, step, {"pid": d.p1, "note": "bad\x00nul"})
        assert plan.violation is R.EXECUTION_FAILED and not isinstance(
            caught.value, AuthorizationPlanViolationError
        )
        assert o.server("audit") == 0
        with pytest.raises(AuthorizationPlanNotFinalizedError):
            connection.commit()
    finally:
        deps._discard(connection)

    # (b) a compile failure at the position before `handle_error` exists: E-driver +0
    connection, plan = open_plan(s, kit.decl(step))
    try:
        plan.finalize(connection)
        handled: list[int] = []
        event.listen(s.engine, "handle_error", lambda ctx: handled.append(1))
        original = type(step.statement)._compile_w_cache
        monkeypatch.setattr(type(step.statement), "_compile_w_cache", _raise_compile)
        with Observe(s, connection, "audit") as o:
            with pytest.raises(Exception) as caught:  # noqa: PT011
                plan.execute(connection, step, {"pid": d.p1, "note": "n"})
        monkeypatch.setattr(type(step.statement), "_compile_w_cache", original)
        assert plan.violation in (R.EXECUTION_FAILED, R.LISTENER_TOPOLOGY)
        assert o.driver() == 0 and o.server("audit") == 0
        assert handled == [], "compile failures never reach handle_error"
        with pytest.raises(AuthorizationPlanNotFinalizedError):
            connection.commit()
    finally:
        deps._discard(connection)


def _raise_compile(*_a: Any, **_k: Any) -> Any:
    from sqlalchemy.exc import CompileError

    raise CompileError("synthetic compile failure")


def test_n1_a_direct_call_rejected_before_its_first_event_is_not_latched(
    synthetic: Synthetic,
) -> None:
    s = synthetic
    kit = Kit(s)
    d = seed(s)
    step = kit.ins_log(Exactly(1))
    # (a) the step is required and not yet run: COMMIT is refused as INCOMPLETE
    connection, plan = open_plan(s, kit.decl(step))
    try:
        plan.lock(connection, kit.lock_parent, {"p": d.p1})
        plan.finalize(connection)
        with Observe(s, connection, "log") as o:
            with pytest.raises(Exception) as caught:  # noqa: PT011
                connection.execute(step.statement, 5)  # type: ignore[arg-type]
        assert type(caught.value).__name__ == "ArgumentError"
        assert not plan.violated and plan.violation is None
        assert o.driver() == 0 and o.server("log") == 0
        with pytest.raises(AuthorizationPlanNotFinalizedError):
            connection.commit()
        assert plan.violation is R.INCOMPLETE
    finally:
        deps._discard(connection)
    # (b) all required steps already completed: the rejected call does not prevent the commit
    connection, plan = open_plan(s, kit.decl(step))
    plan.lock(connection, kit.lock_parent, {"p": d.p1})
    plan.finalize(connection)
    plan.execute(connection, step, {"parent_id": d.p1, "msg": "m"})
    with pytest.raises(ArgumentError):
        connection.execute(step.statement, 5)  # type: ignore[arg-type]
    assert not plan.violated
    commit(connection)
    assert committed(s, f"SELECT count(*) FROM {s.schema}.log")[0][0] == 1


def _request_app(s: Synthetic, kit: Kit, d: Seed, *, catch: bool) -> FastAPI:
    app = FastAPI(dependencies=[Depends(deps.commit_request_transaction, scope="function")])
    install_error_handlers(app)
    step = kit.upd(Exactly(1), lock=kit.lock_targets, narrow=True)
    decl = kit.decl(step)

    @app.post("/write/{which}")
    def write(
        which: str, connection: Annotated[Connection, Depends(deps.get_connection)]
    ) -> dict[str, Any]:
        plan = AuthorizationPlan.begin(
            connection, actor_user_id=new_id(), campaign_id=new_id(), mode=PlanMode.PRE_WRITE, pre_write=decl,
        )  # fmt: skip
        lock_family(connection, plan, kit, d)
        plan.finalize(connection)
        key = d.t1 if which == "bad" else d.t2  # t1 is inactive: the narrowing predicate is false
        try:
            plan.execute(connection, step, {"k": key, "nv": 42})
        except AuthorizationPlanViolationError:
            if not catch:
                raise
        return {"ok": True}

    app.dependency_overrides[deps.get_engine] = lambda: s.engine
    return app


def test_a_caught_refusal_in_a_request_is_a_fixed_500_and_the_pool_is_clean(
    synthetic: Synthetic,
) -> None:
    s = synthetic
    kit = Kit(s)
    d = seed(s, t1_active=False)
    for catch in (True, False):
        with TestClient(
            _request_app(s, kit, d, catch=catch), raise_server_exceptions=False
        ) as client:
            bad = client.post("/write/bad")
            assert bad.status_code == 500 and bad.json()["error"]["code"] == "internal_error"
            assert "plan" not in bad.text.lower()
            assert (
                committed(s, f"SELECT v FROM {s.schema}.target WHERE target_id=:t", t=d.t1)[0][0]
                == 1
            )
            good = client.post("/write/good")
            assert good.status_code == 200
    assert committed(s, f"SELECT v FROM {s.schema}.target WHERE target_id=:t", t=d.t2)[0][0] == 42
    assert (
        s.rows(
            "SELECT count(*) FROM pg_stat_activity WHERE state LIKE 'idle in transaction%' AND datname = current_database()"
        )[0][0]
        == 0
    )


# --- lock evidence (PW-16, PW-17, PW-28) --------------------------------------------------------------------


def test_lock_evidence_is_real_and_only_a_successful_lock_records_it(synthetic: Synthetic) -> None:
    s = synthetic
    kit = Kit(s)
    d = seed(s)
    step = kit.upd(EachLockedRow(complete=False), lock=kit.lock_one)
    connection, plan = open_plan(s, kit.decl(step))
    try:
        assert plan.lock(connection, kit.lock_one, {"k": d.t1}) == ((d.t1,),)
        # a competitor's FOR UPDATE NOWAIT on the evidence key fails with 55P03
        with s.plain.connect() as other:
            with pytest.raises(DBAPIError) as caught:
                other.execute(
                    text(f"SELECT 1 FROM {s.schema}.target WHERE target_id = :k FOR UPDATE NOWAIT"),
                    {"k": d.t1},
                )
            assert caught.value.orig.sqlstate == "55P03"  # type: ignore[union-attr]
            other.rollback()
            # but the unlocked decoy is free
            other.execute(
                text(f"SELECT 1 FROM {s.schema}.target WHERE target_id = :k FOR UPDATE NOWAIT"),
                {"k": d.t3},
            )
            other.rollback()
        # a lock taken by an ordinary statement is not evidence
        connection.execute(
            text(f"SELECT target_id FROM {s.schema}.target WHERE target_id = :k FOR UPDATE"),
            {"k": d.t2},
        )
        assert plan.evidence(kit.lock_one) == frozenset({(d.t1,)})
        # a malformed lock call latches LOCK_FAILED... (a wrong key type) and records nothing
        before = plan.evidence(kit.lock_one)
        refused(
            s,
            connection,
            plan,
            R.PARAMETERS,
            lambda: plan.lock(connection, kit.lock_one, {"k": str(d.t2)}),
            "target",
            driver=2,
        )  # fmt: skip  (driver +2: the session and compared-type checks; the lock never reached the driver)
        assert plan.evidence(kit.lock_one) == before and plan._flight is None
        with pytest.raises(AuthorizationPlanNotFinalizedError):
            connection.commit()
    finally:
        deps._discard(connection)


def test_lock_rules_after_finalize_savepoints_and_bindings(synthetic: Synthetic) -> None:
    s = synthetic
    kit = Kit(s)
    d = seed(s)
    step = kit.upd(EachLockedRow(complete=False), lock=kit.lock_one)
    # LOCK_AFTER_FINALIZE
    connection, plan = open_plan(s, kit.decl(step))
    try:
        plan.finalize(connection)
        with pytest.raises(AuthorizationPlanStateError):
            plan.lock(connection, kit.lock_one, {"k": d.t1})
        assert plan.violation is R.LOCK_AFTER_FINALIZE
    finally:
        deps._discard(connection)
    # a savepoint rollback BEFORE any lock is admitted; AFTER evidence it latches
    connection, plan = open_plan(s, kit.decl(step))
    try:
        sp = connection.begin_nested()
        sp.rollback()
        plan.lock(connection, kit.lock_one, {"k": d.t1})
        plan.finalize(connection)
        assert not plan.violated
    finally:
        deps._discard(connection)
    connection, plan = open_plan(s, kit.decl(step))
    try:
        sp = connection.begin_nested()
        plan.lock(connection, kit.lock_one, {"k": d.t1})
        sp.rollback()
        assert plan.violation is R.SAVEPOINT_ROLLBACK
        with pytest.raises(AuthorizationPlanNotFinalizedError):
            connection.commit()
    finally:
        deps._discard(connection)
    # binding: another connection, and a second transaction on the plan's connection
    connection, plan = open_plan(s, kit.decl(step))
    other = s.engine.dispose() or s.plain.connect()
    try:
        other.begin()
        with pytest.raises(AuthorizationPlanBindingError):
            plan.lock(other, kit.lock_one, {"k": d.t1})
        assert plan.violation is R.BINDING and plan.evidence(kit.lock_one) == frozenset()
    finally:
        other.close()
        deps._discard(connection)
    connection, plan = open_plan(s, kit.decl(step))
    try:
        connection.rollback()
        connection.begin()
        with pytest.raises(AuthorizationPlanBindingError):
            plan.lock(connection, kit.lock_one, {"k": d.t1})
        assert plan.evidence(kit.lock_one) == frozenset()
    finally:
        deps._discard(connection)


def test_plan_lock_controls_reentrancy_side_execution_and_failed_validation(
    synthetic: Synthetic, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = synthetic
    kit = Kit(s)
    d = seed(s)
    step = kit.upd(EachLockedRow(complete=False), lock=kit.lock_one)
    install_authorization_guard(s.engine)
    mode = {"on": None}

    def hook(connection: Connection, element: Any, *_: Any) -> None:
        if mode["on"] is None or getattr(element, "is_select", False) is False:
            return
        action, mode["on"] = mode["on"], None
        if action == "reenter_lock":
            plans[0].lock(connection, kit.lock_one, {"k": d.t1})
        elif action == "reenter_execute":
            plans[0].execute(connection, step, {"k": d.t1, "nv": 1})
        elif action == "advisory":
            connection.execute(text("SELECT pg_advisory_xact_lock(424242)"))
        elif action == "driver_sql":
            connection.exec_driver_sql("SELECT pg_advisory_xact_lock(424243)")

    plans: list[AuthorizationPlan] = []
    event.listen(s.engine, "before_execute", hook)

    for action, reason in (
        ("reenter_lock", R.REENTRANT),
        ("reenter_execute", R.REENTRANT),
        ("advisory", R.SIDE_EXECUTION),
        ("driver_sql", R.SIDE_EXECUTION),
    ):
        connection, plan = open_plan(s, kit.decl(step))
        plans[:] = [plan]
        try:
            mode["on"] = action  # type: ignore[assignment]
            with pytest.raises(AuthorizationPlanViolationError):
                plan.lock(connection, kit.lock_one, {"k": d.t1})
            assert plan.violation in (reason, R.NO_IDENTITY, R.LOCK_FAILED), action
            assert plan.evidence(kit.lock_one) == frozenset() and plan._flight is None
            with pytest.raises(AuthorizationPlanNotFinalizedError):
                connection.commit()
        finally:
            mode["on"] = None
            deps._discard(connection)
    assert (
        s.rows(
            "SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND objid IN (424242, 424243)"
        )[0][0]
        == 0
    )

    # a result that fails validation: a test seam returns a NULL key
    monkeypatch.setattr(authorization, "_validate_key", lambda kinds, row: None)
    connection, plan = open_plan(s, kit.decl(step))
    try:
        with pytest.raises(AuthorizationPlanViolationError):
            plan.lock(connection, kit.lock_one, {"k": d.t1})
        assert plan.violation is R.LOCK_FAILED
        assert plan.evidence(kit.lock_one) == frozenset() and plan._flight is None
        with pytest.raises(AuthorizationPlanNotFinalizedError):
            connection.commit()
    finally:
        deps._discard(connection)


def test_a_failed_lock_never_leaves_vacuous_evidence_for_a_complete_step(
    synthetic: Synthetic,
) -> None:
    s = synthetic
    kit = Kit(s)
    d = seed(s)
    each = kit.upd(EachLockedRow(complete=True), lock=kit.lock_one)
    connection, plan = open_plan(s, kit.decl(each))
    try:
        with pytest.raises(AuthorizationPlanViolationError):
            plan.lock(connection, kit.lock_one, {"k": "not-a-uuid"})  # type: ignore[arg-type]
        assert plan.evidence(kit.lock_one) == frozenset()
        with pytest.raises(AuthorizationPlanViolationError):
            plan.finalize(connection)  # a violated plan refuses to finalize
        with pytest.raises(AuthorizationPlanNotFinalizedError):
            connection.commit()
    finally:
        deps._discard(connection)
    assert d.t1


# --- session assumptions enforced on the bound connection --------------------------------------------------


@pytest.mark.parametrize(
    "setting",
    [
        "SET search_path = pg_catalog, public",
        "SET session_replication_role = replica",
    ],
    ids=["explicit_pg_catalog", "replica_role"],
)
def test_session_assumptions_are_enforced_on_the_bound_connection(
    synthetic: Synthetic, setting: str
) -> None:
    s = synthetic
    kit = Kit(s)
    d = seed(s)
    step = kit.upd(EachLockedRow(complete=False), lock=kit.lock_one)
    # changed before plan.lock: refused before any lock evidence exists
    connection, plan = open_plan(s, kit.decl(step))
    try:
        connection.execute(text(setting))
        with pytest.raises(AuthorizationPlanViolationError):
            plan.lock(connection, kit.lock_one, {"k": d.t1})
        assert plan.violation is R.SESSION and plan.evidence(kit.lock_one) == frozenset()
    finally:
        deps._discard(connection)
    # changed between plan.lock and finalize: finalize refuses and the plan never finalises
    connection, plan = open_plan(s, kit.decl(step))
    try:
        plan.lock(connection, kit.lock_one, {"k": d.t1})
        connection.execute(text(setting))
        with pytest.raises(AuthorizationPlanViolationError):
            plan.finalize(connection)
        assert plan.violation is R.SESSION and not plan.finalised
        with pytest.raises(AuthorizationPlanNotFinalizedError):
            connection.commit()
    finally:
        deps._discard(connection)
    # positive control: the settings are restored, the same flow passes
    connection, plan = open_plan(s, kit.decl(step))
    connection.execute(text("SET search_path = public"))
    plan.lock(connection, kit.lock_one, {"k": d.t1})
    plan.finalize(connection)
    plan.execute(connection, step, {"k": d.t1, "nv": 3})
    commit(connection)


def test_a_lookalike_comparison_operator_for_a_key_type_refuses_the_session(
    synthetic: Synthetic,
) -> None:
    s = synthetic
    kit = Kit(s)
    d = seed(s)
    step = kit.upd(EachLockedRow(complete=False), lock=kit.lock_one)
    s.run(
        f"CREATE FUNCTION {s.schema}.eq_uuid(uuid, uuid) RETURNS boolean LANGUAGE sql IMMUTABLE AS 'SELECT false'"
    )
    s.run(
        f"CREATE OPERATOR {s.schema}.= (LEFTARG = uuid, RIGHTARG = uuid, FUNCTION = {s.schema}.eq_uuid)"
    )
    connection, plan = open_plan(s, kit.decl(step))
    try:
        with pytest.raises(AuthorizationPlanViolationError):
            plan.lock(connection, kit.lock_one, {"k": d.t1})
        assert plan.violation is R.SESSION
    finally:
        deps._discard(connection)


# --- results and cleanup (finding 4) -----------------------------------------------------------------------


def test_the_cursor_result_is_closed_on_success_and_on_fetch_failure_and_the_pool_is_reusable(
    synthetic: Synthetic, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = synthetic
    kit = Kit(s)
    d = seed(s)
    step = kit.upd(Between(0, 5), lock=kit.lock_targets)
    closed: list[Any] = []
    from sqlalchemy.engine import CursorResult

    original_close = CursorResult.close

    def spy(self: Any) -> Any:
        closed.append(self)
        return original_close(self)

    monkeypatch.setattr(CursorResult, "close", spy)
    connection, plan = open_plan(s, kit.decl(step))
    lock_family(connection, plan, kit, d)
    plan.finalize(connection)
    plan.execute(connection, step, {"k": d.t1, "nv": 1})
    assert closed, "the CursorResult was closed on success"
    commit(connection)

    # a fetch failure: the original exception is preserved, the result is closed, the plan latched
    connection, plan = open_plan(s, kit.decl(step))
    first = pid(connection)
    lock_family(connection, plan, kit, d)
    plan.finalize(connection)
    closed.clear()

    class Boom(Exception):
        pass

    def boom(self: Any) -> Any:
        raise Boom

    monkeypatch.setattr(CursorResult, "all", boom)
    try:
        with pytest.raises(Boom):
            plan.execute(connection, step, {"k": d.t1, "nv": 2})
        assert closed and plan.violation is R.EXECUTION_FAILED
    finally:
        monkeypatch.setattr(CursorResult, "all", _Result.all)
        deps._discard(connection)
    # the pooled connection is reusable and idle
    with s.engine.connect() as again:
        assert pid(again) == first
    assert committed(s, f"SELECT v FROM {s.schema}.target WHERE target_id=:t", t=d.t1)[0][0] == 1


def test_step_outcome_carries_only_validated_primary_keys() -> None:
    import dataclasses

    assert [f.name for f in dataclasses.fields(StepOutcome)] == ["step", "keys"]
    with pytest.raises(dataclasses.FrozenInstanceError):
        StepOutcome("x", ()).keys = ()  # type: ignore[misc]


def test_the_requirement_flow_still_judges_a_pre_write_plan(synthetic: Synthetic) -> None:
    """A pre-write plan with no requirement judges nothing; registering after finalize violates it."""
    s = synthetic
    kit = Kit(s)
    connection, plan = open_plan(s, kit.decl(kit.ins_audit()))
    try:
        assert plan.finalize(connection) is None and plan.finalised
        from dnd_ai.domain.authorization import Requirement

        with pytest.raises(AuthorizationPlanStateError):
            plan.require(connection, Requirement("x", lambda _s: True, lambda: ValueError()))
    finally:
        deps._discard(connection)


def test_pending_inventory_helpers_are_untouched() -> None:
    from dnd_ai.api.r01_pending_routes import R01_PENDING_ROUTES

    assert len(R01_PENDING_ROUTES) == 192
    assert authorization.R01_PENDING is authorization.R01_PENDING
