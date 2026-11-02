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

import re
from dataclasses import dataclass

from .authoring import AuthoringValidationError, normalize_description, normalize_name
from .content_authoring import AUTHORABLE_LOCATION_CATEGORIES
from .errors import SafeMessageError
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


# --- Phase 15.2E-2a: dependencies, participants, outcomes, rewards, GM notes ---------------------

DEPENDENCY_TYPES: tuple[tuple[str, str], ...] = (
    ("prerequisite", "Prerequisite"),
    ("blocking", "Blocking"),
    ("exclusion", "Exclusion"),
    ("branching", "Branching"),
)
# Only prerequisites order objectives, so only they may not form a cycle.
ORDERING_DEPENDENCY_TYPE = "prerequisite"

PARTICIPANT_ROLES: tuple[tuple[str, str], ...] = (
    ("quest_giver", "Quest giver"),
    ("ally", "Ally"),
    ("antagonist", "Antagonist"),
    ("involved", "Involved"),
)
# Who may be a quest participant: people and organizations, never places or claims.
PARTICIPANT_TYPE_CODES: frozenset[str] = frozenset(
    {"npc", "player_character"} | ORGANIZATION_ENTITY_TYPE_CODES
)

OUTCOME_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("success", "Success"),
    ("partial_success", "Partial success"),
    ("failure", "Failure"),
    ("neutral", "Neutral"),
)
REWARD_TYPES: tuple[tuple[str, str], ...] = (
    ("item", "Item"),
    ("currency", "Currency"),
    ("reputation", "Reputation"),
    ("knowledge", "Knowledge"),
    ("other", "Other"),
)

GM_NOTES_MAX_LENGTH = 4000
OUTCOME_DESCRIPTION_MAX_LENGTH = 4000
REWARD_DESCRIPTION_MAX_LENGTH = 2000
MAX_DEPENDENCIES = 500
MAX_PARTICIPANTS = 200
MAX_OUTCOMES = 50
MAX_REWARDS_PER_OUTCOME = 50

_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class ObjectiveDependencyCycleError(SafeMessageError):
    """The prerequisite would make an objective depend on itself through others."""

    safe_status_code = 409
    safe_error_code = "objective_dependency_cycle"
    safe_message = "That prerequisite would create a loop of objectives that wait on each other."


class ObjectiveDependencyInvalidError(SafeMessageError):
    """Both objectives must belong to this quest, and differ."""

    safe_status_code = 400
    safe_error_code = "objective_dependency_invalid"
    safe_message = "The selected objectives are not valid for this dependency."


class ObjectiveDependencyExistsError(SafeMessageError):
    safe_status_code = 409
    safe_error_code = "objective_dependency_exists"
    safe_message = "That dependency already exists."


class QuestParticipantInvalidError(SafeMessageError):
    safe_status_code = 400
    safe_error_code = "quest_participant_invalid"
    safe_message = "The selected participant is not valid."


class QuestParticipantExistsError(SafeMessageError):
    safe_status_code = 409
    safe_error_code = "quest_participant_exists"
    safe_message = "That participant already has that role in this quest."


class QuestOutcomeCodeExistsError(SafeMessageError):
    safe_status_code = 409
    safe_error_code = "quest_outcome_code_exists"
    safe_message = "Another outcome of this quest already uses that code."


class RewardKnowledgeInvalidError(SafeMessageError):
    safe_status_code = 400
    safe_error_code = "reward_knowledge_invalid"
    safe_message = "The selected knowledge item is not valid for a reward."


def normalize_gm_notes(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    if len(value.strip()) > GM_NOTES_MAX_LENGTH:
        raise AuthoringValidationError("gm_notes is too long")
    return value.strip()


def _closed(value: str | None, choices: tuple[tuple[str, str], ...], field: str) -> str:
    return _choice(value, choices, field)


def normalize_dependency_type(value: str | None) -> str:
    return _closed(value, DEPENDENCY_TYPES, "dependency_type")


def normalize_participant_role(value: str | None) -> str:
    return _closed(value, PARTICIPANT_ROLES, "participant_role")


@dataclass(frozen=True)
class OutcomeFields:
    code: str
    name: str
    description: str | None
    outcome_category: str


def normalize_outcome_fields(
    *, code: str | None, name: str | None, description: str | None, outcome_category: str | None
) -> OutcomeFields:
    clean_code = (code or "").strip()
    if not _CODE.match(clean_code):
        raise AuthoringValidationError("code must be lowercase letters, digits and underscores")
    clean_description = normalize_description(description)
    if clean_description is not None and len(clean_description) > OUTCOME_DESCRIPTION_MAX_LENGTH:
        raise AuthoringValidationError("description is too long")
    return OutcomeFields(
        code=clean_code,
        name=normalize_name(name),
        description=clean_description,
        outcome_category=_closed(outcome_category, OUTCOME_CATEGORIES, "outcome_category"),
    )


@dataclass(frozen=True)
class RewardFields:
    reward_type: str
    description: str


def normalize_reward_fields(*, reward_type: str | None, description: str | None) -> RewardFields:
    text_value = (description or "").strip()
    if not text_value or len(text_value) > REWARD_DESCRIPTION_MAX_LENGTH:
        raise AuthoringValidationError("description must be 1 to 2000 characters")
    return RewardFields(
        reward_type=_closed(reward_type, REWARD_TYPES, "reward_type"), description=text_value
    )
