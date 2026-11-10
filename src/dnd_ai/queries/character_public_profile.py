"""Reads of a character's public-profile draft and releases (P03-A A2a).

The audience readers (`read_released_profile`, `read_public_character`, A4) are the only functions
here that serve a non-GM. Every other reader is GM-side only and applies the D8 read rule (`may_read_profile`: effective
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
from dnd_ai.domain.npc_authoring import SIZE_CATEGORIES
from dnd_ai.domain.public_profiles import (
    KIND_NPC,
    KIND_PLAYER_CHARACTER,
    has_effective_character_canon_edit,
    holds_character_view_tier,
    may_read_profile,
)
from dnd_ai.domain.reveal_authority import resolve_reveal_authority
from dnd_ai.queries.public_profile_restrictions import (
    character_kind,
    may_read_source_now,
    withheld_fields,
)


@dataclass(frozen=True)
class LatestPublicProfileRelease:
    character_public_profile_release_id: uuid.UUID
    version_number: int
    public_appearance: str | None
    public_background: str | None
    public_summary: str | None = None


def latest_character_public_profile_release(
    connection: Connection, *, campaign_id: uuid.UUID, character_id: uuid.UUID
) -> LatestPublicProfileRelease | None:
    """The campaign's current release of the character's public profile: the highest version
    ("latest release wins"). The one query A3 and A4 read releases through; A2a has no audience
    reader of it."""
    row = connection.execute(
        text("""
            SELECT character_public_profile_release_id, version_number,
                   public_appearance, public_background, public_summary
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
        public_summary=row.public_summary,
    )


@dataclass(frozen=True)
class ReleasedValue:
    """A published `{code, label}` pair (species or size)."""

    code: str
    label: str


@dataclass(frozen=True)
class ReleasedProfile:
    """The audience projection of a campaign's latest release (plan section 12.3): content only.
    The release id, version, time, releaser, authority source, note, field origins, draft version,
    snapshotted species id and identity row version are never part of it."""

    summary: str | None
    appearance: str | None
    background: str | None
    species: ReleasedValue | None
    size: ReleasedValue | None


@dataclass(frozen=True)
class PublicCharacterRead:
    """The public tier's whole read: the canonical name (D5-c), the kind and the projection."""

    name: str
    character_kind: str
    profile: ReleasedProfile


# Names only the releases table: no `rules.*`, `character.characters`, description, draft or
# `core.entities.summary` (a unit test pins this). The label of a size comes from the static
# `SIZE_CATEGORIES` constant; a species label is the snapshot's own.
_RELEASED_PROFILE_SQL = """
    SELECT public_summary, public_appearance, public_background,
           released_species_code, released_species_display_name, released_size_category
    FROM campaign.character_public_profile_releases
    WHERE campaign_id = :campaign AND character_id = :character
    ORDER BY version_number DESC
    LIMIT 1
"""


def read_released_profile(
    connection: Connection, *, campaign_id: uuid.UUID, character_id: uuid.UUID
) -> ReleasedProfile | None:
    """The projection of this campaign's latest release of the character, or `None` when it has no
    release. The latest release wins as a whole snapshot: no field falls back to an earlier release,
    the canonical summary, the draft, legacy text or the live definition. Reads this campaign only.
    The caller has already decided the reader may see it (`may_read_released_profile`)."""
    row = connection.execute(
        text(_RELEASED_PROFILE_SQL), {"campaign": campaign_id, "character": character_id}
    ).one_or_none()
    if row is None:
        return None
    return ReleasedProfile(
        summary=row.public_summary,
        appearance=row.public_appearance,
        background=row.public_background,
        species=(
            None
            if row.released_species_code is None
            else ReleasedValue(row.released_species_code, row.released_species_display_name)
        ),
        size=(
            None
            if row.released_size_category is None
            else ReleasedValue(row.released_size_category, _SIZE_LABELS[row.released_size_category])
        ),
    )


def read_public_character(
    connection: Connection, *, access: AccessContext, character_id: uuid.UUID
) -> PublicCharacterRead | None:
    """The public-profile tier of the character detail (A4): the canonical name, the kind and the
    latest release of this campaign, or `None` (the fixed 404) when there is no release, which D9-d
    makes unreachable for a revelation holder. Never calls `get_character_view`, the sheet,
    calculations, inventory or the encounter readers, so no mechanical field and no
    `active_encounter_id` is ever computed. The route has already decided the tier."""
    profile = read_released_profile(
        connection, campaign_id=access.campaign_id, character_id=character_id
    )
    if profile is None:
        return None
    row = connection.execute(
        text("""
            SELECT e.canonical_name FROM core.entities e
            JOIN campaign.timelines t ON t.timeline_id = :timeline AND t.world_id = e.world_id
            WHERE e.entity_id = :character
        """),
        {"character": character_id, "timeline": access.timeline_id},
    ).one_or_none()
    kind = character_kind(connection, character_id)
    if row is None or kind is None:
        return None
    return PublicCharacterRead(name=row.canonical_name, character_kind=kind, profile=profile)


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


_SIZE_LABELS = dict(SIZE_CATEGORIES)


def _size_value(code: str) -> dict[str, str]:
    return {"code": code, "label": _SIZE_LABELS[code]}


def _live_identity(connection: Connection, character_id: uuid.UUID) -> Any | None:
    """The character's live species, size and `core.entities.row_version`: what the next release
    that publishes them would snapshot (GM read only; an audience never reads this)."""
    return connection.execute(
        text("""
            SELECT ch.species_id, ch.size_category, sp.code AS species_code,
                   sp.display_name AS species_display_name, e.row_version AS entity_row_version
            FROM character.characters ch
            JOIN rules.species sp ON sp.species_id = ch.species_id
            JOIN core.entities e ON e.entity_id = ch.character_id
            WHERE ch.character_id = :id
        """),
        {"id": character_id},
    ).one_or_none()


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
                "public_summary": row.public_summary,
                "release_note": row.release_note,
                # D6: the published values, from the snapshot alone (never the live definition).
                "species": (
                    None
                    if row.released_species_id is None
                    else {
                        "code": row.released_species_code,
                        "label": row.released_species_display_name,
                    }
                ),
                "size": (
                    None
                    if row.released_size_category is None
                    else _size_value(row.released_size_category)
                ),
                "identity_entity_row_version": (
                    None
                    if row.identity_entity_row_version is None
                    else int(row.identity_entity_row_version)
                ),
            }
        )
    return body


_RELEASE_COLUMNS = """
    r.character_public_profile_release_id, r.version_number, r.from_draft_row_version,
    r.authority_source_code, r.released_at,
    r.public_appearance, r.public_appearance_origin_id,
    r.public_background, r.public_background_origin_id, r.public_summary, r.release_note,
    r.released_species_id, r.released_species_code, r.released_species_display_name,
    r.released_size_category, r.identity_entity_row_version,
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


def _legacy_copy(
    connection: Connection,
    access: AccessContext,
    character_id: uuid.UUID,
    character: dict[str, Any],
) -> dict[str, bool] | None:
    """Which legacy description fields hold text to copy, or `None` unless the caller may copy now:
    an active character, the D8 edit rule, a kind with a legacy source, and the source-read rule
    (the same tests as the copy route). Only whether text exists is disclosed, never the text."""
    if not character["active"] or not has_effective_character_canon_edit(access, character_id):
        return None
    kind = character_kind(connection, character_id, world_id=character["world_id"])
    if kind not in (KIND_NPC, KIND_PLAYER_CHARACTER):
        return None
    if not may_read_source_now(
        connection, access=access, character_id=character_id, world_id=character["world_id"]
    ):
        return None
    row = connection.execute(
        text(
            "SELECT (btrim(coalesce(appearance, '')) <> '') AS appearance, "
            "(btrim(coalesce(background, '')) <> '') AS background "
            "FROM character.character_descriptions WHERE character_id = :id"
        ),
        {"id": character_id},
    ).one_or_none()
    return {
        "appearance": bool(row and row.appearance),
        "background": bool(row and row.background),
    }


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
                   public_background_origin_entity_row_version, public_summary,
                   should_publish_species, should_publish_size
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
        draft["public_summary"] = draft_row.public_summary
        draft["publish_species"] = bool(draft_row.should_publish_species)
        draft["publish_size"] = bool(draft_row.should_publish_size)
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
    # D6: the live species and size the next release would snapshot, shown only to a reader who
    # holds a character-view tier (they are summary-tier fields), and whether the latest release
    # has fallen behind the live definition for a field it published.
    live = _live_identity(connection, character_id)
    preview_withheld = not holds_character_view_tier(access, character_id)
    identity_preview: dict[str, Any] | None = None
    if live is not None and not preview_withheld:
        identity_preview = {
            "character_row_version": int(live.entity_row_version),
            "species": {"code": live.species_code, "label": live.species_display_name},
            "size": _size_value(live.size_category),
        }
    # The comparison needs the live definition, so it is only as readable as the preview: where
    # `identity_preview` is withheld (or the definition is unavailable) the indicator is withheld
    # too (`None`, never a false "unchanged"), so it cannot reveal whether unreadable identity data
    # changed.
    differs: bool | None = None
    if identity_preview is not None:
        differs = (
            latest is not None
            and live is not None
            and (
                (
                    latest.released_species_id is not None
                    and latest.released_species_id != live.species_id
                )
                or (
                    latest.released_size_category is not None
                    and latest.released_size_category != live.size_category
                )
            )
        )
    publishes_identity = draft is not None and (draft["publish_species"] or draft["publish_size"])
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
        # (and, when the draft publishes species or size, a preview the releaser can review)
        "can_release": character["active"]
        and can_reveal
        and not withheld
        and not (publishes_identity and preview_withheld),
        "identity_preview": identity_preview,
        "identity_preview_withheld": preview_withheld,
        "identity_differs_from_latest_release": differs,
        "legacy_copy": _legacy_copy(connection, access, character_id, character),
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
