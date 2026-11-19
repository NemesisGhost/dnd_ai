# ruff: noqa: S608, F811 - synthetic DDL/DML in a throwaway schema
"""R01 S1-C: the predicate type allowlist and the session operator check agree (plan 6.13).

A predicate (PreLock WHERE, UPDATE narrowing) may compare only built-in kinds, so every operator that
can run is one `_SESSION_SQL` covers. A composite-type column with a custom `=` is refused at
declaration; the positive control proves the operator really changes which rows a lock selects.
"""

import uuid
from typing import Any

import pytest
from sqlalchemy import Column, Table, bindparam, func, select, text, update
from sqlalchemy.types import UserDefinedType

from dnd_ai.domain.authorization_steps import (
    DeclarationError,
    EachLockedRow,
    KeyBind,
    PreLock,
    WriteStep,
)
from tests.r01_pre_write_evidence import Synthetic, new_id, synthetic  # noqa: F401

pytestmark = pytest.mark.database


class _Pair(UserDefinedType[Any]):
    cache_ok = True

    def get_col_spec(self, **_: Any) -> str:
        return "pair"


def _comp_table(s: Synthetic) -> Table:
    return Table(
        "comp",
        s.md,
        Column("comp_id", s.tables["target"].c.target_id.type, primary_key=True),
        Column("pr", _Pair()),
        Column("pr2", _Pair()),
        schema=s.schema,
    )


def _lock(table: Table, *where: Any) -> PreLock:
    return PreLock(
        "p",
        select(table.c[next(iter(table.primary_key.columns)).name]).where(*where).with_for_update(),
    )


def test_a_composite_type_with_a_custom_equality_changes_selection_and_is_refused(
    synthetic: Synthetic,
) -> None:
    s = synthetic
    s.run(f"CREATE TYPE {s.schema}.pair AS (x integer, y integer)")
    s.run(
        f"CREATE FUNCTION {s.schema}.pair_eq({s.schema}.pair, {s.schema}.pair) RETURNS boolean "
        "LANGUAGE sql IMMUTABLE AS 'SELECT true'"
    )
    s.run(
        f"CREATE OPERATOR {s.schema}.= (LEFTARG = {s.schema}.pair, RIGHTARG = {s.schema}.pair, "
        f"FUNCTION = {s.schema}.pair_eq)"
    )
    s.run(
        f"CREATE TABLE {s.schema}.comp (comp_id uuid PRIMARY KEY, pr {s.schema}.pair, "
        f"pr2 {s.schema}.pair)"
    )
    a, b = new_id(), new_id()
    s.run(
        f"INSERT INTO {s.schema}.comp VALUES (:a, ROW(1, 1)::{s.schema}.pair, ROW(1, 1)::{s.schema}.pair), "
        f"(:b, ROW(1, 2)::{s.schema}.pair, ROW(1, 1)::{s.schema}.pair)",
        a=a,
        b=b,
    )
    # positive control: with the operator visible first, `pr = pr2` selects both rows; the built-in
    # record equality selects one. The selection really depends on the custom operator.
    sql = f"SELECT comp_id FROM {s.schema}.comp WHERE pr = pr2 FOR UPDATE"
    with s.plain.connect() as c:
        assert {r[0] for r in c.execute(text(sql))} == {a}
        c.rollback()
    with s.plain.connect() as c:
        c.execute(text(f"SET LOCAL search_path = {s.schema}, pg_catalog"))
        assert {r[0] for r in c.execute(text(sql))} == {a, b}
        c.rollback()
    comp = _comp_table(s)
    # the declarations that reproduced the hole are all refused before anything can run
    for where in (
        comp.c.pr == comp.c.pr2,
        comp.c.pr != comp.c.pr2,
        comp.c.pr.is_not_distinct_from(comp.c.pr2),
        comp.c.pr.is_distinct_from(None),
    ):
        with pytest.raises(DeclarationError):
            _lock(comp, where)
    # as an UPDATE narrowing predicate
    comp_lock = PreLock(
        "k", select(comp.c.comp_id).where(comp.c.comp_id == bindparam("k")).with_for_update()
    )
    with pytest.raises(DeclarationError):
        WriteStep(
            name="u",
            statement=update(comp)
            .where(comp.c.comp_id == bindparam("k"), comp.c.pr == comp.c.pr2)
            .values(pr2=None)
            .returning(comp.c.comp_id),
            cardinality=EachLockedRow(complete=True),
            target=(KeyBind(comp.c.comp_id, "k"),),
            target_lock=comp_lock,
        )
    # IS NULL invokes no operator: still declarable on any column
    _lock(comp, comp.c.pr.is_(None))


def _tgt(s: Synthetic) -> Table:
    return s.tables["target"]


def test_the_supported_comparison_subset_is_accepted(synthetic: Synthetic) -> None:
    t = _tgt(synthetic)
    ok = [
        t.c.target_id == bindparam("k"),
        t.c.parent_id == t.c.target_id,  # uuid with uuid
        t.c.v >= 3,  # integer literal
        t.c.v < bindparam("n"),
        t.c.note == "x",
        t.c.label.is_(None),
        t.c.note.is_not(None),
        t.c.active.is_(True),
        t.c.active == False,  # noqa: E712 - SQLAlchemy renders `active = false`
        t.c.stamp < func.pg_catalog.now(),
        t.c.tags.is_(None),  # no operator runs
        t.c.meta.is_not(None),
    ]
    for where in ok:
        PreLock("ok", select(t.c.target_id).where(where).with_for_update())


@pytest.mark.parametrize(
    "build",
    [
        lambda t: t.c.tags == bindparam("x"),
        lambda t: t.c.meta == bindparam("x"),
        lambda t: t.c.rng == bindparam("x"),
        lambda t: t.c.v == "text",  # int column, str literal
        lambda t: t.c.note == 5,  # text column, int literal
        lambda t: t.c.target_id == "abc",  # uuid column, str literal
        lambda t: t.c.active == 1,  # bool column, int literal: bool is not int
        lambda t: t.c.v == t.c.note,  # int column with text column
        lambda t: t.c.parent_id == t.c.v,  # uuid column with int column
        lambda t: t.c.active == func.pg_catalog.now(),  # bool with a time function
        lambda t: t.c.v > func.pg_catalog.now(),
        lambda t: t.c.stamp == True,  # noqa: E712 - timestamptz column with TRUE
    ],
    ids=[
        "array",
        "jsonb",
        "range",
        "int_vs_str",
        "text_vs_int",
        "uuid_vs_str",
        "bool_vs_int",
        "int_vs_text_col",
        "uuid_vs_int_col",
        "bool_vs_time",
        "int_vs_time",
        "stamp_vs_true",
    ],
)
def test_unsupported_comparisons_are_refused_at_declaration(
    synthetic: Synthetic, build: Any
) -> None:
    t = _tgt(synthetic)
    with pytest.raises(DeclarationError):
        PreLock("bad", select(t.c.target_id).where(build(t)).with_for_update())


def test_update_narrowing_shares_the_allowlist(synthetic: Synthetic) -> None:
    t = _tgt(synthetic)
    lock = PreLock(
        "k", select(t.c.target_id).where(t.c.target_id == bindparam("k")).with_for_update()
    )

    def step(*narrow: Any) -> WriteStep:
        return WriteStep(
            name="u",
            statement=update(t)
            .where(t.c.target_id == bindparam("k"), *narrow)
            .values(v=bindparam("nv"))
            .returning(t.c.target_id),
            cardinality=EachLockedRow(complete=True),
            target=(KeyBind(t.c.target_id, "k"),),
            target_lock=lock,
            value_binds=frozenset({"nv"}),
        )

    step(t.c.active.is_(True))
    step(t.c.note.is_(None), t.c.stamp < func.pg_catalog.now())
    for bad in (
        t.c.tags == bindparam("x"),
        t.c.active == func.pg_catalog.now(),
        t.c.stamp.is_(True),
    ):
        with pytest.raises(DeclarationError):
            step(bad)


@pytest.mark.parametrize(
    "type_name,left,right",
    [
        ("text", "text", "text"),
        ("boolean", "boolean", "boolean"),
        ("timestamptz", "timestamptz", "timestamptz"),
        ("date", "date", "date"),
        ("integer", "integer", "integer"),
        ("bigint", "bigint", "bigint"),
        ("integer", "integer", "bigint"),  # mixed widths
        ("varchar", "varchar", "text"),
    ],
)
def test_a_shadowing_operator_on_every_supported_type_refuses_the_session(
    synthetic: Synthetic, type_name: str, left: str, right: str
) -> None:
    """The session check covers each built-in type the allowlist admits (positive control: the
    operator exists and the session check query reports it; without it the query is clean)."""
    from dnd_ai.domain.authorization import _SESSION_SQL

    s = synthetic
    with s.admin.connect() as c:
        assert c.execute(_SESSION_SQL).one()[2] is False

    # a user schema operator is in the catalogue for the duration of this test only
    name = f"f_{uuid.uuid4().hex[:8]}"
    s.run(
        f"CREATE FUNCTION {s.schema}.{name}({left}, {right}) RETURNS boolean LANGUAGE sql "
        "IMMUTABLE AS 'SELECT false'"
    )
    s.run(
        f"CREATE OPERATOR {s.schema}.= (LEFTARG = {left}, RIGHTARG = {right}, "
        f"FUNCTION = {s.schema}.{name})"
    )
    with s.admin.connect() as c:
        assert c.execute(_SESSION_SQL).one()[2] is True
    del type_name
