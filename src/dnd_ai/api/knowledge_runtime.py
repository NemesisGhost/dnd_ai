"""Knowledge runtime endpoints (Phase 15 checkpoint 15.2E-3, decision D-17).

    GET  /campaigns/{id}/knowledge/{item_id}/audience
    POST /campaigns/{id}/knowledge/{item_id}/reveal-to-party
    POST /campaigns/{id}/knowledge/{item_id}/learn
    POST /campaigns/{id}/knowledge/{item_id}/transfer
    POST /campaigns/{id}/knowledge/{item_id}/make-public
    POST /campaigns/{id}/knowledge/knowers/{entity_knowledge_id}/belief

All `canon.edit`. The writes use the campaign idempotency store, re-check authority under
lock in the command, answer with an id-only receipt and write one audit row in which
interpretation text is redacted. Players learn what they know only through the existing
perspective-scoped knowledge reads; the audience read is for editors.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import Field
from sqlalchemy import Connection, text

from dnd_ai.commands.knowledge_runtime import (
    KnowledgeResult,
    change_belief,
    make_knowledge_public,
    record_character_knowledge,
    record_knowledge_transfer,
    reveal_knowledge_to_party,
)
from dnd_ai.domain.access import AccessContext
from dnd_ai.domain.authoring import DESCRIPTION_MAX_LENGTH
from dnd_ai.domain.knowledge_runtime import (
    AWARENESS_LEVELS,
    INTERPRETATION_MAX_LENGTH,
    TRANSFER_METHODS,
)
from dnd_ai.queries.knowledge_audience import get_knowledge_audience

from ._authoring import (
    BaseAuthoringRequest,
    finish_campaign_idempotency,
    start_campaign_idempotency,
)
from .access import require_campaign_capability
from .audit import record_change_log
from .correlation import get_request_correlation_id
from .deps import get_connection, get_idempotency_key

router = APIRouter(tags=["knowledge-runtime"])

_Conn = Annotated[Connection, Depends(get_connection)]
_Key = Annotated[str | None, Depends(get_idempotency_key)]
_Corr = Annotated[str | None, Depends(get_request_correlation_id)]
_Edit = Annotated[AccessContext, Depends(require_campaign_capability("canon.edit"))]

_KNOWLEDGE = "/campaigns/{campaign_id}/knowledge"
_AWARENESS = "^(" + "|".join(AWARENESS_LEVELS) + ")$"
_METHOD = "^(" + "|".join(TRANSFER_METHODS) + ")$"
_SCHEMA = {
    "party_knowledge": "campaign",
    "entity_knowledge": "knowledge",
    "information_transfers": "knowledge",
    "public_knowledge": "knowledge",
}


class RevealRequest(BaseAuthoringRequest):
    party_id: uuid.UUID
    awareness_level: str = Field(default="aware", pattern=_AWARENESS)
    world_time_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=DESCRIPTION_MAX_LENGTH)


class LearnRequest(BaseAuthoringRequest):
    knower_entity_id: uuid.UUID
    awareness_level: str = Field(default="aware", pattern=_AWARENESS)
    confidence: int | None = Field(default=None, ge=0, le=100)
    interpretation: str | None = Field(default=None, max_length=INTERPRETATION_MAX_LENGTH)
    willing_to_share: bool = True
    world_time_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=DESCRIPTION_MAX_LENGTH)


class TransferRequest(BaseAuthoringRequest):
    source_entity_id: uuid.UUID
    recipient_entity_id: uuid.UUID
    transfer_method: str = Field(default="dialogue", pattern=_METHOD)
    awareness_level: str = Field(default="aware", pattern=_AWARENESS)
    modified_interpretation: str | None = Field(default=None, max_length=INTERPRETATION_MAX_LENGTH)
    world_time_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=DESCRIPTION_MAX_LENGTH)


class PublicRequest(BaseAuthoringRequest):
    location_id: uuid.UUID
    awareness_level: str = Field(default="aware", pattern=_AWARENESS)
    world_time_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=DESCRIPTION_MAX_LENGTH)


class BeliefRequest(BaseAuthoringRequest):
    # The event that last wrote the belief the editor saw; null when it has none.
    expected_last_event_id: uuid.UUID | None
    awareness_level: str | None = Field(default=None, pattern=_AWARENESS)
    confidence: int | None = Field(default=None, ge=0, le=100)
    interpretation: str | None = Field(default=None, max_length=INTERPRETATION_MAX_LENGTH)
    willing_to_share: bool | None = None
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
    status_code: int,
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
    result: KnowledgeResult = command()
    if result.changed:
        record_change_log(
            connection,
            change_action_code="created" if status_code == 201 else "updated",
            schema_name=_SCHEMA[result.table],
            table_name=result.table,
            record_id=result.record_id,
            entity_id=result.knowledge_item_id,
            world_id=result.world_id,
            actor_user_id=access.user_id,
            correlation_id=correlation_id,
            command_name=command_name,
            event_id=result.event_id,
            changed_fields=result.changed_fields or None,
        )
    receipt: dict[str, Any] = {
        "knowledge_item_id": str(result.knowledge_item_id),
        "record_id": str(result.record_id),
        "changed": result.changed,
    }
    if result.event_id is not None:
        receipt["event_id"] = str(result.event_id)
    if result.knower_entity_id is not None:
        receipt["knower_entity_id"] = str(result.knower_entity_id)
    status = status_code if result.changed else 200
    finish_campaign_idempotency(connection, idem, status_code=status, body=receipt)
    return JSONResponse(status_code=status, content=receipt)


@router.get(_KNOWLEDGE + "/{knowledge_item_id}/audience")
def get_audience_endpoint(
    knowledge_item_id: uuid.UUID, access: _Edit, connection: _Conn
) -> dict[str, Any]:
    world_id = connection.execute(
        text("SELECT world_id FROM campaign.timelines WHERE timeline_id = :t"),
        {"t": access.timeline_id},
    ).scalar()
    assert isinstance(world_id, uuid.UUID)
    audience = get_knowledge_audience(
        connection,
        world_id=world_id,
        timeline_id=access.timeline_id,
        knowledge_item_id=knowledge_item_id,
    )
    if audience is None:
        raise HTTPException(status_code=404, detail="not found")

    def opt(value: uuid.UUID | None) -> str | None:
        return None if value is None else str(value)

    return {
        "knowledge_item_id": str(audience.knowledge_item_id),
        "awareness_levels": list(AWARENESS_LEVELS),
        "transfer_methods": list(TRANSFER_METHODS),
        "parties": [
            {
                "party_knowledge_id": str(p.party_knowledge_id),
                "party_id": str(p.party_id),
                "party_name": p.party_name,
                "awareness_level": p.awareness_level,
            }
            for p in audience.parties
        ],
        "knowers": [
            {
                "entity_knowledge_id": str(k.entity_knowledge_id),
                "knower_entity_id": str(k.knower_entity_id),
                "knower_name": k.knower_name,
                "knower_type": k.knower_type,
                "awareness_level": k.awareness_level,
                "confidence": k.confidence,
                "interpretation": k.interpretation,
                "willing_to_share": k.willing_to_share,
                "last_event_id": opt(k.last_event_id),
            }
            for k in audience.knowers
        ],
        "public": [
            {
                "public_knowledge_id": str(p.public_knowledge_id),
                "location_id": str(p.location_id),
                "location_name": p.location_name,
                "awareness_level": p.awareness_level,
            }
            for p in audience.public
        ],
    }


@router.post(_KNOWLEDGE + "/{knowledge_item_id}/reveal-to-party")
def reveal_endpoint(
    knowledge_item_id: uuid.UUID,
    body: RevealRequest,
    access: _Edit,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    return _run(
        command_name="reveal_knowledge_to_party",
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload={"knowledge_item_id": str(knowledge_item_id), **body.model_dump(mode="json")},
        status_code=201,
        command=lambda: reveal_knowledge_to_party(
            connection,
            campaign_id=access.campaign_id,
            actor_user_id=access.user_id,
            knowledge_item_id=knowledge_item_id,
            party_id=body.party_id,
            awareness_level=body.awareness_level,
            world_time_id=body.world_time_id,
            session_id=body.session_id,
            note=body.note,
        ),
    )


@router.post(_KNOWLEDGE + "/{knowledge_item_id}/learn")
def learn_endpoint(
    knowledge_item_id: uuid.UUID,
    body: LearnRequest,
    access: _Edit,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    return _run(
        command_name="record_character_knowledge",
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload={"knowledge_item_id": str(knowledge_item_id), **body.model_dump(mode="json")},
        status_code=201,
        command=lambda: record_character_knowledge(
            connection,
            campaign_id=access.campaign_id,
            actor_user_id=access.user_id,
            knowledge_item_id=knowledge_item_id,
            knower_entity_id=body.knower_entity_id,
            awareness_level=body.awareness_level,
            confidence=body.confidence,
            interpretation=body.interpretation,
            willing_to_share=body.willing_to_share,
            world_time_id=body.world_time_id,
            note=body.note,
        ),
    )


@router.post(_KNOWLEDGE + "/{knowledge_item_id}/transfer")
def transfer_endpoint(
    knowledge_item_id: uuid.UUID,
    body: TransferRequest,
    access: _Edit,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    return _run(
        command_name="record_knowledge_transfer",
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload={"knowledge_item_id": str(knowledge_item_id), **body.model_dump(mode="json")},
        status_code=201,
        command=lambda: record_knowledge_transfer(
            connection,
            campaign_id=access.campaign_id,
            actor_user_id=access.user_id,
            knowledge_item_id=knowledge_item_id,
            source_entity_id=body.source_entity_id,
            recipient_entity_id=body.recipient_entity_id,
            transfer_method=body.transfer_method,
            awareness_level=body.awareness_level,
            modified_interpretation=body.modified_interpretation,
            world_time_id=body.world_time_id,
            note=body.note,
        ),
    )


@router.post(_KNOWLEDGE + "/{knowledge_item_id}/make-public")
def make_public_endpoint(
    knowledge_item_id: uuid.UUID,
    body: PublicRequest,
    access: _Edit,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    return _run(
        command_name="make_knowledge_public",
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload={"knowledge_item_id": str(knowledge_item_id), **body.model_dump(mode="json")},
        status_code=201,
        command=lambda: make_knowledge_public(
            connection,
            campaign_id=access.campaign_id,
            actor_user_id=access.user_id,
            knowledge_item_id=knowledge_item_id,
            location_id=body.location_id,
            awareness_level=body.awareness_level,
            world_time_id=body.world_time_id,
            note=body.note,
        ),
    )


@router.post(_KNOWLEDGE + "/knowers/{entity_knowledge_id}/belief")
def belief_endpoint(
    entity_knowledge_id: uuid.UUID,
    body: BeliefRequest,
    access: _Edit,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    sent = body.model_fields_set
    changes: dict[str, Any] = {
        name: getattr(body, name)
        for name in ("awareness_level", "confidence", "interpretation", "willing_to_share")
        if name in sent
    }
    return _run(
        command_name="change_belief",
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload={"entity_knowledge_id": str(entity_knowledge_id), **body.model_dump(mode="json")},
        status_code=200,
        command=lambda: change_belief(
            connection,
            campaign_id=access.campaign_id,
            actor_user_id=access.user_id,
            entity_knowledge_id=entity_knowledge_id,
            expected_last_event_id=body.expected_last_event_id,
            changes=changes,
            world_time_id=body.world_time_id,
            note=body.note,
        ),
    )
