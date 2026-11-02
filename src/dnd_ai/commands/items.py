"""TransferItemPossession and IdentifyItem — the commands that let a
dungeon event change who or what currently holds an item instance, or what a
knower currently knows about one, atomically.

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

transfer_item_possession()'s narrative.event_effects.previous_value records
the item's actual prior holder/container/location (added during Phase 9
review, before this PR merged — docs/PHASE9_VERIFICATION.md's correction-
pass note) — NULL only for a genuine first placement, and the real
{holder_entity_id, container_id, location_id} snapshot (matching new_value's
own shape) for every subsequent transfer.

Phase 10 workstream 6 split both commands into a connection-taking
`_..._impl` plus a thin engine-based public wrapper — the same composition
`dnd_ai.commands.encounters.start_encounter`/`_start_encounter_impl`
already used — so `dnd_ai.api.items`' command endpoints run on the
request's own `get_connection` transaction rather than opening a second,
nested one. Both `_impl` functions now also validate a caller-supplied
`session_id`/`campaign_id` pair agree
(`dnd_ai.commands._shared.validate_session_campaign`, the same check
`dnd_ai.commands.encounters` already applied) before mutating anything —
neither command previously did, since no caller supplying both existed
before the API layer. Item-instance/timeline world agreement has no
equivalent application-layer check: unlike a session, there is no
identity- disclosure concern in confirming an item instance's world from a
campaign_id/timeline_id the caller is already authorized against, and
`campaign.enforce_inventory_entry_world()` (revision 077) already rejects
the mismatch atomically at the database layer, surfacing as the same
generic `IntegrityError` -> 400 every other cross-domain FK/CHECK
violation in this codebase does.
"""

import json
import uuid
from dataclasses import dataclass, field

from sqlalchemy import Connection, Engine, text

from ._shared import validate_session_campaign
from .events import EventParticipant, _insert_event_row
from .item_operations import UNSET, Token, transfer_in_context


@dataclass(frozen=True)
class TransferItemPossessionResult:
    inventory_entry_id: uuid.UUID
    event_id: uuid.UUID
    world_id: uuid.UUID
    changed_fields: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class IdentifyItemResult:
    item_identification_id: uuid.UUID
    event_id: uuid.UUID
    previous_level: str | None
    new_level: str
    world_id: uuid.UUID


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


def _transfer_item_possession_impl(
    connection: Connection,
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
    expected_last_event_id: Token = UNSET,
    transfer_ownership: bool = False,
) -> TransferItemPossessionResult:
    """The actual work of transfer_item_possession(), on a connection the
    caller already has open — see that function's docstring for why this
    module splits each command into a composable, connection-taking
    implementation and a public engine-based convenience wrapper (below).
    A caller that owns the surrounding transaction itself (e.g. the API
    layer's per-request connection) calls this directly.

    Validates session_id/campaign_id agreement
    (dnd_ai.commands._shared.validate_session_campaign) before inserting
    anything.

    Phase 15.3B-1b: the placement itself is `dnd_ai.commands.item_operations.
    transfer_in_context`, the one implementation the item operations share, so
    this adapter now also refuses an unpublished or destroyed item, an equipped
    or attuned item changing holder, a holder that is not a published
    character, a container that would form a loop, and a move to where the item
    already is. It takes no optimistic token (it predates it) and records the
    same `item_state.last_event_id` the token reads."""
    validate_session_campaign(connection, campaign_id=campaign_id, session_id=session_id)

    world_id = _item_instance_world(connection, item_instance_id)
    result = transfer_in_context(
        connection,
        world_id=world_id,
        timeline_id=timeline_id,
        campaign_id=campaign_id,
        item_id=item_instance_id,
        time_id=world_time_id,
        holder_entity_id=holder_entity_id,
        container_id=container_id,
        location_id=location_id,
        session_id=session_id,
        transfer_ownership=transfer_ownership,
        expected=expected_last_event_id,
        participants=(
            (EventParticipant(entity_id=actor_entity_id, role_code="actor"),)
            if actor_entity_id is not None
            else ()
        ),
        note=event_details,
        cause_interaction_id=cause_interaction_id,
        cause_event_id=cause_event_id,
    )
    assert result.inventory_entry_id is not None
    return TransferItemPossessionResult(
        inventory_entry_id=result.inventory_entry_id,
        event_id=result.event_id,
        world_id=world_id,
        changed_fields=result.changed_fields,
    )


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
    state, or removed from play without a new location yet). Public
    convenience API: opens and commits its own transaction. See
    _transfer_item_possession_impl() for the composable form a caller with
    its own transaction (e.g. an API command endpoint) uses instead."""
    with engine.begin() as connection:
        return _transfer_item_possession_impl(
            connection,
            item_instance_id=item_instance_id,
            timeline_id=timeline_id,
            world_time_id=world_time_id,
            holder_entity_id=holder_entity_id,
            container_id=container_id,
            location_id=location_id,
            actor_entity_id=actor_entity_id,
            campaign_id=campaign_id,
            session_id=session_id,
            cause_interaction_id=cause_interaction_id,
            cause_event_id=cause_event_id,
            event_details=event_details,
        )


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


def _identify_item_impl(
    connection: Connection,
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
    """The actual work of identify_item(), on a connection the caller
    already has open — see _transfer_item_possession_impl's docstring for
    why this module splits each command into a composable, connection-
    taking implementation and a public engine-based convenience wrapper
    (below). A caller that owns the surrounding transaction itself (e.g.
    the API layer's per-request connection) calls this directly.

    Validates session_id/campaign_id agreement
    (dnd_ai.commands._shared.validate_session_campaign) before inserting
    anything."""
    validate_session_campaign(connection, campaign_id=campaign_id, session_id=session_id)

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
        world_id=world_id,
    )


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
    knowledge.item_identification to match, atomically. Public convenience
    API: opens and commits its own transaction. See _identify_item_impl()
    for the composable form a caller with its own transaction (e.g. an API
    command endpoint) uses instead."""
    with engine.begin() as connection:
        return _identify_item_impl(
            connection,
            item_instance_id=item_instance_id,
            timeline_id=timeline_id,
            world_time_id=world_time_id,
            knower_entity_id=knower_entity_id,
            new_level=new_level,
            known_properties=known_properties,
            actor_entity_id=actor_entity_id,
            campaign_id=campaign_id,
            session_id=session_id,
            cause_interaction_id=cause_interaction_id,
            cause_event_id=cause_event_id,
            event_details=event_details,
        )
