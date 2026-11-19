"""GM reads of a character's campaign player profile (P03-A A5a, decisions D13, D15 and D17).

Every reader here applies `may_read_player_profile` (the GM branch: effective character-scoped
`canon.edit`) and returns `None` otherwise, which the route maps to the generic non-disclosing 404,
the same body as for a missing version or a non-canon character. The content is classified
`CHARACTER_VISIBLE`; that classification grants nothing, so this rule is the only thing standing
between the text and a caller.

**One statement, one snapshot.** The current profile is read by joining the head to the version
whose `profile_row_version` equals the head's `row_version`, so the response can never mix one
edit's head with another edit's content (race RA1). The database also guarantees each head value has
exactly one version (migration 147), so the join cannot come back half-empty for a committed head.

Responses are built from explicit field lists; no row is serialized wholesale. No membership id, user
id, email or account name is returned, only the editing member's display name. Nothing here logs,
audits or formats an error from profile text. These readers take no locks and judge at the moment of
the read.

The module reads no GM-private store, no legacy character description table, no rules or sheet module and no
`core.entity_types`, and it never calls `capture_revision`.
"""

import uuid
from typing import Any

from sqlalchemy import Connection, text

from dnd_ai.domain.access import AccessContext
from dnd_ai.domain.player_profiles import PLAYER_PROFILE_FIELDS, may_read_player_profile

_FIELD_COLUMNS = ", ".join(f"v.{code}" for code in PLAYER_PROFILE_FIELDS)

# Both statements name the player-profile tables only, plus the editor's display name.
_CURRENT_SQL = f"""
    SELECT h.character_player_profile_id, h.row_version, h.updated_at,
           v.created_at AS edited_at, COALESCE(u.display_name, '') AS edited_by,
           {_FIELD_COLUMNS}
    FROM campaign.character_player_profiles h
    JOIN campaign.character_player_profile_versions v
      ON v.character_player_profile_id = h.character_player_profile_id
     AND v.profile_row_version = h.row_version
    LEFT JOIN security.campaign_memberships cm
      ON cm.campaign_membership_id = v.edited_by_campaign_membership_id
    LEFT JOIN security.users u ON u.user_id = cm.user_id
    WHERE h.campaign_id = :campaign AND h.character_id = :character
"""  # noqa: S608

_VERSION_SQL = f"""
    SELECT v.profile_row_version, v.created_at AS edited_at,
           COALESCE(u.display_name, '') AS edited_by,
           {_FIELD_COLUMNS}
    FROM campaign.character_player_profile_versions v
    LEFT JOIN security.campaign_memberships cm
      ON cm.campaign_membership_id = v.edited_by_campaign_membership_id
    LEFT JOIN security.users u ON u.user_id = cm.user_id
    WHERE v.campaign_id = :campaign AND v.character_id = :character
      AND v.profile_row_version = :version
"""  # noqa: S608


def _canon_character_status(
    connection: Connection, access: AccessContext, character_id: uuid.UUID
) -> bool | None:
    """Whether the character is active, or `None` unless it is a canon character of the campaign's
    world (a missing, non-canon or other-world character is indistinguishable)."""
    row = connection.execute(
        text("""
            SELECT cs.code AS canon_code, ls.code AS lifecycle_code
            FROM core.entities e
            JOIN character.characters ch ON ch.character_id = e.entity_id
            JOIN core.canon_statuses cs ON cs.canon_status_id = e.canon_status_id
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = e.lifecycle_status_id
            JOIN campaign.timelines t ON t.timeline_id = :timeline AND t.world_id = e.world_id
            WHERE e.entity_id = :character
        """),
        {"character": character_id, "timeline": access.timeline_id},
    ).one_or_none()
    if row is None or row.canon_code != "canon":
        return None
    return bool(row.lifecycle_code == "active")


def _fields_catalog(connection: Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        text("""
            SELECT code, display_name, is_copy_eligible
            FROM campaign.player_profile_fields
            WHERE is_active
            ORDER BY sort_order, code
        """)
    ).all()
    return [
        {"code": row.code, "label": row.display_name, "copy_eligible": bool(row.is_copy_eligible)}
        for row in rows
    ]


def _fields(row: Any) -> dict[str, str | None]:
    return {code: getattr(row, code) for code in PLAYER_PROFILE_FIELDS}


def read_player_profile(
    connection: Connection, *, access: AccessContext, character_id: uuid.UUID
) -> dict[str, Any] | None:
    """The character's current profile in this campaign (`profile` is `None` when it has none), or
    `None` (the generic 404) unless the caller passes the read rule and the character is a canon
    character of the campaign's world."""
    if not may_read_player_profile(access, character_id):
        return None
    active = _canon_character_status(connection, access, character_id)
    if active is None:
        return None
    row = connection.execute(
        text(_CURRENT_SQL), {"campaign": access.campaign_id, "character": character_id}
    ).one_or_none()
    profile: dict[str, Any] | None = None
    if row is not None:
        profile = {
            "character_player_profile_id": str(row.character_player_profile_id),
            "row_version": int(row.row_version),
            "updated_at": row.updated_at.isoformat(),
            "edited_at": row.edited_at.isoformat(),
            "edited_by": row.edited_by,
            "fields": _fields(row),
        }
    return {
        "character_id": str(character_id),
        "character_active": active,
        "profile": profile,
        "fields_catalog": _fields_catalog(connection),
    }


def read_player_profile_version(
    connection: Connection,
    *,
    access: AccessContext,
    character_id: uuid.UUID,
    profile_row_version: int,
) -> dict[str, Any] | None:
    """One immutable version, or `None` (the generic 404) when the caller may not read this
    profile or the version does not exist."""
    if not may_read_player_profile(access, character_id):
        return None
    if _canon_character_status(connection, access, character_id) is None:
        return None
    row = connection.execute(
        text(_VERSION_SQL),
        {
            "campaign": access.campaign_id,
            "character": character_id,
            "version": profile_row_version,
        },
    ).one_or_none()
    if row is None:
        return None
    return {
        "character_id": str(character_id),
        "profile_row_version": int(row.profile_row_version),
        "edited_at": row.edited_at.isoformat(),
        "edited_by": row.edited_by,
        "fields": _fields(row),
    }
