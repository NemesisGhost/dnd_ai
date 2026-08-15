"""Effective character-state query (docs/PLAN.md Phase 10 deliverable
"query services for the effective dungeon, character, ... state required by
the vertical slice").

`character.characters` and its ruleset-scoped references (`rules.species`,
...) describe what a character *is*; `campaign.character_state`/
`.character_conditions`/`.character_resources`/`.character_location_history`
describe what is currently true of it on a timeline (docs/architecture/
DATABASE_MODEL.md §17). This module reassembles those into one effective
view, tiered by how much detail the caller is authorized to see — the
`character.view_summary`/`character.view_full` capability split this
codebase's own seed data (`database/seeds/security.capabilities.yaml`)
already names for exactly this purpose.

This module is framework-free and performs no authorization of its own:
`include_full` must already be an authorized decision
(`dnd_ai.api.access.resolve_character_view_tier`) by the time it reaches
here, the same "authorization happens at the API/access boundary, the
query only filters" split `dnd_ai.queries.dungeon` established.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, text

from dnd_ai.domain.errors import DomainAuthorizationError


class CharacterNotFoundError(DomainAuthorizationError):
    """Raised by `get_character_view()` for a nonexistent `character_id`,
    or one whose own world does not match the caller's `expected_world_id`
    — identically, so a caller can never distinguish "doesn't exist" from
    "belongs to a different world" (mirroring `dnd_ai.queries.dungeon.
    DungeonAreaNotFoundError`'s identical reasoning). The supplied
    character/world ids are included only in the constructor's `detail`
    argument (`str(self)`), never in `safe_message`."""


@dataclass(frozen=True)
class CharacterConditionView:
    condition_code: str
    source_description: str | None


@dataclass(frozen=True)
class CharacterResourceView:
    resource_code: str
    current_amount: int
    maximum_amount: int


@dataclass(frozen=True)
class CharacterView:
    """`current_hit_points` through `resources` are always `None` when the
    caller was authorized only for the summary tier (`include_full=False`)
    — the query never even fetches this data in that case, rather than
    fetching and withholding it."""

    character_id: uuid.UUID
    name: str
    species_code: str
    size_category: str
    current_hit_points: int | None
    maximum_hit_points: int | None
    temporary_hit_points: int | None
    exhaustion_level: int | None
    death_save_successes: int | None
    death_save_failures: int | None
    current_location_id: uuid.UUID | None
    conditions: tuple[CharacterConditionView, ...] | None
    resources: tuple[CharacterResourceView, ...] | None


def get_character_view(
    connection: Connection,
    *,
    character_id: uuid.UUID,
    timeline_id: uuid.UUID,
    expected_world_id: uuid.UUID,
    include_full: bool,
) -> CharacterView:
    """The effective, tier-filtered state of one character. Raises
    `CharacterNotFoundError` for a nonexistent character or one belonging
    to a different world than `expected_world_id` (always the caller's own
    resolved-timeline world — `dnd_ai.api._shared.timeline_world_id`, never
    caller-supplied)."""
    row = (
        connection.execute(
            text("""
            SELECT c.character_id, e.world_id, e.canonical_name, sp.code AS species_code,
                   c.size_category
            FROM character.characters c
            JOIN core.entities e ON e.entity_id = c.character_id
            JOIN rules.species sp ON sp.species_id = c.species_id
            WHERE c.character_id = :character
        """),
            {"character": character_id},
        )
        .mappings()
        .one_or_none()
    )

    if row is None or row["world_id"] != expected_world_id:
        raise CharacterNotFoundError(
            f"character {character_id} does not exist in world {expected_world_id} "
            f"(actual world: {row['world_id'] if row is not None else None})"
        )

    if not include_full:
        return CharacterView(
            character_id=row["character_id"],
            name=row["canonical_name"],
            species_code=row["species_code"],
            size_category=row["size_category"],
            current_hit_points=None,
            maximum_hit_points=None,
            temporary_hit_points=None,
            exhaustion_level=None,
            death_save_successes=None,
            death_save_failures=None,
            current_location_id=None,
            conditions=None,
            resources=None,
        )

    state_row = (
        connection.execute(
            text("""
                SELECT current_hit_points, maximum_hit_points, temporary_hit_points,
                       exhaustion_level, death_save_successes, death_save_failures
                FROM campaign.character_state
                WHERE timeline_id = :timeline AND character_id = :character
            """),
            {"timeline": timeline_id, "character": character_id},
        )
        .mappings()
        .one_or_none()
    )

    current_location_id = connection.execute(
        text("""
            SELECT location_id FROM campaign.character_location_history
            WHERE timeline_id = :timeline AND character_id = :character
              AND departed_at_world_time_id IS NULL
        """),
        {"timeline": timeline_id, "character": character_id},
    ).scalar()

    condition_rows = connection.execute(
        text("""
            SELECT rc.code AS condition_code, cc.source_description
            FROM campaign.character_conditions cc
            JOIN rules.conditions rc ON rc.condition_id = cc.condition_id
            WHERE cc.timeline_id = :timeline AND cc.character_id = :character
            ORDER BY rc.code
        """),
        {"timeline": timeline_id, "character": character_id},
    ).mappings()
    conditions = tuple(
        CharacterConditionView(
            condition_code=cond_row["condition_code"],
            source_description=cond_row["source_description"],
        )
        for cond_row in condition_rows
    )

    resource_rows = connection.execute(
        text("""
            SELECT rr.code AS resource_code, cr.current_amount, cr.maximum_amount
            FROM campaign.character_resources cr
            JOIN rules.resource_definitions rr
                ON rr.resource_definition_id = cr.resource_definition_id
            WHERE cr.timeline_id = :timeline AND cr.character_id = :character
            ORDER BY rr.code
        """),
        {"timeline": timeline_id, "character": character_id},
    ).mappings()
    resources = tuple(
        CharacterResourceView(
            resource_code=res_row["resource_code"],
            current_amount=res_row["current_amount"],
            maximum_amount=res_row["maximum_amount"],
        )
        for res_row in resource_rows
    )

    return CharacterView(
        character_id=row["character_id"],
        name=row["canonical_name"],
        species_code=row["species_code"],
        size_category=row["size_category"],
        current_hit_points=state_row["current_hit_points"] if state_row is not None else None,
        maximum_hit_points=state_row["maximum_hit_points"] if state_row is not None else None,
        temporary_hit_points=(state_row["temporary_hit_points"] if state_row is not None else None),
        exhaustion_level=state_row["exhaustion_level"] if state_row is not None else None,
        death_save_successes=(state_row["death_save_successes"] if state_row is not None else None),
        death_save_failures=(state_row["death_save_failures"] if state_row is not None else None),
        current_location_id=current_location_id,
        conditions=conditions,
        resources=resources,
    )
