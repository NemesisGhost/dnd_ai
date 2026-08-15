"""Query endpoint over `dnd_ai.queries.knowledge` — Phase 10 workstream 18,
completing the named-domain list in "query services for the effective
dungeon, character, quest, relationship, inventory, encounter, and
knowledge state required by the vertical slice" (docs/PLAN.md Phase 10
deliverable list). Exposes `dnd_ai.queries.knowledge.get_knowledge_view`
over HTTP as `GET /campaigns/{campaign_id}/knowledge/{knowledge_item_id}`,
on the same already-delivered OIDC authentication, transaction management,
and access resolution every other router uses. No command endpoint exists
over `knowledge.*` yet — canon knowledge is currently written only as a
side effect of discovery/interaction commands, not through a dedicated
mutation endpoint — so this module is query-only, the same shape
`dnd_ai.api.dungeon` started from.

Authorization: requires `campaign.view` (the base gate every other read
endpoint in this phase uses), then the same GM/party-perspective split
`dnd_ai.api.dungeon` established: a caller holding `canon.edit` for this
exact `knowledge_item_id` (`access.has_capability(...,
knowledge_item_id=knowledge_item_id)` — never checked without a target,
which would skip any item-scoped `security.resource_grants` deny and let
a role-derived GM bypass an explicit, targeted restriction) sees the
item's own ground truth regardless of any party's belief; anyone else
must supply an authorized `character_id`/`party_id` pair
(`dnd_ai.api.access.resolve_party_perspective`, `character.view_knowledge`)
and sees only that party's own current belief
(`campaign.party_knowledge`) — never the ground truth. Both "no
perspective supplied" and "the authorized party has no belief about this
item" resolve to the identical fixed, non-disclosing 404
(`dnd_ai.queries.knowledge.KnowledgeNotAuthorizedError`) a nonexistent
item would, since a knowledge item's own existence can be sensitive.

This is a read: no idempotency key, no `audit.change_log` row, for the
same reasons `dnd_ai.api.dungeon`'s read endpoint has neither.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import Connection

from dnd_ai.domain.access import AccessContext
from dnd_ai.queries.knowledge import get_knowledge_view

from ._shared import timeline_world_id
from .access import require_campaign_capability, resolve_party_perspective
from .deps import get_connection

router = APIRouter(tags=["knowledge"])

_KNOWLEDGE_VIEW_CAPABILITY = "campaign.view"
_KNOWLEDGE_GROUND_TRUTH_CAPABILITY = "canon.edit"


# ---------------------------------------------------------------------------
# Response contracts
# ---------------------------------------------------------------------------


class KnowledgeResponse(BaseModel):
    knowledge_item_id: uuid.UUID
    knowledge_type_code: str
    statement: str
    truth_status_code: str | None
    sensitivity: str | None
    awareness_level: str | None
    confidence: int | None
    willing_to_share: bool | None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(
    "/campaigns/{campaign_id}/knowledge/{knowledge_item_id}",
    response_model=KnowledgeResponse,
    status_code=200,
)
def get_knowledge_endpoint(
    campaign_id: uuid.UUID,
    knowledge_item_id: uuid.UUID,
    access: Annotated[
        AccessContext, Depends(require_campaign_capability(_KNOWLEDGE_VIEW_CAPABILITY))
    ],
    connection: Annotated[Connection, Depends(get_connection)],
    character_id: uuid.UUID | None = None,
    party_id: uuid.UUID | None = None,
) -> KnowledgeResponse:
    include_ground_truth = access.has_capability(
        _KNOWLEDGE_GROUND_TRUTH_CAPABILITY,
        knowledge_item_id=knowledge_item_id,
    )
    authorized_party_id = (
        None
        if include_ground_truth
        else resolve_party_perspective(
            connection,
            access=access,
            campaign_id=campaign_id,
            character_id=character_id,
            party_id=party_id,
        )
    )

    view = get_knowledge_view(
        connection,
        knowledge_item_id=knowledge_item_id,
        timeline_id=access.timeline_id,
        expected_world_id=timeline_world_id(connection, access.timeline_id),
        party_id=authorized_party_id,
        include_ground_truth=include_ground_truth,
    )

    return KnowledgeResponse(
        knowledge_item_id=view.knowledge_item_id,
        knowledge_type_code=view.knowledge_type_code,
        statement=view.statement,
        truth_status_code=view.truth_status_code,
        sensitivity=view.sensitivity,
        awareness_level=view.awareness_level,
        confidence=view.confidence,
        willing_to_share=view.willing_to_share,
    )
