"""Query endpoints over `dnd_ai.queries.dungeon` — Phase 10 workstream 12,
the first slice of "query services for the effective dungeon, character,
quest, relationship, inventory, encounter, and knowledge state required by
the vertical slice" (docs/PLAN.md Phase 10 deliverable list) after
workstreams 5-10 delivered every command endpoint the same scenario needs.
Exposes `dnd_ai.queries.dungeon.get_dungeon_area_view` over HTTP as
`GET /campaigns/{campaign_id}/dungeon-areas/{dungeon_area_id}`, on the same
already-delivered OIDC authentication, transaction management, and access
resolution every command router uses.

Authorization: requires the `campaign.view` role capability in the target
campaign — the read-only counterpart to every command router's `canon.edit`
requirement, and the capability this codebase's own seed data
(`database/seeds/security.capabilities.yaml`) names for exactly this
purpose. Unlike every command router so far, this endpoint's *response
shape* also depends on the resolved `AccessContext`: a caller who
additionally holds `canon.edit` (a GM) receives every structural child of
the area regardless of `is_hidden`; anyone else receives only what their
party has discovered (`dnd_ai.queries.dungeon`'s own audience-filtering
contract) — the GM/player/observer distinction docs/PLAN.md §25 step 15
requires of this vertical slice's summary and detail reads.

Party scope: an optional `party_id` query parameter selects whose
discoveries filter the response for a non-GM caller (`party_id` omitted is
a safe default — nothing is treated as discovered, so every hidden child is
excluded). Before it reaches the query, `party_id` is validated against the
URL's own `campaign_id`
(`dnd_ai.commands._shared.validate_campaign_party`) — the same guard
`dnd_ai.api.quests` already applies to a caller-supplied `party_id`, and
for the identical reason: `knowledge.party_discoveries` is scoped by
`timeline_id` alone, so an unvalidated `party_id` belonging to a different,
same-timeline campaign would otherwise leak that other party's discoveries
to a caller who was never authorized for it.

Cross-campaign/world area ownership: neither `world.dungeon_areas` nor its
structural children carry a `campaign_id` at all (world-scoped, like the
item/quest/relationship domains) — `dnd_ai.queries.dungeon.
get_dungeon_area_view` itself asserts the area's own `core.entities.
world_id` matches the caller's resolved-timeline world
(`dnd_ai.api._shared.timeline_world_id`, never caller-supplied) before
returning anything, raising `DungeonAreaNotFoundError` (a fixed,
non-disclosing 404) for a nonexistent area or one in a different world —
identically, so a caller can never distinguish the two.

This is a read: no idempotency key, no `audit.change_log` row (that table's
own documented scope is login-linked identity changes, role/access changes,
sensitive reads, and writes — a routine dungeon-area read for an already
campaign-scoped, `campaign.view`-authorized member is not "sensitive" in
that sense) and no mutation of any kind.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import Connection

from dnd_ai.commands._shared import validate_campaign_party
from dnd_ai.domain.access import AccessContext
from dnd_ai.queries.dungeon import get_dungeon_area_view

from ._shared import timeline_world_id
from .access import require_campaign_capability
from .deps import get_connection

router = APIRouter(tags=["dungeon"])

# The read-only counterpart to every command router's canon.edit
# requirement — see this module's docstring.
_DUNGEON_VIEW_CAPABILITY = "campaign.view"

# A caller additionally holding this capability sees every structural
# child of the area regardless of is_hidden (GM view) — see this module's
# docstring.
_DUNGEON_MANAGE_CAPABILITY = "canon.edit"


# ---------------------------------------------------------------------------
# Response contracts
# ---------------------------------------------------------------------------


class DungeonAreaFeatureResponse(BaseModel):
    area_feature_id: uuid.UUID
    feature_type: str | None
    description: str | None
    is_hidden: bool
    is_destroyed: bool
    condition_notes: str | None


class DungeonAreaHazardResponse(BaseModel):
    area_hazard_id: uuid.UUID
    hazard_type: str | None
    description: str | None
    severity: int | None
    is_hidden: bool
    hazard_status_code: str | None


class DungeonAreaInteractableResponse(BaseModel):
    area_interactable_id: uuid.UUID
    interactable_type: str | None
    description: str | None
    is_hidden: bool
    interactable_status_code: str | None


class DungeonAreaConnectionResponse(BaseModel):
    area_connection_id: uuid.UUID
    connection_type_code: str
    other_dungeon_area_id: uuid.UUID
    direction: str
    is_one_way: bool
    is_hidden: bool
    description: str | None
    connection_status_code: str | None


class DungeonAreaResponse(BaseModel):
    dungeon_area_id: uuid.UUID
    name: str
    area_type: str | None
    dimensions: str | None
    environmental_properties: str | None
    is_searched: bool
    is_destroyed: bool
    alarm_level: int
    condition_notes: str | None
    features: list[DungeonAreaFeatureResponse]
    hazards: list[DungeonAreaHazardResponse]
    interactables: list[DungeonAreaInteractableResponse]
    connections: list[DungeonAreaConnectionResponse]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(
    "/campaigns/{campaign_id}/dungeon-areas/{dungeon_area_id}",
    response_model=DungeonAreaResponse,
    status_code=200,
)
def get_dungeon_area_endpoint(
    campaign_id: uuid.UUID,
    dungeon_area_id: uuid.UUID,
    access: Annotated[
        AccessContext, Depends(require_campaign_capability(_DUNGEON_VIEW_CAPABILITY))
    ],
    connection: Annotated[Connection, Depends(get_connection)],
    party_id: uuid.UUID | None = None,
) -> DungeonAreaResponse:
    validate_campaign_party(connection, campaign_id=campaign_id, party_id=party_id)

    view = get_dungeon_area_view(
        connection,
        dungeon_area_id=dungeon_area_id,
        timeline_id=access.timeline_id,
        expected_world_id=timeline_world_id(connection, access.timeline_id),
        party_id=party_id,
        include_hidden=access.has_capability(_DUNGEON_MANAGE_CAPABILITY),
    )

    return DungeonAreaResponse(
        dungeon_area_id=view.dungeon_area_id,
        name=view.name,
        area_type=view.area_type,
        dimensions=view.dimensions,
        environmental_properties=view.environmental_properties,
        is_searched=view.is_searched,
        is_destroyed=view.is_destroyed,
        alarm_level=view.alarm_level,
        condition_notes=view.condition_notes,
        features=[
            DungeonAreaFeatureResponse(
                area_feature_id=f.area_feature_id,
                feature_type=f.feature_type,
                description=f.description,
                is_hidden=f.is_hidden,
                is_destroyed=f.is_destroyed,
                condition_notes=f.condition_notes,
            )
            for f in view.features
        ],
        hazards=[
            DungeonAreaHazardResponse(
                area_hazard_id=h.area_hazard_id,
                hazard_type=h.hazard_type,
                description=h.description,
                severity=h.severity,
                is_hidden=h.is_hidden,
                hazard_status_code=h.hazard_status_code,
            )
            for h in view.hazards
        ],
        interactables=[
            DungeonAreaInteractableResponse(
                area_interactable_id=i.area_interactable_id,
                interactable_type=i.interactable_type,
                description=i.description,
                is_hidden=i.is_hidden,
                interactable_status_code=i.interactable_status_code,
            )
            for i in view.interactables
        ],
        connections=[
            DungeonAreaConnectionResponse(
                area_connection_id=c.area_connection_id,
                connection_type_code=c.connection_type_code,
                other_dungeon_area_id=c.other_dungeon_area_id,
                direction=c.direction,
                is_one_way=c.is_one_way,
                is_hidden=c.is_hidden,
                description=c.description,
                connection_status_code=c.connection_status_code,
            )
            for c in view.connections
        ],
    )
