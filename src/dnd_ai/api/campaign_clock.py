"""Campaign clock endpoints (Phase 15 checkpoint 15.2W-2).

    GET  /campaigns/{campaign_id}/clock            (campaign.view)
    GET  /campaigns/{campaign_id}/clock/cause-choices (canon.edit)
    POST /campaigns/{campaign_id}/clock/advance    (canon.edit)
    POST /campaigns/{campaign_id}/clock/correct    (canon.edit)

The clock is typed timeline state of the campaign's own pinned timeline (never a
request value). Reads are campaign-visible: the current world time is the same
information the session recap already shows. Writes re-check authority under lock
in the command, use the campaign idempotency store, answer with an id-only
receipt, and write one audit row citing the causal event. Human principals only.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import Field, field_validator
from sqlalchemy import Connection

from dnd_ai.commands.campaign_clock import (
    ClockResult,
    advance_campaign_clock,
    correct_campaign_clock,
)
from dnd_ai.domain.access import AccessContext
from dnd_ai.domain.campaign_clock import CLOCK_EXPLANATION_MAX_LENGTH
from dnd_ai.queries.campaign_clock import list_clock_cause_choices, resolve_effective_clock

from ._authoring import (
    BaseAuthoringRequest,
    finish_campaign_idempotency,
    start_campaign_idempotency,
)
from ._shared import timeline_world_id
from .access import require_campaign_capability
from .audit import record_change_log
from .correlation import get_request_correlation_id
from .deps import get_connection, get_idempotency_key
from .world_explorer import resolve_world_entity_visibility

router = APIRouter(tags=["campaign-clock"])

_Conn = Annotated[Connection, Depends(get_connection)]
_Key = Annotated[str | None, Depends(get_idempotency_key)]
_Corr = Annotated[str | None, Depends(get_request_correlation_id)]
_View = Annotated[AccessContext, Depends(require_campaign_capability("campaign.view"))]
_Edit = Annotated[AccessContext, Depends(require_campaign_capability("canon.edit"))]


class _ClockTarget(BaseAuthoringRequest):
    world_time_id: uuid.UUID
    # 0 when the timeline has no clock row of its own yet.
    expected_row_version: int = Field(ge=0)


class AdvanceClockRequest(_ClockTarget):
    # An existing gameplay event the GM names as the cause (validated in the command).
    cause_event_id: uuid.UUID | None = None
    # Written for the members who may view the advance event (not the GM-only details and not
    # the administrative reason); blank means none.
    explanation: str | None = Field(default=None, max_length=CLOCK_EXPLANATION_MAX_LENGTH)

    @field_validator("explanation")
    @classmethod
    def _blank_is_none(cls, value: str | None) -> str | None:
        return value or None


class CorrectClockRequest(_ClockTarget):
    # The event that last set the clock (the advance or correction being corrected).
    corrects_event_id: uuid.UUID


@router.get("/campaigns/{campaign_id}/clock")
def get_clock_endpoint(access: _View, connection: _Conn) -> dict[str, Any]:
    clock = resolve_effective_clock(connection, timeline_id=access.timeline_id)
    if clock is None:
        return {
            "current": None,
            "row_version": 0,
            "inherited": False,
            "last_event_id": None,
        }
    return {
        "current": {"world_time_id": str(clock.world_time_id), "display": clock.display},
        "row_version": clock.row_version,
        "inherited": not clock.own_row,
        "last_event_id": None if clock.last_event_id is None else str(clock.last_event_id),
    }


@router.get("/campaigns/{campaign_id}/clock/cause-choices")
def clock_cause_choices_endpoint(
    access: _Edit,
    connection: _Conn,
    world_time_id: uuid.UUID | None = None,
    q: Annotated[str | None, Field(max_length=100)] = None,
) -> dict[str, Any]:
    choices = list_clock_cause_choices(
        connection,
        timeline_id=access.timeline_id,
        world_id=timeline_world_id(connection, access.timeline_id),
        campaign_id=access.campaign_id,
        denied_event_ids=resolve_world_entity_visibility(
            access, connection
        ).campaign_view_denied_entity_ids,
        not_after_world_time_id=world_time_id,
        search=(q or "").strip() or None,
    )
    return {
        "choices": [
            {"event_id": str(c.event_id), "name": c.name, "in_world_time": c.in_world_time}
            for c in choices
        ]
    }


def _run(
    *,
    command_name: str,
    access: AccessContext,
    connection: Connection,
    idempotency_key: str | None,
    correlation_id: str | None,
    payload: dict[str, Any],
    command: Any,
) -> Any:
    idem = start_campaign_idempotency(
        connection,
        actor_user_id=access.user_id,
        campaign_id=access.campaign_id,
        idempotency_key=idempotency_key,
        command_name=command_name,
        payload=payload,
        correlation_id=correlation_id,
    )
    if idem.replay is not None:
        return idem.replay
    result: ClockResult = command()
    record_change_log(
        connection,
        change_action_code="created" if result.created else "updated",
        schema_name="campaign",
        table_name="timeline_clocks",
        record_id=result.timeline_id,
        entity_id=None,
        world_id=result.world_id,
        actor_user_id=access.user_id,
        correlation_id=correlation_id,
        command_name=command_name,
        event_id=result.event_id,
        changed_fields=result.changed_fields,
    )
    receipt = {
        "world_time_id": str(result.world_time_id),
        "event_id": str(result.event_id),
        "row_version": result.row_version,
        "created": result.created,
        "changed": True,
    }
    finish_campaign_idempotency(connection, idem, status_code=200, body=receipt)
    return JSONResponse(status_code=200, content=receipt)


@router.post("/campaigns/{campaign_id}/clock/advance")
def advance_clock_endpoint(
    body: AdvanceClockRequest,
    access: _Edit,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    return _run(
        command_name="advance_campaign_clock",
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        # Unset optional inputs stay out of the fingerprint so a retry of a request made before
        # these fields existed still matches; a changed or newly added value still conflicts.
        payload=body.model_dump(mode="json", exclude_none=True),
        command=lambda: advance_campaign_clock(
            connection,
            campaign_id=access.campaign_id,
            actor_user_id=access.user_id,
            world_time_id=body.world_time_id,
            expected_row_version=body.expected_row_version,
            cause_event_id=body.cause_event_id,
            explanation=body.explanation,
            # The editor's own event-read denies, resolved by the same visibility the event
            # pages use, so the picker and this check cannot disagree.
            denied_event_ids=resolve_world_entity_visibility(
                access, connection
            ).campaign_view_denied_entity_ids,
        ),
    )


@router.post("/campaigns/{campaign_id}/clock/correct")
def correct_clock_endpoint(
    body: CorrectClockRequest,
    access: _Edit,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    return _run(
        command_name="correct_campaign_clock",
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload=body.model_dump(mode="json"),
        command=lambda: correct_campaign_clock(
            connection,
            campaign_id=access.campaign_id,
            actor_user_id=access.user_id,
            world_time_id=body.world_time_id,
            expected_row_version=body.expected_row_version,
            corrects_event_id=body.corrects_event_id,
        ),
    )
