"""Pure contract for Quest definition authoring (Phase 15.1)."""

import pytest

from dnd_ai.domain.authoring import AuthoringValidationError
from dnd_ai.domain.content_authoring import AUTHORABLE_LOCATION_CATEGORIES
from dnd_ai.domain.entity_lifecycle import ENTITY_LIFECYCLE_ELIGIBLE_TYPE_CODES
from dnd_ai.domain.organization_authoring import ORGANIZATION_ENTITY_TYPE_CODES
from dnd_ai.domain.quest_authoring import (
    COMPLETION_MODES,
    OBJECTIVE_TARGET_TYPE_CODES,
    QUANTITY_MAX,
    REQUIREMENT_LEVELS,
    STAGE_TYPES,
    STRUCTURAL_OBJECTIVE_FIELDS,
    VISIBILITY_POLICIES,
    normalize_objective_fields,
    normalize_stage_fields,
)

OBJECTIVE = {
    "name": "Reach the ruin",
    "description": None,
    "objective_type": "reach_location",
    "requirement_level": "required",
    "completion_mode": "automatic",
    "visibility_policy": "visible",
    "quantity_required": None,
}


def test_vocabularies_mirror_the_table_checks() -> None:
    assert [c for c, _ in STAGE_TYPES] == [
        "sequential",
        "optional",
        "conditional",
        "mutually_exclusive",
    ]
    assert [c for c, _ in REQUIREMENT_LEVELS] == ["required", "optional", "hidden"]
    assert [c for c, _ in COMPLETION_MODES] == ["automatic", "gm_confirmed"]
    assert [c for c, _ in VISIBILITY_POLICIES] == [
        "visible",
        "hidden_until_active",
        "hidden_until_discovered",
        "gm_only",
    ]


def test_targets_are_a_closed_set_of_in_scope_definitions() -> None:
    assert AUTHORABLE_LOCATION_CATEGORIES <= OBJECTIVE_TARGET_TYPE_CODES
    assert ORGANIZATION_ENTITY_TYPE_CODES <= OBJECTIVE_TARGET_TYPE_CODES
    assert {"religion", "npc", "knowledge_item"} <= OBJECTIVE_TARGET_TYPE_CODES
    assert OBJECTIVE_TARGET_TYPE_CODES.isdisjoint(
        {"quest", "dungeon", "dungeon_area", "event", "character"}
    )
    # Everything but a knowledge item is already lifecycle-managed.
    assert {"knowledge_item"} == OBJECTIVE_TARGET_TYPE_CODES - ENTITY_LIFECYCLE_ELIGIBLE_TYPE_CODES


def test_structure_fields_are_the_ones_whose_change_rewrites_progress() -> None:
    assert {
        "objective_type",
        "requirement_level",
        "completion_mode",
        "quantity_required",
        "target_entity_id",
    } == STRUCTURAL_OBJECTIVE_FIELDS


def test_stage_fields() -> None:
    fields = normalize_stage_fields(name="  Opening ", description="  ", stage_type="optional")
    assert (fields.name, fields.description, fields.stage_type) == ("Opening", None, "optional")
    for bad in ({"name": ""}, {"name": "x" * 201}, {"stage_type": "boss"}, {"stage_type": None}):
        with pytest.raises(AuthoringValidationError):
            normalize_stage_fields(
                **{"name": "x", "description": None, "stage_type": "sequential", **bad}
            )  # type: ignore[arg-type]


def test_objective_fields() -> None:
    fields = normalize_objective_fields(**OBJECTIVE)
    assert (fields.name, fields.quantity_required) == ("Reach the ruin", None)
    assert (
        normalize_objective_fields(
            **{**OBJECTIVE, "quantity_required": QUANTITY_MAX}
        ).quantity_required
        == QUANTITY_MAX
    )


@pytest.mark.parametrize(
    "override",
    [
        {"name": " "},
        {"objective_type": ""},
        {"objective_type": "x" * 65},
        {"requirement_level": "mandatory"},
        {"completion_mode": "magic"},
        {"visibility_policy": "secret"},
        {"quantity_required": 0},
        {"quantity_required": -1},
        {"quantity_required": QUANTITY_MAX + 1},
        {"quantity_required": True},
        {"quantity_required": "3"},
    ],
)
def test_invalid_objective_fields_are_refused(override: dict) -> None:
    with pytest.raises(AuthoringValidationError):
        normalize_objective_fields(**{**OBJECTIVE, **override})  # type: ignore[arg-type]
