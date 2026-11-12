"""R01 S1: every scope-helper call site that still passes the explicit `R01_PENDING` marker.

`lock_authoring_scope` and `lock_operation_scope` take a REQUIRED keyword `plan` (plan section 6.5,
rule 1). Until a family is migrated to a real `AuthorizationPlan` its call sites pass `R01_PENDING`,
which protects nothing. This test pins those call sites exactly, so nothing is uncovered silently:

- every call of either helper in `src` passes `plan=` (a mechanical rule the type checker also
  enforces);
- the set of `plan=R01_PENDING` call sites equals `PINNED` below. The set only shrinks: S2 to S5
  remove entries as their commands take a real plan. Adding an entry is a deliberate, reviewed edit.
"""

import ast
import inspect
from pathlib import Path

import pytest

from dnd_ai.commands._content import lock_authoring_scope
from dnd_ai.commands._operations import lock_operation_scope

pytestmark = pytest.mark.unit

SRC = Path(__file__).resolve().parents[2] / "src" / "dnd_ai"
HELPERS = {"lock_authoring_scope", "lock_operation_scope"}

#: (module relative to src/dnd_ai, enclosing function, helper called). 67 sites at S1.
PINNED: frozenset[tuple[str, str, str]] = frozenset(
    {
        ("commands/campaign_clock.py", "advance_campaign_clock", "lock_operation_scope"),
        ("commands/campaign_clock.py", "correct_campaign_clock", "lock_operation_scope"),
        ("commands/character_builds.py", "activate_character_build", "lock_operation_scope"),
        ("commands/character_builds.py", "create_character_build", "lock_operation_scope"),
        ("commands/character_builds.py", "initialize_character_state", "lock_operation_scope"),
        (
            "commands/character_public_profile.py",
            "copy_legacy_text_to_public_profile_draft",
            "lock_authoring_scope",
        ),
        (
            "commands/character_public_profile.py",
            "copy_player_profile_field_to_public_profile_draft",
            "lock_authoring_scope",
        ),
        (
            "commands/character_public_profile.py",
            "save_character_public_profile_draft",
            "lock_authoring_scope",
        ),
        ("commands/dungeon_state.py", "set_dungeon_state", "lock_operation_scope"),
        ("commands/dungeons.py", "_lock_aggregate", "lock_authoring_scope"),
        ("commands/dungeons.py", "create_dungeon", "lock_authoring_scope"),
        ("commands/dungeons.py", "create_dungeon_area", "lock_authoring_scope"),
        ("commands/dungeons.py", "update_dungeon", "lock_authoring_scope"),
        ("commands/dungeons.py", "update_dungeon_area", "lock_authoring_scope"),
        ("commands/encounter_operations.py", "abort_encounter", "lock_operation_scope"),
        ("commands/encounter_operations.py", "start_prepared_encounter", "lock_operation_scope"),
        ("commands/encounter_preparation.py", "_prepare", "lock_operation_scope"),
        ("commands/encounter_preparation.py", "create_encounter", "lock_operation_scope"),
        ("commands/entity_lifecycle.py", "_prepare", "lock_authoring_scope"),
        ("commands/entity_lifecycle.py", "supersede_entity", "lock_authoring_scope"),
        ("commands/event_corrections.py", "correct_event", "lock_operation_scope"),
        ("commands/event_corrections.py", "void_event", "lock_operation_scope"),
        ("commands/item_definitions.py", "create_item_definition", "lock_authoring_scope"),
        ("commands/item_definitions.py", "update_item_definition", "lock_authoring_scope"),
        ("commands/item_instances.py", "create_item_instance", "lock_authoring_scope"),
        ("commands/item_instances.py", "update_item_instance", "lock_authoring_scope"),
        ("commands/item_operations.py", "_scope_and_time", "lock_operation_scope"),
        ("commands/knowledge_definitions.py", "create_knowledge_item", "lock_authoring_scope"),
        ("commands/knowledge_definitions.py", "update_knowledge_item", "lock_authoring_scope"),
        ("commands/knowledge_runtime.py", "change_belief", "lock_operation_scope"),
        ("commands/knowledge_runtime.py", "make_knowledge_public", "lock_operation_scope"),
        ("commands/knowledge_runtime.py", "record_character_knowledge", "lock_operation_scope"),
        ("commands/knowledge_runtime.py", "record_knowledge_transfer", "lock_operation_scope"),
        ("commands/knowledge_runtime.py", "reveal_knowledge_to_party", "lock_operation_scope"),
        ("commands/locations.py", "create_location", "lock_authoring_scope"),
        ("commands/locations.py", "update_location", "lock_authoring_scope"),
        ("commands/npc_portrayal.py", "save_npc_portrayal_profile", "lock_authoring_scope"),
        ("commands/npc_portrayal.py", "update_npc_detail_level", "lock_authoring_scope"),
        ("commands/npcs.py", "create_character_identity", "lock_authoring_scope"),
        ("commands/npcs.py", "update_character_identity", "lock_authoring_scope"),
        ("commands/organizations.py", "create_organization", "lock_authoring_scope"),
        ("commands/organizations.py", "update_organization", "lock_authoring_scope"),
        ("commands/parties.py", "_transition", "lock_operation_scope"),
        ("commands/parties.py", "create_party", "lock_operation_scope"),
        ("commands/parties.py", "update_party", "lock_operation_scope"),
        ("commands/party_members.py", "add_party_member", "lock_operation_scope"),
        ("commands/party_members.py", "end_party_membership", "lock_operation_scope"),
        ("commands/quest_definitions.py", "_lock_quest", "lock_authoring_scope"),
        ("commands/quest_definitions.py", "create_quest", "lock_authoring_scope"),
        ("commands/quest_runtime.py", "change_quest_status", "lock_operation_scope"),
        ("commands/quest_runtime.py", "set_objective_status", "lock_operation_scope"),
        ("commands/religions.py", "create_religion", "lock_authoring_scope"),
        ("commands/religions.py", "update_religion", "lock_authoring_scope"),
        ("commands/session_authoring.py", "_transition", "lock_operation_scope"),
        ("commands/session_authoring.py", "schedule_session", "lock_operation_scope"),
        ("commands/session_authoring.py", "update_session", "lock_operation_scope"),
        ("commands/session_play.py", "add_session_participant", "lock_operation_scope"),
        ("commands/session_play.py", "end_session", "lock_operation_scope"),
        ("commands/session_play.py", "record_session_log_entry", "lock_operation_scope"),
        ("commands/session_play.py", "remove_session_participant", "lock_operation_scope"),
        ("commands/session_play.py", "start_session", "lock_operation_scope"),
        ("commands/sources.py", "_lock_pair", "lock_authoring_scope"),
        ("commands/sources.py", "create_source", "lock_authoring_scope"),
        ("commands/travel.py", "record_travel", "lock_operation_scope"),
        ("commands/world_relationships.py", "_lock_relationship", "lock_authoring_scope"),
        ("commands/world_relationships.py", "create_relationship", "lock_authoring_scope"),
        ("commands/world_time.py", "create_world_time", "lock_operation_scope"),
    }
)


def _walk() -> list[tuple[str, str, str, ast.Call]]:
    found: list[tuple[str, str, str, ast.Call]] = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            callee = getattr(node.func, "id", getattr(node.func, "attr", ""))
            if callee not in HELPERS:
                continue
            owner = node
            while owner in parents:
                owner = parents[owner]
                if isinstance(owner, ast.FunctionDef | ast.AsyncFunctionDef):
                    break
            name = owner.name if isinstance(owner, ast.FunctionDef | ast.AsyncFunctionDef) else ""
            found.append((path.relative_to(SRC).as_posix(), name, callee, node))
    return found


def test_the_plan_argument_is_required_and_keyword_only() -> None:
    for helper in (lock_authoring_scope, lock_operation_scope):
        parameter = inspect.signature(helper).parameters["plan"]
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
        assert parameter.default is inspect.Parameter.empty


def test_omitting_the_plan_is_a_type_error() -> None:
    with pytest.raises(TypeError, match="plan"):
        lock_operation_scope(object(), campaign_id=None, actor_user_id=None)  # type: ignore[arg-type,call-arg]


def test_every_call_of_a_scope_helper_in_src_passes_a_plan() -> None:
    calls = [call for _m, _f, callee, call in _walk() if callee in HELPERS]
    assert calls, "no scope-helper call found: the test lost its subject"
    missing = [
        f"{module}:{call.lineno}"
        for module, _f, _callee, call in _walk()
        if not any(keyword.arg == "plan" for keyword in call.keywords)
    ]
    assert missing == []


def test_the_r01_pending_call_sites_are_exactly_the_pinned_set() -> None:
    pending: list[tuple[str, str, str]] = []
    for module, function, callee, call in _walk():
        for keyword in call.keywords:
            if (
                keyword.arg == "plan"
                and isinstance(keyword.value, ast.Name)
                and keyword.value.id == "R01_PENDING"
            ):
                pending.append((module, function, callee))
    assert len(pending) == len(set(pending)), "two call sites share a function and helper"
    found = frozenset(pending)
    assert found - PINNED == frozenset(), "a new R01_PENDING call site (the set only shrinks)"
    assert PINNED - found == frozenset(), "a pinned call site is gone: remove it from PINNED"


def test_only_the_helper_forwarding_passes_a_real_plan_in_s1() -> None:
    """No production command passes a real plan in S1: `lock_operation_scope` forwards its own
    `plan` to `lock_authoring_scope`, and every other call site passes the pending marker."""
    real = [
        (module, function, callee)
        for module, function, callee, call in _walk()
        for keyword in call.keywords
        if keyword.arg == "plan"
        and not (isinstance(keyword.value, ast.Name) and keyword.value.id == "R01_PENDING")
    ]
    assert real == [("commands/_operations.py", "lock_operation_scope", "lock_authoring_scope")]
