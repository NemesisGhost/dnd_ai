"""Typed NPC identity authoring commands (Phase 15.1, ADR 0015).

`create_npc` / `update_npc` author an NPC's **identity**: `core.entities` (type
`npc`), `character.characters` (species, size, origin), the `character.npcs`
marker, and `character.character_descriptions` (background, appearance, GM
notes). Build, timeline state, inventory, goals, routines, and AI portrayal are
other write boundaries; player characters are Phase 16.

Species must come from a ruleset the world allows and be canon
(`rules.ruleset_allowed_for_world`, the same helper the database trigger uses);
the origin location is a newly referenced record under the shared reference
policy. Lock order: authority scope, then entities by ascending id (the target
`FOR UPDATE`, a changed origin `FOR SHARE`).
"""

import uuid
from typing import Any, Literal

from sqlalchemy import Connection, text

from dnd_ai.domain.authoring import (
    OriginLocationInvalidError,
    SpeciesNotAvailableError,
    normalize_reason,
)
from dnd_ai.domain.content_authoring import (
    AUTHORABLE_LOCATION_CATEGORIES,
    diff_fields,
    initial_fields,
)
from dnd_ai.domain.npc_authoring import normalize_npc_fields
from dnd_ai.domain.world_authority import WORLD_CANON_EDIT

from ._content import (
    ContentWriteResult,
    editable_target,
    insert_draft_entity,
    insert_gm_source,
    lock_authoring_scope,
    lock_entities,
    touch_entity,
    usable_reference,
)

CharacterKind = Literal["npc", "player_character"]

# The subtype marker row each kind owns: (table, primary-key column).
_MARKER: dict[str, tuple[str, str]] = {
    "npc": ("character.npcs", "npc_id"),
    "player_character": ("character.player_characters", "player_character_id"),
}


def _require_species(connection: Connection, *, world_id: uuid.UUID, species_id: uuid.UUID) -> None:
    """The species exists, is canon, and belongs to a ruleset the world allows.
    One non-disclosing code for every failure."""
    allowed = connection.execute(
        text("""
            SELECT EXISTS (
                SELECT 1
                FROM rules.species sp
                JOIN core.canon_statuses cs ON cs.canon_status_id = sp.canon_status_id
                WHERE sp.species_id = :s
                  AND cs.code = 'canon'
                  AND rules.ruleset_allowed_for_world(:w, sp.ruleset_version_id)
            )
        """),
        {"s": species_id, "w": world_id},
    ).scalar()
    if not allowed:
        raise SpeciesNotAvailableError(f"species {species_id} is not available")


def _text_id(value: uuid.UUID | None) -> str | None:
    return None if value is None else str(value)


def _identity_world_capability(kind: CharacterKind) -> str | None:
    """NPC identity is shared world canon (`world.canon.edit`). Player-character
    identity is the explicit D8/E3 exception: it stays campaign-authorized until
    Phase 16 defines player authoring."""
    return None if kind == "player_character" else WORLD_CANON_EDIT


def create_character_identity(
    connection: Connection,
    *,
    kind: CharacterKind,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    name: str | None,
    summary: str | None,
    species_id: uuid.UUID,
    size_category: str | None,
    origin_location_id: uuid.UUID | None = None,
    background: str | None = None,
    appearance: str | None = None,
    notes: str | None = None,
) -> ContentWriteResult:
    fields = normalize_npc_fields(
        name=name,
        summary=summary,
        size_category=size_category,
        background=background,
        appearance=appearance,
        notes=notes,
    )
    scope = lock_authoring_scope(
        connection,
        campaign_id=campaign_id,
        actor_user_id=actor_user_id,
        world_capability=_identity_world_capability(kind),
    )
    locked = lock_entities(
        connection,
        world_id=scope.world_id,
        share_ids=[origin_location_id] if origin_location_id is not None else [],
    )
    usable_reference(
        locked,
        origin_location_id,
        type_codes=AUTHORABLE_LOCATION_CATEGORIES,
        error=OriginLocationInvalidError,
    )
    _require_species(connection, world_id=scope.world_id, species_id=species_id)

    source_id = insert_gm_source(connection, world_id=scope.world_id, actor_user_id=actor_user_id)
    entity_id, row_version = insert_draft_entity(
        connection,
        world_id=scope.world_id,
        entity_type_code=kind,
        name=fields.name,
        summary=fields.summary,
        source_id=source_id,
        actor_user_id=actor_user_id,
    )
    connection.execute(
        text("""
            INSERT INTO character.characters
                (character_id, species_id, size_category, origin_location_id)
            VALUES (:id, :species, :size, :origin)
        """),
        {
            "id": entity_id,
            "species": species_id,
            "size": fields.size_category,
            "origin": origin_location_id,
        },
    )
    marker_table, marker_column = _MARKER[kind]
    connection.execute(
        text(f"INSERT INTO {marker_table} ({marker_column}) VALUES (:id)"),  # noqa: S608
        {"id": entity_id},
    )
    connection.execute(
        text("""
            INSERT INTO character.character_descriptions
                (character_id, background, appearance, notes)
            VALUES (:id, :background, :appearance, :notes)
        """),
        {
            "id": entity_id,
            "background": fields.background,
            "appearance": fields.appearance,
            "notes": fields.notes,
        },
    )
    return ContentWriteResult(
        entity_id=entity_id,
        world_id=scope.world_id,
        entity_type_code=kind,
        row_version=row_version,
        created=True,
        changed=True,
        changed_fields=initial_fields(
            {
                "name": fields.name,
                "summary": fields.summary,
                "species_id": str(species_id),
                "size_category": fields.size_category,
                "origin_location_id": _text_id(origin_location_id),
                "background": fields.background,
                "appearance": fields.appearance,
                "notes": fields.notes,
            }
        ),
        source_id=source_id,
    )


def update_character_identity(
    connection: Connection,
    *,
    kind: CharacterKind,
    campaign_id: uuid.UUID,
    character_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_row_version: int,
    name: str | None,
    summary: str | None,
    species_id: uuid.UUID,
    size_category: str | None,
    origin_location_id: uuid.UUID | None = None,
    background: str | None = None,
    appearance: str | None = None,
    notes: str | None = None,
    change_note: str | None = None,
) -> ContentWriteResult:
    normalize_reason(change_note)
    scope = lock_authoring_scope(
        connection,
        campaign_id=campaign_id,
        actor_user_id=actor_user_id,
        world_capability=_identity_world_capability(kind),
    )
    current_origin = connection.execute(
        text("SELECT origin_location_id FROM character.characters WHERE character_id = :id"),
        {"id": character_id},
    ).scalar()
    share_ids = (
        [origin_location_id]
        if origin_location_id is not None and origin_location_id != current_origin
        else []
    )
    locked = lock_entities(
        connection, world_id=scope.world_id, update_ids=[character_id], share_ids=share_ids
    )
    target = editable_target(
        locked,
        entity_id=character_id,
        type_codes=frozenset({kind}),
        expected_row_version=expected_row_version,
    )
    fields = normalize_npc_fields(
        name=name,
        summary=summary,
        size_category=size_category,
        background=background,
        appearance=appearance,
        notes=notes,
    )
    current = connection.execute(
        text("""
            SELECT c.species_id, c.size_category, c.origin_location_id,
                   d.background, d.appearance, d.notes
            FROM character.characters c
            LEFT JOIN character.character_descriptions d ON d.character_id = c.character_id
            WHERE c.character_id = :id
        """),
        {"id": character_id},
    ).one()
    changed_fields = diff_fields(
        {
            "name": target.canonical_name,
            "summary": target.summary,
            "species_id": _text_id(current.species_id),
            "size_category": current.size_category,
            "origin_location_id": _text_id(current.origin_location_id),
            "background": current.background,
            "appearance": current.appearance,
            "notes": current.notes,
        },
        {
            "name": fields.name,
            "summary": fields.summary,
            "species_id": str(species_id),
            "size_category": fields.size_category,
            "origin_location_id": _text_id(origin_location_id),
            "background": fields.background,
            "appearance": fields.appearance,
            "notes": fields.notes,
        },
    )
    if not changed_fields:
        return ContentWriteResult(
            entity_id=character_id,
            world_id=scope.world_id,
            entity_type_code=kind,
            row_version=target.row_version,
            created=False,
            changed=False,
        )

    if "origin_location_id" in changed_fields and origin_location_id is not None:
        if origin_location_id not in locked:
            locked.update(
                lock_entities(connection, world_id=scope.world_id, share_ids=[origin_location_id])
            )
        usable_reference(
            locked,
            origin_location_id,
            type_codes=AUTHORABLE_LOCATION_CATEGORIES,
            error=OriginLocationInvalidError,
        )
    if "species_id" in changed_fields:
        _require_species(connection, world_id=scope.world_id, species_id=species_id)

    new_version = touch_entity(
        connection, entity_id=character_id, name=fields.name, summary=fields.summary
    )
    if {"species_id", "size_category", "origin_location_id"} & set(changed_fields):
        connection.execute(
            text("""
                UPDATE character.characters
                SET species_id = :species, size_category = :size, origin_location_id = :origin
                WHERE character_id = :id
            """),
            {
                "species": species_id,
                "size": fields.size_category,
                "origin": origin_location_id,
                "id": character_id,
            },
        )
    if {"background", "appearance", "notes"} & set(changed_fields):
        connection.execute(
            text("""
                INSERT INTO character.character_descriptions
                    (character_id, background, appearance, notes)
                VALUES (:id, :background, :appearance, :notes)
                ON CONFLICT (character_id) DO UPDATE
                SET background = EXCLUDED.background,
                    appearance = EXCLUDED.appearance,
                    notes = EXCLUDED.notes
            """),
            {
                "id": character_id,
                "background": fields.background,
                "appearance": fields.appearance,
                "notes": fields.notes,
            },
        )
    return ContentWriteResult(
        entity_id=character_id,
        world_id=scope.world_id,
        entity_type_code=kind,
        row_version=new_version,
        created=False,
        changed=True,
        changed_fields=dict(changed_fields),
    )


def create_npc(connection: Connection, **kwargs: Any) -> ContentWriteResult:
    return create_character_identity(connection, kind="npc", **kwargs)


def update_npc(connection: Connection, *, npc_id: uuid.UUID, **kwargs: Any) -> ContentWriteResult:
    return update_character_identity(connection, kind="npc", character_id=npc_id, **kwargs)
