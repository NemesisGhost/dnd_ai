"""Character public-profile commands (P03-A A2a): save the draft, release a snapshot.

A campaign's GMs author two text fields (`public_appearance`, `public_background`) in a mutable
draft; someone holding `character.reveal` publishes an immutable, versioned release of the draft at
the version they reviewed. A release makes nothing visible by itself (audiences see one only through
a later revelation). The world definition (the character's entity and its legacy description
rows) is never written, and nothing here calls the sheet, calculation or rules modules.

**Save** (`save_character_public_profile_draft`). Locks as every authoring write does
(`lock_authoring_scope`, world capability not required): world, the caller's role rows and
membership, the account, the campaign `KEY SHARE`. It then re-resolves the caller's
`AccessContext` under those locks for the D8 edit rule (role `canon.edit`, no whole-character deny,
no `canon.edit` deny on the character), takes the character's `core.entities` row `FOR SHARE`, and
locks the draft `FOR UPDATE` (or races the unique index on a first save). `expected_row_version`
`None` means "there is no draft yet".

**Release** (`release_character_public_profile`). Lock order (plan sections 5.8 and 9.6; it reverses
no row of the A1 design's section 3): the world row `FOR SHARE` (the head of the global order, taken
on every release so the order is static and the releaser's world capability stands until commit),
then the caller's reveal-authority rows (`resolve_reveal_authority(lock=
"share")`: the owner assignment, or the `gm` assignment and the delegation row), then the caller's
membership `FOR SHARE`, the campaign `FOR KEY SHARE`, the character's `core.entities` row `FOR KEY
SHARE`, the draft `FOR UPDATE`. The membership is `FOR SHARE`, not `KEY SHARE`, so an access-group
addition naming the releaser (membership `FOR NO KEY UPDATE`, P1) serializes with the release at that
row in both orders; the membership comes before the entity because `create_resource_grant` locks
grantee membership, campaign, then target. After the last wait the command reads `clock_timestamp()`
and re-judges the authority at that instant (DEF-013): it must be the same source as the locked
read. It then re-resolves the `AccessContext` for the whole-character deny (404, before a stored
release can be returned) and writes.

**Restricted (copied) fields** (A2b-1, decision D7). Text copied from a character's legacy description
keeps the source-read restriction until a release covers it, tracked by a per-field restriction
watermark (migration 143). A save refuses text for a field withheld from the caller with 403
`public_profile_field_withheld`, after the token check and before the no-op comparison; it allows
clearing; and editing copied text keeps its origin and advances its watermark. A release that would
write a new snapshot refuses when any field would be withheld from the releaser. A retry of an
already released version does not (D7-d). `queries/public_profile_restrictions.py` derives which
fields are withheld; nothing per reader is stored.

**Player-profile origin (A5b, decision D16).** A field copied from a campaign player profile is
restricted the same way, with its own provenance pair (the source version and field, never the legacy
`origin_entity_row_version`) and the same watermark, and is judged by its own origin's source rule
(`may_read_player_profile`), so a draft holding one legacy and one player-profile field is evaluated
per field. This slice adds no command that writes that origin (the copy is A5c); the save and the
release only carry it correctly: a save of edited copied text keeps the provenance and advances the
watermark, a clear ends both provenances, and a release snapshots the pair.

**Copy** (`copy_legacy_text_to_public_profile_draft`, A2b-2). Copies one legacy description field
(`appearance` or `background`) of an NPC or player character into the draft field of the same name.
The kind comes from the character, never the request, and decides the source-read rule (`npc`: role
`canon.edit` plus world `world.canon.read_private`; `player_character`: role `canon.edit`; any other
kind has no source, 404). Lock order (plan section 9.6), the save's with the kind's world capability:
`lock_authoring_scope` (world `FOR SHARE` -> the caller's role rows and membership -> account ->
campaign `KEY SHARE`, then the world capability re-judged under the world lock), the `AccessContext`
re-resolved for the D8 edit rule, the character's `core.entities` row `FOR SHARE`, the entity's
`row_version` and then the description text read in separate statements under that lock (the only
writer of the description, `update_npc`, holds the entity `FOR UPDATE` and bumps `row_version` in the
same transaction, so the pair is consistent), and the draft `FOR UPDATE` (or the unique-index race of
a first save). The copy replaces the whole target field, keeps the other field, records the origin,
the source `row_version` and a restriction watermark equal to the draft's new `row_version`, and
always changes the draft, even when the text is identical: every copy starts new restricted content.

**Player-profile copy** (`copy_player_profile_field_to_public_profile_draft`, A5c, design section 9.3).
Copies one of the nine copy-eligible player-profile fields (never `boundaries` or `profile_notes`) of
the *version the caller read* into a draft field, as `player_profile`-origin restricted text with its
provenance pair and a watermark equal to the draft's new `row_version`. Lock order (design section
10.1): `lock_authoring_scope` (no world capability: the player-profile read rule is the role's
`canon.edit`), the `AccessContext` re-resolved for the D8 edit rule and the GM read rule, the
character's `core.entities` row `FOR SHARE`, the profile head `FOR SHARE` (source freshness is judged
there: a moved head is `player_profile_source_changed`, nothing written), the immutable version read
(no lock), then the draft `FOR UPDATE` or the unique-index race of a first copy. It never writes the
profile and publishes nothing: release and revelation remain separate steps. The result, and what the
route audits and stores as the receipt, carry ids, codes and versions, never the copied text.

Both legacy commands raise only classified errors, write nothing on a refusal, and leave the audit row to
the route (one row per real change, never carrying profile text). The copy's result, receipt and
audit row carry ids, field names, origin code and versions, never the copied text.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Connection, text

from dnd_ai.domain.access import AccessContext, resolve_access_context
from dnd_ai.domain.authoring import (
    CampaignArchivedError,
    CampaignNotAuthorizedError,
    StaleWriteError,
    WorldAuthorityRequiredError,
)
from dnd_ai.domain.authorization import R01_PENDING
from dnd_ai.domain.organization_authoring import normalize_optional_text
from dnd_ai.domain.player_profiles import (
    COPY_ELIGIBLE_PLAYER_PROFILE_FIELDS,
    PlayerProfileFieldEmptyError,
    PlayerProfileMissingError,
    PlayerProfileSourceChangedError,
    may_read_player_profile_as_gm,
)
from dnd_ai.domain.public_profiles import (
    AUTHORITY_DELEGATION,
    AUTHORITY_OWNER,
    FIELD_APPEARANCE,
    FIELD_BACKGROUND,
    FIELD_SUMMARY,
    KIND_NPC,
    KIND_PLAYER_CHARACTER,
    LEGACY_COPY_SOURCES,
    ORIGIN_AUTHORED,
    ORIGIN_PLAYER_PROFILE,
    PUBLIC_PROFILE_IDENTITY_FLAGS,
    PUBLIC_PROFILE_NOTE_MAX_LENGTH,
    PUBLIC_PROFILE_SAVEABLE_FIELDS,
    PUBLIC_PROFILE_TEXT_MAX_LENGTH,
    CharacterRevealRequiredError,
    PublicProfileCharacterNotActiveError,
    PublicProfileDraftMissingError,
    PublicProfileEditDeniedError,
    PublicProfileFieldWithheldError,
    PublicProfileIdentityUnavailableError,
    PublicProfileIdentityVersionRequiredError,
    PublicProfileLegacyTextMissingError,
    PublicProfileNotFoundError,
    has_effective_character_canon_edit,
    holds_character_view_tier,
    may_read_profile,
    whole_character_denied,
)
from dnd_ai.domain.reveal_authority import resolve_reveal_authority
from dnd_ai.domain.world_authority import WORLD_CANON_READ_PRIVATE
from dnd_ai.queries.public_profile_restrictions import (
    character_kind,
    may_read_source_now,
    withheld_fields,
)

from ._content import lock_authoring_scope
from ._shared import lifecycle_code, lookup_id

_ORIGIN_COLUMNS = {
    FIELD_APPEARANCE: (
        "public_appearance_origin_id",
        "public_appearance_origin_entity_row_version",
        "public_appearance_restricted_row_version",
    ),
    FIELD_BACKGROUND: (
        "public_background_origin_id",
        "public_background_origin_entity_row_version",
        "public_background_restricted_row_version",
    ),
}


# A5b: the player-profile provenance pair of each draft field (source version, source field). Never
# reused for the legacy `origin_entity_row_version`, which means something else.
_PLAYER_PROFILE_COLUMNS = {
    FIELD_APPEARANCE: (
        "public_appearance_origin_player_profile_version_id",
        "public_appearance_origin_player_profile_field_id",
    ),
    FIELD_BACKGROUND: (
        "public_background_origin_player_profile_version_id",
        "public_background_origin_player_profile_field_id",
    ),
}


@dataclass(frozen=True)
class SaveCharacterPublicProfileDraftResult:
    character_public_profile_id: uuid.UUID
    character_id: uuid.UUID
    row_version: int
    created: bool
    changed: bool
    changed_field_names: tuple[str, ...]


@dataclass(frozen=True)
class ReleaseCharacterPublicProfileResult:
    character_public_profile_release_id: uuid.UUID
    character_public_profile_id: uuid.UUID
    character_id: uuid.UUID
    version_number: int
    from_draft_row_version: int
    authority_source_code: str
    # True for the release this call wrote; False when the draft version had already been released
    # (a natural retry), in which case the existing release is returned.
    created: bool
    # Whether this is the profile's highest release. False for a retry after a later release.
    is_latest: bool
    # D6 (A4): whether this release published the character's species / size, and the
    # `core.entities.row_version` the snapshot was read at (set exactly when either was published).
    # Flags and a number only: never a code or a label.
    species_published: bool = False
    size_published: bool = False
    identity_entity_row_version: int | None = None


@dataclass(frozen=True)
class _CharacterRow:
    world_id: uuid.UUID
    canon_status: str
    lifecycle_status: str
    row_version: int


def _character_row(
    connection: Connection, *, world_id: uuid.UUID, character_id: uuid.UUID, lock_clause: str
) -> _CharacterRow:
    """The character's `core.entities` row under the given lock, or `PublicProfileNotFoundError`
    when it is not a character of this world. Status codes are read in separate statements (never
    joined inside the locking statement; see `lifecycle_code`)."""
    row = connection.execute(
        text(f"""
            SELECT world_id, canon_status_id, lifecycle_status_id, row_version
            FROM core.entities
            WHERE entity_id = :id AND world_id = :world
            {lock_clause}
        """),  # noqa: S608 - the lock clause is one of two literals
        {"id": character_id, "world": world_id},
    ).one_or_none()
    is_character = (
        row is not None
        and connection.execute(
            text("SELECT 1 FROM character.characters WHERE character_id = :id"),
            {"id": character_id},
        ).first()
        is not None
    )
    if row is None or not is_character:
        raise PublicProfileNotFoundError(f"character {character_id} is not in this world")
    canon = connection.execute(
        text("SELECT code FROM core.canon_statuses WHERE canon_status_id = :s"),
        {"s": row.canon_status_id},
    ).scalar()
    assert isinstance(canon, str)
    return _CharacterRow(
        world_id=row.world_id,
        canon_status=canon,
        lifecycle_status=lifecycle_code(connection, row.lifecycle_status_id),
        row_version=int(row.row_version),
    )


def _require_canon_and_active(character: _CharacterRow, character_id: uuid.UUID) -> None:
    if character.canon_status != "canon":
        raise PublicProfileNotFoundError(f"character {character_id} is not canon")
    if character.lifecycle_status != "active":
        raise PublicProfileCharacterNotActiveError(f"character {character_id} is not active")


def require_may_edit(
    connection: Connection, *, access: AccessContext, character_id: uuid.UUID
) -> None:
    """The D8 edit rule against a resolved `AccessContext`: a whole-character deny removes the
    character (404); a `canon.edit` deny on it, or its absence as a role capability, removes editing.
    A caller who can still read the profile (reveal authority) is told 403
    `public_profile_edit_denied`; anyone else finds nothing (404). Also the route's pre-check
    ahead of the idempotency lookup, so a caller who lost the right cannot replay a stored save."""
    if whole_character_denied(access, character_id):
        raise PublicProfileNotFoundError(f"character {character_id} is not visible")
    if has_effective_character_canon_edit(access, character_id):
        return
    authority = resolve_reveal_authority(
        connection,
        campaign_id=access.campaign_id,
        campaign_membership_id=access.campaign_membership_id,
    )
    if may_read_profile(access, character_id, has_reveal_authority=authority != "none"):
        raise PublicProfileEditDeniedError(f"editing {character_id} is denied")
    raise PublicProfileNotFoundError(f"character {character_id} is not visible")


def require_may_release(
    connection: Connection, *, access: AccessContext, character_id: uuid.UUID
) -> None:
    """The release route's pre-check, before the idempotency lookup: `character.reveal` authority
    (403 `character_reveal_required`, which says nothing about the character), then no
    whole-character deny (404). A caller who has lost either cannot replay a stored response."""
    authority = resolve_reveal_authority(
        connection,
        campaign_id=access.campaign_id,
        campaign_membership_id=access.campaign_membership_id,
    )
    if authority == "none":
        raise CharacterRevealRequiredError(
            f"membership {access.campaign_membership_id} cannot reveal"
        )
    if whole_character_denied(access, character_id):
        raise PublicProfileNotFoundError(f"character {character_id} is not visible")


@dataclass(frozen=True)
class CopyLegacyTextResult:
    character_public_profile_id: uuid.UUID
    character_id: uuid.UUID
    row_version: int
    created: bool
    source_field: str
    origin_code: str
    origin_entity_row_version: int


def _campaign_world_id(connection: Connection, campaign_id: uuid.UUID) -> uuid.UUID:
    world_id = connection.execute(
        text("""
            SELECT t.world_id FROM campaign.campaigns c
            JOIN campaign.timelines t ON t.timeline_id = c.timeline_id
            WHERE c.campaign_id = :campaign
        """),
        {"campaign": campaign_id},
    ).scalar()
    if world_id is None:
        raise CampaignNotAuthorizedError(f"campaign {campaign_id} does not exist")
    assert isinstance(world_id, uuid.UUID)
    return world_id


def require_may_copy(
    connection: Connection, *, access: AccessContext, character_id: uuid.UUID
) -> None:
    """The copy route's pre-check, before the idempotency lookup: the D8 edit rule, then a kind that
    has a legacy source in this campaign's world (else 404), then the source-read rule (403
    `world_authority_required` for an NPC without `world.canon.read_private`). A caller who has lost
    either right cannot replay a stored copy: the source read is the copy's own authority (D7)."""
    require_may_edit(connection, access=access, character_id=character_id)
    world_id = _campaign_world_id(connection, access.campaign_id)
    kind = character_kind(connection, character_id, world_id=world_id)
    if kind not in (KIND_NPC, KIND_PLAYER_CHARACTER):
        raise PublicProfileNotFoundError(f"character {character_id} has no legacy source")
    if not may_read_source_now(
        connection, access=access, character_id=character_id, world_id=world_id
    ):
        raise WorldAuthorityRequiredError(f"{access.user_id} cannot read a source here")


def copy_legacy_text_to_public_profile_draft(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    character_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_row_version: int | None,
    source_field: str,
) -> CopyLegacyTextResult:
    """Copies the character's legacy `source_field` text into the draft field of the same name.

    `expected_row_version` is the draft version the caller read, or `None` for "there is no draft
    yet" (the copy then creates it with only this field set). Raises `StaleWriteError` on a moved
    token, `PublicProfileLegacyTextMissingError` when the source is empty, and the save's and the
    source-read rule's refusals. Always writes (and bumps `row_version`) when it succeeds."""
    if source_field not in LEGACY_COPY_SOURCES:
        raise ValueError(f"unsupported legacy copy source: {source_field!r}")
    target, origin_code, description_column = LEGACY_COPY_SOURCES[source_field]
    origin_column, version_column, watermark_column = _ORIGIN_COLUMNS[target]
    pp_version_column, pp_field_column = _PLAYER_PROFILE_COLUMNS[target]
    other = FIELD_BACKGROUND if target == FIELD_APPEARANCE else FIELD_APPEARANCE
    other_origin_column = _ORIGIN_COLUMNS[other][0]

    # The kind is read unlocked (plan section 9.1 assumption) to choose the world capability the
    # scope must hold; a kind with no legacy source is a character that does not exist here.
    world_id = _campaign_world_id(connection, campaign_id)
    kind = character_kind(connection, character_id, world_id=world_id)
    if kind not in (KIND_NPC, KIND_PLAYER_CHARACTER):
        raise PublicProfileNotFoundError(f"character {character_id} has no legacy source")
    scope = lock_authoring_scope(
        connection,
        campaign_id=campaign_id,
        actor_user_id=actor_user_id,
        world_capability=WORLD_CANON_READ_PRIVATE if kind == KIND_NPC else None,
        plan=R01_PENDING,
    )
    access = resolve_access_context(connection, user_id=actor_user_id, campaign_id=campaign_id)
    if access is None:
        raise CampaignNotAuthorizedError(f"user {actor_user_id} has no access to {campaign_id}")
    character = _character_row(
        connection, world_id=scope.world_id, character_id=character_id, lock_clause="FOR SHARE"
    )
    require_may_edit(connection, access=access, character_id=character_id)
    if not may_read_source_now(
        connection, access=access, character_id=character_id, world_id=scope.world_id
    ):
        raise WorldAuthorityRequiredError(f"{actor_user_id} cannot read a source here")
    _require_canon_and_active(character, character_id)

    # The entity is held FOR SHARE, so no description write (which holds it FOR UPDATE and bumps its
    # row_version in the same transaction) can commit between these two reads: the pair is one state.
    source_version = connection.execute(
        text("SELECT row_version FROM core.entities WHERE entity_id = :id"), {"id": character_id}
    ).scalar_one()
    source_text = connection.execute(
        text(
            f"SELECT {description_column} FROM character.character_descriptions "  # noqa: S608
            "WHERE character_id = :id"
        ),
        {"id": character_id},
    ).scalar()
    clean = normalize_optional_text(
        source_text, field=source_field, max_length=PUBLIC_PROFILE_TEXT_MAX_LENGTH
    )
    if clean is None:
        raise PublicProfileLegacyTextMissingError(f"{character_id} has no {source_field} text")

    authored = lookup_id(
        connection,
        "campaign",
        "public_profile_field_origins",
        "public_profile_field_origin_id",
        ORIGIN_AUTHORED,
    )
    legacy = lookup_id(
        connection,
        "campaign",
        "public_profile_field_origins",
        "public_profile_field_origin_id",
        origin_code,
    )
    params: dict[str, object] = {
        "campaign": campaign_id,
        "character": character_id,
        "membership": access.campaign_membership_id,
        "authored": authored,
        "legacy": legacy,
        "text": clean,
        "source_version": int(source_version),
    }
    if expected_row_version is None:
        inserted = connection.execute(
            text(f"""
                INSERT INTO campaign.character_public_profiles (
                    campaign_id, character_id, {target}, {origin_column}, {version_column},
                    {watermark_column}, {other_origin_column},
                    created_by_membership_id, updated_by_membership_id
                )
                VALUES (:campaign, :character, :text, :legacy, :source_version, 1, :authored,
                        :membership, :membership)
                ON CONFLICT (campaign_id, character_id) DO NOTHING
                RETURNING character_public_profile_id, row_version
            """),  # noqa: S608 - the column names come from LEGACY_COPY_SOURCES
            params,
        ).one_or_none()
        if inserted is None:
            raise StaleWriteError(f"the draft of {character_id} already exists")
        profile_id, new_version, created = (
            inserted.character_public_profile_id,
            int(inserted.row_version),
            True,
        )
    else:
        draft = connection.execute(
            text("""
                SELECT character_public_profile_id, row_version
                FROM campaign.character_public_profiles
                WHERE campaign_id = :campaign AND character_id = :character
                FOR UPDATE
            """),
            {"campaign": campaign_id, "character": character_id},
        ).one_or_none()
        if draft is None:
            raise PublicProfileDraftMissingError(f"{character_id} has no draft")
        if int(draft.row_version) != expected_row_version:
            raise StaleWriteError(f"the draft of {character_id} is at {draft.row_version}")
        profile_id = draft.character_public_profile_id
        new_version = int(draft.row_version) + 1  # what `core.bump_row_version()` gives the row
        connection.execute(
            text(f"""
                UPDATE campaign.character_public_profiles
                SET {target} = :text, {origin_column} = :legacy,
                    {version_column} = :source_version, {watermark_column} = :new_version,
                    {pp_version_column} = NULL, {pp_field_column} = NULL,
                    updated_by_membership_id = :membership
                WHERE character_public_profile_id = :profile
            """),  # noqa: S608 - the column names come from LEGACY_COPY_SOURCES
            {**params, "profile": profile_id, "new_version": new_version},
        )
        created = False
    return CopyLegacyTextResult(
        character_public_profile_id=profile_id,
        character_id=character_id,
        row_version=new_version,
        created=created,
        source_field=source_field,
        origin_code=origin_code,
        origin_entity_row_version=int(source_version),
    )


@dataclass(frozen=True)
class CopyPlayerProfileFieldResult:
    character_public_profile_id: uuid.UUID
    character_id: uuid.UUID
    row_version: int
    created: bool
    player_profile_row_version: int
    source_field: str
    target_field: str


def require_may_copy_player_profile(
    connection: Connection, *, access: AccessContext, character_id: uuid.UUID
) -> None:
    """The player-profile copy route's pre-check, before the idempotency lookup: the D8 edit rule,
    then the player-profile GM read rule (404). In A5 the second is implied by the first (both are
    effective character-scoped `canon.edit`; a unit test pins that), but it is the copy's own source
    authority, so a caller who has lost either right cannot replay a stored copy."""
    require_may_edit(connection, access=access, character_id=character_id)
    if not may_read_player_profile_as_gm(access, character_id):
        raise PublicProfileNotFoundError(f"character {character_id} is not visible")


def copy_player_profile_field_to_public_profile_draft(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    character_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_row_version: int | None,
    expected_player_profile_row_version: int,
    source_field: str,
    target_field: str,
) -> CopyPlayerProfileFieldResult:
    """Copies the named player-profile field of the version the caller read into `target_field`.

    `expected_row_version` is the draft version the caller read (`None`: no draft yet);
    `expected_player_profile_row_version` is the profile head version the caller read (the source
    token). Raises `PlayerProfileMissingError`, `PlayerProfileSourceChangedError`,
    `PlayerProfileFieldEmptyError`, `PublicProfileDraftMissingError`, `StaleWriteError` and the
    save's authorization refusals; a refusal writes nothing. Always writes (and bumps `row_version`)
    when it succeeds, even for identical text: every copy starts new restricted content."""
    if source_field not in COPY_ELIGIBLE_PLAYER_PROFILE_FIELDS:
        raise ValueError(f"unsupported player-profile copy source: {source_field!r}")
    if target_field not in _ORIGIN_COLUMNS:
        raise ValueError(f"unsupported copy target: {target_field!r}")
    origin_column, version_column, watermark_column = _ORIGIN_COLUMNS[target_field]
    pp_version_column, pp_field_column = _PLAYER_PROFILE_COLUMNS[target_field]
    other = FIELD_BACKGROUND if target_field == FIELD_APPEARANCE else FIELD_APPEARANCE
    other_origin_column = _ORIGIN_COLUMNS[other][0]

    scope = lock_authoring_scope(
        connection,
        campaign_id=campaign_id,
        actor_user_id=actor_user_id,
        world_capability=None,
        plan=R01_PENDING,
    )
    access = resolve_access_context(connection, user_id=actor_user_id, campaign_id=campaign_id)
    if access is None:
        raise CampaignNotAuthorizedError(f"user {actor_user_id} has no access to {campaign_id}")
    character = _character_row(
        connection, world_id=scope.world_id, character_id=character_id, lock_clause="FOR SHARE"
    )
    require_may_edit(connection, access=access, character_id=character_id)
    if not may_read_player_profile_as_gm(access, character_id):
        raise PublicProfileNotFoundError(f"character {character_id} is not visible")
    _require_canon_and_active(character, character_id)

    # The head is held FOR SHARE: a profile edit (head FOR UPDATE) cannot commit between this check
    # and the end of the copy, so the version read below is still the one the caller read.
    head = connection.execute(
        text("""
            SELECT character_player_profile_id, row_version
            FROM campaign.character_player_profiles
            WHERE campaign_id = :campaign AND character_id = :character
            FOR SHARE
        """),
        {"campaign": campaign_id, "character": character_id},
    ).one_or_none()
    if head is None:
        raise PlayerProfileMissingError(f"{character_id} has no player profile")
    if int(head.row_version) != expected_player_profile_row_version:
        raise PlayerProfileSourceChangedError(
            f"the player profile of {character_id} is at {head.row_version}"
        )
    # A separate statement: the versions are immutable, so no lock is needed.
    version = connection.execute(
        text(f"""
            SELECT character_player_profile_version_id, {source_field} AS source_text
            FROM campaign.character_player_profile_versions
            WHERE character_player_profile_id = :profile AND campaign_id = :campaign
              AND character_id = :character AND profile_row_version = :version
        """),  # noqa: S608 - the column is one of the nine copy-eligible codes (checked above)
        {
            "profile": head.character_player_profile_id,
            "campaign": campaign_id,
            "character": character_id,
            "version": expected_player_profile_row_version,
        },
    ).one()
    clean = normalize_optional_text(
        version.source_text, field=source_field, max_length=PUBLIC_PROFILE_TEXT_MAX_LENGTH
    )
    if clean is None:
        raise PlayerProfileFieldEmptyError(f"{character_id} has no {source_field} text")
    source_field_id = connection.execute(
        text("SELECT player_profile_field_id FROM campaign.player_profile_fields WHERE code = :c"),
        {"c": source_field},
    ).scalar_one()
    authored = lookup_id(
        connection,
        "campaign",
        "public_profile_field_origins",
        "public_profile_field_origin_id",
        ORIGIN_AUTHORED,
    )
    copied = lookup_id(
        connection,
        "campaign",
        "public_profile_field_origins",
        "public_profile_field_origin_id",
        ORIGIN_PLAYER_PROFILE,
    )
    params: dict[str, object] = {
        "campaign": campaign_id,
        "character": character_id,
        "membership": access.campaign_membership_id,
        "authored": authored,
        "copied": copied,
        "text": clean,
        "pp_version": version.character_player_profile_version_id,
        "pp_field": source_field_id,
    }
    if expected_row_version is None:
        inserted = connection.execute(
            text(f"""
                INSERT INTO campaign.character_public_profiles (
                    campaign_id, character_id, {target_field}, {origin_column},
                    {pp_version_column}, {pp_field_column}, {watermark_column},
                    {other_origin_column}, created_by_membership_id, updated_by_membership_id
                )
                VALUES (:campaign, :character, :text, :copied, :pp_version, :pp_field, 1,
                        :authored, :membership, :membership)
                ON CONFLICT (campaign_id, character_id) DO NOTHING
                RETURNING character_public_profile_id, row_version
            """),  # noqa: S608 - the column names come from the fixed two-field tables
            params,
        ).one_or_none()
        if inserted is None:
            raise StaleWriteError(f"the draft of {character_id} already exists")
        profile_id, new_version, created = (
            inserted.character_public_profile_id,
            int(inserted.row_version),
            True,
        )
    else:
        draft = connection.execute(
            text("""
                SELECT character_public_profile_id, row_version
                FROM campaign.character_public_profiles
                WHERE campaign_id = :campaign AND character_id = :character
                FOR UPDATE
            """),
            {"campaign": campaign_id, "character": character_id},
        ).one_or_none()
        if draft is None:
            raise PublicProfileDraftMissingError(f"{character_id} has no draft")
        if int(draft.row_version) != expected_row_version:
            raise StaleWriteError(f"the draft of {character_id} is at {draft.row_version}")
        profile_id = draft.character_public_profile_id
        new_version = int(draft.row_version) + 1  # what `core.bump_row_version()` gives the row
        connection.execute(
            text(f"""
                UPDATE campaign.character_public_profiles
                SET {target_field} = :text, {origin_column} = :copied,
                    {version_column} = NULL,
                    {pp_version_column} = :pp_version, {pp_field_column} = :pp_field,
                    {watermark_column} = :new_version,
                    updated_by_membership_id = :membership
                WHERE character_public_profile_id = :profile
            """),  # noqa: S608 - the column names come from the fixed two-field tables
            {**params, "profile": profile_id, "new_version": new_version},
        )
        created = False
    return CopyPlayerProfileFieldResult(
        character_public_profile_id=profile_id,
        character_id=character_id,
        row_version=new_version,
        created=created,
        player_profile_row_version=expected_player_profile_row_version,
        source_field=source_field,
        target_field=target_field,
    )


def save_character_public_profile_draft(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    character_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_row_version: int | None,
    fields: dict[str, str | None],
    identity_flags: dict[str, bool] | None = None,
) -> SaveCharacterPublicProfileDraftResult:
    """Creates or updates the campaign's draft of the character's public profile.

    `fields` holds only the fields the request named: a field left out is untouched, an explicit
    `None` (or blank text) clears it and resets its origin to `authored`. `identity_flags` holds only
    the D6 controls the request named (`publish_species`, `publish_size`; strict booleans, never
    text): a flag left out is untouched, and a flag never enters origins, watermarks, the copy aid
    or the withheld check. Values identical to the stored ones write nothing and do not bump
    `row_version`; a change to text and flags in one request bumps it once. `expected_row_version`
    is the draft version the caller read, or `None` for "there is no draft yet"."""
    unknown = set(fields) - set(PUBLIC_PROFILE_SAVEABLE_FIELDS)
    if unknown:
        raise ValueError(f"unknown public-profile fields: {sorted(unknown)}")
    flags = dict(identity_flags or {})
    unknown_flags = set(flags) - set(PUBLIC_PROFILE_IDENTITY_FLAGS)
    if unknown_flags:
        raise ValueError(f"unknown public-profile flags: {sorted(unknown_flags)}")
    clean = {
        name: normalize_optional_text(value, field=name, max_length=PUBLIC_PROFILE_TEXT_MAX_LENGTH)
        for name, value in fields.items()
    }

    scope = lock_authoring_scope(
        connection,
        campaign_id=campaign_id,
        actor_user_id=actor_user_id,
        world_capability=None,
        plan=R01_PENDING,
    )
    access = resolve_access_context(connection, user_id=actor_user_id, campaign_id=campaign_id)
    if access is None:
        raise CampaignNotAuthorizedError(f"user {actor_user_id} has no access to {campaign_id}")
    character = _character_row(
        connection, world_id=scope.world_id, character_id=character_id, lock_clause="FOR SHARE"
    )
    require_may_edit(connection, access=access, character_id=character_id)
    _require_canon_and_active(character, character_id)

    membership_id = access.campaign_membership_id
    authored = lookup_id(
        connection,
        "campaign",
        "public_profile_field_origins",
        "public_profile_field_origin_id",
        ORIGIN_AUTHORED,
    )

    if expected_row_version is None:
        inserted = connection.execute(
            text("""
                INSERT INTO campaign.character_public_profiles (
                    campaign_id, character_id, public_appearance, public_appearance_origin_id,
                    public_background, public_background_origin_id, public_summary,
                    should_publish_species, should_publish_size,
                    created_by_membership_id, updated_by_membership_id
                )
                VALUES (:campaign, :character, :appearance, :origin, :background, :origin,
                        :summary, :species_flag, :size_flag, :membership, :membership)
                ON CONFLICT (campaign_id, character_id) DO NOTHING
                RETURNING character_public_profile_id, row_version
            """),
            {
                "campaign": campaign_id,
                "character": character_id,
                "appearance": clean.get(FIELD_APPEARANCE),
                "background": clean.get(FIELD_BACKGROUND),
                "summary": clean.get(FIELD_SUMMARY),
                "origin": authored,
                "species_flag": flags.get("publish_species", False),
                "size_flag": flags.get("publish_size", False),
                "membership": membership_id,
            },
        ).one_or_none()
        if inserted is None:
            # Another request created the draft first (we waited on its unique-index entry).
            raise StaleWriteError(f"the draft of {character_id} already exists")
        return SaveCharacterPublicProfileDraftResult(
            character_public_profile_id=inserted.character_public_profile_id,
            character_id=character_id,
            row_version=int(inserted.row_version),
            created=True,
            changed=True,
            changed_field_names=(
                *(name for name in PUBLIC_PROFILE_SAVEABLE_FIELDS if name in clean),
                *(name for name in PUBLIC_PROFILE_IDENTITY_FLAGS if name in flags),
            ),
        )

    draft = connection.execute(
        text("""
            SELECT character_public_profile_id, row_version, public_appearance, public_background,
                   public_summary, should_publish_species, should_publish_size,
                   public_appearance_origin_entity_row_version,
                   public_background_origin_entity_row_version,
                   public_appearance_origin_player_profile_version_id,
                   public_background_origin_player_profile_version_id
            FROM campaign.character_public_profiles
            WHERE campaign_id = :campaign AND character_id = :character
            FOR UPDATE
        """),
        {"campaign": campaign_id, "character": character_id},
    ).one_or_none()
    if draft is None:
        raise PublicProfileDraftMissingError(f"{character_id} has no draft")
    # 1. The token first: whether a field is withheld depends on the locked draft, which may differ
    #    from what a stale caller read, so a stale caller is told to reload (409) before anything
    #    about the draft's contents.
    if int(draft.row_version) != expected_row_version:
        raise StaleWriteError(f"the draft of {character_id} is at {draft.row_version}")
    # 2. Text for a field withheld from this caller refuses the whole request (D7-a), before the
    #    no-op comparison so a caller cannot learn whether a guess matched. Clearing (`None`) is
    #    allowed. The draft is held `FOR UPDATE`, which every release also takes, so the releases
    #    this sees cannot change under it.
    withheld = withheld_fields(
        connection,
        profile_id=draft.character_public_profile_id,
        access=access,
        character_id=character_id,
        world_id=scope.world_id,
    )
    if any(clean.get(name) is not None for name in withheld):
        raise PublicProfileFieldWithheldError(f"{character_id} holds copied text withheld from you")
    changed = tuple(
        name
        for name in PUBLIC_PROFILE_SAVEABLE_FIELDS
        if name in clean and clean[name] != draft._mapping[name]
    )
    changed_flags = tuple(
        name
        for name, column in PUBLIC_PROFILE_IDENTITY_FLAGS.items()
        if name in flags and flags[name] != draft._mapping[column]
    )
    if not changed and not changed_flags:
        return SaveCharacterPublicProfileDraftResult(
            character_public_profile_id=draft.character_public_profile_id,
            character_id=character_id,
            row_version=int(draft.row_version),
            created=False,
            changed=False,
            changed_field_names=(),
        )
    assignments = ["updated_by_membership_id = :membership"]
    params: dict[str, object] = {
        "membership": membership_id,
        "profile": draft.character_public_profile_id,
        "authored": authored,
    }
    new_version = int(draft.row_version) + 1  # what `core.bump_row_version()` gives the row
    for name in changed_flags:
        column = PUBLIC_PROFILE_IDENTITY_FLAGS[name]
        assignments.append(f"{column} = :{column}")
        params[column] = flags[name]
    for name in changed:
        if name == FIELD_SUMMARY:
            # Authored-only: no origin, source version or watermark.
            assignments.append(f"{name} = :{name}")
            params[name] = clean[name]
            continue
        origin_column, version_column, watermark_column = _ORIGIN_COLUMNS[name]
        pp_version_column, pp_field_column = _PLAYER_PROFILE_COLUMNS[name]
        assignments.append(f"{name} = :{name}")
        params[name] = clean[name]
        if clean[name] is None:
            # Clearing ends the lineage (I6): the origin, both provenances and the watermark go
            # together. Allowed even for a withheld field (D7-a).
            assignments.append(f"{origin_column} = :authored")
            assignments.append(f"{version_column} = NULL")
            assignments.append(f"{pp_version_column} = NULL")
            assignments.append(f"{pp_field_column} = NULL")
            assignments.append(f"{watermark_column} = NULL")
        elif (
            draft._mapping[version_column] is not None
            or draft._mapping[pp_version_column] is not None
        ):
            # Editing copied text keeps the origin (it over-attributes rather than under-
            # attributes) and advances the watermark to the new row_version (I2), so the field is
            # restricted again until a release covers the new text. The database refuses a content
            # change that does not.
            assignments.append(f"{watermark_column} = :new_version")
            params["new_version"] = new_version
    updated = connection.execute(
        text(
            "UPDATE campaign.character_public_profiles SET "  # noqa: S608
            + ", ".join(assignments)
            + " WHERE character_public_profile_id = :profile RETURNING row_version"
        ),
        params,
    ).scalar_one()
    return SaveCharacterPublicProfileDraftResult(
        character_public_profile_id=draft.character_public_profile_id,
        character_id=character_id,
        row_version=int(updated),
        created=False,
        changed=True,
        changed_field_names=(*changed, *changed_flags),
    )


def _database_clock(connection: Connection) -> datetime:
    value = connection.execute(text("SELECT clock_timestamp()")).scalar()
    assert isinstance(value, datetime)
    return value


def release_character_public_profile(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    character_id: uuid.UUID,
    actor_membership_id: uuid.UUID,
    expected_draft_row_version: int,
    release_note: str | None,
    expected_character_row_version: int | None = None,
) -> ReleaseCharacterPublicProfileResult:
    """Publishes an immutable snapshot of the draft at `expected_draft_row_version`.

    The caller must hold `character.reveal` authority (an owner, or a GM with a live delegation),
    re-judged at a fresh database instant after the last lock wait. The snapshot is exactly the
    locked draft at that version; the command never takes field content. If that draft version was
    already released, the existing release is returned (`created=False`) even when the draft has
    since moved on; a whole-character deny is checked first, so a denied caller is never handed a
    release.

    **Species and size (A4, decision D6).** When the draft publishes either, the release snapshots
    the character's actual species (id, code, display name) and size, read in one statement after
    every lock wait, together with the `core.entities.row_version` they were read at.
    `expected_character_row_version` is the version the releaser reviewed; it is required then
    (422) and must equal the version read under the entity lock (409 `stale_write`). A release that
    publishes neither ignores it. A natural retry matches the draft version and either no identity
    or the same character version, so the same draft version may be released again after a
    definition change."""
    note = normalize_optional_text(
        release_note, field="release_note", max_length=PUBLIC_PROFILE_NOTE_MAX_LENGTH
    )
    world_id = connection.execute(
        text("""
            SELECT t.world_id FROM campaign.campaigns c
            JOIN campaign.timelines t ON t.timeline_id = c.timeline_id
            WHERE c.campaign_id = :campaign
        """),
        {"campaign": campaign_id},
    ).scalar()
    if world_id is None:
        raise CampaignNotAuthorizedError(f"campaign {campaign_id} does not exist")
    assert isinstance(world_id, uuid.UUID)

    # The world row `FOR SHARE` first, the head of the global lock order (A2b-1): it pins the
    # releaser's world capability for the withheld check below, and every command that changes a
    # world role or ownership takes the world `FOR UPDATE` before anything this release holds.
    connection.execute(
        text("SELECT 1 FROM core.worlds WHERE world_id = :world FOR SHARE"), {"world": world_id}
    ).all()

    source = resolve_reveal_authority(
        connection,
        campaign_id=campaign_id,
        campaign_membership_id=actor_membership_id,
        lock="share",
    )
    if source == "none":
        raise CharacterRevealRequiredError(f"membership {actor_membership_id} cannot reveal")

    connection.execute(
        text(
            "SELECT 1 FROM security.campaign_memberships "
            "WHERE campaign_membership_id = :membership FOR SHARE"
        ),
        {"membership": actor_membership_id},
    ).all()
    campaign = connection.execute(
        text(
            "SELECT lifecycle_status_id FROM campaign.campaigns "
            "WHERE campaign_id = :campaign FOR KEY SHARE"
        ),
        {"campaign": campaign_id},
    ).one_or_none()
    if campaign is None:
        raise CampaignNotAuthorizedError(f"campaign {campaign_id} does not exist")
    if lifecycle_code(connection, campaign.lifecycle_status_id) != "active":
        raise CampaignArchivedError(f"campaign {campaign_id} is not active")
    character = _character_row(
        connection, world_id=world_id, character_id=character_id, lock_clause="FOR KEY SHARE"
    )
    draft = connection.execute(
        text("""
            SELECT character_public_profile_id, row_version,
                   public_appearance, public_appearance_origin_id,
                   public_appearance_origin_entity_row_version,
                   public_background, public_background_origin_id,
                   public_background_origin_entity_row_version, public_summary,
                   should_publish_species, should_publish_size,
                   public_appearance_origin_player_profile_version_id,
                   public_appearance_origin_player_profile_field_id,
                   public_background_origin_player_profile_version_id,
                   public_background_origin_player_profile_field_id
            FROM campaign.character_public_profiles
            WHERE campaign_id = :campaign AND character_id = :character
            FOR UPDATE
        """),
        {"campaign": campaign_id, "character": character_id},
    ).one_or_none()

    # Every lock wait is behind us: judge the caller at a fresh database instant. The authority
    # must be the same source the locked read found (its rows are the ones held); a delegation or
    # owner row that lapsed during a wait refuses the release and a retry resolves it afresh.
    fresh = resolve_reveal_authority(
        connection,
        campaign_id=campaign_id,
        campaign_membership_id=actor_membership_id,
        as_of=_database_clock(connection),
    )
    if fresh != source:
        raise CharacterRevealRequiredError(f"membership {actor_membership_id} cannot reveal now")
    access = _resolve_membership_access(connection, campaign_id, actor_membership_id)
    if whole_character_denied(access, character_id):
        raise PublicProfileNotFoundError(f"character {character_id} is not visible")

    if draft is None:
        raise PublicProfileDraftMissingError(f"{character_id} has no draft")
    profile_id: uuid.UUID = draft.character_public_profile_id

    existing = connection.execute(
        text("""
            SELECT character_public_profile_release_id, version_number, authority_source_code,
                   released_species_id, released_size_category, identity_entity_row_version
            FROM campaign.character_public_profile_releases
            WHERE character_public_profile_id = :profile AND from_draft_row_version = :version
              AND (identity_entity_row_version IS NULL
                   OR identity_entity_row_version = :character_version)
        """),
        {
            "profile": profile_id,
            "version": expected_draft_row_version,
            "character_version": expected_character_row_version,
        },
    ).one_or_none()
    if existing is not None:
        latest = _latest_version(connection, profile_id)
        return ReleaseCharacterPublicProfileResult(
            character_public_profile_release_id=existing.character_public_profile_release_id,
            character_public_profile_id=profile_id,
            character_id=character_id,
            version_number=int(existing.version_number),
            from_draft_row_version=expected_draft_row_version,
            authority_source_code=str(existing.authority_source_code),
            created=False,
            is_latest=int(existing.version_number) == latest,
            species_published=existing.released_species_id is not None,
            size_published=existing.released_size_category is not None,
            identity_entity_row_version=(
                None
                if existing.identity_entity_row_version is None
                else int(existing.identity_entity_row_version)
            ),
        )
    if int(draft.row_version) != expected_draft_row_version:
        raise StaleWriteError(f"the draft of {character_id} is at {draft.row_version}")
    _require_canon_and_active(character, character_id)
    publishes_species = bool(draft.should_publish_species)
    publishes_size = bool(draft.should_publish_size)
    identity: _IdentitySnapshot | None = None
    if publishes_species or publishes_size:
        if expected_character_row_version is None:
            raise PublicProfileIdentityVersionRequiredError(
                f"{character_id} publishes species or size without a character row_version"
            )
        if expected_character_row_version != character.row_version:
            raise StaleWriteError(f"the character {character_id} is at {character.row_version}")
        # Species and size are summary-tier fields: the releaser must hold a character-view tier
        # (D7 item 3, for the new fields). Only a raw-row state can fail this for a built-in GM.
        if not holds_character_view_tier(access, character_id):
            raise PublicProfileFieldWithheldError(
                f"{character_id} species or size is withheld from membership {actor_membership_id}"
            )
        identity = _read_identity(
            connection,
            character_id=character_id,
            species=publishes_species,
            size=publishes_size,
            row_version=character.row_version,
        )
    # A new snapshot would publish every field of this draft version, so the releaser must be able
    # to read each one (D7 item 3). Retries and natural retries returned above, without this check
    # (D7-d).
    if withheld_fields(
        connection,
        profile_id=profile_id,
        access=access,
        character_id=character_id,
        world_id=world_id,
    ):
        raise PublicProfileFieldWithheldError(
            f"{character_id} holds copied text withheld from membership {actor_membership_id}"
        )

    delegation_id: uuid.UUID | None = None
    if source == "delegation":
        delegation_id = connection.execute(
            text("""
                SELECT character_reveal_delegation_id
                FROM security.character_reveal_delegations
                WHERE campaign_id = :campaign AND grantee_campaign_membership_id = :membership
                  AND revoked_at IS NULL
            """),
            {"campaign": campaign_id, "membership": actor_membership_id},
        ).scalar_one()
    next_version = _latest_version(connection, profile_id) + 1
    inserted = connection.execute(
        text("""
            INSERT INTO campaign.character_public_profile_releases (
                character_public_profile_id, campaign_id, character_id, version_number,
                from_draft_row_version,
                public_appearance, public_appearance_origin_id,
                public_appearance_origin_entity_row_version,
                public_background, public_background_origin_id,
                public_background_origin_entity_row_version, public_summary,
                public_appearance_origin_player_profile_version_id,
                public_appearance_origin_player_profile_field_id,
                public_background_origin_player_profile_version_id,
                public_background_origin_player_profile_field_id,
                authority_source_code, character_reveal_delegation_id,
                released_by_membership_id, release_note,
                released_species_id, released_species_code, released_species_display_name,
                released_size_category, identity_entity_row_version
            )
            VALUES (:profile, :campaign, :character, :version, :from_version,
                    :appearance, :appearance_origin, :appearance_origin_version,
                    :background, :background_origin, :background_origin_version, :summary,
                    :a_pp_version, :a_pp_field, :b_pp_version, :b_pp_field,
                    :source, :delegation, :membership, :note,
                    :species_id, :species_code, :species_name, :size, :identity_version)
            RETURNING character_public_profile_release_id
        """),
        {
            "profile": profile_id,
            "campaign": campaign_id,
            "character": character_id,
            "version": next_version,
            "from_version": expected_draft_row_version,
            "appearance": draft.public_appearance,
            "appearance_origin": draft.public_appearance_origin_id,
            "appearance_origin_version": draft.public_appearance_origin_entity_row_version,
            "background": draft.public_background,
            "background_origin": draft.public_background_origin_id,
            "background_origin_version": draft.public_background_origin_entity_row_version,
            "summary": draft.public_summary,
            "a_pp_version": draft.public_appearance_origin_player_profile_version_id,
            "a_pp_field": draft.public_appearance_origin_player_profile_field_id,
            "b_pp_version": draft.public_background_origin_player_profile_version_id,
            "b_pp_field": draft.public_background_origin_player_profile_field_id,
            "source": AUTHORITY_OWNER if source == "owner" else AUTHORITY_DELEGATION,
            "delegation": delegation_id,
            "membership": actor_membership_id,
            "note": note,
            "species_id": None if identity is None else identity.species_id,
            "species_code": None if identity is None else identity.species_code,
            "species_name": None if identity is None else identity.species_display_name,
            "size": None if identity is None else identity.size_category,
            "identity_version": None if identity is None else identity.row_version,
        },
    ).scalar_one()
    return ReleaseCharacterPublicProfileResult(
        character_public_profile_release_id=inserted,
        character_public_profile_id=profile_id,
        character_id=character_id,
        version_number=next_version,
        from_draft_row_version=expected_draft_row_version,
        authority_source_code=AUTHORITY_OWNER if source == "owner" else AUTHORITY_DELEGATION,
        created=True,
        is_latest=True,
        species_published=publishes_species,
        size_published=publishes_size,
        identity_entity_row_version=None if identity is None else identity.row_version,
    )


@dataclass(frozen=True)
class _IdentitySnapshot:
    """The definition values a release snapshots (only the selected ones are set)."""

    row_version: int
    species_id: uuid.UUID | None
    species_code: str | None
    species_display_name: str | None
    size_category: str | None


def _read_identity(
    connection: Connection,
    *,
    character_id: uuid.UUID,
    species: bool,
    size: bool,
    row_version: int,
) -> _IdentitySnapshot:
    """The character's species and/or size in ONE statement, after every lock wait: the release
    holds the entity row `FOR KEY SHARE`, which the only writer (`update_character_identity`, entity
    `FOR UPDATE`) conflicts with, so this is the state at `row_version`. Unselected fields are kept
    out of the snapshot. No row (unreachable: the columns are NOT NULL) is a classified refusal."""
    row = connection.execute(
        text("""
            SELECT ch.species_id, ch.size_category, sp.code AS species_code,
                   sp.display_name AS species_display_name
            FROM character.characters ch
            JOIN rules.species sp ON sp.species_id = ch.species_id
            WHERE ch.character_id = :id
        """),
        {"id": character_id},
    ).one_or_none()
    if row is None:
        raise PublicProfileIdentityUnavailableError(f"{character_id} has no species or size")
    return _IdentitySnapshot(
        row_version=row_version,
        species_id=row.species_id if species else None,
        species_code=row.species_code if species else None,
        species_display_name=row.species_display_name if species else None,
        size_category=row.size_category if size else None,
    )


def _latest_version(connection: Connection, profile_id: uuid.UUID) -> int:
    """The profile's highest release number (0 when it has none). Read under the draft's
    `FOR UPDATE` lock, which every release of the profile takes, so versions are gapless."""
    value = connection.execute(
        text(
            "SELECT COALESCE(MAX(version_number), 0) "
            "FROM campaign.character_public_profile_releases "
            "WHERE character_public_profile_id = :profile"
        ),
        {"profile": profile_id},
    ).scalar_one()
    return int(value)


def _resolve_membership_access(
    connection: Connection, campaign_id: uuid.UUID, campaign_membership_id: uuid.UUID
) -> AccessContext:
    """The membership's `AccessContext`, resolved from committed state under the release's locks
    (the whole-character deny re-check)."""
    user_id = connection.execute(
        text(
            "SELECT user_id FROM security.campaign_memberships "
            "WHERE campaign_membership_id = :membership"
        ),
        {"membership": campaign_membership_id},
    ).scalar()
    if user_id is None:
        raise CampaignNotAuthorizedError(f"membership {campaign_membership_id} does not exist")
    access = resolve_access_context(connection, user_id=user_id, campaign_id=campaign_id)
    if access is None:
        raise CampaignNotAuthorizedError(f"membership {campaign_membership_id} has no access")
    return access
