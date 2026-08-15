"""Effective character-inventory query (docs/PLAN.md Phase 10 deliverable
"query services for the effective dungeon, character, quest, relationship,
inventory, ... state required by the vertical slice").

`rules.item_definitions`/`world.item_instances` describe what an item is;
`campaign.item_state`/`.item_ownership`/`.inventory_entries` describe its
current condition, legal owner, and current possessor on a timeline
(docs/architecture/DATABASE_MODEL.md §11 — reconciliation note at §19.7's
sibling `campaign.character_inventory` entry: "Phase 9, which owns items,
should confirm whether a separate index table is actually warranted or
whether a view/query suffices." No `campaign.character_inventory` table
was ever built (migration 077 built the four tables above and
`knowledge.item_identification` only) — this module is that confirmation:
a direct query over `campaign.inventory_entries` joined to the item-level
tables, not a maintained index table.

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
            SELECT ii.item_instance_id, idef.display_name, icat.code AS item_category_code,
                   idef.rarity, idef.properties_jsonb,
                   COALESCE(ist.quantity, 1) AS quantity, ist.condition_percentage,
                   ist.charges_current, ist.charges_maximum,
                   COALESCE(ist.is_equipped, false) AS is_equipped,
                   COALESCE(ist.is_destroyed, false) AS is_destroyed,
                   io.owner_entity_id,
                   COALESCE(idn.identification_level, :default_level) AS identification_level,
                   idn.known_properties_jsonb
            FROM campaign.inventory_entries ie
            JOIN world.item_instances ii ON ii.item_instance_id = ie.item_instance_id
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
            ORDER BY ii.item_instance_id
        """),
        {
            "timeline": timeline_id,
            "holder": holder_entity_id,
            "default_level": _DEFAULT_IDENTIFICATION_LEVEL,
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
            )
        )

    return tuple(items)
