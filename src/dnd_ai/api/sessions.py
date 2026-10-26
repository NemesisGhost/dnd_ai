"""Session-ending command endpoint, plus the session list/detail read side.

Exposes `end_session` as `POST /campaigns/
{campaign_id}/sessions/{session_id}/end`.

Authorization: requires `canon.edit`, the same GM/adapter-level scoping
`dnd_ai.api.interactions`/`.movement` use — ending a session is a
narrative/GM bookkeeping action, not access administration.

Idempotency: `end_session` is already idempotent for the common case
(ending an already-ended session is a no-op — see `dnd_ai.commands.
sessions`'s docstring), but this route still uses the durable `security.
idempotent_requests` mechanism every other create/mutate endpoint uses,
protecting the *first* end call against a dropped-response retry the same
way `dnd_ai.api.movement.enter_location_endpoint` does for its own
first-move call.

Auditing: one `audit.change_log` row per call that actually ended the
session (`result.already_ended is False`); a replay against an
already-ended session records nothing further, since nothing changed.
`entity_id` is `None` — `campaign.sessions` is not a `core.entities` row.
`world_id` is resolved server-side from the campaign's own pinned
timeline, never caller-supplied.

Phase 13D backend-readiness workstream added the read side:
`GET /campaigns/{campaign_id}/sessions` (list) and `GET /campaigns/
{campaign_id}/sessions/{session_id}` (detail) — see `dnd_ai.queries.
session`'s own module docstring for the full authorization/audience-
filtering contract (`campaign.view`, plus an optional per-session
`resource_grants` deny/allow, plus the same draft-event visibility rule
`dnd_ai.api.summary` already applies to its own recent-events list). These
are reads: no idempotency key, no `audit.change_log` row, for the same
reasons every other query router in this package has neither.
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection

from dnd_ai.domain.access import AccessContext
from dnd_ai.domain.session_participation import participant_role_options
from dnd_ai.queries.session import (
    MemberRosterAudience,
    get_session_view,
    list_campaign_sessions,
    list_session_participants,
)
from dnd_ai.queries.session_travel import list_session_travel

from ._shared import timeline_world_id
from .access import (
    CharacterViewNotAuthorizedError,
    require_campaign_capability,
    resolve_character_view_tier,
)
from .deps import get_connection
from .errors import NotFoundError
from .world_explorer import resolve_world_entity_visibility

router = APIRouter(tags=["sessions"])

# Narrative/GM bookkeeping, the same first-cut scoping every other command
# router in this codebase chose — see this module's own docstring.
_CANON_EDIT_CAPABILITY = "canon.edit"

# The read-only counterpart to _CANON_EDIT_CAPABILITY — the base gate every
# other read endpoint in this package uses (dnd_ai.api.dungeon/.characters/
# .quests/.knowledge/.summary all name the identical capability).
_SESSION_VIEW_CAPABILITY = "campaign.view"

# A caller holding this for the target session's own core.entities-less
# session_id resource-grant target additionally sees draft events linked to
# it — same split dnd_ai.api.summary already applies campaign-wide.
_DRAFT_EVENTS_CAPABILITY = "canon.edit"


# ---------------------------------------------------------------------------
# Read side (Phase 13D backend readiness) — response contracts
# ---------------------------------------------------------------------------


class SessionListItemResponse(BaseModel):
    session_id: uuid.UUID
    session_number: int
    title: str | None
    status_code: str
    started_at: datetime | None
    ended_at: datetime | None
    # Phase 15.2D-1: the planned start and the derived play status (D-13).
    scheduled_for: datetime | None = None
    play_status: str = "unscheduled"
    # Editors only: the version to send back, and what they can do.
    row_version: int | None = None
    available_actions: list[str] | None = None


class SessionEventResponse(BaseModel):
    event_id: uuid.UUID
    name: str
    summary: str | None
    event_type_code: str
    event_status_code: str
    world_time_id: uuid.UUID
    details: str | None
    # In-world time as display text. Real-world timestamps are separate session fields.
    world_time: str = ""


class TravelPlaceResponse(BaseModel):
    """One end of a leg. `state` is `named` (readable and discoverable by the caller),
    `unrecorded` (the traveler had no earlier location) or `unavailable` (not resolvable or not
    discoverable by the caller). A name is only ever present when `state` is `named`."""

    state: str
    entity_id: uuid.UUID | None = None
    name: str | None = None


class TravelTravelerResponse(BaseModel):
    entity_id: uuid.UUID
    name: str


class TravelLegResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    traveler: TravelTravelerResponse
    from_: TravelPlaceResponse = Field(alias="from")
    to: TravelPlaceResponse


class SessionTravelResponse(BaseModel):
    event_id: uuid.UUID
    world_time_id: uuid.UUID
    world_time: str
    # GM note: canon.edit only, otherwise null.
    note: str | None = None
    legs: list[TravelLegResponse]


class SessionParticipantResponse(BaseModel):
    session_participant_id: uuid.UUID
    character_id: uuid.UUID
    character_name: str
    character_kind: Literal["npc", "player_character", "character"]
    participation_role: str
    added_at: datetime
    removed_at: datetime | None
    # Whether the caller may open this character's page (the character route's own gate).
    # Always true for editors; for a member, discovering a character does not imply it.
    can_open_character: bool = True


class SessionDetailResponse(BaseModel):
    session_id: uuid.UUID
    session_number: int
    title: str | None
    status_code: str
    started_at: datetime | None
    ended_at: datetime | None
    summary: str | None
    start_world_time_id: uuid.UUID | None
    end_world_time_id: uuid.UUID | None
    events: list[SessionEventResponse]
    # Readable travel entries for the travel events above (same order). Additive.
    travel: list[SessionTravelResponse] = Field(default_factory=list)
    scheduled_for: datetime | None = None
    play_status: str = "unscheduled"
    row_version: int | None = None
    available_actions: list[str] | None = None
    # Editors: every stint. Members: every stint, present or left, of the characters the caller
    # may discover, with no trace of anyone else (no counts, placeholders or ids).
    participants: list[SessionParticipantResponse] | None = None
    # Editors only: the roles each kind of character may take, from the same policy the add
    # command enforces (character kind -> roles, matching role first). Additive.
    participant_role_options: dict[str, list[str]] | None = None


def _can_open_character(access: AccessContext, character_id: uuid.UUID) -> bool:
    """The character route's own gate, after the entity deny and lifecycle checks the member
    roster query has already applied: some character-view tier must be held."""
    try:
        resolve_character_view_tier(access, character_id=character_id)
    except CharacterViewNotAuthorizedError:
        return False
    return True


def _participants(
    connection: Connection, access: AccessContext, *, session_id: uuid.UUID, can_edit: bool
) -> list[SessionParticipantResponse]:
    audience = None
    if not can_edit:
        visibility = resolve_world_entity_visibility(access, connection)
        audience = MemberRosterAudience(
            character_visibility=visibility.character_visibility,
            denied_entity_ids=visibility.campaign_view_denied_entity_ids,
        )
    return [
        SessionParticipantResponse(
            session_participant_id=p.session_participant_id,
            character_id=p.character_id,
            character_name=p.character_name,
            character_kind=p.character_kind,  # type: ignore[arg-type]
            participation_role=p.participation_role,
            added_at=p.added_at,
            removed_at=p.removed_at,
            can_open_character=can_edit or _can_open_character(access, p.character_id),
        )
        for p in list_session_participants(connection, session_id=session_id, audience=audience)
    ]


def _actions(lifecycle_status: str, play_status: str) -> list[str]:
    """What an editor can do with the session, by lifecycle and derived play
    status (a session being played cannot be archived)."""
    if lifecycle_status == "archived":
        return ["restore"]
    if lifecycle_status != "active":
        # Every session command refuses a session that is not active (for example
        # a `pending` row), so offering actions would only lead to a 409.
        return []
    actions = ["update"]
    if play_status in ("unscheduled", "scheduled"):
        actions.append("start")
    if play_status in ("unscheduled", "scheduled", "in_progress"):
        actions.append("manage_participants")
    if play_status == "in_progress":
        actions.extend(["log", "end"])
    if play_status != "in_progress":
        actions.append("archive")
    return actions


# ---------------------------------------------------------------------------
# Read side — routes
# ---------------------------------------------------------------------------


@router.get(
    "/campaigns/{campaign_id}/sessions",
    response_model=list[SessionListItemResponse],
    status_code=200,
)
def list_sessions_endpoint(
    campaign_id: uuid.UUID,
    access: Annotated[
        AccessContext, Depends(require_campaign_capability(_SESSION_VIEW_CAPABILITY))
    ],
    connection: Annotated[Connection, Depends(get_connection)],
) -> list[SessionListItemResponse]:
    denied_session_ids, _allowed_session_ids = access.resource_grant_targets(
        _SESSION_VIEW_CAPABILITY, field_name="session_id"
    )
    editor = access.has_capability(_CANON_EDIT_CAPABILITY)
    # An archived session is hidden from anyone who cannot edit canon (D-13).
    items = list_campaign_sessions(
        connection,
        campaign_id=campaign_id,
        denied_session_ids=denied_session_ids,
        include_archived=editor,
    )
    return [
        SessionListItemResponse(
            session_id=item.session_id,
            session_number=item.session_number,
            title=item.title,
            status_code=item.status_code,
            started_at=item.started_at,
            ended_at=item.ended_at,
            scheduled_for=item.scheduled_for,
            play_status=item.play_status,
            row_version=item.row_version if editor else None,
            available_actions=_actions(item.status_code, item.play_status) if editor else None,
        )
        for item in items
    ]


@router.get(
    "/campaigns/{campaign_id}/sessions/{session_id}",
    response_model=SessionDetailResponse,
    status_code=200,
)
def get_session_endpoint(
    campaign_id: uuid.UUID,
    session_id: uuid.UUID,
    access: Annotated[
        AccessContext, Depends(require_campaign_capability(_SESSION_VIEW_CAPABILITY))
    ],
    connection: Annotated[Connection, Depends(get_connection)],
) -> SessionDetailResponse:
    if not access.has_capability(_SESSION_VIEW_CAPABILITY, session_id=session_id):
        # A per-session resource-grant deny — indistinguishable from a
        # nonexistent session, matching every other resource-scoped denial
        # in this codebase (dnd_ai.api.access's own module docstring).
        raise NotFoundError()

    denied_draft_event_ids, allowed_draft_event_ids = access.resource_grant_targets(
        _DRAFT_EVENTS_CAPABILITY, field_name="event_id"
    )
    view = get_session_view(
        connection,
        session_id=session_id,
        campaign_id=campaign_id,
        include_draft_events=access.has_capability(_DRAFT_EVENTS_CAPABILITY),
        denied_draft_event_ids=denied_draft_event_ids,
        allowed_draft_event_ids=allowed_draft_event_ids,
        include_archived=access.has_capability(_CANON_EDIT_CAPABILITY),
    )

    can_edit = access.has_capability(_CANON_EDIT_CAPABILITY)
    travel = list_session_travel(
        connection,
        events=view.events,
        world_id=timeline_world_id(connection, access.timeline_id),
        timeline_id=access.timeline_id,
        visibility=resolve_world_entity_visibility(access, connection),
        include_gm_note=can_edit,
    )

    return SessionDetailResponse(
        session_id=view.session_id,
        session_number=view.session_number,
        title=view.title,
        status_code=view.status_code,
        started_at=view.started_at,
        ended_at=view.ended_at,
        summary=view.summary,
        start_world_time_id=view.start_world_time_id,
        end_world_time_id=view.end_world_time_id,
        scheduled_for=view.scheduled_for,
        play_status=view.play_status,
        row_version=view.row_version if access.has_capability(_CANON_EDIT_CAPABILITY) else None,
        available_actions=(
            _actions(view.status_code, view.play_status)
            if access.has_capability(_CANON_EDIT_CAPABILITY)
            else None
        ),
        participants=_participants(connection, access, session_id=session_id, can_edit=can_edit),
        participant_role_options=(
            participant_role_options() if access.has_capability(_CANON_EDIT_CAPABILITY) else None
        ),
        events=[
            SessionEventResponse(
                event_id=e.event_id,
                name=e.name,
                summary=e.summary,
                event_type_code=e.event_type_code,
                event_status_code=e.event_status_code,
                world_time_id=e.world_time_id,
                world_time=e.world_time,
                # GM-only (D-3, data class GM_ONLY).
                details=e.details if access.has_capability(_CANON_EDIT_CAPABILITY) else None,
            )
            for e in view.events
        ],
        travel=[
            SessionTravelResponse(
                event_id=t.event_id,
                world_time_id=t.world_time_id,
                world_time=t.world_time,
                note=t.note if can_edit else None,
                legs=[
                    TravelLegResponse(
                        traveler=TravelTravelerResponse(
                            entity_id=leg.traveler_id, name=leg.traveler_name
                        ),
                        **{
                            "from": TravelPlaceResponse(
                                state=leg.origin.state,
                                entity_id=leg.origin.entity_id,
                                name=leg.origin.name,
                            )
                        },
                        to=TravelPlaceResponse(
                            state=leg.destination.state,
                            entity_id=leg.destination.entity_id,
                            name=leg.destination.name,
                        ),
                    )
                    for leg in t.legs
                ],
            )
            for t in travel
        ],
    )
