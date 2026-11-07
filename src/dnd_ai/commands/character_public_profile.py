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

**Release** (`release_character_public_profile`). Lock order (plan section 5.8; it reverses no row of
the A1 design's section 3): the caller's reveal-authority rows (`resolve_reveal_authority(lock=
"share")`: the owner assignment, or the `gm` assignment and the delegation row), then the caller's
membership `FOR SHARE`, the campaign `FOR KEY SHARE`, the character's `core.entities` row `FOR KEY
SHARE`, the draft `FOR UPDATE`. The membership is `FOR SHARE`, not `KEY SHARE`, so an access-group
addition naming the releaser (membership `FOR NO KEY UPDATE`, P1) serializes with the release at that
row in both orders; the membership comes before the entity because `create_resource_grant` locks
grantee membership, campaign, then target. After the last wait the command reads `clock_timestamp()`
and re-judges the authority at that instant (DEF-013): it must be the same source as the locked
read. It then re-resolves the `AccessContext` for the whole-character deny (404, before a stored
release can be returned) and writes.

Both commands raise only classified errors, write nothing on a refusal, and leave the audit row to
the route (one row per real change, never carrying profile text).
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
)
from dnd_ai.domain.organization_authoring import normalize_optional_text
from dnd_ai.domain.public_profiles import (
    AUTHORITY_DELEGATION,
    AUTHORITY_OWNER,
    FIELD_APPEARANCE,
    FIELD_BACKGROUND,
    ORIGIN_AUTHORED,
    PUBLIC_PROFILE_FIELDS,
    PUBLIC_PROFILE_NOTE_MAX_LENGTH,
    PUBLIC_PROFILE_TEXT_MAX_LENGTH,
    CharacterRevealRequiredError,
    PublicProfileCharacterNotActiveError,
    PublicProfileDraftMissingError,
    PublicProfileEditDeniedError,
    PublicProfileNotFoundError,
    has_effective_character_canon_edit,
    may_read_profile,
    whole_character_denied,
)
from dnd_ai.domain.reveal_authority import resolve_reveal_authority

from ._content import lock_authoring_scope
from ._shared import lifecycle_code, lookup_id

_ORIGIN_COLUMNS = {
    FIELD_APPEARANCE: (
        "public_appearance_origin_id",
        "public_appearance_origin_entity_row_version",
    ),
    FIELD_BACKGROUND: (
        "public_background_origin_id",
        "public_background_origin_entity_row_version",
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


@dataclass(frozen=True)
class _CharacterRow:
    world_id: uuid.UUID
    canon_status: str
    lifecycle_status: str


def _character_row(
    connection: Connection, *, world_id: uuid.UUID, character_id: uuid.UUID, lock_clause: str
) -> _CharacterRow:
    """The character's `core.entities` row under the given lock, or `PublicProfileNotFoundError`
    when it is not a character of this world. Status codes are read in separate statements (never
    joined inside the locking statement; see `lifecycle_code`)."""
    row = connection.execute(
        text(f"""
            SELECT world_id, canon_status_id, lifecycle_status_id
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


def save_character_public_profile_draft(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    character_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_row_version: int | None,
    fields: dict[str, str | None],
) -> SaveCharacterPublicProfileDraftResult:
    """Creates or updates the campaign's draft of the character's public profile.

    `fields` holds only the fields the request named: a field left out is untouched, an explicit
    `None` (or blank text) clears it and resets its origin to `authored`. Values identical to the
    stored ones write nothing and do not bump `row_version`. `expected_row_version` is the draft
    version the caller read, or `None` for "there is no draft yet"."""
    unknown = set(fields) - set(PUBLIC_PROFILE_FIELDS)
    if unknown:
        raise ValueError(f"unknown public-profile fields: {sorted(unknown)}")
    clean = {
        name: normalize_optional_text(value, field=name, max_length=PUBLIC_PROFILE_TEXT_MAX_LENGTH)
        for name, value in fields.items()
    }

    scope = lock_authoring_scope(
        connection, campaign_id=campaign_id, actor_user_id=actor_user_id, world_capability=None
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
                    public_background, public_background_origin_id,
                    created_by_membership_id, updated_by_membership_id
                )
                VALUES (:campaign, :character, :appearance, :origin, :background, :origin,
                        :membership, :membership)
                ON CONFLICT (campaign_id, character_id) DO NOTHING
                RETURNING character_public_profile_id, row_version
            """),
            {
                "campaign": campaign_id,
                "character": character_id,
                "appearance": clean.get(FIELD_APPEARANCE),
                "background": clean.get(FIELD_BACKGROUND),
                "origin": authored,
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
            changed_field_names=tuple(name for name in PUBLIC_PROFILE_FIELDS if name in clean),
        )

    draft = connection.execute(
        text("""
            SELECT character_public_profile_id, row_version, public_appearance, public_background
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
    changed = tuple(
        name
        for name in PUBLIC_PROFILE_FIELDS
        if name in clean and clean[name] != draft._mapping[name]
    )
    if not changed:
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
    for name in changed:
        origin_column, version_column = _ORIGIN_COLUMNS[name]
        assignments.append(f"{name} = :{name}")
        params[name] = clean[name]
        if clean[name] is None:
            # Clearing a field resets its origin; editing text keeps the origin (it over-attributes
            # rather than under-attributes: plan section 5.6).
            assignments.append(f"{origin_column} = :authored")
            assignments.append(f"{version_column} = NULL")
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
        changed_field_names=changed,
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
) -> ReleaseCharacterPublicProfileResult:
    """Publishes an immutable snapshot of the draft at `expected_draft_row_version`.

    The caller must hold `character.reveal` authority (an owner, or a GM with a live delegation),
    re-judged at a fresh database instant after the last lock wait. The snapshot is exactly the
    locked draft at that version; the command never takes field content. If that draft version was
    already released, the existing release is returned (`created=False`) even when the draft has
    since moved on; a whole-character deny is checked first, so a denied caller is never handed a
    release."""
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
                   public_background_origin_entity_row_version
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
            SELECT character_public_profile_release_id, version_number, authority_source_code
            FROM campaign.character_public_profile_releases
            WHERE character_public_profile_id = :profile AND from_draft_row_version = :version
        """),
        {"profile": profile_id, "version": expected_draft_row_version},
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
        )
    if int(draft.row_version) != expected_draft_row_version:
        raise StaleWriteError(f"the draft of {character_id} is at {draft.row_version}")
    _require_canon_and_active(character, character_id)

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
                public_background_origin_entity_row_version,
                authority_source_code, character_reveal_delegation_id,
                released_by_membership_id, release_note
            )
            VALUES (:profile, :campaign, :character, :version, :from_version,
                    :appearance, :appearance_origin, :appearance_origin_version,
                    :background, :background_origin, :background_origin_version,
                    :source, :delegation, :membership, :note)
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
            "source": AUTHORITY_OWNER if source == "owner" else AUTHORITY_DELEGATION,
            "delegation": delegation_id,
            "membership": actor_membership_id,
            "note": note,
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
