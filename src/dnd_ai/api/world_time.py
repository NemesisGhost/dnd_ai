"""Calendar and world-time endpoints (Phase 15 checkpoint 15.2W-1).

    GET  /worlds/{world_id}/calendars                 (world.view)
    POST /worlds/{world_id}/calendars                 (world.manage)
    GET  /campaigns/{campaign_id}/calendars           (canon.edit)
    GET  /campaigns/{campaign_id}/world-times         (canon.edit, keyset-paged, latest first)
    POST /campaigns/{campaign_id}/world-times         (canon.edit)

Calendars are world definitions, so creating one needs per-world authority
(ADR 0014) and uses the actor-scoped idempotency store. World-time points are a
campaign operation: the world is derived from the campaign (never the request),
authority is `canon.edit` re-checked under lock by the command, and a point of
another world is never listed or referenced. Writes answer with an id-only
receipt; the audit row stores structural values only (the label is content and is
redacted). Human principals only; Foundry and machine principals never reach
these routes.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection

from dnd_ai.commands.world_time import create_calendar, create_world_time
from dnd_ai.domain.access import AccessContext
from dnd_ai.domain.authoring import DESCRIPTION_MAX_LENGTH, NAME_MAX_LENGTH
from dnd_ai.domain.world_authority import WORLD_MANAGE, WORLD_VIEW, WorldAuthority
from dnd_ai.domain.world_time import (
    DAY_COUNT_MAX,
    DAYS_PER_WEEK_MAX,
    EPOCH_LABEL_MAX_LENGTH,
    LABEL_MAX_LENGTH,
    MONTH_NAME_MAX_LENGTH,
    MONTHS_MAX,
    YEAR_MAX,
    YEAR_MIN,
)
from dnd_ai.queries.world_time import CalendarView, list_calendars, list_world_times

from ._authoring import (
    BaseAuthoringRequest,
    finish_actor_idempotency,
    finish_campaign_idempotency,
    start_actor_idempotency,
    start_campaign_idempotency,
)
from ._shared import timeline_world_id
from .access import require_campaign_capability
from .audit import record_change_log
from .correlation import get_request_correlation_id
from .deps import get_connection, get_idempotency_key
from .pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, build_page, decode_typed_cursor
from .world_access import require_world_capability

router = APIRouter(tags=["world-time"])

_Conn = Annotated[Connection, Depends(get_connection)]
_Key = Annotated[str | None, Depends(get_idempotency_key)]
_Corr = Annotated[str | None, Depends(get_request_correlation_id)]
_CampaignAccess = Annotated[AccessContext, Depends(require_campaign_capability("canon.edit"))]
_WorldView = Annotated[WorldAuthority, Depends(require_world_capability(WORLD_VIEW))]
_WorldManage = Annotated[WorldAuthority, Depends(require_world_capability(WORLD_MANAGE))]
_KEYSET = "world_times"


class MonthRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=MONTH_NAME_MAX_LENGTH)
    day_count: int = Field(ge=1, le=DAY_COUNT_MAX)


class CreateCalendarRequest(BaseAuthoringRequest):
    name: str = Field(min_length=1, max_length=NAME_MAX_LENGTH)
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX_LENGTH)
    days_per_week: int | None = Field(default=None, ge=1, le=DAYS_PER_WEEK_MAX)
    epoch_label: str | None = Field(default=None, max_length=EPOCH_LABEL_MAX_LENGTH)
    months: list[MonthRequest] = Field(min_length=1, max_length=MONTHS_MAX)


class CreateWorldTimeRequest(BaseAuthoringRequest):
    calendar_id: uuid.UUID | None = None
    year: int | None = Field(default=None, ge=YEAR_MIN, le=YEAR_MAX)
    month_number: int | None = Field(default=None, ge=1, le=MONTHS_MAX)
    day: int | None = Field(default=None, ge=1, le=DAY_COUNT_MAX)
    hour: int | None = Field(default=None, ge=0, le=23)
    minute: int | None = Field(default=None, ge=0, le=59)
    approximate: bool = False
    label: str | None = Field(default=None, max_length=LABEL_MAX_LENGTH)
    after_world_time_id: uuid.UUID | None = None
    before_world_time_id: uuid.UUID | None = None


def _calendar_json(view: CalendarView) -> dict[str, Any]:
    return {
        "calendar_id": str(view.calendar_id),
        "code": view.code,
        "name": view.name,
        "description": view.description,
        "days_per_week": view.days_per_week,
        "epoch_label": view.epoch_label,
        "months": [
            {"month_number": m.month_number, "name": m.name, "day_count": m.day_count}
            for m in view.months
        ],
    }


@router.get("/worlds/{world_id}/calendars")
def list_world_calendars_endpoint(authority: _WorldView, connection: _Conn) -> dict[str, Any]:
    return {
        "calendars": [
            _calendar_json(v) for v in list_calendars(connection, world_id=authority.world_id)
        ]
    }


@router.post("/worlds/{world_id}/calendars", status_code=201)
def create_calendar_endpoint(
    body: CreateCalendarRequest,
    authority: _WorldManage,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    command_name = "create_calendar"
    state = start_actor_idempotency(
        connection,
        actor_user_id=authority.user_id,
        idempotency_key=idempotency_key,
        command_name=command_name,
        payload={"world_id": str(authority.world_id), **body.model_dump(mode="json")},
        correlation_id=correlation_id,
    )
    if state.replay is not None:
        return state.replay
    result = create_calendar(
        connection,
        world_id=authority.world_id,
        actor_user_id=authority.user_id,
        name=body.name,
        description=body.description,
        days_per_week=body.days_per_week,
        epoch_label=body.epoch_label,
        months=[(m.name, m.day_count) for m in body.months],
    )
    record_change_log(
        connection,
        change_action_code="created",
        schema_name="core",
        table_name="calendars",
        record_id=result.calendar_id,
        entity_id=None,
        world_id=result.world_id,
        actor_user_id=authority.user_id,
        correlation_id=correlation_id,
        command_name=command_name,
        event_id=None,
        changed_fields=result.changed_fields,
    )
    receipt = {"calendar_id": str(result.calendar_id), "created": True, "changed": True}
    finish_actor_idempotency(connection, state, status_code=201, body=receipt)
    return JSONResponse(status_code=201, content=receipt)


@router.get("/campaigns/{campaign_id}/calendars")
def list_campaign_calendars_endpoint(access: _CampaignAccess, connection: _Conn) -> dict[str, Any]:
    world_id = timeline_world_id(connection, access.timeline_id)
    return {"calendars": [_calendar_json(v) for v in list_calendars(connection, world_id=world_id)]}


@router.get("/campaigns/{campaign_id}/world-times")
def list_world_times_endpoint(
    access: _CampaignAccess,
    connection: _Conn,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    cursor: str | None = None,
) -> dict[str, Any]:
    decoded = decode_typed_cursor(cursor, keyset=_KEYSET, fields=["int_or_none", "uuid"])
    after: tuple[int, uuid.UUID] | None = None
    if decoded is not None:
        key, time_id = decoded
        assert isinstance(key, int) and isinstance(time_id, uuid.UUID)
        after = (key, time_id)
    world_id = timeline_world_id(connection, access.timeline_id)
    rows = list_world_times(connection, world_id=world_id, limit=limit, after=after)
    page = build_page(
        rows, limit=limit, keyset=_KEYSET, cursor_key=lambda r: (r.sort_key, r.world_time_id)
    )
    return {
        "items": [
            {
                "world_time_id": str(r.world_time_id),
                "calendar_id": None if r.calendar_id is None else str(r.calendar_id),
                "year": r.year,
                "month_number": r.month_number,
                "day": r.day,
                "hour": r.hour,
                "minute": r.minute,
                "label": r.label,
                "precision": r.precision,
                "sort_key": r.sort_key,
                "display": r.display,
            }
            for r in page.items
        ],
        "next_cursor": page.next_cursor,
    }


@router.post("/campaigns/{campaign_id}/world-times", status_code=201)
def create_world_time_endpoint(
    body: CreateWorldTimeRequest,
    access: _CampaignAccess,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    command_name = "create_world_time"
    idem = start_campaign_idempotency(
        connection,
        actor_user_id=access.user_id,
        campaign_id=access.campaign_id,
        idempotency_key=idempotency_key,
        command_name=command_name,
        payload=body.model_dump(mode="json"),
        correlation_id=correlation_id,
    )
    if idem.replay is not None:
        return idem.replay
    result = create_world_time(
        connection,
        campaign_id=access.campaign_id,
        actor_user_id=access.user_id,
        calendar_id=body.calendar_id,
        year=body.year,
        month_number=body.month_number,
        day=body.day,
        hour=body.hour,
        minute=body.minute,
        approximate=body.approximate,
        label=body.label,
        after_world_time_id=body.after_world_time_id,
        before_world_time_id=body.before_world_time_id,
    )
    record_change_log(
        connection,
        change_action_code="created",
        schema_name="core",
        table_name="world_times",
        record_id=result.world_time_id,
        entity_id=None,
        world_id=result.world_id,
        actor_user_id=access.user_id,
        correlation_id=correlation_id,
        command_name=command_name,
        event_id=None,
        changed_fields=result.changed_fields,
    )
    receipt = {"world_time_id": str(result.world_time_id), "created": True, "changed": True}
    finish_campaign_idempotency(connection, idem, status_code=201, body=receipt)
    return JSONResponse(status_code=201, content=receipt)
