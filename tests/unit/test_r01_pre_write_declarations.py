"""R01 S1-C: construction-time checks of pre-write declarations and the frozen-value rules (plan 6.9.4,
6.10.4-6.10.5, 6.11.3, 6.11.5; PW-9, PW-27). No database."""

import datetime
import uuid
from typing import Any

import pytest
from sqlalchemy import (
    Boolean,
    Column,
    ForeignKeyConstraint,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    Sequence,
    Table,
    Text,
    Uuid,
    bindparam,
    delete,
    exists,
    func,
    insert,
    literal_column,
    select,
    text,
    update,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB, Range

from dnd_ai.domain.authorization_steps import (
    DeclarationError,
    EachLockedRow,
    Exactly,
    FkBinding,
    FunctionPin,
    KeyBind,
    Kind,
    Level,
    ParameterError,
    PreLock,
    PreWriteDeclaration,
    RowExpectation,
    Timing,
    TriggerPin,
    UniqueWait,
    WriteStep,
    freeze_value,
    matches_driver,
    matches_extracted,
    spec_for,
    thaw_value,
)

pytestmark = pytest.mark.unit


def build() -> dict[str, Table]:
    md = MetaData()
    parent = Table("parent", md, Column("parent_id", Uuid, primary_key=True), Column("name", Text))
    other = Table("other", md, Column("o_id", Uuid, primary_key=True), Column("v", Integer))
    child = Table(
        "child",
        md,
        Column("child_id", Uuid, primary_key=True),
        Column("parent_id", Uuid, nullable=False),
        Column("v", Integer, nullable=False),
        Column("flag", Boolean),
        Column("meta", JSONB),
        Column("code", Text),
        ForeignKeyConstraint(["parent_id"], ["parent.parent_id"]),
    )
    return {"parent": parent, "other": other, "child": child}


def lock_for(table: Table, **kw: Any) -> PreLock:
    pk = table.primary_key.columns
    return PreLock(
        "lock",
        select(*pk).where(next(iter(pk)) == bindparam("k")).with_for_update(**kw),
    )


def good_update(t: dict[str, Table]) -> tuple[WriteStep, PreLock]:
    child = t["child"]
    lock = lock_for(child)
    step = WriteStep(
        name="u",
        statement=update(child)
        .where(child.c.child_id == bindparam("k"))
        .values(v=bindparam("nv"))
        .returning(child.c.child_id),
        cardinality=EachLockedRow(complete=True),
        target=(KeyBind(child.c.child_id, "k"),),
        target_lock=lock,
        value_binds=frozenset({"nv"}),
    )
    return step, lock


def test_a_good_declaration_constructs() -> None:
    t = build()
    step, lock = good_update(t)
    decl = PreWriteDeclaration(locks=(lock,), steps=(step,))
    assert decl.index_of_step(step) == 0 and decl.has_lock(lock)
    assert step.specs["nv"].kind is Kind.INT and step.is_update


def _update_variants(t: dict[str, Table]) -> dict[str, Any]:
    child, other, parent = t["child"], t["other"], t["parent"]
    lock = lock_for(child)
    base: dict[str, Any] = {
        "cardinality": Exactly(1),
        "target": (KeyBind(child.c.child_id, "k"),),
        "target_lock": lock,
    }

    def upd(stmt: Any, **kw: Any) -> WriteStep:
        return WriteStep(name="x", statement=stmt, **{**base, **kw})

    pk_eq = child.c.child_id == bindparam("k")
    ret = child.c.child_id
    return {
        "delete": lambda: upd(delete(child).where(pk_eq).returning(ret), value_binds=frozenset()),
        "pg_insert_on_conflict": lambda: WriteStep(
            name="x",
            statement=postgresql.insert(child)
            .values(parent_id=bindparam("p"), v=1)
            .on_conflict_do_nothing()
            .returning(ret),
            cardinality=Exactly(1),
        ),
        "or_in_where": lambda: upd(
            update(child).where(pk_eq | (child.c.v == 1)).values(v=bindparam("nv")).returning(ret),
            value_binds=frozenset({"nv"}),
        ),
        "missing_pk_equality": lambda: upd(
            update(child)
            .where(child.c.v == bindparam("nv2"))
            .values(v=bindparam("nv"))
            .returning(ret),
            value_binds=frozenset({"nv", "nv2"}),
        ),
        "second_table": lambda: upd(
            update(child)
            .where(pk_eq, child.c.parent_id == parent.c.parent_id)
            .values(v=bindparam("nv"))
            .returning(ret),
            value_binds=frozenset({"nv"}),
        ),
        "returning_function": lambda: upd(
            update(child).where(pk_eq).values(v=bindparam("nv")).returning(func.count()),
            value_binds=frozenset({"nv"}),
        ),
        "returning_more_than_pk": lambda: upd(
            update(child).where(pk_eq).values(v=bindparam("nv")).returning(ret, child.c.v),
            value_binds=frozenset({"nv"}),
        ),
        "no_returning": lambda: upd(
            update(child).where(pk_eq).values(v=bindparam("nv")), value_binds=frozenset({"nv"})
        ),
        "prefix_with": lambda: upd(
            update(child)
            .where(pk_eq)
            .values(v=bindparam("nv"))
            .returning(ret)
            .prefix_with("/* x */"),
            value_binds=frozenset({"nv"}),
        ),
        "expanding_bind": lambda: upd(
            update(child)
            .where(pk_eq, child.c.v.in_(bindparam("vs", expanding=True)))
            .values(v=bindparam("nv"))
            .returning(ret),
            value_binds=frozenset({"nv", "vs"}),
        ),
        "set_pk_column": lambda: upd(
            update(child).where(pk_eq).values(child_id=bindparam("nv")).returning(ret),
            value_binds=frozenset({"nv"}),
        ),
        "select_value": lambda: upd(
            update(child).where(pk_eq).values(v=select(other.c.v).scalar_subquery()).returning(ret),
            value_binds=frozenset(),
        ),
        "unqualified_now": lambda: upd(
            update(child).where(pk_eq).values(code=func.now()).returning(ret),
            value_binds=frozenset(),
        ),
        "user_function": lambda: upd(
            update(child).where(pk_eq).values(code=func.upper("x")).returning(ret),
            value_binds=frozenset(),
        ),
        "cast_value": lambda: upd(
            update(child).where(pk_eq).values(v=bindparam("nv").cast(Integer)).returning(ret),
            value_binds=frozenset({"nv"}),
        ),
        "textual_value": lambda: upd(
            update(child).where(pk_eq).values(v=literal_column("1")).returning(ret),
            value_binds=frozenset(),
        ),
        "bind_named_like_a_column": lambda: upd(
            update(child).where(pk_eq).values(v=bindparam("code")).returning(ret),
            value_binds=frozenset({"code"}),
        ),
        "wrong_value_binds": lambda: upd(
            update(child).where(pk_eq).values(v=bindparam("nv")).returning(ret),
            value_binds=frozenset(),
        ),
        "embedded_literal_on_key": lambda: upd(
            update(child)
            .where(child.c.child_id == uuid.uuid4())
            .values(v=bindparam("nv"))
            .returning(ret),
            value_binds=frozenset({"nv"}),
        ),
        "repeated_bind_name": lambda: upd(
            update(child)
            .where(pk_eq, child.c.v > bindparam("nv"))
            .values(v=bindparam("nv"))
            .returning(ret),
            value_binds=frozenset({"nv"}),
        ),
        "reading_target_lock_share": lambda: upd(
            update(child).where(pk_eq).values(v=bindparam("nv")).returning(ret),
            value_binds=frozenset({"nv"}),
            target_lock=lock_for(child, read=True),
        ),
        "zero_or_one_exactly": lambda: upd(
            update(child).where(pk_eq).values(v=bindparam("nv")).returning(ret),
            value_binds=frozenset({"nv"}),
            rows=RowExpectation.ZERO_OR_ONE,
        ),
        "insert_identity_supplied_default": lambda: WriteStep(
            name="x",
            statement=insert(child).values(parent_id=bindparam("p")).returning(ret),
            cardinality=Exactly(1),
            value_binds=frozenset({"p"}),
        ),
    }


@pytest.mark.parametrize("case", sorted(_update_variants(build())))
def test_construction_rejections(case: str) -> None:
    factory = _update_variants(build())[case]
    with pytest.raises(ValueError):
        factory()


def test_sqlalchemy_side_defaults_and_sequences_are_rejected() -> None:
    md = MetaData()
    t = Table(
        "d",
        md,
        Column("d_id", Uuid, primary_key=True),
        Column("v", Integer, default=3),
        Column("w", Integer, Sequence("s")),
    )
    with pytest.raises(DeclarationError):
        WriteStep(
            name="x",
            statement=insert(t).values(d_id=bindparam("i")).returning(t.c.d_id),
            cardinality=Exactly(1),
            value_binds=frozenset({"i"}),
        )


def test_text_and_typedecorator_keys_and_unsupported_types_are_rejected() -> None:
    from sqlalchemy import Numeric, TypeDecorator

    class Dec(TypeDecorator[int]):
        impl = Integer
        cache_ok = True

    md = MetaData()
    for column_type in (Text(), Dec(), Numeric(), Uuid(as_uuid=False)):
        t = Table(
            f"t{id(column_type)}", md, Column("k", column_type, primary_key=True, nullable=False)
        )
        with pytest.raises(DeclarationError):
            PreLock("l", select(t.c.k).where(t.c.k == bindparam("x")).with_for_update())


@pytest.mark.parametrize(
    "build_lock",
    [
        lambda c: select(c.c.child_id).where(c.c.child_id == bindparam("k")),
        lambda c: (
            select(c.c.child_id)
            .where(c.c.child_id == bindparam("k"))
            .with_for_update(skip_locked=True)
        ),
        lambda c: (
            select(c.c.child_id).where(c.c.child_id == bindparam("k")).limit(1).with_for_update()
        ),
        lambda c: (
            select(c.c.child_id).where(c.c.child_id == bindparam("k")).distinct().with_for_update()
        ),
        lambda c: (
            select(c.c.child_id).where(func.pg_advisory_xact_lock(1).is_(None)).with_for_update()
        ),  # noqa: E711
        lambda c: select(c.c.child_id).where(c.c.v == func.now()).with_for_update(),
        lambda c: (
            select(c.c.child_id).where(c.c.v == select(c.c.v).scalar_subquery()).with_for_update()
        ),
        lambda c: select(c.c.child_id).where(exists().where(c.c.v == 1)).with_for_update(),
        lambda c: (
            select(c.c.child_id).where(c.c.v == bindparam("k").cast(Integer)).with_for_update()
        ),
        lambda c: select(c.c.child_id).where(text("v = 1")).with_for_update(),
        lambda c: select(c.c.child_id).where(literal_column("v") == 1).with_for_update(),
        lambda c: select(c.c.child_id).where(c.c.v == build()["other"].c.v).with_for_update(),
        lambda c: (
            select(c.c.child_id).where(c.c.v.in_(bindparam("vs", expanding=True))).with_for_update()
        ),
        lambda c: select(c.c.child_id).where(c.c.code.like("x")).with_for_update(),
        lambda c: select(c.c.child_id, c.c.v).select_from(c).with_for_update(of=build()["other"]),
    ],
    ids=[
        "no_for",
        "skip_locked",
        "limit",
        "distinct",
        "advisory_function",
        "unqualified_now",
        "scalar_select",
        "exists",
        "cast",
        "textclause",
        "literal_column",
        "another_table",
        "expanding",
        "like",
        "of_another_table",
    ],
)
def test_prelock_predicate_allowlist_rejections(build_lock: Any) -> None:
    child = build()["child"]
    with pytest.raises(DeclarationError):
        PreLock("l", build_lock(child))


def test_prelock_allowed_forms_construct() -> None:
    c = build()["child"]
    for stmt in (
        select(c.c.child_id).where(c.c.child_id == bindparam("k")).with_for_update(),
        select(c.c.child_id)
        .where(c.c.parent_id == bindparam("p"))
        .order_by(c.c.child_id.desc())
        .with_for_update(key_share=True),
        select(c.c.child_id)
        .where((c.c.v > 1) & (c.c.flag.is_(True) | c.c.flag.is_(None)))
        .with_for_update(),
        select(c.c.child_id)
        .where(c.c.v == func.pg_catalog.now())
        .with_for_update(read=True, nowait=True),
        select(c.c.child_id).where(~(c.c.v == bindparam("x"))).with_for_update(of=c),
    ):
        PreLock("ok", stmt)


def test_a_deferrable_primary_key_is_rejected_at_construction() -> None:
    md = MetaData()
    t = Table(
        "dk",
        md,
        Column("k", Uuid, nullable=False),
        Column("v", Integer),
        PrimaryKeyConstraint("k", deferrable=True, initially="DEFERRED"),
    )
    with pytest.raises(DeclarationError, match="deferrable primary key"):
        PreLock("l", select(t.c.k).where(t.c.k == bindparam("x")).with_for_update())


def test_a_nullable_prelock_key_column_is_rejected() -> None:
    md = MetaData()
    t = Table("nk", md, Column("k", Uuid), Column("v", Integer))
    with pytest.raises(DeclarationError, match="NOT NULL"):
        PreLock("l", select(t.c.k).where(t.c.v == bindparam("x")).with_for_update())


def test_declaration_level_rules() -> None:
    t = build()
    step, lock = good_update(t)
    with pytest.raises(DeclarationError, match="not in locks"):
        PreWriteDeclaration(locks=(), steps=(step,))
    with pytest.raises(DeclarationError):
        PreWriteDeclaration(locks=(lock,), steps=(step, step))
    with pytest.raises(DeclarationError):
        PreWriteDeclaration(locks=(lock,), steps=())
    child = t["child"]
    constraint = next(iter(child.foreign_key_constraints))
    parent_lock = lock_for(t["parent"], read=True)
    ins = WriteStep(
        name="i",
        statement=insert(child)
        .values(child_id=bindparam("cid"), parent_id=bindparam("p"), v=1)
        .returning(child.c.child_id),
        cardinality=Exactly(1),
        fks=(FkBinding(constraint, (KeyBind(child.c.parent_id, "p"),), None),),
        value_binds=frozenset({"cid"}),
    )
    with pytest.raises(DeclarationError, match="unlocked"):
        PreWriteDeclaration(locks=(), steps=(ins,))
    PreWriteDeclaration(locks=(), steps=(ins,), unlocked_fk_targets=frozenset({t["parent"]}))
    assert parent_lock.mode.value == "share"


def test_a_trigger_pin_with_a_security_definer_function_is_rejected() -> None:
    from dataclasses import replace

    pin_function = FunctionPin("s", "f", "", "plpgsql", False, None, "v", "abc")
    pin = TriggerPin(
        "t",
        Timing.BEFORE,
        Level.ROW,
        frozenset(),
        None,
        None,
        "O",
        False,
        False,
        False,
        (),
        pin_function,
    )
    assert pin.function.security_definer is False
    with pytest.raises(DeclarationError, match="SECURITY DEFINER"):
        replace(pin, function=replace(pin_function, security_definer=True))
    assert UniqueWait("s.i", "t")


# --- frozen values ------------------------------------------------------------------------------


class Zone(datetime.tzinfo):
    def __init__(self, hours: int) -> None:
        self.hours = hours

    def utcoffset(self, dt: datetime.datetime | None) -> datetime.timedelta:
        return datetime.timedelta(hours=self.hours)

    def dst(self, dt: datetime.datetime | None) -> datetime.timedelta:
        return datetime.timedelta(0)


def spec(name: str, column: Column[Any]) -> Any:
    Table("t", MetaData(), column)
    return spec_for(name, column)


def test_timestamps_are_normalised_to_utc_and_keep_no_caller_tzinfo() -> None:
    from sqlalchemy import DateTime

    s = spec("ts", Column("ts", DateTime(timezone=True)))
    zone = Zone(2)
    frozen = freeze_value(s, datetime.datetime(2026, 1, 1, 12, 0, tzinfo=zone))
    zone.hours = 9  # mutated after validation
    assert frozen == datetime.datetime(2026, 1, 1, 10, 0, tzinfo=datetime.UTC)
    assert frozen.tzinfo is datetime.UTC and frozen.utcoffset() == datetime.timedelta(0)
    assert thaw_value(s, frozen) is frozen
    assert matches_extracted(s, frozen, frozen) and matches_driver(s, frozen, frozen)
    # an equal instant with a caller tzinfo does not match the driver/extracted form
    assert not matches_driver(s, frozen, datetime.datetime(2026, 1, 1, 12, 0, tzinfo=Zone(2)))
    for bad in (datetime.datetime(2026, 1, 1), "2026-01-01", datetime.date(2026, 1, 1)):
        with pytest.raises(ParameterError):
            freeze_value(s, bad)

    class Sub(datetime.datetime):
        pass

    with pytest.raises(ParameterError):
        freeze_value(s, Sub(2026, 1, 1, tzinfo=datetime.UTC))
    with pytest.raises(ParameterError):  # outside the representable range after normalisation
        freeze_value(s, datetime.datetime.min.replace(tzinfo=Zone(5)))


def test_json_arrays_ranges_and_exact_types_freeze_and_thaw() -> None:
    from sqlalchemy import ARRAY
    from sqlalchemy.dialects.postgresql import INT8RANGE

    j = spec("j", Column("j", JSONB))
    value = {"b": [1, {"c": None}], "a": "x"}
    frozen = freeze_value(j, value)
    assert isinstance(frozen, str)
    value["a"] = "changed"
    assert thaw_value(j, frozen) == {"a": "x", "b": [1, {"c": None}]}
    assert thaw_value(j, frozen) is not thaw_value(j, frozen)  # a new tree every time
    assert matches_extracted(j, frozen, {"a": "x", "b": [1, {"c": None}]})
    assert not matches_extracted(j, frozen, {"a": "y", "b": [1, {"c": None}]})
    for bad in ({1: 2}, float("nan"), {"a": object()}, [[[]] * 1] * 0 or {"a": {1, 2}}):
        with pytest.raises(ParameterError):
            freeze_value(j, bad)
    deep: Any = []
    for _ in range(70):
        deep = [deep]
    with pytest.raises(ParameterError):
        freeze_value(j, deep)

    a = spec("a", Column("a", ARRAY(Text)))
    items = ["x", None]
    frozen_a = freeze_value(a, items)
    items.append("y")
    assert frozen_a == ("x", None) and thaw_value(a, frozen_a) == ["x", None]
    with pytest.raises(ParameterError):
        freeze_value(a, ["x", 1])

    r = spec("r", Column("r", INT8RANGE))
    frozen_r = freeze_value(r, Range(1, 5))
    assert thaw_value(r, frozen_r) == Range(1, 5) and matches_extracted(r, frozen_r, Range(1, 5))
    with pytest.raises(ParameterError):
        freeze_value(r, Range("a", "b"))  # type: ignore[arg-type]

    i = spec("i", Column("i", Integer))
    assert freeze_value(i, 5) == 5
    for bad in (True, 2**31, "5", 5.0):
        with pytest.raises(ParameterError):
            freeze_value(i, bad)
    u = spec("u", Column("u", Uuid, nullable=False))
    with pytest.raises(ParameterError):
        freeze_value(u, str(uuid.uuid4()))
    with pytest.raises(ParameterError):
        freeze_value(u, None)
    b = spec("b", Column("b", Boolean))
    assert freeze_value(b, None) is None
    with pytest.raises(ParameterError):
        freeze_value(b, 1)
    assert Kind.UUID is u.kind
