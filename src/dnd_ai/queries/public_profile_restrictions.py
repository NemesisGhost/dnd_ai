"""Which fields of a public-profile draft are withheld from a caller (P03-A A2b-1, decision D7).

Text copied from a character's legacy description keeps the source-read restriction until a release
covers it (plan section 9). Restriction and withholding are *derived* on every read and command from
the draft's rows and its releases; nothing per reader is stored and no request can set them:

- a field is **restricted** when its text is not NULL, its origin is legacy, and no release of the
  profile covers it (a release covers a field when its `from_draft_row_version` is at or above the
  field's restriction watermark);
- a restricted field is **withheld** from a caller who fails the source-read rule for the character's
  kind (`domain.public_profiles.may_read_legacy_source`).

Reads take no locks. The commands call this after they hold the draft `FOR UPDATE`, which every
release also takes, so the set of releases it sees cannot change under them.
"""

import uuid

from sqlalchemy import Connection, text

from dnd_ai.domain.access import AccessContext
from dnd_ai.domain.public_profiles import (
    LEGACY_ORIGINS,
    PUBLIC_PROFILE_FIELDS,
    field_is_restricted,
    may_read_legacy_source,
)
from dnd_ai.queries.world_authority import resolve_world_authority


def character_kind(connection: Connection, character_id: uuid.UUID) -> str | None:
    """The character's `core.entity_types.code` (`player_character`, `npc` or `character`)."""
    value = connection.execute(
        text("""
            SELECT et.code FROM core.entities e
            JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id
            WHERE e.entity_id = :id
        """),
        {"id": character_id},
    ).scalar()
    return None if value is None else str(value)


def covering_draft_version(connection: Connection, profile_id: uuid.UUID) -> int | None:
    """The highest `from_draft_row_version` of the profile's releases, or `None` when it has none."""
    value = connection.execute(
        text(
            "SELECT max(from_draft_row_version) "
            "FROM campaign.character_public_profile_releases "
            "WHERE character_public_profile_id = :profile"
        ),
        {"profile": profile_id},
    ).scalar()
    return None if value is None else int(value)


def restricted_fields(connection: Connection, profile_id: uuid.UUID) -> frozenset[str]:
    """The fields of the draft whose current content is copied and not yet covered by a release."""
    row = connection.execute(
        text("""
            SELECT d.public_appearance, ao.code AS appearance_origin,
                   d.public_appearance_restricted_row_version AS appearance_watermark,
                   d.public_background, bo.code AS background_origin,
                   d.public_background_restricted_row_version AS background_watermark
            FROM campaign.character_public_profiles d
            JOIN campaign.public_profile_field_origins ao
              ON ao.public_profile_field_origin_id = d.public_appearance_origin_id
            JOIN campaign.public_profile_field_origins bo
              ON bo.public_profile_field_origin_id = d.public_background_origin_id
            WHERE d.character_public_profile_id = :profile
        """),
        {"profile": profile_id},
    ).one_or_none()
    if row is None:
        return frozenset()
    covering = covering_draft_version(connection, profile_id)
    states = {
        "public_appearance": (
            row.public_appearance,
            row.appearance_origin,
            row.appearance_watermark,
        ),
        "public_background": (
            row.public_background,
            row.background_origin,
            row.background_watermark,
        ),
    }
    return frozenset(
        name
        for name in PUBLIC_PROFILE_FIELDS
        if field_is_restricted(
            has_text=states[name][0] is not None,
            is_legacy=states[name][1] in LEGACY_ORIGINS,
            watermark=states[name][2],
            covering_draft_version=covering,
        )
    )


def may_read_source_now(
    connection: Connection,
    *,
    access: AccessContext,
    character_id: uuid.UUID,
    world_id: uuid.UUID,
) -> bool:
    """The source-read rule for this character's kind, for this caller, judged now. The world
    capability is resolved only for an NPC (the one kind that needs it)."""
    kind = character_kind(connection, character_id)
    authority = (
        resolve_world_authority(connection, user_id=access.user_id, world_id=world_id)
        if kind == "npc"
        else None
    )
    return may_read_legacy_source(kind, access=access, world_authority=authority)


def withheld_fields(
    connection: Connection,
    *,
    profile_id: uuid.UUID,
    access: AccessContext,
    character_id: uuid.UUID,
    world_id: uuid.UUID,
) -> frozenset[str]:
    """The draft fields withheld from `access`'s holder: the restricted ones, unless they may read
    the source."""
    restricted = restricted_fields(connection, profile_id)
    if not restricted:
        return frozenset()
    if may_read_source_now(connection, access=access, character_id=character_id, world_id=world_id):
        return frozenset()
    return restricted
