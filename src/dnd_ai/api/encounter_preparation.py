"""Encounter preparation endpoints (Phase 15 checkpoint 15.3B-2a, decision D-23).

    POST /campaigns/{id}/encounters/prepare                  (a pending encounter in a session)
    POST /campaigns/{id}/encounters/{eid}/update             (place, summary)
    POST /campaigns/{id}/encounters/{eid}/participants       (add a character, side, initiative)
    POST /campaigns/{id}/encounters/{eid}/participants/{pid}/update
    POST /campaigns/{id}/encounters/{eid}/participants/{pid}/remove
    POST /campaigns/{id}/encounters/{eid}/start              (pending -> active, 15.3B-2b)
    POST /campaigns/{id}/encounters/{eid}/abort              (pending or active -> aborted)
    GET  /campaigns/{id}/authoring/encounters?session_id=
    GET  /campaigns/{id}/authoring/encounters/options
    GET  /campaigns/{id}/authoring/encounters/{eid}

All `canon.edit`. Only a pending encounter can be prepared; once it starts (15.3B-2b) every write
here is a 409. Writes use the campaign idempotency store and record one audit row. The existing
`POST /campaigns/{id}/encounters` (which starts an active encounter) is unchanged.
"""

import uuid
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import Field
from sqlalchemy import Connection

from dnd_ai.commands.encounter_operations import (
    EncounterOperationResult,
    abort_encounter,
    start_prepared_encounter,
)
from dnd_ai.commands.encounter_preparation import (
    PreparationResult,
    add_encounter_participant,
    create_encounter,
    remove_encounter_participant,
    update_encounter,
    update_encounter_participant,
)
from dnd_ai.domain.access import AccessContext
from dnd_ai.domain.encounter_operations import ACTION_KINDS, OUTCOMES
from dnd_ai.domain.encounter_preparation import (
    INITIATIVE_MAX,
    INITIATIVE_MIN,
    MAX_PARTICIPANTS,
    SIDES,
    SUMMARY_MAX_LENGTH,
)
from dnd_ai.queries.encounter_preparation import (
    EncounterPreparationView,
    get_encounter_preparation,
    list_session_encounters,
)

from ._authoring import (
    BaseAuthoringRequest,
    finish_campaign_idempotency,
    start_campaign_idempotency,
)
from .access import require_campaign_capability
from .audit import record_change_log
from .correlation import get_request_correlation_id
from .deps import get_connection, get_idempotency_key
from .errors import NotFoundError

router = APIRouter(tags=["encounter-preparation"])

_AUTHORING = "/campaigns/{campaign_id}/authoring/encounters"
_BASE = "/campaigns/{campaign_id}/encounters"
_Access = Annotated[AccessContext, Depends(require_campaign_capability("canon.edit"))]
_Conn = Annotated[Connection, Depends(get_connection)]
_Key = Annotated[str | None, Depends(get_idempotency_key)]
_Corr = Annotated[str | None, Depends(get_request_correlation_id)]


class PrepareRequest(BaseAuthoringRequest):
    session_id: uuid.UUID
    location_id: uuid.UUID | None = None
    summary: str | None = Field(default=None, max_length=SUMMARY_MAX_LENGTH)
    world_time_id: uuid.UUID | None = None


class UpdateEncounterRequest(BaseAuthoringRequest):
    location_id: uuid.UUID | None = None
    summary: str | None = Field(default=None, max_length=SUMMARY_MAX_LENGTH)


class AddParticipantRequest(BaseAuthoringRequest):
    participant_entity_id: uuid.UUID
    side: str = Field(default="party", max_length=20)
    initiative: int | None = Field(default=None, ge=INITIATIVE_MIN, le=INITIATIVE_MAX)


class UpdateParticipantRequest(BaseAuthoringRequest):
    side: str = Field(max_length=20)
    initiative: int | None = Field(default=None, ge=INITIATIVE_MIN, le=INITIATIVE_MAX)


def _view_json(view: EncounterPreparationView, *, changed: bool | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "encounter_id": str(view.encounter_id),
        "session_id": None if view.session_id is None else str(view.session_id),
        "status": view.status,
        "can_prepare": view.can_prepare,
        "summary": view.summary,
        "location_id": None if view.location_id is None else str(view.location_id),
        "location_name": view.location_name,
        "world_time_id": str(view.world_time_id),
        "current_round": view.current_round,
        "resulting_event_id": (
            None if view.resulting_event_id is None else str(view.resulting_event_id)
        ),
        "rounds": [
            {
                "round_number": r.round_number,
                "turns": [
                    {
                        "turn_order": t.turn_order,
                        "actor_name": t.actor_name,
                        "target_name": t.target_name,
                        "action_kind": t.action_kind,
                        "hit": t.hit,
                        "damage_amount": t.damage_amount,
                    }
                    for t in r.turns
                ],
            }
            for r in view.rounds
        ],
        "participants": [
            {
                "encounter_participant_id": str(p.encounter_participant_id),
                "participant_entity_id": str(p.participant_entity_id),
                "name": p.name,
                "entity_type_code": p.entity_type_code,
                "side": p.side,
                "initiative": p.initiative,
                "outcome": p.outcome,
                "current_hit_points": p.current_hit_points,
                "maximum_hit_points": p.maximum_hit_points,
            }
            for p in view.participants
        ],
    }
    if changed is not None:
        body["changed"] = changed
    return body


def _load(connection: Connection, access: AccessContext, encounter_id: uuid.UUID) -> Any:
    view = get_encounter_preparation(
        connection, campaign_id=access.campaign_id, encounter_id=encounter_id
    )
    if view is None:
        raise NotFoundError()
    return view


@router.get(
    _AUTHORING + "/options", dependencies=[Depends(require_campaign_capability("canon.edit"))]
)
def options_endpoint() -> dict[str, Any]:
    return {
        "sides": [{"value": code, "label": label} for code, label in SIDES],
        "action_kinds": [{"value": code, "label": label} for code, label in ACTION_KINDS],
        "outcomes": [{"value": code, "label": label} for code, label in OUTCOMES],
        "limits": {
            "summary_max_length": SUMMARY_MAX_LENGTH,
            "initiative_min": INITIATIVE_MIN,
            "initiative_max": INITIATIVE_MAX,
            "max_participants": MAX_PARTICIPANTS,
        },
    }


@router.get(_AUTHORING)
def list_endpoint(
    access: _Access, connection: _Conn, session_id: Annotated[uuid.UUID, Query()]
) -> dict[str, Any]:
    items = list_session_encounters(
        connection, campaign_id=access.campaign_id, session_id=session_id
    )
    return {
        "items": [
            {
                "encounter_id": str(i.encounter_id),
                "status": i.status,
                "summary": i.summary,
                "location_name": i.location_name,
                "participant_count": i.participant_count,
            }
            for i in items
        ]
    }


@router.get(_AUTHORING + "/{encounter_id}")
def get_endpoint(encounter_id: uuid.UUID, access: _Access, connection: _Conn) -> Any:
    return _view_json(_load(connection, access, encounter_id))


def _write(
    *,
    command_name: str,
    access: AccessContext,
    connection: Connection,
    idempotency_key: str | None,
    correlation_id: str | None,
    payload: dict[str, Any],
    created: bool,
    command: Callable[[], PreparationResult],
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
    result = command()
    if result.changed:
        record_change_log(
            connection,
            change_action_code=result.action,
            schema_name="narrative",
            table_name=result.table,
            record_id=result.record_id,
            entity_id=None,
            world_id=result.world_id,
            actor_user_id=access.user_id,
            correlation_id=correlation_id,
            command_name=command_name,
            event_id=None,
            changed_fields=result.changed_fields or None,
        )
    response = _view_json(_load(connection, access, result.encounter_id), changed=result.changed)
    status = 201 if created else 200
    finish_campaign_idempotency(connection, idem, status_code=status, body=response)
    return JSONResponse(status_code=status, content=response) if created else response


@router.post(_BASE + "/prepare", status_code=201)
def prepare_endpoint(
    body: PrepareRequest,
    access: _Access,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    return _write(
        command_name="create_encounter",
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload=body.model_dump(mode="json"),
        created=True,
        command=lambda: create_encounter(
            connection,
            campaign_id=access.campaign_id,
            actor_user_id=access.user_id,
            session_id=body.session_id,
            location_id=body.location_id,
            summary=body.summary,
            world_time_id=body.world_time_id,
        ),
    )


@router.post(_BASE + "/{encounter_id}/update")
def update_endpoint(
    encounter_id: uuid.UUID,
    body: UpdateEncounterRequest,
    access: _Access,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    return _write(
        command_name="update_encounter",
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload={"encounter_id": str(encounter_id), **body.model_dump(mode="json")},
        created=False,
        command=lambda: update_encounter(
            connection,
            campaign_id=access.campaign_id,
            actor_user_id=access.user_id,
            encounter_id=encounter_id,
            location_id=body.location_id,
            summary=body.summary,
        ),
    )


@router.post(_BASE + "/{encounter_id}/participants", status_code=201)
def add_participant_endpoint(
    encounter_id: uuid.UUID,
    body: AddParticipantRequest,
    access: _Access,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    return _write(
        command_name="add_encounter_participant",
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload={"encounter_id": str(encounter_id), **body.model_dump(mode="json")},
        created=True,
        command=lambda: add_encounter_participant(
            connection,
            campaign_id=access.campaign_id,
            actor_user_id=access.user_id,
            encounter_id=encounter_id,
            participant_entity_id=body.participant_entity_id,
            side=body.side,
            initiative=body.initiative,
        ),
    )


@router.post(_BASE + "/{encounter_id}/participants/{participant_id}/update")
def update_participant_endpoint(
    encounter_id: uuid.UUID,
    participant_id: uuid.UUID,
    body: UpdateParticipantRequest,
    access: _Access,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    return _write(
        command_name="update_encounter_participant",
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload={
            "encounter_id": str(encounter_id),
            "participant_id": str(participant_id),
            **body.model_dump(mode="json"),
        },
        created=False,
        command=lambda: update_encounter_participant(
            connection,
            campaign_id=access.campaign_id,
            actor_user_id=access.user_id,
            encounter_id=encounter_id,
            encounter_participant_id=participant_id,
            side=body.side,
            initiative=body.initiative,
        ),
    )


@router.post(_BASE + "/{encounter_id}/participants/{participant_id}/remove")
def remove_participant_endpoint(
    encounter_id: uuid.UUID,
    participant_id: uuid.UUID,
    access: _Access,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    return _write(
        command_name="remove_encounter_participant",
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload={"encounter_id": str(encounter_id), "participant_id": str(participant_id)},
        created=False,
        command=lambda: remove_encounter_participant(
            connection,
            campaign_id=access.campaign_id,
            actor_user_id=access.user_id,
            encounter_id=encounter_id,
            encounter_participant_id=participant_id,
        ),
    )


class OperationRequest(BaseAuthoringRequest):
    world_time_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=4000)


def _operate(
    *,
    command_name: str,
    encounter_id: uuid.UUID,
    access: AccessContext,
    connection: Connection,
    idempotency_key: str | None,
    correlation_id: str | None,
    body: OperationRequest,
    command: Callable[[], EncounterOperationResult],
) -> Any:
    idem = start_campaign_idempotency(
        connection,
        actor_user_id=access.user_id,
        campaign_id=access.campaign_id,
        idempotency_key=idempotency_key,
        command_name=command_name,
        payload={"encounter_id": str(encounter_id), **body.model_dump(mode="json")},
        correlation_id=correlation_id,
    )
    if idem.replay is not None:
        return idem.replay
    result = command()
    record_change_log(
        connection,
        change_action_code="updated",
        schema_name="narrative",
        table_name="encounters",
        record_id=result.encounter_id,
        entity_id=None,
        world_id=result.world_id,
        actor_user_id=access.user_id,
        correlation_id=correlation_id,
        command_name=command_name,
        event_id=result.event_id,
        previous_status=result.previous_status,
        new_status=result.new_status,
    )
    response = {
        **_view_json(_load(connection, access, encounter_id), changed=True),
        "event_id": None if result.event_id is None else str(result.event_id),
    }
    finish_campaign_idempotency(connection, idem, status_code=200, body=response)
    return response


@router.post(_BASE + "/{encounter_id}/start")
def start_endpoint(
    encounter_id: uuid.UUID,
    body: OperationRequest,
    access: _Access,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    return _operate(
        command_name="start_encounter",
        encounter_id=encounter_id,
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        body=body,
        command=lambda: start_prepared_encounter(
            connection,
            campaign_id=access.campaign_id,
            actor_user_id=access.user_id,
            encounter_id=encounter_id,
            world_time_id=body.world_time_id,
            session_id=body.session_id,
            note=body.note,
        ),
    )


@router.post(_BASE + "/{encounter_id}/abort")
def abort_endpoint(
    encounter_id: uuid.UUID,
    body: OperationRequest,
    access: _Access,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    return _operate(
        command_name="abort_encounter",
        encounter_id=encounter_id,
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        body=body,
        command=lambda: abort_encounter(
            connection,
            campaign_id=access.campaign_id,
            actor_user_id=access.user_id,
            encounter_id=encounter_id,
            world_time_id=body.world_time_id,
            session_id=body.session_id,
            note=body.note,
        ),
    )
