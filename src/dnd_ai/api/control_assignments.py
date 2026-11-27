"""Control-assignment endpoints (P15-C11-S02-T01): assign, replace and revoke a character's control, and read it.

Authority is `character.assign_control`: a live built-in `campaign_owner` or `gm` assignment (ADR 0021 OD-4), judged by
the plan (`dnd_ai.commands.control_assignment_plans`) before any target lookup and again at `plan.finalize`. The route
requirement is only `campaign.view`; `access.manage`, `canon.edit`, custom roles, resource grants and control
assignments never confer the authority. A refusal is one fixed 403 `character_assign_control_required`.

The three writers are **keyed-optional pre-write plans** (`R01_KEYED_PRE_WRITE_ROUTES`): an `Idempotency-Key` replays
the original receipt, a changed body under the same key is refused, every lock and refusal precedes `plan.finalize`, and
every write and the receipt are declared steps after it. The body is taken as a plain mapping and validated after the
authority is judged (403 before 422).

The read is limited to the same holders (R-7: the built-in owner and `gm`, and a delegated assistant GM, T02) and takes no lock.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends
from pydantic import BaseModel
from sqlalchemy import Connection

from dnd_ai.commands._pre_write_steps import receipt_params
from dnd_ai.commands.control_assignment_plans import (
    RECEIPT,
    AssignControlRequiredError,
    prepare_assign,
    prepare_replace,
    prepare_revoke,
    write_assign,
    write_replace,
    write_revoke,
)
from dnd_ai.domain.access import AccessContext, read_authority_snapshot
from dnd_ai.domain.authorization import AuthorizationPlan
from dnd_ai.queries.control_assignments import CharacterControl, get_character_control
from dnd_ai.queries.party_membership_period import resolve_membership_clock

from .access import require_campaign_capability
from .campaigns import _begin_lifecycle_request
from .correlation import get_request_correlation_id
from .deps import get_connection, get_idempotency_key
from .r01_route_plans import get_authorization_plan

router = APIRouter(tags=["control-assignments"])
_Plan = Annotated[AuthorizationPlan, Depends(get_authorization_plan)]
_VIEW = "campaign.view"

_ASSIGN_COMMAND_NAME = "assign_character_control"
_REPLACE_COMMAND_NAME = "replace_primary_controller"
_REVOKE_COMMAND_NAME = "revoke_character_control"

_Body = Annotated[dict[str, Any], Body()]
_OptionalBody = Annotated[dict[str, Any] | None, Body()]


class AssignmentCreatedResponse(BaseModel):
    control_assignment_id: uuid.UUID


class PrimaryReplacedResponse(BaseModel):
    control_assignment_id: uuid.UUID
    revoked_control_assignment_id: uuid.UUID


class AssignmentRevokedResponse(BaseModel):
    control_assignment_id: uuid.UUID
    revoked: bool


class ControlHolderResponse(BaseModel):
    campaign_membership_id: uuid.UUID
    display_name: str
    kind: str


class ClockResponse(BaseModel):
    set: bool
    display: str | None


class ControlAssignmentResponse(BaseModel):
    control_assignment_id: uuid.UUID
    role: str
    kind: str
    campaign_membership_id: uuid.UUID
    display_name: str
    status: str
    granted_at: datetime
    granted_by: str | None
    ongoing_since: datetime | None
    effective_from: str | None
    effective_to: str | None
    revoked_at: datetime | None
    revoked_by: str | None
    revocation_reason: str | None
    reason: str | None


class CharacterControlResponse(BaseModel):
    controller: ControlHolderResponse | None
    co_controllers: list[ControlHolderResponse]
    gm_operated: bool
    clock: ClockResponse
    assignments: list[ControlAssignmentResponse]
    truncated: bool


def _complete_receipt(
    connection: Connection,
    plan: AuthorizationPlan,
    reservation_id: uuid.UUID | None,
    status: int,
    response: BaseModel,
) -> None:
    if reservation_id is not None:
        plan.execute(
            connection,
            RECEIPT,
            receipt_params(reservation_id, status, response.model_dump(mode="json")),
        )


@router.post(
    "/campaigns/{campaign_id}/characters/{character_id}/control-assignments",
    response_model=AssignmentCreatedResponse,
    status_code=201,
)
def assign_character_control_endpoint(
    campaign_id: uuid.UUID,
    character_id: uuid.UUID,
    body: _Body,
    access: Annotated[AccessContext, Depends(require_campaign_capability(_VIEW))],
    plan: _Plan,
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> Any:
    """Assigns a primary or co-controller to a character, for an `ongoing` or a `dated` period (OD-14: the kind is
    required). A keyed-optional pre-write route (`dnd_ai.commands.control_assignment_plans`)."""
    replay, reservation_id = _begin_lifecycle_request(
        plan=plan,
        connection=connection,
        access=access,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        command_name=_ASSIGN_COMMAND_NAME,
        payload={"character_id": str(character_id), **body},
    )
    if replay is not None:
        return replay
    prepared = prepare_assign(
        connection,
        plan,
        campaign_id=campaign_id,
        actor_user_id=access.user_id,
        actor_membership_id=access.campaign_membership_id,
        character_id=character_id,
        raw=body,
        reservation_id=reservation_id,
    )
    plan.finalize(connection)
    new_id = write_assign(
        connection,
        plan,
        prepared,
        actor_user_id=access.user_id,
        actor_membership_id=access.campaign_membership_id,
        correlation_id=correlation_id,
    )
    response = AssignmentCreatedResponse(control_assignment_id=new_id)
    _complete_receipt(connection, plan, reservation_id, 201, response)
    return response


@router.post(
    "/campaigns/{campaign_id}/characters/{character_id}/control-assignments/replace-primary",
    response_model=PrimaryReplacedResponse,
    status_code=201,
)
def replace_primary_controller_endpoint(
    campaign_id: uuid.UUID,
    character_id: uuid.UUID,
    body: _Body,
    access: Annotated[AccessContext, Depends(require_campaign_capability(_VIEW))],
    plan: _Plan,
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> Any:
    """Replaces the character's live primary controller: the old row is revoked (with the reason), the new primary
    inserted, co-controllers untouched. A keyed-optional pre-write route."""
    replay, reservation_id = _begin_lifecycle_request(
        plan=plan,
        connection=connection,
        access=access,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        command_name=_REPLACE_COMMAND_NAME,
        payload={"character_id": str(character_id), **body},
    )
    if replay is not None:
        return replay
    prepared = prepare_replace(
        connection,
        plan,
        campaign_id=campaign_id,
        actor_user_id=access.user_id,
        actor_membership_id=access.campaign_membership_id,
        character_id=character_id,
        raw=body,
        reservation_id=reservation_id,
    )
    plan.finalize(connection)
    new_id, old_id = write_replace(
        connection,
        plan,
        prepared,
        actor_user_id=access.user_id,
        actor_membership_id=access.campaign_membership_id,
        correlation_id=correlation_id,
    )
    response = PrimaryReplacedResponse(
        control_assignment_id=new_id, revoked_control_assignment_id=old_id
    )
    _complete_receipt(connection, plan, reservation_id, 201, response)
    return response


@router.post(
    "/campaigns/{campaign_id}/control-assignments/{control_assignment_id}/revoke",
    response_model=AssignmentRevokedResponse,
    status_code=200,
)
def revoke_character_control_endpoint(
    campaign_id: uuid.UUID,
    control_assignment_id: uuid.UUID,
    access: Annotated[AccessContext, Depends(require_campaign_capability(_VIEW))],
    plan: _Plan,
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
    body: _OptionalBody = None,
) -> Any:
    """Revokes one control assignment. Co-controllers are untouched and nobody is promoted. A row already revoked is the
    documented no-op: 200 `revoked: false`, no write and no audit row. A keyed-optional pre-write route."""
    replay, reservation_id = _begin_lifecycle_request(
        plan=plan,
        connection=connection,
        access=access,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        command_name=_REVOKE_COMMAND_NAME,
        payload={"control_assignment_id": str(control_assignment_id), **(body or {})},
    )
    if replay is not None:
        return replay
    prepared = prepare_revoke(
        connection,
        plan,
        campaign_id=campaign_id,
        actor_user_id=access.user_id,
        actor_membership_id=access.campaign_membership_id,
        assignment_id=control_assignment_id,
        raw=body,
        reservation_id=reservation_id,
    )
    plan.finalize(connection)
    revoked = write_revoke(
        connection,
        plan,
        prepared,
        assignment_id=control_assignment_id,
        actor_user_id=access.user_id,
        actor_membership_id=access.campaign_membership_id,
        correlation_id=correlation_id,
    )
    response = AssignmentRevokedResponse(
        control_assignment_id=control_assignment_id, revoked=revoked
    )
    _complete_receipt(connection, plan, reservation_id, 200, response)
    return response


def _response(state: CharacterControl) -> CharacterControlResponse:
    def holder(h: Any) -> ControlHolderResponse:
        return ControlHolderResponse(
            campaign_membership_id=h.campaign_membership_id,
            display_name=h.display_name,
            kind=h.kind,
        )

    return CharacterControlResponse(
        controller=holder(state.controller) if state.controller is not None else None,
        co_controllers=[holder(h) for h in state.co_controllers],
        gm_operated=state.gm_operated,
        clock=ClockResponse(set=state.clock_set, display=state.clock_display),
        assignments=[ControlAssignmentResponse(**vars(row)) for row in state.assignments],
        truncated=state.truncated,
    )


@router.get(
    "/campaigns/{campaign_id}/characters/{character_id}/control-assignments",
    response_model=CharacterControlResponse,
    status_code=200,
)
def get_character_control_endpoint(
    campaign_id: uuid.UUID,
    character_id: uuid.UUID,
    access: Annotated[AccessContext, Depends(require_campaign_capability(_VIEW))],
    connection: Annotated[Connection, Depends(get_connection)],
) -> CharacterControlResponse:
    """The character's current control, the effective clock and every assignment row, newest first (at most 200, with
    `truncated`). Limited to the holders of `character.assign_control`; the refusal precedes any character lookup, so it
    is one fixed 403 for an existing and a missing character. Writes nothing and takes no lock."""
    snapshot = read_authority_snapshot(
        connection,
        user_id=access.user_id,
        campaign_id=campaign_id,
        with_assign_control=True,
    )
    if snapshot.assign_control_authority not in ("campaign_owner", "gm", "delegation"):
        raise AssignControlRequiredError(
            f"membership {access.campaign_membership_id} holds no live owner or gm assignment "
            f"in campaign {campaign_id}"
        )
    state = get_character_control(
        connection,
        campaign_id=campaign_id,
        character_id=character_id,
        clock=resolve_membership_clock(connection, timeline_id=access.timeline_id),
    )
    return _response(state)
