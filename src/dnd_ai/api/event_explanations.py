"""Event explanation contracts and audience (Phase 15 checkpoint CP-9a).

The one place the API turns the caller's `AccessContext` into an `ExplanationAudience` and the
domain `EventExplanation` into its response. Every surface that explains an event (the world event
page, the GM event view, the session activity and the recent events) calls `explain_for_caller`
so they cannot disagree. See `dnd_ai.queries.event_explanations` for what each field means and
for the access rules.
"""

import uuid
from collections.abc import Sequence
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection

from dnd_ai.domain.access import AccessContext
from dnd_ai.queries.event_explanations import (
    EventExplanation,
    ExplanationAudience,
    ExplanationClockTime,
    ExplanationRef,
    explain_events,
)
from dnd_ai.queries.session_travel import SessionTravelEntry

from ._shared import timeline_world_id
from .access import (
    CharacterViewNotAuthorizedError,
    can_open_participant,
    resolve_character_view_tier,
)

_CANON_EDIT = "canon.edit"
_VIEW = "campaign.view"


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


def travel_legs_response(entry: SessionTravelEntry) -> list[TravelLegResponse]:
    return [
        TravelLegResponse(
            traveler=TravelTravelerResponse(entity_id=leg.traveler_id, name=leg.traveler_name),
            **{
                "from": TravelPlaceResponse(
                    state=leg.origin.state, entity_id=leg.origin.entity_id, name=leg.origin.name
                )
            },
            to=TravelPlaceResponse(
                state=leg.destination.state,
                entity_id=leg.destination.entity_id,
                name=leg.destination.name,
            ),
        )
        for leg in entry.legs
    ]


class ExplanationRefResponse(BaseModel):
    """`state` is `named`, `unrecorded` (the event records no value) or `unavailable` (a value the
    caller may not see, or that no longer resolves). Id and name only when `named`."""

    state: str
    kind: str
    entity_id: uuid.UUID | None = None
    name: str | None = None
    openable: bool = False


class ExplanationClockTimeResponse(BaseModel):
    state: str
    text: str | None = None


class ExplanationRelationResponse(BaseModel):
    relation: str
    event: ExplanationRefResponse
    # Correction reason: canon.edit only, otherwise null.
    reason: str | None = None


class ExplanationSessionResponse(BaseModel):
    session_id: uuid.UUID
    session_number: int
    title: str | None


class ExplanationTravelResponse(BaseModel):
    legs: list[TravelLegResponse]


class EventExplanationResponse(BaseModel):
    event_id: uuid.UUID
    family: str
    # Effective in-world time (campaign calendar); never a wall-clock fallback.
    in_world_time: str
    # Real recording timestamp (UTC), shown separately from in-world time.
    recorded_at: datetime
    subject: ExplanationRefResponse | None = None
    party: ExplanationRefResponse | None = None
    build_detail: str | None = None
    previous_build: ExplanationRefResponse | None = None
    new_build: ExplanationRefResponse | None = None
    previous_time: ExplanationClockTimeResponse | None = None
    new_time: ExplanationClockTimeResponse | None = None
    travel: ExplanationTravelResponse | None = None
    session: ExplanationSessionResponse | None = None
    relations: list[ExplanationRelationResponse] = Field(default_factory=list)


def _ref(ref: ExplanationRef) -> ExplanationRefResponse:
    return ExplanationRefResponse(
        state=ref.state,
        kind=ref.kind,
        entity_id=ref.entity_id,
        name=ref.name,
        openable=ref.openable,
    )


def _optional_ref(ref: ExplanationRef | None) -> ExplanationRefResponse | None:
    return None if ref is None else _ref(ref)


def _time(value: ExplanationClockTime | None) -> ExplanationClockTimeResponse | None:
    return (
        None if value is None else ExplanationClockTimeResponse(state=value.state, text=value.text)
    )


def explanation_response(explanation: EventExplanation) -> EventExplanationResponse:
    session = explanation.session
    return EventExplanationResponse(
        event_id=explanation.event_id,
        family=explanation.family,
        in_world_time=explanation.in_world_time,
        recorded_at=explanation.recorded_at,
        subject=_optional_ref(explanation.subject),
        party=_optional_ref(explanation.party),
        build_detail=explanation.build_detail,
        previous_build=_optional_ref(explanation.previous_build),
        new_build=_optional_ref(explanation.new_build),
        previous_time=_time(explanation.previous_time),
        new_time=_time(explanation.new_time),
        travel=(
            None
            if explanation.travel is None
            else ExplanationTravelResponse(legs=travel_legs_response(explanation.travel))
        ),
        session=(
            None
            if session is None
            else ExplanationSessionResponse(
                session_id=session.session_id,
                session_number=session.session_number,
                title=session.title,
            )
        ),
        relations=[
            ExplanationRelationResponse(relation=r.relation, event=_ref(r.event), reason=r.reason)
            for r in explanation.relations
        ],
    )


def build_explanation_audience(
    access: AccessContext, connection: Connection, *, authoring: bool = False
) -> ExplanationAudience:
    # Imported here: `world_explorer` imports this module for its event page response.
    from .world_explorer import resolve_world_entity_visibility

    def may_read_build(character_id: uuid.UUID) -> bool:
        if not access.has_capability(_VIEW, entity_id=character_id):
            return False
        try:
            return resolve_character_view_tier(access, character_id=character_id)
        except CharacterViewNotAuthorizedError:
            return False

    return ExplanationAudience(
        campaign_id=access.campaign_id,
        world_id=timeline_world_id(connection, access.timeline_id),
        timeline_id=access.timeline_id,
        visibility=resolve_world_entity_visibility(access, connection),
        can_edit=access.has_capability(_CANON_EDIT),
        may_read_build=may_read_build,
        may_open_character=lambda character_id: can_open_participant(
            access, "character", character_id
        ),
        may_view_session=lambda session_id: access.has_capability(_VIEW, session_id=session_id),
        authoring=authoring,
    )


def explain_for_caller(
    access: AccessContext,
    connection: Connection,
    event_ids: Sequence[uuid.UUID],
    *,
    authoring: bool = False,
) -> dict[uuid.UUID, EventExplanationResponse]:
    audience = build_explanation_audience(access, connection, authoring=authoring)
    return {
        event_id: explanation_response(explanation)
        for event_id, explanation in explain_events(
            connection, event_ids=event_ids, audience=audience
        ).items()
    }
