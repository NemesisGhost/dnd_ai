"""Build authoring read models (Phase 15 checkpoint 15.2B-2).

For `canon.edit` holders only (the route dependency enforces it first). Everything
is read from the authored build records and the campaign's pinned ruleset version;
the active build is the branch-aware effective value, never a raw column read.
"""

import uuid
from dataclasses import dataclass, field

from sqlalchemy import Connection, text

from .character_build_resolution import resolve_effective_character_build_id


@dataclass(frozen=True)
class RuleOption:
    id: uuid.UUID
    name: str
    code: str
    extra: dict[str, object] = field(default_factory=dict)


def _options(connection: Connection, sql: str, ruleset_version_id: uuid.UUID) -> list[RuleOption]:
    rows = connection.execute(text(sql), {"rv": ruleset_version_id}).mappings().all()
    return [
        RuleOption(
            id=row["id"],
            name=str(row["display_name"]),
            code=str(row["code"]),
            extra={k: v for k, v in row.items() if k not in {"id", "display_name", "code"}},
        )
        for row in rows
    ]


_CANON = (
    "JOIN core.canon_statuses cs ON cs.canon_status_id = t.canon_status_id AND cs.code = 'canon'"
)


def get_build_options(
    connection: Connection, *, ruleset_version_id: uuid.UUID
) -> dict[str, list[RuleOption]]:
    """Canon rules content of one ruleset version, by family."""
    return {
        "abilities": _options(
            connection,
            f"SELECT t.ability_id AS id, t.display_name, t.code FROM rules.abilities t {_CANON} "
            "WHERE t.ruleset_version_id = :rv ORDER BY lower(t.display_name), t.ability_id",
            ruleset_version_id,
        ),
        "classes": _options(
            connection,
            f"SELECT t.class_id AS id, t.display_name, t.code, t.hit_die FROM rules.classes t {_CANON} "
            "WHERE t.ruleset_version_id = :rv ORDER BY lower(t.display_name), t.class_id",
            ruleset_version_id,
        ),
        "subclasses": _options(
            connection,
            f"SELECT t.subclass_id AS id, t.display_name, t.code, t.class_id FROM rules.subclasses t {_CANON} "
            "WHERE t.ruleset_version_id = :rv ORDER BY lower(t.display_name), t.subclass_id",
            ruleset_version_id,
        ),
        "skills": _options(
            connection,
            f"SELECT t.skill_id AS id, t.display_name, t.code FROM rules.skills t {_CANON} "
            "WHERE t.ruleset_version_id = :rv ORDER BY lower(t.display_name), t.skill_id",
            ruleset_version_id,
        ),
        "proficiency_types": _options(
            connection,
            f"SELECT t.proficiency_type_id AS id, t.display_name, t.code, t.target_kind "
            f"FROM rules.proficiency_types t {_CANON} "
            "WHERE t.ruleset_version_id = :rv ORDER BY lower(t.display_name), t.proficiency_type_id",
            ruleset_version_id,
        ),
        "spells": _options(
            connection,
            f"SELECT t.spell_id AS id, t.display_name, t.code, t.level FROM rules.spells t {_CANON} "
            "WHERE t.ruleset_version_id = :rv ORDER BY t.level, lower(t.display_name), t.spell_id",
            ruleset_version_id,
        ),
        "features": _options(
            connection,
            f"SELECT t.feature_id AS id, t.display_name, t.code, t.class_id, t.subclass_id, "
            f"t.granted_at_level FROM rules.features t {_CANON} "
            "WHERE t.ruleset_version_id = :rv ORDER BY lower(t.display_name), t.feature_id",
            ruleset_version_id,
        ),
    }


@dataclass(frozen=True)
class BuildSummary:
    character_build_id: uuid.UUID
    label: str | None
    ruleset_version_id: uuid.UUID
    created_at: str
    is_active: bool
    counts: dict[str, int]


@dataclass(frozen=True)
class CharacterBuildsView:
    character_id: uuid.UUID
    name: str
    entity_type_code: str
    state_initialized: bool
    current_hit_points: int | None
    maximum_hit_points: int | None
    active_build_id: uuid.UUID | None
    builds: list[BuildSummary]


def get_character_builds(
    connection: Connection,
    *,
    world_id: uuid.UUID,
    timeline_id: uuid.UUID,
    character_id: uuid.UUID,
) -> CharacterBuildsView | None:
    """The character's builds and starting state on `timeline_id`; `None` when it
    is not an NPC or player character of `world_id`."""
    head = connection.execute(
        text("""
            SELECT e.canonical_name, et.code AS type_code
            FROM core.entities e JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id
            WHERE e.entity_id = :c AND e.world_id = :w AND et.code IN ('npc', 'player_character')
        """),
        {"c": character_id, "w": world_id},
    ).one_or_none()
    if head is None:
        return None
    state = connection.execute(
        text(
            "SELECT current_hit_points, maximum_hit_points FROM campaign.character_state "
            "WHERE timeline_id = :t AND character_id = :c"
        ),
        {"t": timeline_id, "c": character_id},
    ).one_or_none()
    active = resolve_effective_character_build_id(
        connection, character_id=character_id, timeline_id=timeline_id
    )
    rows = connection.execute(
        text("""
            SELECT b.character_build_id, b.label, b.ruleset_version_id, b.created_at,
                   (SELECT count(*) FROM character.character_ability_scores WHERE character_build_id = b.character_build_id) AS abilities,
                   (SELECT count(*) FROM character.character_class_levels WHERE character_build_id = b.character_build_id) AS classes,
                   (SELECT count(*) FROM character.character_proficiencies WHERE character_build_id = b.character_build_id) AS proficiencies,
                   (SELECT count(*) FROM character.character_features WHERE character_build_id = b.character_build_id) AS features,
                   (SELECT count(*) FROM character.character_spellcasting_profiles WHERE character_build_id = b.character_build_id) AS spellcasting
            FROM character.character_builds b
            WHERE b.character_id = :c
            ORDER BY b.created_at, b.character_build_id
        """),
        {"c": character_id},
    ).all()
    return CharacterBuildsView(
        character_id=character_id,
        name=str(head.canonical_name),
        entity_type_code=str(head.type_code),
        state_initialized=state is not None,
        current_hit_points=None if state is None else int(state.current_hit_points),
        maximum_hit_points=None if state is None else int(state.maximum_hit_points),
        active_build_id=active,
        builds=[
            BuildSummary(
                character_build_id=row.character_build_id,
                label=row.label,
                ruleset_version_id=row.ruleset_version_id,
                created_at=row.created_at.isoformat(),
                is_active=row.character_build_id == active,
                counts={
                    "abilities": int(row.abilities),
                    "classes": int(row.classes),
                    "proficiencies": int(row.proficiencies),
                    "features": int(row.features),
                    "spellcasting": int(row.spellcasting),
                },
            )
            for row in rows
        ],
    )


def campaign_ruleset_version(connection: Connection, *, campaign_id: uuid.UUID) -> uuid.UUID:
    value = connection.execute(
        text("SELECT ruleset_version_id FROM campaign.campaigns WHERE campaign_id = :c"),
        {"c": campaign_id},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value
