"""Character public-profile endpoints (P03-A A2a): the draft, its releases, and the GM reads.

    GET  /campaigns/{campaign_id}/characters/{character_id}/public-profile
    GET  /campaigns/{campaign_id}/characters/{character_id}/public-profile/releases/{version_number}
    POST /campaigns/{campaign_id}/characters/{character_id}/public-profile/draft
    POST /campaigns/{campaign_id}/characters/{character_id}/public-profile/releases

Authorization (plan section 5.7, decision D8):

- The two reads need `campaign.view` at the route and the D8 read rule in the query (effective
  character-scoped `canon.edit` or current `character.reveal` authority, no whole-character deny);
  anyone else gets a non-disclosing 404.
- The draft save needs the role `canon.edit` at the route, then the D8 edit rule, re-resolved under
  the command's locks.
- A release needs `campaign.view` at the route (a reveal holder need not hold `canon.edit`), then
  `character.reveal` authority and no whole-character deny, checked by a dependency *before* the
  idempotency lookup so a caller who has lost the right cannot replay a stored response, and again
  under lock inside the command.

All three POSTs put the path's `character_id` into the idempotency fingerprint: the key's scope is
(actor, campaign, key), so without it the same key and body posted to another character would replay
the first character's stored response.

No audience reader exists here. A release makes nothing visible by itself; audiences see one only
through a later revelation (A3/A4). Audit rows (one per real change, none for a no-op, refusal or
replay) carry field names, versions and the authority source, never profile text.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response
from pydantic import Field
from sqlalchemy import Connection

from dnd_ai.commands.character_public_profile import (
    release_character_public_profile,
    require_may_edit,
    require_may_release,
    save_character_public_profile_draft,
)
from dnd_ai.domain.access import AccessContext
from dnd_ai.domain.public_profiles import (
    PUBLIC_PROFILE_NOTE_MAX_LENGTH,
    PUBLIC_PROFILE_TEXT_MAX_LENGTH,
)
from dnd_ai.queries.character_public_profile import (
    read_character_public_profile,
    read_character_public_profile_release,
)

from ._authoring import (
    BaseAuthoringRequest,
    finish_campaign_idempotency,
    start_campaign_idempotency,
)
from ._shared import timeline_world_id
from .access import require_campaign_capability
from .audit import record_change_log
from .correlation import get_request_correlation_id
from .deps import get_connection, get_idempotency_key
from .errors import NotFoundError

router = APIRouter(tags=["character-public-profile"])

_BASE = "/campaigns/{campaign_id}/characters/{character_id}/public-profile"

_view_access = require_campaign_capability("campaign.view")
_edit_access = require_campaign_capability("canon.edit")

_Conn = Annotated[Connection, Depends(get_connection)]
_Key = Annotated[str | None, Depends(get_idempotency_key)]
_Corr = Annotated[str | None, Depends(get_request_correlation_id)]

_SAVE_COMMAND = "save_character_public_profile_draft"
_RELEASE_COMMAND = "release_character_public_profile"


class SaveCharacterPublicProfileDraftRequest(BaseAuthoringRequest):
    """`expected_row_version` is required: `null` means "there is no draft yet". A field left out
    is untouched; an explicit `null` (or blank text) clears it."""

    expected_row_version: int | None = Field(ge=1)
    public_appearance: str | None = Field(default=None, max_length=PUBLIC_PROFILE_TEXT_MAX_LENGTH)
    public_background: str | None = Field(default=None, max_length=PUBLIC_PROFILE_TEXT_MAX_LENGTH)


class ReleaseCharacterPublicProfileRequest(BaseAuthoringRequest):
    """A release never takes field content: it snapshots the draft at this version."""

    expected_draft_row_version: int = Field(ge=1)
    release_note: str | None = Field(default=None, max_length=PUBLIC_PROFILE_NOTE_MAX_LENGTH)


def _edit_precheck(
    character_id: uuid.UUID,
    access: Annotated[AccessContext, Depends(_edit_access)],
    connection: _Conn,
) -> None:
    """Before the idempotency lookup: a caller who can no longer edit cannot replay a save."""
    require_may_edit(connection, access=access, character_id=character_id)


def _release_precheck(
    character_id: uuid.UUID,
    access: Annotated[AccessContext, Depends(_view_access)],
    connection: _Conn,
) -> None:
    """Before the idempotency lookup, and before the body is read: 403 `character_reveal_required`
    for a caller without reveal authority, 404 for a whole-character deny."""
    require_may_release(connection, access=access, character_id=character_id)


@router.get(_BASE)
def get_character_public_profile_endpoint(
    character_id: uuid.UUID,
    access: Annotated[AccessContext, Depends(_view_access)],
    connection: _Conn,
) -> dict[str, Any]:
    view = read_character_public_profile(connection, access=access, character_id=character_id)
    if view is None:
        raise NotFoundError()
    return view


@router.get(_BASE + "/releases/{version_number}")
def get_character_public_profile_release_endpoint(
    character_id: uuid.UUID,
    version_number: str,
    access: Annotated[AccessContext, Depends(_view_access)],
    connection: _Conn,
) -> dict[str, Any]:
    # A path segment that is not a release number names nothing: the same 404 as a missing release
    # (and the route manifest's generic probes substitute a UUID here).
    if not version_number.isdigit() or not 1 <= int(version_number) <= 2_147_483_647:
        raise NotFoundError()
    release = read_character_public_profile_release(
        connection, access=access, character_id=character_id, version_number=int(version_number)
    )
    if release is None:
        raise NotFoundError()
    return release


@router.post(_BASE + "/draft")
def save_character_public_profile_draft_endpoint(
    character_id: uuid.UUID,
    body: SaveCharacterPublicProfileDraftRequest,
    response: Response,
    access: Annotated[AccessContext, Depends(_edit_access)],
    _precheck: Annotated[None, Depends(_edit_precheck)],
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    idem = start_campaign_idempotency(
        connection,
        actor_user_id=access.user_id,
        campaign_id=access.campaign_id,
        idempotency_key=idempotency_key,
        command_name=_SAVE_COMMAND,
        payload={
            "character_id": str(character_id),
            **body.model_dump(mode="json", exclude_unset=True),
        },
        correlation_id=correlation_id,
    )
    if idem.replay is not None:
        return idem.replay
    result = save_character_public_profile_draft(
        connection,
        campaign_id=access.campaign_id,
        character_id=character_id,
        actor_user_id=access.user_id,
        expected_row_version=body.expected_row_version,
        fields={
            name: getattr(body, name)
            for name in ("public_appearance", "public_background")
            if name in body.model_fields_set
        },
    )
    if result.changed:
        record_change_log(
            connection,
            change_action_code="created" if result.created else "updated",
            schema_name="campaign",
            table_name="character_public_profiles",
            record_id=result.character_public_profile_id,
            entity_id=character_id,
            world_id=timeline_world_id(connection, access.timeline_id),
            actor_user_id=access.user_id,
            correlation_id=correlation_id,
            command_name=_SAVE_COMMAND,
            event_id=None,
            changed_fields={
                "changed_field_names": list(result.changed_field_names),
                "row_version": result.row_version,
            },
        )
    payload: dict[str, Any] = {
        "character_public_profile_id": str(result.character_public_profile_id),
        "character_id": str(result.character_id),
        "row_version": result.row_version,
        "created": result.created,
        "changed": result.changed,
    }
    response.status_code = 201 if result.created else 200
    finish_campaign_idempotency(connection, idem, status_code=response.status_code, body=payload)
    return payload


@router.post(_BASE + "/releases")
def release_character_public_profile_endpoint(
    character_id: uuid.UUID,
    body: ReleaseCharacterPublicProfileRequest,
    response: Response,
    access: Annotated[AccessContext, Depends(_view_access)],
    _precheck: Annotated[None, Depends(_release_precheck)],
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    idem = start_campaign_idempotency(
        connection,
        actor_user_id=access.user_id,
        campaign_id=access.campaign_id,
        idempotency_key=idempotency_key,
        command_name=_RELEASE_COMMAND,
        payload={"character_id": str(character_id), **body.model_dump(mode="json")},
        correlation_id=correlation_id,
    )
    if idem.replay is not None:
        return idem.replay
    result = release_character_public_profile(
        connection,
        campaign_id=access.campaign_id,
        character_id=character_id,
        actor_membership_id=access.campaign_membership_id,
        expected_draft_row_version=body.expected_draft_row_version,
        release_note=body.release_note,
    )
    if result.created:
        record_change_log(
            connection,
            change_action_code="created",
            schema_name="campaign",
            table_name="character_public_profile_releases",
            record_id=result.character_public_profile_release_id,
            entity_id=character_id,
            world_id=timeline_world_id(connection, access.timeline_id),
            actor_user_id=access.user_id,
            correlation_id=correlation_id,
            command_name=_RELEASE_COMMAND,
            event_id=None,
            changed_fields={
                "version_number": result.version_number,
                "from_draft_row_version": result.from_draft_row_version,
                "authority_source": result.authority_source_code,
            },
        )
    payload: dict[str, Any] = {
        "character_public_profile_release_id": str(result.character_public_profile_release_id),
        "character_public_profile_id": str(result.character_public_profile_id),
        "character_id": str(result.character_id),
        "version_number": result.version_number,
        "from_draft_row_version": result.from_draft_row_version,
        "authority_source": result.authority_source_code,
        "created": result.created,
        "is_latest": result.is_latest,
    }
    response.status_code = 201 if result.created else 200
    finish_campaign_idempotency(connection, idem, status_code=response.status_code, body=payload)
    return payload
