"""R01 S1-C catalogue helper (plan 6.10.7, 6.11.6), test-side.

It **inventories and checks the assumptions** a pre-write declaration makes about the database it runs on:
relation kind, row-level security, rules, generated columns, defaults, CHECK constraints, deferrable keys,
unique-index waits, exclusion constraints, the exact set of triggers and their configuration and function
identity, FK column order and match type, and lookalike comparison operators.

It does **not** prove that execution cannot block. Hashes and catalogue checks only detect change; trigger
callees, dynamic SQL, unique-index waits and business-rule lock completeness remain S5 obligations.

Every query runs with `SET LOCAL search_path = ''` and reads identities from catalogue columns (OIDs,
namespace and language rows). Deparsed text (`regprocedure`, `pg_get_expr`) appears only in diagnostics,
never in a decision: it is identical for different objects under some search paths (Q-L, Q-T7).
"""

import re
from collections.abc import Iterable

from sqlalchemy import Connection, Table, text

from dnd_ai.domain.authorization_steps import (
    DeclarationError,
    Event,
    FunctionPin,
    Level,
    PreLock,
    PreWriteDeclaration,
    Timing,
    TriggerPin,
    WriteStep,
)

_TAG = re.compile(r"\{([A-Z_]+) ")
_FUNCID = re.compile(r":(?:funcid|opfuncid) (\d+)")
_LOCATION = re.compile(r":location -?\d+")
_SYSTEM_OID = 16384
_KEY_TYPES = ("uuid", "int2", "int4", "int8")


def _q(connection: Connection, sql: str, **params: object) -> list[tuple[object, ...]]:
    return [tuple(r) for r in connection.execute(text(sql), params).all()]


def _isolate(connection: Connection) -> None:
    connection.execute(text("SET LOCAL search_path = ''"))


def _oid(connection: Connection, regproc: str) -> int:
    return int(
        connection.execute(
            text(f"SELECT '{regproc}'::pg_catalog.regprocedure::pg_catalog.oid")
        ).scalar_one()
    )  # noqa: S608


def _relation(connection: Connection, table: Table) -> tuple[object, ...] | None:
    rows = _q(
        connection,
        "SELECT c.oid, c.relkind::text, c.relispartition, c.relrowsecurity, c.relforcerowsecurity, "
        "c.relhassubclass, "
        "(SELECT count(*) FROM pg_catalog.pg_inherits i WHERE i.inhrelid = c.oid), "
        "EXISTS (SELECT 1 FROM pg_catalog.pg_rewrite r WHERE r.ev_class = c.oid) "
        "FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = :s AND c.relname = :t",
        s=table.schema or "public",
        t=table.name,
    )
    return rows[0] if rows else None


def _function_pin(connection: Connection, proc_oid: int) -> FunctionPin:
    row = _q(
        connection,
        "SELECT n.nspname, p.proname, pg_catalog.oidvectortypes(p.proargtypes), l.lanname, "
        "p.prosecdef, p.proconfig, p.provolatile::text, pg_catalog.md5(p.prosrc) "
        "FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace "
        "JOIN pg_catalog.pg_language l ON l.oid = p.prolang WHERE p.oid = :o",
        o=proc_oid,
    )[0]
    return FunctionPin(
        schema=str(row[0]),
        name=str(row[1]),
        arg_types=str(row[2]),
        language=str(row[3]),
        security_definer=bool(row[4]),
        config=tuple(row[5]) if row[5] is not None else None,  # type: ignore[call-overload]
        volatility=str(row[6]),
        source_md5=str(row[7]),
    )


def read_trigger_pins(
    connection: Connection, table: Table, command: Event, *, problems: list[str] | None = None
) -> frozenset[TriggerPin]:
    """Every non-internal trigger on `table` whose event bits include `command`, disabled ones included,
    read from catalogue columns. `problems` collects what cannot be pinned (INSTEAD OF, WHEN functions that
    are not built-in and immutable, a SECURITY DEFINER function)."""
    _isolate(connection)
    sink = problems if problems is not None else []
    relation = _relation(connection, table)
    if relation is None:
        sink.append(f"{table.name}: relation not found")
        return frozenset()
    bit = {Event.INSERT: 4, Event.DELETE: 8, Event.UPDATE: 16, Event.TRUNCATE: 32}[command]
    pins: set[TriggerPin] = set()
    rows = _q(
        connection,
        "SELECT t.oid, t.tgname, t.tgtype::int, t.tgfoid, t.tgenabled::text, t.tgconstraint <> 0, "
        "t.tgdeferrable, t.tginitdeferred, t.tgargs, t.tgattr::int2[], t.tgqual::text, "
        "(t.tgqual IS NOT NULL) "
        "FROM pg_catalog.pg_trigger t WHERE t.tgrelid = :r AND NOT t.tgisinternal ORDER BY t.tgname",
        r=relation[0],
    )
    for row in rows:
        tgtype = int(row[2])  # type: ignore[call-overload]
        if not tgtype & bit:
            continue
        if tgtype & 64:
            sink.append(f"{row[1]}: INSTEAD OF triggers are not supported")
            continue
        function = _function_pin(connection, int(row[3]))  # type: ignore[call-overload]
        if function.security_definer:
            sink.append(
                f"{row[1]}: SECURITY DEFINER trigger function {function.schema}.{function.name}"
            )
            continue
        attrs = list(row[9] or ())  # type: ignore[call-overload]
        names: tuple[str, ...] | None = None
        if attrs:
            names = tuple(
                str(
                    _q(
                        connection,
                        "SELECT attname FROM pg_catalog.pg_attribute WHERE attrelid = :r AND attnum = :n",
                        r=relation[0],
                        n=a,
                    )[0][0]
                )
                for a in attrs
            )
        when_hash: str | None = None
        if row[11]:
            qual = _LOCATION.sub("", str(row[10]))
            when_hash = str(_q(connection, "SELECT pg_catalog.md5(:q)", q=qual)[0][0])
            _check_expression(connection, str(row[10]), f"{row[1]} WHEN", sink)
        args_raw = bytes(row[8]) if row[8] else b""  # type: ignore[call-overload]
        args = tuple(a.decode("latin-1") for a in args_raw.split(b"\x00")[:-1]) if args_raw else ()
        events = frozenset(
            event
            for event, mask in (
                (Event.INSERT, 4),
                (Event.DELETE, 8),
                (Event.UPDATE, 16),
                (Event.TRUNCATE, 32),
            )
            if tgtype & mask
        )
        pins.add(
            TriggerPin(
                name=str(row[1]),
                timing=Timing.BEFORE if tgtype & 2 else Timing.AFTER,
                level=Level.ROW if tgtype & 1 else Level.STATEMENT,
                events=events,
                update_columns=names,
                when_hash=when_hash,
                enabled=str(row[4]),
                constraint_trigger=bool(row[5]),
                deferrable=bool(row[6]),
                initially_deferred=bool(row[7]),
                args=args,
                function=function,
            )
        )
    # internal triggers must belong to FK constraints
    for (name,) in _q(
        connection,
        "SELECT t.tgname FROM pg_catalog.pg_trigger t LEFT JOIN pg_catalog.pg_constraint c "
        "ON c.oid = t.tgconstraint WHERE t.tgrelid = :r AND t.tgisinternal "
        "AND (c.oid IS NULL OR c.contype <> 'f')",
        r=relation[0],
    ):
        sink.append(f"internal trigger {name} is not owned by a foreign-key constraint")
    return frozenset(pins)


def _check_expression(connection: Connection, tree: str, label: str, sink: list[str]) -> None:
    """No sublink; every function and operator function is built-in (OID < 16384) and immutable."""
    if "SUBLINK" in _TAG.findall(tree):
        sink.append(f"{label}: contains a sub-select")
    oids = sorted({int(m) for m in _FUNCID.findall(tree)})
    if not oids:
        return
    found = {
        int(r[0]): str(r[1])
        for r in _q(
            connection,
            "SELECT oid::int, provolatile::text FROM pg_catalog.pg_proc WHERE oid = ANY(:o)",
            o=oids,
        )
    }
    for oid in oids:
        if oid >= _SYSTEM_OID:
            sink.append(f"{label}: calls a non-built-in function (oid {oid})")
        elif found.get(oid) != "i":
            sink.append(f"{label}: calls a built-in function that is not immutable (oid {oid})")


def _attnums(connection: Connection, relation_oid: object, names: Iterable[str]) -> dict[str, int]:
    return {
        str(r[0]): int(r[1])  # type: ignore[call-overload]
        for r in _q(
            connection,
            "SELECT attname, attnum FROM pg_catalog.pg_attribute WHERE attrelid = :r "
            "AND NOT attisdropped AND attnum > 0 AND attname = ANY(:n)",
            r=relation_oid,
            n=list(names),
        )
    }


def check_declaration(connection: Connection, declaration: PreWriteDeclaration) -> list[str]:
    """Every problem found, as readable diagnostics. An empty list means the declaration's assumptions
    hold on this database."""
    _isolate(connection)
    problems: list[str] = []
    allowed_functions = {
        _oid(connection, "pg_catalog.now()"),
        _oid(connection, "pg_catalog.clock_timestamp()"),
        _oid(connection, "pg_catalog.gen_random_uuid()"),
    }
    # the operator inventory: no lookalike comparison operator for the key types
    for namespace, name, left, right in _q(
        connection,
        "SELECT n.nspname, o.oprname, o.oprleft::pg_catalog.regtype::text, "
        "o.oprright::pg_catalog.regtype::text FROM pg_catalog.pg_operator o "
        "JOIN pg_catalog.pg_namespace n ON n.oid = o.oprnamespace WHERE n.nspname <> 'pg_catalog' "
        "AND o.oprname IN ('=', '<>', '<', '<=', '>', '>=') AND (o.oprleft::pg_catalog.regtype::text "
        "= ANY(:k) OR o.oprright::pg_catalog.regtype::text = ANY(:k))",
        k=list(_KEY_TYPES),
    ):
        problems.append(f"lookalike operator {namespace}.{name}({left}, {right})")
    for step in declaration.steps:
        _check_step(connection, step, allowed_functions, problems)
    for lock in declaration.locks:
        _check_table_keys(connection, lock.table, f"lock {lock.name}", problems)
    return problems


def _check_table_keys(
    connection: Connection, table: Table, label: str, problems: list[str]
) -> object | None:
    relation = _relation(connection, table)
    if relation is None:
        problems.append(f"{label}: {table.name} not found")
        return None
    for (name,) in _q(
        connection,
        "SELECT conname FROM pg_catalog.pg_constraint WHERE conrelid = :r AND contype = 'p' "
        "AND condeferrable",
        r=relation[0],
    ):
        problems.append(f"{label}: deferrable primary key {name}")
    return relation[0]


def _check_step(
    connection: Connection, step: WriteStep, allowed: set[int], problems: list[str]
) -> None:
    table = step.table
    label = f"step {step.name}"
    relation = _relation(connection, table)
    if relation is None:
        problems.append(f"{label}: {table.name} not found")
        return
    oid, relkind, ispartition, rls, force_rls, hassubclass, inherits, hasrules = relation
    if relkind != "r":
        problems.append(f"{label}: relation kind {relkind} (an ordinary table is required)")
    if ispartition or hassubclass or inherits:
        problems.append(f"{label}: partition or inheritance relationship")
    if rls or force_rls:
        problems.append(f"{label}: row-level security is enabled or forced")
    if hasrules:
        problems.append(f"{label}: the table has rewrite rules")
    _check_table_keys(connection, table, label, problems)
    for ref in {c.referred_table for c in table.foreign_key_constraints}:
        _check_table_keys(connection, ref, f"{label} (referenced)", problems)

    written = {table.c[k].name for k in step.statement._values}  # type: ignore[union-attr]
    columns = _q(
        connection,
        "SELECT a.attname, a.attnum, a.attnotnull, a.attgenerated::text, a.attidentity::text, "
        "a.atthasdef, a.atttypid, ty.typtype::text, d.oid, d.adbin::text "
        "FROM pg_catalog.pg_attribute a JOIN pg_catalog.pg_type ty ON ty.oid = a.atttypid "
        "LEFT JOIN pg_catalog.pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum "
        "WHERE a.attrelid = :r AND a.attnum > 0 AND NOT a.attisdropped ORDER BY a.attnum",
        r=oid,
    )
    domain_oids: set[int] = set()
    for name, _num, notnull, generated, identity, hasdef, typ, typtype, adoid, adbin in columns:
        if generated:
            problems.append(f"{label}: generated column {name}")
        if typtype == "d":
            domain_oids.add(int(typ))  # type: ignore[call-overload]
        if name in written or (step.is_update):
            continue
        # an INSERT omits this column
        if identity in ("a", "d"):
            continue
        if not hasdef:
            if notnull:
                problems.append(f"{label}: omitted NOT NULL column {name} has no default")
            continue
        _check_default(connection, label, str(name), str(adbin), int(adoid), allowed, problems)  # type: ignore[call-overload]
    # CHECK constraints of the table and of the domains in use
    checks = _q(
        connection,
        "SELECT conname, conbin::text FROM pg_catalog.pg_constraint WHERE contype = 'c' "
        "AND (conrelid = :r OR contypid = ANY(:d))",
        r=oid,
        d=sorted(domain_oids),
    )
    for name, tree in checks:
        _check_expression(connection, str(tree), f"{label}: CHECK {name}", problems)
    # exclusion constraints and deferrable unique constraints
    for name, contype in _q(
        connection,
        "SELECT conname, contype::text FROM pg_catalog.pg_constraint WHERE conrelid = :r "
        "AND (contype = 'x' OR (contype = 'u' AND condeferrable))",
        r=oid,
    ):
        problems.append(
            f"{label}: {'exclusion' if contype == 'x' else 'deferrable unique'} constraint {name}"
        )
    # unique indexes the step can touch must be named by a UniqueWait
    wait_names = {w.index for w in step.unique_waits}
    written_nums = set(_attnums(connection, oid, written).values())
    for index_oid, index_name in _q(
        connection,
        "SELECT i.indexrelid, c.relname FROM pg_catalog.pg_index i "
        "JOIN pg_catalog.pg_class c ON c.oid = i.indexrelid "
        "WHERE i.indrelid = :r AND i.indisunique AND NOT i.indisprimary",
        r=oid,
    ):
        columns_of_index = {
            int(r[0])  # type: ignore[call-overload]
            for r in _q(
                connection,
                "SELECT refobjsubid FROM pg_catalog.pg_depend WHERE classid = 'pg_catalog.pg_class'::"
                "pg_catalog.regclass AND objid = :i AND refclassid = 'pg_catalog.pg_class'::"
                "pg_catalog.regclass AND refobjid = :r AND refobjsubid > 0",
                i=index_oid,
                r=oid,
            )
        }
        touches = (not step.is_update) or bool(columns_of_index & written_nums)
        qualified = f"{table.schema}.{index_name}" if table.schema else str(index_name)
        if touches and qualified not in wait_names:
            problems.append(f"{label}: unique index {qualified} needs a UniqueWait")
    # FK constraints: match type, deferral and column order
    foreign = _q(
        connection,
        "SELECT c.oid, c.confmatchtype::text, c.condeferrable, c.confrelid, "
        "(SELECT array_agg(a.attname ORDER BY k.ord) FROM unnest(c.conkey) WITH ORDINALITY k(n, ord) "
        "JOIN pg_catalog.pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.n), "
        "(SELECT array_agg(a.attname ORDER BY k.ord) FROM unnest(c.confkey) WITH ORDINALITY k(n, ord) "
        "JOIN pg_catalog.pg_attribute a ON a.attrelid = c.confrelid AND a.attnum = k.n) "
        "FROM pg_catalog.pg_constraint c WHERE c.conrelid = :r AND c.contype = 'f'",
        r=oid,
    )
    for binding in step.fks:
        local = [e.parent.name for e in binding.constraint.elements]
        referred = [e.column.name for e in binding.constraint.elements]
        match = [row for row in foreign if list(row[4]) == local]  # type: ignore[call-overload]
        if not match:
            problems.append(f"{label}: no foreign key over {local} (or its column order differs)")
            continue
        row = match[0]
        if list(row[5]) != referred:  # type: ignore[call-overload]
            problems.append(f"{label}: referenced column order {list(row[5])} != {referred}")  # type: ignore[call-overload]
        if row[1] not in ("s", "f"):
            problems.append(f"{label}: unsupported FK match type {row[1]}")
        if row[2]:
            problems.append(f"{label}: deferrable foreign key")
    # triggers: the pinned set equals the catalogue's, exactly
    command = Event.UPDATE if step.is_update else Event.INSERT
    sink: list[str] = []
    actual = read_trigger_pins(connection, table, command, problems=sink)
    problems.extend(f"{label}: {p}" for p in sink)
    _isolate(connection)
    for pin in step.triggers - actual:
        problems.append(
            f"{label}: pinned trigger differs or is gone: {pin.name} ({pin.function.name})"
        )
    for pin in actual - step.triggers:
        problems.append(f"{label}: unpinned or changed trigger {pin.name} ({pin.function.name})")


def _check_default(
    connection: Connection,
    label: str,
    column: str,
    tree: str,
    attrdef_oid: int,
    allowed: set[int],
    problems: list[str],
) -> None:
    """A default is accepted by its stored node tree and dependencies, never by deparsed text."""
    tags = set(_TAG.findall(tree))
    funcids = {int(m) for m in re.findall(r":funcid (\d+)", tree)}
    ok = False
    if tags in ({"CONST"}, {"COERCETODOMAIN", "CONST"}) or (
        tags == {"FUNCEXPR"} and ":args <>" in tree and funcids and funcids <= allowed
    ):
        ok = True
    if ok:
        depends = _q(
            connection,
            "SELECT count(*) FROM pg_catalog.pg_depend WHERE classid = 'pg_catalog.pg_attrdef'::"
            "pg_catalog.regclass AND objid = :o AND refclassid = 'pg_catalog.pg_proc'::pg_catalog.regclass",
            o=attrdef_oid,
        )[0][0]
        if depends:
            ok = False
    if not ok:
        shown = _q(
            connection,
            "SELECT pg_catalog.pg_get_expr(adbin, adrelid) FROM pg_catalog.pg_attrdef WHERE oid = :o",
            o=attrdef_oid,
        )[0][0]
        problems.append(
            f"{label}: default of omitted column {column} is not supported (shown as {shown})"
        )


__all__ = ["DeclarationError", "PreLock", "check_declaration", "read_trigger_pins"]
