"""Editor read models for item instances (Phase 15 checkpoint 15.3B-1b).

`canon.edit` only. The view carries the instance definition (name, summary, origin notes and the
item definition it is an example of), its lifecycle actions, and the campaign timeline's current
state: where it is, who owns it, its condition and equipped or destroyed state, and any active
attunement. `last_event_id` is the optimistic token every operation takes ("last event seen").
Players read items through character and party inventories, never through this view.
"""

import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import Connection, text

from dnd_ai.domain.content_authoring import evaluate_content_actions
from dnd_ai.domain.entity_lifecycle import BlockedAction
from dnd_ai.queries.content_preconditions import type_specific_blocks


@dataclass(frozen=True)
class Reference:
    entity_id: uuid.UUID
    name: str
    entity_type_code: str


@dataclass(frozen=True)
class ItemAuthoringView:
    item_instance_id: uuid.UUID
    name: str
    summary: str | None
    origin_notes: str | None
    item_definition_id: uuid.UUID
    definition_name: str
    category: str
    category_label: str
    rarity: str
    requires_attunement: bool
    weight: Decimal | None
    canon_status: str
    lifecycle_status: str
    row_version: int
    is_container: bool
    quantity: int
    condition_percentage: int | None
    is_equipped: bool
    is_destroyed: bool
    last_event_id: uuid.UUID | None
    holder: Reference | None
    container: Reference | None
    location: Reference | None
    owner: Reference | None
    attuned_to: Reference | None
    available_actions: list[str] = field(default_factory=list)
    blocked_actions: list[BlockedAction] = field(default_factory=list)


@dataclass(frozen=True)
class ItemSummary:
    item_instance_id: uuid.UUID
    name: str
    definition_name: str
    category_label: str
    canon_status: str
    lifecycle_status: str
    holder_name: str | None
    is_destroyed: bool


def _reference(connection: Connection, entity_id: uuid.UUID | None) -> Reference | None:
    if entity_id is None:
        return None
    row = connection.execute(
        text("""
            SELECT e.canonical_name, et.code FROM core.entities e
            JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id
            WHERE e.entity_id = :e
        """),
        {"e": entity_id},
    ).one_or_none()
    if row is None:
        return None
    return Reference(
        entity_id=entity_id, name=str(row.canonical_name), entity_type_code=str(row.code)
    )


def get_item_authoring(
    connection: Connection,
    *,
    world_id: uuid.UUID,
    timeline_id: uuid.UUID,
    item_instance_id: uuid.UUID,
) -> ItemAuthoringView | None:
    """The authoring view of an item instance in `world_id`, or `None` when it is not one there."""
    row = (
        connection.execute(
            text("""
                SELECT e.canonical_name, e.summary, e.row_version,
                       cs.code AS canon_status, ls.code AS lifecycle_status,
                       ii.origin_notes, d.item_definition_id, d.display_name AS definition_name,
                       ic.code AS category, ic.display_name AS category_label, d.rarity,
                       d.requires_attunement, d.weight,
                       EXISTS (SELECT 1 FROM world.item_containers c
                               WHERE c.container_id = ii.item_instance_id) AS is_container,
                       COALESCE(st.quantity, 1) AS quantity, st.condition_percentage,
                       COALESCE(st.is_equipped, false) AS is_equipped,
                       COALESCE(st.is_destroyed, false) AS is_destroyed, st.last_event_id,
                       ie.holder_entity_id, ie.container_id, ie.location_id,
                       io.owner_entity_id,
                       (SELECT a.character_id FROM campaign.item_attunements a
                        WHERE a.timeline_id = :t AND a.item_instance_id = ii.item_instance_id
                          AND a.broken_world_time_id IS NULL) AS attuned_character_id
                FROM core.entities e
                JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id
                JOIN core.canon_statuses cs ON cs.canon_status_id = e.canon_status_id
                JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = e.lifecycle_status_id
                JOIN world.item_instances ii ON ii.item_instance_id = e.entity_id
                JOIN rules.item_definitions d ON d.item_definition_id = ii.item_definition_id
                JOIN rules.item_categories ic ON ic.item_category_id = d.item_category_id
                LEFT JOIN campaign.item_state st
                       ON st.timeline_id = :t AND st.item_instance_id = ii.item_instance_id
                LEFT JOIN campaign.inventory_entries ie
                       ON ie.timeline_id = :t AND ie.item_instance_id = ii.item_instance_id
                LEFT JOIN campaign.item_ownership io
                       ON io.timeline_id = :t AND io.item_instance_id = ii.item_instance_id
                WHERE e.entity_id = :i AND e.world_id = :w AND et.code = 'item_instance'
            """),
            {"i": item_instance_id, "w": world_id, "t": timeline_id},
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    extra_blocked = type_specific_blocks(
        connection, entity_id=item_instance_id, entity_type_code="item_instance"
    )
    available, blocked = evaluate_content_actions(
        entity_type_code="item_instance",
        canon_status=str(row["canon_status"]),
        lifecycle_status=str(row["lifecycle_status"]),
        extra_blocked=extra_blocked or None,
    )
    return ItemAuthoringView(
        item_instance_id=item_instance_id,
        name=str(row["canonical_name"]),
        summary=row["summary"],
        origin_notes=row["origin_notes"],
        item_definition_id=row["item_definition_id"],
        definition_name=str(row["definition_name"]),
        category=str(row["category"]),
        category_label=str(row["category_label"]),
        rarity=str(row["rarity"]),
        requires_attunement=bool(row["requires_attunement"]),
        weight=row["weight"],
        canon_status=str(row["canon_status"]),
        lifecycle_status=str(row["lifecycle_status"]),
        row_version=int(row["row_version"]),
        is_container=bool(row["is_container"]),
        quantity=int(row["quantity"]),
        condition_percentage=row["condition_percentage"],
        is_equipped=bool(row["is_equipped"]),
        is_destroyed=bool(row["is_destroyed"]),
        last_event_id=row["last_event_id"],
        holder=_reference(connection, row["holder_entity_id"]),
        container=_reference(connection, row["container_id"]),
        location=_reference(connection, row["location_id"]),
        owner=_reference(connection, row["owner_entity_id"]),
        attuned_to=_reference(connection, row["attuned_character_id"]),
        available_actions=list(available),
        blocked_actions=list(blocked),
    )


def list_item_instances(
    connection: Connection,
    *,
    world_id: uuid.UUID,
    timeline_id: uuid.UUID,
    limit: int = 200,
) -> list[ItemSummary]:
    rows = connection.execute(
        text("""
            SELECT e.entity_id, e.canonical_name, d.display_name AS definition_name,
                   ic.display_name AS category_label, cs.code AS canon_status,
                   ls.code AS lifecycle_status, h.canonical_name AS holder_name,
                   COALESCE(st.is_destroyed, false) AS is_destroyed
            FROM core.entities e
            JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id
            JOIN core.canon_statuses cs ON cs.canon_status_id = e.canon_status_id
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = e.lifecycle_status_id
            JOIN world.item_instances ii ON ii.item_instance_id = e.entity_id
            JOIN rules.item_definitions d ON d.item_definition_id = ii.item_definition_id
            JOIN rules.item_categories ic ON ic.item_category_id = d.item_category_id
            LEFT JOIN campaign.item_state st
                   ON st.timeline_id = :t AND st.item_instance_id = ii.item_instance_id
            LEFT JOIN campaign.inventory_entries ie
                   ON ie.timeline_id = :t AND ie.item_instance_id = ii.item_instance_id
            LEFT JOIN core.entities h ON h.entity_id = ie.holder_entity_id
            WHERE e.world_id = :w AND et.code = 'item_instance'
            ORDER BY lower(e.canonical_name), e.entity_id
            LIMIT :limit
        """),
        {"w": world_id, "t": timeline_id, "limit": limit},
    ).all()
    return [
        ItemSummary(
            item_instance_id=r.entity_id,
            name=str(r.canonical_name),
            definition_name=str(r.definition_name),
            category_label=str(r.category_label),
            canon_status=str(r.canon_status),
            lifecycle_status=str(r.lifecycle_status),
            holder_name=None if r.holder_name is None else str(r.holder_name),
            is_destroyed=bool(r.is_destroyed),
        )
        for r in rows
    ]
