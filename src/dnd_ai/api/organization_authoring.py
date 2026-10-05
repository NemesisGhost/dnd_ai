"""Typed Organization and Religion authoring endpoints (Phase 15.1, ADR 0015).

    GET  /campaigns/{campaign_id}/authoring/organizations/options
    GET  /campaigns/{campaign_id}/authoring/organizations/parent-options
    POST /campaigns/{campaign_id}/authoring/organizations
    GET  /campaigns/{campaign_id}/authoring/organizations/{organization_id}
    POST /campaigns/{campaign_id}/authoring/organizations/{organization_id}/update

    GET  /campaigns/{campaign_id}/authoring/religions/reference-options
    POST /campaigns/{campaign_id}/authoring/religions
    GET  /campaigns/{campaign_id}/authoring/religions/{religion_id}
    POST /campaigns/{campaign_id}/authoring/religions/{religion_id}/update

The contract is the same as Location authoring (`dnd_ai.api.location_authoring`):
`canon.edit` checked before anything resolves and again under lock, humans only,
the world derived from the campaign, strict bodies, campaign-scoped idempotency,
one audit row per real change, `Cache-Control: no-store`. Headquarters choices
come from the Location parent-options list; they are not duplicated here.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import Field
from sqlalchemy import Connection

from dnd_ai.commands._content import ContentWriteResult
from dnd_ai.commands.organizations import create_organization, update_organization
from dnd_ai.commands.religions import create_religion, update_religion
from dnd_ai.domain.access import AccessContext
from dnd_ai.domain.authoring import DESCRIPTION_MAX_LENGTH, NAME_MAX_LENGTH, REASON_MAX_LENGTH
from dnd_ai.domain.organization_authoring import (
    DESCRIPTION_FIELD_MAX_LENGTH,
    GENERIC_ORGANIZATION_TYPES,
    ORGANIZATION_ENTITY_TYPE_CODES,
    REPUTATION_MAX,
    REPUTATION_MIN,
    SHORT_FIELD_MAX_LENGTH,
    OrganizationField,
    OrganizationKind,
)
from dnd_ai.queries.organization_authoring import (
    OrganizationAuthoringView,
    ReferenceSummary,
    ReligionAuthoringView,
    get_organization_authoring,
    get_religion_authoring,
    list_organization_kinds,
)
from dnd_ai.queries.reference_options import descendant_ids, list_reference_options

from ._authoring import (
    BaseAuthoringRequest,
    finish_campaign_idempotency,
    start_campaign_idempotency,
)
from ._content_support import (
    audit_content_write,
    clean_note,
    decode_name_cursor,
    reference_options_page,
)
from ._shared import timeline_world_id
from .access import require_campaign_capability
from .correlation import get_request_correlation_id
from .deps import get_connection, get_idempotency_key
from .errors import NotFoundError
from .pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

router = APIRouter(tags=["organization-authoring"])

_ORG = "/campaigns/{campaign_id}/authoring/organizations"
_REL = "/campaigns/{campaign_id}/authoring/religions"
_CAPABILITY = "canon.edit"

_Access = Annotated[AccessContext, Depends(require_campaign_capability(_CAPABILITY))]
_Conn = Annotated[Connection, Depends(get_connection)]
_Key = Annotated[str | None, Depends(get_idempotency_key)]
_Corr = Annotated[str | None, Depends(get_request_correlation_id)]

_TYPED_FIELD_NAMES = (
    "organization_type",
    "business_type",
    "operating_status",
    "reputation",
    "government_form",
    "unit_type",
    "ideology",
)


class _OrganizationFields(BaseAuthoringRequest):
    name: str = Field(min_length=1, max_length=NAME_MAX_LENGTH)
    summary: str | None = Field(default=None, max_length=DESCRIPTION_MAX_LENGTH)
    public_description: str | None = Field(default=None, max_length=DESCRIPTION_FIELD_MAX_LENGTH)
    internal_description: str | None = Field(default=None, max_length=DESCRIPTION_FIELD_MAX_LENGTH)
    parent_organization_id: uuid.UUID | None = None
    headquarters_location_id: uuid.UUID | None = None
    religion_id: uuid.UUID | None = None
    organization_type: str | None = Field(default=None, max_length=64)
    business_type: str | None = Field(default=None, max_length=SHORT_FIELD_MAX_LENGTH)
    operating_status: str | None = Field(default=None, max_length=32)
    reputation: int | None = Field(default=None, ge=REPUTATION_MIN, le=REPUTATION_MAX)
    government_form: str | None = Field(default=None, max_length=SHORT_FIELD_MAX_LENGTH)
    unit_type: str | None = Field(default=None, max_length=SHORT_FIELD_MAX_LENGTH)
    ideology: str | None = Field(default=None, max_length=DESCRIPTION_FIELD_MAX_LENGTH)

    def typed_fields(self) -> dict[str, object]:
        return {name: getattr(self, name) for name in _TYPED_FIELD_NAMES}


class CreateOrganizationRequest(_OrganizationFields):
    kind: str = Field(min_length=1, max_length=64)


class UpdateOrganizationRequest(_OrganizationFields):
    expected_row_version: int = Field(ge=1)
    change_note: str | None = Field(default=None, max_length=REASON_MAX_LENGTH)


class _ReligionFields(BaseAuthoringRequest):
    name: str = Field(min_length=1, max_length=NAME_MAX_LENGTH)
    summary: str | None = Field(default=None, max_length=DESCRIPTION_MAX_LENGTH)
    pantheon_structure: str | None = Field(default=None, max_length=DESCRIPTION_FIELD_MAX_LENGTH)


class CreateReligionRequest(_ReligionFields):
    pass


class UpdateReligionRequest(_ReligionFields):
    expected_row_version: int = Field(ge=1)
    change_note: str | None = Field(default=None, max_length=REASON_MAX_LENGTH)


# --- JSON shaping ---------------------------------------------------------------------------


def _field_json(f: OrganizationField) -> dict[str, Any]:
    return {
        "name": f.name,
        "kind": f.kind,
        "label": f.label,
        "max_length": f.max_length,
        "minimum": f.minimum,
        "maximum": f.maximum,
        "required": f.required,
        "options": [{"value": v, "label": label} for v, label in f.options],
    }


def _kind_json(kind: OrganizationKind) -> dict[str, Any]:
    return {
        "code": kind.code,
        "label": kind.label,
        "needs_religion": kind.needs_religion,
        "fields": [_field_json(f) for f in kind.fields],
    }


def _reference_json(ref: ReferenceSummary | None) -> dict[str, Any] | None:
    if ref is None:
        return None
    return {
        "entity_id": str(ref.entity_id),
        "name": ref.name,
        "canon_status": ref.canon_status,
        "lifecycle_status": ref.lifecycle_status,
    }


def _organization_json(
    view: OrganizationAuthoringView, *, changed: bool | None = None
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "organization_id": str(view.organization_id),
        "name": view.name,
        "summary": view.summary,
        "kind": {"code": view.kind.code, "label": view.kind.label},
        "organization_type": view.organization_type,
        "public_description": view.public_description,
        "internal_description": view.internal_description,
        "parent": _reference_json(view.parent),
        "headquarters": _reference_json(view.headquarters),
        "religion": _reference_json(view.religion),
        "typed": view.typed,
        "canon_status": view.canon_status,
        "lifecycle_status": view.lifecycle_status,
        "row_version": view.row_version,
        "available_actions": view.available_actions,
        "blocked_actions": [{"action": b.action, "reason": b.reason} for b in view.blocked_actions],
        "field_locks": view.field_locks,
    }
    if changed is not None:
        body["changed"] = changed
    return body


def _religion_json(view: ReligionAuthoringView, *, changed: bool | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "religion_id": str(view.religion_id),
        "name": view.name,
        "summary": view.summary,
        "pantheon_structure": view.pantheon_structure,
        "canon_status": view.canon_status,
        "lifecycle_status": view.lifecycle_status,
        "row_version": view.row_version,
        "available_actions": view.available_actions,
        "blocked_actions": [{"action": b.action, "reason": b.reason} for b in view.blocked_actions],
        "field_locks": view.field_locks,
    }
    if changed is not None:
        body["changed"] = changed
    return body


# --- Organizations ----------------------------------------------------------------------------


@router.get(_ORG + "/options")
def organization_options_endpoint(access: _Access) -> dict[str, Any]:
    del access
    return {
        "can_create": True,
        "kinds": [_kind_json(k) for k in list_organization_kinds()],
        "limits": {
            "name_max_length": NAME_MAX_LENGTH,
            "summary_max_length": DESCRIPTION_MAX_LENGTH,
            "description_max_length": DESCRIPTION_FIELD_MAX_LENGTH,
            "change_note_max_length": REASON_MAX_LENGTH,
        },
        "generic_types": [{"value": v, "label": label} for v, label in GENERIC_ORGANIZATION_TYPES],
    }


@router.get(_ORG + "/parent-options")
def organization_parent_options_endpoint(
    access: _Access,
    connection: _Conn,
    for_organization: Annotated[uuid.UUID | None, Query(alias="for")] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    cursor: Annotated[str | None, Query(max_length=2048)] = None,
) -> dict[str, Any]:
    keyset = "organization_parent_options"
    world_id = timeline_world_id(connection, access.timeline_id)
    after = decode_name_cursor(cursor, keyset)
    excluded = (
        descendant_ids(
            connection,
            table="world.organizations",
            pk="organization_id",
            parent_column="parent_organization_id",
            root_id=for_organization,
        )
        if for_organization is not None
        else set()
    )
    rows = list_reference_options(
        connection,
        world_id=world_id,
        type_codes=ORGANIZATION_ENTITY_TYPE_CODES,
        query_text=q.strip() if q and q.strip() else None,
        limit=limit,
        after=after,
        exclude_ids=excluded,
    )
    return reference_options_page(
        rows,
        limit=limit,
        keyset=keyset,
        item=lambda r: {
            "organization_id": str(r.entity_id),
            "name": r.name,
            "kind": r.entity_type_code,
            "canon_status": r.canon_status,
        },
    )


@router.post(_ORG, status_code=201)
def create_organization_endpoint(
    body: CreateOrganizationRequest,
    access: _Access,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    command_name = "create_organization"
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
    result = create_organization(
        connection,
        campaign_id=access.campaign_id,
        actor_user_id=access.user_id,
        kind_code=body.kind,
        name=body.name,
        summary=body.summary,
        public_description=body.public_description,
        internal_description=body.internal_description,
        parent_organization_id=body.parent_organization_id,
        headquarters_location_id=body.headquarters_location_id,
        religion_id=body.religion_id,
        typed_fields=body.typed_fields(),
    )
    audit_content_write(
        connection,
        result=result,
        command_name=command_name,
        access=access,
        correlation_id=correlation_id,
        reason=None,
    )
    response = _organization_response(connection, result, changed=True)
    finish_campaign_idempotency(connection, idem, status_code=201, body=response)
    return JSONResponse(status_code=201, content=response)


@router.get(_ORG + "/{organization_id}")
def get_organization_authoring_endpoint(
    organization_id: uuid.UUID, access: _Access, connection: _Conn
) -> dict[str, Any]:
    world_id = timeline_world_id(connection, access.timeline_id)
    view = get_organization_authoring(
        connection, world_id=world_id, organization_id=organization_id
    )
    if view is None:
        raise NotFoundError()
    return _organization_json(view)


@router.post(_ORG + "/{organization_id}/update")
def update_organization_endpoint(
    organization_id: uuid.UUID,
    body: UpdateOrganizationRequest,
    access: _Access,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    command_name = "update_organization"
    idem = start_campaign_idempotency(
        connection,
        actor_user_id=access.user_id,
        campaign_id=access.campaign_id,
        idempotency_key=idempotency_key,
        command_name=command_name,
        payload={"organization_id": str(organization_id), **body.model_dump(mode="json")},
        correlation_id=correlation_id,
    )
    if idem.replay is not None:
        return idem.replay
    result = update_organization(
        connection,
        campaign_id=access.campaign_id,
        organization_id=organization_id,
        actor_user_id=access.user_id,
        expected_row_version=body.expected_row_version,
        name=body.name,
        summary=body.summary,
        public_description=body.public_description,
        internal_description=body.internal_description,
        parent_organization_id=body.parent_organization_id,
        headquarters_location_id=body.headquarters_location_id,
        religion_id=body.religion_id,
        typed_fields=body.typed_fields(),
        change_note=body.change_note,
    )
    if result.changed:
        audit_content_write(
            connection,
            result=result,
            command_name=command_name,
            access=access,
            correlation_id=correlation_id,
            reason=clean_note(body.change_note),
        )
    response = _organization_response(connection, result, changed=result.changed)
    finish_campaign_idempotency(connection, idem, status_code=200, body=response)
    return response


def _organization_response(
    connection: Connection, result: ContentWriteResult, *, changed: bool
) -> dict[str, Any]:
    view = get_organization_authoring(
        connection, world_id=result.world_id, organization_id=result.entity_id
    )
    assert view is not None
    return _organization_json(view, changed=changed)


# --- Religions ---------------------------------------------------------------------------------


@router.get(_REL + "/options")
def religion_options_endpoint(access: _Access) -> dict[str, Any]:
    del access
    return {
        "can_create": True,
        "limits": {
            "name_max_length": NAME_MAX_LENGTH,
            "summary_max_length": DESCRIPTION_MAX_LENGTH,
            "pantheon_max_length": DESCRIPTION_FIELD_MAX_LENGTH,
            "change_note_max_length": REASON_MAX_LENGTH,
        },
    }


@router.get(_REL + "/reference-options")
def religion_reference_options_endpoint(
    access: _Access,
    connection: _Conn,
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    cursor: Annotated[str | None, Query(max_length=2048)] = None,
) -> dict[str, Any]:
    keyset = "religion_reference_options"
    world_id = timeline_world_id(connection, access.timeline_id)
    rows = list_reference_options(
        connection,
        world_id=world_id,
        type_codes={"religion"},
        query_text=q.strip() if q and q.strip() else None,
        limit=limit,
        after=decode_name_cursor(cursor, keyset),
    )
    return reference_options_page(
        rows,
        limit=limit,
        keyset=keyset,
        item=lambda r: {
            "religion_id": str(r.entity_id),
            "name": r.name,
            "canon_status": r.canon_status,
        },
    )


@router.post(_REL, status_code=201)
def create_religion_endpoint(
    body: CreateReligionRequest,
    access: _Access,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    command_name = "create_religion"
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
    result = create_religion(
        connection,
        campaign_id=access.campaign_id,
        actor_user_id=access.user_id,
        name=body.name,
        summary=body.summary,
        pantheon_structure=body.pantheon_structure,
    )
    audit_content_write(
        connection,
        result=result,
        command_name=command_name,
        access=access,
        correlation_id=correlation_id,
        reason=None,
    )
    response = _religion_response(connection, result, changed=True)
    finish_campaign_idempotency(connection, idem, status_code=201, body=response)
    return JSONResponse(status_code=201, content=response)


@router.get(_REL + "/{religion_id}")
def get_religion_authoring_endpoint(
    religion_id: uuid.UUID, access: _Access, connection: _Conn
) -> dict[str, Any]:
    world_id = timeline_world_id(connection, access.timeline_id)
    view = get_religion_authoring(connection, world_id=world_id, religion_id=religion_id)
    if view is None:
        raise NotFoundError()
    return _religion_json(view)


@router.post(_REL + "/{religion_id}/update")
def update_religion_endpoint(
    religion_id: uuid.UUID,
    body: UpdateReligionRequest,
    access: _Access,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    command_name = "update_religion"
    idem = start_campaign_idempotency(
        connection,
        actor_user_id=access.user_id,
        campaign_id=access.campaign_id,
        idempotency_key=idempotency_key,
        command_name=command_name,
        payload={"religion_id": str(religion_id), **body.model_dump(mode="json")},
        correlation_id=correlation_id,
    )
    if idem.replay is not None:
        return idem.replay
    result = update_religion(
        connection,
        campaign_id=access.campaign_id,
        religion_id=religion_id,
        actor_user_id=access.user_id,
        expected_row_version=body.expected_row_version,
        name=body.name,
        summary=body.summary,
        pantheon_structure=body.pantheon_structure,
        change_note=body.change_note,
    )
    if result.changed:
        audit_content_write(
            connection,
            result=result,
            command_name=command_name,
            access=access,
            correlation_id=correlation_id,
            reason=clean_note(body.change_note),
        )
    response = _religion_response(connection, result, changed=result.changed)
    finish_campaign_idempotency(connection, idem, status_code=200, body=response)
    return response


def _religion_response(
    connection: Connection, result: ContentWriteResult, *, changed: bool
) -> dict[str, Any]:
    view = get_religion_authoring(
        connection, world_id=result.world_id, religion_id=result.entity_id
    )
    assert view is not None
    return _religion_json(view, changed=changed)
