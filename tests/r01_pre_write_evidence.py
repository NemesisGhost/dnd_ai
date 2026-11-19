"""R01 S1 evidence harness for pre-write refusals (plan 6.11.7), test-side.

- **A per-test schema** `r01pw_<hex>` holds the synthetic tables, one counter sequence per table and a
  statement-level trigger per table that advances that sequence. A counter delta can therefore come only
  from that test's statements. The schema is dropped by the fixture's finalizer.
- **E-driver, per connection:** `CountingCursor` counts `execute`/`executemany` on the psycopg connection
  it belongs to (not a class-level list). It observes every psycopg cursor call, including raw
  `driver_connection.execute`, independently of SQLAlchemy's events.
- **E-server:** the counter sequences advance for every statement that *began executing* on a table, even
  with zero matched rows and even when the transaction is rolled back (non-transactional).
- **E-locks:** `pg_locks` filtered by a backend pid and the test schema's relations.
- **Positive controls** run the same attempt on a plain, guard-free connection, rolled back, and the tests
  require E-driver +1, E-server +1 and the expected `rowcount`.
"""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import psycopg
import pytest
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Connection,
    Engine,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    MetaData,
    Table,
    Text,
    Uuid,
    create_engine,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, INT8RANGE, JSONB
from sqlalchemy.types import DateTime

TABLES = ("parent", "target", "cpk", "log", "audit", "skip", "ref", "child", "childf", "other")


class CountingCursor(psycopg.Cursor[Any]):
    """Counts the psycopg `execute`/`executemany` calls made through this cursor's connection."""

    def execute(self, *args: Any, **kwargs: Any) -> Any:
        _bump(self.connection)
        return super().execute(*args, **kwargs)

    def executemany(self, *args: Any, **kwargs: Any) -> Any:
        _bump(self.connection)
        return super().executemany(*args, **kwargs)


def _bump(connection: Any) -> None:
    connection.r01_driver_calls = getattr(connection, "r01_driver_calls", 0) + 1


def driver_calls(connection: Connection) -> int:
    driver = connection.connection.driver_connection
    return int(getattr(driver, "r01_driver_calls", 0))


def counting_engine(url: Any) -> Engine:
    """The application engine's shape (`get_engine`) plus the driver counter, one pooled connection."""
    return create_engine(
        url,
        isolation_level="READ COMMITTED",
        pool_size=1,
        max_overflow=0,
        connect_args={"cursor_factory": CountingCursor},
    )


@dataclass
class Synthetic:
    """One test's isolated schema, metadata and engines."""

    schema: str
    admin: Engine
    engine: Engine  # counting, one pooled connection; the guard is installed by `AuthorizationPlan.begin`
    plain: Engine  # counting, guard-free, for positive controls
    md: MetaData = field(default_factory=MetaData)
    tables: dict[str, Table] = field(default_factory=dict)

    def qualified(self, name: str) -> str:
        return f"{self.schema}.{name}"

    # -- E-server ----------------------------------------------------------------------------
    def server_count(self, table: str) -> int:
        with self.admin.connect() as connection:
            last, called = connection.execute(
                text(f"SELECT last_value, is_called FROM {self.schema}.{table}_ctr")  # noqa: S608
            ).one()
        return int(last) if called else 0

    def server_counts(self) -> dict[str, int]:
        return {name: self.server_count(name) for name in TABLES}

    # -- seed / read ---------------------------------------------------------------------------
    def run(self, sql: str, **params: Any) -> None:
        with self.admin.connect() as connection:
            connection.execute(text(sql), params)

    def rows(self, sql: str, **params: Any) -> list[tuple[Any, ...]]:
        with self.admin.connect() as connection:
            return [tuple(r) for r in connection.execute(text(sql), params).all()]

    # -- E-locks -----------------------------------------------------------------------------
    def locks(self, pid: int) -> list[tuple[str, str | None, str]]:
        """(locktype, relation name or None, mode) for `pid`, restricted to this schema or advisory."""
        return [
            (str(r[0]), r[1], str(r[2]))
            for r in self.rows(
                "SELECT l.locktype, c.relname, l.mode FROM pg_locks l "
                "LEFT JOIN pg_class c ON c.oid = l.relation "
                "LEFT JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE l.pid = :pid AND l.granted AND (l.locktype = 'advisory' OR n.nspname = :s)",
                pid=pid,
                s=self.schema,
            )
        ]

    def relation_modes(self, pid: int, relation: str) -> set[str]:
        return {
            mode for kind, rel, mode in self.locks(pid) if kind == "relation" and rel == relation
        }


_DDL = """
CREATE SCHEMA {s};
CREATE TABLE {s}.parent (parent_id uuid PRIMARY KEY DEFAULT gen_random_uuid(), name text NOT NULL);
CREATE TABLE {s}.target (
    target_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    parent_id uuid NOT NULL REFERENCES {s}.parent,
    v integer NOT NULL DEFAULT 0, note text, active boolean NOT NULL DEFAULT true,
    stamp timestamptz, tags text[], meta jsonb, rng int8range, label text
);
CREATE UNIQUE INDEX ux_target_label ON {s}.target (label) WHERE label IS NOT NULL;
CREATE TABLE {s}.cpk (a uuid NOT NULL, b uuid NOT NULL, v integer NOT NULL, PRIMARY KEY (a, b));
CREATE TABLE {s}.log (
    log_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    parent_id uuid NOT NULL REFERENCES {s}.parent, msg text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE {s}.audit (
    audit_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, parent_id uuid NOT NULL,
    note text NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE {s}.skip (skip_id uuid PRIMARY KEY DEFAULT gen_random_uuid(), msg text NOT NULL);
CREATE TABLE {s}.ref (r_id uuid NOT NULL, scope uuid NOT NULL, other uuid NOT NULL,
    UNIQUE (r_id, scope, other));
CREATE TABLE {s}.child (child_id uuid PRIMARY KEY, r_id uuid, scope uuid, other uuid,
    FOREIGN KEY (r_id, scope, other) REFERENCES {s}.ref (r_id, scope, other) MATCH SIMPLE);
CREATE TABLE {s}.childf (child_id uuid PRIMARY KEY, r_id uuid, scope uuid, other uuid,
    FOREIGN KEY (r_id, scope, other) REFERENCES {s}.ref (r_id, scope, other) MATCH FULL);
CREATE TABLE {s}.other (n integer);
"""

_COUNTERS = """
CREATE SEQUENCE {s}.{t}_ctr;
CREATE FUNCTION {s}.{t}_bump() RETURNS trigger LANGUAGE plpgsql AS
$$BEGIN PERFORM nextval('{s}.{t}_ctr'); RETURN NULL; END$$;
CREATE TRIGGER {t}_bump_stmt BEFORE INSERT OR UPDATE ON {s}.{t}
    FOR EACH STATEMENT EXECUTE FUNCTION {s}.{t}_bump();
"""

_SKIP_TRIGGER = """
CREATE FUNCTION {s}.skip_row() RETURNS trigger LANGUAGE plpgsql AS
$$BEGIN IF NEW.msg = 'skip' THEN RETURN NULL; END IF; RETURN NEW; END$$;
CREATE TRIGGER skip_row_trg BEFORE INSERT ON {s}.skip
    FOR EACH ROW EXECUTE FUNCTION {s}.skip_row();
"""


def _metadata(s: Synthetic) -> None:
    md, schema = s.md, s.schema

    def table(name: str, *columns: Any, **kw: Any) -> Table:
        t = Table(name, md, *columns, schema=schema, **kw)
        s.tables[name] = t
        return t

    table(
        "parent",
        Column("parent_id", Uuid, primary_key=True, server_default=text("gen_random_uuid()")),
        Column("name", Text, nullable=False),
    )
    table(
        "target",
        Column("target_id", Uuid, primary_key=True, server_default=text("gen_random_uuid()")),
        Column("parent_id", Uuid, nullable=False),
        Column("v", Integer, nullable=False),
        Column("note", Text),
        Column("active", Boolean, nullable=False),
        Column("stamp", DateTime(timezone=True)),
        Column("tags", ARRAY(Text)),
        Column("meta", JSONB),
        Column("rng", INT8RANGE),
        Column("label", Text),
        ForeignKeyConstraint(["parent_id"], [f"{schema}.parent.parent_id"]),
        Index("ux_target_label", "label", unique=True, postgresql_where=text("label IS NOT NULL")),
    )
    table(
        "cpk",
        Column("a", Uuid, primary_key=True),
        Column("b", Uuid, primary_key=True),
        Column("v", Integer, nullable=False),
    )
    table(
        "log",
        Column("log_id", Uuid, primary_key=True, server_default=text("gen_random_uuid()")),
        Column("parent_id", Uuid, nullable=False),
        Column("msg", Text, nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
        ForeignKeyConstraint(["parent_id"], [f"{schema}.parent.parent_id"]),
    )
    table(
        "audit",
        Column("audit_id", BigInteger, Identity(always=True), primary_key=True),
        Column("parent_id", Uuid, nullable=False),
        Column("note", Text, nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
    )
    table(
        "skip",
        Column("skip_id", Uuid, primary_key=True, server_default=text("gen_random_uuid()")),
        Column("msg", Text, nullable=False),
    )
    ref = table(
        "ref",
        Column("r_id", Uuid, nullable=False),
        Column("scope", Uuid, nullable=False),
        Column("other", Uuid, nullable=False),
    )
    from sqlalchemy import UniqueConstraint

    ref.append_constraint(
        UniqueConstraint("r_id", "scope", "other", name="ref_r_id_scope_other_key")
    )
    for name, match in (("child", None), ("childf", "FULL")):
        table(
            name,
            Column("child_id", Uuid, primary_key=True),
            Column("r_id", Uuid),
            Column("scope", Uuid),
            Column("other", Uuid),
            ForeignKeyConstraint(
                ["r_id", "scope", "other"],
                [f"{schema}.ref.r_id", f"{schema}.ref.scope", f"{schema}.ref.other"],
                match=match,
            ),
        )
    table("other", Column("n", Integer))


@pytest.fixture
def synthetic(postgres_engine: Engine) -> Iterator[Synthetic]:
    schema = f"r01pw_{uuid.uuid4().hex}"
    admin = postgres_engine.execution_options(isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        for statement in _statements(_DDL.format(s=schema)):
            connection.execute(text(statement))
        for name in TABLES:
            for statement in _statements(_COUNTERS.format(s=schema, t=name)):
                connection.execute(text(statement))
        for statement in _statements(_SKIP_TRIGGER.format(s=schema)):
            connection.execute(text(statement))
    engine = counting_engine(postgres_engine.url)
    plain = counting_engine(postgres_engine.url)
    s = Synthetic(schema=schema, admin=admin, engine=engine, plain=plain)
    _metadata(s)
    try:
        yield s
    finally:
        engine.dispose()
        plain.dispose()
        with admin.connect() as connection:
            # a failed test may leave its connection holding locks: end those sessions first
            connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE pid <> "
                    "pg_backend_pid() AND datname = current_database() "
                    "AND state LIKE 'idle in transaction%'"
                )
            )
            connection.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))


def _statements(script: str) -> list[str]:
    """Split on a semicolon that ends a line outside `$$` blocks."""
    parts: list[str] = []
    current: list[str] = []
    in_body = False
    for line in script.splitlines():
        current.append(line)
        in_body ^= line.count("$$") % 2 == 1
        if not in_body and line.rstrip().endswith(";"):
            parts.append("\n".join(current))
            current = []
    if "\n".join(current).strip():
        parts.append("\n".join(current))
    return [p for p in parts if p.strip()]


def new_id() -> uuid.UUID:
    return uuid.uuid4()
