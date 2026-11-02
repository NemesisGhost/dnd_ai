"""Character builds, build activation, and starting state (Phase 15 checkpoint 15.2B-2).

Decision D-9 (option a): a build is an immutable mechanical snapshot, so there is
no edit command. `create_character_build` writes one build and all its children in
one transaction, validated against the campaign's pinned ruleset version.
`initialize_character_state` creates the character's `campaign.character_state` row
on the campaign's timeline (administrative: no event, `last_event_id` NULL), once.
`activate_character_build` selects the active build:

- the *first* activation, when the state row has no build and no event has touched
  it, is administrative (`last_event_id` stays NULL), exactly the baseline the
  branch-aware resolver inherits;
- every later activation records a `character_build_activated` event and a
  `narrative.event_effects` row (`character_build_id`, previous -> new) and sets
  `last_event_id`, atomically with the state write.

Optimistic token for an activation: `expected_active_build_id` (the build the
caller saw as active, or NULL), compared under the state row's `FOR UPDATE` lock,
so two concurrent activations from the same view cannot both succeed.

Lock order: operation scope (world, membership rows, account, campaign `FOR
SHARE`), the character's entity row `FOR SHARE`, then the character's state row
`FOR UPDATE` (activation and initialization only).
"""

import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy import Connection, text

from dnd_ai.domain.authoring import StaleWriteError
from dnd_ai.domain.character_builds import (
    BUILD_COMPONENT,
    BUILD_EVENT_ACTIVATED,
    TARGET_KIND_FIELD,
    BuildAlreadyActiveError,
    BuildCharacterInvalidError,
    BuildInput,
    BuildNotFoundError,
    BuildOptionNotAvailableError,
    CharacterNotPublishedError,
    CharacterStateExistsError,
    CharacterStateMissingError,
    ClockRequiredError,
    normalize_build,
    normalize_hit_points,
)
from dnd_ai.domain.data_classification import audit_change, audit_initial
from dnd_ai.queries.campaign_clock import resolve_effective_clock

from ._content import LockedContent, lock_entities
from ._operations import OperationScope, lock_operation_scope
from .events import EventParticipant, _insert_event_row

_BUILDABLE = frozenset({"npc", "player_character"})


@dataclass(frozen=True)
class BuildResult:
    character_id: uuid.UUID
    world_id: uuid.UUID
    character_build_id: uuid.UUID
    changed_fields: Mapping[str, object]
    event_id: uuid.UUID | None = None


def _lock_buildable_character(
    connection: Connection, scope: OperationScope, character_id: uuid.UUID
) -> LockedContent:
    locked = lock_entities(connection, world_id=scope.world_id, share_ids=[character_id])
    character = locked.get(character_id)
    if (
        character is None
        or character.entity_type_code not in _BUILDABLE
        or character.lifecycle_status != "active"
    ):
        raise BuildCharacterInvalidError(f"character {character_id} is not buildable")
    return character


def _campaign_ruleset_version(connection: Connection, campaign_id: uuid.UUID) -> uuid.UUID:
    value = connection.execute(
        text("SELECT ruleset_version_id FROM campaign.campaigns WHERE campaign_id = :c"),
        {"c": campaign_id},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def _require_in_ruleset(
    connection: Connection,
    *,
    table: str,
    column: str,
    ids: list[uuid.UUID],
    ruleset_version_id: uuid.UUID,
) -> dict[uuid.UUID, uuid.UUID | None]:
    """Every id exists in `rules.<table>`, is canon, and belongs to the version.
    Returns `{id: class_id-or-None}` for tables that have a class link (subclasses,
    features) so callers can check consistency; one non-disclosing error."""
    wanted = set(ids)
    if not wanted:
        return {}
    extra = ", t.class_id" if table in {"subclasses", "features"} else ", NULL AS class_id"
    rows = connection.execute(
        text(f"""
            SELECT t.{column} AS id{extra}
            FROM rules.{table} t
            JOIN core.canon_statuses cs ON cs.canon_status_id = t.canon_status_id
            WHERE t.{column} = ANY(CAST(:ids AS uuid[]))
              AND t.ruleset_version_id = :rv
              AND cs.code = 'canon'
        """),  # noqa: S608 -- table and column are closed literals from this module
        {"ids": list(wanted), "rv": ruleset_version_id},
    ).all()
    found = {row.id: row.class_id for row in rows}
    if set(found) != wanted:
        raise BuildOptionNotAvailableError(f"{table}: {len(wanted - set(found))} unavailable")
    return found


def _validate_rules(
    connection: Connection, build: BuildInput, ruleset_version_id: uuid.UUID
) -> None:
    abilities = [a for a, _ in build.ability_scores]
    abilities += [
        p.saving_throw_ability_id for p in build.proficiencies if p.saving_throw_ability_id
    ]
    abilities += [s.spellcasting_ability_id for s in build.spellcasting]
    _require_in_ruleset(
        connection,
        table="abilities",
        column="ability_id",
        ids=abilities,
        ruleset_version_id=ruleset_version_id,
    )
    classes = [c.class_id for c in build.class_levels]
    classes += [s.class_id for s in build.spellcasting if s.class_id is not None]
    _require_in_ruleset(
        connection,
        table="classes",
        column="class_id",
        ids=classes,
        ruleset_version_id=ruleset_version_id,
    )
    subclass_owner = _require_in_ruleset(
        connection,
        table="subclasses",
        column="subclass_id",
        ids=[c.subclass_id for c in build.class_levels if c.subclass_id is not None],
        ruleset_version_id=ruleset_version_id,
    )
    for c in build.class_levels:
        if c.subclass_id is not None and subclass_owner[c.subclass_id] != c.class_id:
            raise BuildOptionNotAvailableError("subclass does not belong to the class")
    _require_in_ruleset(
        connection,
        table="skills",
        column="skill_id",
        ids=[p.skill_id for p in build.proficiencies if p.skill_id is not None],
        ruleset_version_id=ruleset_version_id,
    )
    _require_in_ruleset(
        connection,
        table="spells",
        column="spell_id",
        ids=[
            spell
            for s in build.spellcasting
            for spell in (*s.known_spell_ids, *s.prepared_spell_ids)
        ],
        ruleset_version_id=ruleset_version_id,
    )
    _require_in_ruleset(
        connection,
        table="features",
        column="feature_id",
        ids=list(build.feature_ids),
        ruleset_version_id=ruleset_version_id,
    )
    type_ids = [p.proficiency_type_id for p in build.proficiencies]
    _require_in_ruleset(
        connection,
        table="proficiency_types",
        column="proficiency_type_id",
        ids=type_ids,
        ruleset_version_id=ruleset_version_id,
    )
    if type_ids:
        kind_rows = connection.execute(
            text(
                "SELECT proficiency_type_id, target_kind FROM rules.proficiency_types "
                "WHERE proficiency_type_id = ANY(CAST(:ids AS uuid[]))"
            ),
            {"ids": type_ids},
        ).all()
        kinds: dict[uuid.UUID, str] = {row[0]: str(row[1]) for row in kind_rows}
        for p in build.proficiencies:
            field_name = TARGET_KIND_FIELD[kinds[p.proficiency_type_id]]
            if getattr(p, field_name) is None:
                raise BuildOptionNotAvailableError("proficiency target does not match its type")


def create_character_build(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    character_id: uuid.UUID,
    build: BuildInput,
) -> BuildResult:
    normalized = normalize_build(build)
    scope = lock_operation_scope(connection, campaign_id=campaign_id, actor_user_id=actor_user_id)
    _lock_buildable_character(connection, scope, character_id)
    ruleset_version_id = _campaign_ruleset_version(connection, campaign_id)
    _validate_rules(connection, normalized, ruleset_version_id)

    build_id = connection.execute(
        text("""
            INSERT INTO character.character_builds (character_id, ruleset_version_id, label)
            VALUES (:c, :rv, :label) RETURNING character_build_id
        """),
        {"c": character_id, "rv": ruleset_version_id, "label": normalized.label},
    ).scalar()
    assert isinstance(build_id, uuid.UUID)
    for ability_id, score in normalized.ability_scores:
        connection.execute(
            text(
                "INSERT INTO character.character_ability_scores "
                "(character_build_id, ability_id, score) VALUES (:b, :a, :s)"
            ),
            {"b": build_id, "a": ability_id, "s": score},
        )
    for cl in normalized.class_levels:
        connection.execute(
            text(
                "INSERT INTO character.character_class_levels "
                "(character_build_id, class_id, subclass_id, level) VALUES (:b, :c, :s, :l)"
            ),
            {"b": build_id, "c": cl.class_id, "s": cl.subclass_id, "l": cl.level},
        )
    for p in normalized.proficiencies:
        connection.execute(
            text("""
                INSERT INTO character.character_proficiencies
                    (character_build_id, proficiency_type_id, skill_id,
                     saving_throw_ability_id, target_label, is_expertise)
                VALUES (:b, :t, :sk, :st, :tl, :ex)
            """),
            {
                "b": build_id,
                "t": p.proficiency_type_id,
                "sk": p.skill_id,
                "st": p.saving_throw_ability_id,
                "tl": p.target_label,
                "ex": p.is_expertise,
            },
        )
    for feature_id in normalized.feature_ids:
        connection.execute(
            text(
                "INSERT INTO character.character_features (character_build_id, feature_id) "
                "VALUES (:b, :f)"
            ),
            {"b": build_id, "f": feature_id},
        )
    for s in normalized.spellcasting:
        profile_id = connection.execute(
            text(
                "INSERT INTO character.character_spellcasting_profiles "
                "(character_build_id, class_id, spellcasting_ability_id) VALUES (:b, :c, :a) "
                "RETURNING character_spellcasting_profile_id"
            ),
            {"b": build_id, "c": s.class_id, "a": s.spellcasting_ability_id},
        ).scalar()
        for table, spells in (
            ("character_known_spells", s.known_spell_ids),
            ("character_prepared_spells", s.prepared_spell_ids),
        ):
            for spell_id in spells:
                connection.execute(
                    text(
                        f"INSERT INTO character.{table} "  # noqa: S608 -- closed literals
                        "(character_spellcasting_profile_id, spell_id) VALUES (:p, :s)"
                    ),
                    {"p": profile_id, "s": spell_id},
                )
    return BuildResult(
        character_id=character_id,
        world_id=scope.world_id,
        character_build_id=build_id,
        changed_fields=audit_initial(
            {
                "ruleset_version_id": str(ruleset_version_id),
                "label": normalized.label,
                "ability_count": len(normalized.ability_scores),
                "class_level_count": len(normalized.class_levels),
                "proficiency_count": len(normalized.proficiencies),
                "feature_count": len(normalized.feature_ids),
                "spellcasting_count": len(normalized.spellcasting),
                "spell_count": sum(
                    len(p.known_spell_ids) + len(p.prepared_spell_ids)
                    for p in normalized.spellcasting
                ),
            }
        ),
    )


def _lock_state(
    connection: Connection, timeline_id: uuid.UUID, character_id: uuid.UUID
) -> tuple[uuid.UUID | None, uuid.UUID | None] | None:
    """`(active build id, last_event_id)` of the character's own state row on the
    timeline, locked `FOR UPDATE`, or `None` when there is none."""
    row = connection.execute(
        text("""
            SELECT character_build_id, last_event_id FROM campaign.character_state
            WHERE timeline_id = :t AND character_id = :c FOR UPDATE
        """),
        {"t": timeline_id, "c": character_id},
    ).one_or_none()
    return None if row is None else (row.character_build_id, row.last_event_id)


def initialize_character_state(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    character_id: uuid.UUID,
    maximum_hit_points: int,
    current_hit_points: int | None = None,
) -> BuildResult:
    current, maximum = normalize_hit_points(current_hit_points, maximum_hit_points)
    scope = lock_operation_scope(connection, campaign_id=campaign_id, actor_user_id=actor_user_id)
    _lock_buildable_character(connection, scope, character_id)
    inserted = connection.execute(
        text("""
            INSERT INTO campaign.character_state
                (timeline_id, character_id, current_hit_points, maximum_hit_points)
            VALUES (:t, :c, :cur, :max)
            ON CONFLICT (timeline_id, character_id) DO NOTHING
            RETURNING character_id
        """),
        {"t": scope.timeline_id, "c": character_id, "cur": current, "max": maximum},
    ).scalar()
    if inserted is None:
        raise CharacterStateExistsError(f"state of {character_id} exists")
    return BuildResult(
        character_id=character_id,
        world_id=scope.world_id,
        character_build_id=character_id,  # unused for state; kept for one result shape
        changed_fields=audit_initial(
            {"current_hit_points": current, "maximum_hit_points": maximum}
        ),
    )


def activate_character_build(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    character_id: uuid.UUID,
    character_build_id: uuid.UUID,
    expected_active_build_id: uuid.UUID | None,
) -> BuildResult:
    scope = lock_operation_scope(connection, campaign_id=campaign_id, actor_user_id=actor_user_id)
    character = _lock_buildable_character(connection, scope, character_id)
    belongs = connection.execute(
        text(
            "SELECT 1 FROM character.character_builds "
            "WHERE character_build_id = :b AND character_id = :c"
        ),
        {"b": character_build_id, "c": character_id},
    ).scalar()
    if belongs is None:
        raise BuildNotFoundError(f"build {character_build_id} is not {character_id}'s")
    state = _lock_state(connection, scope.timeline_id, character_id)
    if state is None:
        raise CharacterStateMissingError(f"{character_id} has no state on {scope.timeline_id}")
    active, last_event = state
    if active != expected_active_build_id:
        raise StaleWriteError(f"the active build of {character_id} changed")
    if active == character_build_id:
        raise BuildAlreadyActiveError(f"{character_build_id} is already active")

    changed = {
        BUILD_COMPONENT: audit_change(
            BUILD_COMPONENT,
            None if active is None else str(active),
            str(character_build_id),
        )
    }
    if active is None and last_event is None:
        # The first activation is the administrative baseline (no event).
        connection.execute(
            text("""
                UPDATE campaign.character_state SET character_build_id = :b
                WHERE timeline_id = :t AND character_id = :c
            """),
            {"b": character_build_id, "t": scope.timeline_id, "c": character_id},
        )
        return BuildResult(
            character_id=character_id,
            world_id=scope.world_id,
            character_build_id=character_build_id,
            changed_fields=changed,
        )

    if character.canon_status != "canon":
        raise CharacterNotPublishedError(f"{character_id} is {character.canon_status}")
    world_time_id = _clock_time(connection, scope)
    event_id = _insert_event_row(
        connection,
        world_id=scope.world_id,
        timeline_id=scope.timeline_id,
        world_time_id=world_time_id,
        event_type_code=BUILD_EVENT_ACTIVATED,
        name="A character build was activated",
        campaign_id=campaign_id,
        participants=(EventParticipant(entity_id=character_id, role_code="actor"),),
    )
    connection.execute(
        text("""
            INSERT INTO narrative.event_effects
                (event_id, target_entity_id, target_component, previous_value, new_value,
                 effective_world_time_id)
            VALUES (:e, :c, :component, CAST(:previous AS jsonb), CAST(:new AS jsonb), :time)
        """),
        {
            "e": event_id,
            "c": character_id,
            "component": BUILD_COMPONENT,
            "previous": None if active is None else json.dumps(str(active)),
            "new": json.dumps(str(character_build_id)),
            "time": world_time_id,
        },
    )
    connection.execute(
        text("""
            UPDATE campaign.character_state
            SET character_build_id = :b, last_event_id = :e, updated_at = now()
            WHERE timeline_id = :t AND character_id = :c
        """),
        {"b": character_build_id, "e": event_id, "t": scope.timeline_id, "c": character_id},
    )
    return BuildResult(
        character_id=character_id,
        world_id=scope.world_id,
        character_build_id=character_build_id,
        changed_fields=changed,
        event_id=event_id,
    )


def _clock_time(connection: Connection, scope: OperationScope) -> uuid.UUID:
    """The world time an activation event is recorded at: the campaign's effective
    clock. Without one, the campaign has no recorded time and the caller is told
    to set the clock first."""
    effective = resolve_effective_clock(connection, timeline_id=scope.timeline_id)
    if effective is None:
        raise ClockRequiredError("the campaign clock is not set")
    return effective.world_time_id
