"""Character revelation endpoints (P03-A A3a): create, revoke and list.

    GET  /campaigns/{campaign_id}/characters/{character_id}/revelations
    POST /campaigns/{campaign_id}/characters/{character_id}/revelations
    POST /campaigns/{campaign_id}/characters/{character_id}/revelations/{character_revelation_id}/revoke

Create and revoke need `campaign.view` at the route, then `character.reveal` authority and no
whole-character deny, checked by a dependency *before* the body and the idempotency lookup, and
again under lock inside the command at a fresh database instant (plan section 10.4).

**Idempotency order (plan section 10.4, step 0 and step 8a).** A keyed request takes the
idempotency key lock (P2) as its first database statement, before any row lock. The reservation
and the replay lookup are not made here but inside the command, through `reserve()`, after the
command's locks and its under-lock authority and deny checks. A caller who lost authority is
therefore refused (403 or 404) instead of being handed a stored receipt, and the reservation cannot
wait on anything. The receipt is minimal (ids and flags). The audit row (one per real change) names
ids, the audience kind, the authority source and the audience size, never the reason text.

A3a changes no audience response: nothing outside this module reads the revelation tables.
"""

import uuid
from typing import Annotated, Any, Literal, Self

from fastapi import APIRouter, Depends, Response
from pydantic import Field, model_validator
from sqlalchemy import Connection

from dnd_ai.commands.character_public_profile import require_may_release
from dnd_ai.commands.character_revelations import (
    InvalidRevelationRequestError,
    create_character_revelation,
    revoke_character_revelation,
    validate_revelation_shape,
)
from dnd_ai.domain.access import AccessContext
from dnd_ai.domain.authorization import AuthorizationPlan
from dnd_ai.domain.public_profiles import REVELATION_REASON_MAX_LENGTH
from dnd_ai.queries.character_revelations import list_character_revelations

from ._authoring import (
    BaseAuthoringRequest,
    CampaignIdempotency,
    finish_campaign_idempotency,
    start_campaign_idempotency,
)
from ._shared import timeline_world_id
from .access import require_campaign_capability
from .audit import record_change_log
from .correlation import get_request_correlation_id
from .deps import get_connection, get_idempotency_key
from .errors import NotFoundError
from .idempotency import lock_idempotency_key
from .r01_route_plans import get_authorization_plan

router = APIRouter(tags=["character-revelations"])

_BASE = "/campaigns/{campaign_id}/characters/{character_id}/revelations"

_view_access = require_campaign_capability("campaign.view")

_Conn = Annotated[Connection, Depends(get_connection)]
_Plan = Annotated[AuthorizationPlan, Depends(get_authorization_plan)]
_Key = Annotated[str | None, Depends(get_idempotency_key)]
_Corr = Annotated[str | None, Depends(get_request_correlation_id)]

_CREATE_COMMAND = "create_character_revelation"
_REVOKE_COMMAND = "revoke_character_revelation"


class CreateCharacterRevelationRequest(BaseAuthoringRequest):
    audience_kind: Literal[
        "member", "access_group", "campaign_current", "campaign_current_and_future"
    ]
    target_campaign_membership_id: uuid.UUID | None = None
    target_access_group_id: uuid.UUID | None = None
    reason: str = Field(min_length=1, max_length=REVELATION_REASON_MAX_LENGTH)

    @model_validator(mode="after")
    def _shape(self) -> Self:
        try:
            validate_revelation_shape(
                audience_kind=self.audience_kind,
                target_campaign_membership_id=self.target_campaign_membership_id,
                target_access_group_id=self.target_access_group_id,
                reason=self.reason,
            )
        except InvalidRevelationRequestError as exc:
            raise ValueError(str(exc)) from exc
        return self


class RevokeCharacterRevelationRequest(BaseAuthoringRequest):
    reason: str = Field(min_length=1, max_length=REVELATION_REASON_MAX_LENGTH)


def _reveal_precheck(
    character_id: uuid.UUID,
    access: Annotated[AccessContext, Depends(_view_access)],
    connection: _Conn,
    plan: _Plan,
) -> None:
    """Before the body and the idempotency lookup: 403 `character_reveal_required` for a caller
    without reveal authority, 404 for a whole-character deny."""
    require_may_release(connection, access=access, character_id=character_id, plan=plan)


@router.get(_BASE)
def list_character_revelations_endpoint(
    character_id: uuid.UUID,
    access: Annotated[AccessContext, Depends(_view_access)],
    connection: _Conn,
) -> dict[str, Any]:
    body = list_character_revelations(connection, access=access, character_id=character_id)
    if body is None:
        raise NotFoundError()
    return body


@router.post(_BASE)
def create_character_revelation_endpoint(
    character_id: uuid.UUID,
    body: CreateCharacterRevelationRequest,
    response: Response,
    access: Annotated[AccessContext, Depends(_view_access)],
    _precheck: Annotated[None, Depends(_reveal_precheck)],
    plan: _Plan,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    # Step 0: the key lock, the first database statement of the request's own work.
    lock_idempotency_key(
        connection,
        actor_user_id=access.user_id,
        campaign_id=access.campaign_id,
        idempotency_key=idempotency_key,
    )
    started: list[CampaignIdempotency] = []

    def reserve() -> bool:
        state = start_campaign_idempotency(
            connection,
            actor_user_id=access.user_id,
            campaign_id=access.campaign_id,
            idempotency_key=idempotency_key,
            command_name=_CREATE_COMMAND,
            payload={"character_id": str(character_id), **body.model_dump(mode="json")},
            correlation_id=correlation_id,
            plan=plan,
        )
        started.append(state)
        return state.replay is not None

    result = create_character_revelation(
        connection,
        campaign_id=access.campaign_id,
        character_id=character_id,
        actor_membership_id=access.campaign_membership_id,
        audience_kind=body.audience_kind,
        target_campaign_membership_id=body.target_campaign_membership_id,
        target_access_group_id=body.target_access_group_id,
        reason=body.reason,
        reserve=reserve,
        plan=plan,
    )
    if result is None:
        return started[0].replay
    if result.created:
        record_change_log(
            connection,
            change_action_code="created",
            schema_name="security",
            table_name="character_revelations",
            record_id=result.character_revelation_id,
            entity_id=character_id,
            world_id=timeline_world_id(connection, access.timeline_id),
            actor_user_id=access.user_id,
            correlation_id=correlation_id,
            command_name=_CREATE_COMMAND,
            event_id=None,
            changed_fields={
                "audience_kind": result.audience_kind,
                "authority_source": result.authority_source_code,
                "audience_size": result.audience_size,
                "target_campaign_membership_id": _text(body.target_campaign_membership_id),
                "target_access_group_id": _text(body.target_access_group_id),
            },
        )
    payload: dict[str, Any] = {
        "character_revelation_id": str(result.character_revelation_id),
        "created": result.created,
    }
    response.status_code = 201 if result.created else 200
    finish_campaign_idempotency(
        connection, started[0], status_code=response.status_code, body=payload
    )
    plan.finalize(connection)  # R01: the last statement of the request
    return payload


@router.post(_BASE + "/{character_revelation_id}/revoke")
def revoke_character_revelation_endpoint(
    character_id: uuid.UUID,
    character_revelation_id: uuid.UUID,
    body: RevokeCharacterRevelationRequest,
    response: Response,
    access: Annotated[AccessContext, Depends(_view_access)],
    _precheck: Annotated[None, Depends(_reveal_precheck)],
    plan: _Plan,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    lock_idempotency_key(
        connection,
        actor_user_id=access.user_id,
        campaign_id=access.campaign_id,
        idempotency_key=idempotency_key,
    )
    started: list[CampaignIdempotency] = []

    def reserve() -> bool:
        state = start_campaign_idempotency(
            connection,
            actor_user_id=access.user_id,
            campaign_id=access.campaign_id,
            idempotency_key=idempotency_key,
            command_name=_REVOKE_COMMAND,
            payload={
                "character_id": str(character_id),
                "character_revelation_id": str(character_revelation_id),
                **body.model_dump(mode="json"),
            },
            correlation_id=correlation_id,
            plan=plan,
        )
        started.append(state)
        return state.replay is not None

    result = revoke_character_revelation(
        connection,
        campaign_id=access.campaign_id,
        character_id=character_id,
        character_revelation_id=character_revelation_id,
        actor_membership_id=access.campaign_membership_id,
        reason=body.reason,
        reserve=reserve,
        plan=plan,
    )
    if result is None:
        return started[0].replay
    if result.revoked:
        record_change_log(
            connection,
            change_action_code="updated",
            schema_name="security",
            table_name="character_revelations",
            record_id=character_revelation_id,
            entity_id=character_id,
            world_id=timeline_world_id(connection, access.timeline_id),
            actor_user_id=access.user_id,
            correlation_id=correlation_id,
            command_name=_REVOKE_COMMAND,
            event_id=None,
            previous_status="live",
            new_status="revoked",
            changed_fields={"end_reason": "revoked"},
        )
    payload: dict[str, Any] = {
        "character_revelation_id": str(character_revelation_id),
        "revoked": result.revoked,
    }
    response.status_code = 200
    finish_campaign_idempotency(connection, started[0], status_code=200, body=payload)
    plan.finalize(connection)  # R01: the last statement of the request
    return payload


def _text(value: uuid.UUID | None) -> str | None:
    return None if value is None else str(value)
