"""Player-character identity authoring commands (Phase 15.2B-1, decision D-7/D-8).

A player character's **identity** is authored exactly like an NPC's (species, size,
origin, background, appearance, GM notes) by the same shared command, with the
`character.player_characters` marker instead of `character.npcs`. It is created as
a draft and joins the lifecycle registry, so a draft is invisible to players on
every read surface until published. `player_user_id` is never set (D-8): who plays
a character is expressed only through `security.membership_character_relationships`,
which the access commands own. Builds, state, and approval are other boundaries.
"""

import uuid

from sqlalchemy import Connection

from ._content import ContentWriteResult
from .npcs import create_character_identity, update_character_identity


def create_player_character(
    connection: Connection,
    *,
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
    return create_character_identity(
        connection,
        kind="player_character",
        campaign_id=campaign_id,
        actor_user_id=actor_user_id,
        name=name,
        summary=summary,
        species_id=species_id,
        size_category=size_category,
        origin_location_id=origin_location_id,
        background=background,
        appearance=appearance,
        notes=notes,
    )


def update_player_character(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    player_character_id: uuid.UUID,
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
    return update_character_identity(
        connection,
        kind="player_character",
        campaign_id=campaign_id,
        character_id=player_character_id,
        actor_user_id=actor_user_id,
        expected_row_version=expected_row_version,
        name=name,
        summary=summary,
        species_id=species_id,
        size_category=size_category,
        origin_location_id=origin_location_id,
        background=background,
        appearance=appearance,
        notes=notes,
        change_note=change_note,
    )
