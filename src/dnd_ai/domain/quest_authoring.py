"""Pure contract for Quest definition authoring (Phase 15.1, ADR 0015).

A quest definition is one aggregate: the quest entity, its ordered stages, and
each stage's objectives. Progress (`campaign.quest_state` / `objective_state`),
outcomes, rewards, participants, and objective dependencies are timeline state or
Phase 15.2 work and are not authored here. `completion_rule` (JSONB) is not
exposed: no documented evaluator consumes its structure yet, so offering it
would invite untyped input.

The closed vocabularies below mirror the table CHECK constraints
(`ck_quest_stages_stage_type`, `ck_quest_objectives_*`); the database is the
backstop. The objective *type* vocabulary is a lookup table
(`narrative.objective_types`) and is read from the database.
"""

from dataclasses import dataclass

from .authoring import AuthoringValidationError, normalize_description, normalize_name
from .content_authoring import AUTHORABLE_LOCATION_CATEGORIES
from .organization_authoring import ORGANIZATION_ENTITY_TYPE_CODES

STAGE_TYPES: tuple[tuple[str, str], ...] = (
    ("sequential", "Sequential"),
    ("optional", "Optional"),
    ("conditional", "Conditional"),
    ("mutually_exclusive", "Mutually exclusive"),
)
REQUIREMENT_LEVELS: tuple[tuple[str, str], ...] = (
    ("required", "Required"),
    ("optional", "Optional"),
    ("hidden", "Hidden"),
)
COMPLETION_MODES: tuple[tuple[str, str], ...] = (
    ("automatic", "Automatic"),
    ("gm_confirmed", "Confirmed by the GM"),
)
VISIBILITY_POLICIES: tuple[tuple[str, str], ...] = (
    ("visible", "Visible"),
    ("hidden_until_active", "Hidden until active"),
    ("hidden_until_discovered", "Hidden until discovered"),
    ("gm_only", "GM only"),
)

QUANTITY_MAX = 1_000_000

# Entity types an objective may target (the dungeon-element targets are not
# offered). `knowledge_item` joins when knowledge-item authoring lands.
OBJECTIVE_TARGET_TYPE_CODES: frozenset[str] = frozenset(
    AUTHORABLE_LOCATION_CATEGORIES
    | ORGANIZATION_ENTITY_TYPE_CODES
    | {"religion", "npc", "knowledge_item"}
)

# Objective fields whose change rewrites the meaning of recorded progress. They
# freeze once any progress exists for the quest in any timeline.
STRUCTURAL_OBJECTIVE_FIELDS: frozenset[str] = frozenset(
    {
        "objective_type",
        "requirement_level",
        "completion_mode",
        "quantity_required",
        "target_entity_id",
    }
)
STRUCTURAL_STAGE_FIELDS: frozenset[str] = frozenset({"stage_type"})


def _choice(value: str | None, choices: tuple[tuple[str, str], ...], field: str) -> str:
    if value not in {code for code, _ in choices}:
        raise AuthoringValidationError(f"{field} is not an allowed choice")
    assert value is not None
    return value


@dataclass(frozen=True)
class StageFields:
    name: str
    description: str | None
    stage_type: str


def normalize_stage_fields(
    *, name: str | None, description: str | None, stage_type: str | None
) -> StageFields:
    return StageFields(
        name=normalize_name(name),
        description=normalize_description(description),
        stage_type=_choice(stage_type, STAGE_TYPES, "stage_type"),
    )


@dataclass(frozen=True)
class ObjectiveFields:
    name: str
    description: str | None
    objective_type: str
    requirement_level: str
    completion_mode: str
    visibility_policy: str
    quantity_required: int | None


def normalize_objective_fields(
    *,
    name: str | None,
    description: str | None,
    objective_type: str | None,
    requirement_level: str | None,
    completion_mode: str | None,
    visibility_policy: str | None,
    quantity_required: int | None,
) -> ObjectiveFields:
    if not objective_type or len(objective_type) > 64:
        raise AuthoringValidationError("objective_type is required")
    if quantity_required is not None and (
        isinstance(quantity_required, bool)
        or not isinstance(quantity_required, int)
        or quantity_required < 1
        or quantity_required > QUANTITY_MAX
    ):
        raise AuthoringValidationError("quantity_required is out of range")
    return ObjectiveFields(
        name=normalize_name(name),
        description=normalize_description(description),
        objective_type=objective_type,
        requirement_level=_choice(requirement_level, REQUIREMENT_LEVELS, "requirement_level"),
        completion_mode=_choice(completion_mode, COMPLETION_MODES, "completion_mode"),
        visibility_policy=_choice(visibility_policy, VISIBILITY_POLICIES, "visibility_policy"),
        quantity_required=quantity_required,
    )
