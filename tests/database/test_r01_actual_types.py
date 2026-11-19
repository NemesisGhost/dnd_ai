# ruff: noqa: S608, F811 - synthetic DDL/DML in a throwaway schema; fixtures are pytest-injected
"""R01 S1-C: the type boundary of predicates (plan 6.14).

Three separate safeguards, each tested on its own:

1. **Declaration (runtime, import time):** `kind_of` accepts exact SQLAlchemy classes only.
2. **Plan (runtime):** before lock evidence and before finalize, the plan checks that every compared
   column's actual PostgreSQL type is the one built-in type its declared class stands for. A domain,
   composite or mismatched type refuses the plan before the protected statement reaches the driver.
3. **Catalogue helper (test-side):** `check_declaration` reports the same mismatch. It is a safeguard
   for reviewers and CI, not a runtime refusal.
"""

import datetime
import uuid
from typing import Any

import pytest
from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Integer,
    SmallInteger,
    String,
    Table,
    Text,
    Uuid,
    bindparam,
    select,
    text,
    update,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import sqltypes

from dnd_ai.domain.authorization_steps import (
    DeclarationError,
    EachLockedRow,
    KeyBind,
    PreLock,
    PreWriteDeclaration,
    WriteStep,
)
from tests.database.test_authorization_pre_write import Observe, open_plan, pid
from tests.r01_pre_write_catalogue import check_declaration
from tests.r01_pre_write_evidence import Synthetic, new_id, synthetic  # noqa: F401

pytestmark = pytest.mark.database


# --- 1. exact declaration types -------------------------------------------------------------------


class _MyInt(Integer):
    pass


class _MyUuid(Uuid):
    pass


class _MyText(Text):
    pass


class _MyString(String):
    pass


class _MyBool(Boolean):
    pass


class _MyDate(Date):
    pass


class _MyStamp(DateTime):
    pass


def _one_column_table(column_type: Any) -> Table:
    from sqlalchemy import MetaData

    return Table(
        "t",
        MetaData(),
        Column("k", Uuid, primary_key=True),
        Column("c", column_type),
    )


@pytest.mark.parametrize(
    "column_type",
    [
        _MyInt(),
        _MyUuid(),
        _MyText(),
        _MyString(),
        _MyBool(),
        _MyDate(),
        _MyStamp(timezone=True),
        ARRAY(_MyText()),
    ],
    ids=["int", "uuid", "text", "string", "bool", "date", "datetime", "array_of_subclass"],
)
def test_a_subclassed_type_is_refused_in_every_predicate_position(column_type: Any) -> None:
    t = _one_column_table(column_type)
    # as a comparison against a literal (no bind, so only the allowlist can notice) ...
    literal: Any = {
        "int": 1,
    }.get("int")
    with pytest.raises(DeclarationError):
        PreLock("l", select(t.c.k).where(t.c.c == literal).with_for_update())
    # ... against a supplied bind, and as an UPDATE narrowing predicate
    with pytest.raises(DeclarationError):
        PreLock("l", select(t.c.k).where(t.c.c == bindparam("x")).with_for_update())
    lock = PreLock("k", select(t.c.k).where(t.c.k == bindparam("k")).with_for_update())
    with pytest.raises(DeclarationError):
        WriteStep(
            name="u",
            statement=update(t)
            .where(t.c.k == bindparam("k"), t.c.c == literal)
            .values(c=None)
            .returning(t.c.k),
            cardinality=EachLockedRow(complete=True),
            target=(KeyBind(t.c.k, "k"),),
            target_lock=lock,
        )


@pytest.mark.parametrize(
    "column_type,literal",
    [
        (Uuid(), None),
        (sqltypes.UUID(), None),
        (postgresql.UUID(), None),
        (SmallInteger(), 1),
        (Integer(), 1),
        (BigInteger(), 1),
        (Boolean(), True),
        (Text(), "x"),
        (sqltypes.TEXT(), "x"),
        (String(), "x"),
        (String(20), "x"),
        (sqltypes.VARCHAR(), "x"),
        (DateTime(timezone=True), None),
        (sqltypes.TIMESTAMP(timezone=True), None),
        (postgresql.TIMESTAMP(timezone=True), None),
        (Date(), None),
    ],
    ids=lambda v: type(v).__name__ if not isinstance(v, (int, str, bool, type(None))) else "",
)
def test_the_supported_exact_classes_are_still_accepted(column_type: Any, literal: Any) -> None:
    t = _one_column_table(column_type)
    PreLock("ok", select(t.c.k).where(t.c.c == bindparam("x")).with_for_update())
    if literal is not None:
        PreLock("ok", select(t.c.k).where(t.c.c == literal).with_for_update())
    PreLock("ok", select(t.c.k).where(t.c.c.is_(None)).with_for_update())


def test_timezone_naive_datetimes_stay_refused() -> None:
    t = _one_column_table(DateTime())
    with pytest.raises(DeclarationError):
        PreLock("l", select(t.c.k).where(t.c.c == bindparam("x")).with_for_update())


# --- 2. actual database types: runtime refusal ----------------------------------------------------


class _Dom:
    """A table whose columns are SQLAlchemy `Integer` but PostgreSQL domains over integer, with a
    custom `=` on the domain that is always true (so it changes lock selection)."""

    def __init__(self, s: Synthetic) -> None:
        self.s = s
        schema = s.schema
        s.run(f"CREATE DOMAIN {schema}.dint AS integer")
        s.run(
            f"CREATE FUNCTION {schema}.dint_eq({schema}.dint, {schema}.dint) RETURNS boolean "
            "LANGUAGE sql IMMUTABLE AS 'SELECT true'"
        )
        s.run(
            f"CREATE OPERATOR {schema}.= (LEFTARG = {schema}.dint, RIGHTARG = {schema}.dint, "
            f"FUNCTION = {schema}.dint_eq)"
        )
        s.run(
            f"CREATE TABLE {schema}.dom (dom_id uuid PRIMARY KEY, n {schema}.dint NOT NULL, "
            f"m {schema}.dint NOT NULL, plain_v integer NOT NULL DEFAULT 0)"
        )
        self.a, self.b = new_id(), new_id()
        s.run(
            f"INSERT INTO {schema}.dom (dom_id, n, m) VALUES (:a, 1, 1), (:b, 1, 2)",
            a=self.a,
            b=self.b,
        )
        self.table = Table(
            "dom",
            s.md,
            Column("dom_id", Uuid, primary_key=True),
            Column("n", Integer, nullable=False),
            Column("m", Integer, nullable=False),
            Column("plain_v", Integer, nullable=False),
            schema=schema,
        )
        t = self.table
        self.lock_pk = PreLock(
            "pk", select(t.c.dom_id).where(t.c.dom_id == bindparam("k")).with_for_update()
        )
        # a compared column that is neither a target nor an FK key
        self.lock_cmp = PreLock(
            "cmp", select(t.c.dom_id).where(t.c.n == t.c.m).with_for_update(key_share=True)
        )
        self.lock_plain = PreLock(
            "plain", select(t.c.dom_id).where(t.c.plain_v >= 0).with_for_update(key_share=True)
        )

    def step(self, *narrow: Any) -> WriteStep:
        t = self.table
        return WriteStep(
            name="u",
            statement=update(t)
            .where(t.c.dom_id == bindparam("k"), *narrow)
            .values(plain_v=bindparam("nv"))
            .returning(t.c.dom_id),
            cardinality=EachLockedRow(complete=False),
            target=(KeyBind(t.c.dom_id, "k"),),
            target_lock=self.lock_pk,
            value_binds=frozenset({"nv"}),
        )


def test_the_domain_operator_changes_selection_and_the_control_proves_it(
    synthetic: Synthetic,
) -> None:
    """The positive control for every test below: the same SQL selects one row by default and both
    rows once the domain's schema is on the search path."""
    s = synthetic
    dom = _Dom(s)
    sql = f"SELECT dom_id FROM {s.schema}.dom WHERE n = m FOR UPDATE"
    with s.plain.connect() as c:
        assert {r[0] for r in c.execute(text(sql))} == {dom.a}
        c.rollback()
    with s.plain.connect() as c:
        c.execute(text(f"SET LOCAL search_path = {s.schema}"))
        assert {r[0] for r in c.execute(text(sql))} == {dom.a, dom.b}
        c.rollback()


def _row_locks(s: Synthetic, backend: int) -> set[str]:
    return s.relation_modes(backend, "dom")


@pytest.mark.parametrize("where", ["cmp", "narrow"])
def test_ordinary_integer_metadata_over_a_domain_column_is_refused_before_the_protected_statement(
    synthetic: Synthetic, where: str
) -> None:
    s = synthetic
    dom = _Dom(s)
    t = dom.table
    # declarations construct: SQLAlchemy cannot know the database type
    if where == "cmp":
        declaration = PreWriteDeclaration(locks=(dom.lock_pk, dom.lock_cmp), steps=(dom.step(),))
        protected, params = dom.lock_cmp, {}
    else:
        declaration = PreWriteDeclaration(
            locks=(dom.lock_pk,),
            steps=(dom.step(t.c.n > 0),),  # narrowing on a domain column
        )
        protected, params = dom.lock_pk, {"k": dom.a}
    assert {c[1] for c in declaration.type_checks} >= ({"n", "m"} if where == "cmp" else {"n"})
    connection, plan = open_plan(s, declaration)
    try:
        backend = pid(connection)
        with Observe(s, connection) as o, pytest.raises(Exception) as caught:
            plan.lock(connection, protected, params)
        assert type(caught.value).__name__ == "AuthorizationPlanViolationError"
        assert plan.violation.name == "SESSION"
        # E-driver: exactly the session check and the actual-type check; the lock statement is the
        # third call and never happened
        assert o.driver() == 2
        # E-locks: no relation lock on the protected table was taken by this backend
        assert _row_locks(s, backend) == set()
        assert plan.evidence(protected) == frozenset()
    finally:
        import dnd_ai.api.deps as deps

        deps._discard(connection)


def test_every_actual_type_mismatch_refuses_the_plan_and_a_matching_type_passes(
    synthetic: Synthetic,
) -> None:
    s = synthetic
    cases = {
        "c_int": (Integer, "bigint"),
        "c_big": (BigInteger, "integer"),
        "c_small": (SmallInteger, "integer"),
        "c_text": (Text, "varchar"),
        "c_string": (String, "text"),
        "c_bool": (Boolean, "integer"),
        "c_date": (Date, "timestamptz"),
        "c_stamp": (DateTime(timezone=True), "timestamp"),
        "c_uuid": (Uuid, "text"),
    }
    matching = {
        "m_int": (Integer, "integer"),
        "m_big": (BigInteger, "bigint"),
        "m_small": (SmallInteger, "smallint"),
        "m_text": (Text, "text"),
        "m_string": (String, "varchar"),
        "m_varchar": (String(20), "varchar(20)"),
        "m_bool": (Boolean, "boolean"),
        "m_date": (Date, "date"),
        "m_stamp": (DateTime(timezone=True), "timestamptz"),
        "m_uuid": (Uuid, "uuid"),
    }
    every = {**cases, **matching}
    columns = ", ".join(f"{name} {pg}" for name, (_, pg) in every.items())
    s.run(f"CREATE TABLE {s.schema}.mm (mm_id uuid PRIMARY KEY, {columns})")
    table = Table(
        "mm",
        s.md,
        Column("mm_id", Uuid, primary_key=True),
        *(Column(name, typ) for name, (typ, _) in every.items()),
        schema=s.schema,
    )

    def literal_for(typ: Any) -> Any:
        typ = typ() if isinstance(typ, type) else typ
        return {
            Integer: 1,
            BigInteger: 1,
            SmallInteger: 1,
            Text: "x",
            String: "x",
            Boolean: True,
        }.get(type(typ))

    def declaration_for(name: str) -> PreWriteDeclaration:
        column = table.c[name]
        value = literal_for(every[name][0])
        predicate = column == value if value is not None else column == bindparam("x")
        lock = PreLock(
            f"l_{name}",
            select(table.c.mm_id).where(predicate).with_for_update(key_share=True),
        )
        key_lock = PreLock(
            f"k_{name}",
            select(table.c.mm_id).where(table.c.mm_id == bindparam("k")).with_for_update(),
        )
        step = WriteStep(
            name="u",
            statement=update(table)
            .where(table.c.mm_id == bindparam("k"))
            .values(m_int=bindparam("nv"))
            .returning(table.c.mm_id),
            cardinality=EachLockedRow(complete=False),
            target=(KeyBind(table.c.mm_id, "k"),),
            target_lock=key_lock,
            value_binds=frozenset({"nv"}),
        )
        decl = PreWriteDeclaration(locks=(key_lock, lock), steps=(step,))
        decl_lock[name] = lock
        return decl

    decl_lock: dict[str, PreLock] = {}
    for name in every:
        declaration = declaration_for(name)
        lock = decl_lock[name]
        params: dict[str, Any] = {}
        if lock.specs:
            only = next(iter(lock.specs))
            params[only] = (
                datetime.date(2020, 1, 1)
                if every[name][0] is Date
                else datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC)
                if every[name][0] is not Uuid
                else new_id()
            )
        connection, plan = open_plan(s, declaration)
        try:
            with Observe(s, connection) as o:
                if name in cases:
                    with pytest.raises(Exception) as caught:
                        plan.lock(connection, lock, params)
                    assert type(caught.value).__name__ == "AuthorizationPlanViolationError", name
                    assert plan.violation.name == "SESSION", name
                    assert o.driver() == 2, name
                else:
                    plan.lock(connection, lock, params)
                    assert o.driver() == 3, name  # session, actual types, the lock itself
        finally:
            import dnd_ai.api.deps as deps

            deps._discard(connection)
        # the catalogue helper reports the same mismatches, independently
        with s.plain.connect() as c:
            problems = [p for p in check_declaration(c, declaration) if "compared column" in p]
            c.rollback()
        assert bool(problems) is (name in cases), (name, problems)


# --- 3. catalogue helper (test-side) ---------------------------------------------------------------


def test_the_catalogue_helper_reports_a_domain_independently_of_the_runtime(
    synthetic: Synthetic,
) -> None:
    s = synthetic
    dom = _Dom(s)
    bad = PreWriteDeclaration(locks=(dom.lock_pk, dom.lock_cmp), steps=(dom.step(),))
    good = PreWriteDeclaration(locks=(dom.lock_pk, dom.lock_plain), steps=(dom.step(),))
    with s.plain.connect() as c:
        flagged = [p for p in check_declaration(c, bad) if "compared column" in p]
        assert any(".n " in p or ".n is" in p for p in flagged) and any(".m" in p for p in flagged)
        assert [p for p in check_declaration(c, good) if "compared column" in p] == []
        c.rollback()
    # the plain integer column on the same table passes the runtime check
    connection, plan = open_plan(s, good)
    try:
        keys = plan.lock(connection, dom.lock_plain, {})
        assert sorted(keys) == sorted([(dom.a,), (dom.b,)])
    finally:
        import dnd_ai.api.deps as deps

        deps._discard(connection)
    assert uuid.UUID(int=0)  # keep `uuid` imported for the fixtures' sake
