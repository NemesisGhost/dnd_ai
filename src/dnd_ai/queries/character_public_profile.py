"""Reads of a character's public-profile draft and releases (P03-A A2a).

GM-side only: every reader here applies the D8 read rule (`may_read_profile`: effective
character-scoped `canon.edit`, or current `character.reveal` authority, and no whole-character deny)
and returns `None` otherwise, which the route maps to a non-disclosing 404. No audience reader
selects these tables in A2a; `latest_character_public_profile_release` is the single query A3/A4
will use and has no caller yet.

Reads are judged at the moment of the read and take no locks.
"""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection, text

from dnd_ai.domain.access import AccessContext
from dnd_ai.domain.public_profiles import (
    has_effective_character_canon_edit,
    may_read_profile,
)
from dnd_ai.domain.reveal_authority import resolve_reveal_authority
from dnd_ai.queries.public_profile_restrictions import withheld_fields


@dataclass(frozen=True)
class LatestPublicProfileRelease:
    character_public_profile_release_id: uuid.UUID
    version_number: int
    public_appearance: str | None
    public_background: str | None


def latest_character_public_profile_release(
    connection: Connection, *, campaign_id: uuid.UUID, character_id: uuid.UUID
) -> LatestPublicProfileRelease | None:
    """The campaign's current release of the character's public profile: the highest version
    ("latest release wins"). The one query A3 and A4 read releases through; A2a has no audience
    reader of it."""
    row = connection.execute(
        text("""
            SELECT character_public_profile_release_id, version_number,
                   public_appearance, public_background
            FROM campaign.character_public_profile_releases
            WHERE campaign_id = :campaign AND character_id = :character
            ORDER BY version_number DESC
            LIMIT 1
        """),
        {"campaign": campaign_id, "character": character_id},
    ).one_or_none()
    if row is None:
        return None
    return LatestPublicProfileRelease(
        character_public_profile_release_id=row.character_public_profile_release_id,
        version_number=int(row.version_number),
        public_appearance=row.public_appearance,
        public_background=row.public_background,
    )


def _character(
    connection: Connection, access: AccessContext, character_id: uuid.UUID
) -> dict[str, Any] | None:
    """The character's label and status when it is a canon character of the campaign's world."""
    row = connection.execute(
        text("""
            SELECT e.world_id, e.canonical_name, e.summary, cs.code AS canon_code,
                   ls.code AS lifecycle_code
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
    return {
        "world_id": row.world_id,
        "name": row.canonical_name,
        "summary": row.summary,
        "active": row.lifecycle_code == "active",
    }


def _origin_codes(connection: Connection) -> dict[uuid.UUID, str]:
    rows = connection.execute(
        text(
            "SELECT public_profile_field_origin_id, code FROM campaign.public_profile_field_origins"
        )
    ).all()
    return {row.public_profile_field_origin_id: str(row.code) for row in rows}


def _release_json(row: Any, origins: dict[uuid.UUID, str], *, with_text: bool) -> dict[str, Any]:
    body: dict[str, Any] = {
        "character_public_profile_release_id": str(row.character_public_profile_release_id),
        "version_number": int(row.version_number),
        "from_draft_row_version": int(row.from_draft_row_version),
        "authority_source": row.authority_source_code,
        "released_at": row.released_at.isoformat(),
        "released_by": row.released_by_name,
    }
    if with_text:
        body.update(
            {
                "public_appearance": row.public_appearance,
                "public_appearance_origin": origins[row.public_appearance_origin_id],
                "public_background": row.public_background,
                "public_background_origin": origins[row.public_background_origin_id],
                "release_note": row.release_note,
            }
        )
    return body


_RELEASE_COLUMNS = """
    r.character_public_profile_release_id, r.version_number, r.from_draft_row_version,
    r.authority_source_code, r.released_at,
    r.public_appearance, r.public_appearance_origin_id,
    r.public_background, r.public_background_origin_id, r.release_note,
    COALESCE(u.display_name, '') AS released_by_name
"""
_RELEASE_JOINS = """
    FROM campaign.character_public_profile_releases r
    LEFT JOIN security.campaign_memberships cm
      ON cm.campaign_membership_id = r.released_by_membership_id
    LEFT JOIN security.users u ON u.user_id = cm.user_id
"""


def _readable(
    connection: Connection, access: AccessContext, character_id: uuid.UUID
) -> tuple[dict[str, Any], bool] | None:
    """`(character, holds_reveal_authority)` when the caller may read this character's profile."""
    character = _character(connection, access, character_id)
    if character is None:
        return None
    authority = resolve_reveal_authority(
        connection,
        campaign_id=access.campaign_id,
        campaign_membership_id=access.campaign_membership_id,
    )
    if not may_read_profile(access, character_id, has_reveal_authority=authority != "none"):
        return None
    return character, authority != "none"


def read_character_public_profile(
    connection: Connection, *, access: AccessContext, character_id: uuid.UUID
) -> dict[str, Any] | None:
    """The draft, its release summaries and the latest release, with what the caller may do, or
    `None` when the caller may not read this profile (404)."""
    readable = _readable(connection, access, character_id)
    if readable is None:
        return None
    character, can_reveal = readable
    origins = _origin_codes(connection)
    draft_row = connection.execute(
        text("""
            SELECT character_public_profile_id, row_version, updated_at,
                   public_appearance, public_appearance_origin_id,
                   public_appearance_origin_entity_row_version,
                   public_background, public_background_origin_id,
                   public_background_origin_entity_row_version
            FROM campaign.character_public_profiles
            WHERE campaign_id = :campaign AND character_id = :character
        """),
        {"campaign": access.campaign_id, "character": character_id},
    ).one_or_none()
    releases = connection.execute(
        text(
            f"SELECT {_RELEASE_COLUMNS} {_RELEASE_JOINS} "  # noqa: S608
            "WHERE r.campaign_id = :campaign AND r.character_id = :character "
            "ORDER BY r.version_number DESC"
        ),
        {"campaign": access.campaign_id, "character": character_id},
    ).all()
    latest = releases[0] if releases else None
    draft: dict[str, Any] | None = None
    withheld: frozenset[str] = frozenset()
    if draft_row is not None:
        # Copied text still under its source-read restriction is withheld from a caller who may
        # not read the source (A2b-1, D7). The flag, the origin code and the source version are
        # disclosed (D7-f), never the text. Releases are never withheld.
        withheld = withheld_fields(
            connection,
            profile_id=draft_row.character_public_profile_id,
            access=access,
            character_id=character_id,
            world_id=character["world_id"],
        )
        draft = {
            "character_public_profile_id": str(draft_row.character_public_profile_id),
            "row_version": int(draft_row.row_version),
            "updated_at": draft_row.updated_at.isoformat(),
        }
        for field_name, text_value, origin_id, source_version in (
            (
                "public_appearance",
                draft_row.public_appearance,
                draft_row.public_appearance_origin_id,
                draft_row.public_appearance_origin_entity_row_version,
            ),
            (
                "public_background",
                draft_row.public_background,
                draft_row.public_background_origin_id,
                draft_row.public_background_origin_entity_row_version,
            ),
        ):
            is_withheld = field_name in withheld
            draft[field_name] = None if is_withheld else text_value
            draft[f"{field_name}_withheld"] = is_withheld
            draft[f"{field_name}_origin"] = origins[origin_id]
            draft[f"{field_name}_origin_entity_row_version"] = (
                None if source_version is None else int(source_version)
            )
    unreleased = draft is not None and (
        latest is None or int(latest.from_draft_row_version) != draft["row_version"]
    )
    return {
        "character_id": str(character_id),
        "label": {"name": character["name"], "summary": character["summary"]},
        "draft": draft,
        "has_unreleased_changes": unreleased,
        "latest_release": (
            None if latest is None else _release_json(latest, origins, with_text=True)
        ),
        "releases": [_release_json(row, origins, with_text=False) for row in releases],
        "can_edit": character["active"]
        and has_effective_character_canon_edit(access, character_id),
        # A release would publish every field, so it needs the releaser to read each one (D7 item 3).
        "can_release": character["active"] and can_reveal and not withheld,
    }


def read_character_public_profile_release(
    connection: Connection,
    *,
    access: AccessContext,
    character_id: uuid.UUID,
    version_number: int,
) -> dict[str, Any] | None:
    """One release snapshot, or `None` (404) when the caller may not read this profile or the
    version does not exist."""
    if _readable(connection, access, character_id) is None:
        return None
    origins = _origin_codes(connection)
    row = connection.execute(
        text(
            f"SELECT {_RELEASE_COLUMNS} {_RELEASE_JOINS} "  # noqa: S608
            "WHERE r.campaign_id = :campaign AND r.character_id = :character "
            "AND r.version_number = :version"
        ),
        {"campaign": access.campaign_id, "character": character_id, "version": version_number},
    ).one_or_none()
    if row is None:
        return None
    return {"character_id": str(character_id), **_release_json(row, origins, with_text=True)}
