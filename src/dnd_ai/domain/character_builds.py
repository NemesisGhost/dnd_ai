"""Character build authoring policy (Phase 15 checkpoint 15.2B-2, decision D-9).

A build is an immutable mechanical snapshot of a character (ability scores, class
levels, proficiencies, features, spellcasting profiles) pinned to one ruleset
version. There is no edit command: a change is a new build, and which build is
*active* on a timeline is typed state (`campaign.character_state.
character_build_id`) changed only by `activate_character_build`.

This module is pure: input shapes, normalization, and fixed-code errors. Whether
a referenced rule record exists in the campaign's ruleset version is the
command's job (one database read per family), reported with a single
non-disclosing code.
"""

import uuid
from dataclasses import dataclass, field

from .authoring import AuthoringValidationError
from .errors import SafeMessageError

BUILD_EVENT_ACTIVATED = "character_build_activated"
BUILD_COMPONENT = "character_build_id"

LABEL_MAX_LENGTH = 200
ABILITY_SCORE_MIN = 1
ABILITY_SCORE_MAX = 30
CLASS_LEVEL_MIN = 1
CLASS_LEVEL_MAX = 20
TARGET_LABEL_MAX_LENGTH = 200
MAX_ABILITIES = 20
MAX_CLASSES = 12
MAX_PROFICIENCIES = 100
MAX_FEATURES = 100
MAX_SPELLCASTING_PROFILES = 12
MAX_SPELLS_PER_LIST = 300
MAX_HIT_POINTS = 10000

# Which `rules.proficiency_types.target_kind` takes which target field.
TARGET_KIND_FIELD = {
    "skill": "skill_id",
    "saving_throw": "saving_throw_ability_id",
    "free_text": "target_label",
}


class BuildOptionNotAvailableError(SafeMessageError):
    """A referenced rule record is nonexistent, not canon, or from another ruleset
    version -- one non-disclosing code."""

    safe_status_code = 400
    safe_error_code = "build_option_not_available"
    safe_message = "A selected rules option is not available for this campaign's ruleset."


class BuildCharacterInvalidError(SafeMessageError):
    """The character is not a buildable character in this world."""

    safe_status_code = 400
    safe_error_code = "build_character_invalid"
    safe_message = "The selected character cannot have a build."


class BuildNotFoundError(SafeMessageError):
    """The build does not exist for this character (or in this world)."""

    safe_status_code = 404
    safe_error_code = "not_found"
    safe_message = "The requested resource does not exist or is not accessible."


class CharacterNotPublishedError(SafeMessageError):
    """A build change during play is a recorded event, and an unpublished character
    cannot take part in one."""

    safe_status_code = 409
    safe_error_code = "character_not_published"
    safe_message = "Publish the character before changing its build during play."


class BuildAlreadyActiveError(SafeMessageError):
    """Activating the build that is already active."""

    safe_status_code = 409
    safe_error_code = "build_already_active"
    safe_message = "That build is already the active build."


class CharacterStateExistsError(SafeMessageError):
    """Initial state may be created once; later changes are events."""

    safe_status_code = 409
    safe_error_code = "character_state_exists"
    safe_message = "This character already has state on this timeline."


class CharacterStateMissingError(SafeMessageError):
    """A build can be activated only on a timeline where the character has state."""

    safe_status_code = 409
    safe_error_code = "character_state_missing"
    safe_message = "Set the character's starting state before activating a build."


class ClockRequiredError(SafeMessageError):
    """Recording a change needs a campaign time to record it at."""

    safe_status_code = 409
    safe_error_code = "clock_required"
    safe_message = "Set the campaign time before changing a character's build."


@dataclass(frozen=True)
class ProficiencyInput:
    proficiency_type_id: uuid.UUID
    skill_id: uuid.UUID | None = None
    saving_throw_ability_id: uuid.UUID | None = None
    target_label: str | None = None
    is_expertise: bool = False


@dataclass(frozen=True)
class SpellcastingInput:
    class_id: uuid.UUID | None
    spellcasting_ability_id: uuid.UUID
    known_spell_ids: tuple[uuid.UUID, ...] = ()
    prepared_spell_ids: tuple[uuid.UUID, ...] = ()


@dataclass(frozen=True)
class ClassLevelInput:
    class_id: uuid.UUID
    subclass_id: uuid.UUID | None
    level: int


@dataclass(frozen=True)
class BuildInput:
    label: str | None
    ability_scores: tuple[tuple[uuid.UUID, int], ...] = ()
    class_levels: tuple[ClassLevelInput, ...] = ()
    proficiencies: tuple[ProficiencyInput, ...] = ()
    feature_ids: tuple[uuid.UUID, ...] = ()
    spellcasting: tuple[SpellcastingInput, ...] = ()
    notes: list[str] = field(default_factory=list)


def _unique(values: list[object], what: str) -> None:
    if len(set(values)) != len(values):
        raise AuthoringValidationError(f"{what} must not repeat")


def normalize_build(build: BuildInput) -> BuildInput:
    """Validate shape and bounds; return the build with a trimmed label."""
    label = None
    if build.label is not None and build.label.strip():
        label = build.label.strip()
        if len(label) > LABEL_MAX_LENGTH:
            raise AuthoringValidationError("label is too long")
    if len(build.ability_scores) > MAX_ABILITIES:
        raise AuthoringValidationError("too many ability scores")
    for _, score in build.ability_scores:
        if not ABILITY_SCORE_MIN <= score <= ABILITY_SCORE_MAX:
            raise AuthoringValidationError("ability score is out of range")
    _unique([a for a, _ in build.ability_scores], "ability scores")
    if len(build.class_levels) > MAX_CLASSES:
        raise AuthoringValidationError("too many classes")
    for cl in build.class_levels:
        if not CLASS_LEVEL_MIN <= cl.level <= CLASS_LEVEL_MAX:
            raise AuthoringValidationError("class level is out of range")
    _unique([c.class_id for c in build.class_levels], "classes")
    if len(build.proficiencies) > MAX_PROFICIENCIES:
        raise AuthoringValidationError("too many proficiencies")
    for p in build.proficiencies:
        targets = [t for t in (p.skill_id, p.saving_throw_ability_id, p.target_label) if t]
        if len(targets) != 1:
            raise AuthoringValidationError("a proficiency needs exactly one target")
        if p.target_label is not None and len(p.target_label) > TARGET_LABEL_MAX_LENGTH:
            raise AuthoringValidationError("target label is too long")
    _unique(
        [
            (p.proficiency_type_id, p.skill_id, p.saving_throw_ability_id, p.target_label)
            for p in build.proficiencies
        ],
        "proficiencies",
    )
    if len(build.feature_ids) > MAX_FEATURES:
        raise AuthoringValidationError("too many features")
    _unique(list(build.feature_ids), "features")
    if len(build.spellcasting) > MAX_SPELLCASTING_PROFILES:
        raise AuthoringValidationError("too many spellcasting profiles")
    _unique([s.class_id for s in build.spellcasting if s.class_id is not None], "spellcasting")
    for profile in build.spellcasting:
        for spells in (profile.known_spell_ids, profile.prepared_spell_ids):
            if len(spells) > MAX_SPELLS_PER_LIST:
                raise AuthoringValidationError("too many spells")
            _unique(list(spells), "spells")
    return BuildInput(
        label=label,
        ability_scores=build.ability_scores,
        class_levels=build.class_levels,
        proficiencies=build.proficiencies,
        feature_ids=build.feature_ids,
        spellcasting=build.spellcasting,
    )


def normalize_hit_points(current: int | None, maximum: int) -> tuple[int, int]:
    """`(current, maximum)` for a character's starting state; current defaults to
    the maximum."""
    if not 1 <= maximum <= MAX_HIT_POINTS:
        raise AuthoringValidationError("maximum_hit_points is out of range")
    value = maximum if current is None else current
    if not 0 <= value <= maximum:
        raise AuthoringValidationError("current_hit_points is out of range")
    return value, maximum
