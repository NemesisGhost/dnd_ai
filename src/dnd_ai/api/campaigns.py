"""Command endpoint over `dnd_ai.commands.campaigns` — Phase 10's
campaign-creation bootstrap (docs/PLAN.md Phase 10 "Still to come" list).
Exposes `create_campaign` as `POST /campaigns`.

Authorization is deliberately different from every other command router in
this codebase: there is no campaign yet to resolve `dnd_ai.api.access.
require_campaign_capability` against, so this route depends only on
`dnd_ai.api.auth.get_authenticated_user_id` at the API layer — any
authenticated user may *call* this route. `dnd_ai.commands.campaigns.
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

No idempotency-key handling: see `dnd_ai.commands.campaigns`'s module
docstring for why `security.idempotent_requests`'s `NOT NULL campaign_id`
foreign key makes that structurally unavailable to the one command with no
existing campaign to key a reservation against.

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
from .auth import get_authenticated_user_id
from .correlation import get_request_correlation_id
from .deps import get_connection

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
    creator_user_id: Annotated[uuid.UUID, Depends(get_authenticated_user_id)],
    connection: Annotated[Connection, Depends(get_connection)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> CreateCampaignResponse:
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

    return CreateCampaignResponse(
        campaign_id=result.campaign_id, campaign_membership_id=result.campaign_membership_id
    )
