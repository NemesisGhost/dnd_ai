"""Registry of where shared world canon is gated (docs/adr/0020-scoped-system-world-and-campaign-roles.md).

World authority is enforced in two places and this pins both, so a route or command added later
cannot silently skip the world check (checkpoints CP-4b and CP-4e of the Phase 14/15 integration):

- **reads of the private side of canon** are gated by the route dependency
  (`require_campaign_capability(..., world_capability=...)`): the exact set of routes is pinned
  below, each with its capability;
- **writes** are gated inside the command by `lock_authoring_scope(world_capability=...)` under the
  world lock. Every call site names the capability explicitly, and the only ones that pass `None`
  are the campaign-originated exceptions and the campaign-state wrapper, pinned below.

The per-record eligibility previews and the lifecycle action mapping must agree with the commands,
so the mapping is checked to cover every lifecycle action.
"""

import ast
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import APIRouter
from fastapi.routing import APIRoute

from dnd_ai.api.app import create_app
from dnd_ai.domain import entity_lifecycle
from dnd_ai.domain.record_authoring import (
    ALL_ACTIONS,
    CAMPAIGN_ORIGINATED_TYPES,
    LIFECYCLE_ACTION_CAPABILITIES,
)

pytestmark = pytest.mark.unit

READ_PRIVATE = "world.canon.read_private"

# Reads of the private side of shared canon: drafts, GM-only preparation, revisions, provenance,
# sources, the review queue, and the authoring catalogs that only an author uses. All need campaign
# `canon.edit` and `world.canon.read_private`. A campaign-originated record's own authoring read
# (player-character identity, item instances), the lifecycle read of such a record, and every
# campaign-state operation are deliberately absent: they are campaign-authorized.
EXPECTED_PRIVATE_READS: frozenset[str] = frozenset(
    {
        "/authoring/dungeon-areas/{dungeon_area_id}",
        "/authoring/dungeons/options",
        "/authoring/dungeons/{dungeon_id}",
        "/authoring/item-definitions",
        "/authoring/item-definitions/{definition_id}",
        "/authoring/knowledge/options",
        "/authoring/knowledge/subject-options",
        "/authoring/knowledge/{knowledge_item_id}",
        "/authoring/locations/options",
        "/authoring/locations/parent-options",
        "/authoring/locations/{location_id}",
        "/authoring/npcs/options",
        "/authoring/npcs/{npc_id}",
        "/authoring/npcs/{npc_id}/portrayal",
        "/authoring/organizations/options",
        "/authoring/organizations/parent-options",
        "/authoring/organizations/{organization_id}",
        "/authoring/quests/options",
        "/authoring/quests/target-options",
        "/authoring/quests/{quest_id}",
        "/authoring/relationships",
        "/authoring/relationships/options",
        "/authoring/relationships/{relationship_id}",
        "/authoring/religions/options",
        "/authoring/religions/reference-options",
        "/authoring/religions/{religion_id}",
        "/entities/{entity_id}/provenance",
        "/entities/{entity_id}/revisions",
        "/entities/{entity_id}/revisions/compare",
        "/review-queue",
        "/sources",
    }
)

# `lock_authoring_scope` call sites that pass `world_capability=None`: item instances (decision
# E2), the campaign-state wrapper `lock_operation_scope` (world-time points E1 and every runtime
# operation), and the shared identity helper, which passes None only for a player character (E3).
EXPECTED_CAMPAIGN_ONLY_SCOPES: frozenset[tuple[str, str]] = frozenset(
    {
        ("item_instances.py", "create_item_instance"),
        ("item_instances.py", "update_item_instance"),
        ("_operations.py", "lock_operation_scope"),
    }
)

COMMANDS = Path(__file__).resolve().parents[2] / "src" / "dnd_ai" / "commands"


def _iter_api_routes(routes: list[object]) -> Iterator[APIRoute]:
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        elif hasattr(route, "original_router"):
            yield from _iter_api_routes(route.original_router.routes)
        elif isinstance(route, APIRouter):
            yield from _iter_api_routes(route.routes)


def test_exactly_the_private_reads_are_gated_by_the_world_capability() -> None:
    gated: dict[tuple[str, str], str] = {}
    for route in _iter_api_routes(create_app().routes):
        for dependency in route.dependant.dependencies:
            if "require_campaign_capability" not in getattr(dependency.call, "__qualname__", ""):
                continue
            capability = getattr(dependency.call, "world_capability", None)
            if capability is None:
                continue
            for method in route.methods or ():
                if method not in ("HEAD", "OPTIONS"):
                    gated[(method, route.path)] = capability
    prefix = "/campaigns/{campaign_id}"
    assert {path.removeprefix(prefix) for _, path in gated} == EXPECTED_PRIVATE_READS
    assert {method for method, _ in gated} == {"GET"}, "a write is gated inside its command"
    assert set(gated.values()) == {READ_PRIVATE}


def _scope_calls() -> Iterator[tuple[str, str, ast.Call]]:
    for path in sorted(COMMANDS.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for function in ast.walk(tree):
            if not isinstance(function, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for node in ast.walk(function):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "lock_authoring_scope"
                ):
                    yield path.name, function.name, node


def test_every_authoring_scope_names_its_world_capability_and_only_the_exceptions_pass_none() -> (
    None
):
    campaign_only: set[tuple[str, str]] = set()
    seen = 0
    for module, function, call in _scope_calls():
        seen += 1
        keywords = {kw.arg: kw.value for kw in call.keywords}
        assert "world_capability" in keywords, f"{module}:{function} omits world_capability"
        value = keywords["world_capability"]
        if isinstance(value, ast.Constant) and value.value is None:
            campaign_only.add((module, function))
    assert seen >= 15, "the scan found no scope calls: the helper moved"
    assert campaign_only == EXPECTED_CAMPAIGN_ONLY_SCOPES


def test_the_campaign_originated_types_are_exactly_player_character_identity_and_item_instances() -> (
    None
):
    assert {"player_character", "item_instance"} == CAMPAIGN_ORIGINATED_TYPES


def test_every_lifecycle_action_has_a_world_capability() -> None:
    actions = {
        value
        for name, value in vars(entity_lifecycle).items()
        if name
        in {
            "SUBMIT_FOR_REVIEW",
            "RETURN_TO_DRAFT",
            "APPROVE",
            "REJECT",
            "PUBLISH",
            "SUPERSEDE",
            "ARCHIVE",
            "RESTORE",
            "DELETE_DRAFT",
        }
    }
    assert len(actions) == 9
    assert set(LIFECYCLE_ACTION_CAPABILITIES) == actions
    assert ALL_ACTIONS not in LIFECYCLE_ACTION_CAPABILITIES
