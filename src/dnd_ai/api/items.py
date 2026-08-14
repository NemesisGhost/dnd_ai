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

Idempotency: neither command has a natural per-request idempotency key the
way `narrative.encounter_turns`' `UNIQUE(encounter_round_id,
participant_id)` gives `resolve_combat_turn`. A retried transfer/identify
request is not rejected as a conflict — it is applied again, updating the
same `campaign.inventory_entries`/`knowledge.item_identification` row to
the (already-current) requested state and recording a second `narrative.
events` row. This mirrors the underlying commands' own behavior (already
exercised by `tests/scenario/test_item_commands.py`'s "transferring an
already-placed item updates the same row" case) — no bespoke idempotency-
key store is introduced here, consistent with `dnd_ai.api.deps.
get_idempotency_key`'s "most commands already derive their own idempotency
from domain state" scoping note; a genuine duplicate-request problem is
future scope once a concrete caller demonstrates it.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import Connection

from dnd_ai.commands.items import _identify_item_impl, _transfer_item_possession_impl
from dnd_ai.domain.access import AccessContext

from .access import require_campaign_capability
from .deps import get_connection

router = APIRouter(tags=["items"])

# Item possession/identification are canon-affecting mutations (docs/
# architecture/DATABASE_MODEL.md §12.3) — see this module's docstring for
# why every route here requires it rather than a narrower, character-
# scoped capability.
_ITEM_MANAGE_CAPABILITY = "canon.edit"


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
) -> TransferItemPossessionResponse:
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
    return TransferItemPossessionResponse(
        inventory_entry_id=result.inventory_entry_id, event_id=result.event_id
    )


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
) -> IdentifyItemResponse:
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
    return IdentifyItemResponse(
        item_identification_id=result.item_identification_id,
        event_id=result.event_id,
        previous_level=result.previous_level,
        new_level=result.new_level,
    )
