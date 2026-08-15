"""Query endpoint over `dnd_ai.queries.character` — Phase 10 workstream 13,
continuing "query services for the effective dungeon, character, quest,
relationship, inventory, encounter, and knowledge state required by the
vertical slice" (docs/PLAN.md Phase 10 deliverable list) into the character
domain after workstream 12's dungeon-area query. Exposes
`dnd_ai.queries.character.get_character_view` over HTTP as
`GET /campaigns/{campaign_id}/characters/{character_id}`, on the same
already-delivered OIDC authentication, transaction management, and access
resolution every other router uses.

Authorization: requires the `campaign.view` role capability in the target
campaign (the same base gate `dnd_ai.api.dungeon` uses), then a second,
resource-scoped decision specific to this endpoint: how much detail about
*this* character the caller may see. `dnd_ai.api.access.
resolve_character_view_tier` returns `True` (full mechanical detail — hit
points, conditions, resources, current location) for a caller holding
`canon.edit` (a GM) or `character.view_full` for this exact `character_id`,
`False` (name/species/size only) for one holding only `character.
view_summary`, and raises a fixed, non-disclosing 404 for a caller holding
neither — identical to a nonexistent character, so a caller can never learn
whether a character they have no relationship to even exists. This mirrors
`dnd_ai.api.dungeon`'s GM/party-perspective split: a capability tier
decided from the resolved `AccessContext`, not a query parameter, and never
downgraded by a caller simply omitting one.

Cross-campaign/world character ownership: `character.characters` carries no
`campaign_id` at all (world-scoped, like the dungeon/item/quest/
relationship domains) — `get_character_view` itself asserts the
character's own `core.entities.world_id` matches the caller's
resolved-timeline world (`dnd_ai.api._shared.timeline_world_id`, never
caller-supplied) before returning anything, raising
`CharacterNotFoundError` (a fixed, non-disclosing 404) identically for a
nonexistent character or one in a different world.

This is a read: no idempotency key, no `audit.change_log` row (a routine,
already-authorized character read is not "sensitive" in that table's
documented sense — see `dnd_ai.api.dungeon`'s identical reasoning) and no
mutation of any kind.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import Connection

from dnd_ai.domain.access import AccessContext
from dnd_ai.queries.character import get_character_view

from ._shared import timeline_world_id
from .access import require_campaign_capability, resolve_character_view_tier
from .deps import get_connection

router = APIRouter(tags=["characters"])

# The base campaign-membership gate — the same capability
# dnd_ai.api.dungeon requires for its own read endpoint.
_CHARACTER_VIEW_CAPABILITY = "campaign.view"


# ---------------------------------------------------------------------------
# Response contracts
# ---------------------------------------------------------------------------


class CharacterConditionResponse(BaseModel):
    condition_code: str
    source_description: str | None


class CharacterResourceResponse(BaseModel):
    resource_code: str
    current_amount: int
    maximum_amount: int


class CharacterResponse(BaseModel):
    character_id: uuid.UUID
    name: str
    species_code: str
    size_category: str
    # None on every field below when the caller was authorized only for
    # the summary tier (dnd_ai.api.access.resolve_character_view_tier).
    current_hit_points: int | None
    maximum_hit_points: int | None
    temporary_hit_points: int | None
    exhaustion_level: int | None
    death_save_successes: int | None
    death_save_failures: int | None
    current_location_id: uuid.UUID | None
    conditions: list[CharacterConditionResponse] | None
    resources: list[CharacterResourceResponse] | None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(
    "/campaigns/{campaign_id}/characters/{character_id}",
    response_model=CharacterResponse,
    status_code=200,
)
def get_character_endpoint(
    character_id: uuid.UUID,
    # campaign_id is not otherwise used in this body — require_campaign_
    # capability's own returned dependency callable declares campaign_id
    # itself and binds it from the URL path independently, the same way
    # every other capability-gated route's path parameter resolves.
    access: Annotated[
        AccessContext, Depends(require_campaign_capability(_CHARACTER_VIEW_CAPABILITY))
    ],
    connection: Annotated[Connection, Depends(get_connection)],
) -> CharacterResponse:
    include_full = resolve_character_view_tier(access, character_id=character_id)

    view = get_character_view(
        connection,
        character_id=character_id,
        timeline_id=access.timeline_id,
        expected_world_id=timeline_world_id(connection, access.timeline_id),
        include_full=include_full,
    )

    return CharacterResponse(
        character_id=view.character_id,
        name=view.name,
        species_code=view.species_code,
        size_category=view.size_category,
        current_hit_points=view.current_hit_points,
        maximum_hit_points=view.maximum_hit_points,
        temporary_hit_points=view.temporary_hit_points,
        exhaustion_level=view.exhaustion_level,
        death_save_successes=view.death_save_successes,
        death_save_failures=view.death_save_failures,
        current_location_id=view.current_location_id,
        conditions=(
            None
            if view.conditions is None
            else [
                CharacterConditionResponse(
                    condition_code=c.condition_code, source_description=c.source_description
                )
                for c in view.conditions
            ]
        ),
        resources=(
            None
            if view.resources is None
            else [
                CharacterResourceResponse(
                    resource_code=r.resource_code,
                    current_amount=r.current_amount,
                    maximum_amount=r.maximum_amount,
                )
                for r in view.resources
            ]
        ),
    )
