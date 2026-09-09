"""Audience-filtered browse/search/detail reads for the Phase 13D World
Explorer screen (docs/UI_DESIGN.md §5.4, docs/PHASE13D_BACKEND_READINESS.md
§3/§9).

Every existing world read in this codebase is a single-resource "get by
id" (`dnd_ai.queries.dungeon`/`.character`/`.organization`/`.relationship`);
none can *enumerate* or *search*. This module adds exactly the enumeration
and search the World Explorer needs, plus typed detail views for the three
entity-rooted categories that had no detail route at all
(`world.religions`, `world.item_instances`, `narrative.events`) and for a
non-dungeon `world.locations` row. Character, organization, relationship,
and dungeon-area detail already exist and are reused unchanged (their
routes gain a targeted-deny check for list/detail agreement — see
`dnd_ai.api.world_explorer`).

## Visibility model (owner decision, 2026-09-09)

The schema has **no entity-level discovery/knowledge gating** for world
locations, organizations, items, historical events, relationships, or
religions — discovery state exists only for dungeon structural children
(`is_hidden` + `knowledge.party_discoveries`) and `knowledge.knowledge_items`
(the Knowledge screen's own domain). So World Explorer visibility
deliberately **mirrors what the existing single-resource detail endpoints
already disclose**, rather than inventing a speculative discovery
mechanism:

- **Baseline** for every category is the `campaign.view` role capability
  already required to reach any of these routes.
- **Per-resource `campaign.view` deny** (`security.resource_grants`,
  `entity_id` target — resolved by the caller via
  `AccessContext.resource_grant_targets("campaign.view", "entity_id")`)
  removes a specific entity from *both* the list and its own detail route,
  the same deny-overrides-baseline precedence
  `dnd_ai.queries.quest`/`.session` already apply for their own targets.
  There is no `allowed` counterpart: baseline visibility is already `True`
  for every `campaign.view` holder, so there is no default-hidden state
  for an explicit allow to add back (same reasoning
  `list_campaign_quests`/`list_campaign_sessions` document).
- **GM-only *fields*** (e.g. `world.organizations.internal_description`,
  `campaign.relationship_state` subjective rows) stay gated by `canon.edit`
  inside the reused detail queries — unchanged.
- **Characters** (NPCs and player characters) are the one category with a
  stricter existing gate: the character-relationship capability tiers this
  codebase's own seed data already defines
  (`character.discover`/`.view_summary`/`.view_full`, or `canon.edit`).
  A character appears in the World Explorer only when the caller holds one
  of those for it — campaign-wide (a role capability) or per-character (a
  `security.membership_character_relationships` row, or a
  `security.resource_grants` allow), minus any per-character deny. See
  `dnd_ai.api.world_explorer.resolve_world_character_visibility`.
- **Events** additionally honor `narrative.events` timeline scope and the
  `draft`/`voided` status split `dnd_ai.queries.summary` already
  established: a `voided` event is never listed for anyone; a `draft`
  event only for a `canon.edit` caller (or one holding a `canon.edit`
  allow targeting that `event_id`), never for a plain `campaign.view`
  member.

All filtering happens **in SQL, before pagination and before the response
is built** — no route ever fetches unfiltered rows and hides them
afterward. An inaccessible or nonexistent detail resource raises the same
fixed, non-disclosing `WorldResourceNotFoundError` (mapped to the
repository's standard 404), so "doesn't exist", "different world",
"different timeline" (events), and "denied to you" are indistinguishable.

## Ordering and pagination

Entity-rooted browse results are ordered `(lower(canonical_name),
entity_id)` — deterministic, stable across inserts/deletes, and the exact
keyset the opaque `dnd_ai.api.pagination` cursor carries. Relationships
(not entity-rooted, no name) order by `relationship_id` alone. No total
count is computed for any browse result (docs/UI_DESIGN.md §9).

`world.relationships` visibility mirrors the existing relationship detail
route (participants are a structural fact visible to any `campaign.view`
caller) rather than hiding an edge whose node the caller cannot discover —
see `list_world_relationships` for the reasoning and the follow-up note.

This module is framework-free and performs no authorization of its own:
every visibility parameter (`campaign_view_denied_entity_ids`,
`character_*`, `include_draft_events`, ...) must already be an authorized,
resolved decision by the time it reaches here — the same split every other
query module in this package follows.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy import Connection, text

from dnd_ai.domain.errors import DomainAuthorizationError

# ---------------------------------------------------------------------------
# Category vocabulary
# ---------------------------------------------------------------------------

# The World Explorer's browsable categories -> the `core.entity_types.code`
# values that belong to each. Every code here is a real seeded row
# (`database/seeds`/migration 004+); a category maps to the CTI leaf types
# that share one browse/detail treatment. `relationship` is deliberately
# absent — `world.relationships` is not entity-rooted and has its own
# dedicated list function below.
WORLD_CATEGORY_TYPE_CODES: dict[str, tuple[str, ...]] = {
    "location": (
        "location",
        "settlement",
        "building",
        "dungeon",
        "dungeon_area",
        "plane",
        "continent",
        "nation",
        "region",
        "district",
        "geographic_feature",
        "realm",
    ),
    "character": ("character", "npc", "player_character"),
    "organization": (
        "organization",
        "business",
        "government",
        "religious_organization",
        "military_unit",
        "political_faction",
    ),
    "religion": ("religion",),
    "item": ("item_instance",),
    "event": ("event",),
}

WORLD_CATEGORIES: tuple[str, ...] = tuple(WORLD_CATEGORY_TYPE_CODES)

_CHARACTER_TYPE_CODES: tuple[str, ...] = WORLD_CATEGORY_TYPE_CODES["character"]

# The entity-code -> category reverse map, for tagging a result row.
_TYPE_CODE_TO_CATEGORY: dict[str, str] = {
    code: category for category, codes in WORLD_CATEGORY_TYPE_CODES.items() for code in codes
}

# Cursor keyset names (bind a cursor to the endpoint family that issued it
# — see `dnd_ai.api.pagination`).
ENTITY_SEARCH_KEYSET = "world_entities"
RELATIONSHIP_KEYSET = "world_relationships"


class WorldResourceNotFoundError(DomainAuthorizationError):
    """Raised by every `get_*_view` in this module for a nonexistent
    resource, one in a different world (or, for an event, a different
    timeline) than the caller's own, or one removed by a targeted
    `campaign.view` deny — all identically, so a caller can never
    distinguish which applied (docs/architecture/DATABASE_MODEL.md §19.7,
    the same reasoning `dnd_ai.queries.dungeon.DungeonAreaNotFoundError`
    and the quest/session detail routes already apply). The supplied ids
    appear only in the constructor's `detail` (`str(self)`), never in
    `safe_message`."""


# ---------------------------------------------------------------------------
# Character-visibility parameter bundle
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CharacterVisibility:
    """The already-resolved answer to "which characters may this caller
    discover in the World Explorer" — computed once per request by
    `dnd_ai.api.world_explorer.resolve_world_character_visibility` from the
    caller's `AccessContext`, then pushed into SQL so character rows are
    filtered before pagination.

    `discover_all` is `True` when the caller holds any of
    `character.discover`/`.view_summary`/`.view_full`/`canon.edit` as a
    *baseline* (role) capability — it can then see every character in the
    world except those in `force_hidden`. `force_visible`/`force_hidden`
    carry the per-character resolution for every character the caller has
    an explicit relationship or resource grant for (deny-overrides-allow-
    overrides-baseline already applied per capability): a character in
    `force_visible` is shown regardless of `discover_all`, one in
    `force_hidden` is hidden regardless of it.
    """

    discover_all: bool
    force_visible: frozenset[uuid.UUID] = field(default_factory=frozenset)
    force_hidden: frozenset[uuid.UUID] = field(default_factory=frozenset)


# ---------------------------------------------------------------------------
# Unified entity search / browse
# ---------------------------------------------------------------------------


# `core.entities.canonical_name` is up to 500 characters (migration 004's
# `ck_entities_canonical_name_length`); a name of non-ASCII characters
# escapes to ~6 bytes each in the opaque `dnd_ai.api.pagination` cursor,
# so carrying a whole name could push the encoded cursor past that
# module's size bound. Search therefore sorts by, and carries in the
# cursor, only a bounded lower-cased prefix of the name. `(prefix,
# entity_id)` is still a strict total order — `entity_id` is unique — so
# keyset paging over it never skips or repeats a row; the SQL computes the
# prefix (`lower(left(canonical_name, N))`) and it is echoed back verbatim
# so the value compared on the next request is exactly what the previous
# page emitted. (The same treatment `dnd_ai.queries.knowledge_browse`
# applies to its statement sort key.)
_NAME_SORT_PREFIX = 200


@dataclass(frozen=True)
class WorldEntityCard:
    """One compact, uniform search/browse result — enough to render a card
    and link to the typed detail route, nothing sensitive. `name`/`summary`
    are `core.entities` fields a `campaign.view` caller is already entitled
    to for any entity that survived the visibility filter.

    `name_sort` is the bounded, case-folded ordering key the SQL produced
    for this row — the value the pagination cursor carries, never
    recomputed in Python (see `_NAME_SORT_PREFIX`)."""

    entity_id: uuid.UUID
    category: str
    entity_type_code: str
    name: str
    summary: str | None
    name_sort: str


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search_world_entities(
    connection: Connection,
    *,
    world_id: uuid.UUID,
    timeline_id: uuid.UUID,
    category_type_codes: Sequence[str],
    query_text: str | None,
    campaign_view_denied_entity_ids: frozenset[uuid.UUID],
    character_visibility: CharacterVisibility,
    include_draft_events: bool,
    draft_event_allowed_ids: frozenset[uuid.UUID],
    draft_event_denied_ids: frozenset[uuid.UUID],
    limit: int,
    after_name: str | None,
    after_entity_id: uuid.UUID | None,
) -> tuple[WorldEntityCard, ...]:
    """Up to `limit + 1` visible world entities of the requested categories,
    ordered `(lower(left(canonical_name, N)), entity_id)` — a bounded name
    prefix (`_NAME_SORT_PREFIX`) plus the unique entity id, a strict total
    order that keeps the pagination cursor small regardless of name length.
    The caller passes `limit + 1` and uses the presence of the extra row as
    the "has next page" signal (`dnd_ai.api.pagination.build_page`).

    `after_name`/`after_entity_id` are the keyset from the previous page's
    last row (both `None` on the first page). `query_text`, when set, is a
    bounded case-insensitive substring match over `canonical_name` and
    `summary` only — never over `core.entity_names` aliases, some of which
    (`secret`, `mistaken`) would themselves be a disclosure.
    """
    like_pattern = f"%{_escape_like(query_text)}%" if query_text else None
    params: dict[str, object] = {
        "world_id": world_id,
        "timeline_id": timeline_id,
        "type_codes": list(category_type_codes),
        "character_codes": list(_CHARACTER_TYPE_CODES),
        "like_pattern": like_pattern,
        "cv_denied": list(campaign_view_denied_entity_ids),
        "discover_all": character_visibility.discover_all,
        "char_visible": list(character_visibility.force_visible),
        "char_hidden": list(character_visibility.force_hidden),
        "include_draft": include_draft_events,
        "draft_allowed": list(draft_event_allowed_ids),
        "draft_denied": list(draft_event_denied_ids),
        "limit_plus_one": limit + 1,
        "after_name": after_name,
        "after_entity_id": after_entity_id,
        "has_cursor": after_name is not None and after_entity_id is not None,
    }

    rows = connection.execute(
        text(f"""
            SELECT e.entity_id, e.canonical_name, e.summary, et.code AS entity_type_code,
                   lower(left(e.canonical_name, {_NAME_SORT_PREFIX})) AS name_sort
            FROM core.entities e
            JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id
            LEFT JOIN narrative.events ev ON ev.event_id = e.entity_id
            LEFT JOIN narrative.event_statuses es
                   ON es.event_status_id = ev.event_status_id
            WHERE e.world_id = :world_id
              AND et.code = ANY(CAST(:type_codes AS text[]))
              AND (
                    CAST(:like_pattern AS text) IS NULL
                    OR e.canonical_name ILIKE CAST(:like_pattern AS text) ESCAPE '\\'
                    OR e.summary ILIKE CAST(:like_pattern AS text) ESCAPE '\\'
                  )
              AND NOT (e.entity_id = ANY(CAST(:cv_denied AS uuid[])))
              AND (
                CASE
                  WHEN et.code = ANY(CAST(:character_codes AS text[])) THEN
                    (CAST(:discover_all AS boolean)
                     AND NOT (e.entity_id = ANY(CAST(:char_hidden AS uuid[]))))
                    OR e.entity_id = ANY(CAST(:char_visible AS uuid[]))
                  WHEN et.code = 'event' THEN
                    ev.event_id IS NOT NULL
                    AND ev.timeline_id = :timeline_id
                    AND es.code <> 'voided'
                    AND (
                      es.code <> 'draft'
                      OR (
                        NOT (e.entity_id = ANY(CAST(:draft_denied AS uuid[])))
                        AND (
                          CAST(:include_draft AS boolean)
                          OR e.entity_id = ANY(CAST(:draft_allowed AS uuid[]))
                        )
                      )
                    )
                  ELSE TRUE
                END
              )
              AND (
                    NOT CAST(:has_cursor AS boolean)
                    OR (lower(left(e.canonical_name, {_NAME_SORT_PREFIX})), e.entity_id)
                       > (CAST(:after_name AS text), CAST(:after_entity_id AS uuid))
                  )
            ORDER BY lower(left(e.canonical_name, {_NAME_SORT_PREFIX})), e.entity_id
            LIMIT :limit_plus_one
        """),
        params,
    ).mappings()

    return tuple(
        WorldEntityCard(
            entity_id=row["entity_id"],
            category=_TYPE_CODE_TO_CATEGORY[row["entity_type_code"]],
            entity_type_code=row["entity_type_code"],
            name=row["canonical_name"],
            summary=row["summary"],
            name_sort=row["name_sort"],
        )
        for row in rows
    )


# ---------------------------------------------------------------------------
# Relationships list (not entity-rooted)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RelationshipCard:
    relationship_id: uuid.UUID
    relationship_type_code: str
    description: str | None
    participant_entity_ids: tuple[uuid.UUID, ...]


def list_world_relationships(
    connection: Connection,
    *,
    world_id: uuid.UUID,
    query_text: str | None,
    relationship_type_code: str | None,
    related_entity_id: uuid.UUID | None,
    limit: int,
    after_relationship_id: uuid.UUID | None,
) -> tuple[RelationshipCard, ...]:
    """Up to `limit + 1` relationships in the world, ordered by
    `relationship_id`.

    **Visibility (owner decision, 2026-09-09 — "mirror existing detail
    endpoints"):** the existing `GET /campaigns/{id}/relationships/{id}`
    route already returns a relationship and its full participant list to
    *any* `campaign.view` caller — `dnd_ai.queries.relationship`'s own
    docstring: "who is related to whom is a structural fact, not a
    subjective judgment"; only the per-participant *subjective* state is
    GM-gated. This list mirrors that exactly: every relationship in the
    campaign's world, filtered only by `query_text` (case-insensitive
    substring over `description`), `relationship_type_code`, and
    `related_entity_id`. `world.relationships` is not entity-rooted and has
    no `security.resource_grants` target column, so there is no per-
    relationship deny to apply. The `participant_entity_ids` a card carries
    are the same ids the detail route already discloses. (A future product
    decision to hide edges whose nodes a caller cannot discover would be a
    change to the *existing* relationship contract, not just this list —
    tracked as a consideration in docs/PHASE13D_BACKEND_READINESS.md.)
    """
    params: dict[str, object] = {
        "world_id": world_id,
        "like_pattern": f"%{_escape_like(query_text)}%" if query_text else None,
        "type_code": relationship_type_code,
        "related_entity_id": related_entity_id,
        "limit_plus_one": limit + 1,
        "after_relationship_id": after_relationship_id,
        "has_cursor": after_relationship_id is not None,
    }

    rows = connection.execute(
        text("""
            SELECT r.relationship_id, rt.code AS type_code, r.description
            FROM world.relationships r
            JOIN world.relationship_types rt
              ON rt.relationship_type_id = r.relationship_type_id
            WHERE r.world_id = :world_id
              AND (CAST(:type_code AS text) IS NULL OR rt.code = CAST(:type_code AS text))
              AND (
                    CAST(:like_pattern AS text) IS NULL
                    OR r.description ILIKE CAST(:like_pattern AS text) ESCAPE '\\'
                  )
              AND (
                    NOT CAST(:has_cursor AS boolean)
                    OR r.relationship_id > CAST(:after_relationship_id AS uuid)
                  )
              AND (
                CAST(:related_entity_id AS uuid) IS NULL
                OR EXISTS (
                  SELECT 1 FROM world.relationship_participants rp
                  WHERE rp.relationship_id = r.relationship_id
                    AND rp.entity_id = CAST(:related_entity_id AS uuid)
                )
              )
            ORDER BY r.relationship_id
            LIMIT :limit_plus_one
        """),
        params,
    ).mappings()

    cards: list[RelationshipCard] = []
    for row in rows:
        participant_ids = tuple(
            connection.execute(
                text("""
                    SELECT entity_id FROM world.relationship_participants
                    WHERE relationship_id = :r
                    ORDER BY relationship_participant_id
                """),
                {"r": row["relationship_id"]},
            ).scalars()
        )
        cards.append(
            RelationshipCard(
                relationship_id=row["relationship_id"],
                relationship_type_code=row["type_code"],
                description=row["description"],
                participant_entity_ids=participant_ids,
            )
        )
    return tuple(cards)


# ---------------------------------------------------------------------------
# Detail: location (any world.locations row, including a dungeon area's
# basic view — structural children stay on the dedicated dungeon-areas
# route)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LocationCrumb:
    location_id: uuid.UUID
    name: str
    location_type_code: str


@dataclass(frozen=True)
class LocationDetailView:
    location_id: uuid.UUID
    name: str
    summary: str | None
    location_type_code: str
    parent_location_id: uuid.UUID | None
    """`None` when the containing location is itself denied to the caller —
    the breadcrumb trail is truncated there rather than naming a hidden
    ancestor."""
    breadcrumbs: tuple[LocationCrumb, ...]
    population: int | None
    building_use: str | None
    danger_level: int | None
    # Current timeline state (`campaign.location_state`), None when no row.
    is_searched: bool | None
    is_destroyed: bool | None
    alarm_level: int | None
    condition_notes: str | None


def get_location_view(
    connection: Connection,
    *,
    location_id: uuid.UUID,
    timeline_id: uuid.UUID,
    expected_world_id: uuid.UUID,
    denied_entity_ids: frozenset[uuid.UUID],
) -> LocationDetailView:
    """One `world.locations` row's definition, its subtype fields, current
    `campaign.location_state`, and its containment breadcrumbs (authorized
    ancestors only). Raises `WorldResourceNotFoundError` for a nonexistent
    location, one in another world, or one in `denied_entity_ids`."""
    if location_id in denied_entity_ids:
        raise WorldResourceNotFoundError(f"location {location_id} denied to caller")

    row = (
        connection.execute(
            text("""
                SELECT l.location_id, e.world_id, e.canonical_name, e.summary,
                       et.code AS location_type_code, l.parent_location_id,
                       s.population, b.building_use, d.danger_level,
                       ls.is_searched, ls.is_destroyed, ls.alarm_level, ls.condition_notes
                FROM world.locations l
                JOIN core.entities e ON e.entity_id = l.location_id
                JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id
                LEFT JOIN world.settlements s ON s.settlement_id = l.location_id
                LEFT JOIN world.buildings b ON b.building_id = l.location_id
                LEFT JOIN world.dungeons d ON d.dungeon_id = l.location_id
                LEFT JOIN campaign.location_state ls
                       ON ls.timeline_id = :timeline AND ls.location_id = l.location_id
                WHERE l.location_id = :location
            """),
            {"location": location_id, "timeline": timeline_id},
        )
        .mappings()
        .one_or_none()
    )
    if row is None or row["world_id"] != expected_world_id:
        raise WorldResourceNotFoundError(f"location {location_id} not in world {expected_world_id}")

    breadcrumbs: list[LocationCrumb] = []
    parent_id = row["parent_location_id"]
    parent_visible = parent_id is not None and parent_id not in denied_entity_ids
    current = parent_id
    seen: set[uuid.UUID] = {location_id}
    while current is not None and current not in denied_entity_ids and current not in seen:
        seen.add(current)
        ancestor = (
            connection.execute(
                text("""
                    SELECT l.location_id, e.canonical_name, et.code AS location_type_code,
                           l.parent_location_id
                    FROM world.locations l
                    JOIN core.entities e ON e.entity_id = l.location_id
                    JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id
                    WHERE l.location_id = :location
                """),
                {"location": current},
            )
            .mappings()
            .one_or_none()
        )
        if ancestor is None:
            break
        breadcrumbs.append(
            LocationCrumb(
                location_id=ancestor["location_id"],
                name=ancestor["canonical_name"],
                location_type_code=ancestor["location_type_code"],
            )
        )
        current = ancestor["parent_location_id"]
    breadcrumbs.reverse()  # root -> immediate parent

    return LocationDetailView(
        location_id=row["location_id"],
        name=row["canonical_name"],
        summary=row["summary"],
        location_type_code=row["location_type_code"],
        parent_location_id=parent_id if parent_visible else None,
        breadcrumbs=tuple(breadcrumbs),
        population=row["population"],
        building_use=row["building_use"],
        danger_level=row["danger_level"],
        is_searched=row["is_searched"],
        is_destroyed=row["is_destroyed"],
        alarm_level=row["alarm_level"],
        condition_notes=row["condition_notes"],
    )


# ---------------------------------------------------------------------------
# Detail: religion
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReligionDetailView:
    religion_id: uuid.UUID
    name: str
    summary: str | None
    pantheon_structure: str | None
    serving_organization_ids: tuple[uuid.UUID, ...]
    """`world.religious_organizations` rows pointing at this religion whose
    organization entity is not `campaign.view`-denied to the caller."""


def get_religion_view(
    connection: Connection,
    *,
    religion_id: uuid.UUID,
    expected_world_id: uuid.UUID,
    denied_entity_ids: frozenset[uuid.UUID],
) -> ReligionDetailView:
    if religion_id in denied_entity_ids:
        raise WorldResourceNotFoundError(f"religion {religion_id} denied to caller")
    row = (
        connection.execute(
            text("""
                SELECT r.religion_id, e.world_id, e.canonical_name, e.summary,
                       r.pantheon_structure
                FROM world.religions r
                JOIN core.entities e ON e.entity_id = r.religion_id
                WHERE r.religion_id = :religion
            """),
            {"religion": religion_id},
        )
        .mappings()
        .one_or_none()
    )
    if row is None or row["world_id"] != expected_world_id:
        raise WorldResourceNotFoundError(f"religion {religion_id} not in world {expected_world_id}")

    serving = tuple(
        connection.execute(
            text("""
                SELECT ro.religious_organization_id
                FROM world.religious_organizations ro
                WHERE ro.religion_id = :religion
                  AND NOT (ro.religious_organization_id = ANY(CAST(:denied AS uuid[])))
                ORDER BY ro.religious_organization_id
            """),
            {"religion": religion_id, "denied": list(denied_entity_ids)},
        ).scalars()
    )

    return ReligionDetailView(
        religion_id=row["religion_id"],
        name=row["canonical_name"],
        summary=row["summary"],
        pantheon_structure=row["pantheon_structure"],
        serving_organization_ids=serving,
    )


# ---------------------------------------------------------------------------
# Detail: item instance
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ItemDetailView:
    item_instance_id: uuid.UUID
    name: str
    summary: str | None
    item_definition_id: uuid.UUID | None
    origin_notes: str | None
    # Current `campaign.item_state` (None when no row on this timeline).
    quantity: int | None
    condition_percentage: int | None
    charges_current: int | None
    charges_maximum: int | None
    is_equipped: bool | None
    is_destroyed: bool | None


def get_item_view(
    connection: Connection,
    *,
    item_instance_id: uuid.UUID,
    timeline_id: uuid.UUID,
    expected_world_id: uuid.UUID,
    denied_entity_ids: frozenset[uuid.UUID],
) -> ItemDetailView:
    """One `world.item_instances` row plus its current `campaign.item_state`.
    Ownership/inventory (who currently holds it) is deliberately deferred —
    it needs its own audience design (docs/PHASE13D_BACKEND_READINESS.md
    §9.3) and no World Explorer bullet requires it for the MVP."""
    if item_instance_id in denied_entity_ids:
        raise WorldResourceNotFoundError(f"item {item_instance_id} denied to caller")
    row = (
        connection.execute(
            text("""
                SELECT ii.item_instance_id, e.world_id, e.canonical_name, e.summary,
                       ii.item_definition_id, ii.origin_notes,
                       ist.quantity, ist.condition_percentage, ist.charges_current,
                       ist.charges_maximum, ist.is_equipped, ist.is_destroyed
                FROM world.item_instances ii
                JOIN core.entities e ON e.entity_id = ii.item_instance_id
                LEFT JOIN campaign.item_state ist
                       ON ist.timeline_id = :timeline
                      AND ist.item_instance_id = ii.item_instance_id
                WHERE ii.item_instance_id = :item
            """),
            {"item": item_instance_id, "timeline": timeline_id},
        )
        .mappings()
        .one_or_none()
    )
    if row is None or row["world_id"] != expected_world_id:
        raise WorldResourceNotFoundError(
            f"item {item_instance_id} not in world {expected_world_id}"
        )
    return ItemDetailView(
        item_instance_id=row["item_instance_id"],
        name=row["canonical_name"],
        summary=row["summary"],
        item_definition_id=row["item_definition_id"],
        origin_notes=row["origin_notes"],
        quantity=row["quantity"],
        condition_percentage=row["condition_percentage"],
        charges_current=row["charges_current"],
        charges_maximum=row["charges_maximum"],
        is_equipped=row["is_equipped"],
        is_destroyed=row["is_destroyed"],
    )


# ---------------------------------------------------------------------------
# Detail: historical event
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EventParticipantView:
    entity_id: uuid.UUID
    role_code: str | None


@dataclass(frozen=True)
class EventLocationView:
    location_id: uuid.UUID
    role: str | None


@dataclass(frozen=True)
class EventDetailView:
    event_id: uuid.UUID
    name: str
    summary: str | None
    event_type_code: str
    event_status_code: str
    world_time_id: uuid.UUID
    details: str | None
    session_id: uuid.UUID | None
    participants: tuple[EventParticipantView, ...]
    locations: tuple[EventLocationView, ...]


def get_event_view(
    connection: Connection,
    *,
    event_id: uuid.UUID,
    timeline_id: uuid.UUID,
    expected_world_id: uuid.UUID,
    denied_entity_ids: frozenset[uuid.UUID],
    include_draft: bool,
    draft_allowed: bool,
    draft_denied: bool,
    character_visibility: CharacterVisibility,
) -> EventDetailView:
    """One `narrative.events` row visible to the caller: same timeline, not
    `voided`, and — for a `draft` — only with `include_draft`/`draft_allowed`
    and not `draft_denied`. Participants and event locations are each
    independently filtered (a `campaign.view`-denied entity, or an
    undiscoverable character, is omitted from the participant list without
    a placeholder). Raises `WorldResourceNotFoundError` otherwise."""
    if event_id in denied_entity_ids:
        raise WorldResourceNotFoundError(f"event {event_id} denied to caller")
    row = (
        connection.execute(
            text("""
                SELECT ev.event_id, e.world_id, e.canonical_name, e.summary,
                       et.code AS event_type_code, es.code AS event_status_code,
                       ev.timeline_id, ev.world_time_id, ev.details, ev.session_id
                FROM narrative.events ev
                JOIN core.entities e ON e.entity_id = ev.event_id
                JOIN narrative.event_types et ON et.event_type_id = ev.event_type_id
                JOIN narrative.event_statuses es ON es.event_status_id = ev.event_status_id
                WHERE ev.event_id = :event
            """),
            {"event": event_id},
        )
        .mappings()
        .one_or_none()
    )
    if (
        row is None
        or row["world_id"] != expected_world_id
        or row["timeline_id"] != timeline_id
        or row["event_status_code"] == "voided"
    ):
        raise WorldResourceNotFoundError(f"event {event_id} not visible in this campaign")
    if row["event_status_code"] == "draft" and not (
        draft_allowed or (include_draft and not draft_denied)
    ):
        raise WorldResourceNotFoundError(f"draft event {event_id} not visible to caller")

    participants = tuple(
        EventParticipantView(entity_id=p["participant_entity_id"], role_code=p["role_code"])
        for p in connection.execute(
            text("""
                SELECT ep.participant_entity_id, pr.code AS role_code
                FROM narrative.event_participants ep
                JOIN core.entities pe ON pe.entity_id = ep.participant_entity_id
                JOIN core.entity_types pet ON pet.entity_type_id = pe.entity_type_id
                LEFT JOIN narrative.event_participant_roles pr
                       ON pr.event_participant_role_id = ep.participant_role_id
                WHERE ep.event_id = :event
                  AND NOT (ep.participant_entity_id = ANY(CAST(:denied AS uuid[])))
                  AND (
                    NOT (pet.code = ANY(:character_codes))
                    OR (:discover_all AND NOT (pe.entity_id = ANY(CAST(:char_hidden AS uuid[]))))
                    OR pe.entity_id = ANY(CAST(:char_visible AS uuid[]))
                  )
                ORDER BY ep.event_participant_id
            """),
            {
                "event": event_id,
                "denied": list(denied_entity_ids),
                "character_codes": list(_CHARACTER_TYPE_CODES),
                "discover_all": character_visibility.discover_all,
                "char_hidden": list(character_visibility.force_hidden),
                "char_visible": list(character_visibility.force_visible),
            },
        ).mappings()
    )

    locations = tuple(
        EventLocationView(location_id=loc["location_id"], role=loc["event_location_role"])
        for loc in connection.execute(
            text("""
                SELECT el.location_id, el.event_location_role
                FROM narrative.event_locations el
                WHERE el.event_id = :event
                  AND NOT (el.location_id = ANY(CAST(:denied AS uuid[])))
                ORDER BY el.event_location_id
            """),
            {"event": event_id, "denied": list(denied_entity_ids)},
        ).mappings()
    )

    return EventDetailView(
        event_id=row["event_id"],
        name=row["canonical_name"],
        summary=row["summary"],
        event_type_code=row["event_type_code"],
        event_status_code=row["event_status_code"],
        world_time_id=row["world_time_id"],
        details=row["details"],
        session_id=row["session_id"],
        participants=participants,
        locations=locations,
    )
