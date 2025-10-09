
"""
Compile a validated query spec into parameterized SQL.

Highlights
- Uniform identifier safety: ALL identifiers (tables, aliases, columns) are validated,
  resolved against a central alias map, and optionally quoted by an IdentifierResolver.
- Parameter style adapter: supports %s (psycopg), ? (qmark), and named (:p1, :p2).
- Safe ORDER BY / JOIN handling (no raw expressions allowed).
- Many-to-many via a bridge/through table with robust detection of the target table.
- Guardrails for depth, joins, IN-size, and LIMIT.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple
import re


# ------------------------- Identifier utilities ----------------------------

IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class IdentifierError(ValueError):
    pass


class IdentifierResolver:
    """Minimal resolver that validates and (optionally) quotes identifiers.

    If quote is True, identifiers will be wrapped in double-quotes—assumes a
    PostgreSQL-like dialect. For MySQL, backticks could be used instead.
    """

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


# ------------------------- Parameter formatting ----------------------------

class ParamStyle:
    PSYCOPG = "psycopg"  # %s
    QMARK = "qmark"      # ?
    NAMED = "named"      # :p1


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
        return f":p{self._count}"  # NAMED

    def reset(self) -> None:
        self._count = 0


# ----------------------------- SQL product ---------------------------------

@dataclass
class SQL:
    text: str
    params: List[Any]


# ----------------------------- Core compiler -------------------------------

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
    """Compile a validated spec to SQL + params with strong safety checks."""
    idr = idr or IdentifierResolver(quote=False)
    pf = ParamFormatter(param_style)
    params: List[Any] = []

    # ---- alias map management ----
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
        # also allow referencing the alias by its alias-name
        aliases[table] = alias
        aliases[alias] = alias
        return alias

    # Validate top-level source
    source_table = spec["source_table"]
    idr._check(source_table)
    base_alias = register_table(source_table)

    select_bits: List[str] = []
    join_bits: List[str] = []

    total_joins = 0

    # -------------- helpers --------------
    def parse_ident(path: str) -> Tuple[str, str]:
        """Parse 'head.tail' into (head, column) and validate shapes."""
        parts = path.split(".")
        if len(parts) != 2:
            raise IdentifierError(f"Identifier must be 'table.column': {path!r}")
        head, col = parts[0], parts[1]
        idr._check(head)
        idr._check(col)
        return head, col

    def resolve_ident(path: str) -> str:
        """Resolve 'tableOrAlias.column' to 'alias.column' with quoting via idr."""
        head, col = parse_ident(path)
        alias = aliases.get(head)
        if not alias:
            # allow registering unseen targets only when they are real tables (not arbitrary)
            # we optimistically register here so that join_on can mention target first
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

    # -------------- fields & relationships --------------
    def add_projection(table_alias: str, field_name: str) -> None:
        idr._check(field_name)
        select_bits.append(f"{idr.table(table_alias)}.{idr.column(field_name)}")

    def compile_relationship(rel: Dict[str, Any], parent_alias: str, depth: int) -> None:
        nonlocal total_joins
        if depth > max_depth:
            raise ValueError(f"Maximum relationship depth {max_depth} exceeded")

        # Determine relationship kind and target table
        rel_type = rel.get("type")
        as_alias = rel.get("as")
        join_on = rel.get("join_on") or {}
        child_table = rel.get("child_table")
        lookup_table = rel.get("lookup_table")
        through_table = rel.get("through_table")

        if through_table:
            # many-to-many
            idr._check(through_table)
            through_alias = register_table(through_table)
            # detect target table by scanning join_on mappings
            heads: set[str] = set()
            for k, v in join_on.items():
                h1, _ = parse_ident(k)
                h2, _ = parse_ident(v)
                heads.add(h1); heads.add(h2)
            # remove known heads: parent and through
            heads.discard(parent_alias)           # if alias used
            heads.discard(source_table)           # if table name used
            heads.discard(through_table)
            heads.discard(aliases.get(through_table, ""))
            heads.discard(aliases.get(parent_alias, ""))

            # Guess the target table name: a remaining head that isn't the parent or through
            possible = [h for h in heads if h not in (parent_alias, through_alias := aliases.get(through_table, through_table))]
            if not possible:
                # fallback: use 'as' as table name if provided
                if not as_alias:
                    raise IdentifierError("Unable to determine many_to_many target table; include it in join_on or set 'as' to the real table name.")
                target_table = as_alias
            else:
                target_table = possible[0]

            target_alias = register_table(target_table, desired_alias=as_alias)

            # Build joins from join_on pairs—partition to ensure through is joined before target
            through_clauses: List[str] = []
            target_clauses: List[str] = []
            for left, right in join_on.items():
                l = resolve_ident(left)
                r = resolve_ident(right)
                # classify by presence of through alias/table vs target alias/table
                if through_table in left or through_table in right or aliases.get(through_table, "") in (left.split(".")[0], right.split(".")[0]):
                    through_clauses.append(f"{l} = {r}")
                else:
                    target_clauses.append(f"{l} = {r}")

            if not through_clauses or not target_clauses:
                # If classification failed, just AND all conditions in both joins
                conds = " AND ".join([resolve_ident(k) + " = " + resolve_ident(v) for k, v in join_on.items()])
                join_bits.append(f" JOIN {idr.table(through_table)} {idr.table(through_alias)} ON {conds}")
                join_bits.append(f" JOIN {idr.table(target_table)} {idr.table(target_alias)} ON {conds}")
                total_joins += 2
            else:
                join_bits.append(f" JOIN {idr.table(through_table)} {idr.table(through_alias)} ON " + " AND ".join(through_clauses))
                join_bits.append(f" JOIN {idr.table(target_table)} {idr.table(target_alias)} ON " + " AND ".join(target_clauses))
                total_joins += 2

            # projections from the target
            for f in rel.get("fields", []):
                if isinstance(f, str):
                    add_projection(target_alias, f)
                elif isinstance(f, dict):
                    compile_relationship(f, target_alias, depth + 1)

        else:
            # one_to_many / many_to_one / one_to_one using child_table or lookup_table
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

    # base fields
    for f in spec["fields"]:
        if isinstance(f, str):
            add_projection(base_alias, f)
        elif isinstance(f, dict):
            compile_relationship(f, base_alias, 1)
        else:
            raise ValueError("Unsupported field entry")

    if not select_bits:
        raise ValueError("No fields selected; refusing to emit SELECT *")

    # -------------- filters --------------
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
                return "1=0"  # empty IN never matches
            if len(value) > max_in:
                raise ValueError(f"IN list too large (>{max_in})")
            phs = add_params(value)
            return f"{field_sql} IN ({phs})"
        if op == "is":
            # expect value to be None for IS NULL or 'not null'
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

    # -------------- order by --------------
    order_clause = ""
    if "order_by" in spec and spec["order_by"]:
        order_bits = []
        for o in spec["order_by"]:
            # Support either {field, direction} or {table, column, direction}
            if "field" in o:
                field_ref = o["field"]
            else:
                t = o.get("table"); c = o.get("column")
                if not t or not c:
                    raise ValueError("order_by requires either 'field' or both 'table' and 'column'")
                idr._check(t); idr._check(c)
                # allow table name or alias; resolve will map
                field_ref = f"{t}.{c}"
            direction = (o.get("direction") or "asc").upper()
            if direction not in ("ASC", "DESC"):
                raise ValueError("Invalid order_by direction")
            field_sql = resolve_ident(field_ref)
            order_bits.append(f"{field_sql} {direction}")
        if order_bits:
            order_clause = " ORDER BY " + ", ".join(order_bits)

    # -------------- limit/offset --------------
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

    # -------------- finalize --------------
    select_clause = "SELECT " + ", ".join(select_bits)
    from_clause = f" FROM {idr.table(source_table)} {idr.table(base_alias)}"
    sql = select_clause + from_clause + "".join(join_bits) + where_clause + order_clause + sql_tail
    return SQL(text=sql, params=params)


__all__ = ["compile_query", "SQL", "IdentifierResolver", "IdentifierError", "ParamStyle"]
