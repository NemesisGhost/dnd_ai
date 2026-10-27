"""Item runtime operations (Phase 15 checkpoint 15.3B-1b).

Award, transfer, equip, unequip, consume, damage, repair, destroy, attune and end attunement.
Each records one causal event, writes the timeline state it changes (`campaign.inventory_entries`,
`item_ownership`, `item_state`, `item_attunements`), and records one `narrative.event_effects`
row per changed component with the previous and new values (which is what an event correction
needs to undo it), all in the caller's transaction.

Rules shared by every operation:

- The item and every character, container item or place it names must be a published (`canon`,
  `active`) definition of the campaign's world; a draft or archived one is refused.
- `campaign.item_state.last_event_id` is the item's single optimistic token. Every operation
  writes it, so `expected_last_event_id` (the event the caller last saw, `None` when the item has
  no state yet) goes stale whichever table another operation changed. A mismatch is a stale write.
- A destroyed item takes no further operation. An equipped or attuned item does not change
  holder, and is not destroyed or fully consumed, until it is unequipped or its attunement ended.
- Time is the explicit world time or the campaign clock.

Lock order: operation scope (world, membership rows, account, campaign `FOR SHARE`); a per-timeline
advisory lock when the destination is a container (it serializes placements, so two concurrent
placements cannot form a loop) and a per-character advisory lock for attunement (the three-item
limit); every named entity `FOR SHARE` in id order; the item instance `FOR UPDATE`; then the
inventory entry, item state, ownership and attunement rows `FOR UPDATE`.
"""

import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Final

from sqlalchemy import Connection, text

from dnd_ai.domain.authoring import StaleWriteError, normalize_description
from dnd_ai.domain.content_authoring import diff_fields
from dnd_ai.domain.item_runtime import (
    HOLDER_TYPE_CODES,
    MAX_ATTUNEMENTS_PER_CHARACTER,
    OPERATION_EVENTS,
    AttunementNotAllowedError,
    ItemAlreadyPlacedError,
    ItemAttunedError,
    ItemContainerInvalidError,
    ItemDestroyedError,
    ItemEquippedError,
    ItemHolderInvalidError,
    ItemNotHeldError,
    ItemOperationInvalidError,
    normalize_percentage_amount,
    normalize_quantity,
)

from ._content import EntityNotFoundError
from ._operations import OperationScope, lock_operation_scope
from ._shared import require_state_targetable, validate_session_campaign
from .events import EventParticipant, _insert_event_row
from .quest_runtime import time_or_clock


class _Unset:
    """Marks a token the caller did not supply (adapter calls that predate the token)."""


UNSET: Final = _Unset()
Token = uuid.UUID | None | _Unset

_CONTAINER_DEPTH_LIMIT = 50


@dataclass(frozen=True)
class ItemOperationResult:
    item_instance_id: uuid.UUID
    world_id: uuid.UUID
    event_id: uuid.UUID
    operation: str
    inventory_entry_id: uuid.UUID | None = None
    changed_fields: dict[str, object] = field(default_factory=dict)


@dataclass
class _State:
    item_state_id: uuid.UUID | None
    quantity: int = 1
    condition_percentage: int | None = None
    charges_current: int | None = None
    charges_maximum: int | None = None
    is_equipped: bool = False
    is_destroyed: bool = False
    last_event_id: uuid.UUID | None = None

    def snapshot(self) -> dict[str, Any]:
        return {
            "quantity": self.quantity,
            "condition_percentage": self.condition_percentage,
            "is_equipped": self.is_equipped,
            "is_destroyed": self.is_destroyed,
        }


@dataclass
class _Entry:
    inventory_entry_id: uuid.UUID | None
    holder_entity_id: uuid.UUID | None = None
    container_id: uuid.UUID | None = None
    location_id: uuid.UUID | None = None

    def place(self) -> dict[str, str | None]:
        return {
            "holder_entity_id": _text(self.holder_entity_id),
            "container_id": _text(self.container_id),
            "location_id": _text(self.location_id),
        }

    @property
    def is_placed(self) -> bool:
        return any((self.holder_entity_id, self.container_id, self.location_id))


@dataclass
class _Context:
    connection: Connection
    world_id: uuid.UUID
    timeline_id: uuid.UUID
    campaign_id: uuid.UUID | None
    item_id: uuid.UUID
    state: _State
    entry: _Entry
    owner_row: uuid.UUID | None  # item_ownership_id, when there is a row
    owner: uuid.UUID | None
    attunement_id: uuid.UUID | None
    attuned_character_id: uuid.UUID | None
    requires_attunement: bool


def _text(value: uuid.UUID | None) -> str | None:
    return None if value is None else str(value)


# --- locking and reading -------------------------------------------------------------------------


def _require_item_in_world(connection: Connection, world_id: uuid.UUID, item_id: uuid.UUID) -> None:
    row = connection.execute(
        text("""
            SELECT e.world_id, et.code FROM core.entities e
            JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id
            WHERE e.entity_id = :i
        """),
        {"i": item_id},
    ).one_or_none()
    if row is None or row.world_id != world_id or row.code != "item_instance":
        raise EntityNotFoundError(f"item {item_id} is not in this world")


def _require_world_entity(
    connection: Connection, world_id: uuid.UUID, entity_id: uuid.UUID, type_codes: frozenset[str]
) -> None:
    row = connection.execute(
        text("""
            SELECT e.world_id, et.code FROM core.entities e
            JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id
            WHERE e.entity_id = :i
        """),
        {"i": entity_id},
    ).one_or_none()
    if row is None or row.world_id != world_id or row.code not in type_codes:
        raise ItemHolderInvalidError(f"entity {entity_id} is not usable here")


def _is_location(connection: Connection, world_id: uuid.UUID, location_id: uuid.UUID) -> bool:
    return (
        connection.execute(
            text("""
                SELECT 1 FROM world.locations l
                JOIN core.entities e ON e.entity_id = l.location_id
                WHERE l.location_id = :l AND e.world_id = :w
            """),
            {"l": location_id, "w": world_id},
        ).scalar()
        is not None
    )


def _load(
    connection: Connection,
    *,
    world_id: uuid.UUID,
    timeline_id: uuid.UUID,
    campaign_id: uuid.UUID | None,
    item_id: uuid.UUID,
) -> _Context:
    state_row = (
        connection.execute(
            text("""
                SELECT item_state_id, quantity, condition_percentage, charges_current,
                       charges_maximum, is_equipped, is_destroyed, last_event_id
                FROM campaign.item_state
                WHERE timeline_id = :t AND item_instance_id = :i FOR UPDATE
            """),
            {"t": timeline_id, "i": item_id},
        )
        .mappings()
        .one_or_none()
    )
    state = _State(item_state_id=None) if state_row is None else _State(**dict(state_row))
    entry_row = connection.execute(
        text("""
            SELECT inventory_entry_id, holder_entity_id, container_id, location_id
            FROM campaign.inventory_entries
            WHERE timeline_id = :t AND item_instance_id = :i FOR UPDATE
        """),
        {"t": timeline_id, "i": item_id},
    ).one_or_none()
    entry = (
        _Entry(inventory_entry_id=None)
        if entry_row is None
        else _Entry(
            entry_row.inventory_entry_id,
            entry_row.holder_entity_id,
            entry_row.container_id,
            entry_row.location_id,
        )
    )
    owner_row = connection.execute(
        text("""
            SELECT item_ownership_id, owner_entity_id FROM campaign.item_ownership
            WHERE timeline_id = :t AND item_instance_id = :i FOR UPDATE
        """),
        {"t": timeline_id, "i": item_id},
    ).one_or_none()
    attunement = connection.execute(
        text("""
            SELECT item_attunement_id, character_id FROM campaign.item_attunements
            WHERE timeline_id = :t AND item_instance_id = :i AND broken_world_time_id IS NULL
            FOR UPDATE
        """),
        {"t": timeline_id, "i": item_id},
    ).one_or_none()
    requires = connection.execute(
        text("""
            SELECT d.requires_attunement FROM world.item_instances ii
            JOIN rules.item_definitions d ON d.item_definition_id = ii.item_definition_id
            WHERE ii.item_instance_id = :i
        """),
        {"i": item_id},
    ).scalar()
    return _Context(
        connection=connection,
        world_id=world_id,
        timeline_id=timeline_id,
        campaign_id=campaign_id,
        item_id=item_id,
        state=state,
        entry=entry,
        owner_row=None if owner_row is None else owner_row.item_ownership_id,
        owner=None if owner_row is None else owner_row.owner_entity_id,
        attunement_id=None if attunement is None else attunement.item_attunement_id,
        attuned_character_id=None if attunement is None else attunement.character_id,
        requires_attunement=bool(requires),
    )


def _begin(
    connection: Connection,
    *,
    world_id: uuid.UUID,
    timeline_id: uuid.UUID,
    campaign_id: uuid.UUID | None,
    item_id: uuid.UUID,
    others: tuple[uuid.UUID | None, ...] = (),
    expected: Token = UNSET,
    advisory: str | None = None,
) -> _Context:
    _require_item_in_world(connection, world_id, item_id)
    if advisory is not None:
        connection.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": advisory}
        )
    require_state_targetable(connection, item_id, *others)
    connection.execute(
        text("SELECT 1 FROM world.item_instances WHERE item_instance_id = :i FOR UPDATE"),
        {"i": item_id},
    )
    ctx = _load(
        connection,
        world_id=world_id,
        timeline_id=timeline_id,
        campaign_id=campaign_id,
        item_id=item_id,
    )
    if not isinstance(expected, _Unset) and expected != ctx.state.last_event_id:
        raise StaleWriteError(f"item {item_id} changed since it was read")
    return ctx


# --- recording -------------------------------------------------------------------------------------


def _effect(
    ctx: _Context,
    *,
    event_id: uuid.UUID,
    time_id: uuid.UUID,
    component: str,
    previous: object,
    new: object,
) -> None:
    ctx.connection.execute(
        text("""
            INSERT INTO narrative.event_effects
                (event_id, target_entity_id, target_component, previous_value, new_value,
                 effective_world_time_id)
            VALUES (:e, :i, :c, CAST(:p AS jsonb), CAST(:n AS jsonb), :t)
        """),
        {
            "e": event_id,
            "i": ctx.item_id,
            "c": component,
            "p": None if previous is None else json.dumps(previous),
            "n": None if new is None else json.dumps(new),
            "t": time_id,
        },
    )


def _record(
    ctx: _Context,
    operation: str,
    *,
    time_id: uuid.UUID,
    session_id: uuid.UUID | None,
    note: str | None,
    participants: tuple[EventParticipant, ...] = (),
    event_type: str | None = None,
    cause_interaction_id: uuid.UUID | None = None,
    cause_event_id: uuid.UUID | None = None,
) -> uuid.UUID:
    default_type, name = OPERATION_EVENTS[operation]
    return _insert_event_row(
        ctx.connection,
        world_id=ctx.world_id,
        timeline_id=ctx.timeline_id,
        world_time_id=time_id,
        event_type_code=event_type or default_type,
        name=name,
        details=note,
        campaign_id=ctx.campaign_id,
        session_id=session_id,
        participants=participants,
        cause_interaction_id=cause_interaction_id,
        cause_event_id=cause_event_id,
    )


def _write_state(
    ctx: _Context, event_id: uuid.UUID, time_id: uuid.UUID, before: dict[str, Any]
) -> None:
    """Upsert `item_state` with the event as its token.

    Every operation records an `item_state` effect, even when no field changed, because it
    carries the token before and after: an event correction restores the previous token, so the
    item's token always names its last event that is still in force."""
    s = ctx.state
    previous_token = s.last_event_id
    if s.item_state_id is None:
        s.item_state_id = ctx.connection.execute(
            text("""
                INSERT INTO campaign.item_state
                    (timeline_id, item_instance_id, quantity, condition_percentage,
                     charges_current, charges_maximum, is_equipped, is_destroyed, last_event_id)
                VALUES (:t, :i, :q, :c, :cc, :cm, :eq, :d, :e)
                RETURNING item_state_id
            """),
            {
                "t": ctx.timeline_id,
                "i": ctx.item_id,
                "q": s.quantity,
                "c": s.condition_percentage,
                "cc": s.charges_current,
                "cm": s.charges_maximum,
                "eq": s.is_equipped,
                "d": s.is_destroyed,
                "e": event_id,
            },
        ).scalar()
    else:
        ctx.connection.execute(
            text("""
                UPDATE campaign.item_state
                SET quantity = :q, condition_percentage = :c, is_equipped = :eq,
                    is_destroyed = :d, last_event_id = :e
                WHERE item_state_id = :s
            """),
            {
                "q": s.quantity,
                "c": s.condition_percentage,
                "eq": s.is_equipped,
                "d": s.is_destroyed,
                "e": event_id,
                "s": s.item_state_id,
            },
        )
    _effect(
        ctx,
        event_id=event_id,
        time_id=time_id,
        component="item_state",
        previous={**before, "last_event_id": _text(previous_token)},
        new={**s.snapshot(), "last_event_id": str(event_id)},
    )
    s.last_event_id = event_id


def _write_place(ctx: _Context, event_id: uuid.UUID, time_id: uuid.UUID, new: _Entry) -> uuid.UUID:
    previous = ctx.entry.place() if ctx.entry.inventory_entry_id is not None else None
    if ctx.entry.inventory_entry_id is None:
        entry_id = ctx.connection.execute(
            text("""
                INSERT INTO campaign.inventory_entries
                    (timeline_id, item_instance_id, holder_entity_id, container_id, location_id,
                     last_event_id)
                VALUES (:t, :i, :h, :c, :l, :e) RETURNING inventory_entry_id
            """),
            {
                "t": ctx.timeline_id,
                "i": ctx.item_id,
                "h": new.holder_entity_id,
                "c": new.container_id,
                "l": new.location_id,
                "e": event_id,
            },
        ).scalar()
        assert isinstance(entry_id, uuid.UUID)
    else:
        entry_id = ctx.entry.inventory_entry_id
        ctx.connection.execute(
            text("""
                UPDATE campaign.inventory_entries
                SET holder_entity_id = :h, container_id = :c, location_id = :l,
                    last_event_id = :e, updated_at = now()
                WHERE inventory_entry_id = :id
            """),
            {
                "h": new.holder_entity_id,
                "c": new.container_id,
                "l": new.location_id,
                "e": event_id,
                "id": entry_id,
            },
        )
    _effect(
        ctx,
        event_id=event_id,
        time_id=time_id,
        component="inventory_entries.location",
        previous=previous,
        new=new.place(),
    )
    ctx.entry = _Entry(entry_id, new.holder_entity_id, new.container_id, new.location_id)
    return entry_id


def _write_owner(
    ctx: _Context, event_id: uuid.UUID, time_id: uuid.UUID, owner: uuid.UUID | None
) -> None:
    if ctx.owner_row is None:
        ctx.connection.execute(
            text("""
                INSERT INTO campaign.item_ownership
                    (timeline_id, item_instance_id, owner_entity_id, acquired_world_time_id,
                     last_event_id)
                VALUES (:t, :i, :o, :w, :e)
            """),
            {"t": ctx.timeline_id, "i": ctx.item_id, "o": owner, "w": time_id, "e": event_id},
        )
    else:
        ctx.connection.execute(
            text("""
                UPDATE campaign.item_ownership
                SET owner_entity_id = :o, acquired_world_time_id = :w, last_event_id = :e
                WHERE item_ownership_id = :id
            """),
            {"o": owner, "w": time_id, "e": event_id, "id": ctx.owner_row},
        )
    _effect(
        ctx,
        event_id=event_id,
        time_id=time_id,
        component="item_ownership",
        previous={"owner_entity_id": _text(ctx.owner)} if ctx.owner_row is not None else None,
        new={"owner_entity_id": _text(owner)},
    )


def _result(
    ctx: _Context,
    event_id: uuid.UUID,
    operation: str,
    before: dict[str, object],
    after: dict[str, object],
    entry_id: uuid.UUID | None = None,
) -> ItemOperationResult:
    """`changed_fields` is the bounded audit diff: structural fields only keep their values."""
    return ItemOperationResult(
        item_instance_id=ctx.item_id,
        world_id=ctx.world_id,
        event_id=event_id,
        operation=operation,
        inventory_entry_id=entry_id or ctx.entry.inventory_entry_id,
        changed_fields=dict(diff_fields(before, after)),
    )


def _require_live(ctx: _Context) -> None:
    if ctx.state.is_destroyed:
        raise ItemDestroyedError(f"item {ctx.item_id} is destroyed")


# --- the shared placement core (also used by the adapter command) ------------------------------


def _check_destination(
    connection: Connection,
    *,
    ctx: _Context,
    holder_id: uuid.UUID | None,
    container_id: uuid.UUID | None,
    location_id: uuid.UUID | None,
) -> None:
    if holder_id is not None:
        _require_world_entity(connection, ctx.world_id, holder_id, HOLDER_TYPE_CODES)
    if location_id is not None and not _is_location(connection, ctx.world_id, location_id):
        raise ItemHolderInvalidError(f"location {location_id} is not usable here")
    if container_id is not None:
        is_container = connection.execute(
            text("SELECT 1 FROM world.item_containers WHERE container_id = :c"),
            {"c": container_id},
        ).scalar()
        _require_world_entity(connection, ctx.world_id, container_id, frozenset({"item_instance"}))
        if is_container is None or container_id == ctx.item_id:
            raise ItemContainerInvalidError(f"{container_id} is not a container")
        # Walk up from the destination: reaching this item would make a loop.
        cursor: uuid.UUID | None = container_id
        for _ in range(_CONTAINER_DEPTH_LIMIT):
            if cursor is None:
                break
            if cursor == ctx.item_id:
                raise ItemContainerInvalidError("that would place the item inside itself")
            cursor = connection.execute(
                text("""
                    SELECT container_id FROM campaign.inventory_entries
                    WHERE timeline_id = :t AND item_instance_id = :c
                """),
                {"t": ctx.timeline_id, "c": cursor},
            ).scalar()
        else:
            raise ItemContainerInvalidError("containers are nested too deeply")


def transfer_in_context(
    connection: Connection,
    *,
    world_id: uuid.UUID,
    timeline_id: uuid.UUID,
    campaign_id: uuid.UUID | None,
    item_id: uuid.UUID,
    time_id: uuid.UUID,
    holder_entity_id: uuid.UUID | None,
    container_id: uuid.UUID | None,
    location_id: uuid.UUID | None,
    transfer_ownership: bool = False,
    expected: Token = UNSET,
    session_id: uuid.UUID | None = None,
    participants: tuple[EventParticipant, ...] = (),
    note: str | None = None,
    cause_interaction_id: uuid.UUID | None = None,
    cause_event_id: uuid.UUID | None = None,
) -> ItemOperationResult:
    if sum(x is not None for x in (holder_entity_id, container_id, location_id)) > 1:
        raise ItemHolderInvalidError("name at most one of holder, container and location")
    ctx = _begin(
        connection,
        world_id=world_id,
        timeline_id=timeline_id,
        campaign_id=campaign_id,
        item_id=item_id,
        others=(holder_entity_id, container_id, location_id),
        expected=expected,
        advisory=(None if container_id is None else f"campaign.item_containment:{timeline_id}"),
    )
    _require_live(ctx)
    _check_destination(
        connection,
        ctx=ctx,
        holder_id=holder_entity_id,
        container_id=container_id,
        location_id=location_id,
    )
    new = _Entry(None, holder_entity_id, container_id, location_id)
    if ctx.entry.inventory_entry_id is not None and ctx.entry.place() == new.place():
        raise ItemOperationInvalidError("the item is already there")
    if ctx.entry.holder_entity_id != holder_entity_id:
        if ctx.state.is_equipped:
            raise ItemEquippedError(f"item {item_id} is equipped")
        if ctx.attunement_id is not None:
            raise ItemAttunedError(f"item {item_id} is attuned")
    event_id = _record(
        ctx,
        "transfer",
        time_id=time_id,
        session_id=session_id,
        note=note,
        participants=participants
        or (
            (EventParticipant(entity_id=holder_entity_id, role_code="beneficiary"),)
            if holder_entity_id is not None
            else ()
        ),
        cause_interaction_id=cause_interaction_id,
        cause_event_id=cause_event_id,
    )
    before = ctx.state.snapshot()
    previous_place = ctx.entry.place()
    entry_id = _write_place(ctx, event_id, time_id, new)
    if transfer_ownership and holder_entity_id is not None and holder_entity_id != ctx.owner:
        _write_owner(ctx, event_id, time_id, holder_entity_id)
    _write_state(ctx, event_id, time_id, before)
    return _result(ctx, event_id, "transfer", dict(previous_place), dict(new.place()), entry_id)


# --- public operations -------------------------------------------------------------------------


def _scope_and_time(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    world_time_id: uuid.UUID | None,
    session_id: uuid.UUID | None,
) -> tuple[OperationScope, uuid.UUID]:
    scope = lock_operation_scope(connection, campaign_id=campaign_id, actor_user_id=actor_user_id)
    validate_session_campaign(connection, campaign_id=campaign_id, session_id=session_id)
    return scope, time_or_clock(connection, scope, world_time_id)


def award_item(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    item_instance_id: uuid.UUID,
    holder_entity_id: uuid.UUID,
    expected_last_event_id: uuid.UUID | None,
    quantity: int = 1,
    set_owner: bool = True,
    world_time_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    note: str | None = None,
) -> ItemOperationResult:
    amount = normalize_quantity(quantity)
    details = normalize_description(note)
    scope, time_id = _scope_and_time(
        connection,
        campaign_id=campaign_id,
        actor_user_id=actor_user_id,
        world_time_id=world_time_id,
        session_id=session_id,
    )
    ctx = _begin(
        connection,
        world_id=scope.world_id,
        timeline_id=scope.timeline_id,
        campaign_id=campaign_id,
        item_id=item_instance_id,
        others=(holder_entity_id,),
        expected=expected_last_event_id,
    )
    _require_live(ctx)
    if ctx.entry.is_placed:
        raise ItemAlreadyPlacedError(f"item {item_instance_id} is already placed")
    _require_world_entity(connection, scope.world_id, holder_entity_id, HOLDER_TYPE_CODES)
    event_id = _record(
        ctx,
        "award",
        time_id=time_id,
        session_id=session_id,
        note=details,
        participants=(EventParticipant(entity_id=holder_entity_id, role_code="beneficiary"),),
    )
    before = ctx.state.snapshot()
    ctx.state.quantity = amount
    entry_id = _write_place(ctx, event_id, time_id, _Entry(None, holder_entity_id))
    if set_owner:
        _write_owner(ctx, event_id, time_id, holder_entity_id)
    _write_state(ctx, event_id, time_id, before)
    return _result(
        ctx,
        event_id,
        "award",
        {"holder_entity_id": None, "quantity": before["quantity"]},
        {"holder_entity_id": str(holder_entity_id), "quantity": amount},
        entry_id,
    )


def _state_operation(
    connection: Connection,
    *,
    operation: str,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    item_instance_id: uuid.UUID,
    expected_last_event_id: uuid.UUID | None,
    world_time_id: uuid.UUID | None,
    session_id: uuid.UUID | None,
    note: str | None,
    amount: int | None = None,
) -> ItemOperationResult:
    details = normalize_description(note)
    count = normalize_quantity(amount) if operation == "consume" and amount is not None else None
    points = (
        normalize_percentage_amount(amount)
        if operation in ("damage", "repair") and amount is not None
        else None
    )
    scope, time_id = _scope_and_time(
        connection,
        campaign_id=campaign_id,
        actor_user_id=actor_user_id,
        world_time_id=world_time_id,
        session_id=session_id,
    )
    ctx = _begin(
        connection,
        world_id=scope.world_id,
        timeline_id=scope.timeline_id,
        campaign_id=campaign_id,
        item_id=item_instance_id,
        expected=expected_last_event_id,
    )
    _require_live(ctx)
    s = ctx.state
    before = s.snapshot()
    participants: tuple[EventParticipant, ...] = ()

    if operation in ("equip", "unequip"):
        if ctx.entry.holder_entity_id is None:
            raise ItemNotHeldError(f"item {item_instance_id} is not carried")
        if s.is_equipped == (operation == "equip"):
            raise ItemOperationInvalidError(f"item is already {operation}ped")
        s.is_equipped = operation == "equip"
        participants = (EventParticipant(entity_id=ctx.entry.holder_entity_id, role_code="actor"),)
    elif operation == "consume":
        used = count or 1
        if used > s.quantity:
            raise ItemOperationInvalidError("there is not that much to use")
        s.quantity -= used
        if s.quantity == 0:
            if ctx.attunement_id is not None:
                raise ItemAttunedError(f"item {item_instance_id} is attuned")
            s.is_destroyed = True
            s.is_equipped = False
    elif operation == "damage":
        current = 100 if s.condition_percentage is None else s.condition_percentage
        if current == 0:
            raise ItemOperationInvalidError("the item cannot be damaged further")
        s.condition_percentage = max(0, current - (points or 0))
    elif operation == "repair":
        current = 100 if s.condition_percentage is None else s.condition_percentage
        if current == 100:
            raise ItemOperationInvalidError("the item is not damaged")
        s.condition_percentage = min(100, current + (points or 0))
    elif operation == "destroy":
        if ctx.attunement_id is not None:
            raise ItemAttunedError(f"item {item_instance_id} is attuned")
        s.is_destroyed = True
        s.is_equipped = False
    else:  # pragma: no cover - the callers below fix the operation names
        raise ValueError(operation)

    event_id = _record(
        ctx,
        operation,
        time_id=time_id,
        session_id=session_id,
        note=details,
        participants=participants,
    )
    _write_state(ctx, event_id, time_id, before)
    return _result(ctx, event_id, operation, dict(before), dict(s.snapshot()))


def equip_item(connection: Connection, **kwargs: Any) -> ItemOperationResult:
    return _state_operation(connection, operation="equip", **kwargs)


def unequip_item(connection: Connection, **kwargs: Any) -> ItemOperationResult:
    return _state_operation(connection, operation="unequip", **kwargs)


def consume_item(connection: Connection, **kwargs: Any) -> ItemOperationResult:
    return _state_operation(connection, operation="consume", **kwargs)


def damage_item(connection: Connection, **kwargs: Any) -> ItemOperationResult:
    return _state_operation(connection, operation="damage", **kwargs)


def repair_item(connection: Connection, **kwargs: Any) -> ItemOperationResult:
    return _state_operation(connection, operation="repair", **kwargs)


def destroy_item(connection: Connection, **kwargs: Any) -> ItemOperationResult:
    return _state_operation(connection, operation="destroy", **kwargs)


def attune_item(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    item_instance_id: uuid.UUID,
    character_id: uuid.UUID,
    expected_last_event_id: uuid.UUID | None,
    world_time_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    note: str | None = None,
) -> ItemOperationResult:
    details = normalize_description(note)
    scope, time_id = _scope_and_time(
        connection,
        campaign_id=campaign_id,
        actor_user_id=actor_user_id,
        world_time_id=world_time_id,
        session_id=session_id,
    )
    # Serialize one character's attunements (the three-item limit) before any row lock.
    connection.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
        {"k": f"campaign.item_attunement:{scope.timeline_id}:{character_id}"},
    )
    ctx = _begin(
        connection,
        world_id=scope.world_id,
        timeline_id=scope.timeline_id,
        campaign_id=campaign_id,
        item_id=item_instance_id,
        others=(character_id,),
        expected=expected_last_event_id,
    )
    _require_live(ctx)
    _require_world_entity(connection, scope.world_id, character_id, HOLDER_TYPE_CODES)
    if not ctx.requires_attunement or ctx.attunement_id is not None:
        raise AttunementNotAllowedError(f"item {item_instance_id} cannot be attuned")
    if ctx.entry.holder_entity_id != character_id:
        raise ItemNotHeldError(f"item {item_instance_id} is not carried by {character_id}")
    active = connection.execute(
        text("""
            SELECT count(*) FROM campaign.item_attunements
            WHERE timeline_id = :t AND character_id = :c AND broken_world_time_id IS NULL
        """),
        {"t": scope.timeline_id, "c": character_id},
    ).scalar()
    if int(active or 0) >= MAX_ATTUNEMENTS_PER_CHARACTER:
        raise AttunementNotAllowedError(f"character {character_id} is at the attunement limit")
    event_id = _record(
        ctx,
        "attune",
        time_id=time_id,
        session_id=session_id,
        note=details,
        participants=(EventParticipant(entity_id=character_id, role_code="actor"),),
    )
    before = ctx.state.snapshot()
    connection.execute(
        text("""
            INSERT INTO campaign.item_attunements
                (timeline_id, item_instance_id, character_id, attuned_world_time_id, last_event_id)
            VALUES (:t, :i, :c, :w, :e)
        """),
        {
            "t": scope.timeline_id,
            "i": item_instance_id,
            "c": character_id,
            "w": time_id,
            "e": event_id,
        },
    )
    _effect(
        ctx,
        event_id=event_id,
        time_id=time_id,
        component="item_attuned",
        previous=None,
        new={"character_id": str(character_id)},
    )
    _write_state(ctx, event_id, time_id, before)
    return _result(
        ctx,
        event_id,
        "attune",
        {"attuned_character_id": None},
        {"attuned_character_id": str(character_id)},
    )


def end_item_attunement(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    item_instance_id: uuid.UUID,
    expected_last_event_id: uuid.UUID | None,
    world_time_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    note: str | None = None,
) -> ItemOperationResult:
    details = normalize_description(note)
    scope, time_id = _scope_and_time(
        connection,
        campaign_id=campaign_id,
        actor_user_id=actor_user_id,
        world_time_id=world_time_id,
        session_id=session_id,
    )
    ctx = _begin(
        connection,
        world_id=scope.world_id,
        timeline_id=scope.timeline_id,
        campaign_id=campaign_id,
        item_id=item_instance_id,
        expected=expected_last_event_id,
    )
    if ctx.attunement_id is None or ctx.attuned_character_id is None:
        raise AttunementNotAllowedError(f"item {item_instance_id} is not attuned")
    ordered = connection.execute(
        text("""
            SELECT (SELECT sort_key FROM core.world_times WHERE world_time_id = :end)
                   >  (SELECT sort_key FROM core.world_times wt
                       JOIN campaign.item_attunements a ON a.attuned_world_time_id = wt.world_time_id
                       WHERE a.item_attunement_id = :a)
        """),
        {"end": time_id, "a": ctx.attunement_id},
    ).scalar()
    if ordered is False:
        raise ItemOperationInvalidError("the attunement must end after it began")
    character_id = ctx.attuned_character_id
    event_id = _record(
        ctx,
        "end_attunement",
        time_id=time_id,
        session_id=session_id,
        note=details,
        participants=(EventParticipant(entity_id=character_id, role_code="actor"),),
    )
    before = ctx.state.snapshot()
    connection.execute(
        text("""
            UPDATE campaign.item_attunements
            SET broken_world_time_id = :w, last_event_id = :e
            WHERE item_attunement_id = :a
        """),
        {"w": time_id, "e": event_id, "a": ctx.attunement_id},
    )
    _effect(
        ctx,
        event_id=event_id,
        time_id=time_id,
        component="item_attunement_ended",
        previous={"character_id": str(character_id)},
        new=None,
    )
    _write_state(ctx, event_id, time_id, before)
    return _result(
        ctx,
        event_id,
        "end_attunement",
        {"attuned_character_id": str(character_id)},
        {"attuned_character_id": None},
    )
