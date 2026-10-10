"""Quest runtime endpoints (Phase 15 checkpoint 15.2E-2b, decision D-16).

    GET  /campaigns/{id}/quests/{quest_id}/progress
    POST /campaigns/{id}/quests/{quest_id}/activate|complete|fail|suspend|resume|abandon
    POST /campaigns/{id}/quests/objectives/{objective_id}/status

All `canon.edit`. The writes use the campaign idempotency store, re-check authority under
lock in the command, answer with an id-only receipt and write one audit row. The caller
names the status it saw (`expected_status`); a quest or objective that moved is a stale
write. The older `POST .../objectives/{id}/advance` adapter route is kept; it now refuses
objective progress for a quest that is suspended or finished.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import Field
from sqlalchemy import Connection, text

from dnd_ai.commands.quest_runtime import RuntimeResult, change_quest_status, set_objective_status
from dnd_ai.domain.access import AccessContext
from dnd_ai.domain.authoring import DESCRIPTION_MAX_LENGTH
from dnd_ai.domain.quest_runtime import OBJECTIVE_TARGETS
from dnd_ai.queries.quest_runtime import get_quest_progress

from ._authoring import (
    BaseAuthoringRequest,
    finish_campaign_idempotency,
    start_campaign_idempotency,
)
from .access import require_campaign_capability
from .audit import record_change_log
from .correlation import get_request_correlation_id
from .deps import get_connection, get_idempotency_key

router = APIRouter(tags=["quest-runtime"])

_Conn = Annotated[Connection, Depends(get_connection)]
_Key = Annotated[str | None, Depends(get_idempotency_key)]
_Corr = Annotated[str | None, Depends(get_request_correlation_id)]
_Edit = Annotated[AccessContext, Depends(require_campaign_capability("canon.edit"))]

_QUESTS = "/campaigns/{campaign_id}/quests"

_QUEST_STATUS_PATTERN = "^(unavailable|available|active|suspended|completed|failed|abandoned)$"
_OBJECTIVE_STATUS_PATTERN = "^(hidden|available|active|completed|failed|skipped|superseded)$"


class QuestActionRequest(BaseAuthoringRequest):
    # The status the editor saw; null when the quest had no state for this audience.
    expected_status: str | None = Field(pattern=_QUEST_STATUS_PATTERN)
    party_id: uuid.UUID | None = None
    world_time_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=DESCRIPTION_MAX_LENGTH)


class ObjectiveStatusRequest(BaseAuthoringRequest):
    new_status: str = Field(pattern="^(" + "|".join(OBJECTIVE_TARGETS) + ")$")
    expected_status: str | None = Field(pattern=_OBJECTIVE_STATUS_PATTERN)
    party_id: uuid.UUID | None = None
    world_time_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=DESCRIPTION_MAX_LENGTH)


def _run(
    *,
    command_name: str,
    access: AccessContext,
    connection: Connection,
    idempotency_key: str | None,
    correlation_id: str | None,
    payload: dict[str, Any],
    command: Any,
    table: str,
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
    result: RuntimeResult = command()
    record_change_log(
        connection,
        change_action_code="updated" if result.previous_status is not None else "created",
        schema_name="campaign",
        table_name=table,
        record_id=result.state_id,
        entity_id=result.quest_id,
        world_id=result.world_id,
        actor_user_id=access.user_id,
        correlation_id=correlation_id,
        command_name=command_name,
        event_id=result.event_id,
        changed_fields=result.changed_fields,
    )
    receipt: dict[str, Any] = {
        "quest_id": str(result.quest_id),
        "event_id": str(result.event_id),
        "previous_status": result.previous_status,
        "status": result.new_status,
        "changed": True,
    }
    if result.quest_objective_id is not None:
        receipt["quest_objective_id"] = str(result.quest_objective_id)
    finish_campaign_idempotency(connection, idem, status_code=200, body=receipt)
    return JSONResponse(status_code=200, content=receipt)


@router.get(_QUESTS + "/{quest_id}/progress")
def get_progress_endpoint(quest_id: uuid.UUID, access: _Edit, connection: _Conn) -> dict[str, Any]:
    world_id = connection.execute(
        text("SELECT world_id FROM campaign.timelines WHERE timeline_id = :t"),
        {"t": access.timeline_id},
    ).scalar()
    assert isinstance(world_id, uuid.UUID)
    progress = get_quest_progress(
        connection,
        world_id=world_id,
        campaign_id=access.campaign_id,
        timeline_id=access.timeline_id,
        quest_id=quest_id,
    )
    if progress is None:
        raise HTTPException(status_code=404, detail="not found")
    return {
        "quest_id": str(progress.quest_id),
        "name": progress.name,
        "published": progress.published,
        "scopes": [
            {
                "party_id": None if s.party_id is None else str(s.party_id),
                "party_name": s.party_name,
                "status": s.status,
                "actions": s.actions,
                "all_required_complete": s.all_required_complete,
                "objectives": [
                    {
                        "quest_objective_id": str(o.quest_objective_id),
                        "name": o.name,
                        "stage_name": o.stage_name,
                        "requirement_level": o.requirement_level,
                        "status": o.status,
                        "next_statuses": o.next_statuses,
                    }
                    for o in s.objectives
                ],
            }
            for s in progress.scopes
        ],
    }


def _quest_action(action: str) -> Any:
    def endpoint(
        quest_id: uuid.UUID,
        body: QuestActionRequest,
        access: _Edit,
        connection: _Conn,
        idempotency_key: _Key,
        correlation_id: _Corr,
    ) -> Any:
        return _run(
            command_name=f"quest_{action}",
            access=access,
            connection=connection,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            payload={"quest_id": str(quest_id), **body.model_dump(mode="json")},
            table="quest_state",
            command=lambda: change_quest_status(
                connection,
                campaign_id=access.campaign_id,
                actor_user_id=access.user_id,
                quest_id=quest_id,
                action=action,
                expected_status=body.expected_status,
                party_id=body.party_id,
                world_time_id=body.world_time_id,
                note=body.note,
            ),
        )

    endpoint.__name__ = f"quest_{action}_endpoint"
    return endpoint


for _action in ("activate", "complete", "fail", "suspend", "resume", "abandon"):
    router.add_api_route(
        _QUESTS + "/{quest_id}/" + _action, _quest_action(_action), methods=["POST"]
    )


@router.post(_QUESTS + "/objectives/{quest_objective_id}/status")
def set_objective_status_endpoint(
    quest_objective_id: uuid.UUID,
    body: ObjectiveStatusRequest,
    access: _Edit,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    return _run(
        command_name="set_objective_status",
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload={"quest_objective_id": str(quest_objective_id), **body.model_dump(mode="json")},
        table="objective_state",
        command=lambda: set_objective_status(
            connection,
            campaign_id=access.campaign_id,
            actor_user_id=access.user_id,
            quest_objective_id=quest_objective_id,
            new_status=body.new_status,
            expected_status=body.expected_status,
            party_id=body.party_id,
            world_time_id=body.world_time_id,
            note=body.note,
        ),
    )
