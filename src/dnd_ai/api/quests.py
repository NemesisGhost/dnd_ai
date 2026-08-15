"""Command endpoints over `dnd_ai.commands.quests` — Phase 10 workstream 7,
continuing "command endpoints over the existing command/application
services" (docs/PLAN.md Phase 10) into the quest domain after workstream 5's
encounter endpoints (`dnd_ai.api.encounters`) and workstream 6's item
endpoints (`dnd_ai.api.items`). Exposes `advance_objective`
(docs/PHASE7_VERIFICATION.md) over HTTP, on the same already-delivered OIDC
authentication (`dnd_ai.api.auth`), transaction management
(`dnd_ai.api.deps`), and access resolution (`dnd_ai.api.access`,
`dnd_ai.domain.access`) `dnd_ai.api.encounters`/`.items` use.

The route runs on the request's own `get_connection` transaction and calls
the connection-taking `_advance_objective_impl` form of the command (never
the public engine-based wrapper, which would open a second, nested
transaction) — identical to every route in `dnd_ai.api.encounters`/`.items`.

Authorization: requires the `canon.edit` role capability in the target
campaign (`dnd_ai.api.access.require_campaign_capability`), the same
capability `dnd_ai.api.encounters`/`.items` use — quest-objective
advancement is treated as GM/adapter-level canon mutation for this first
cut, the same deliberate scoping those modules' own docstrings record.

Cross-campaign session integrity: the route passes the URL's own (already-
authorized) `campaign_id` and the request body's caller-supplied
`session_id` straight through to `_advance_objective_impl`, which validates
the two agree (`dnd_ai.commands._shared.validate_session_campaign`) before
mutating anything, raising `SessionNotInCampaignError` — a `SafeMessageError`
the existing generic handler maps to a fixed, non-disclosing 404 — for a
nonexistent or foreign-campaign session. See that function's docstring for
why this can't be caught by `require_campaign_capability` alone.

Like `dnd_ai.api.items`, there is no encounter-style "does this resource
belong to my campaign" ownership check here: neither
`narrative.quest_objectives` nor `campaign.objective_state` carries a
`campaign_id` at all — they are scoped by `timeline_id`, taken from the
resolved `AccessContext` (the campaign's own pinned timeline), never from
the request body.

Idempotency: durable, PostgreSQL-backed, via `dnd_ai.api.idempotency` and
`security.idempotent_requests` (migration 082) — identical mechanism to
`dnd_ai.api.items`, see that module's docstring for the full concurrency
argument.

Auditing: every successful call inserts one `audit.change_log` row
(`dnd_ai.api.audit.record_change_log`) identifying the authenticated
`actor_user_id`, the request's correlation ID, the command name, the
affected record/entity/world, and the resulting `event_id` — on the same
connection, so it commits atomically with the command it describes.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import Connection

from dnd_ai.commands.quests import _advance_objective_impl
from dnd_ai.domain.access import AccessContext

from .access import require_campaign_capability
from .audit import record_change_log
from .correlation import get_request_correlation_id
from .deps import get_connection, get_idempotency_key
from .idempotency import IdempotentReplay, begin_idempotent_request, complete_idempotent_request

router = APIRouter(tags=["quests"])

# Quest objective advancement is a canon-affecting mutation (docs/
# architecture/DATABASE_MODEL.md §12.3) — see this module's docstring for
# why this route requires it rather than a narrower, character-scoped
# capability.
_QUEST_MANAGE_CAPABILITY = "canon.edit"

# audit.change_log.command_name / the idempotency store's fingerprinted
# command_name — one literal per route, never derived from request data.
_ADVANCE_OBJECTIVE_COMMAND_NAME = "advance_objective"

# audit.change_actions.code (revision 007 seed): each call updates an
# existing conceptual resource's objective state, whether or not a
# campaign.objective_state row already existed — "updated" fits a first
# transition too, the same way dnd_ai.api.items treats "insert vs. update
# the state row" as an implementation detail of one logical operation.
_UPDATED_CHANGE_ACTION = "updated"


# ---------------------------------------------------------------------------
# Request/response contracts
# ---------------------------------------------------------------------------


class AdvanceObjectiveRequest(BaseModel):
    world_time_id: uuid.UUID
    new_status_code: str
    party_id: uuid.UUID | None = None
    actor_entity_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None
    cause_interaction_id: uuid.UUID | None = None
    cause_event_id: uuid.UUID | None = None
    event_details: str | None = None


class AdvanceObjectiveResponse(BaseModel):
    objective_state_id: uuid.UUID
    event_id: uuid.UUID
    previous_status_code: str | None
    new_status_code: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post(
    "/campaigns/{campaign_id}/quests/objectives/{quest_objective_id}/advance",
    response_model=AdvanceObjectiveResponse,
    status_code=200,
)
def advance_objective_endpoint(
    campaign_id: uuid.UUID,
    quest_objective_id: uuid.UUID,
    body: AdvanceObjectiveRequest,
    access: Annotated[
        AccessContext, Depends(require_campaign_capability(_QUEST_MANAGE_CAPABILITY))
    ],
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> AdvanceObjectiveResponse:
    reservation_id: uuid.UUID | None = None
    if idempotency_key is not None:
        fingerprint_payload: dict[str, Any] = {
            "quest_objective_id": str(quest_objective_id),
            **body.model_dump(mode="json"),
        }
        outcome = begin_idempotent_request(
            connection,
            actor_user_id=access.user_id,
            campaign_id=campaign_id,
            idempotency_key=idempotency_key,
            command_name=_ADVANCE_OBJECTIVE_COMMAND_NAME,
            payload=fingerprint_payload,
            correlation_id=correlation_id,
        )
        if isinstance(outcome, IdempotentReplay):
            return AdvanceObjectiveResponse.model_validate(outcome.response_body)
        reservation_id = outcome.idempotent_request_id

    result = _advance_objective_impl(
        connection,
        quest_objective_id=quest_objective_id,
        timeline_id=access.timeline_id,
        world_time_id=body.world_time_id,
        new_status_code=body.new_status_code,
        party_id=body.party_id,
        actor_entity_id=body.actor_entity_id,
        campaign_id=campaign_id,
        session_id=body.session_id,
        cause_interaction_id=body.cause_interaction_id,
        cause_event_id=body.cause_event_id,
        event_details=body.event_details,
    )

    record_change_log(
        connection,
        change_action_code=_UPDATED_CHANGE_ACTION,
        schema_name="campaign",
        table_name="objective_state",
        record_id=result.objective_state_id,
        entity_id=quest_objective_id,
        world_id=result.world_id,
        actor_user_id=access.user_id,
        correlation_id=correlation_id,
        command_name=_ADVANCE_OBJECTIVE_COMMAND_NAME,
        event_id=result.event_id,
    )

    response = AdvanceObjectiveResponse(
        objective_state_id=result.objective_state_id,
        event_id=result.event_id,
        previous_status_code=result.previous_status_code,
        new_status_code=result.new_status_code,
    )

    if reservation_id is not None:
        complete_idempotent_request(
            connection,
            idempotent_request_id=reservation_id,
            response_status_code=200,
            response_body=response.model_dump(mode="json"),
        )

    return response
