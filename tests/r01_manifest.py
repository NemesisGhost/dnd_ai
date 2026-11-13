"""R01 S0: the route-to-command manifest generator.

Test-side tooling only (no production behavior). It reads the live FastAPI route table and the
committed source and answers, for every non-GET route: which authorization dependency guards it,
which pre-check dependencies run, which command functions the handler reaches, which scope and
authority resolvers those commands reach, which idempotency and audit helpers the route calls, and
whether it ends the request transaction early.

It is a **static** (AST plus runtime name resolution) trace. It proves the *shape* of the source, not
runtime order, and cannot see calls it cannot resolve to a module-level function (a closure local to
a handler, a function stored in a data structure, `getattr`). Unresolved call targets that look like
they could matter are listed per route under `unresolved` so a reviewer can see the limit.
"""

from __future__ import annotations

import ast
import builtins
import inspect
import json
import re
import textwrap
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from types import FunctionType, ModuleType
from typing import Any

from fastapi import APIRouter
from fastapi.routing import APIRoute

_LAYERS = ("dnd_ai.api.", "dnd_ai.commands.", "dnd_ai.queries.", "dnd_ai.domain.")

#: Functions whose presence on a call path marks an authorization-relevant step.
MARKERS: dict[str, str] = {
    "lock_authoring_scope": "scope:authoring",
    "lock_operation_scope": "scope:operation",
    "_lock_campaign_for_manage": "scope:campaign_manage",
    "_lock_and_authorize": "scope:world_access",
    "resolve_access_context": "reader:access_context",
    "resolve_world_authority": "reader:world_authority",
    "resolve_reveal_authority": "reader:reveal_authority",
    "require_world_capability_for_campaign": "reader:world_capability",
    "start_campaign_idempotency": "idempotency:campaign",
    "start_actor_idempotency": "idempotency:actor",
    "begin_idempotent_request": "idempotency:campaign",
    "begin_actor_idempotent_request": "idempotency:actor",
    "record_change_log": "audit:change_log",
    "end_request_transaction": "early_commit",
}

_SCOPE_PREFIXES = ("scope:", "reader:")


# Authentication and request-transaction plumbing: reached through `Depends(...)` references, never a
# command, and not part of the authorization-decision trace.
_PLUMBING = ("dnd_ai.api.auth", "dnd_ai.api.deps")


def _is_layer(module: str) -> bool:
    return module.startswith(_LAYERS) and not module.startswith(_PLUMBING)


def _function_source_tree(func: Callable[..., Any]) -> ast.AST | None:
    try:
        source = textwrap.dedent(inspect.getsource(func))
        return ast.parse(source)
    except (OSError, TypeError, SyntaxError, IndentationError):
        return None


def _resolve(node: ast.expr, scope: dict[str, Any]) -> Any:
    """Resolve a Name or dotted Attribute against the function's module globals, else None."""
    if isinstance(node, ast.Name):
        return scope.get(node.id)
    if isinstance(node, ast.Attribute):
        base = _resolve(node.value, scope)
        if base is not None and isinstance(base, ModuleType):
            return getattr(base, node.attr, None)
    return None


def _callee_names(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_callee_names(node.value)}.{node.attr}"
    return "<expr>"


@dataclass
class Trace:
    """What one function reaches. `commands` stops at the first command layer on each path."""

    commands: set[str] = field(default_factory=set)
    markers: set[str] = field(default_factory=set)
    unresolved: set[str] = field(default_factory=set)
    writes: set[str] = field(default_factory=set)


_WRITE_SQL = re.compile(
    r"\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+(?:ONLY\s+)?([a-z_]+\.[a-z_]+)\b", re.IGNORECASE
)


def _sql_writes(func: Callable[..., Any]) -> set[str]:
    """Tables named after INSERT INTO / UPDATE / DELETE FROM in the function's string literals.
    Static: it sees SQL written inline, not SQL assembled from names at run time."""
    tree = _function_source_tree(func)
    found: set[str] = set()
    if tree is None:
        return found
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            text_ = node.value
        elif isinstance(node, ast.JoinedStr):
            text_ = "".join(
                part.value if isinstance(part, ast.Constant) else "{}" for part in node.values
            )
        else:
            continue
        # a FOR UPDATE clause is a lock, not a write
        text_ = re.sub(r"FOR\s+(?:NO\s+KEY\s+)?UPDATE", "FOR_LOCK", text_, flags=re.IGNORECASE)
        found.update(m.lower() for m in _WRITE_SQL.findall(text_))
    return found


def _calls(func: Callable[..., Any]) -> Iterator[tuple[ast.Call, dict[str, Any]]]:
    tree = _function_source_tree(func)
    if tree is None:
        return
    scope = dict(getattr(func, "__globals__", {}))
    # Handlers built by a factory (a closure over the command) bind it as a free variable.
    code = getattr(func, "__code__", None)
    closure = getattr(func, "__closure__", None)
    if code is not None and closure:
        for var, cell in zip(code.co_freevars, closure, strict=True):
            try:
                scope[var] = cell.cell_contents
            except ValueError:
                continue
    # Names a handler binds locally to a function (nested defs) are not resolvable statically.
    for call in ast.walk(tree):
        if isinstance(call, ast.Call):
            yield call, scope


def _qual(func: Callable[..., Any]) -> str:
    return f"{func.__module__}.{func.__qualname__}"


def trace_function(
    func: Callable[..., Any],
    *,
    stop_at_commands: bool,
    seen: set[str] | None = None,
    depth: int = 0,
    max_depth: int = 8,
) -> Trace:
    """Follow resolved calls through the layered packages.

    With `stop_at_commands`, a function in `dnd_ai.commands.*` is recorded and not entered (the
    route -> command edge). Without it, everything reachable is entered, to find the markers a
    command reaches."""
    result = Trace()
    seen = seen if seen is not None else set()
    key = _qual(func)
    if key in seen or depth > max_depth:
        return result
    seen.add(key)
    result.writes |= _sql_writes(func)
    for call, scope in _calls(func):
        target = _resolve(call.func, scope)
        name = _callee_names(call.func)
        leaf = name.rsplit(".", 1)[-1]
        if leaf in MARKERS:
            result.markers.add(MARKERS[leaf])
        # A function passed as an argument (`_run(create_npc, ...)`) is reached through the helper.
        referenced = [
            _resolve(arg, scope)
            for arg in [*call.args, *(kw.value for kw in call.keywords)]
            if isinstance(arg, ast.Name | ast.Attribute)
        ]
        for passed in referenced:
            if isinstance(passed, FunctionType) and _is_layer(passed.__module__):
                if passed.__module__ == "dnd_ai.commands._shared":
                    continue
                if stop_at_commands and passed.__module__.startswith("dnd_ai.commands."):
                    result.commands.add(_qual(passed))
                    continue
                sub = trace_function(
                    passed,
                    stop_at_commands=stop_at_commands,
                    seen=seen,
                    depth=depth + 1,
                    max_depth=max_depth,
                )
                result.commands |= sub.commands
                result.markers |= sub.markers
                result.unresolved |= sub.unresolved
                result.writes |= sub.writes
        if isinstance(target, FunctionType) and _is_layer(target.__module__):
            if target.__module__ == "dnd_ai.commands._shared":
                continue  # id lookups and shared guards, not commands
            if stop_at_commands and target.__module__.startswith("dnd_ai.commands."):
                # a pre-check or scope helper in the commands layer is still a command-layer edge
                result.commands.add(_qual(target))
                continue
            sub = trace_function(
                target,
                stop_at_commands=stop_at_commands,
                seen=seen,
                depth=depth + 1,
                max_depth=max_depth,
            )
            result.commands |= sub.commands
            result.markers |= sub.markers
            result.unresolved |= sub.unresolved
            result.writes |= sub.writes
        elif target is None and isinstance(call.func, ast.Name) and not hasattr(builtins, leaf):
            # a bare name that is not a module global: a local closure or an unresolved import
            result.unresolved.add(leaf)
    return result


def _walk_dependants(dependant: Any) -> Iterator[Callable[..., Any]]:
    for sub in dependant.dependencies:
        call = sub.call
        if call is not None:
            yield call
        yield from _walk_dependants(sub)


def _closure_value(func: Callable[..., Any], name: str) -> Any:
    code = func.__code__
    if func.__closure__ is None:
        return None
    for var, cell in zip(code.co_freevars, func.__closure__, strict=True):
        if var == name:
            try:
                return cell.cell_contents
            except ValueError:
                return None
    return None


def _describe_dependency(call: Callable[..., Any]) -> dict[str, Any] | None:
    qualname = getattr(call, "__qualname__", "")
    if qualname.startswith("require_campaign_capability.<locals>."):
        return {
            "kind": "campaign_capability",
            "capability": _closure_value(call, "capability_code"),
            "world_capability": _closure_value(call, "world_capability"),
            "allow_foundry_access": _closure_value(call, "allow_foundry_access"),
            "foundry_scope": _closure_value(call, "foundry_scope"),
            "allow_archived_campaign": _closure_value(call, "allow_archived_campaign"),
        }
    module = getattr(call, "__module__", "")
    if module.startswith("dnd_ai.commands."):
        return {"kind": "command_layer_precheck", "function": _qual(call)}
    return None


def _command_scope(command: FunctionType) -> Trace:
    return trace_function(command, stop_at_commands=False)


def _iter_api_routes(routes: list[object]) -> Iterator[APIRoute]:
    """Flatten the app's route table (FastAPI wraps included routers lazily)."""
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        elif hasattr(route, "original_router"):
            yield from _iter_api_routes(route.original_router.routes)
        elif isinstance(route, APIRouter):
            yield from _iter_api_routes(route.routes)


def _route_records(app: Any) -> Iterator[APIRoute]:
    yield from _iter_api_routes(app.routes)


def build_manifest(app: Any) -> list[dict[str, Any]]:
    """One record per (path, method) for every non-GET API route."""
    records: list[dict[str, Any]] = []
    for route in _route_records(app):
        methods = sorted(route.methods - {"HEAD", "OPTIONS"})
        for method in methods:
            if method == "GET":
                continue
            records.append(_record(route, method))
    records.sort(key=lambda r: (r["path"], r["method"]))
    return records


def _record(route: APIRoute, method: str) -> dict[str, Any]:
    handler = route.endpoint
    dependencies: list[dict[str, Any]] = []
    precheck_commands: set[str] = set()
    for call in _walk_dependants(route.dependant):
        described = _describe_dependency(call)
        if described is None:
            continue
        if described["kind"] == "command_layer_precheck":
            precheck_commands.add(described["function"])
        dependencies.append(described)
    # Route dependencies that are command-layer functions are pre-checks, not commands run by the
    # handler body. Keep the two sets apart.
    handler_trace = trace_function(handler, stop_at_commands=True)
    commands = sorted(handler_trace.commands - precheck_commands)
    markers_by_command: dict[str, list[str]] = {}
    writes_by_command: dict[str, list[str]] = {}
    reached: set[str] = set()
    for qualified in commands:
        module_name, _, func_name = qualified.rpartition(".")
        module = __import__(module_name, fromlist=[func_name])
        func = getattr(module, func_name)
        scope = _command_scope(func)
        markers_by_command[qualified] = sorted(scope.markers)
        writes_by_command[qualified] = sorted(scope.writes)
        reached |= scope.markers
    pre_markers: set[str] = set()
    for qualified in sorted(precheck_commands):
        module_name, _, func_name = qualified.rpartition(".")
        module = __import__(module_name, fromlist=[func_name])
        pre_markers |= _command_scope(getattr(module, func_name)).markers
    route_markers = sorted(handler_trace.markers)
    scope_markers = sorted(m for m in reached if m.startswith(_SCOPE_PREFIXES))
    return {
        "method": method,
        "path": route.path,
        "handler": _qual(handler),
        "dependencies": sorted(
            dependencies, key=lambda d: (d["kind"], str(d.get("capability") or d.get("function")))
        ),
        "precheck_markers": sorted(pre_markers),
        "route_markers": route_markers,
        "commands": commands,
        "command_markers": markers_by_command,
        "command_writes": writes_by_command,
        "command_scope_markers": scope_markers,
        "early_commit": "early_commit" in handler_trace.markers,
        "idempotency": sorted(m for m in route_markers if m.startswith("idempotency:")),
        "audit": "audit:change_log" in route_markers,
        "unresolved": sorted(handler_trace.unresolved),
    }


def classify(record: dict[str, Any]) -> str:
    """The R01 family of a manifest record (plan section 7.1 / 8 / 10), or `unclassified`."""
    if record["early_commit"]:
        return "engine_early_commit"
    scope = set(record["command_scope_markers"]) | set(record["precheck_markers"])
    caps = {d["capability"] for d in record["dependencies"] if d["kind"] == "campaign_capability"}
    if "access.manage" in caps:
        return "access_management"
    if "reader:reveal_authority" in scope and "scope:authoring" not in scope:
        return "reveal_authority"
    if "scope:authoring" in scope and "scope:operation" not in scope:
        return "authoring_scope"
    if "scope:operation" in scope:
        return "operation_scope"
    if "scope:campaign_manage" in scope or "scope:world_access" in scope:
        return "access_management"
    if caps:
        return "route_capability_only"
    return "no_campaign_capability"


MANIFEST_PATH = Path(__file__).with_name("r01_route_manifest.json")


def render(manifest: list[dict[str, Any]]) -> str:
    """The committed file's exact text (stable key order, one record per block)."""
    records = [{**record, "family": classify(record)} for record in manifest]
    return json.dumps(records, indent=1, sort_keys=True) + "\n"


#: Routes whose handlers have been migrated to a final `AuthorizationPlan` (R01 S2 onwards). Empty in
#: S1. S2 migrates the six profile and revelation routes. A route moves here from the pending set,
#: never silently.
_PROFILE = "/campaigns/{campaign_id}/characters/{character_id}/public-profile"
_REVELATIONS = "/campaigns/{campaign_id}/characters/{character_id}/revelations"
MIGRATED_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", _PROFILE + "/draft"),
        ("POST", _PROFILE + "/draft/copy-legacy"),
        ("POST", _PROFILE + "/draft/copy-player-profile"),
        ("POST", _PROFILE + "/releases"),
        ("POST", _REVELATIONS),
        ("POST", _REVELATIONS + "/{character_revelation_id}/revoke"),
    }
)

#: The one family outside R01's bound: account, authentication, Foundry pairing, world and timeline
#: routes, none of which carries `{campaign_id}`.
OUTSIDE_R01 = "no_campaign_capability"

PENDING_ROUTES_PATH = (
    Path(__file__).resolve().parents[1] / "src" / "dnd_ai" / "api" / "r01_pending_routes.py"
)


def render_pending_routes(records: list[dict[str, Any]]) -> str:
    """The exact text of `src/dnd_ai/api/r01_pending_routes.py`: every manifest route inside R01's
    bound, split into the pending ones and the migrated ones. Generated; never edit by hand."""
    classified = [{**record, "family": classify(record)} for record in records]
    inside = [r for r in classified if r["family"] != OUTSIDE_R01]
    # A (method, path) can be registered twice (S0 found one such route); the key is unique, the
    # manifest lists both handlers.
    pending = sorted(
        {
            (str(r["method"]), str(r["path"]), str(r["family"]))
            for r in inside
            if (r["method"], r["path"]) not in MIGRATED_ROUTES
        }
    )
    migrated = sorted(MIGRATED_ROUTES)
    lines = [
        '"""R01: which write routes are still pending, and which are finalized. GENERATED.',
        "",
        "Written by `uv run python -m tests.r01_manifest` from the live route table (the S0 manifest,",
        "`tests/r01_route_manifest.json`); `tests/unit/test_r01_pending_routes.py` fails when this file",
        "is stale. Do not edit by hand.",
        "",
        "A **pending** route is in R01's bound (`campaign_id` in its path and a family) but its handler",
        "has not been migrated to a final `AuthorizationPlan`: it is **not protected** by the R01 final",
        "check, and the commit guard admits its unfinalized plan. The set only shrinks, as slices S2-S5",
        "and E1-E4 migrate routes into `R01_FINALIZED_ROUTES`. Routes outside R01's bound (account,",
        'authentication, Foundry pairing, world and timeline routes) are in neither set."""',
        "",
        "from types import MappingProxyType",
        "from typing import Final",
        "",
        "#: (method, route path template) -> manifest family, for every pending route.",
        "# fmt: off",
        "R01_PENDING_ROUTES: Final = MappingProxyType(",
        "    {",
    ]
    for method, path, family in pending:
        lines.append(f'        ("{method}", "{path}"): "{family}",')
    lines += [
        "    }",
        ")",
        "# fmt: on",
        "",
        "#: (method, route path template) of every route migrated to a final plan.",
    ]
    if not migrated:
        lines.append("R01_FINALIZED_ROUTES: Final[frozenset[tuple[str, str]]] = frozenset()")
    else:
        lines += [
            "# fmt: off",
            "R01_FINALIZED_ROUTES: Final[frozenset[tuple[str, str]]] = frozenset(",
            "    {",
        ]
        for method, path in migrated:
            lines.append(f'        ("{method}", "{path}"),')
        lines += ["    }", ")", "# fmt: on"]
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":  # python -m tests.r01_manifest  (rewrites the committed manifest)
    from dnd_ai.api.app import create_app

    built = build_manifest(create_app())
    MANIFEST_PATH.write_text(render(built), encoding="utf-8", newline="\n")
    PENDING_ROUTES_PATH.write_text(render_pending_routes(built), encoding="utf-8", newline="\n")
    print(f"wrote {MANIFEST_PATH}")
    print(f"wrote {PENDING_ROUTES_PATH}")
