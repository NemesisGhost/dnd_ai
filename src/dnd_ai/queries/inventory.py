"""Audience-filtered effective character-inventory query.

`rules.item_definitions`/`world.item_instances` describe what an item is;
`campaign.item_state`/`.item_ownership`/`.inventory_entries` describe its
current condition, legal owner, and current possessor on a timeline
(docs/architecture/DATABASE_MODEL.md §11). There is no maintained
`campaign.character_inventory` index table; this module queries
`campaign.inventory_entries` directly and joins the item-level tables.

Audience filtering: definition-level facts (name, category, rarity) and
timeline state (quantity, condition, charges, equipped/destroyed, current
owner) are never described as secret anywhere in this schema, so they are
always returned once the caller is authorized to view the holder's
inventory at all. An item's *hidden mechanical properties*
(`rules.item_definitions.properties_jsonb`) are different:
`knowledge.item_identification` exists specifically to gate them per
knower. This first cut resolves identification from exactly one
perspective — the holder's own (`knower_entity_id = holder_entity_id`) —
rather than accepting an arbitrary caller-supplied knower, since "does
this authenticated user have standing to use a *different* character's
identification knowledge" is the same class of question `dnd_ai.api.
access.resolve_party_perspective`/`resolve_character_view_tier` already
answer for their own resources, and inventing a third variant here for a
case no caller has yet needed would be speculative. A caller holding
`canon.edit` (a GM) sees every item's full properties regardless of the
holder's own identification state.

This module is framework-free and performs no authorization of its own:
`reveal_all_properties` must already be an authorized decision (a resolved
`canon.edit` capability check) by the time it reaches here, and the caller
of this function is responsible for having already authorized viewing
`holder_entity_id`'s inventory at all (`dnd_ai.api.access.
resolve_character_view_tier`) — the same "authorization happens at the
API/access boundary, the query only filters" split every other query
module in this package follows.
"""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection, text

from dnd_ai.domain.errors import DomainAuthorizationError

_IDENTIFIED_LEVELS = frozenset({"fully_identified"})
_PARTIAL_LEVEL = "partially_identified"
_DEFAULT_IDENTIFICATION_LEVEL = "unidentified"


class InventoryHolderNotFoundError(DomainAuthorizationError):
    """Raised by `get_inventory_view()` for a nonexistent
    `holder_entity_id`, or one whose own world does not match the caller's
    `expected_world_id` — identically, so a caller can never distinguish
    "doesn't exist" from "belongs to a different world" (mirroring
    `dnd_ai.queries.dungeon.DungeonAreaNotFoundError`'s identical
    reasoning). The supplied holder/world ids are included only in the
    constructor's `detail` argument (`str(self)`), never in
    `safe_message`."""


@dataclass(frozen=True)
class InventoryItemView:
    item_instance_id: uuid.UUID
    display_name: str
    item_category_code: str
    rarity: str
    quantity: int
    condition_percentage: int | None
    charges_current: int | None
    charges_maximum: int | None
    is_equipped: bool
    is_destroyed: bool
    owner_entity_id: uuid.UUID | None
    identification_level: str
    properties: dict[str, Any] | None
    """The subset of `rules.item_definitions.properties_jsonb` currently
    revealed — the full definition when `identification_level ==
    'fully_identified'` (or the caller is a GM), the identification row's
    own `known_properties_jsonb` when `'partially_identified'`, and `None`
    otherwise."""
    name: str = ""
    """The instance's own name (a named sword), as opposed to its definition's `display_name`."""
    last_event_id: uuid.UUID | None = None
    """The item's optimistic token (`campaign.item_state.last_event_id`)."""
    is_published: bool = True
    """False for a draft or archived instance, which only a GM (`reveal_all_properties`) sees."""
    is_attuned: bool = False
    """Whether the holder is currently attuned to this item on the timeline: an open
    `campaign.item_attunements` row (`broken_world_time_id IS NULL`, the codebase's definition of
    active, as the attune/end-attunement commands and the item editor read it) for this timeline,
    this item and this holder. An ended attunement, another character's, and another timeline's
    all read `False`; nothing is inferred from the definition's attunement requirement."""


def get_inventory_view(
    connection: Connection,
    *,
    holder_entity_id: uuid.UUID,
    timeline_id: uuid.UUID,
    expected_world_id: uuid.UUID,
    reveal_all_properties: bool,
) -> tuple[InventoryItemView, ...]:
    """Every item `holder_entity_id` currently possesses
    (`campaign.inventory_entries.holder_entity_id`) on `timeline_id`, each
    with its identification-gated properties resolved from the holder's
    own `knowledge.item_identification` row. Raises
    `InventoryHolderNotFoundError` for a nonexistent holder or one
    belonging to a different world than `expected_world_id` (always the
    caller's own resolved-timeline world — `dnd_ai.api._shared.
    timeline_world_id`, never caller-supplied)."""
    holder_world_id = connection.execute(
        text("SELECT world_id FROM core.entities WHERE entity_id = :holder"),
        {"holder": holder_entity_id},
    ).scalar()

    if holder_world_id is None or holder_world_id != expected_world_id:
        raise InventoryHolderNotFoundError(
            f"holder {holder_entity_id} does not exist in world {expected_world_id} "
            f"(actual world: {holder_world_id})"
        )

    rows = connection.execute(
        text("""
            SELECT ii.item_instance_id, ie_ent.canonical_name AS instance_name,
                   idef.display_name, icat.code AS item_category_code,
                   idef.rarity, idef.properties_jsonb, ist.last_event_id,
                   (ie_cs.code = 'canon' AND ie_ls.code = 'active') AS is_published,
                   COALESCE(ist.quantity, 1) AS quantity, ist.condition_percentage,
                   ist.charges_current, ist.charges_maximum,
                   COALESCE(ist.is_equipped, false) AS is_equipped,
                   COALESCE(ist.is_destroyed, false) AS is_destroyed,
                   io.owner_entity_id,
                   COALESCE(idn.identification_level, :default_level) AS identification_level,
                   idn.known_properties_jsonb,
                   EXISTS (
                       SELECT 1 FROM campaign.item_attunements att
                       WHERE att.timeline_id = ie.timeline_id
                         AND att.item_instance_id = ie.item_instance_id
                         AND att.character_id = ie.holder_entity_id
                         AND att.broken_world_time_id IS NULL
                   ) AS is_attuned
            FROM campaign.inventory_entries ie
            JOIN world.item_instances ii ON ii.item_instance_id = ie.item_instance_id
            JOIN core.entities ie_ent ON ie_ent.entity_id = ii.item_instance_id
            JOIN core.canon_statuses ie_cs ON ie_cs.canon_status_id = ie_ent.canon_status_id
            JOIN core.lifecycle_statuses ie_ls
                 ON ie_ls.lifecycle_status_id = ie_ent.lifecycle_status_id
            JOIN rules.item_definitions idef ON idef.item_definition_id = ii.item_definition_id
            JOIN rules.item_categories icat ON icat.item_category_id = idef.item_category_id
            LEFT JOIN campaign.item_state ist
                   ON ist.timeline_id = ie.timeline_id AND ist.item_instance_id = ie.item_instance_id
            LEFT JOIN campaign.item_ownership io
                   ON io.timeline_id = ie.timeline_id AND io.item_instance_id = ie.item_instance_id
            LEFT JOIN knowledge.item_identification idn
                   ON idn.timeline_id = ie.timeline_id
                  AND idn.item_instance_id = ie.item_instance_id
                  AND idn.knower_entity_id = ie.holder_entity_id
            WHERE ie.timeline_id = :timeline AND ie.holder_entity_id = :holder
              AND (:gm OR (ie_cs.code = 'canon' AND ie_ls.code = 'active'))
            ORDER BY lower(ie_ent.canonical_name), ii.item_instance_id
        """),
        {
            "timeline": timeline_id,
            "holder": holder_entity_id,
            "default_level": _DEFAULT_IDENTIFICATION_LEVEL,
            "gm": reveal_all_properties,
        },
    ).mappings()

    items = []
    for row in rows:
        identification_level = row["identification_level"]
        if reveal_all_properties or identification_level in _IDENTIFIED_LEVELS:
            properties = row["properties_jsonb"]
        elif identification_level == _PARTIAL_LEVEL:
            properties = row["known_properties_jsonb"]
        else:
            properties = None

        items.append(
            InventoryItemView(
                item_instance_id=row["item_instance_id"],
                display_name=row["display_name"],
                item_category_code=row["item_category_code"],
                rarity=row["rarity"],
                quantity=row["quantity"],
                condition_percentage=row["condition_percentage"],
                charges_current=row["charges_current"],
                charges_maximum=row["charges_maximum"],
                is_equipped=row["is_equipped"],
                is_destroyed=row["is_destroyed"],
                owner_entity_id=row["owner_entity_id"],
                identification_level=identification_level,
                properties=properties,
                name=row["instance_name"],
                last_event_id=row["last_event_id"],
                is_published=bool(row["is_published"]),
                is_attuned=bool(row["is_attuned"]),
            )
        )

    return tuple(items)


@dataclass(frozen=True)
class RestrictedInventoryItemView:
    """The `inventory_only` projection of `InventoryItemView` (CP-6 / DR-2): what a reader holding
    `character.view_inventory` without the full character view may see. This is an allowlist, so a
    field added to `InventoryItemView` is withheld from this view until it is added here on purpose.

    Attunement (`is_attuned`) is part of the allowlist. Withheld: `condition_percentage`, `charges_current`/`charges_maximum` (item-instance mechanical
    state), `last_event_id` (the mutation token), `is_published` (a restricted reader never sees an
    unpublished instance), and `owner_entity_id` (replaced by `ownership`, so the id of an
    entity the reader may not be able to discover is not disclosed). GM-only instance fields such
    as `origin_notes` are not part of `InventoryItemView` at all.
    """

    item_instance_id: uuid.UUID
    name: str
    display_name: str
    item_category_code: str
    rarity: str
    quantity: int
    is_equipped: bool
    is_destroyed: bool
    is_attuned: bool
    ownership: str
    """`holder` when the legal owner is the character carrying the item, `other` when someone else
    owns what the character carries (custody without ownership), `none` when it has no owner."""
    identification_level: str
    properties: dict[str, Any] | None
    """Already identification-filtered by `get_inventory_view` (called with
    `reveal_all_properties=False`)."""


def restrict_inventory_view(
    items: tuple[InventoryItemView, ...], *, holder_entity_id: uuid.UUID
) -> tuple[RestrictedInventoryItemView, ...]:
    """Project `items` (read with `reveal_all_properties=False`, so draft/archived instances and
    unrevealed properties are already absent) onto the `inventory_only` allowlist."""
    restricted = []
    for item in items:
        if item.owner_entity_id is None:
            ownership = "none"
        elif item.owner_entity_id == holder_entity_id:
            ownership = "holder"
        else:
            ownership = "other"
        restricted.append(
            RestrictedInventoryItemView(
                item_instance_id=item.item_instance_id,
                name=item.name,
                display_name=item.display_name,
                item_category_code=item.item_category_code,
                rarity=item.rarity,
                quantity=item.quantity,
                is_equipped=item.is_equipped,
                is_destroyed=item.is_destroyed,
                is_attuned=item.is_attuned,
                ownership=ownership,
                identification_level=item.identification_level,
                properties=item.properties,
            )
        )
    return tuple(restricted)
