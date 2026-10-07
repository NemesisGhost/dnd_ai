"""Campaign-creation endpoint over `dnd_ai.commands.campaigns`.

Exposes `create_campaign` as `POST /campaigns`.

Authorization is deliberately different from every other command router in
this codebase: there is no campaign yet to resolve `dnd_ai.api.access.
require_campaign_capability` against, so this route depends only on
`dnd_ai.api.auth.require_human_user_id` at the API layer — any *human,
OIDC- or local-session-authenticated* user may *call* this route; every
Foundry-adapter credential is rejected outright (campaign creation has no
`campaign_id` for `require_campaign_capability`'s own `allow_foundry_
access` gate to scope a paired-device principal's campaign against, and
is not part of the bounded adapter-facing surface in any case — the
legacy `FoundrySystem` credential this reasoning originally covered is
now rejected unconditionally before it can reach any route at all, per
`dnd_ai.api.auth`'s own docstring).
`dnd_ai.commands.campaigns.create_campaign` itself is where the real
authorization lives (docs/adr/0020-scoped-system-world-and-campaign-roles.md):
the creator must hold the system `campaign.host` capability (the system `gm`
role; 403 `system_gm_required` otherwise), and then either the world capability
`campaign.create` on the timeline's world (an Owner; plus `timeline.manage` when
the timeline already hosts a campaign) or a live, positively-issued
`security.timeline_bootstrap_grants` row naming both the timeline and the caller
for a genuinely unclaimed one. Holding `access.manage` in another campaign on
the timeline confers nothing. A rejected attempt surfaces as
`dnd_ai.commands.campaigns.TimelineNotAuthorizedError`, a fixed non-disclosing
404 indistinguishable from a nonexistent `timeline_id` or an expired/revoked/
already-consumed grant, handled by the existing generic `SafeMessageError`
mapping. Once authorized, the creator receives both the `campaign_owner` and the
`gm` template roles. World and timeline lifecycle are checked only after
authorization. The same module also hosts campaign settings, archive, and
reactivate (below the creation endpoint).

Idempotency: durable, PostgreSQL-backed, like every other Phase 10 write —
but via `security.campaign_creation_reservations` (migration 088) rather
than the general `security.idempotent_requests` store every other command
endpoint uses, since `idempotent_requests`' `campaign_id` column is `NOT
NULL` and this is the one write in this codebase with no existing campaign
to key a reservation against yet. Migration 087's single-use bootstrap
grant stops a *different* user from claiming the first campaign, but does
nothing on its own to stop the successful creator's own dropped-response
retry from reusing the timeline it just claimed (an Owner stays entitled) and
minting a second campaign,
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
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection

from dnd_ai.commands.campaigns import (
    CampaignMutationResult,
    archive_campaign,
    create_campaign,
    reactivate_campaign,
    update_campaign,
)
from dnd_ai.domain.access import AccessContext
from dnd_ai.queries.campaign_settings import get_campaign_settings, list_archived_campaigns

from .access import require_campaign_capability
from .audit import record_change_log
from .auth import require_human_user_id
from .correlation import get_request_correlation_id
from .deps import get_connection, get_idempotency_key
from .errors import InvalidCursorError, NotFoundError
from .idempotency import (
    IdempotentReplay,
    begin_campaign_creation_request,
    begin_idempotent_request,
    complete_campaign_creation_request,
    complete_idempotent_request,
)
from .pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, build_page, decode_typed_cursor

router = APIRouter(tags=["campaigns"])

_CREATE_CAMPAIGN_COMMAND_NAME = "create_campaign"
_CREATED_CHANGE_ACTION = "created"


class CreateCampaignRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    timeline_id: uuid.UUID
    ruleset_version_id: uuid.UUID
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)


class CreateCampaignResponse(BaseModel):
    campaign_id: uuid.UUID
    campaign_membership_id: uuid.UUID


@router.post("/campaigns", response_model=CreateCampaignResponse, status_code=201)
def create_campaign_endpoint(
    body: CreateCampaignRequest,
    creator_user_id: Annotated[uuid.UUID, Depends(require_human_user_id)],
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


# ---------------------------------------------------------------------------
# Phase 14: settings, archive, reactivate, archived list
# ---------------------------------------------------------------------------
#
#   GET  /campaigns/archived                    archived campaigns the caller manages
#   GET  /campaigns/{campaign_id}/settings      (access.manage; allowed on archived)
#   POST /campaigns/{campaign_id}/update        (access.manage)
#   POST /campaigns/{campaign_id}/archive       (access.manage)
#   POST /campaigns/{campaign_id}/reactivate    (access.manage; allowed on archived)
#
# Campaign-scoped idempotency (`security.idempotent_requests`). Foundry
# principals are rejected (no `allow_foundry_access`). Settings and reactivate
# are the *only* routes that opt into `allow_archived_campaign=True` — a
# route-registry test pins that exact set.


class UpdateCampaignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    expected_row_version: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)


class ArchiveCampaignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    expected_row_version: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=1000)


class ReactivateCampaignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_row_version: int = Field(ge=1)


_ARCHIVED_KEYSET = "archived_campaigns"


@router.get("/campaigns/archived")
def list_archived_campaigns_endpoint(
    user_id: Annotated[uuid.UUID, Depends(require_human_user_id)],
    connection: Annotated[Connection, Depends(get_connection)],
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    cursor: Annotated[str | None, Query(max_length=2048)] = None,
) -> dict[str, Any]:
    decoded = decode_typed_cursor(cursor, keyset=_ARCHIVED_KEYSET, fields=["str", "uuid"])
    after: tuple[str, uuid.UUID] | None = None
    if decoded is not None:
        after_name, after_id = decoded
        if not isinstance(after_name, str) or not isinstance(after_id, uuid.UUID):
            raise InvalidCursorError()
        after = (after_name, after_id)
    rows = list_archived_campaigns(connection, user_id=user_id, limit=limit, after=after)
    page = build_page(
        rows,
        limit=limit,
        keyset=_ARCHIVED_KEYSET,
        cursor_key=lambda r: (r.name, r.campaign_id),
    )
    return {
        "items": [
            {
                "campaign_id": str(r.campaign_id),
                "name": r.name,
                "world_name": r.world_name,
                "timeline_name": r.timeline_name,
                "row_version": r.row_version,
            }
            for r in page.items
        ],
        "next_cursor": page.next_cursor,
    }


@router.get("/campaigns/{campaign_id}/settings")
def get_campaign_settings_endpoint(
    access: Annotated[
        AccessContext,
        Depends(require_campaign_capability("access.manage", allow_archived_campaign=True)),
    ],
    connection: Annotated[Connection, Depends(get_connection)],
) -> dict[str, Any]:
    settings = get_campaign_settings(connection, campaign_id=access.campaign_id)
    if settings is None:
        raise NotFoundError()
    return {
        "campaign_id": str(settings.campaign_id),
        "name": settings.name,
        "description": settings.description,
        "lifecycle_status": settings.lifecycle_status,
        "row_version": settings.row_version,
        "world": {"world_id": str(settings.world_id), "name": settings.world_name},
        "timeline": {"timeline_id": str(settings.timeline_id), "name": settings.timeline_name},
        "ruleset_version": {
            "ruleset_version_id": str(settings.ruleset_version_id),
            "ruleset_display_name": settings.ruleset_display_name,
            "version_label": settings.ruleset_version_label,
        },
        "available_actions": settings.available_actions,
        "blocked_actions": [
            {"action": b.action, "reason": b.reason} for b in settings.blocked_actions
        ],
    }


def _record_campaign_change(
    connection: Connection,
    *,
    result: CampaignMutationResult,
    action: str,
    command_name: str,
    access: AccessContext,
    correlation_id: str | None,
    reason: str | None,
) -> None:
    record_change_log(
        connection,
        change_action_code=action,
        schema_name="campaign",
        table_name="campaigns",
        record_id=result.campaign_id,
        entity_id=None,
        world_id=result.world_id,
        actor_user_id=access.user_id,
        correlation_id=correlation_id,
        command_name=command_name,
        event_id=None,
        previous_status=result.previous_lifecycle_status,
        new_status=result.lifecycle_status if result.previous_lifecycle_status else None,
        changed_fields=result.changed_fields or None,
        reason=reason,
    )


def _campaign_command(
    *,
    command_name: str,
    action: str | None,
    access: AccessContext,
    connection: Connection,
    idempotency_key: str | None,
    correlation_id: str | None,
    payload: dict[str, Any],
    run: Callable[[], CampaignMutationResult],
    reason: str | None = None,
    include_status: bool = True,
) -> Any:
    reservation_id: uuid.UUID | None = None
    if idempotency_key is not None:
        outcome = begin_idempotent_request(
            connection,
            actor_user_id=access.user_id,
            campaign_id=access.campaign_id,
            idempotency_key=idempotency_key,
            command_name=command_name,
            payload=payload,
            correlation_id=correlation_id,
        )
        if isinstance(outcome, IdempotentReplay):
            return JSONResponse(
                status_code=outcome.response_status_code, content=outcome.response_body
            )
        reservation_id = outcome.idempotent_request_id

    result = run()
    if result.changed and action is not None:
        _record_campaign_change(
            connection,
            result=result,
            action=action,
            command_name=command_name,
            access=access,
            correlation_id=correlation_id,
            reason=reason,
        )
    response: dict[str, Any] = {
        "campaign_id": str(result.campaign_id),
        "row_version": result.row_version,
    }
    if include_status:
        response["lifecycle_status"] = result.lifecycle_status
    if reservation_id is not None:
        complete_idempotent_request(
            connection,
            idempotent_request_id=reservation_id,
            response_status_code=200,
            response_body=response,
        )
    return response


@router.post("/campaigns/{campaign_id}/update")
def update_campaign_endpoint(
    body: UpdateCampaignRequest,
    access: Annotated[AccessContext, Depends(require_campaign_capability("access.manage"))],
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> Any:
    return _campaign_command(
        command_name="update_campaign",
        action="updated",
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload={"campaign_id": str(access.campaign_id), **body.model_dump(mode="json")},
        include_status=False,
        run=lambda: update_campaign(
            connection,
            campaign_id=access.campaign_id,
            actor_user_id=access.user_id,
            expected_row_version=body.expected_row_version,
            name=body.name,
            description=body.description,
        ),
    )


@router.post("/campaigns/{campaign_id}/archive")
def archive_campaign_endpoint(
    body: ArchiveCampaignRequest,
    access: Annotated[AccessContext, Depends(require_campaign_capability("access.manage"))],
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> Any:
    return _campaign_command(
        command_name="archive_campaign",
        action="archived",
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload={"campaign_id": str(access.campaign_id), **body.model_dump(mode="json")},
        reason=body.reason.strip() if body.reason and body.reason.strip() else None,
        run=lambda: archive_campaign(
            connection,
            campaign_id=access.campaign_id,
            actor_user_id=access.user_id,
            expected_row_version=body.expected_row_version,
            reason=body.reason,
        ),
    )


@router.post("/campaigns/{campaign_id}/reactivate")
def reactivate_campaign_endpoint(
    body: ReactivateCampaignRequest,
    access: Annotated[
        AccessContext,
        Depends(require_campaign_capability("access.manage", allow_archived_campaign=True)),
    ],
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> Any:
    return _campaign_command(
        command_name="reactivate_campaign",
        action="restored",
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload={"campaign_id": str(access.campaign_id), **body.model_dump(mode="json")},
        run=lambda: reactivate_campaign(
            connection,
            campaign_id=access.campaign_id,
            actor_user_id=access.user_id,
            expected_row_version=body.expected_row_version,
        ),
    )
