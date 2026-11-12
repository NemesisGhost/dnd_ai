"""Which fields of a public-profile draft are withheld from a caller (P03-A A2b-1, decision D7).

Text copied from a character's legacy description keeps the source-read restriction until a release
covers it (plan section 9). Restriction and withholding are *derived* on every read and command from
the draft's rows and its releases; nothing per reader is stored and no request can set them:

- a field is **restricted** when its text is not NULL, its origin is copied (legacy, or from A5b a
  campaign player profile), and no release of the profile covers it (a release covers a field when
  its `from_draft_row_version` is at or above the field's restriction watermark);
- a restricted field is **withheld** from a caller who fails the source-read rule *of that field's
  origin*: for a legacy origin the rule for the character's kind
  (`domain.public_profiles.may_read_legacy_source`), for a player-profile origin
  `domain.player_profiles.may_read_player_profile`. A draft holding one of each is judged per field,
  and the world capability is resolved only when a legacy NPC field needs it.

Reads take no locks. The commands call this after they hold the draft `FOR UPDATE`, which every
release also takes, so the set of releases it sees cannot change under them.
"""

import uuid

from sqlalchemy import Connection, text

from dnd_ai.domain.access import AccessContext
from dnd_ai.domain.player_profiles import (
    SOURCE_RULE_LEGACY,
    SOURCE_RULE_PLAYER_PROFILE,
    may_read_player_profile,
    source_rule_for_origin,
)
from dnd_ai.domain.public_profiles import (
    PUBLIC_PROFILE_FIELDS,
    RESTRICTED_ORIGINS,
    field_is_restricted,
    may_read_legacy_source,
)
from dnd_ai.queries.world_authority import resolve_world_authority


def character_kind(
    connection: Connection, character_id: uuid.UUID, *, world_id: uuid.UUID | None = None
) -> str | None:
    """The character's `core.entity_types.code` (`player_character`, `npc` or `character`); with
    `world_id`, `None` unless the entity belongs to that world."""
    value = connection.execute(
        text("""
            SELECT et.code FROM core.entities e
            JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id
            WHERE e.entity_id = :id AND (CAST(:world AS uuid) IS NULL OR e.world_id = :world)
        """),
        {"id": character_id, "world": world_id},
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


def restricted_origins(connection: Connection, profile_id: uuid.UUID) -> dict[str, str]:
    """The restricted fields of the draft (current content copied and not yet covered by a release),
    each with its origin code."""
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
        return {}
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
    return {
        name: str(states[name][1])
        for name in PUBLIC_PROFILE_FIELDS
        if field_is_restricted(
            has_text=states[name][0] is not None,
            is_legacy=states[name][1] in RESTRICTED_ORIGINS,
            watermark=states[name][2],
            covering_draft_version=covering,
        )
    }


def restricted_fields(connection: Connection, profile_id: uuid.UUID) -> frozenset[str]:
    """The fields of the draft whose current content is copied and not yet covered by a release."""
    return frozenset(restricted_origins(connection, profile_id))


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
    """The draft fields withheld from `access`'s holder: each restricted field, unless they pass the
    source-read rule of that field's own origin. The legacy rule (which may resolve world authority)
    is evaluated at most once, and only when a legacy field is restricted."""
    restricted = restricted_origins(connection, profile_id)
    if not restricted:
        return frozenset()
    legacy_readable: bool | None = None
    withheld: set[str] = set()
    for name, origin in restricted.items():
        rule = source_rule_for_origin(origin)
        if rule == SOURCE_RULE_PLAYER_PROFILE:
            readable = may_read_player_profile(access, character_id)
        elif rule == SOURCE_RULE_LEGACY:
            if legacy_readable is None:
                legacy_readable = may_read_source_now(
                    connection, access=access, character_id=character_id, world_id=world_id
                )
            readable = legacy_readable
        else:  # unreachable: only restricted origins are returned; fail closed
            readable = False
        if not readable:
            withheld.add(name)
    return frozenset(withheld)
