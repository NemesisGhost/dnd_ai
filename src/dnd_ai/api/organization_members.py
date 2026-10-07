"""Organization members read (Phase 15 checkpoint 15.3A-2b, decision D-19).

    GET /campaigns/{id}/organizations/{organization_id}/members

`campaign.view`. An editor (`canon.edit`) sees every stint, private and archived ones included,
and the choices for the organization's operational status; everyone else sees the active, public
members they can independently discover. Memberships are authored through the relationship
endpoints (kind `membership`) and the status through the existing organization status route.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import Connection

from dnd_ai.domain.access import AccessContext
from dnd_ai.queries.entity_lifecycle import lifecycle_hidden_entity_ids
from dnd_ai.queries.organization_members import list_organization_members

from ._shared import timeline_world_id
from .access import require_campaign_capability
from .deps import get_connection
from .errors import NotFoundError
from .world_explorer import resolve_world_entity_visibility

router = APIRouter(tags=["organization-members"])

_VIEW = "campaign.view"
_MANAGE = "canon.edit"


@router.get("/campaigns/{campaign_id}/organizations/{organization_id}/members")
def list_members_endpoint(
    organization_id: uuid.UUID,
    access: Annotated[AccessContext, Depends(require_campaign_capability(_VIEW))],
    connection: Annotated[Connection, Depends(get_connection)],
) -> dict[str, Any]:
    if not access.has_capability(_VIEW, entity_id=organization_id):
        raise NotFoundError()
    world_id = timeline_world_id(connection, access.timeline_id)
    editor = access.has_capability(_MANAGE, entity_id=organization_id)
    if organization_id in lifecycle_hidden_entity_ids(
        connection,
        world_id=world_id,
        mode="reference",
        viewer_user_id=access.user_id,
        can_edit_canon=editor,
    ):
        raise NotFoundError()
    result = list_organization_members(
        connection,
        organization_id=organization_id,
        world_id=world_id,
        timeline_id=access.timeline_id,
        visibility=resolve_world_entity_visibility(access, connection),
        include_private=editor,
    )
    if result is None:
        raise NotFoundError()
    return {
        "organization_id": str(result.organization_id),
        "status": result.status,
        "can_edit": editor,
        "status_choices": [{"value": v, "label": label} for v, label in result.status_choices],
        "members": [
            {
                "relationship_id": str(m.relationship_id),
                "member_entity_id": str(m.member_entity_id),
                "member_name": m.member_name,
                "member_type_code": m.member_type_code,
                "role": m.role,
                "rank": m.rank,
                "is_public": m.is_public,
                "started": m.started,
                "ended": m.ended,
                "current": m.current,
                "lifecycle_status": m.lifecycle_status,
                "row_version": m.row_version,
            }
            for m in result.members
        ],
    }
