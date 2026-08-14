"""Command endpoints over `dnd_ai.commands.items` — Phase 10 workstream 6,
continuing "command endpoints over the existing command/application
services" (docs/PLAN.md Phase 10) into the item domain after workstream 5's
encounter endpoints (`dnd_ai.api.encounters`). Exposes `transfer_item_
possession` and `identify_item` (docs/PHASE9_VERIFICATION.md) over HTTP, on
the same already-delivered OIDC authentication (`dnd_ai.api.auth`),
transaction management (`dnd_ai.api.deps`), and access resolution
(`dnd_ai.api.access`, `dnd_ai.domain.access`) `dnd_ai.api.encounters` uses.

Both routes run on the request's own `get_connection` transaction and call
the connection-taking `_..._impl` form of their command (never the public
engine-based wrapper, which would open a second, nested transaction) —
identical to every route in `dnd_ai.api.encounters`.

Authorization: both routes require the `canon.edit` role capability in the
target campaign (`dnd_ai.api.access.require_campaign_capability`), the same
capability `dnd_ai.api.encounters` uses for encounter management. Item
possession/identification are treated as GM/adapter-level canon mutations
for this first cut — narrower than the full character-relationship-derived
access a player transferring their own character's held item could in
principle use, extending that is future scope once a caller actually needs
it, not invented speculatively here (the same deliberate scoping
`dnd_ai.api.encounters`' own module docstring records for combat turns).

Cross-campaign session integrity: both routes pass the URL's own (already-
authorized) `campaign_id` and the request body's caller-supplied
`session_id` straight through to their respective `_..._impl` function,
which validates the two agree
(`dnd_ai.commands._shared.validate_session_campaign`) before mutating
anything, raising `SessionNotInCampaignError` — a `SafeMessageError` the
existing generic handler maps to a fixed, non-disclosing 404 — for a
nonexistent or foreign-campaign session. See that function's docstring for
why this can't be caught by `require_campaign_capability` alone:
`campaign_id` is trusted (from the URL, already authorized), but
`session_id` is ordinary caller-supplied request data with no authorization
check of its own.

Unlike `dnd_ai.api.encounters`, there is no encounter-style "does this
resource belong to my campaign" ownership check here: neither
`world.item_instances` nor `campaign.inventory_entries`/`knowledge.
item_identification` carries a `campaign_id` at all — they are scoped by
`timeline_id`, which these routes always take from the resolved
`AccessContext` (the campaign's own pinned timeline), never from the
request body. An item instance from a different world/timeline than the
campaign's is rejected atomically by `campaign.
enforce_inventory_entry_world()` (revision 077) as an `IntegrityError`,
mapped by the existing generic handler to a fixed, non-disclosing 400 —
the same reliance on a database constraint (rather than a duplicate
application-layer lookup) `dnd_ai.commands.items`' own module docstring
describes.

Idempotency: durable, PostgreSQL-backed, via `dnd_ai.api.idempotency` and
`security.idempotent_requests` (migration 082). When a client supplies an
`Idempotency-Key` header, each route reserves `(actor_user_id, campaign_id,
idempotency_key)` before running its command and completes that reservation
with the command's actual response before returning — both inside the
request's own transaction, so a retried request either replays the
original response with no new event/effect/audit row, or (a different
payload or command reusing the same key) gets a fixed, non-disclosing 409
without touching anything. See `dnd_ai.api.idempotency`'s module docstring
for the full concurrency argument. A request with no `Idempotency-Key`
header is not deduplicated at all, matching every other command endpoint in
this codebase today.

Auditing: every successful call inserts one `audit.change_log` row
(`dnd_ai.api.audit.record_change_log`) identifying the authenticated
`actor_user_id` (never `actor_entity_id` — see that module's docstring for
why the two must not be conflated), the request's correlation ID, the
command name, the affected record/entity/world, and the resulting
`event_id` — on the same connection, so it commits atomically with the
command it describes.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import Connection

from dnd_ai.commands.items import _identify_item_impl, _transfer_item_possession_impl
from dnd_ai.domain.access import AccessContext

from .access import require_campaign_capability
from .audit import record_change_log
from .correlation import get_request_correlation_id
from .deps import get_connection, get_idempotency_key
from .idempotency import IdempotentReplay, begin_idempotent_request, complete_idempotent_request

router = APIRouter(tags=["items"])

# Item possession/identification are canon-affecting mutations (docs/
# architecture/DATABASE_MODEL.md §12.3) — see this module's docstring for
# why every route here requires it rather than a narrower, character-
# scoped capability.
_ITEM_MANAGE_CAPABILITY = "canon.edit"

# audit.change_log.command_name / the idempotency store's fingerprinted
# command_name — one literal per route, never derived from request data.
_TRANSFER_COMMAND_NAME = "transfer_item_possession"
_IDENTIFY_COMMAND_NAME = "identify_item"

# audit.change_actions.code (revision 007 seed) both routes record: each
# call updates an existing conceptual resource's possession/identification
# state, whether or not a campaign.inventory_entries/knowledge.
# item_identification row already existed — "updated" fits a first
# placement/identification too, the same way dnd_ai.commands.items' own
# module docstring treats "insert vs. update the state row" as an
# implementation detail of one logical operation, not two.
_UPDATED_CHANGE_ACTION = "updated"


# ---------------------------------------------------------------------------
# Request/response contracts
# ---------------------------------------------------------------------------


class TransferItemPossessionRequest(BaseModel):
    world_time_id: uuid.UUID
    holder_entity_id: uuid.UUID | None = None
    container_id: uuid.UUID | None = None
    location_id: uuid.UUID | None = None
    actor_entity_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None
    event_details: str | None = None


class TransferItemPossessionResponse(BaseModel):
    inventory_entry_id: uuid.UUID
    event_id: uuid.UUID


class IdentifyItemRequest(BaseModel):
    world_time_id: uuid.UUID
    knower_entity_id: uuid.UUID
    new_level: str
    known_properties: dict[str, object] | None = None
    actor_entity_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None
    event_details: str | None = None


class IdentifyItemResponse(BaseModel):
    item_identification_id: uuid.UUID
    event_id: uuid.UUID
    previous_level: str | None
    new_level: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post(
    "/campaigns/{campaign_id}/items/{item_instance_id}/transfer",
    response_model=TransferItemPossessionResponse,
    status_code=200,
)
def transfer_item_possession_endpoint(
    campaign_id: uuid.UUID,
    item_instance_id: uuid.UUID,
    body: TransferItemPossessionRequest,
    access: Annotated[AccessContext, Depends(require_campaign_capability(_ITEM_MANAGE_CAPABILITY))],
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> TransferItemPossessionResponse:
    reservation_id: uuid.UUID | None = None
    if idempotency_key is not None:
        fingerprint_payload: dict[str, Any] = {
            "item_instance_id": str(item_instance_id),
            **body.model_dump(mode="json"),
        }
        outcome = begin_idempotent_request(
            connection,
            actor_user_id=access.user_id,
            campaign_id=campaign_id,
            idempotency_key=idempotency_key,
            command_name=_TRANSFER_COMMAND_NAME,
            payload=fingerprint_payload,
            correlation_id=correlation_id,
        )
        if isinstance(outcome, IdempotentReplay):
            return TransferItemPossessionResponse.model_validate(outcome.response_body)
        reservation_id = outcome.idempotent_request_id

    result = _transfer_item_possession_impl(
        connection,
        item_instance_id=item_instance_id,
        timeline_id=access.timeline_id,
        world_time_id=body.world_time_id,
        holder_entity_id=body.holder_entity_id,
        container_id=body.container_id,
        location_id=body.location_id,
        actor_entity_id=body.actor_entity_id,
        campaign_id=campaign_id,
        session_id=body.session_id,
        event_details=body.event_details,
    )

    record_change_log(
        connection,
        change_action_code=_UPDATED_CHANGE_ACTION,
        schema_name="campaign",
        table_name="inventory_entries",
        record_id=result.inventory_entry_id,
        entity_id=item_instance_id,
        world_id=result.world_id,
        actor_user_id=access.user_id,
        correlation_id=correlation_id,
        command_name=_TRANSFER_COMMAND_NAME,
        event_id=result.event_id,
    )

    response = TransferItemPossessionResponse(
        inventory_entry_id=result.inventory_entry_id, event_id=result.event_id
    )

    if reservation_id is not None:
        complete_idempotent_request(
            connection,
            idempotent_request_id=reservation_id,
            response_status_code=200,
            response_body=response.model_dump(mode="json"),
        )

    return response


@router.post(
    "/campaigns/{campaign_id}/items/{item_instance_id}/identify",
    response_model=IdentifyItemResponse,
    status_code=200,
)
def identify_item_endpoint(
    campaign_id: uuid.UUID,
    item_instance_id: uuid.UUID,
    body: IdentifyItemRequest,
    access: Annotated[AccessContext, Depends(require_campaign_capability(_ITEM_MANAGE_CAPABILITY))],
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> IdentifyItemResponse:
    reservation_id: uuid.UUID | None = None
    if idempotency_key is not None:
        fingerprint_payload: dict[str, Any] = {
            "item_instance_id": str(item_instance_id),
            **body.model_dump(mode="json"),
        }
        outcome = begin_idempotent_request(
            connection,
            actor_user_id=access.user_id,
            campaign_id=campaign_id,
            idempotency_key=idempotency_key,
            command_name=_IDENTIFY_COMMAND_NAME,
            payload=fingerprint_payload,
            correlation_id=correlation_id,
        )
        if isinstance(outcome, IdempotentReplay):
            return IdentifyItemResponse.model_validate(outcome.response_body)
        reservation_id = outcome.idempotent_request_id

    result = _identify_item_impl(
        connection,
        item_instance_id=item_instance_id,
        timeline_id=access.timeline_id,
        world_time_id=body.world_time_id,
        knower_entity_id=body.knower_entity_id,
        new_level=body.new_level,
        known_properties=body.known_properties,
        actor_entity_id=body.actor_entity_id,
        campaign_id=campaign_id,
        session_id=body.session_id,
        event_details=body.event_details,
    )

    record_change_log(
        connection,
        change_action_code=_UPDATED_CHANGE_ACTION,
        schema_name="knowledge",
        table_name="item_identification",
        record_id=result.item_identification_id,
        entity_id=item_instance_id,
        world_id=result.world_id,
        actor_user_id=access.user_id,
        correlation_id=correlation_id,
        command_name=_IDENTIFY_COMMAND_NAME,
        event_id=result.event_id,
    )

    response = IdentifyItemResponse(
        item_identification_id=result.item_identification_id,
        event_id=result.event_id,
        previous_level=result.previous_level,
        new_level=result.new_level,
    )

    if reservation_id is not None:
        complete_idempotent_request(
            connection,
            idempotent_request_id=reservation_id,
            response_status_code=200,
            response_body=response.model_dump(mode="json"),
        )

    return response
