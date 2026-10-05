"""NPC authoring read models (Phase 15.1).

For `canon.edit` holders only -- the route dependency enforces it first. The view
is the NPC's **identity**, including the GM-only `notes`; the audience-safe
character reads never select it.
"""

import uuid
from dataclasses import dataclass, field

from sqlalchemy import Connection, text

from dnd_ai.domain.content_authoring import evaluate_content_actions
from dnd_ai.domain.entity_lifecycle import BlockedAction
from dnd_ai.queries.content_preconditions import type_specific_blocks
from dnd_ai.queries.organization_authoring import ReferenceSummary, _reference


@dataclass(frozen=True)
class SpeciesOption:
    species_id: uuid.UUID
    name: str
    ruleset_name: str


def list_species_options(connection: Connection, *, world_id: uuid.UUID) -> list[SpeciesOption]:
    """Canon species of the *current* version of every ruleset the world allows
    (`rules.world_rulesets`), by name. The command accepts any version of an
    allowed ruleset (what the database trigger enforces); the form offers the
    current one."""
    rows = connection.execute(
        text("""
            SELECT sp.species_id, sp.display_name, rs.display_name AS ruleset_name
            FROM rules.world_rulesets wr
            JOIN rules.rulesets rs ON rs.ruleset_id = wr.ruleset_id
            JOIN rules.ruleset_versions rv ON rv.ruleset_id = rs.ruleset_id AND rv.is_current
            JOIN rules.species sp ON sp.ruleset_version_id = rv.ruleset_version_id
            JOIN core.canon_statuses cs ON cs.canon_status_id = sp.canon_status_id
            WHERE wr.world_id = :w AND cs.code = 'canon'
            ORDER BY lower(sp.display_name), sp.species_id
        """),
        {"w": world_id},
    ).all()
    return [
        SpeciesOption(
            species_id=row.species_id,
            name=str(row.display_name),
            ruleset_name=str(row.ruleset_name),
        )
        for row in rows
    ]


@dataclass(frozen=True)
class CharacterAuthoringView:
    character_id: uuid.UUID
    name: str
    summary: str | None
    species_id: uuid.UUID
    species_name: str
    size_category: str
    origin: ReferenceSummary | None
    background: str | None
    appearance: str | None
    notes: str | None
    canon_status: str
    lifecycle_status: str
    row_version: int
    available_actions: list[str]
    blocked_actions: list[BlockedAction]
    field_locks: list[str] = field(default_factory=list)


NpcAuthoringView = CharacterAuthoringView


def get_npc_authoring(
    connection: Connection, *, world_id: uuid.UUID, npc_id: uuid.UUID
) -> CharacterAuthoringView | None:
    """The authoring view of an NPC in `world_id`, or `None` if it does not exist
    there or is not an NPC (a player character is not edited here)."""
    return get_character_authoring(connection, world_id=world_id, character_id=npc_id, kind="npc")


def get_character_authoring(
    connection: Connection, *, world_id: uuid.UUID, character_id: uuid.UUID, kind: str
) -> CharacterAuthoringView | None:
    """The identity authoring view of a character of `kind` (`npc` or
    `player_character`), or `None` when it does not exist in `world_id` or is a
    different kind -- so each kind's route reaches only its own records."""
    row = connection.execute(
        text("""
            SELECT e.canonical_name, e.summary, e.row_version,
                   cs.code AS canon_status, ls.code AS lifecycle_status,
                   c.species_id, sp.display_name AS species_name, c.size_category,
                   c.origin_location_id, d.background, d.appearance, d.notes
            FROM core.entities e
            JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id
            JOIN core.canon_statuses cs ON cs.canon_status_id = e.canon_status_id
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = e.lifecycle_status_id
            JOIN character.characters c ON c.character_id = e.entity_id
            JOIN rules.species sp ON sp.species_id = c.species_id
            LEFT JOIN character.character_descriptions d ON d.character_id = e.entity_id
            WHERE e.entity_id = :n AND e.world_id = :w AND et.code = :kind
        """),
        {"n": character_id, "w": world_id, "kind": kind},
    ).one_or_none()
    if row is None:
        return None
    extra_blocked = type_specific_blocks(connection, entity_id=character_id, entity_type_code=kind)
    available, blocked = evaluate_content_actions(
        entity_type_code=kind,
        canon_status=str(row.canon_status),
        lifecycle_status=str(row.lifecycle_status),
        extra_blocked=extra_blocked or None,
    )
    return CharacterAuthoringView(
        character_id=character_id,
        name=str(row.canonical_name),
        summary=row.summary,
        species_id=row.species_id,
        species_name=str(row.species_name),
        size_category=str(row.size_category),
        origin=_reference(connection, row.origin_location_id),
        background=row.background,
        appearance=row.appearance,
        notes=row.notes,
        canon_status=str(row.canon_status),
        lifecycle_status=str(row.lifecycle_status),
        row_version=int(row.row_version),
        available_actions=available,
        blocked_actions=blocked,
    )
