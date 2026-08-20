"""Campaign-creation endpoint over `dnd_ai.commands.campaigns`.

Exposes `create_campaign` as `POST /campaigns`.

Authorization is deliberately different from every other command router in
this codebase: there is no campaign yet to resolve `dnd_ai.api.access.
require_campaign_capability` against, so this route depends only on
`dnd_ai.api.auth.require_oidc_user_id` at the API layer — any
*human, OIDC-authenticated* user may *call* this route; a `FoundrySystem`
adapter credential is rejected outright (Phase 11 workstream 2 correction
— campaign creation has no `campaign_id` for `require_campaign_capability`'s
own `allow_foundry_system` gate to scope a Foundry principal's world
against, and is not part of the bounded adapter-facing surface in any
case, per `dnd_ai.domain.access.AuthenticatedPrincipal`'s docstring).
`dnd_ai.commands.campaigns.
create_campaign` itself is where the real authorization now lives:
`_authorize_timeline_reuse()` (that module's own docstring has the full
policy and the High/Critical defect history behind it, including a second
Critical defect found and closed immediately after the first) requires
the caller to already hold `access.manage` in an existing campaign before
a *second* campaign may attach to an already-used `timeline_id`, and a
live, positively-issued `security.timeline_bootstrap_grants` row naming
both the timeline and the caller before a genuinely unclaimed one may be
created on at all — nothing about a `timeline_id` being unclaimed is
itself authorization; a real deployment issues that grant through trusted
world-authoring/import infrastructure, never through this route. A
rejected attempt surfaces as `dnd_ai.commands.campaigns.
TimelineNotAuthorizedError`, a fixed non-disclosing 404 indistinguishable
from a nonexistent `timeline_id` or an expired/revoked/already-consumed
grant, handled by the existing generic `SafeMessageError` mapping — no
per-route error handling needed here. Once authorized, the caller becomes
the campaign's first `campaign_owner` (the system-template role migration
085 seeded with the full functional-owner capability set — `access.
manage`, `campaign.view`, `canon.edit` — after migration 080 seeded it
with `access.manage` alone) by construction. This mirrors the "no invented
capability" scoping every other Phase 10 workstream's first cut already
chose (e.g. `dnd_ai.api.memberships`'s own docstring), applied here to the
one action that structurally cannot be gated by `require_campaign_
capability` itself, since no campaign exists yet at the time the route is
entered.

Idempotency: durable, PostgreSQL-backed, like every other Phase 10 write —
but via `security.campaign_creation_reservations` (migration 088) rather
than the general `security.idempotent_requests` store every other command
endpoint uses, since `idempotent_requests`' `campaign_id` column is `NOT
NULL` and this is the one write in this codebase with no existing campaign
to key a reservation against yet. Migration 087's single-use bootstrap
grant stops a *different* user from claiming the first campaign, but does
nothing on its own to stop the successful creator's own dropped-response
retry from reusing the timeline it just claimed (via the `access.manage`
that retry's own creator now holds) and minting a second campaign,
membership, owner role, and audit row — the defect this idempotency
mechanism closes. When a client supplies an `Idempotency-Key` header, the
route reserves `(actor_user_id, idempotency_key)` via `dnd_ai.api.
idempotency.begin_campaign_creation_request()` before calling `create_
campaign`, and completes that reservation with the campaign it produced
before returning — both inside the request's own transaction, so a
retried request either replays the original `campaign_id`/`campaign_
membership_id` with no new campaign/membership/role/audit row, or (a
different payload reusing the same key) gets a fixed, non-disclosing 409
without touching anything. A request with no `Idempotency-Key` header is
not deduplicated at all, matching every other command endpoint in this
codebase.

Auditing: one `audit.change_log` row per successful call, identifying the
new campaign row (`schema_name="campaign"`, `table_name="campaigns"`).
`entity_id` is `None` — `campaign.campaigns` is not a `core.entities` row
(a campaign is a play-session construct, not a world entity subject to
class-table inheritance). `world_id` is the timeline's own world, already
resolved by the command and returned on its result — never re-derived,
unlike every other command router's `dnd_ai.api._shared.timeline_world_id`
call, since there is no `AccessContext.timeline_id` here to look it up
from in the first place.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import Connection

from dnd_ai.commands.campaigns import create_campaign

from .audit import record_change_log
from .auth import require_oidc_user_id
from .correlation import get_request_correlation_id
from .deps import get_connection, get_idempotency_key
from .idempotency import (
    IdempotentReplay,
    begin_campaign_creation_request,
    complete_campaign_creation_request,
)

router = APIRouter(tags=["campaigns"])

_CREATE_CAMPAIGN_COMMAND_NAME = "create_campaign"
_CREATED_CHANGE_ACTION = "created"


class CreateCampaignRequest(BaseModel):
    timeline_id: uuid.UUID
    ruleset_version_id: uuid.UUID
    name: str
    description: str | None = None


class CreateCampaignResponse(BaseModel):
    campaign_id: uuid.UUID
    campaign_membership_id: uuid.UUID


@router.post("/campaigns", response_model=CreateCampaignResponse, status_code=201)
def create_campaign_endpoint(
    body: CreateCampaignRequest,
    creator_user_id: Annotated[uuid.UUID, Depends(require_oidc_user_id)],
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> CreateCampaignResponse:
    reservation_id: uuid.UUID | None = None
    if idempotency_key is not None:
        outcome = begin_campaign_creation_request(
            connection,
            actor_user_id=creator_user_id,
            idempotency_key=idempotency_key,
            payload=body.model_dump(mode="json"),
            correlation_id=correlation_id,
        )
        if isinstance(outcome, IdempotentReplay):
            return CreateCampaignResponse.model_validate(outcome.response_body)
        reservation_id = outcome.campaign_creation_reservation_id

    result = create_campaign(
        connection,
        timeline_id=body.timeline_id,
        ruleset_version_id=body.ruleset_version_id,
        name=body.name,
        description=body.description,
        creator_user_id=creator_user_id,
    )

    record_change_log(
        connection,
        change_action_code=_CREATED_CHANGE_ACTION,
        schema_name="campaign",
        table_name="campaigns",
        record_id=result.campaign_id,
        entity_id=None,
        world_id=result.world_id,
        actor_user_id=creator_user_id,
        correlation_id=correlation_id,
        command_name=_CREATE_CAMPAIGN_COMMAND_NAME,
        event_id=None,
    )

    response = CreateCampaignResponse(
        campaign_id=result.campaign_id, campaign_membership_id=result.campaign_membership_id
    )

    if reservation_id is not None:
        complete_campaign_creation_request(
            connection,
            campaign_creation_reservation_id=reservation_id,
            response_status_code=201,
            response_body=response.model_dump(mode="json"),
            campaign_id=result.campaign_id,
        )

    return response
