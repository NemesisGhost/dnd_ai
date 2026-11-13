"""R01 pre-write declarations (plan sections 6.9.3, 6.10.3-6.10.5, 6.11.3-6.11.6).

A pre-write command declares, as module-level constants, the SQLAlchemy Core statements it will run
after the authorization decision (`WriteStep`, `insert`/`update`) and the row locks it takes before it
(`PreLock`, `select ... FOR ... `). `AuthorizationPlan.execute` / `AuthorizationPlan.lock` run exactly those
objects. Every declaration is validated when it is constructed: an unsupported shape fails at import.

Supported (an allowlist over SQLAlchemy's expression tree, not a SQL parser):

- **Steps:** plain `insert` (one row, explicit `values`) and `update` (full primary-key equality plus
  column-versus-value narrowing conjuncts, `and_` only). `RETURNING` is mandatory and is exactly the
  table's primary-key columns: the API fetches and validates the returned keys itself.
- **Values:** a named bind, a literal, NULL, or one of the four `pg_catalog`-qualified time functions.
- **Bind values** have a freezing rule per column type (`freeze_value`). Anything else is refused.
- **Keys:** `uuid.UUID` or `int`. No deferrable primary key, no partial-NULL FK groups.
- **PreLocks:** a pure-expression predicate allowlist.

Nothing here proves that a statement cannot block; trigger callees, dynamic SQL, unique-index waits and
business-rule lock completeness remain S5 obligations (plan 6.11.6).
"""

import datetime
import enum
import json
import math
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Final, cast

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Insert,
    Integer,
    Select,
    SmallInteger,
    String,
    Table,
    Text,
    TypeDecorator,
    Update,
    Uuid,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import INT8RANGE, JSONB, Range
from sqlalchemy.schema import Index, UniqueConstraint
from sqlalchemy.sql import elements, functions, operators, sqltypes

#: Effective execution options a guarded statement must carry (plan 6.10.5). The application engine
#: shape has none (P-X1); a future engine default is added here as a reviewed change.
REVIEWED_EXECUTION_OPTIONS: Final[Mapping[str, object]] = MappingProxyType({})

_TIME_FUNCTIONS: Final = frozenset(
    {"now", "clock_timestamp", "statement_timestamp", "transaction_timestamp"}
)
_COMPARISONS: Final = frozenset(
    {
        operators.eq,
        operators.ne,
        operators.lt,
        operators.le,
        operators.gt,
        operators.ge,
        operators.is_,
        operators.is_not,
        operators.is_distinct_from,
        operators.is_not_distinct_from,
    }
)
_MAX_JSON_DEPTH: Final = 64


class DeclarationError(ValueError):
    """A declaration uses an unsupported shape. Raised at construction (import time)."""


class ParameterError(ValueError):
    """A caller-supplied bind value is outside the supported, frozen types."""


# -- kinds and frozen values ---------------------------------------------------------------------


class Kind(enum.Enum):
    UUID = "uuid"
    INT = "int"
    BOOL = "bool"
    TEXT = "text"
    DATETIME = "datetime"
    DATE = "date"
    TEXT_ARRAY = "text_array"
    JSONB = "jsonb"
    INT8RANGE = "int8range"


_INT_RANGES: Final = {
    SmallInteger: (-(2**15), 2**15 - 1),
    Integer: (-(2**31), 2**31 - 1),
    BigInteger: (-(2**63), 2**63 - 1),
}
_KEY_KINDS: Final = frozenset({Kind.UUID, Kind.INT})
#: The only column kinds a predicate may compare (PreLock WHERE and UPDATE narrowing). They map to the
#: built-in types whose comparison operators `_SESSION_SQL` proves are not shadowed: uuid,
#: int2/int4/int8, bool, text/varchar, timestamptz and date. Arrays, jsonb, ranges, enums,
#: composites, decorated and user-defined types are refused at declaration (plan 6.13).
_COMPARABLE_KINDS: Final = frozenset(
    {Kind.UUID, Kind.INT, Kind.BOOL, Kind.TEXT, Kind.DATETIME, Kind.DATE}
)
_LITERAL_KINDS: Final = {bool: Kind.BOOL, int: Kind.INT, str: Kind.TEXT, uuid.UUID: Kind.UUID}


@dataclass(frozen=True)
class BindSpec:
    """What a supplied bind accepts, derived from its column's type when the declaration is built."""

    name: str
    kind: Kind
    nullable: bool
    int_range: tuple[int, int] | None = None


#: The SQLAlchemy type classes a declared column may have, by EXACT class (never `isinstance`: a
#: subclass or wrapper could change the value or the operator the server sees), with the one
#: PostgreSQL type each stands for. `kind_of` rejects every other class.
_EXACT_TYPES: Final[Mapping[type, tuple[Kind, str]]] = MappingProxyType(
    {
        Uuid: (Kind.UUID, "uuid"),
        sqltypes.UUID: (Kind.UUID, "uuid"),
        Boolean: (Kind.BOOL, "bool"),
        SmallInteger: (Kind.INT, "int2"),
        Integer: (Kind.INT, "int4"),
        BigInteger: (Kind.INT, "int8"),
        Date: (Kind.DATE, "date"),
        Text: (Kind.TEXT, "text"),
        String: (Kind.TEXT, "varchar"),
        sqltypes.VARCHAR: (Kind.TEXT, "varchar"),
        sqltypes.TEXT: (Kind.TEXT, "text"),
        JSONB: (Kind.JSONB, "jsonb"),
        INT8RANGE: (Kind.INT8RANGE, "int8range"),
    }
)
_EXACT_DATETIME: Final = frozenset({DateTime, sqltypes.TIMESTAMP, postgresql.TIMESTAMP})
_EXACT_INTS: Final = {SmallInteger: "int2", Integer: "int4", BigInteger: "int8"}


def kind_and_pg_type(column: Column[Any]) -> tuple[Kind, tuple[int, int] | None, str]:
    """The supported kind, integer range and the single PostgreSQL type of `column`'s declared type,
    or `DeclarationError`. Only the exact classes of `_EXACT_TYPES` (and a timezone-aware DateTime or
    TIMESTAMP, or ARRAY(Text)) are accepted: subclasses, `TypeDecorator`s and every other class are
    refused."""
    column_type: Any = column.type
    cls = type(column_type)
    if isinstance(column_type, TypeDecorator):
        raise DeclarationError(f"{column}: a TypeDecorator column is not supported")
    if cls in _EXACT_DATETIME:
        if not column_type.timezone:
            raise DeclarationError(f"{column}: only DateTime(timezone=True) is supported")
        return Kind.DATETIME, None, "timestamptz"
    if cls is ARRAY or cls is postgresql.ARRAY:
        if type(column_type.item_type) not in (Text, sqltypes.TEXT):
            raise DeclarationError(f"{column}: only ARRAY(Text) is supported")
        return Kind.TEXT_ARRAY, None, "_text"
    entry = _EXACT_TYPES.get(cls)
    if entry is None:
        raise DeclarationError(f"{column}: column type {column_type!r} is not supported")
    kind, pg_type = entry
    if kind is Kind.UUID and not (column_type.as_uuid and column_type.native_uuid):
        raise DeclarationError(
            f"{column}: only a native Uuid(as_uuid=True) is supported (native_uuid=False is CHAR(32))"
        )
    return kind, (_INT_RANGES[cls] if cls in _EXACT_INTS else None), pg_type


def kind_of(column: Column[Any]) -> tuple[Kind, tuple[int, int] | None]:
    kind, int_range, _ = kind_and_pg_type(column)
    return kind, int_range


def spec_for(name: str, column: Column[Any]) -> BindSpec:
    kind, int_range = kind_of(column)
    return BindSpec(name, kind, bool(column.nullable), int_range)


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def _check_json(value: Any, depth: int = 0) -> None:
    if depth > _MAX_JSON_DEPTH:
        raise ParameterError("a JSON value is nested too deeply")
    t = type(value)
    if value is None or t in (str, bool, int):
        return
    if t is float:
        if not math.isfinite(value):
            raise ParameterError("a JSON number must be finite")
        return
    if t is list:
        for item in value:
            _check_json(item, depth + 1)
        return
    if t is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise ParameterError("a JSON object key must be a string")
            _check_json(item, depth + 1)
        return
    raise ParameterError("a JSON value of an unsupported type")


def freeze_value(spec: BindSpec, value: Any) -> Any:
    """Validate `value` for `spec` and return its immutable form. Types are checked with `type(v) is
    T`, never `isinstance` (a subclass could change equality or processing). Raises `ParameterError`."""
    if value is None:
        if not spec.nullable:
            raise ParameterError(f"{spec.name}: NULL for a NOT NULL column")
        return None
    kind = spec.kind
    t = type(value)
    if kind is Kind.UUID:
        if t is not uuid.UUID:
            raise ParameterError(f"{spec.name}: a uuid.UUID is required")
        return value
    if kind is Kind.INT:
        if t is not int:
            raise ParameterError(f"{spec.name}: an int is required")
        assert spec.int_range is not None
        if not spec.int_range[0] <= value <= spec.int_range[1]:
            raise ParameterError(f"{spec.name}: an int outside the column's range")
        return value
    if kind is Kind.BOOL:
        if t is not bool:
            raise ParameterError(f"{spec.name}: a bool is required")
        return value
    if kind is Kind.TEXT:
        if t is not str:
            raise ParameterError(f"{spec.name}: a str is required")
        return value
    if kind is Kind.DATETIME:
        if t is not datetime.datetime:
            raise ParameterError(f"{spec.name}: a datetime is required")
        # One call to the caller's tzinfo, then a stable UTC value with the immutable
        # `datetime.timezone.utc`: no caller-owned (mutable) tzinfo object is retained.
        offset = value.utcoffset()
        if offset is None:
            raise ParameterError(f"{spec.name}: a timezone-aware datetime is required")
        try:
            naive = value.replace(tzinfo=None) - offset
        except OverflowError as exc:
            raise ParameterError(f"{spec.name}: a datetime outside the supported range") from exc
        return naive.replace(tzinfo=datetime.UTC)
    if kind is Kind.DATE:
        if t is not datetime.date:
            raise ParameterError(f"{spec.name}: a date is required")
        return value
    if kind is Kind.TEXT_ARRAY:
        if t not in (list, tuple):
            raise ParameterError(f"{spec.name}: a list or tuple of str is required")
        items = tuple(value)
        if any(item is not None and type(item) is not str for item in items):
            raise ParameterError(f"{spec.name}: array elements must be str or None")
        return items
    if kind is Kind.JSONB:
        _check_json(value)
        return _canonical_json(value)
    if kind is Kind.INT8RANGE:
        if t is not Range:
            raise ParameterError(f"{spec.name}: a Range is required")
        lower, upper = value.lower, value.upper
        for bound in (lower, upper):
            if bound is not None and type(bound) is not int:
                raise ParameterError(f"{spec.name}: range bounds must be int or None")
        bounds = value.bounds
        if bounds is not None and bounds not in ("[)", "(]", "()", "[]"):
            raise ParameterError(f"{spec.name}: unsupported range bounds")
        return (lower, upper, bounds, bool(value.empty))
    raise ParameterError(f"{spec.name}: unsupported kind")  # pragma: no cover


def thaw_value(spec: BindSpec, frozen: Any) -> Any:
    """A fresh, mutable-where-needed object for SQLAlchemy, built from the frozen form."""
    if frozen is None:
        return None
    kind = spec.kind
    if kind is Kind.TEXT_ARRAY:
        return list(frozen)
    if kind is Kind.JSONB:
        return json.loads(frozen)
    if kind is Kind.INT8RANGE:
        lower, upper, bounds, empty = frozen
        if empty:
            return Range(empty=True)
        return Range(lower, upper, bounds=bounds or "[)")
    return frozen


def matches_extracted(spec: BindSpec, frozen: Any, value: Any) -> bool:
    """Whether `value` (as held in SQLAlchemy's parameters, before type processing) is the frozen
    value. Never raises."""
    try:
        if frozen is None or value is None:
            return frozen is None and value is None
        kind = spec.kind
        t = type(value)
        if kind in (Kind.UUID, Kind.INT, Kind.TEXT, Kind.DATE):
            return t is type(frozen) and value == frozen
        if kind is Kind.BOOL:
            return t is bool and value is frozen
        if kind is Kind.DATETIME:
            return t is datetime.datetime and value.tzinfo is datetime.UTC and value == frozen
        if kind is Kind.TEXT_ARRAY:
            return bool(
                t is list
                and tuple(value) == frozen
                and all(i is None or type(i) is str for i in value)
            )
        if kind is Kind.JSONB:
            _check_json(value)
            return bool(_canonical_json(value) == frozen)
        if kind is Kind.INT8RANGE:
            return (
                t is Range and (value.lower, value.upper, value.bounds, bool(value.empty)) == frozen
            )
    except Exception:
        return False
    return False  # type: ignore[unreachable]


def matches_driver(spec: BindSpec, frozen: Any, value: Any) -> bool:
    """Whether `value` (as handed to the DBAPI) is the frozen value in its driver form. Never raises."""
    try:
        if frozen is None or value is None:
            return frozen is None and value is None
        kind = spec.kind
        t = type(value)
        if kind is Kind.JSONB:
            from psycopg.types.json import Jsonb

            if t is not Jsonb:
                return False
            _check_json(value.obj)
            return bool(_canonical_json(value.obj) == frozen)
        if kind is Kind.INT8RANGE:
            from psycopg.types.range import Range as DriverRange

            if t is not DriverRange:
                return False
            lower, upper, bounds, empty = frozen
            if bool(value.isempty) != empty:
                return False
            if empty:
                return True
            return (value.lower, value.upper, value.bounds) == (lower, upper, bounds or "[)")
        return matches_extracted(spec, frozen, value)
    except Exception:
        return False


# -- cardinalities, expectations ------------------------------------------------------------------


@dataclass(frozen=True)
class Exactly:
    """`n` confirmed rows at COMMIT, at most `n` attempts."""

    n: int

    def __post_init__(self) -> None:
        if type(self.n) is not int or self.n < 1:
            raise DeclarationError("Exactly(n) needs an int n >= 1")


@dataclass(frozen=True)
class Between:
    low: int
    high: int

    def __post_init__(self) -> None:
        if (
            type(self.low) is not int
            or type(self.high) is not int
            or not 0 <= self.low <= self.high
            or self.high < 1
        ):
            raise DeclarationError("Between(low, high) needs 0 <= low <= high and high >= 1")


@dataclass(frozen=True)
class EachLockedRow:
    """At most one attempt per distinct key of `target_lock`'s evidence. With `complete=True`, every
    evidence key must be confirmed exactly once before COMMIT."""

    complete: bool


type Cardinality = Exactly | Between | EachLockedRow


class RowExpectation(enum.Enum):
    """`ONE`: exactly one returned key, the target's. `ZERO_OR_ONE`: zero is allowed, but a zero-row
    result is attempted and never confirmed."""

    ONE = "one"
    ZERO_OR_ONE = "zero_or_one"


class LockMode(enum.Enum):
    KEY_SHARE = "key_share"
    SHARE = "share"
    NO_KEY_UPDATE = "no_key_update"
    UPDATE = "update"


# -- catalogue pins (data only; the helper is test-side) -----------------------------------------


class Timing(enum.Enum):
    BEFORE = "before"
    AFTER = "after"


class Level(enum.Enum):
    ROW = "row"
    STATEMENT = "statement"


class Event(enum.Enum):
    INSERT = "insert"
    UPDATE = "update"
    DELETE = "delete"
    TRUNCATE = "truncate"


@dataclass(frozen=True)
class FunctionPin:
    schema: str
    name: str
    arg_types: str
    language: str
    security_definer: bool
    config: tuple[str, ...] | None
    volatility: str
    source_md5: str


@dataclass(frozen=True)
class TriggerPin:
    name: str
    timing: Timing
    level: Level
    events: frozenset[Event]
    update_columns: tuple[str, ...] | None
    when_hash: str | None
    enabled: str
    constraint_trigger: bool
    deferrable: bool
    initially_deferred: bool
    args: tuple[str, ...]
    function: FunctionPin

    def __post_init__(self) -> None:
        if self.function.security_definer:
            raise DeclarationError("a SECURITY DEFINER trigger function is not supported")


@dataclass(frozen=True)
class UniqueWait:
    index: str
    competitor_test: str


# -- statement analysis ---------------------------------------------------------------------------

_CLEAN_ATTRIBUTES: Final = (
    "_prefixes",
    "_suffixes",
    "_hints",
    "_statement_hints",
    "_independent_ctes",
    "_execution_options",
    "_with_options",
    "_setup_joins",
    "_from_obj",
    "_correlate",
    "_group_by_clauses",
    "_having_criteria",
)


def _require_clean(statement: object, what: str) -> None:
    for attribute in _CLEAN_ATTRIBUTES:
        if getattr(statement, attribute, None):
            raise DeclarationError(f"{what}: {attribute} is not supported")
    if list(getattr(statement, "dialect_kwargs", ())):
        raise DeclarationError(f"{what}: dialect options are not supported")
    for attribute in ("_limit_clause", "_offset_clause", "_fetch_clause"):
        if getattr(statement, attribute, None) is not None:
            raise DeclarationError(f"{what}: LIMIT/OFFSET/FETCH is not supported")
    if getattr(statement, "_distinct", False) or getattr(statement, "_distinct_on", ()):
        raise DeclarationError(f"{what}: DISTINCT is not supported")


@dataclass
class _Collected:
    """What the walker saw: required (supplied) binds by name, and where each bind sits."""

    columns: dict[str, Column[Any]] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)
    literal_columns: set[Column[Any]] = field(default_factory=set)
    compared: set[Column[Any]] = field(default_factory=set)

    def add_supplied(self, bind: elements.BindParameter[Any], column: Column[Any]) -> None:
        name = bind.key
        self.counts[name] = self.counts.get(name, 0) + 1
        if name in self.columns and self.columns[name] is not column:
            raise DeclarationError(f"bind {name!r} is used for two columns")
        self.columns[name] = column


def _is_time_function(expr: object) -> bool:
    return (
        type(expr) is functions.Function
        and expr.packagenames == ("pg_catalog",)
        and expr.name in _TIME_FUNCTIONS
        and len(list(expr.clauses)) == 0
    )


_FROZEN_LITERAL_TYPES: Final = (int, str, bool, uuid.UUID, type(None))


def _check_bind(bind: elements.BindParameter[Any]) -> None:
    if bind.expanding or bind.literal_execute or bind.callable is not None:
        raise DeclarationError(
            f"bind {bind.key!r}: expanding, literal_execute and callables are not supported"
        )
    if not bind.required and type(bind.value) not in _FROZEN_LITERAL_TYPES:
        raise DeclarationError("an embedded literal of an unsupported type")


def _walk_value(
    expr: object, column: Column[Any], collected: _Collected, *, what: str, key: bool
) -> None:
    """Accept a `<value>`: a bind, a literal, NULL/TRUE/FALSE or a `pg_catalog` time function."""
    if isinstance(expr, elements.BindParameter):
        _check_bind(expr)
        if expr.required:
            collected.add_supplied(expr, column)
        else:
            if key:
                raise DeclarationError(f"{what}: a key or foreign-key column takes a supplied bind")
            collected.literal_columns.add(column)
        return
    if isinstance(expr, (elements.Null, elements.True_, elements.False_)):
        if key:
            raise DeclarationError(f"{what}: a key or foreign-key column takes a supplied bind")
        return
    if _is_time_function(expr):
        if key:
            raise DeclarationError(f"{what}: a key or foreign-key column takes a supplied bind")
        return
    raise DeclarationError(f"{what}: unsupported value expression {type(expr).__name__}")


def _conjuncts(expr: object, what: str) -> list[elements.BinaryExpression[Any]]:
    if isinstance(expr, elements.Grouping):
        return _conjuncts(expr.element, what)
    if isinstance(expr, elements.BooleanClauseList):
        if expr.operator is not operators.and_:
            raise DeclarationError(f"{what}: OR is not supported")
        result: list[elements.BinaryExpression[Any]] = []
        for clause in expr.clauses:
            result.extend(_conjuncts(clause, what))
        return result
    if isinstance(expr, elements.BinaryExpression):
        return [expr]
    raise DeclarationError(f"{what}: unsupported WHERE element {type(expr).__name__}")


def _pure_column(expr: object, table: Table, what: str) -> Column[Any]:
    if not isinstance(expr, Column) or expr.table is not table:
        raise DeclarationError(f"{what}: a column of {table.name} is required")
    return expr


def _comparable_kind(column: Column[Any], what: str) -> Kind:
    kind = kind_of(column)[0]
    if kind not in _COMPARABLE_KINDS:
        raise DeclarationError(f"{what}: {column} has a type that a predicate may not compare")
    return kind


def _check_comparison(
    left: Column[Any],
    operator: object,
    right: object,
    table: Table,
    what: str,
    collected: _Collected,
) -> None:
    """The type allowlist for one comparison: both operands are built-in kinds of the same family
    (mixed integer widths and varchar/text are the same family), so the operators that run are
    exactly those `_SESSION_SQL` covers. `IS [NOT] NULL` invokes no operator and takes any column."""
    if isinstance(right, elements.Null) and operator in (operators.is_, operators.is_not):
        return
    kind = _comparable_kind(left, what)
    collected.compared.add(left)
    if isinstance(right, Column):
        if _comparable_kind(_pure_column(right, table, what), what) is not kind:
            raise DeclarationError(f"{what}: {left} and {right} are of different kinds")
        collected.compared.add(right)
    elif isinstance(right, elements.BindParameter):
        if (
            not right.required
            and right.value is not None
            and _LITERAL_KINDS.get(type(right.value)) is not kind
        ):
            raise DeclarationError(f"{what}: a literal of the wrong kind for {left}")
    elif isinstance(right, (elements.True_, elements.False_)):
        if kind is not Kind.BOOL:
            raise DeclarationError(f"{what}: TRUE/FALSE needs a boolean column")
    elif _is_time_function(right) and kind is not Kind.DATETIME:
        raise DeclarationError(f"{what}: a time function needs a timestamptz column")


def _check_predicate_expression(
    expr: object, table: Table, collected: _Collected, what: str
) -> None:
    """The PreLock predicate allowlist (plan 6.11.5)."""
    if isinstance(expr, elements.Grouping):
        _check_predicate_expression(expr.element, table, collected, what)
    elif isinstance(expr, elements.BooleanClauseList):
        if expr.operator not in (operators.and_, operators.or_):
            raise DeclarationError(f"{what}: unsupported boolean operator")
        for clause in expr.clauses:
            _check_predicate_expression(clause, table, collected, what)
    elif isinstance(expr, elements.UnaryExpression):
        if expr.operator is not operators.inv:
            raise DeclarationError(f"{what}: only NOT is allowed as a unary operator")
        _check_predicate_expression(expr.element, table, collected, what)
    elif isinstance(expr, elements.BinaryExpression):
        if expr.operator not in _COMPARISONS:
            raise DeclarationError(f"{what}: unsupported operator {expr.operator}")
        left = _pure_column(expr.left, table, what)
        right = expr.right
        if isinstance(right, Column):
            _pure_column(right, table, what)
        elif isinstance(right, elements.BindParameter):
            _check_bind(right)
            if right.required:
                collected.add_supplied(right, left)
        elif not (
            isinstance(right, (elements.Null, elements.True_, elements.False_))
            or _is_time_function(right)
        ):
            raise DeclarationError(f"{what}: unsupported right operand {type(right).__name__}")
        _check_comparison(left, expr.operator, right, table, what, collected)
    else:
        raise DeclarationError(f"{what}: unsupported predicate element {type(expr).__name__}")


def _check_deferrable_pk(table: Table, what: str) -> None:
    pk = table.primary_key
    if pk.deferrable or pk.initially:
        raise DeclarationError(f"{what}: {table.name} has a deferrable primary key")


_DIALECT: Any = postgresql.psycopg.dialect


def _canonical(statement: Any, column_keys: list[str]) -> Any:
    return statement.compile(dialect=_DIALECT(), column_keys=column_keys)


def _embedded_and_supplied(statement: Any, supplied: set[str]) -> dict[str, object]:
    """Compile once at construction: the supplied binds must be exactly the compiled binds that are
    required, and no embedded key may equal a supplied name (P-B5/P-C2). Returns the embedded literals."""
    compiled = _canonical(statement, sorted(supplied))
    required = {key for key, bind in compiled.binds.items() if bind.required}
    if required != supplied:
        raise DeclarationError(
            f"the statement's supplied binds {sorted(required)} differ from the declaration"
        )
    embedded = {key: bind.value for key, bind in compiled.binds.items() if not bind.required}
    if set(embedded) & supplied:
        raise DeclarationError("an embedded literal key equals a supplied bind name")
    return embedded


# -- PreLock ---------------------------------------------------------------------------------------


@dataclass(frozen=True, eq=False)
class PreLock:
    """`select(*key_columns).where(<allowlisted predicate>).with_for_update(...)` on one table.

    Compared and hashed by identity: the plan runs the declared object itself."""

    name: str
    statement: Select[Any]
    table: Table = field(init=False)
    mode: LockMode = field(init=False)
    key: tuple[Column[Any], ...] = field(init=False)
    specs: Mapping[str, BindSpec] = field(init=False)
    embedded: Mapping[str, object] = field(init=False)
    compared: tuple[Column[Any], ...] = field(init=False)

    def __post_init__(self) -> None:
        what = f"PreLock {self.name!r}"
        stmt = self.statement
        if type(stmt) is not Select:
            raise DeclarationError(f"{what}: a plain select() is required")
        _require_clean(stmt, what)
        arg = stmt._for_update_arg
        if arg is None:
            raise DeclarationError(f"{what}: with_for_update() is required")
        if arg.skip_locked:
            raise DeclarationError(f"{what}: skip_locked is not supported")
        columns = list(stmt.selected_columns)
        if not columns or not all(isinstance(c, Column) for c in columns):
            raise DeclarationError(f"{what}: select plain key columns")
        table = columns[0].table
        if not isinstance(table, Table) or any(c.table is not table for c in columns):
            raise DeclarationError(f"{what}: the key columns must belong to one table")
        if stmt.get_final_froms() != [table]:
            raise DeclarationError(f"{what}: FROM must be {table.name} alone")
        if arg.of is not None and any(o is not table for o in arg.of):
            raise DeclarationError(f"{what}: FOR ... OF may name only {table.name}")
        for column in columns:
            if column.nullable:
                raise DeclarationError(f"{what}: key column {column} must be NOT NULL")
            if kind_of(cast("Column[Any]", column))[0] not in _KEY_KINDS:
                raise DeclarationError(f"{what}: key columns must be uuid or int")
        _check_deferrable_pk(table, what)
        for order in stmt._order_by_clauses:
            if isinstance(order, elements.UnaryExpression):
                if order.modifier not in (operators.asc_op, operators.desc_op):
                    raise DeclarationError(f"{what}: unsupported ORDER BY")
                _pure_column(order.element, table, what)
            else:
                _pure_column(order, table, what)
        collected = _Collected()
        criteria = stmt._where_criteria
        if not criteria:
            raise DeclarationError(f"{what}: a WHERE clause is required")
        for criterion in criteria:
            _check_predicate_expression(criterion, table, collected, what)
        if any(n != 1 for n in collected.counts.values()):
            raise DeclarationError(f"{what}: each bind name may appear once")
        mode = (
            LockMode.KEY_SHARE
            if arg.read and arg.key_share
            else LockMode.SHARE
            if arg.read
            else LockMode.NO_KEY_UPDATE
            if arg.key_share
            else LockMode.UPDATE
        )
        specs = {name: spec_for(name, column) for name, column in collected.columns.items()}
        embedded = _embedded_and_supplied(stmt, set(specs))
        object.__setattr__(self, "table", table)
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "key", tuple(columns))
        object.__setattr__(self, "specs", MappingProxyType(specs))
        object.__setattr__(self, "embedded", MappingProxyType(embedded))
        object.__setattr__(self, "compared", tuple(collected.compared))


@dataclass(frozen=True)
class KeyBind:
    column: Column[Any]
    bind: str


@dataclass(frozen=True, eq=False)
class FkBinding:
    constraint: ForeignKeyConstraint
    binds: tuple[KeyBind, ...]
    lock: PreLock | None


def _referenced_key_ok(constraint: ForeignKeyConstraint) -> bool:
    referred = constraint.referred_table
    columns = {element.column for element in constraint.elements}
    if columns == set(referred.primary_key.columns):
        return True
    for item in referred.constraints:
        if (
            isinstance(item, UniqueConstraint)
            and set(item.columns) == columns
            and not item.deferrable
        ):
            return True
    for index in referred.indexes:
        if (
            isinstance(index, Index)
            and index.unique
            and index.dialect_options["postgresql"]["where"] is None
            and all(isinstance(e, Column) for e in index.expressions)
            and set(index.columns) == columns
        ):
            return True
    return False


# -- WriteStep -------------------------------------------------------------------------------------


@dataclass(frozen=True, eq=False)
class WriteStep:
    name: str
    statement: Insert | Update
    cardinality: Cardinality
    target: tuple[KeyBind, ...] = ()
    target_lock: PreLock | None = None
    fks: tuple[FkBinding, ...] = ()
    value_binds: frozenset[str] = frozenset()
    triggers: frozenset[TriggerPin] = frozenset()
    unique_waits: frozenset[UniqueWait] = frozenset()
    rows: RowExpectation = RowExpectation.ONE
    # derived
    table: Table = field(init=False)
    is_update: bool = field(init=False)
    specs: Mapping[str, BindSpec] = field(init=False)
    embedded: Mapping[str, object] = field(init=False)
    pk_kinds: tuple[Kind, ...] = field(init=False)
    pk_binds: tuple[str | None, ...] = field(init=False)
    identity_pk: bool = field(init=False)
    compared: tuple[Column[Any], ...] = field(init=False)

    def __post_init__(self) -> None:  # noqa: C901, PLR0912, PLR0915 - one linear validator
        what = f"WriteStep {self.name!r}"
        stmt = self.statement
        if type(stmt) is Insert:
            is_update = False
        elif type(stmt) is Update:
            is_update = True
        else:
            raise DeclarationError(f"{what}: a plain sqlalchemy insert() or update() is required")
        _require_clean(stmt, what)
        table = stmt.table
        if not isinstance(table, Table):
            raise DeclarationError(f"{what}: the target must be a table")
        _check_deferrable_pk(table, what)
        if not isinstance(self.cardinality, (Exactly, Between, EachLockedRow)):
            raise DeclarationError(f"{what}: unsupported cardinality")
        if not isinstance(self.rows, RowExpectation):
            raise DeclarationError(f"{what}: rows must be a RowExpectation")
        # RETURNING: exactly the primary key, in order.
        if tuple(stmt._returning) != tuple(table.primary_key.columns):
            raise DeclarationError(f"{what}: RETURNING must be exactly the primary-key columns")
        if stmt._return_defaults:
            raise DeclarationError(f"{what}: return_defaults() is not supported")
        # SQLAlchemy-side defaults would add SQL or pre-execute statements.
        for column in table.columns:
            if column.default is not None or column.onupdate is not None:
                raise DeclarationError(f"{what}: {column} has a SQLAlchemy-side default")
        values: dict[Any, Any] = dict(stmt._values or {})
        if not values:
            raise DeclarationError(f"{what}: explicit .values(...) is required")
        if getattr(stmt, "_post_values_clause", None) is not None:
            raise DeclarationError(f"{what}: ON CONFLICT and similar clauses are not supported")
        for key in values:
            if not isinstance(key, str) or key not in table.c:
                raise DeclarationError(f"{what}: .values() names a non-column {key!r}")
        written = {table.c[key] for key in values}
        for column in written:
            if column.identity is not None and column.primary_key and not is_update:
                raise DeclarationError(f"{what}: an identity column is never supplied")
            kind_of(column)
        collected = _Collected()
        target_binds: dict[str, Column[Any]] = {}
        if is_update:
            if stmt._ordered_values:
                raise DeclarationError(f"{what}: ordered values are not supported")
            if any(column.primary_key for column in written):
                raise DeclarationError(f"{what}: SET of a primary-key column")
            if self.rows is RowExpectation.ZERO_OR_ONE and not (
                (isinstance(self.cardinality, Between) and self.cardinality.low == 0)
                or (isinstance(self.cardinality, EachLockedRow) and not self.cardinality.complete)
            ):
                raise DeclarationError(f"{what}: ZERO_OR_ONE needs a lower bound of 0")
            if (
                isinstance(self.cardinality, EachLockedRow)
                and self.cardinality.complete
                and self.rows is not RowExpectation.ONE
            ):
                raise DeclarationError(f"{what}: EachLockedRow(complete=True) needs rows ONE")
            # WHERE: full-PK equality plus narrowing conjuncts
            criteria = cast(Update, stmt)._where_criteria
            if len(criteria) == 0:
                raise DeclarationError(f"{what}: a WHERE clause is required")
            pk_columns = tuple(table.primary_key.columns)
            if tuple(kb.column for kb in self.target) != pk_columns:
                raise DeclarationError(f"{what}: target must list every PK column in PK order")
            if self.target_lock is None:
                raise DeclarationError(f"{what}: an UPDATE needs a target_lock")
            if self.target_lock.table is not table or self.target_lock.key != pk_columns:
                raise DeclarationError(f"{what}: target_lock must lock this table's PK, in order")
            if self.target_lock.mode not in (LockMode.NO_KEY_UPDATE, LockMode.UPDATE):
                raise DeclarationError(f"{what}: target_lock must be FOR (NO KEY) UPDATE")
            conjuncts: list[elements.BinaryExpression[Any]] = []
            for criterion in criteria:
                conjuncts.extend(_conjuncts(criterion, what))
            equalities: dict[Column[Any], str] = {}
            for conjunct in conjuncts:
                left = _pure_column(conjunct.left, table, what)
                if conjunct.operator not in _COMPARISONS:
                    raise DeclarationError(f"{what}: unsupported WHERE operator")
                if left.primary_key:
                    right = conjunct.right
                    if (
                        conjunct.operator is not operators.eq
                        or not isinstance(right, elements.BindParameter)
                        or not right.required
                        or left in equalities
                    ):
                        raise DeclarationError(f"{what}: one bind equality per PK column")
                    _check_bind(right)
                    equalities[left] = right.key
                    collected.add_supplied(right, left)
                    target_binds[right.key] = left
                else:
                    _walk_value(conjunct.right, left, collected, what=what, key=False)
                _check_comparison(left, conjunct.operator, conjunct.right, table, what, collected)
            if equalities != {kb.column: kb.bind for kb in self.target}:
                raise DeclarationError(f"{what}: WHERE equalities do not match target")
        else:
            if self.target or self.target_lock is not None:
                raise DeclarationError(f"{what}: an INSERT has no target")
            if stmt.select is not None or stmt._multi_values:
                raise DeclarationError(
                    f"{what}: INSERT ... SELECT and multi-row values are not supported"
                )
            if self.rows is not RowExpectation.ONE:
                raise DeclarationError(f"{what}: an INSERT is always ONE")
            if isinstance(self.cardinality, EachLockedRow):
                raise DeclarationError(f"{what}: an INSERT cannot be EachLockedRow")
        # SET / VALUES
        fk_columns: set[Column[Any]] = set()
        for constraint in table.foreign_key_constraints:
            if written & set(constraint.columns):
                fk_columns |= set(constraint.columns)
        for key, expr in values.items():
            column = table.c[key]
            _walk_value(
                expr,
                column,
                collected,
                what=what,
                key=column in fk_columns or column.primary_key,
            )
            if (
                isinstance(expr, elements.BindParameter)
                and expr.required
                and expr.key != key
                and expr.key in table.c
            ):
                raise DeclarationError(f"{what}: bind {expr.key!r} is named like another column")
        # A supplied name equal to a column adds that column to SET / VALUES (P-B2) unless it is the
        # bind of that very column in `.values()`.
        for name in collected.columns:
            if name in table.c:
                expr = values.get(name)
                if not (
                    isinstance(expr, elements.BindParameter) and expr.required and expr.key == name
                ):
                    raise DeclarationError(
                        f"{what}: bind {name!r} is named like a column it does not set"
                    )
        if any(count != 1 for count in collected.counts.values()):
            raise DeclarationError(f"{what}: each bind name may appear once")
        # Unique constraints and indexes the step can touch must be named by a UniqueWait.
        waits = {w.index for w in self.unique_waits}
        for item in (*table.constraints, *table.indexes):
            if not (
                isinstance(item, UniqueConstraint) or (isinstance(item, Index) and item.unique)
            ):
                continue
            if item.name and (not is_update or written & set(item.columns)):
                label = f"{table.schema}.{item.name}" if table.schema else item.name
                if label not in waits:
                    raise DeclarationError(f"{what}: unique index {label} needs a UniqueWait")
        # FK groups
        expected = [c for c in table.foreign_key_constraints if written & set(c.columns)]
        if {id(f.constraint) for f in self.fks} != {id(c) for c in expected} or len(
            self.fks
        ) != len(expected):
            raise DeclarationError(
                f"{what}: fks must be exactly the FK constraints the step writes"
            )
        fk_supplied: set[str] = set()
        for binding in self.fks:
            constraint = binding.constraint
            if constraint.deferrable or constraint.initially:
                raise DeclarationError(f"{what}: a deferrable FK is not supported")
            if (constraint.match or "SIMPLE").upper() not in ("SIMPLE", "FULL"):
                raise DeclarationError(f"{what}: unsupported MATCH type")
            if not _referenced_key_ok(constraint):
                raise DeclarationError(
                    f"{what}: an FK must reference a primary key or a plain unique key"
                )
            _check_deferrable_pk(constraint.referred_table, what)
            elements_ = list(constraint.elements)
            if set(constraint.columns) - written:
                raise DeclarationError(f"{what}: a step must write every column of an FK group")
            if tuple(kb.column for kb in binding.binds) != tuple(e.parent for e in elements_):
                raise DeclarationError(
                    f"{what}: FK binds must follow the constraint's element order"
                )
            for kb in binding.binds:
                if collected.columns.get(kb.bind) is not kb.column:
                    raise DeclarationError(
                        f"{what}: FK bind {kb.bind!r} is not the value of {kb.column}"
                    )
                if kind_of(kb.column)[0] not in _KEY_KINDS:
                    raise DeclarationError(f"{what}: FK columns must be uuid or int")
                fk_supplied.add(kb.bind)
            if binding.lock is not None and (
                binding.lock.table is not constraint.referred_table
                or binding.lock.key != tuple(e.column for e in elements_)
            ):
                raise DeclarationError(
                    f"{what}: an FK lock must key the referenced columns, in order"
                )
        for kb in self.target:
            if kind_of(kb.column)[0] not in _KEY_KINDS:
                raise DeclarationError(f"{what}: target key columns must be uuid or int")
        for bind in (kb.bind for kb in self.target):
            if bind in fk_supplied:
                raise DeclarationError(f"{what}: a bind is both target and FK")
        supplied = set(collected.columns)
        derived = supplied - set(target_binds) - fk_supplied
        if set(self.value_binds) != derived:
            raise DeclarationError(
                f"{what}: value_binds {sorted(self.value_binds)} should be {sorted(derived)}"
            )
        embedded = _embedded_and_supplied(stmt, supplied)
        specs = {name: spec_for(name, column) for name, column in collected.columns.items()}
        for name, spec in specs.items():
            if (name in target_binds or name in fk_supplied) and spec.kind not in _KEY_KINDS:
                raise DeclarationError(f"{what}: key bind {name!r} must be uuid or int")
        pk_kinds = tuple(kind_of(c)[0] for c in table.primary_key.columns)
        for kind in pk_kinds:
            if kind not in _KEY_KINDS:
                raise DeclarationError(f"{what}: primary-key columns must be uuid or int")
        pk_binds: list[str | None] = []
        for column in table.primary_key.columns:
            expr = values.get(column.key)
            pk_binds.append(expr.key if isinstance(expr, elements.BindParameter) else None)
        identity = (not is_update) and any(
            c.identity is not None and c.key not in values for c in table.primary_key.columns
        )
        object.__setattr__(self, "table", table)
        object.__setattr__(self, "is_update", is_update)
        object.__setattr__(self, "specs", MappingProxyType(specs))
        object.__setattr__(self, "embedded", MappingProxyType(embedded))
        object.__setattr__(self, "compared", tuple(collected.compared))
        object.__setattr__(self, "pk_kinds", pk_kinds)
        object.__setattr__(self, "pk_binds", tuple(pk_binds) if not is_update else ())
        object.__setattr__(self, "identity_pk", identity)


@dataclass(frozen=True, eq=False)
class PreWriteDeclaration:
    locks: tuple[PreLock, ...]
    steps: tuple[WriteStep, ...]
    unlocked_fk_targets: frozenset[Table] = frozenset()
    _step_index: Mapping[int, int] = field(init=False, repr=False)
    _lock_ids: frozenset[int] = field(init=False, repr=False)
    type_checks: tuple[tuple[str, str, str], ...] = field(init=False)

    def __post_init__(self) -> None:
        if not self.steps:
            raise DeclarationError("a pre-write declaration needs at least one step")
        lock_ids = {id(lock) for lock in self.locks}
        if len(lock_ids) != len(self.locks):
            raise DeclarationError("a PreLock is listed twice")
        statement_ids: set[int] = set()
        step_index: dict[int, int] = {}
        for index, step in enumerate(self.steps):
            if id(step.statement) in statement_ids or id(step) in step_index:
                raise DeclarationError("a statement object appears in at most one step")
            statement_ids.add(id(step.statement))
            step_index[id(step)] = index
            used = [step.target_lock] if step.target_lock is not None else []
            used += [f.lock for f in step.fks if f.lock is not None]
            for lock in used:
                if id(lock) not in lock_ids:
                    raise DeclarationError(
                        f"step {step.name!r} uses a PreLock that is not in locks"
                    )
            for binding in step.fks:
                if (
                    binding.lock is None
                    and binding.constraint.referred_table not in self.unlocked_fk_targets
                ):
                    raise DeclarationError(
                        f"step {step.name!r}: an unlocked FK target must be a reviewed unlocked_fk_targets table"
                    )
        for lock in self.locks:
            if id(lock.statement) in statement_ids:
                raise DeclarationError("a statement object is reused")
            statement_ids.add(id(lock.statement))
        object.__setattr__(self, "_step_index", MappingProxyType(step_index))
        object.__setattr__(self, "_lock_ids", frozenset(lock_ids))
        # every compared column, with the one built-in PostgreSQL type its declared class stands for:
        # the plan verifies these against the live catalogue before lock evidence and finalize
        preparer = _DIALECT().identifier_preparer
        checks: dict[tuple[str, str, str], None] = {}
        for item in cast("tuple[PreLock | WriteStep, ...]", (*self.locks, *self.steps)):
            for column in item.compared:
                relation = preparer.format_table(column.table)
                checks[(relation, column.name, kind_and_pg_type(column)[2])] = None
        object.__setattr__(self, "type_checks", tuple(sorted(checks)))

    def index_of_step(self, step: object) -> int | None:
        index = self._step_index.get(id(step))
        if index is None or self.steps[index] is not step:
            return None
        return index

    def has_lock(self, lock: object) -> bool:
        return id(lock) in self._lock_ids and any(item is lock for item in self.locks)


__all__ = [
    "REVIEWED_EXECUTION_OPTIONS",
    "BindSpec",
    "Between",
    "Cardinality",
    "DeclarationError",
    "EachLockedRow",
    "Event",
    "Exactly",
    "FkBinding",
    "FunctionPin",
    "Kind",
    "KeyBind",
    "Level",
    "LockMode",
    "ParameterError",
    "PreLock",
    "PreWriteDeclaration",
    "RowExpectation",
    "Timing",
    "TriggerPin",
    "UniqueWait",
    "WriteStep",
    "freeze_value",
    "kind_and_pg_type",
    "kind_of",
    "matches_driver",
    "matches_extracted",
    "spec_for",
    "thaw_value",
]
