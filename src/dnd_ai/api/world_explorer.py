"""World Explorer read endpoints (docs/UI_DESIGN.md §5.4,
docs/PHASE13D_BACKEND_READINESS.md §3).

One unified, cursor-paginated entity search/browse
(`GET /campaigns/{campaign_id}/world/search`), one relationship list
(`GET /campaigns/{campaign_id}/world/relationships`), and typed detail
routes for the three entity-rooted categories that previously had no
detail route at all — religions, item instances, historical events — plus
a generic `world.locations` detail with containment breadcrumbs. Character,
organization, relationship, and dungeon-area *detail* already exist on
their own routers and are reused; those routers gain a targeted
`campaign.view` deny check in this same workstream so list and detail can
never disagree on which resources an audience may see (the disclosure
class the quest-detail route was hardened against in Phase 13D —
docs/PHASE13D_BACKEND_READINESS.md §4.2).

Every route requires the `campaign.view` role capability
(`dnd_ai.api.access.require_campaign_capability`), the read-only
counterpart every other query endpoint in this codebase uses. Visibility,
ordering, and pagination semantics are documented on
`dnd_ai.queries.world_explorer`. These are reads: no CSRF header, no
idempotency key, no `audit.change_log` row, no mutation.
"""

import uuid
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import Connection

from dnd_ai.domain.access import AccessContext
from dnd_ai.queries.world_explorer import (
    ENTITY_SEARCH_KEYSET,
    RELATIONSHIP_KEYSET,
    WORLD_CATEGORY_TYPE_CODES,
    CharacterVisibility,
    WorldEntityVisibility,
    get_event_view,
    get_item_view,
    get_location_view,
    get_religion_view,
    list_world_relationships,
    search_world_entities,
)

from ._shared import timeline_world_id
from .access import require_campaign_capability
from .deps import get_connection
from .pagination import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    build_page,
    decode_typed_cursor,
)

router = APIRouter(tags=["world-explorer"])

_VIEW_CAPABILITY = "campaign.view"
_GM_CAPABILITY = "canon.edit"

# The character-relationship capability tiers that make a character
# discoverable in the World Explorer (owner decision, 2026-09-09 — mirror
# the existing character-detail gate rather than invent a discovery table).
_DISCOVER_CAPABILITIES: tuple[str, ...] = (
    "character.discover",
    "character.view_summary",
    "character.view_full",
    _GM_CAPABILITY,
)

WorldCategory = Literal["location", "character", "organization", "religion", "item", "event"]

_MAX_QUERY_LEN = 200


# ---------------------------------------------------------------------------
# Visibility resolution
# ---------------------------------------------------------------------------


def resolve_world_character_visibility(access: AccessContext) -> CharacterVisibility:
    """Turn the caller's resolved `AccessContext` into the SQL-ready
    `CharacterVisibility` bundle — see that dataclass's docstring.

    `discover_all` is a pure baseline (role) check. `force_visible` /
    `force_hidden` are resolved per character for every character the
    caller has an explicit relationship or resource grant for, applying
    `AccessContext.has_capability`'s own deny-overrides-allow-overrides-
    baseline precedence per capability: a character with *any* surviving
    discover path is force-visible, one with *none* is force-hidden.
    """
    discover_all = any(access.has_capability(cap) for cap in _DISCOVER_CAPABILITIES)

    mentioned: set[uuid.UUID] = set(access.character_capabilities)
    for cap in _DISCOVER_CAPABILITIES:
        denied, allowed = access.resource_grant_targets(cap, "character_id")
        mentioned |= denied | allowed

    force_visible: set[uuid.UUID] = set()
    force_hidden: set[uuid.UUID] = set()
    for character_id in mentioned:
        if any(
            access.has_capability(cap, character_id=character_id) for cap in _DISCOVER_CAPABILITIES
        ):
            force_visible.add(character_id)
        else:
            force_hidden.add(character_id)

    return CharacterVisibility(
        discover_all=discover_all,
        force_visible=frozenset(force_visible),
        force_hidden=frozenset(force_hidden),
    )


def _campaign_view_denied_entity_ids(access: AccessContext) -> frozenset[uuid.UUID]:
    """Every entity the caller holds a `campaign.view` deny for — resolved
    across both the `entity_id` and `event_id` grant target columns, since
    an event is an entity and a deny may be recorded against either."""
    entity_denied, _ = access.resource_grant_targets(_VIEW_CAPABILITY, "entity_id")
    event_denied, _ = access.resource_grant_targets(_VIEW_CAPABILITY, "event_id")
    return entity_denied | event_denied


def resolve_world_entity_visibility(access: AccessContext) -> WorldEntityVisibility:
    """The full discoverability bundle for the caller — the same inputs
    `search_world_entities` applies, packaged so a *second* consumer (the
    relationship list and detail, Issue 1) decides "may this relationship
    name this participant" the identical way."""
    draft_denied, draft_allowed = access.resource_grant_targets(_GM_CAPABILITY, "event_id")
    return WorldEntityVisibility(
        campaign_view_denied_entity_ids=_campaign_view_denied_entity_ids(access),
        character_visibility=resolve_world_character_visibility(access),
        include_draft_events=access.has_capability(_GM_CAPABILITY),
        draft_event_allowed_ids=draft_allowed,
        draft_event_denied_ids=draft_denied,
    )


# ---------------------------------------------------------------------------
# Response contracts
# ---------------------------------------------------------------------------


class WorldEntityCardResponse(BaseModel):
    entity_id: uuid.UUID
    category: WorldCategory
    entity_type_code: str
    name: str
    summary: str | None


class WorldEntitySearchResponse(BaseModel):
    items: list[WorldEntityCardResponse]
    next_cursor: str | None


class RelationshipCardResponse(BaseModel):
    relationship_id: uuid.UUID
    relationship_type_code: str
    description: str | None
    participant_entity_ids: list[uuid.UUID]


class RelationshipListResponse(BaseModel):
    items: list[RelationshipCardResponse]
    next_cursor: str | None


class LocationCrumbResponse(BaseModel):
    location_id: uuid.UUID
    name: str
    location_type_code: str


class LocationDetailResponse(BaseModel):
    location_id: uuid.UUID
    name: str
    summary: str | None
    location_type_code: str
    parent_location_id: uuid.UUID | None
    breadcrumbs: list[LocationCrumbResponse]
    population: int | None
    building_use: str | None
    danger_level: int | None
    is_searched: bool | None
    is_destroyed: bool | None
    alarm_level: int | None
    condition_notes: str | None


class ReligionDetailResponse(BaseModel):
    religion_id: uuid.UUID
    name: str
    summary: str | None
    pantheon_structure: str | None
    serving_organization_ids: list[uuid.UUID]


class ItemDetailResponse(BaseModel):
    item_instance_id: uuid.UUID
    name: str
    summary: str | None
    item_definition_id: uuid.UUID | None
    origin_notes: str | None
    quantity: int | None
    condition_percentage: int | None
    charges_current: int | None
    charges_maximum: int | None
    is_equipped: bool | None
    is_destroyed: bool | None


class EventParticipantResponse(BaseModel):
    entity_id: uuid.UUID
    role_code: str | None


class EventLocationResponse(BaseModel):
    location_id: uuid.UUID
    role: str | None


class EventDetailResponse(BaseModel):
    event_id: uuid.UUID
    name: str
    summary: str | None
    event_type_code: str
    event_status_code: str
    world_time_id: uuid.UUID
    details: str | None
    session_id: uuid.UUID | None
    participants: list[EventParticipantResponse]
    locations: list[EventLocationResponse]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(
    "/campaigns/{campaign_id}/world/search",
    response_model=WorldEntitySearchResponse,
    status_code=200,
)
def search_world_entities_endpoint(
    # campaign_id is bound from the path by require_campaign_capability's own
    # dependency; this handler never needs it directly.
    access: Annotated[AccessContext, Depends(require_campaign_capability(_VIEW_CAPABILITY))],
    connection: Annotated[Connection, Depends(get_connection)],
    category: Annotated[list[WorldCategory] | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=_MAX_QUERY_LEN)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    cursor: Annotated[str | None, Query()] = None,
) -> WorldEntitySearchResponse:
    """Type-filtered, text-searchable, cursor-paginated browse over every
    authorized entity-rooted World Explorer category. `category` may be
    repeated (`?category=location&category=item`); omitted means every
    category. `q` is a bounded case-insensitive substring match over name
    and summary. An empty result — including for an authorized search with
    no visible matches — returns `items: []`, never an existence hint."""
    categories = list(category) if category else list(WORLD_CATEGORY_TYPE_CODES)
    type_codes: list[str] = []
    for cat in categories:
        type_codes.extend(WORLD_CATEGORY_TYPE_CODES[cat])

    keyset = decode_typed_cursor(cursor, keyset=ENTITY_SEARCH_KEYSET, fields=("str", "uuid"))
    after_name = cast(str, keyset[0]) if keyset is not None else None
    after_entity_id = cast(uuid.UUID, keyset[1]) if keyset is not None else None

    draft_denied, draft_allowed = access.resource_grant_targets(_GM_CAPABILITY, "event_id")

    cards = search_world_entities(
        connection,
        world_id=timeline_world_id(connection, access.timeline_id),
        timeline_id=access.timeline_id,
        category_type_codes=type_codes,
        query_text=q,
        campaign_view_denied_entity_ids=_campaign_view_denied_entity_ids(access),
        character_visibility=resolve_world_character_visibility(access),
        include_draft_events=access.has_capability(_GM_CAPABILITY),
        draft_event_allowed_ids=draft_allowed,
        draft_event_denied_ids=draft_denied,
        limit=limit,
        after_name=after_name,
        after_entity_id=after_entity_id,
    )

    page = build_page(
        cards,
        limit=limit,
        keyset=ENTITY_SEARCH_KEYSET,
        cursor_key=lambda card: [card.name_sort, card.entity_id],
    )
    return WorldEntitySearchResponse(
        items=[
            WorldEntityCardResponse(
                entity_id=card.entity_id,
                category=card.category,  # type: ignore[arg-type]
                entity_type_code=card.entity_type_code,
                name=card.name,
                summary=card.summary,
            )
            for card in page.items
        ],
        next_cursor=page.next_cursor,
    )


@router.get(
    "/campaigns/{campaign_id}/world/relationships",
    response_model=RelationshipListResponse,
    status_code=200,
)
def list_world_relationships_endpoint(
    access: Annotated[AccessContext, Depends(require_campaign_capability(_VIEW_CAPABILITY))],
    connection: Annotated[Connection, Depends(get_connection)],
    q: Annotated[str | None, Query(max_length=_MAX_QUERY_LEN)] = None,
    type: Annotated[str | None, Query(max_length=64)] = None,
    related_entity_id: Annotated[uuid.UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    cursor: Annotated[str | None, Query()] = None,
) -> RelationshipListResponse:
    """Relationships in the campaign's world, cursor-paginated. A
    relationship is returned only when every participant is independently
    discoverable by the caller (Issue 1 — a card never carries a
    participant id the audience has no route to, and this route agrees with
    `GET /campaigns/{id}/relationships/{id}`). Filtered further by `q`
    (substring over description), `type`, and `related_entity_id`. See
    `dnd_ai.queries.world_explorer.list_world_relationships`."""
    keyset = decode_typed_cursor(cursor, keyset=RELATIONSHIP_KEYSET, fields=("uuid",))
    after_relationship_id = cast(uuid.UUID, keyset[0]) if keyset is not None else None

    cards = list_world_relationships(
        connection,
        world_id=timeline_world_id(connection, access.timeline_id),
        timeline_id=access.timeline_id,
        query_text=q,
        relationship_type_code=type,
        related_entity_id=related_entity_id,
        visibility=resolve_world_entity_visibility(access),
        limit=limit,
        after_relationship_id=after_relationship_id,
    )

    page = build_page(
        cards,
        limit=limit,
        keyset=RELATIONSHIP_KEYSET,
        cursor_key=lambda card: [card.relationship_id],
    )
    return RelationshipListResponse(
        items=[
            RelationshipCardResponse(
                relationship_id=card.relationship_id,
                relationship_type_code=card.relationship_type_code,
                description=card.description,
                participant_entity_ids=list(card.participant_entity_ids),
            )
            for card in page.items
        ],
        next_cursor=page.next_cursor,
    )


@router.get(
    "/campaigns/{campaign_id}/world/locations/{location_id}",
    response_model=LocationDetailResponse,
    status_code=200,
)
def get_location_endpoint(
    location_id: uuid.UUID,
    access: Annotated[AccessContext, Depends(require_campaign_capability(_VIEW_CAPABILITY))],
    connection: Annotated[Connection, Depends(get_connection)],
) -> LocationDetailResponse:
    view = get_location_view(
        connection,
        location_id=location_id,
        timeline_id=access.timeline_id,
        expected_world_id=timeline_world_id(connection, access.timeline_id),
        denied_entity_ids=_campaign_view_denied_entity_ids(access),
    )
    return LocationDetailResponse(
        location_id=view.location_id,
        name=view.name,
        summary=view.summary,
        location_type_code=view.location_type_code,
        parent_location_id=view.parent_location_id,
        breadcrumbs=[
            LocationCrumbResponse(
                location_id=c.location_id, name=c.name, location_type_code=c.location_type_code
            )
            for c in view.breadcrumbs
        ],
        population=view.population,
        building_use=view.building_use,
        danger_level=view.danger_level,
        is_searched=view.is_searched,
        is_destroyed=view.is_destroyed,
        alarm_level=view.alarm_level,
        condition_notes=view.condition_notes,
    )


@router.get(
    "/campaigns/{campaign_id}/world/religions/{religion_id}",
    response_model=ReligionDetailResponse,
    status_code=200,
)
def get_religion_endpoint(
    religion_id: uuid.UUID,
    access: Annotated[AccessContext, Depends(require_campaign_capability(_VIEW_CAPABILITY))],
    connection: Annotated[Connection, Depends(get_connection)],
) -> ReligionDetailResponse:
    view = get_religion_view(
        connection,
        religion_id=religion_id,
        expected_world_id=timeline_world_id(connection, access.timeline_id),
        denied_entity_ids=_campaign_view_denied_entity_ids(access),
    )
    return ReligionDetailResponse(
        religion_id=view.religion_id,
        name=view.name,
        summary=view.summary,
        pantheon_structure=view.pantheon_structure,
        serving_organization_ids=list(view.serving_organization_ids),
    )


@router.get(
    "/campaigns/{campaign_id}/world/items/{item_instance_id}",
    response_model=ItemDetailResponse,
    status_code=200,
)
def get_item_endpoint(
    item_instance_id: uuid.UUID,
    access: Annotated[AccessContext, Depends(require_campaign_capability(_VIEW_CAPABILITY))],
    connection: Annotated[Connection, Depends(get_connection)],
) -> ItemDetailResponse:
    view = get_item_view(
        connection,
        item_instance_id=item_instance_id,
        timeline_id=access.timeline_id,
        expected_world_id=timeline_world_id(connection, access.timeline_id),
        denied_entity_ids=_campaign_view_denied_entity_ids(access),
    )
    return ItemDetailResponse(
        item_instance_id=view.item_instance_id,
        name=view.name,
        summary=view.summary,
        item_definition_id=view.item_definition_id,
        origin_notes=view.origin_notes,
        quantity=view.quantity,
        condition_percentage=view.condition_percentage,
        charges_current=view.charges_current,
        charges_maximum=view.charges_maximum,
        is_equipped=view.is_equipped,
        is_destroyed=view.is_destroyed,
    )


@router.get(
    "/campaigns/{campaign_id}/world/events/{event_id}",
    response_model=EventDetailResponse,
    status_code=200,
)
def get_event_endpoint(
    event_id: uuid.UUID,
    access: Annotated[AccessContext, Depends(require_campaign_capability(_VIEW_CAPABILITY))],
    connection: Annotated[Connection, Depends(get_connection)],
) -> EventDetailResponse:
    draft_denied, draft_allowed = access.resource_grant_targets(_GM_CAPABILITY, "event_id")
    view = get_event_view(
        connection,
        event_id=event_id,
        timeline_id=access.timeline_id,
        expected_world_id=timeline_world_id(connection, access.timeline_id),
        denied_entity_ids=_campaign_view_denied_entity_ids(access),
        include_draft=access.has_capability(_GM_CAPABILITY),
        draft_allowed=event_id in draft_allowed,
        draft_denied=event_id in draft_denied,
        character_visibility=resolve_world_character_visibility(access),
    )
    return EventDetailResponse(
        event_id=view.event_id,
        name=view.name,
        summary=view.summary,
        event_type_code=view.event_type_code,
        event_status_code=view.event_status_code,
        world_time_id=view.world_time_id,
        details=view.details,
        session_id=view.session_id,
        participants=[
            EventParticipantResponse(entity_id=p.entity_id, role_code=p.role_code)
            for p in view.participants
        ],
        locations=[
            EventLocationResponse(location_id=loc.location_id, role=loc.role)
            for loc in view.locations
        ],
    )
