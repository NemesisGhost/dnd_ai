"""TransferItemPossession and IdentifyItem — the commands that let a
dungeon event change who/what currently holds an item instance, or what a
knower currently knows about one, atomically (docs/PLAN.md Phase 9).

Mirrors dnd_ai.commands.relationships.evolve_relationship_reaction's shape:
lock a structural row that always exists (world.item_instances) before
touching the possibly-absent campaign.inventory_entries /
knowledge.item_identification row, then record the causing narrative.events
row, update the state table to match, and link the two through a
narrative.event_effects row — all in one transaction.

Ownership (campaign.item_ownership) has no command yet — no exit criterion
requires an ownership-transfer command this increment, and the shape would
be identical to transfer_item_possession's, so it is deferred to a concrete
caller rather than built speculatively (conventions §33.1).
"""

import json
import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, Engine, text

from .events import EventParticipant, _insert_event_row


@dataclass(frozen=True)
class TransferItemPossessionResult:
    inventory_entry_id: uuid.UUID
    event_id: uuid.UUID


@dataclass(frozen=True)
class IdentifyItemResult:
    item_identification_id: uuid.UUID
    event_id: uuid.UUID
    previous_level: str | None
    new_level: str


def _item_instance_world(connection: Connection, item_instance_id: uuid.UUID) -> uuid.UUID:
    world_id = connection.execute(
        text("SELECT world_id FROM core.entities WHERE entity_id = :i"),
        {"i": item_instance_id},
    ).scalar()
    if world_id is None:
        raise ValueError(f"item instance {item_instance_id} does not exist")
    assert isinstance(world_id, uuid.UUID)
    return world_id


def _lock_item_instance(connection: Connection, item_instance_id: uuid.UUID) -> None:
    """Acquire an exclusive row lock on the item instance itself (a
    structural row that always exists, unlike its possibly-absent
    campaign.inventory_entries / knowledge.item_identification row) before
    touching either — the same first-write concurrency guard
    evolve_relationship_reaction applies via _lock_relationship."""
    connection.execute(
        text(
            "SELECT item_instance_id FROM world.item_instances "
            "WHERE item_instance_id = :i FOR UPDATE"
        ),
        {"i": item_instance_id},
    )


def _lock_inventory_entry(
    connection: Connection, *, timeline_id: uuid.UUID, item_instance_id: uuid.UUID
) -> uuid.UUID | None:
    row = connection.execute(
        text("""
            SELECT inventory_entry_id
            FROM campaign.inventory_entries
            WHERE timeline_id = :timeline AND item_instance_id = :item
            FOR UPDATE
        """),
        {"timeline": timeline_id, "item": item_instance_id},
    ).scalar()
    if row is None:
        return None
    assert isinstance(row, uuid.UUID)
    return row


def transfer_item_possession(
    engine: Engine,
    *,
    item_instance_id: uuid.UUID,
    timeline_id: uuid.UUID,
    world_time_id: uuid.UUID,
    holder_entity_id: uuid.UUID | None = None,
    container_id: uuid.UUID | None = None,
    location_id: uuid.UUID | None = None,
    actor_entity_id: uuid.UUID | None = None,
    campaign_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    cause_interaction_id: uuid.UUID | None = None,
    cause_event_id: uuid.UUID | None = None,
    event_details: str | None = None,
) -> TransferItemPossessionResult:
    """Record the narrative.events row that moves an item instance to a new
    holder/container/location and update campaign.inventory_entries to
    match, atomically. At most one of holder_entity_id/container_id/
    location_id may be set — campaign.inventory_entries' own
    ck_inventory_entries_at_most_one_place CHECK rejects any other
    combination; all three NULL is valid (item picked up from an unplaced
    state, or removed from play without a new location yet)."""
    with engine.begin() as connection:
        world_id = _item_instance_world(connection, item_instance_id)
        _lock_item_instance(connection, item_instance_id)

        existing = _lock_inventory_entry(
            connection, timeline_id=timeline_id, item_instance_id=item_instance_id
        )

        event_id = _insert_event_row(
            connection,
            world_id=world_id,
            timeline_id=timeline_id,
            world_time_id=world_time_id,
            event_type_code="item_transferred",
            name="Item transferred",
            details=event_details,
            campaign_id=campaign_id,
            session_id=session_id,
            participants=(
                (EventParticipant(entity_id=actor_entity_id, role_code="actor"),)
                if actor_entity_id is not None
                else ()
            ),
            cause_interaction_id=cause_interaction_id,
            cause_event_id=cause_event_id,
        )

        if existing is None:
            inventory_entry_id = connection.execute(
                text("""
                    INSERT INTO campaign.inventory_entries
                        (timeline_id, item_instance_id, holder_entity_id, container_id,
                         location_id, last_event_id)
                    VALUES (:timeline, :item, :holder, :container, :location, :event)
                    RETURNING inventory_entry_id
                """),
                {
                    "timeline": timeline_id,
                    "item": item_instance_id,
                    "holder": holder_entity_id,
                    "container": container_id,
                    "location": location_id,
                    "event": event_id,
                },
            ).scalar()
            assert isinstance(inventory_entry_id, uuid.UUID)
        else:
            inventory_entry_id = existing
            connection.execute(
                text("""
                    UPDATE campaign.inventory_entries
                    SET holder_entity_id = :holder, container_id = :container,
                        location_id = :location, last_event_id = :event, updated_at = now()
                    WHERE inventory_entry_id = :id
                """),
                {
                    "holder": holder_entity_id,
                    "container": container_id,
                    "location": location_id,
                    "event": event_id,
                    "id": inventory_entry_id,
                },
            )

        connection.execute(
            text("""
                INSERT INTO narrative.event_effects
                    (event_id, target_entity_id, target_component, previous_value,
                     new_value, effective_world_time_id)
                VALUES (:event, :item, 'inventory_entries.location', :previous, :new, :world_time)
            """),
            {
                "event": event_id,
                "item": item_instance_id,
                "previous": None,
                "new": json.dumps(
                    {
                        "holder_entity_id": str(holder_entity_id) if holder_entity_id else None,
                        "container_id": str(container_id) if container_id else None,
                        "location_id": str(location_id) if location_id else None,
                    }
                ),
                "world_time": world_time_id,
            },
        )

    return TransferItemPossessionResult(inventory_entry_id=inventory_entry_id, event_id=event_id)


def _lock_item_identification(
    connection: Connection,
    *,
    timeline_id: uuid.UUID,
    item_instance_id: uuid.UUID,
    knower_entity_id: uuid.UUID,
) -> tuple[uuid.UUID, str] | None:
    row = connection.execute(
        text("""
            SELECT item_identification_id, identification_level
            FROM knowledge.item_identification
            WHERE timeline_id = :timeline AND item_instance_id = :item
              AND knower_entity_id = :knower
            FOR UPDATE
        """),
        {"timeline": timeline_id, "item": item_instance_id, "knower": knower_entity_id},
    ).one_or_none()
    if row is None:
        return None
    item_identification_id, level = row
    assert isinstance(item_identification_id, uuid.UUID)
    assert isinstance(level, str)
    return item_identification_id, level


def identify_item(
    engine: Engine,
    *,
    item_instance_id: uuid.UUID,
    timeline_id: uuid.UUID,
    world_time_id: uuid.UUID,
    knower_entity_id: uuid.UUID,
    new_level: str,
    known_properties: dict[str, object] | None = None,
    actor_entity_id: uuid.UUID | None = None,
    campaign_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    cause_interaction_id: uuid.UUID | None = None,
    cause_event_id: uuid.UUID | None = None,
    event_details: str | None = None,
) -> IdentifyItemResult:
    """Record the narrative.events row that advances a knower's
    identification of an item instance and update
    knowledge.item_identification to match, atomically."""
    with engine.begin() as connection:
        world_id = _item_instance_world(connection, item_instance_id)
        _lock_item_instance(connection, item_instance_id)

        existing = _lock_item_identification(
            connection,
            timeline_id=timeline_id,
            item_instance_id=item_instance_id,
            knower_entity_id=knower_entity_id,
        )
        previous_level = existing[1] if existing is not None else None

        event_id = _insert_event_row(
            connection,
            world_id=world_id,
            timeline_id=timeline_id,
            world_time_id=world_time_id,
            event_type_code="item_identified",
            name="Item identified",
            details=event_details,
            campaign_id=campaign_id,
            session_id=session_id,
            participants=(
                (EventParticipant(entity_id=actor_entity_id, role_code="actor"),)
                if actor_entity_id is not None
                else ()
            ),
            cause_interaction_id=cause_interaction_id,
            cause_event_id=cause_event_id,
        )

        properties_json = json.dumps(known_properties) if known_properties is not None else None

        if existing is None:
            item_identification_id = connection.execute(
                text("""
                    INSERT INTO knowledge.item_identification
                        (timeline_id, item_instance_id, knower_entity_id, identification_level,
                         known_properties_jsonb, identified_at_world_time_id, last_event_id)
                    VALUES (:timeline, :item, :knower, :level, :properties, :world_time, :event)
                    RETURNING item_identification_id
                """),
                {
                    "timeline": timeline_id,
                    "item": item_instance_id,
                    "knower": knower_entity_id,
                    "level": new_level,
                    "properties": properties_json,
                    "world_time": world_time_id,
                    "event": event_id,
                },
            ).scalar()
            assert isinstance(item_identification_id, uuid.UUID)
        else:
            item_identification_id = existing[0]
            connection.execute(
                text("""
                    UPDATE knowledge.item_identification
                    SET identification_level = :level, known_properties_jsonb = :properties,
                        identified_at_world_time_id = :world_time, last_event_id = :event,
                        updated_at = now()
                    WHERE item_identification_id = :id
                """),
                {
                    "level": new_level,
                    "properties": properties_json,
                    "world_time": world_time_id,
                    "event": event_id,
                    "id": item_identification_id,
                },
            )

        connection.execute(
            text("""
                INSERT INTO narrative.event_effects
                    (event_id, target_entity_id, target_component, previous_value,
                     new_value, effective_world_time_id)
                VALUES (:event, :item, 'identification_level', :previous, :new, :world_time)
            """),
            {
                "event": event_id,
                "item": item_instance_id,
                "previous": json.dumps(previous_level),
                "new": json.dumps(new_level),
                "world_time": world_time_id,
            },
        )

    return IdentifyItemResult(
        item_identification_id=item_identification_id,
        event_id=event_id,
        previous_level=previous_level,
        new_level=new_level,
    )
