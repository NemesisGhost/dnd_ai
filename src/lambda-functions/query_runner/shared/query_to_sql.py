from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple
import re

IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class IdentifierError(ValueError):
    pass


class IdentifierResolver:
    def __init__(self, quote: bool = False) -> None:
        self.quote = quote

    def _check(self, name: str) -> None:
        if not IDENT_RE.match(name or ""):
            raise IdentifierError(f"Bad identifier: {name!r}")

    def table(self, name: str) -> str:
        self._check(name)
        return f'"{name}"' if self.quote else name

    def column(self, name: str) -> str:
        self._check(name)
        return f'"{name}"' if self.quote else name


class ParamStyle:
    PSYCOPG = "psycopg"
    QMARK = "qmark"
    NAMED = "named"


class ParamFormatter:
    def __init__(self, style: str = ParamStyle.PSYCOPG) -> None:
        if style not in (ParamStyle.PSYCOPG, ParamStyle.QMARK, ParamStyle.NAMED):
            raise ValueError("Unsupported parameter style")
        self.style = style
        self._count = 0

    def placeholder(self) -> str:
        self._count += 1
        if self.style == ParamStyle.PSYCOPG:
            return "%s"
        if self.style == ParamStyle.QMARK:
            return "?"
        return f":p{self._count}"

    def reset(self) -> None:
        self._count = 0


@dataclass
class SQL:
    text: str
    params: List[Any]


def compile_query(
    spec: Dict[str, Any],
    *,
    idr: Optional[IdentifierResolver] = None,
    param_style: str = ParamStyle.PSYCOPG,
    max_depth: int = 3,
    max_joins: int = 16,
    max_in: int = 1000,
    max_limit: int = 1000,
) -> SQL:
    idr = idr or IdentifierResolver(quote=False)
    pf = ParamFormatter(param_style)
    params: List[Any] = []

    def make_alias(name: str, used: Dict[str, int]) -> str:
        base = name.split(".")[-1]
        if base not in used:
            used[base] = 1
            return base
        used[base] += 1
        return f"{base}_{used[base]}"

    aliases: Dict[str, str] = {}
    used_base: Dict[str, int] = {}

    def register_table(table: str, desired_alias: Optional[str] = None) -> str:
        if table in aliases:
            return aliases[table]
        alias = desired_alias or make_alias(table, used_base)
        aliases[table] = alias
        aliases[alias] = alias
        return alias

    source_table = spec["source_table"]
    idr._check(source_table)
    base_alias = register_table(source_table)

    select_bits: List[str] = []
    join_bits: List[str] = []
    total_joins = 0

    def parse_ident(path: str) -> Tuple[str, str]:
        parts = path.split(".")
        if len(parts) != 2:
            raise IdentifierError(f"Identifier must be 'table.column': {path!r}")
        head, col = parts[0], parts[1]
        idr._check(head)
        idr._check(col)
        return head, col

    def resolve_ident(path: str) -> str:
        head, col = parse_ident(path)
        alias = aliases.get(head)
        if not alias:
            alias = register_table(head)
        return f"{idr.table(alias)}.{idr.column(col)}"

    def ensure_limit(limit_val: Optional[int]) -> None:
        if limit_val is not None and (not isinstance(limit_val, int) or limit_val < 1 or limit_val > max_limit):
            raise ValueError(f"limit must be 1..{max_limit}")

    def add_params(values: Iterable[Any]) -> str:
        phs = []
        for v in values:
            ph = pf.placeholder()
            phs.append(ph)
            params.append(v)
        return ", ".join(phs)

    def add_projection(table_alias: str, field_name: str) -> None:
        idr._check(field_name)
        select_bits.append(f"{idr.table(table_alias)}.{idr.column(field_name)}")

    def compile_relationship(rel: Dict[str, Any], parent_alias: str, depth: int) -> None:
        nonlocal total_joins
        if depth > max_depth:
            raise ValueError(f"Maximum relationship depth {max_depth} exceeded")

        as_alias = rel.get("as")
        join_on = rel.get("join_on") or {}
        child_table = rel.get("child_table")
        lookup_table = rel.get("lookup_table")
        through_table = rel.get("through_table")

        if through_table:
            idr._check(through_table)
            through_alias = register_table(through_table)
            heads: set[str] = set()
            for k, v in join_on.items():
                h1, _ = parse_ident(k)
                h2, _ = parse_ident(v)
                heads.add(h1); heads.add(h2)
            heads.discard(parent_alias)
            heads.discard(source_table)
            heads.discard(through_table)
            heads.discard(aliases.get(through_table, ""))
            heads.discard(aliases.get(parent_alias, ""))
            possible = [h for h in heads if h not in (parent_alias, aliases.get(through_table, through_table))]
            if not possible:
                if not as_alias:
                    raise IdentifierError("Unable to determine many_to_many target table; include it in join_on or set 'as' to the real table name.")
                target_table = as_alias
            else:
                target_table = possible[0]

            target_alias = register_table(target_table, desired_alias=as_alias)
            through_clauses: List[str] = []
            target_clauses: List[str] = []
            for left, right in join_on.items():
                l = resolve_ident(left)
                r = resolve_ident(right)
                if through_table in left or through_table in right or aliases.get(through_table, "") in (left.split(".")[0], right.split(".")[0]):
                    through_clauses.append(f"{l} = {r}")
                else:
                    target_clauses.append(f"{l} = {r}")

            if not through_clauses or not target_clauses:
                conds = " AND ".join([resolve_ident(k) + " = " + resolve_ident(v) for k, v in join_on.items()])
                join_bits.append(f" JOIN {idr.table(through_table)} {idr.table(through_alias)} ON {conds}")
                join_bits.append(f" JOIN {idr.table(target_table)} {idr.table(target_alias)} ON {conds}")
                total_joins += 2
            else:
                join_bits.append(f" JOIN {idr.table(through_table)} {idr.table(through_alias)} ON " + " AND ".join(through_clauses))
                join_bits.append(f" JOIN {idr.table(target_table)} {idr.table(target_alias)} ON " + " AND ".join(target_clauses))
                total_joins += 2

            for f in rel.get("fields", []):
                if isinstance(f, str):
                    add_projection(target_alias, f)
                elif isinstance(f, dict):
                    compile_relationship(f, target_alias, depth + 1)

        else:
            target_table = child_table or lookup_table
            if not target_table:
                raise ValueError("Relationship must define child_table, lookup_table, or through_table")
            idr._check(target_table)
            target_alias = register_table(target_table, desired_alias=as_alias)
            if not join_on:
                raise ValueError("Relationship requires join_on")
            on_clause = " AND ".join([f"{resolve_ident(l)} = {resolve_ident(r)}" for l, r in join_on.items()])
            join_bits.append(f" JOIN {idr.table(target_table)} {idr.table(target_alias)} ON {on_clause}")
            total_joins += 1
            for f in rel.get("fields", []):
                if isinstance(f, str):
                    add_projection(target_alias, f)
                elif isinstance(f, dict):
                    compile_relationship(f, target_alias, depth + 1)

        if total_joins > max_joins:
            raise ValueError(f"Maximum number of joins {max_joins} exceeded")

    for f in spec["fields"]:
        if isinstance(f, str):
            add_projection(base_alias, f)
        elif isinstance(f, dict):
            compile_relationship(f, base_alias, 1)
        else:
            raise ValueError("Unsupported field entry")

    if not select_bits:
        raise ValueError("No fields selected; refusing to emit SELECT *")

    def compile_condition(cond: Dict[str, Any]) -> str:
        field = cond["field"]
        op = cond["operator"]
        value = cond.get("value")
        field_sql = resolve_ident(field)
        if op in ("=", "!=", ">", "<", ">=", "<="):
            ph = pf.placeholder()
            params.append(value)
            return f"{field_sql} {op} {ph}"
        if op == "like":
            ph = pf.placeholder()
            params.append(value)
            return f"{field_sql} LIKE {ph}"
        if op == "ilike":
            ph = pf.placeholder()
            params.append(value)
            return f"LOWER({field_sql}) LIKE LOWER({ph})"
        if op == "in":
            if not isinstance(value, list):
                raise ValueError("IN requires an array value")
            if len(value) == 0:
                return "1=0"
            if len(value) > max_in:
                raise ValueError(f"IN list too large (>{max_in})")
            phs = add_params(value)
            return f"{field_sql} IN ({phs})"
        if op == "is":
            if value is None:
                return f"{field_sql} IS NULL"
            if isinstance(value, str) and value.lower() == "not null":
                return f"{field_sql} IS NOT NULL"
            raise ValueError("IS operator expects null or 'not null'")
        raise ValueError(f"Unsupported operator: {op}")

    where_clause = ""
    if "filter" in spec and spec["filter"]:
        def walk_filter(node: Dict[str, Any]) -> str:
            if "logic" in node and "conditions" in node:
                logic = node["logic"].upper()
                if logic not in ("AND", "OR"):
                    raise ValueError("Invalid filter.logic")
                parts = [walk_filter(c) if "logic" in c else compile_condition(c) for c in node["conditions"]]
                return "(" + f" {logic} ".join(parts) + ")"
            return compile_condition(node)
        where_clause = " WHERE " + walk_filter(spec["filter"])

    order_clause = ""
    if "order_by" in spec and spec["order_by"]:
        order_bits = []
        for o in spec["order_by"]:
            if "field" in o:
                field_ref = o["field"]
            else:
                t = o.get("table"); c = o.get("column")
                if not t or not c:
                    raise ValueError("order_by requires either 'field' or both 'table' and 'column'")
                idr._check(t); idr._check(c)
                field_ref = f"{t}.{c}"
            direction = (o.get("direction") or "asc").upper()
            if direction not in ("ASC", "DESC"):
                raise ValueError("Invalid order_by direction")
            field_sql = resolve_ident(field_ref)
            order_bits.append(f"{field_sql} {direction}")
        if order_bits:
            order_clause = " ORDER BY " + ", ".join(order_bits)

    sql_tail = ""
    lim = spec.get("limit")
    off = spec.get("offset")
    ensure_limit(lim)
    if lim:
        sql_tail += " LIMIT " + pf.placeholder()
        params.append(lim)
    if off is not None:
        if not isinstance(off, int) or off < 0:
            raise ValueError("offset must be a non-negative integer")
        sql_tail += " OFFSET " + pf.placeholder()
        params.append(off)

    select_clause = "SELECT " + ", ".join(select_bits)
    from_clause = f" FROM {idr.table(source_table)} {idr.table(base_alias)}"
    sql = select_clause + from_clause + "".join(join_bits) + where_clause + order_clause + sql_tail
    return SQL(text=sql, params=params)


__all__ = ["compile_query", "SQL", "IdentifierResolver", "IdentifierError", "ParamStyle"]
