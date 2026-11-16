# ruff: noqa: F811 - the imported fixture `w` is used by name
"""R01 S5-E5 infrastructure: `PerEvidenceRow` (I-1), `PerConfirmedRow` (I-2) and the `GREATEST` value form (I-3).

Design sections 4.1-4.3 and 10.1-10.2. These tests drive `AuthorizationPlan` directly against scratch tables, so each rule
is shown apart from any route. Evidence classes:

- **plan**: the API on a real connection and transaction; an INSERT refused before the driver call is proved by the
  recorded statement stream, not assumed;
- **declaration**: validation at construction (no database).

*Reachability note (COUNT).* `PerEvidenceRow` and `PerConfirmedRow` also refuse `COUNT` when attempts reach the size of
the evidence. Attempts equal the number of distinct values attempted, and every attempt must carry a not-yet-attempted
evidence key, so the earlier refusals (`FK_NOT_LOCKED`, `DUPLICATE_TARGET`, `EVIDENCE`) always fire first: `COUNT` is a
defensive third line and no schedule reaches it. It is not claimed as tested.
"""

import contextlib
import datetime
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import (
    Column,
    Connection,
    DateTime,
    Engine,
    ForeignKey,
    Identity,
    Integer,
    MetaData,
    Table,
    Text,
    Uuid,
    bindparam,
    create_engine,
    event,
    func,
    insert,
    select,
    text,
    update,
)
from sqlalchemy.dialects import postgresql

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
    DeclarationError,
    EachLockedRow,
    Exactly,
    FkBinding,
    KeyBind,
    PerConfirmedRow,
    PerEvidence,
    PerEvidenceRow,
    PreLock,
    PreWriteDeclaration,
    WriteStep,
)
from tests.database.test_r01_s3_authoring_routes import World, w  # noqa: F401 - fixture by name

pytestmark = pytest.mark.database

R = ViolationReason
SCHEMA = "r01_s5e5_ev"

_meta = MetaData()
gate = Table(
    "gate",
    _meta,
    Column("gate_id", Uuid, primary_key=True),
    Column("flag", Text, nullable=False),
    schema=SCHEMA,
)
link = Table(
    "link",
    _meta,
    Column("link_id", Uuid, primary_key=True),
    Column("gate_id", Uuid, ForeignKey(f"{SCHEMA}.gate.gate_id"), nullable=False),
    schema=SCHEMA,
)
audit = Table(
    "audit",
    _meta,
    Column("audit_id", Integer, Identity(), primary_key=True),
    Column("record_id", Uuid, nullable=False),
    Column("note", Text, nullable=False),
    schema=SCHEMA,
)
#: metadata only (declaration tests): an audit row whose record column is a foreign key
audit_fk = Table(
    "audit_fk",
    _meta,
    Column("audit_id", Integer, Identity(), primary_key=True),
    Column("record_id", Uuid, ForeignKey(f"{SCHEMA}.link.link_id"), nullable=False),
    schema=SCHEMA,
)

LOCK = PreLock(
    "gates",
    select(gate.c.gate_id)
    .where(gate.c.flag == bindparam("f"))
    .order_by(gate.c.gate_id)
    .with_for_update(),
)
#: the same SQL, another object: evidence is recorded under the exact object
LOCK_TWIN = PreLock(
    "gates_twin",
    select(gate.c.gate_id)
    .where(gate.c.flag == bindparam("f"))
    .order_by(gate.c.gate_id)
    .with_for_update(),
)
_LINK_FK = next(iter(link.foreign_key_constraints))
FK_LINK = FkBinding(_LINK_FK, (KeyBind(link.c.gate_id, "m"),), LOCK)
FK_LINK_TWIN = FkBinding(_LINK_FK, (KeyBind(link.c.gate_id, "m"),), LOCK_TWIN)
INS_LINK = WriteStep(
    name="ins_link",
    statement=insert(link)
    .values(link_id=bindparam("link"), gate_id=bindparam("m"))
    .returning(link.c.link_id),
    cardinality=PerEvidenceRow(LOCK, FK_LINK),
    fks=(FK_LINK,),
    value_binds=frozenset({"link"}),
)
INS_AUDIT = WriteStep(
    name="ins_audit",
    statement=insert(audit)
    .values(record_id=bindparam("rec"), note=bindparam("note"))
    .returning(audit.c.audit_id),
    cardinality=PerConfirmedRow(INS_LINK, "rec"),
    value_binds=frozenset({"rec", "note"}),
)
DECLARATION = PreWriteDeclaration(locks=(LOCK, LOCK_TWIN), steps=(INS_LINK, INS_AUDIT))

_OPEN: list[Connection] = []


@pytest.fixture
def ev(w: World) -> Iterator[World]:
    """Scratch tables. `gate` holds the evidence rows: flag `three`: three rows, `one`: one row, `none`: none."""
    admin = w.engine.execution_options(isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE"))
        connection.execute(text(f"CREATE SCHEMA {SCHEMA}"))
        connection.execute(
            text(f"CREATE TABLE {SCHEMA}.gate (gate_id uuid PRIMARY KEY, flag text NOT NULL)")
        )
        connection.execute(
            text(
                f"CREATE TABLE {SCHEMA}.link (link_id uuid PRIMARY KEY, "
                f"gate_id uuid NOT NULL REFERENCES {SCHEMA}.gate (gate_id))"
            )
        )
        connection.execute(
            text(
                f"CREATE TABLE {SCHEMA}.audit (audit_id int GENERATED ALWAYS AS IDENTITY PRIMARY KEY, "
                "record_id uuid NOT NULL, note text NOT NULL)"
            )
        )
        for flag in ("three", "three", "three", "one"):
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

    def inserts_since(self, mark: int, table: str = "link") -> int:
        return sum(1 for s in self.seen[mark:] if s.startswith(f"INSERT INTO {SCHEMA}.{table}"))


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
    engine: Engine, w: World, declaration: PreWriteDeclaration = DECLARATION
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


def count(engine: Engine, table: str) -> int:
    with engine.connect() as connection:
        return int(connection.execute(text(f"SELECT count(*) FROM {SCHEMA}.{table}")).scalar_one())


def gate_ids(engine: Engine, flag: str) -> list[uuid.UUID]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(f"SELECT gate_id FROM {SCHEMA}.gate WHERE flag = :f ORDER BY gate_id"), {"f": flag}
        )
        return [row[0] for row in rows]


def commit_refused(connection: Connection) -> None:
    with pytest.raises(AuthorizationPlanNotFinalizedError):
        connection.commit()


def lock(connection: Connection, plan: AuthorizationPlan, flag: str, which: PreLock = LOCK) -> Any:
    return plan.lock(connection, which, {"f": flag})


def put_link(connection: Connection, plan: AuthorizationPlan, key: Any, link_id: Any = None) -> Any:
    link_id = link_id or uuid.uuid4()
    outcome = plan.execute(connection, INS_LINK, {"link": link_id, "m": key})
    return outcome.keys[0][0]


def put_audit(connection: Connection, plan: AuthorizationPlan, record: Any) -> Any:
    return plan.execute(connection, INS_AUDIT, {"rec": record, "note": "n"})


def all_links(connection: Connection, plan: AuthorizationPlan, flag: str = "three") -> list[Any]:
    keys = lock(connection, plan, flag)
    plan.finalize(connection)
    return [put_link(connection, plan, key[0]) for key in keys]


# =====================================================================================================
# I-1 PerEvidenceRow
# =====================================================================================================


def test_k_evidence_rows_owe_k_inserts_and_k_audits_and_commit(ev: World, one: Engine) -> None:
    """plan: the positive case. Three members locked, three links, three identity-bound audit rows."""
    connection, plan = begin(one, ev)
    links = all_links(connection, plan)
    for record in links:
        put_audit(connection, plan, record)
    connection.commit()
    assert count(ev.engine, "link") == 3 and count(ev.engine, "audit") == 3
    with ev.engine.connect() as c:
        recorded = {row[0] for row in c.execute(text(f"SELECT record_id FROM {SCHEMA}.audit"))}
    assert recorded == set(links)


def test_an_omitted_link_insert_is_refused_at_commit_and_nothing_persists(
    ev: World, one: Engine
) -> None:
    connection, plan = begin(one, ev)
    keys = lock(connection, plan, "three")
    plan.finalize(connection)
    links = [
        put_link(connection, plan, key[0]) for key in keys[:2]
    ]  # the third member's INSERT is omitted
    for record in links:
        put_audit(connection, plan, record)
    commit_refused(connection)
    assert plan.violation is R.INCOMPLETE
    connection.close()
    assert count(ev.engine, "link") == 0 and count(ev.engine, "audit") == 0


def test_a_repeated_carried_value_is_refused_before_the_driver_as_a_duplicate(
    ev: World, one: Engine
) -> None:
    connection, plan = begin(one, ev)
    keys = lock(connection, plan, "three")
    plan.finalize(connection)
    put_link(connection, plan, keys[0][0])
    mark = RECORDERS[one].mark()
    with pytest.raises(AuthorizationPlanViolationError):
        put_link(connection, plan, keys[0][0])
    assert RECORDERS[one].inserts_since(mark) == 0 and plan.violation is R.DUPLICATE_TARGET
    commit_refused(connection)
    connection.close()
    assert count(ev.engine, "link") == 0


def test_a_value_outside_the_evidence_is_refused_before_the_driver(ev: World, one: Engine) -> None:
    """plan: an eligible member that was never locked (the `one` row) cannot be inserted on `three`'s evidence."""
    connection, plan = begin(one, ev)
    lock(connection, plan, "three")
    plan.finalize(connection)
    outsider = gate_ids(ev.engine, "one")[0]
    mark = RECORDERS[one].mark()
    with pytest.raises(AuthorizationPlanViolationError):
        put_link(connection, plan, outsider)
    assert RECORDERS[one].inserts_since(mark) == 0 and plan.violation is R.FK_NOT_LOCKED
    commit_refused(connection)
    connection.close()


def test_a_lock_that_never_ran_permits_nothing_and_the_plan_cannot_complete(
    ev: World, one: Engine
) -> None:
    """plan: missing evidence is not empty evidence. The attempt is refused (`EVIDENCE`); and without any attempt the
    commit is refused as incomplete, because the step is not skippable."""
    connection, plan = begin(one, ev)
    plan.finalize(connection)
    mark = RECORDERS[one].mark()
    with pytest.raises(AuthorizationPlanViolationError):
        put_link(connection, plan, gate_ids(ev.engine, "three")[0])
    assert RECORDERS[one].inserts_since(mark) == 0 and plan.violation is R.EVIDENCE
    connection.close()

    connection, plan = begin(one, ev)
    plan.finalize(connection)
    commit_refused(connection)
    assert plan.violation is R.INCOMPLETE
    connection.close()


def test_a_lock_call_that_failed_latches_and_the_commit_is_refused(ev: World, one: Engine) -> None:
    """plan: a lock timeout on a row another transaction holds. The failed call records no evidence and latches."""
    holder = ev.engine.connect()
    _OPEN.append(holder)
    holder.begin()
    holder.execute(
        text(f"SELECT 1 FROM {SCHEMA}.gate WHERE gate_id = :g FOR UPDATE"),
        {"g": gate_ids(ev.engine, "three")[1]},
    )
    connection, plan = begin(one, ev)
    connection.execute(text("SET LOCAL lock_timeout = '300ms'"))
    with pytest.raises(Exception, match="lock timeout|LockNotAvailable|canceling statement"):
        lock(connection, plan, "three")
    # the first latched reason is the driver error hook's; `LOCK_FAILED` would follow and never overwrites it
    assert plan.violated and plan.violation in (R.EXECUTION_FAILED, R.LOCK_FAILED)
    assert plan.evidence(LOCK) == frozenset()
    with pytest.raises(AuthorizationPlanViolationError):
        plan.finalize(connection)
    commit_refused(connection)
    connection.close()
    holder.rollback()


def test_empty_evidence_owes_nothing_permits_nothing_and_commits(ev: World, one: Engine) -> None:
    """plan: the lock ran and found no member. The link and the audit steps are skippable; an attempt is refused."""
    connection, plan = begin(one, ev)
    assert lock(connection, plan, "none") == ()
    plan.finalize(connection)
    connection.commit()  # nothing owed
    connection.close()

    connection, plan = begin(one, ev)
    lock(connection, plan, "none")
    plan.finalize(connection)
    with pytest.raises(AuthorizationPlanViolationError):
        put_link(connection, plan, gate_ids(ev.engine, "three")[0])
    assert plan.violation is R.EVIDENCE
    commit_refused(connection)
    connection.close()
    assert count(ev.engine, "link") == 0


def test_evidence_from_several_calls_is_merged(ev: World, one: Engine) -> None:
    """plan: two lock calls of the same object. The union is the evidence: four links and four audits commit."""
    connection, plan = begin(one, ev)
    keys = lock(connection, plan, "three") + lock(connection, plan, "one")
    plan.finalize(connection)
    assert plan.evidence(LOCK) == frozenset(keys) and len(keys) == 4
    links = [put_link(connection, plan, key[0]) for key in keys]
    for record in links:
        put_audit(connection, plan, record)
    connection.commit()
    assert count(ev.engine, "link") == 4 and count(ev.engine, "audit") == 4


def test_a_lock_inside_a_rolled_back_savepoint_latches(ev: World, one: Engine) -> None:
    connection, plan = begin(one, ev)
    lock(connection, plan, "three")
    nested = connection.begin_nested()
    nested.rollback()
    assert plan.violation is R.SAVEPOINT_ROLLBACK
    with pytest.raises(AuthorizationPlanViolationError):
        plan.finalize(connection)
    commit_refused(connection)
    connection.close()


def test_evidence_of_another_lock_object_with_the_same_sql_does_not_count(
    ev: World, one: Engine
) -> None:
    """plan: the twin lock ran; the declared step names the other object. The attempt is refused (`EVIDENCE`)."""
    connection, plan = begin(one, ev)
    keys = lock(connection, plan, "three", LOCK_TWIN)
    plan.finalize(connection)
    mark = RECORDERS[one].mark()
    with pytest.raises(AuthorizationPlanViolationError):
        put_link(connection, plan, keys[0][0])
    assert RECORDERS[one].inserts_since(mark) == 0 and plan.violation is R.EVIDENCE
    connection.close()


def test_evidence_of_another_plan_or_transaction_does_not_count(ev: World, one: Engine) -> None:
    """plan: a lock run in an earlier transaction of the same pooled connection, and a lock run through a plan on
    another connection, are not this plan's evidence."""
    connection, plan = begin(one, ev)
    keys = lock(connection, plan, "three")
    connection.rollback()
    connection.close()

    connection, plan = begin(one, ev)  # the same pooled connection, a new transaction and plan
    plan.finalize(connection)
    with pytest.raises(AuthorizationPlanViolationError):
        put_link(connection, plan, keys[0][0])
    assert plan.violation is R.EVIDENCE
    connection.close()

    other = ev.engine.connect()
    _OPEN.append(other)
    other.begin()
    other_plan = AuthorizationPlan.begin(
        other,
        actor_user_id=ev.gm_user,
        campaign_id=ev.campaign_id,
        mode=PlanMode.PRE_WRITE,
        pre_write=DECLARATION,
    )
    lock(other, other_plan, "three")
    connection, plan = begin(one, ev)
    plan.finalize(connection)
    with pytest.raises(AuthorizationPlanViolationError):
        put_link(connection, plan, keys[0][0])
    assert plan.violation is R.EVIDENCE
    connection.close()
    other.rollback()
    assert count(ev.engine, "link") == 0


def test_a_lock_after_finalize_is_refused(ev: World, one: Engine) -> None:
    connection, plan = begin(one, ev)
    plan.finalize(connection)
    with pytest.raises(AuthorizationPlanStateError):
        lock(connection, plan, "three")
    assert plan.violation is R.LOCK_AFTER_FINALIZE
    commit_refused(connection)
    connection.close()


# =====================================================================================================
# I-2 PerConfirmedRow
# =====================================================================================================


def test_an_audit_naming_a_link_already_used_is_a_duplicate_target(ev: World, one: Engine) -> None:
    connection, plan = begin(one, ev)
    links = all_links(connection, plan)
    put_audit(connection, plan, links[0])
    mark = RECORDERS[one].mark()
    with pytest.raises(AuthorizationPlanViolationError):
        put_audit(connection, plan, links[0])
    assert RECORDERS[one].inserts_since(mark, "audit") == 0 and plan.violation is R.DUPLICATE_TARGET
    commit_refused(connection)
    connection.close()
    assert count(ev.engine, "audit") == 0


def test_an_audit_naming_an_unconfirmed_id_is_the_wrong_identity_refusal(
    ev: World, one: Engine
) -> None:
    """plan: a random id, and the id of a gate row (a real row that is not a confirmed link), are both refused."""
    connection, plan = begin(one, ev)
    all_links(connection, plan)
    mark = RECORDERS[one].mark()
    with pytest.raises(AuthorizationPlanViolationError):
        put_audit(connection, plan, uuid.uuid4())
    assert RECORDERS[one].inserts_since(mark, "audit") == 0 and plan.violation is R.EVIDENCE
    connection.close()

    connection, plan = begin(one, ev)
    all_links(connection, plan)
    with pytest.raises(AuthorizationPlanViolationError):
        put_audit(connection, plan, gate_ids(ev.engine, "one")[0])
    assert plan.violation is R.EVIDENCE
    connection.close()


def test_two_audits_naming_one_link_while_another_link_has_none_is_refused(
    ev: World, one: Engine
) -> None:
    """plan: the second audit for the same link is refused at admission; the remaining link has no audit, so the
    commit is refused as well (the latch already set)."""
    connection, plan = begin(one, ev)
    links = all_links(connection, plan)
    put_audit(connection, plan, links[0])
    with pytest.raises(AuthorizationPlanViolationError):
        put_audit(connection, plan, links[0])
    put_audit_second = None
    with contextlib.suppress(AuthorizationPlanViolationError):
        put_audit_second = put_audit(connection, plan, links[1])
    assert put_audit_second is None  # the latch refuses everything after it
    commit_refused(connection)
    connection.close()
    assert (
        count(ev.engine, "audit") == 0 and count(ev.engine, "link") == 0
    )  # the whole transaction rolled back


def test_an_omitted_audit_is_refused_at_commit(ev: World, one: Engine) -> None:
    connection, plan = begin(one, ev)
    links = all_links(connection, plan)
    for record in links[:2]:
        put_audit(connection, plan, record)  # the third link's audit is omitted
    commit_refused(connection)
    assert plan.violation is R.INCOMPLETE
    connection.close()
    assert count(ev.engine, "link") == 0 and count(ev.engine, "audit") == 0


def test_an_audit_before_any_link_is_refused_by_order_and_a_source_that_confirmed_nothing_permits_none(
    ev: World, one: Engine
) -> None:
    """plan: with no link attempted the earlier step is not skippable, so the audit is refused by order (a missing
    source lock therefore never reaches the `EVIDENCE` branch of the audit step); with *empty* evidence the link step
    is skippable and the audit step is reached and refused (`EVIDENCE`): the source confirmed nothing."""
    connection, plan = begin(one, ev)
    plan.finalize(connection)
    with pytest.raises(AuthorizationPlanViolationError):
        put_audit(connection, plan, uuid.uuid4())
    assert plan.violation is R.ORDER
    connection.close()

    connection, plan = begin(one, ev)
    lock(connection, plan, "three")
    plan.finalize(connection)
    with pytest.raises(AuthorizationPlanViolationError):
        put_audit(connection, plan, uuid.uuid4())
    assert plan.violation is R.ORDER  # evidence exists, no link attempted
    connection.close()

    connection, plan = begin(one, ev)
    lock(connection, plan, "none")
    plan.finalize(connection)
    with pytest.raises(AuthorizationPlanViolationError):
        put_audit(connection, plan, uuid.uuid4())
    assert plan.violation is R.EVIDENCE
    connection.close()


def test_a_link_after_an_audit_is_refused_by_order(ev: World, one: Engine) -> None:
    connection, plan = begin(one, ev)
    keys = lock(connection, plan, "three")
    plan.finalize(connection)
    first = put_link(connection, plan, keys[0][0])
    put_audit(connection, plan, first)
    with pytest.raises(AuthorizationPlanViolationError):
        put_link(connection, plan, keys[1][0])
    assert plan.violation is R.ORDER
    connection.close()


# =====================================================================================================
# declaration rejections (no database)
# =====================================================================================================


def _link_step(cardinality: Any, fks: tuple[FkBinding, ...] = (FK_LINK,)) -> WriteStep:
    return WriteStep(
        name="link_variant",
        statement=insert(link)
        .values(link_id=bindparam("link"), gate_id=bindparam("m"))
        .returning(link.c.link_id),
        cardinality=cardinality,
        fks=fks,
        value_binds=frozenset({"link"}),
    )


def _audit_step(cardinality: Any) -> WriteStep:
    return WriteStep(
        name="audit_variant",
        statement=insert(audit)
        .values(record_id=bindparam("rec"), note=bindparam("note"))
        .returning(audit.c.audit_id),
        cardinality=cardinality,
        value_binds=frozenset({"rec", "note"}),
    )


def test_per_evidence_row_has_no_count_only_form() -> None:
    with pytest.raises(TypeError):
        PerEvidenceRow(LOCK)  # type: ignore[call-arg]
    with pytest.raises(DeclarationError):
        PerEvidenceRow(LOCK, None)  # type: ignore[arg-type]


def test_via_must_be_one_of_the_steps_own_fk_bindings() -> None:
    twin = FkBinding(
        _LINK_FK, (KeyBind(link.c.gate_id, "m"),), LOCK
    )  # equal in content, another object
    with pytest.raises(DeclarationError, match="own FkBindings"):
        _link_step(PerEvidenceRow(LOCK, twin))


def test_via_must_be_bound_to_the_evidence_lock() -> None:
    with pytest.raises(DeclarationError, match="bound to the evidence lock"):
        _link_step(PerEvidenceRow(LOCK, FK_LINK_TWIN), fks=(FK_LINK_TWIN,))


def test_per_evidence_row_applies_to_an_insert_only() -> None:
    with pytest.raises(DeclarationError, match="INSERT only"):
        WriteStep(
            name="upd",
            statement=update(gate)
            .where(gate.c.gate_id == bindparam("g"))
            .values(flag=bindparam("new_flag"))
            .returning(gate.c.gate_id),
            cardinality=PerEvidenceRow(LOCK, FK_LINK),
            target=(KeyBind(gate.c.gate_id, "g"),),
            target_lock=LOCK,
            value_binds=frozenset({"new_flag"}),
        )


def test_the_evidence_lock_must_be_one_of_the_declarations_locks() -> None:
    with pytest.raises(DeclarationError, match="not in locks"):
        PreWriteDeclaration(locks=(LOCK_TWIN,), steps=(_link_step(PerEvidenceRow(LOCK, FK_LINK)),))


def test_per_confirmed_row_must_follow_an_earlier_per_evidence_row_step() -> None:
    with pytest.raises(DeclarationError, match="strictly earlier"):  # a later step
        PreWriteDeclaration(
            locks=(LOCK,),
            steps=(INS_AUDIT, INS_LINK),
        )
    with pytest.raises(
        DeclarationError, match="PerEvidenceRow INSERT"
    ):  # not a PerEvidenceRow step
        plain = WriteStep(
            name="plain",
            statement=insert(link)
            .values(link_id=bindparam("link"), gate_id=bindparam("m"))
            .returning(link.c.link_id),
            cardinality=Exactly(1),
            fks=(FK_LINK,),
            value_binds=frozenset({"link"}),
        )
        _audit_step(PerConfirmedRow(plain, "rec"))
    with pytest.raises(DeclarationError, match="PerEvidenceRow INSERT"):  # the receipt (an UPDATE)
        _audit_step(PerConfirmedRow(RECEIPT_STEP, "rec"))
    with pytest.raises(DeclarationError, match="PerEvidenceRow INSERT"):  # another PerConfirmedRow
        _audit_step(PerConfirmedRow(INS_AUDIT, "rec"))
    with pytest.raises(DeclarationError, match="not in this declaration|strictly earlier"):
        PreWriteDeclaration(
            locks=(LOCK,), steps=(INS_AUDIT,)
        )  # the source step is not declared at all


def test_per_confirmed_row_bind_must_be_a_value_bind_of_the_source_kind() -> None:
    with pytest.raises(
        DeclarationError, match="value binds"
    ):  # `note` is a value bind of kind text
        _audit_step(PerConfirmedRow(INS_LINK, "nonexistent"))
    with pytest.raises(DeclarationError, match="source key's kind"):
        _audit_step(PerConfirmedRow(INS_LINK, "note"))
    fk_step_binding = FkBinding(
        next(iter(audit_fk.foreign_key_constraints)), (KeyBind(audit_fk.c.record_id, "rec"),), None
    )
    with pytest.raises(DeclarationError, match="value binds"):  # an FK bind
        WriteStep(
            name="audit_fk_step",
            statement=insert(audit_fk)
            .values(record_id=bindparam("rec"))
            .returning(audit_fk.c.audit_id),
            cardinality=PerConfirmedRow(INS_LINK, "rec"),
            fks=(fk_step_binding,),
            value_binds=frozenset(),
        )


def test_per_confirmed_row_applies_to_an_insert_only() -> None:
    with pytest.raises(DeclarationError, match="INSERT only"):
        WriteStep(
            name="upd",
            statement=update(gate)
            .where(gate.c.gate_id == bindparam("g"))
            .values(flag=bindparam("new_flag"))
            .returning(gate.c.gate_id),
            cardinality=PerConfirmedRow(INS_LINK, "new_flag"),
            target=(KeyBind(gate.c.gate_id, "g"),),
            target_lock=LOCK,
            value_binds=frozenset({"new_flag"}),
        )


def test_the_existing_cardinalities_are_unchanged() -> None:
    """structure: the existing cardinality classes still carry their old fields (the new classes are additions)."""
    assert PerEvidence(LOCK).lock is LOCK
    assert EachLockedRow(complete=True).complete is True and Exactly(1).n == 1


# =====================================================================================================
# I-3 the GREATEST value form
# =====================================================================================================

timed = Table(
    "timed",
    _meta,
    Column("timed_id", Uuid, primary_key=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("closed_at", DateTime(timezone=True)),
    Column("maybe_at", DateTime(timezone=True)),
    Column("label", Text, nullable=False),
    schema=SCHEMA,
)
other_timed = Table(
    "other_timed",
    _meta,
    Column("other_id", Uuid, primary_key=True),
    Column("stamped_at", DateTime(timezone=True), nullable=False),
    schema=SCHEMA,
)
keyed_stamp = Table(
    "keyed_stamp",
    _meta,
    Column("stamp_id", Uuid, primary_key=True),
    Column(
        "stamp_at",
        DateTime(timezone=True),
        ForeignKey(f"{SCHEMA}.other_timed.stamped_at"),
        nullable=False,
    ),
    Column("closed_at", DateTime(timezone=True)),
    schema=SCHEMA,
)
TIMED_LOCK = PreLock(
    "timed",
    select(timed.c.timed_id)
    .where(timed.c.label == bindparam("label"))
    .order_by(timed.c.timed_id)
    .with_for_update(),
)


def _close(
    value: Any, table: Table = timed, set_column: str = "closed_at", lock: PreLock = TIMED_LOCK
) -> WriteStep:
    return WriteStep(
        name="close",
        statement=update(table)
        .where(table.c[next(iter(table.primary_key.columns)).key] == bindparam("t"))
        .values({set_column: value})
        .returning(*table.primary_key.columns),
        cardinality=EachLockedRow(complete=True),
        target=(KeyBind(next(iter(table.primary_key.columns)), "t"),),
        target_lock=lock,
    )


NOW = func.pg_catalog.clock_timestamp()


def test_the_greatest_form_is_accepted_and_renders_unqualified_with_a_qualified_time_function() -> (
    None
):
    step = _close(func.greatest(NOW, timed.c.created_at))
    rendered = str(step.statement.compile(dialect=postgresql.dialect()))
    assert "greatest(pg_catalog.clock_timestamp(), r01_s5e5_ev.timed.created_at)" in rendered
    assert "pg_catalog.greatest" not in rendered
    assert (
        timed.c.created_at in step.compared
    )  # the live catalogue verifies that it really is timestamptz


@pytest.mark.parametrize(
    ("name", "value", "table"),
    [
        ("reversed", func.greatest(timed.c.created_at, NOW), timed),
        ("literal", func.greatest(NOW, datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC)), timed),
        ("bind", func.greatest(NOW, bindparam("x")), timed),
        ("second function", func.greatest(NOW, func.pg_catalog.now()), timed),
        ("nested", func.greatest(NOW, func.greatest(NOW, timed.c.created_at)), timed),
        ("three arguments", func.greatest(NOW, timed.c.created_at, timed.c.maybe_at), timed),
        ("one argument", func.greatest(NOW), timed),
        ("another table's column", func.greatest(NOW, other_timed.c.stamped_at), timed),
        ("a nullable column", func.greatest(NOW, timed.c.maybe_at), timed),
        ("a non-datetime column", func.greatest(NOW, timed.c.label), timed),
        ("the same column as the set column", func.greatest(NOW, timed.c.closed_at), timed),
        ("a foreign-key column", func.greatest(NOW, keyed_stamp.c.stamp_at), keyed_stamp),
        ("a qualified greatest", func.pg_catalog.greatest(NOW, timed.c.created_at), timed),
        (
            "a non-time first function",
            func.greatest(func.pg_catalog.lower("x"), timed.c.created_at),
            timed,
        ),
    ],
)
def test_every_other_greatest_shape_is_rejected(name: str, value: Any, table: Table) -> None:
    with pytest.raises(DeclarationError):
        _close(value, table=table)


def test_the_greatest_form_is_rejected_in_an_insert_and_as_a_where_value() -> None:
    with pytest.raises(DeclarationError):
        WriteStep(
            name="ins",
            statement=insert(timed)
            .values(
                timed_id=bindparam("t"),
                created_at=func.greatest(NOW, timed.c.created_at),
                label=bindparam("label"),
            )
            .returning(timed.c.timed_id),
            cardinality=Exactly(1),
            value_binds=frozenset({"label"}),
        )
    with pytest.raises(DeclarationError):
        WriteStep(
            name="where",
            statement=update(timed)
            .where(timed.c.timed_id == bindparam("t"))
            .where(timed.c.created_at < func.greatest(NOW, timed.c.created_at))
            .values(closed_at=NOW)
            .returning(timed.c.timed_id),
            cardinality=EachLockedRow(complete=True),
            target=(KeyBind(timed.c.timed_id, "t"),),
            target_lock=TIMED_LOCK,
        )


def test_the_set_column_may_not_be_a_key_or_foreign_key_column() -> None:
    with pytest.raises(DeclarationError):
        _close(
            func.greatest(NOW, timed.c.created_at), set_column="created_at"
        )  # not the argument column itself
    with pytest.raises(DeclarationError):
        _close(
            func.greatest(NOW, keyed_stamp.c.closed_at), table=keyed_stamp, set_column="stamp_at"
        )


def test_a_declared_update_with_the_form_runs_and_writes_the_clamped_value(
    ev: World, one: Engine
) -> None:
    """database: the value is `greatest(clock_timestamp(), created_at)`. A past `created_at` yields the clock (a time
    after it); a **future** `created_at` (a labelled raw-SQL fixture, never an application path) yields exactly the
    stored value, so the constraint `closed_at >= created_at` still holds."""
    admin = ev.engine.execution_options(isolation_level="AUTOCOMMIT")
    future = datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=30)
    past = datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC)
    ids = {"past": uuid.uuid4(), "future": uuid.uuid4()}
    with admin.connect() as connection:
        connection.execute(
            text(
                f"CREATE TABLE {SCHEMA}.timed (timed_id uuid PRIMARY KEY, created_at timestamptz NOT NULL, "
                "closed_at timestamptz, maybe_at timestamptz, label text NOT NULL)"
            )
        )
        for key, stamp in (("past", past), ("future", future)):
            connection.execute(
                text(f"INSERT INTO {SCHEMA}.timed VALUES (:i, :c, NULL, NULL, 'close-me')"),
                {"i": ids[key], "c": stamp},
            )
    step = _close(func.greatest(NOW, timed.c.created_at))
    declaration = PreWriteDeclaration(locks=(TIMED_LOCK,), steps=(step,))
    connection, plan = begin(one, ev, declaration)
    keys = plan.lock(connection, TIMED_LOCK, {"label": "close-me"})
    plan.finalize(connection)
    before = datetime.datetime.now(datetime.UTC)
    for key in keys:
        plan.execute(connection, step, {"t": key[0]})
    connection.commit()
    connection.close()
    with ev.engine.connect() as c:
        rows = {
            row[0]: (row[1], row[2])
            for row in c.execute(
                text(f"SELECT timed_id, created_at, closed_at FROM {SCHEMA}.timed")
            )
        }
    assert rows[ids["future"]][1] == future  # clamped to the stored value
    assert rows[ids["past"]][1] >= before  # the clock
    assert all(closed >= created for created, closed in rows.values())
