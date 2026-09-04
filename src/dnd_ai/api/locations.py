"""Audience-filtered, searchable, keyset-paginated location list endpoint —
the backend for the portal's World Explorer "browse authorized locations
and dungeons" MVP slice (Phase 13D, docs/UI_DESIGN.md §5.4).

Exposes `dnd_ai.queries.location.list_campaign_locations` over HTTP as
`GET /campaigns/{campaign_id}/locations`, on the same already-delivered
browser-session/OIDC authentication (`dnd_ai.api.auth`), transaction
management (`dnd_ai.api.deps`), and access resolution (`dnd_ai.api.access`,
`dnd_ai.domain.access`) every other query router in this package uses —
this route introduces no second authorization implementation.

Authorization: requires the `campaign.view` role capability in the target
campaign (`dnd_ai.api.access.require_campaign_capability`), the same base
gate `dnd_ai.api.dungeon`/`.characters`/`.quests`/`.sessions` already use.
Re-resolved fresh on every request, like every other route built on
`require_campaign_capability`. Beyond that baseline, three further layers
apply per row (see `dnd_ai.queries.location`'s own docstring for the full
precedence): a per-location `campaign.view` resource-grant deny excludes
it outright; a caller canonical-truth-authorized for a given location (a
baseline `canon.edit` holder not specifically denied it, or one
specifically granted `canon.edit` for it) sees it regardless of discovery;
otherwise a location gated by a `knowledge.knowledge_items` row naming it
(`subject_entity_id`) is included only once the caller's authorized party
has discovered it. A caller holding baseline `canon.edit` (a GM) never
resolves a party perspective at all — the same "GM sees canonical truth,
not one party's subjective view" rule `dnd_ai.api.quests`/`.dungeon`
already apply, kept consistent here so a GM is never required to hold a
`character.view_knowledge` relationship just to browse. `character_id`/
`party_id` are optional query parameters authorized through `dnd_ai.api.
access.resolve_party_perspective`, identical to every other party-scoped
read route in this package — a caller-supplied `party_id` is never trusted
on its own, matching that function's own docstring.

Pagination: deterministic keyset pagination over `(lower(canonical_name),
location_id)`, never offset-based — see `dnd_ai.queries.location`'s own
docstring for the ordering/cursor contract. `limit` is bounded to
`[1, MAX_PAGE_SIZE]`; an out-of-range value is an ordinary domain
`ValueError`, mapped by the existing generic handler
(`dnd_ai.api.errors`) to a fixed 400 `validation_failed` response — the
same contract a malformed `cursor` (via `dnd_ai.queries.location.
decode_location_cursor`) already uses. No total result count is ever
computed or returned — see that module's docstring for why.

This is a read: no idempotency key, no `audit.change_log` row, for the
same reasons every other query router in this package has neither.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import Connection

from dnd_ai.domain.access import AccessContext
from dnd_ai.queries.location import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    decode_location_cursor,
    list_campaign_locations,
)

from ._shared import timeline_world_id
from .access import require_campaign_capability, resolve_party_perspective
from .deps import get_connection

router = APIRouter(tags=["locations"])

# The base gate every other read endpoint in this package uses.
_LOCATION_VIEW_CAPABILITY = "campaign.view"

# A caller additionally holding this (baseline, or per-location via a
# resource grant) sees canonical truth regardless of discovery — see this
# module's own docstring and dnd_ai.queries.location's precedence rule.
_LOCATION_MANAGE_CAPABILITY = "canon.edit"


# ---------------------------------------------------------------------------
# Response contracts
# ---------------------------------------------------------------------------


class LocationListItemResponse(BaseModel):
    location_id: uuid.UUID
    name: str
    entity_type_code: str
    summary: str | None
    # None either because this location has no parent, or because its
    # parent exists but is not itself authorized for this caller — the two
    # cases are indistinguishable in the response, matching every other
    # non-disclosure rule in this codebase (dnd_ai.queries.location's own
    # docstring, "Parent disclosure").
    parent_location_id: uuid.UUID | None
    parent_name: str | None


class LocationListResponse(BaseModel):
    items: list[LocationListItemResponse]
    # None once no further authorized rows remain. Deliberately no total
    # count field — see dnd_ai.queries.location's own docstring.
    next_cursor: str | None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(
    "/campaigns/{campaign_id}/locations",
    response_model=LocationListResponse,
    status_code=200,
)
def list_locations_endpoint(
    campaign_id: uuid.UUID,
    access: Annotated[
        AccessContext, Depends(require_campaign_capability(_LOCATION_VIEW_CAPABILITY))
    ],
    connection: Annotated[Connection, Depends(get_connection)],
    entity_type: str | None = None,
    q: str | None = None,
    character_id: uuid.UUID | None = None,
    party_id: uuid.UUID | None = None,
    cursor: str | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
) -> LocationListResponse:
    if not (1 <= limit <= MAX_PAGE_SIZE):
        raise ValueError(f"limit must be between 1 and {MAX_PAGE_SIZE}")

    # decode_location_cursor raises ValueError for anything malformed —
    # left to propagate to the existing generic handler unchanged, per
    # this module's own docstring.
    after = None if cursor is None else decode_location_cursor(cursor)

    # A caller holding baseline canon.edit (a GM) never resolves a party
    # perspective — see this module's own docstring.
    is_gm = access.has_capability(_LOCATION_MANAGE_CAPABILITY)
    authorized_party_id = (
        None
        if is_gm
        else resolve_party_perspective(
            connection,
            access=access,
            campaign_id=campaign_id,
            character_id=character_id,
            party_id=party_id,
        )
    )

    # Baseline campaign.view is already established for every row by
    # require_campaign_capability above (uniform across the whole
    # campaign), so only a targeted deny can ever change that outcome for
    # one specific location — matching dnd_ai.api.sessions/.quests' own
    # list-endpoint precedent, no allowed-set counterpart needed here.
    denied_view_entity_ids, _allowed_view_entity_ids = access.resource_grant_targets(
        _LOCATION_VIEW_CAPABILITY, field_name="entity_id"
    )
    denied_canon_edit_entity_ids, allowed_canon_edit_entity_ids = access.resource_grant_targets(
        _LOCATION_MANAGE_CAPABILITY, field_name="entity_id"
    )

    page = list_campaign_locations(
        connection,
        world_id=timeline_world_id(connection, access.timeline_id),
        timeline_id=access.timeline_id,
        party_id=authorized_party_id,
        baseline_canon_edit=is_gm,
        denied_view_entity_ids=denied_view_entity_ids,
        denied_canon_edit_entity_ids=denied_canon_edit_entity_ids,
        allowed_canon_edit_entity_ids=allowed_canon_edit_entity_ids,
        entity_type_code=entity_type,
        search_text=q,
        after=after,
        limit=limit,
    )

    return LocationListResponse(
        items=[
            LocationListItemResponse(
                location_id=item.location_id,
                name=item.name,
                entity_type_code=item.entity_type_code,
                summary=item.summary,
                parent_location_id=item.parent_location_id,
                parent_name=item.parent_name,
            )
            for item in page.items
        ],
        next_cursor=page.next_cursor,
    )
