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


ENGINE_REQUEST_SCOPED = "engine_request_scoped"
ENGINE_TWO_PHASE = "engine_two_phase"
ENGINE_CLAIM_WORK = "engine_claim_work"


def classify(record: dict[str, Any]) -> str:
    """The R01 family of a manifest record (plan section 7.1 / 8 / 10), or `unclassified`."""
    if (str(record.get("method")), str(record.get("path"))) in E1_ROUTES:
        return ENGINE_REQUEST_SCOPED
    if (str(record.get("method")), str(record.get("path"))) in E2_ROUTES:
        return ENGINE_TWO_PHASE
    if (str(record.get("method")), str(record.get("path"))) in E3_ROUTES:
        return ENGINE_CLAIM_WORK
    if (str(record.get("method")), str(record.get("path"))) in _C11S02_ROUTES:
        return "access_management"
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
#: S1. S2 migrates the six profile and revelation routes; S3 the 71 definition authoring and lifecycle routes; S4 the 54 campaign operation routes. A route moves here from the pending set,
#: never silently.
_PROFILE = "/campaigns/{campaign_id}/characters/{character_id}/public-profile"
_REVELATIONS = "/campaigns/{campaign_id}/characters/{character_id}/revelations"
#: S3 migrates the 71 definition authoring and lifecycle routes (manifest family `authoring_scope`).
_CAMPAIGN = "/campaigns/{campaign_id}"
_AUTHORING = _CAMPAIGN + "/authoring"
_S3_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", _AUTHORING + "/dungeon-areas/{dungeon_area_id}/update"),
        ("POST", _AUTHORING + "/dungeons"),
        ("POST", _AUTHORING + "/dungeons/{dungeon_id}/areas"),
        ("POST", _AUTHORING + "/dungeons/{dungeon_id}/connections"),
        ("POST", _AUTHORING + "/dungeons/{dungeon_id}/connections/{area_connection_id}/remove"),
        ("POST", _AUTHORING + "/dungeons/{dungeon_id}/connections/{area_connection_id}/update"),
        ("POST", _AUTHORING + "/dungeons/{dungeon_id}/features"),
        ("POST", _AUTHORING + "/dungeons/{dungeon_id}/features/{child_id}/remove"),
        ("POST", _AUTHORING + "/dungeons/{dungeon_id}/features/{child_id}/update"),
        ("POST", _AUTHORING + "/dungeons/{dungeon_id}/hazards"),
        ("POST", _AUTHORING + "/dungeons/{dungeon_id}/hazards/{child_id}/remove"),
        ("POST", _AUTHORING + "/dungeons/{dungeon_id}/hazards/{child_id}/update"),
        ("POST", _AUTHORING + "/dungeons/{dungeon_id}/interactables"),
        ("POST", _AUTHORING + "/dungeons/{dungeon_id}/interactables/{child_id}/remove"),
        ("POST", _AUTHORING + "/dungeons/{dungeon_id}/interactables/{child_id}/update"),
        ("POST", _AUTHORING + "/dungeons/{dungeon_id}/update"),
        ("POST", _AUTHORING + "/item-definitions"),
        ("POST", _AUTHORING + "/item-definitions/{definition_id}/update"),
        ("POST", _AUTHORING + "/items"),
        ("POST", _AUTHORING + "/items/{item_instance_id}/update"),
        ("POST", _AUTHORING + "/knowledge"),
        ("POST", _AUTHORING + "/knowledge/{knowledge_item_id}/update"),
        ("POST", _AUTHORING + "/locations"),
        ("POST", _AUTHORING + "/locations/{location_id}/update"),
        ("POST", _AUTHORING + "/npcs"),
        ("POST", _AUTHORING + "/npcs/{npc_id}/detail-level"),
        ("POST", _AUTHORING + "/npcs/{npc_id}/portrayal"),
        ("POST", _AUTHORING + "/npcs/{npc_id}/update"),
        ("POST", _AUTHORING + "/organizations"),
        ("POST", _AUTHORING + "/organizations/{organization_id}/update"),
        ("POST", _AUTHORING + "/player-characters"),
        ("POST", _AUTHORING + "/player-characters/{player_character_id}/update"),
        ("POST", _AUTHORING + "/quests"),
        ("POST", _AUTHORING + "/quests/{quest_id}/dependencies"),
        ("POST", _AUTHORING + "/quests/{quest_id}/dependencies/{dependency_id}/remove"),
        ("POST", _AUTHORING + "/quests/{quest_id}/outcomes"),
        ("POST", _AUTHORING + "/quests/{quest_id}/outcomes/{outcome_id}/remove"),
        ("POST", _AUTHORING + "/quests/{quest_id}/outcomes/{outcome_id}/rewards"),
        ("POST", _AUTHORING + "/quests/{quest_id}/outcomes/{outcome_id}/update"),
        ("POST", _AUTHORING + "/quests/{quest_id}/participants"),
        ("POST", _AUTHORING + "/quests/{quest_id}/participants/{participant_id}/remove"),
        ("POST", _AUTHORING + "/quests/{quest_id}/rewards/{reward_id}/remove"),
        ("POST", _AUTHORING + "/quests/{quest_id}/stages"),
        ("POST", _AUTHORING + "/quests/{quest_id}/stages/reorder"),
        ("POST", _AUTHORING + "/quests/{quest_id}/stages/{stage_id}/objectives"),
        (
            "POST",
            _AUTHORING + "/quests/{quest_id}/stages/{stage_id}/objectives/{objective_id}/remove",
        ),
        (
            "POST",
            _AUTHORING + "/quests/{quest_id}/stages/{stage_id}/objectives/{objective_id}/update",
        ),
        ("POST", _AUTHORING + "/quests/{quest_id}/stages/{stage_id}/remove"),
        ("POST", _AUTHORING + "/quests/{quest_id}/stages/{stage_id}/update"),
        ("POST", _AUTHORING + "/quests/{quest_id}/update"),
        ("POST", _AUTHORING + "/relationships"),
        ("POST", _AUTHORING + "/relationships/{relationship_id}/archive"),
        ("POST", _AUTHORING + "/relationships/{relationship_id}/change-office"),
        ("POST", _AUTHORING + "/relationships/{relationship_id}/end"),
        ("POST", _AUTHORING + "/relationships/{relationship_id}/perspectives"),
        ("POST", _AUTHORING + "/relationships/{relationship_id}/restore"),
        ("POST", _AUTHORING + "/relationships/{relationship_id}/update"),
        ("POST", _AUTHORING + "/religions"),
        ("POST", _AUTHORING + "/religions/{religion_id}/update"),
        ("POST", _CAMPAIGN + "/entities/{entity_id}/lifecycle/approve"),
        ("POST", _CAMPAIGN + "/entities/{entity_id}/lifecycle/archive"),
        ("POST", _CAMPAIGN + "/entities/{entity_id}/lifecycle/delete-draft"),
        ("POST", _CAMPAIGN + "/entities/{entity_id}/lifecycle/publish"),
        ("POST", _CAMPAIGN + "/entities/{entity_id}/lifecycle/reject"),
        ("POST", _CAMPAIGN + "/entities/{entity_id}/lifecycle/restore"),
        ("POST", _CAMPAIGN + "/entities/{entity_id}/lifecycle/return-to-draft"),
        ("POST", _CAMPAIGN + "/entities/{entity_id}/lifecycle/submit-for-review"),
        ("POST", _CAMPAIGN + "/entities/{entity_id}/lifecycle/supersede"),
        ("POST", _CAMPAIGN + "/entities/{entity_id}/sources/attach"),
        ("POST", _CAMPAIGN + "/entities/{entity_id}/sources/detach"),
        ("POST", _CAMPAIGN + "/sources"),
    }
)

#: S4 migrates the 54 campaign operation routes (manifest family `operation_scope`, plan section 7.1).
_S4_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", _CAMPAIGN + "/authoring/characters/{character_id}/builds"),
        ("POST", _CAMPAIGN + "/authoring/characters/{character_id}/builds/{build_id}/activate"),
        ("POST", _CAMPAIGN + "/authoring/characters/{character_id}/state/initialize"),
        ("POST", _CAMPAIGN + "/clock/advance"),
        ("POST", _CAMPAIGN + "/clock/correct"),
        ("POST", _CAMPAIGN + "/dungeon-areas/{dungeon_area_id}/state"),
        ("POST", _CAMPAIGN + "/encounters/prepare"),
        ("POST", _CAMPAIGN + "/encounters/{encounter_id}/abort"),
        ("POST", _CAMPAIGN + "/encounters/{encounter_id}/participants"),
        ("POST", _CAMPAIGN + "/encounters/{encounter_id}/participants/{participant_id}/remove"),
        ("POST", _CAMPAIGN + "/encounters/{encounter_id}/participants/{participant_id}/update"),
        ("POST", _CAMPAIGN + "/encounters/{encounter_id}/start"),
        ("POST", _CAMPAIGN + "/encounters/{encounter_id}/update"),
        ("POST", _CAMPAIGN + "/events/{event_id}/correct"),
        ("POST", _CAMPAIGN + "/events/{event_id}/void"),
        ("POST", _CAMPAIGN + "/items/{item_instance_id}/attune"),
        ("POST", _CAMPAIGN + "/items/{item_instance_id}/award"),
        ("POST", _CAMPAIGN + "/items/{item_instance_id}/consume"),
        ("POST", _CAMPAIGN + "/items/{item_instance_id}/damage"),
        ("POST", _CAMPAIGN + "/items/{item_instance_id}/destroy"),
        ("POST", _CAMPAIGN + "/items/{item_instance_id}/end-attunement"),
        ("POST", _CAMPAIGN + "/items/{item_instance_id}/equip"),
        ("POST", _CAMPAIGN + "/items/{item_instance_id}/repair"),
        ("POST", _CAMPAIGN + "/items/{item_instance_id}/unequip"),
        ("POST", _CAMPAIGN + "/knowledge/knowers/{entity_knowledge_id}/belief"),
        ("POST", _CAMPAIGN + "/knowledge/{knowledge_item_id}/learn"),
        ("POST", _CAMPAIGN + "/knowledge/{knowledge_item_id}/make-public"),
        ("POST", _CAMPAIGN + "/knowledge/{knowledge_item_id}/reveal-to-party"),
        ("POST", _CAMPAIGN + "/knowledge/{knowledge_item_id}/transfer"),
        ("POST", _CAMPAIGN + "/parties"),
        ("POST", _CAMPAIGN + "/parties/{party_id}/archive"),
        ("POST", _CAMPAIGN + "/parties/{party_id}/members"),
        ("POST", _CAMPAIGN + "/parties/{party_id}/members/{party_membership_id}/end"),
        ("POST", _CAMPAIGN + "/parties/{party_id}/restore"),
        ("POST", _CAMPAIGN + "/parties/{party_id}/update"),
        ("POST", _CAMPAIGN + "/quests/objectives/{quest_objective_id}/status"),
        ("POST", _CAMPAIGN + "/quests/{quest_id}/abandon"),
        ("POST", _CAMPAIGN + "/quests/{quest_id}/activate"),
        ("POST", _CAMPAIGN + "/quests/{quest_id}/complete"),
        ("POST", _CAMPAIGN + "/quests/{quest_id}/fail"),
        ("POST", _CAMPAIGN + "/quests/{quest_id}/resume"),
        ("POST", _CAMPAIGN + "/quests/{quest_id}/suspend"),
        ("POST", _CAMPAIGN + "/sessions"),
        ("POST", _CAMPAIGN + "/sessions/{session_id}/archive"),
        ("POST", _CAMPAIGN + "/sessions/{session_id}/end"),
        ("POST", _CAMPAIGN + "/sessions/{session_id}/log"),
        ("POST", _CAMPAIGN + "/sessions/{session_id}/participants"),
        ("POST", _CAMPAIGN + "/sessions/{session_id}/participants/{session_participant_id}/remove"),
        ("POST", _CAMPAIGN + "/sessions/{session_id}/restore"),
        ("POST", _CAMPAIGN + "/sessions/{session_id}/start"),
        ("POST", _CAMPAIGN + "/sessions/{session_id}/travel"),
        ("POST", _CAMPAIGN + "/sessions/{session_id}/update"),
        ("POST", _CAMPAIGN + "/travel"),
        ("POST", _CAMPAIGN + "/world-times"),
    }
)

#: S4b migrates the 21 route-capability-only write routes (manifest family `route_capability_only`, plan
#: section 7.3): S4b-1 character state, S4b-2 interactions and encounters, S4b-3 item, organization, quest
#: and relationship runtime state, S4b-4 integration, S4b-5 the reference-corpus source register and remove,
#: S4b-6 the Foundry pairing code's creation.
_S4B_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", _CAMPAIGN + "/characters/{character_id}/conditions"),
        ("POST", _CAMPAIGN + "/characters/{character_id}/conditions/{condition_id}/remove"),
        ("POST", _CAMPAIGN + "/characters/{character_id}/hit-points"),
        ("POST", _CAMPAIGN + "/characters/{character_id}/location"),
        ("POST", _CAMPAIGN + "/characters/{character_id}/resources"),
        ("POST", _CAMPAIGN + "/checks/{check_request_id}/resolve"),
        ("POST", _CAMPAIGN + "/encounters"),
        ("POST", _CAMPAIGN + "/encounters/{encounter_id}/end"),
        ("POST", _CAMPAIGN + "/encounters/{encounter_id}/turns"),
        ("POST", _CAMPAIGN + "/events"),
        ("POST", _CAMPAIGN + "/foundry/pairing-codes"),
        ("POST", _CAMPAIGN + "/integration/external-systems"),
        ("POST", _CAMPAIGN + "/integration/external-systems/{external_system_id}/identifiers"),
        ("POST", _CAMPAIGN + "/interactions"),
        ("POST", _CAMPAIGN + "/items/{item_instance_id}/identify"),
        ("POST", _CAMPAIGN + "/items/{item_instance_id}/transfer"),
        ("POST", _CAMPAIGN + "/organizations/{organization_id}/status"),
        ("POST", _CAMPAIGN + "/quests/objectives/{quest_objective_id}/advance"),
        ("POST", _CAMPAIGN + "/reference-corpus/sources"),
        ("DELETE", _CAMPAIGN + "/reference-corpus/sources/{source_document_id}"),
        ("POST", _CAMPAIGN + "/relationships/{relationship_id}/evolve"),
    }
)

#: S5-D migrates five campaign access-management routes: the two invitation routes (keyed pre-write; the
#: only pre-write routes so far, `dnd_ai.api.r01_pre_write_routes`) and the three post-write Foundry routes
#: (device revocation, connection revocation, identity link). The five world routes stay pending (not
#: finalized, not reclassified yet).
_S5D_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", _CAMPAIGN + "/invitations"),
        ("POST", _CAMPAIGN + "/invitations/{campaign_invitation_id}/revoke"),
        ("DELETE", _CAMPAIGN + "/foundry/connections/{foundry_connection_id}"),
        ("DELETE", _CAMPAIGN + "/foundry/devices/{foundry_device_id}"),
        (
            "POST",
            _CAMPAIGN + "/integration/external-systems/{external_system_id}/foundry-identities",
        ),
    }
)

#: S5-E1 migrates the three campaign lifecycle routes (update, archive, reactivate), all keyed-optional
#: pre-write plans (`dnd_ai.commands.campaign_lifecycle_plans`).
_S5E1_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", _CAMPAIGN + "/update"),
        ("POST", _CAMPAIGN + "/archive"),
        ("POST", _CAMPAIGN + "/reactivate"),
    }
)

#: S5-E2 migrates four membership routes (add member; assign, change and revoke a role), all keyed-optional
#: pre-write plans (`dnd_ai.commands.membership_role_plans`). Ownership transfer, an **unkeyed** pre-write plan
#: (`R01_UNKEYED_PRE_WRITE_ROUTES`), joined them with the owner-approved amendment (plan 6.27.4).
_S5E2_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", _CAMPAIGN + "/memberships"),
        ("POST", _CAMPAIGN + "/memberships/{campaign_membership_id}/roles"),
        ("POST", _CAMPAIGN + "/memberships/roles/{membership_role_id}/change"),
        ("POST", _CAMPAIGN + "/memberships/roles/{membership_role_id}/revoke"),
    }
)
#: S5-E2's fifth route, ownership transfer: an **unkeyed** pre-write plan (`R01_UNKEYED_PRE_WRITE_ROUTES`).
_S5E2_TRANSFER_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {("POST", _CAMPAIGN + "/ownership-transfer")}
)

#: S5-E3 migrates end campaign membership, a keyed-optional pre-write plan (`dnd_ai.commands.membership_end_plans`).
_S5E3_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {("POST", _CAMPAIGN + "/memberships/{campaign_membership_id}/end")}
)

#: S5-E4 migrates the two resource-grant routes and the three character-relationship routes, keyed-optional
#: pre-write plans (`dnd_ai.commands.access_grant_plans`).
_S5E4_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", _CAMPAIGN + "/memberships/{campaign_membership_id}/character-relationships"),
        (
            "POST",
            _CAMPAIGN + "/character-relationships/{membership_character_relationship_id}/change",
        ),
        (
            "POST",
            _CAMPAIGN + "/character-relationships/{membership_character_relationship_id}/revoke",
        ),
        ("POST", _CAMPAIGN + "/resource-grants"),
        ("POST", _CAMPAIGN + "/resource-grants/{resource_grant_id}/revoke"),
    }
)

#: S5-E5 migrates the six access-group routes, keyed-optional pre-write plans
#: (`dnd_ai.commands.access_group_plans`).
_S5E5_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", _CAMPAIGN + "/access-groups"),
        ("POST", _CAMPAIGN + "/access-groups/{access_group_id}/update"),
        ("POST", _CAMPAIGN + "/access-groups/{access_group_id}/deactivate"),
        ("POST", _CAMPAIGN + "/access-groups/{access_group_id}/reactivate"),
        ("POST", _CAMPAIGN + "/access-groups/{access_group_id}/members"),
        (
            "POST",
            _CAMPAIGN + "/access-group-memberships/{access_group_membership_id}/remove",
        ),
    }
)

#: S5-E6 migrates the two reveal-delegation routes, **unkeyed** pre-write plans
#: (`dnd_ai.commands.reveal_delegation_plans`, `R01_UNKEYED_PRE_WRITE_ROUTES`).
_S5E6_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", _CAMPAIGN + "/reveal-delegations"),
        ("POST", _CAMPAIGN + "/reveal-delegations/{grantee_campaign_membership_id}/revoke"),
    }
)

#: P15-C11-S02-T01 migrates the three control-assignment writers, **keyed** pre-write plans
#: (`dnd_ai.commands.control_assignment_plans`, `R01_KEYED_PRE_WRITE_ROUTES`). Their route requirement is only
#: `campaign.view`; the operation authority (`character.assign_control`, the built-in owner and `gm`) is a plan
#: requirement. They write `security.membership_character_relationships`, a table the authority statement reads, so
#: they belong to the pre-write access-management family and `classify()` returns `access_management` for them.
_C11S02_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", _CAMPAIGN + "/characters/{character_id}/control-assignments"),
        ("POST", _CAMPAIGN + "/characters/{character_id}/control-assignments/replace-primary"),
        ("POST", _CAMPAIGN + "/control-assignments/{control_assignment_id}/revoke"),
    }
)

#: R01 E1 migrates the proposal-review route: an **unkeyed post-write** plan on the request-owned transaction
#: (`dnd_ai.commands.ai_proposals.review_proposed_change`, `lock_operation_scope` first). It calls the operation
#: scope helper but is **not** an operation-scope route for the reservation opt-in: it has no reservation, so it
#: must stay out of `R01_DEFERRED_RESERVATION_ROUTES` (O-2's 129). `classify()` returns `engine_request_scoped`
#: for it before the scope markers are read.
E1_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {("POST", _CAMPAIGN + "/ai/proposed-changes/{ai_proposed_change_id}/review")}
)

#: R01 E2 migrates the two AI engine routes that call a provider: the request transaction is finalized and ended
#: (the early check), and the command runs two further `authorized_transaction`s (T1 before the provider call, T2
#: after it), each with its own post-write plan. Neither has a reservation, so both stay out of
#: `R01_DEFERRED_RESERVATION_ROUTES` (129). `classify()` returns `engine_two_phase` before the `early_commit` marker.
E2_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", _CAMPAIGN + "/ai/npc-conversation"),
        ("POST", _CAMPAIGN + "/ai/synthesis"),
    }
)

#: R01 E3 migrates the Foundry combat sync: the request transaction is finalized and ended (the early check), then the
#: command takes the operation's session advisory lock and runs a claim transaction and a work transaction on that one
#: connection, each with its own post-write plan (a replay is a claim that returns early). No reservation, so it stays
#: out of `R01_DEFERRED_RESERVATION_ROUTES`. `classify()` returns `engine_claim_work` before the `early_commit` marker.
E3_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {("POST", _CAMPAIGN + "/integration/foundry/combat-sync")}
)

#: R01 E4 migrates the four reference-corpus engine routes (ingest, grant, revoke, query) into their request transaction:
#: dependency, the command on the request connection, the response built, then the final check last. They stop being
#: `early_commit`, so `classify()` returns `route_capability_only` (the S4b family) and no pending route remains.
_CORPUS = _CAMPAIGN + "/reference-corpus"
E4_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", _CORPUS + "/sources/{source_document_id}/passages"),
        ("POST", _CORPUS + "/sources/{source_document_id}/grant"),
        ("DELETE", _CORPUS + "/grants/{reference_source_campaign_id}"),
        ("POST", _CORPUS + "/query"),
    }
)

#: The five world routes, an explicit **planned exclusion** from campaign-scoped R01 work (owner decision 4, plan
#: 6.21.1; S5-F bookkeeping). Neither finalized nor pending, and not migrated or accepted: their plan lookup fails
#: closed (`dnd_ai.api.r01_route_plans`). Their unkeyed-window follow-up is recorded in `docs/delivery/work-register.md`.
EXCLUDED_WORLD_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", "/worlds/{world_id}/ownership-transfer"),
        ("POST", "/worlds/{world_id}/roles"),
        ("POST", "/worlds/{world_id}/roles/{world_membership_id}/end"),
        ("POST", "/worlds/{world_id}/use-grants"),
        ("POST", "/worlds/{world_id}/use-grants/{world_use_grant_id}/revoke"),
    }
)

MIGRATED_ROUTES: frozenset[tuple[str, str]] = (
    frozenset(
        {
            ("POST", _PROFILE + "/draft"),
            ("POST", _PROFILE + "/draft/copy-legacy"),
            ("POST", _PROFILE + "/draft/copy-player-profile"),
            ("POST", _PROFILE + "/releases"),
            ("POST", _REVELATIONS),
            ("POST", _REVELATIONS + "/{character_revelation_id}/revoke"),
        }
    )
    | _S3_ROUTES
    | _S4_ROUTES
    | _S4B_ROUTES
    | _S5D_ROUTES
    | _S5E1_ROUTES
    | _S5E2_ROUTES
    | _S5E2_TRANSFER_ROUTES
    | _S5E3_ROUTES
    | _S5E4_ROUTES
    | _S5E5_ROUTES
    | _S5E6_ROUTES
    | _C11S02_ROUTES
    | E1_ROUTES
    | E2_ROUTES
    | E3_ROUTES
    | E4_ROUTES
)

#: R01 O-2 (design 1.3): the two revelation routes reserve **after** their own campaign `KEY SHARE`
#: (`_lock_caller_and_campaign`, then the fresh authority check, then `reserve()`), so they meet the ordering by
#: construction and are **not** opted in. Named here, never derived; `tests/unit/test_r01_o2_structure.py` pins both
#: halves (the AST order, and that neither route is in the deferred set).
LATE_RESERVATION_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", _REVELATIONS),
        ("POST", _REVELATIONS + "/{character_revelation_id}/revoke"),
    }
)

#: The manifest families whose finalized routes opt in to the reservation deferral (R01 O-2, AM-1).
DEFERRED_FAMILIES: frozenset[str] = frozenset(
    {"authoring_scope", "operation_scope", "reveal_authority"}
)


def deferred_reservation_routes(records: list[dict[str, Any]]) -> frozenset[tuple[str, str]]:
    """The routes that opt in: every finalized route of `DEFERRED_FAMILIES` except the late-reservation routes.
    Fails when a deferred route is excluded or in either pre-write registry (a deferred route is post-write by
    construction), or when a late route is not itself a finalized route of those families."""
    from dnd_ai.api.r01_pre_write_routes import (
        R01_KEYED_PRE_WRITE_ROUTES,
        R01_UNKEYED_PRE_WRITE_ROUTES,
    )

    family_of = {(str(r["method"]), str(r["path"])): classify(r) for r in records}
    members = frozenset(
        key
        for key, family in family_of.items()
        if family in DEFERRED_FAMILIES and key in MIGRATED_ROUTES
    )
    if not members >= LATE_RESERVATION_ROUTES:
        raise AssertionError("a late-reservation route is not a finalized deferred-family route")
    deferred = members - LATE_RESERVATION_ROUTES
    forbidden = (
        (deferred & EXCLUDED_WORLD_ROUTES)
        | (deferred & frozenset(R01_KEYED_PRE_WRITE_ROUTES))
        | (deferred & frozenset(R01_UNKEYED_PRE_WRITE_ROUTES))
    )
    if forbidden:
        raise AssertionError(f"a deferred route is excluded or pre-write: {sorted(forbidden)}")
    return deferred


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
            and (r["method"], r["path"]) not in EXCLUDED_WORLD_ROUTES
        }
    )
    migrated = sorted(MIGRATED_ROUTES)
    inside_keys = {(str(r["method"]), str(r["path"])) for r in inside}
    if not inside_keys >= EXCLUDED_WORLD_ROUTES or EXCLUDED_WORLD_ROUTES & MIGRATED_ROUTES:
        raise AssertionError(
            "the excluded world routes must be inside R01's bound and never migrated"
        )
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
        "and E1-E4 migrate routes into `R01_FINALIZED_ROUTES`. The five world routes are the **planned",
        "exclusions** (`R01_EXCLUDED_WORLD_ROUTES`): neither pending nor finalized, never migrated or accepted",
        "by R01, and their plan lookup fails closed. Routes outside R01's bound (account, authentication,",
        'Foundry pairing, timeline routes) are in no set."""',
        "",
        "from collections.abc import Mapping",
        "from types import MappingProxyType",
        "from typing import Final",
        "",
        "#: (method, route path template) -> manifest family, for every pending route.",
        "# fmt: off",
        "R01_PENDING_ROUTES: Final[Mapping[tuple[str, str], str]] = MappingProxyType(",
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
    lines += [
        "",
        "#: (method, route path template) of every planned exclusion: the five world routes (owner decision 4).",
        "#: Not finalized, not pending; an attempt to open a campaign plan for one fails closed.",
        "# fmt: off",
        "R01_EXCLUDED_WORLD_ROUTES: Final[frozenset[tuple[str, str]]] = frozenset(",
        "    {",
    ]
    for method, path in sorted(EXCLUDED_WORLD_ROUTES):
        lines.append(f'        ("{method}", "{path}"),')
    lines += ["    }", ")", "# fmt: on"]
    lines += [
        "",
        "#: (method, route path template) of every route that opts in to the reservation's deferred campaign",
        "#: foreign key (R01 O-2, AM-1): the finalized authoring, operation and reveal routes except the two",
        "#: late-reservation routes below. A keyed request defers, binds the server's outcome and takes campaign",
        "#: evidence; an unkeyed request is unchanged. Generated by `deferred_reservation_routes`.",
        "# fmt: off",
        "R01_DEFERRED_RESERVATION_ROUTES: Final[frozenset[tuple[str, str]]] = frozenset(",
        "    {",
    ]
    for method, path in sorted(deferred_reservation_routes(records)):
        lines.append(f'        ("{method}", "{path}"),')
    lines += [
        "    }",
        ")",
        "# fmt: on",
        "",
        "#: (method, route path template) of the two revelation routes that are **not** opted in: their reservation",
        "#: already follows their own campaign `KEY SHARE` (R01 design 1.2, R-C), so it cannot hold the campaign",
        "#: ahead of their access rows. Not deferred; pinned structurally.",
        "# fmt: off",
        "R01_LATE_RESERVATION_ROUTES: Final[frozenset[tuple[str, str]]] = frozenset(",
        "    {",
    ]
    for method, path in sorted(LATE_RESERVATION_ROUTES):
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
