"""Command endpoint over `dnd_ai.commands.events.record_event` — Phase 10
workstream 9, continuing "command endpoints over the existing
command/application services" (docs/PLAN.md Phase 10) into the "interactions/
events" domain the Phase 10 progress note names as the last remaining
domain after workstream 8's relationship/organization endpoints
(`dnd_ai.api.relationships`) — alongside this workstream's own interaction
endpoints (`dnd_ai.api.interactions`).

Exposes the standalone `RecordEvent` command (docs/ENTITY_LIFECYCLE.md
§21) over HTTP as `POST /campaigns/{campaign_id}/events`, on the same
already-delivered OIDC authentication (`dnd_ai.api.auth`), transaction
management (`dnd_ai.api.deps`), and access resolution (`dnd_ai.api.access`,
`dnd_ai.domain.access`) every other command router uses.

The route runs on the request's own `get_connection` transaction and calls
the connection-taking `_record_event_impl` form of the command (never the
public engine-based `record_event`, which would open a second, nested
transaction) — identical to every route in `dnd_ai.api.encounters`/
`.items`/`.quests`/`.relationships`.

Authorization: requires the `canon.edit` role capability in the target
campaign (`dnd_ai.api.access.require_campaign_capability`) — the same
first-cut GM/adapter-level scoping every other command router's own
docstring records; a standalone recorded event is treated as a canon
mutation here for the same reason a quest-objective advancement or a
relationship-reaction evolution is.

`world_id` is never accepted from the request body: `record_event`'s own
`world_id` argument is always resolved server-side from the campaign's own
pinned timeline (`campaign.timelines.world_id`, via `access.timeline_id`)
— the same "never trust a caller-supplied world/timeline pairing" rule
every other command router already follows for `timeline_id` itself
(always `access.timeline_id`, never a request field).

Cross-campaign session integrity: the route passes the URL's own (already-
authorized) `campaign_id` and the request body's caller-supplied
`session_id` straight through to `_record_event_impl`, which validates the
two agree (`dnd_ai.commands._shared.validate_session_campaign`) before
writing anything, raising `SessionNotInCampaignError` — a `SafeMessageError`
the existing generic handler maps to a fixed, non-disclosing 404 — for a
nonexistent or foreign-campaign session.

Auditing: `narrative.events` rows are `core.entities` rows (class-table
inheritance, CLAUDE.md rule 4 — `event_id` *is* the entity_id), so
`record_event_endpoint` records `entity_id=result.event_id` directly,
unlike the quest/relationship routes' owning-entity indirection.

Idempotency: durable, PostgreSQL-backed, via `dnd_ai.api.idempotency` and
`security.idempotent_requests` (migration 082) — identical mechanism to
every other command router; see `dnd_ai.api.items`'s module docstring for
the full concurrency argument.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import Connection

from dnd_ai.commands.events import EventParticipant, _record_event_impl
from dnd_ai.domain.access import AccessContext

from ._shared import timeline_world_id
from .access import require_campaign_capability
from .audit import record_change_log
from .correlation import get_request_correlation_id
from .deps import get_connection, get_idempotency_key
from .idempotency import IdempotentReplay, begin_idempotent_request, complete_idempotent_request

router = APIRouter(tags=["events"])

# A standalone recorded event is a canon-affecting mutation (docs/
# architecture/DATABASE_MODEL.md §12.3) — see this module's docstring for
# why this route requires it rather than a narrower, character-scoped
# capability.
_EVENT_MANAGE_CAPABILITY = "canon.edit"

# audit.change_log.command_name / the idempotency store's fingerprinted
# command_name — one literal per route, never derived from request data.
_RECORD_EVENT_COMMAND_NAME = "record_event"

# audit.change_actions.code (revision 007 seed): each call always creates a
# new narrative.events row — there is no "insert vs. update" ambiguity the
# way a typed current-state table's own upsert has.
_CREATED_CHANGE_ACTION = "created"


# ---------------------------------------------------------------------------
# Request/response contracts
# ---------------------------------------------------------------------------


class EventParticipantRequest(BaseModel):
    entity_id: uuid.UUID
    role_code: str
    notes: str | None = None


class RecordEventRequest(BaseModel):
    world_time_id: uuid.UUID
    event_type_code: str
    name: str
    event_status_code: str = "recorded"
    details: str | None = None
    session_id: uuid.UUID | None = None
    participants: list[EventParticipantRequest] = Field(default_factory=list)
    cause_event_id: uuid.UUID | None = None
    cause_interaction_id: uuid.UUID | None = None
    cause_description: str | None = None


class RecordEventResponse(BaseModel):
    event_id: uuid.UUID


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post(
    "/campaigns/{campaign_id}/events",
    response_model=RecordEventResponse,
    status_code=201,
)
def record_event_endpoint(
    campaign_id: uuid.UUID,
    body: RecordEventRequest,
    access: Annotated[
        AccessContext, Depends(require_campaign_capability(_EVENT_MANAGE_CAPABILITY))
    ],
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> RecordEventResponse:
    reservation_id: uuid.UUID | None = None
    if idempotency_key is not None:
        fingerprint_payload: dict[str, Any] = body.model_dump(mode="json")
        outcome = begin_idempotent_request(
            connection,
            actor_user_id=access.user_id,
            campaign_id=campaign_id,
            idempotency_key=idempotency_key,
            command_name=_RECORD_EVENT_COMMAND_NAME,
            payload=fingerprint_payload,
            correlation_id=correlation_id,
        )
        if isinstance(outcome, IdempotentReplay):
            return RecordEventResponse.model_validate(outcome.response_body)
        reservation_id = outcome.idempotent_request_id

    world_id = timeline_world_id(connection, access.timeline_id)

    result = _record_event_impl(
        connection,
        world_id=world_id,
        timeline_id=access.timeline_id,
        world_time_id=body.world_time_id,
        event_type_code=body.event_type_code,
        name=body.name,
        event_status_code=body.event_status_code,
        details=body.details,
        campaign_id=campaign_id,
        session_id=body.session_id,
        participants=tuple(
            EventParticipant(entity_id=p.entity_id, role_code=p.role_code, notes=p.notes)
            for p in body.participants
        ),
        cause_event_id=body.cause_event_id,
        cause_interaction_id=body.cause_interaction_id,
        cause_description=body.cause_description,
    )

    record_change_log(
        connection,
        change_action_code=_CREATED_CHANGE_ACTION,
        schema_name="narrative",
        table_name="events",
        record_id=result.event_id,
        # narrative.events rows are core.entities rows (class-table
        # inheritance) — event_id is the entity_id directly.
        entity_id=result.event_id,
        world_id=world_id,
        actor_user_id=access.user_id,
        correlation_id=correlation_id,
        command_name=_RECORD_EVENT_COMMAND_NAME,
        event_id=result.event_id,
    )

    response = RecordEventResponse(event_id=result.event_id)

    if reservation_id is not None:
        complete_idempotent_request(
            connection,
            idempotent_request_id=reservation_id,
            response_status_code=201,
            response_body=response.model_dump(mode="json"),
        )

    return response
