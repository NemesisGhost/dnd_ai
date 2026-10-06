"""World relationship authoring endpoints (Phase 15 checkpoint 15.3A-2a, D-18, ADR 0017).

    GET  /campaigns/{id}/authoring/relationships/options
    GET  /campaigns/{id}/authoring/relationships?entity_id=&include_archived=
    POST /campaigns/{id}/authoring/relationships
    GET  /campaigns/{id}/authoring/relationships/{relationship_id}
    POST /campaigns/{id}/authoring/relationships/{relationship_id}/update|end|archive|restore
    POST /campaigns/{id}/authoring/relationships/{relationship_id}/perspectives

All `canon.edit`. A relationship is created with its participants and its kind's typed fields;
afterwards its kind, type and participants never change. Every mutation takes the relationship
version the editor saw and an `Idempotency-Key`, writes one audit row for a real change (the
description, tone and interpretations are redacted), and answers with the refreshed view.
Readers who cannot edit use the audience-filtered relationship reads, which hide an archived
relationship and one whose subtype is not public.
"""

import uuid
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import Field
from sqlalchemy import Connection

from dnd_ai.commands.world_relationships import (
    ParticipantInput,
    RelationshipResult,
    archive_relationship,
    create_relationship,
    end_relationship,
    restore_relationship,
    set_relationship_perspective,
    update_relationship,
)
from dnd_ai.domain.access import AccessContext
from dnd_ai.domain.authoring import REASON_MAX_LENGTH
from dnd_ai.domain.relationship_authoring import (
    MAX_PARTICIPANTS,
    MIN_PARTICIPANTS,
    RELATIONSHIP_KINDS,
    SHORT_TEXT_MAX_LENGTH,
    STANCE_MAX,
    STANCE_MIN,
    TEXT_MAX_LENGTH,
)
from dnd_ai.queries.relationship_authoring import (
    Participant,
    RelationshipAuthoringView,
    get_relationship_authoring,
    list_entity_relationships,
)

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
from .errors import NotFoundError

router = APIRouter(tags=["relationship-authoring"])

_BASE = "/campaigns/{campaign_id}/authoring/relationships"
_Access = Annotated[AccessContext, Depends(require_campaign_capability("canon.edit"))]
_Conn = Annotated[Connection, Depends(get_connection)]
_Key = Annotated[str | None, Depends(get_idempotency_key)]
_Corr = Annotated[str | None, Depends(get_request_correlation_id)]


class ParticipantBody(BaseAuthoringRequest):
    entity_id: uuid.UUID
    role: str = Field(min_length=1, max_length=64)


class CreateRelationshipRequest(BaseAuthoringRequest):
    kind: str = Field(min_length=1, max_length=32)
    relationship_type: str = Field(min_length=1, max_length=64)
    participants: list[ParticipantBody] = Field(
        min_length=MIN_PARTICIPANTS, max_length=MAX_PARTICIPANTS
    )
    description: str | None = Field(default=None, max_length=TEXT_MAX_LENGTH)
    started_world_time_id: uuid.UUID | None = None
    family_unit_name: str | None = Field(default=None, max_length=SHORT_TEXT_MAX_LENGTH)
    job_title: str | None = Field(default=None, max_length=SHORT_TEXT_MAX_LENGTH)
    ownership_share: int | None = Field(default=None, ge=0, le=100)
    is_public: bool | None = None
    is_active: bool | None = None
    treaty_terms: str | None = Field(default=None, max_length=TEXT_MAX_LENGTH)
    role: str | None = Field(default=None, max_length=SHORT_TEXT_MAX_LENGTH)
    rank: str | None = Field(default=None, max_length=SHORT_TEXT_MAX_LENGTH)


class UpdateRelationshipRequest(BaseAuthoringRequest):
    expected_row_version: int = Field(ge=1)
    description: str | None = Field(default=None, max_length=TEXT_MAX_LENGTH)
    started_world_time_id: uuid.UUID | None = None
    family_unit_name: str | None = Field(default=None, max_length=SHORT_TEXT_MAX_LENGTH)
    job_title: str | None = Field(default=None, max_length=SHORT_TEXT_MAX_LENGTH)
    ownership_share: int | None = Field(default=None, ge=0, le=100)
    is_public: bool | None = None
    is_active: bool | None = None
    treaty_terms: str | None = Field(default=None, max_length=TEXT_MAX_LENGTH)
    role: str | None = Field(default=None, max_length=SHORT_TEXT_MAX_LENGTH)
    rank: str | None = Field(default=None, max_length=SHORT_TEXT_MAX_LENGTH)
    change_note: str | None = Field(default=None, max_length=REASON_MAX_LENGTH)


class EndRelationshipRequest(BaseAuthoringRequest):
    expected_row_version: int = Field(ge=1)
    ended_world_time_id: uuid.UUID


class VersionRequest(BaseAuthoringRequest):
    expected_row_version: int = Field(ge=1)


class PerspectiveRequest(BaseAuthoringRequest):
    expected_row_version: int = Field(ge=1)
    holder_entity_id: uuid.UUID
    affinity: int | None = Field(default=None, ge=STANCE_MIN, le=STANCE_MAX)
    trust: int | None = Field(default=None, ge=STANCE_MIN, le=STANCE_MAX)
    respect: int | None = Field(default=None, ge=STANCE_MIN, le=STANCE_MAX)
    fear: int | None = Field(default=None, ge=STANCE_MIN, le=STANCE_MAX)
    obligation: int | None = Field(default=None, ge=STANCE_MIN, le=STANCE_MAX)
    emotional_tone: str | None = Field(default=None, max_length=SHORT_TEXT_MAX_LENGTH)
    private_interpretation: str | None = Field(default=None, max_length=TEXT_MAX_LENGTH)


_TYPED_NAMES = (
    "family_unit_name",
    "job_title",
    "ownership_share",
    "is_public",
    "is_active",
    "treaty_terms",
    "role",
    "rank",
)


def _typed_from(body: BaseAuthoringRequest) -> dict[str, Any]:
    """Only the typed fields the caller actually sent."""
    return {name: getattr(body, name) for name in _TYPED_NAMES if name in body.model_fields_set}


def _participant_json(p: Participant) -> dict[str, Any]:
    return {
        "entity_id": str(p.entity_id),
        "name": p.name,
        "entity_type_code": p.entity_type_code,
        "canon_status": p.canon_status,
        "lifecycle_status": p.lifecycle_status,
        "role": p.role,
        "role_label": p.role_label,
    }


def _view_json(view: RelationshipAuthoringView, *, changed: bool | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "relationship_id": str(view.relationship_id),
        "kind": view.kind,
        "kind_label": view.kind_label,
        "relationship_type": view.relationship_type,
        "relationship_type_label": view.relationship_type_label,
        "description": view.description,
        "started_world_time_id": None
        if view.started_world_time_id is None
        else str(view.started_world_time_id),
        "started": view.started,
        "ended_world_time_id": None
        if view.ended_world_time_id is None
        else str(view.ended_world_time_id),
        "ended": view.ended,
        "lifecycle_status": view.lifecycle_status,
        "row_version": view.row_version,
        "typed": view.typed,
        "participants": [_participant_json(p) for p in view.participants],
        "perspectives": [
            {
                "holder_entity_id": str(p.holder_entity_id),
                "holder_name": p.holder_name,
                "affinity": p.affinity,
                "trust": p.trust,
                "respect": p.respect,
                "fear": p.fear,
                "obligation": p.obligation,
                "emotional_tone": p.emotional_tone,
                "private_interpretation": p.private_interpretation,
            }
            for p in view.perspectives
        ],
        "current_status": view.current_status,
        "available_actions": view.available_actions,
    }
    if changed is not None:
        body["changed"] = changed
    return body


def _run(
    *,
    command_name: str,
    access: AccessContext,
    connection: Connection,
    idempotency_key: str | None,
    correlation_id: str | None,
    payload: dict[str, Any],
    command: Callable[[], RelationshipResult],
    created: bool = False,
    reason: str | None = None,
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
            schema_name="world",
            table_name=result.record_table,
            record_id=result.record_id or result.relationship_id,
            # A relationship has no core.entities identity of its own.
            entity_id=None,
            world_id=result.world_id,
            actor_user_id=access.user_id,
            correlation_id=correlation_id,
            command_name=command_name,
            event_id=None,
            changed_fields=result.changed_fields or None,
            reason=reason,
        )
    view = get_relationship_authoring(
        connection,
        world_id=result.world_id,
        timeline_id=access.timeline_id,
        relationship_id=result.relationship_id,
    )
    if view is None:
        raise NotFoundError()
    response = _view_json(view, changed=result.changed)
    status = 201 if created else 200
    finish_campaign_idempotency(connection, idem, status_code=status, body=response)
    return JSONResponse(status_code=status, content=response) if created else response


@router.get(_BASE + "/options")
def options_endpoint(access: _Access) -> dict[str, Any]:
    del access
    return {
        "can_create": True,
        "kinds": [
            {
                "code": k.code,
                "label": k.label,
                "types": list(k.types),
                "roles": list(k.roles),
                "fixed_roles": None if k.fixed_roles is None else list(k.fixed_roles),
            }
            for k in RELATIONSHIP_KINDS
        ],
        "limits": {
            "text_max_length": TEXT_MAX_LENGTH,
            "short_text_max_length": SHORT_TEXT_MAX_LENGTH,
            "stance_min": STANCE_MIN,
            "stance_max": STANCE_MAX,
            "min_participants": MIN_PARTICIPANTS,
            "max_participants": MAX_PARTICIPANTS,
        },
    }


@router.get(_BASE)
def list_endpoint(
    access: _Access,
    connection: _Conn,
    entity_id: Annotated[uuid.UUID, Query()],
    include_archived: bool = False,
) -> dict[str, Any]:
    items = list_entity_relationships(
        connection,
        world_id=timeline_world_id(connection, access.timeline_id),
        entity_id=entity_id,
        include_archived=include_archived,
    )
    return {
        "items": [
            {
                "relationship_id": str(i.relationship_id),
                "kind": i.kind,
                "relationship_type": i.relationship_type,
                "relationship_type_label": i.relationship_type_label,
                "description": i.description,
                "lifecycle_status": i.lifecycle_status,
                "ended": i.ended,
                "is_public": i.is_public,
                "row_version": i.row_version,
                "participants": [_participant_json(p) for p in i.participants],
            }
            for i in items
        ]
    }


@router.get(_BASE + "/{relationship_id}")
def get_endpoint(relationship_id: uuid.UUID, access: _Access, connection: _Conn) -> Any:
    view = get_relationship_authoring(
        connection,
        world_id=timeline_world_id(connection, access.timeline_id),
        timeline_id=access.timeline_id,
        relationship_id=relationship_id,
    )
    if view is None:
        raise NotFoundError()
    return _view_json(view)


@router.post(_BASE, status_code=201)
def create_endpoint(
    body: CreateRelationshipRequest,
    access: _Access,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    return _run(
        command_name="create_relationship",
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload=body.model_dump(mode="json"),
        created=True,
        command=lambda: create_relationship(
            connection,
            campaign_id=access.campaign_id,
            actor_user_id=access.user_id,
            kind=body.kind,
            relationship_type=body.relationship_type,
            participants=[ParticipantInput(p.entity_id, p.role) for p in body.participants],
            description=body.description,
            started_world_time_id=body.started_world_time_id,
            typed=_typed_from(body),
        ),
    )


@router.post(_BASE + "/{relationship_id}/update")
def update_endpoint(
    relationship_id: uuid.UUID,
    body: UpdateRelationshipRequest,
    access: _Access,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    return _run(
        command_name="update_relationship",
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload={"relationship_id": str(relationship_id), **body.model_dump(mode="json")},
        reason=(body.change_note or "").strip() or None,
        command=lambda: update_relationship(
            connection,
            campaign_id=access.campaign_id,
            actor_user_id=access.user_id,
            relationship_id=relationship_id,
            expected_row_version=body.expected_row_version,
            description=body.description,
            started_world_time_id=body.started_world_time_id,
            typed=_typed_from(body),
            change_note=body.change_note,
        ),
    )


@router.post(_BASE + "/{relationship_id}/end")
def end_endpoint(
    relationship_id: uuid.UUID,
    body: EndRelationshipRequest,
    access: _Access,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    return _run(
        command_name="end_relationship",
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload={"relationship_id": str(relationship_id), **body.model_dump(mode="json")},
        command=lambda: end_relationship(
            connection,
            campaign_id=access.campaign_id,
            actor_user_id=access.user_id,
            relationship_id=relationship_id,
            expected_row_version=body.expected_row_version,
            ended_world_time_id=body.ended_world_time_id,
        ),
    )


def _lifecycle_endpoint(name: str, command: Callable[..., RelationshipResult]) -> None:
    def endpoint(
        relationship_id: uuid.UUID,
        body: VersionRequest,
        access: _Access,
        connection: _Conn,
        idempotency_key: _Key,
        correlation_id: _Corr,
    ) -> Any:
        return _run(
            command_name=f"{name}_relationship",
            access=access,
            connection=connection,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            payload={"relationship_id": str(relationship_id), **body.model_dump(mode="json")},
            command=lambda: command(
                connection,
                campaign_id=access.campaign_id,
                actor_user_id=access.user_id,
                relationship_id=relationship_id,
                expected_row_version=body.expected_row_version,
            ),
        )

    endpoint.__name__ = f"{name}_relationship_endpoint"
    router.add_api_route(_BASE + "/{relationship_id}/" + name, endpoint, methods=["POST"])


_lifecycle_endpoint("archive", archive_relationship)
_lifecycle_endpoint("restore", restore_relationship)


@router.post(_BASE + "/{relationship_id}/perspectives")
def perspective_endpoint(
    relationship_id: uuid.UUID,
    body: PerspectiveRequest,
    access: _Access,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    return _run(
        command_name="set_relationship_perspective",
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload={"relationship_id": str(relationship_id), **body.model_dump(mode="json")},
        command=lambda: set_relationship_perspective(
            connection,
            campaign_id=access.campaign_id,
            actor_user_id=access.user_id,
            relationship_id=relationship_id,
            expected_row_version=body.expected_row_version,
            holder_entity_id=body.holder_entity_id,
            affinity=body.affinity,
            trust=body.trust,
            respect=body.respect,
            fear=body.fear,
            obligation=body.obligation,
            emotional_tone=body.emotional_tone,
            private_interpretation=body.private_interpretation,
        ),
    )
