"""Assess, void, and correct recorded events (Phase 15 checkpoint 15.2E-1, decision D-15).

`assess_event` is read-only: for each effect of an event it says whether the effect can be
reversed *now* (the state it produced is still there, and a reversal exists for its kind).
`void_event` and `correct_event` apply the compensation and relink atomically, in one
transaction:

1. record a correcting event (`administrative_correction`, at the original event's own
   world time, citing it as its cause) and a compensating `narrative.event_effects` row
   for every reversed effect;
2. write the reversals (hit points, the active build, a party membership);
3. for a correction, record the replacement event;
4. insert the `narrative.event_corrections` link;
5. move the original from `recorded` to `voided` / `corrected` (the deferred database
   trigger refuses the move without the link).

Nothing is reversed unless every effect is reversible. Originals are never edited or
deleted; `campaign.effective_events()` already ignores events that are not `recorded`, so
effect-derived resolution (the active build, for example) stops seeing a voided event on
its own. Events reachable here are those of the campaign's own timeline only.

Lock order: operation scope (world, membership rows, account, campaign `FOR SHARE`), the
event row `FOR UPDATE`, then the state rows the reversals touch (`FOR UPDATE`).
"""

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Connection, text

from dnd_ai.domain.authoring import normalize_reason
from dnd_ai.domain.data_classification import audit_change, audit_initial
from dnd_ai.domain.event_corrections import (
    CORRECTING_EVENT_TYPE,
    CORRECTION_CORRECT,
    CORRECTION_VOID,
    REASON_NOT_APPLIED,
    REASON_STATE_CHANGED,
    REASON_UNSUPPORTED,
    REVERSIBLE_COMPONENTS,
    CorrectionNotReversibleError,
    EventAlreadyCorrectedError,
    EventNotCorrectableError,
    EventNotFoundError,
    normalize_event_text,
    require_recordable_type,
)
from dnd_ai.domain.knowledge_runtime import BELIEF_COMPONENTS

from ._operations import OperationScope, lock_operation_scope
from ._shared import lookup_id
from .events import EventParticipant, _insert_event_row

# Quest and objective status effects are undone through the state row the event last wrote:
# component -> (state table, status lookup table, status column).
_RUNTIME_STATE = {
    "quest_status_id": ("quest_state", "quest_statuses", "quest_status_id"),
    "objective_status_id": ("objective_state", "objective_statuses", "objective_status_id"),
}


# Knowledge effects are undone through the rows the event wrote, found by event provenance:
# component -> [(table, provenance column)]. The first entry is the state row whose
# `last_event_id` says nothing has written it since; the rest are history rows removed with it.
_PROVENANCE_ROWS = {
    "knowledge_learned": [
        ("knowledge.entity_knowledge", "last_event_id"),
        ("knowledge.information_transfers", "caused_by_event_id"),
    ],
    "knowledge_public": [("knowledge.public_knowledge", "last_event_id")],
    "party_discovered": [("knowledge.party_discoveries", "discovered_via_event_id")],
    "awareness_level": [("campaign.party_knowledge", "last_event_id")],
}
_BELIEF_COLUMNS = {component: column for column, component in BELIEF_COMPONENTS.items()}


# Item effects are undone through the item's own rows. `campaign.item_state.last_event_id` is the
# item's single token (every item operation writes it), so any item effect is reversible only
# while that row still names the event, whichever table the effect changed.
_ITEM_COMPONENTS = frozenset(
    {
        "item_state",
        "inventory_entries.location",
        "item_ownership",
        "item_attuned",
        "item_attunement_ended",
    }
)
_ITEM_STATE_COLUMNS = ("quantity", "condition_percentage", "is_equipped", "is_destroyed")


# Dungeon state effects are undone through the state row the event last wrote:
# component -> (state table, key column, effect target column, status lookup, column).
_DUNGEON_STATE = {
    "location_is_searched": (
        "location_state",
        "location_id",
        "target_entity_id",
        None,
        "is_searched",
    ),
    "location_is_destroyed": (
        "location_state",
        "location_id",
        "target_entity_id",
        None,
        "is_destroyed",
    ),
    "location_alarm_level": (
        "location_state",
        "location_id",
        "target_entity_id",
        None,
        "alarm_level",
    ),
    "location_condition_notes": (
        "location_state",
        "location_id",
        "target_entity_id",
        None,
        "condition_notes",
    ),
    "connection_status_id": (
        "area_connection_state",
        "area_connection_id",
        "target_area_connection_id",
        ("connection_statuses", "connection_status_id"),
        "connection_status_id",
    ),
    "hazard_status_id": (
        "hazard_state",
        "area_hazard_id",
        "target_area_hazard_id",
        ("hazard_statuses", "hazard_status_id"),
        "hazard_status_id",
    ),
    "interactable_status_id": (
        "interactable_state",
        "area_interactable_id",
        "target_area_interactable_id",
        ("interactable_statuses", "interactable_status_id"),
        "interactable_status_id",
    ),
    "organization_status_id": (
        "organization_state",
        "organization_id",
        "target_entity_id",
        ("organization_statuses", "organization_status_id"),
        "organization_status_id",
    ),
    "feature_is_destroyed": (
        "area_feature_state",
        "area_feature_id",
        "target_area_feature_id",
        None,
        "is_destroyed",
    ),
    "feature_condition_notes": (
        "area_feature_state",
        "area_feature_id",
        "target_area_feature_id",
        None,
        "condition_notes",
    ),
}
_AREA_TARGETS = (
    "target_area_connection_id",
    "target_area_feature_id",
    "target_area_hazard_id",
    "target_area_interactable_id",
)


@dataclass(frozen=True)
class EffectAssessment:
    event_effect_id: uuid.UUID
    component: str
    target_entity_id: uuid.UUID | None
    previous: Any
    new: Any
    reversible: bool
    reason: str | None
    target_quest_objective_id: uuid.UUID | None = None
    target_knowledge_item_id: uuid.UUID | None = None
    area_targets: dict[str, uuid.UUID] | None = None


@dataclass(frozen=True)
class EventAssessment:
    event_id: uuid.UUID
    event_type_code: str
    status: str
    world_time_id: uuid.UUID
    name: str
    effects: list[EffectAssessment] = field(default_factory=list)

    @property
    def can_correct(self) -> bool:
        return (
            self.status == "recorded"
            and self.event_type_code != CORRECTING_EVENT_TYPE
            and all(e.reversible for e in self.effects)
        )


@dataclass(frozen=True)
class CorrectionResult:
    event_id: uuid.UUID
    world_id: uuid.UUID
    correction_id: uuid.UUID
    correcting_event_id: uuid.UUID
    replacement_event_id: uuid.UUID | None
    kind: str
    new_status: str
    changed_fields: dict[str, object]


def _locked_event(
    connection: Connection, *, timeline_id: uuid.UUID, event_id: uuid.UUID, lock: bool
) -> tuple[Any, str, str, str]:
    """The event row (locked without a join), then its status, type, and name."""
    row = connection.execute(
        text(
            "SELECT e.event_id, e.event_status_id, e.event_type_id, e.world_time_id "
            "FROM narrative.events e WHERE e.event_id = :e AND e.timeline_id = :t"
            + (" FOR UPDATE OF e" if lock else "")
        ),
        {"e": event_id, "t": timeline_id},
    ).one_or_none()
    if row is None:
        raise EventNotFoundError(f"event {event_id} is not on timeline {timeline_id}")
    status = connection.execute(
        text("SELECT code FROM narrative.event_statuses WHERE event_status_id = :s"),
        {"s": row.event_status_id},
    ).scalar()
    type_code = connection.execute(
        text("SELECT code FROM narrative.event_types WHERE event_type_id = :s"),
        {"s": row.event_type_id},
    ).scalar()
    name = connection.execute(
        text("SELECT canonical_name FROM core.entities WHERE entity_id = :e"), {"e": event_id}
    ).scalar()
    return row, str(status), str(type_code), str(name)


def _assess_effect(
    connection: Connection,
    *,
    timeline_id: uuid.UUID,
    event_id: uuid.UUID,
    effect: Any,
    lock: bool,
) -> EffectAssessment:
    base = {
        "event_effect_id": effect.event_effect_id,
        "component": str(effect.target_component),
        "target_entity_id": effect.target_entity_id,
        "target_quest_objective_id": effect.target_quest_objective_id,
        "target_knowledge_item_id": effect.target_knowledge_item_id,
        "area_targets": {
            column: getattr(effect, column)
            for column in _AREA_TARGETS
            if getattr(effect, column) is not None
        }
        or None,
        "previous": effect.previous_value,
        "new": effect.new_value,
    }
    suffix = " FOR UPDATE" if lock else ""
    if effect.application_status != "applied":
        return EffectAssessment(**base, reversible=False, reason=REASON_NOT_APPLIED)
    component = str(effect.target_component)
    if component in _ITEM_COMPONENTS:
        item = effect.target_entity_id
        ok = False
        if item is not None:
            if lock:
                # The item row first, the order every item operation takes.
                connection.execute(
                    text(
                        "SELECT 1 FROM world.item_instances WHERE item_instance_id = :i FOR UPDATE"
                    ),
                    {"i": item},
                )
            ok = (
                connection.execute(
                    text(
                        "SELECT 1 FROM campaign.item_state "
                        "WHERE timeline_id = :t AND item_instance_id = :i AND last_event_id = :e"
                        + suffix
                    ),
                    {"t": timeline_id, "i": item, "e": event_id},
                ).scalar()
                is not None
            )
        return EffectAssessment(**base, reversible=ok, reason=None if ok else REASON_STATE_CHANGED)
    if component in _RUNTIME_STATE:
        table = _RUNTIME_STATE[component][0]
        # The state row the event wrote is still the latest write of its scope.
        ok = (
            connection.execute(
                text(
                    f"SELECT 1 FROM campaign.{table} "  # noqa: S608 - fixed table names
                    f"WHERE last_event_id = :e AND timeline_id = :t" + suffix
                ),
                {"e": event_id, "t": timeline_id},
            ).scalar()
            is not None
        )
        return EffectAssessment(**base, reversible=ok, reason=None if ok else REASON_STATE_CHANGED)
    if component in _DUNGEON_STATE:
        table, key, target_column, _lookup, _column = _DUNGEON_STATE[component]
        target = getattr(effect, target_column)
        ok = (
            target is not None
            and connection.execute(
                text(
                    f"SELECT 1 FROM campaign.{table} "  # noqa: S608 - fixed table names
                    f"WHERE {key} = :k AND last_event_id = :e AND timeline_id = :t" + suffix
                ),
                {"k": target, "e": event_id, "t": timeline_id},
            ).scalar()
            is not None
        )
        return EffectAssessment(**base, reversible=ok, reason=None if ok else REASON_STATE_CHANGED)
    if component in _PROVENANCE_ROWS or component in _BELIEF_COLUMNS:
        table, column = (
            _PROVENANCE_ROWS[component][0]
            if component in _PROVENANCE_ROWS
            else ("knowledge.entity_knowledge", "last_event_id")
        )
        ok = (
            connection.execute(
                text(
                    f"SELECT 1 FROM {table} "  # noqa: S608 - fixed table names
                    f"WHERE {column} = :e AND timeline_id = :t" + suffix
                ),
                {"e": event_id, "t": timeline_id},
            ).scalar()
            is not None
        )
        return EffectAssessment(**base, reversible=ok, reason=None if ok else REASON_STATE_CHANGED)
    if component not in REVERSIBLE_COMPONENTS or effect.target_entity_id is None:
        return EffectAssessment(**base, reversible=False, reason=REASON_UNSUPPORTED)
    character = effect.target_entity_id
    if component == "current_hit_points":
        current = connection.execute(
            text(
                "SELECT current_hit_points FROM campaign.character_state "
                "WHERE timeline_id = :t AND character_id = :c" + suffix
            ),
            {"t": timeline_id, "c": character},
        ).scalar()
        ok = current is not None and current == effect.new_value
    elif component == "character_build_id":
        row = connection.execute(
            text(
                "SELECT character_build_id FROM campaign.character_state "
                "WHERE timeline_id = :t AND character_id = :c" + suffix
            ),
            {"t": timeline_id, "c": character},
        ).one_or_none()
        ok = row is not None and (
            (None if row.character_build_id is None else str(row.character_build_id))
            == effect.new_value
        )
    else:  # party_membership
        if effect.new_value is not None:  # a join: the open membership it created
            ok = (
                connection.execute(
                    text(
                        "SELECT 1 FROM campaign.party_memberships WHERE joined_event_id = :e "
                        "AND timeline_id = :t AND effective_to_world_time_id IS NULL" + suffix
                    ),
                    {"e": event_id, "t": timeline_id},
                ).scalar()
                is not None
            )
        else:  # a leave: reopenable only if nothing overlaps the reopened period
            row = connection.execute(
                text(
                    "SELECT party_membership_id, party_id, member_entity_id, "
                    "lower(effective_period) AS start_key FROM campaign.party_memberships "
                    "WHERE left_event_id = :e AND timeline_id = :t" + suffix
                ),
                {"e": event_id, "t": timeline_id},
            ).one_or_none()
            ok = row is not None and (
                connection.execute(
                    text("""
                        SELECT 1 FROM campaign.party_memberships
                        WHERE timeline_id = :t AND party_id = :p AND member_entity_id = :m
                          AND party_membership_id <> :id
                          AND effective_period && int8range(:start, NULL, '[)')
                        LIMIT 1
                    """),
                    {
                        "t": timeline_id,
                        "p": row.party_id,
                        "m": row.member_entity_id,
                        "id": row.party_membership_id,
                        "start": row.start_key,
                    },
                ).scalar()
                is None
            )
    return EffectAssessment(**base, reversible=ok, reason=None if ok else REASON_STATE_CHANGED)


def assess_event(
    connection: Connection, *, timeline_id: uuid.UUID, event_id: uuid.UUID, lock: bool = False
) -> EventAssessment:
    """Read-only unless `lock` (then the event row and the state rows it would touch are
    locked `FOR UPDATE`, which is how the correction commands call it)."""
    row, status, type_code, name = _locked_event(
        connection, timeline_id=timeline_id, event_id=event_id, lock=lock
    )
    effects = connection.execute(
        text(
            "SELECT event_effect_id, target_entity_id, target_quest_objective_id, "
            "target_knowledge_item_id, target_area_connection_id, target_area_feature_id, "
            "target_area_hazard_id, target_area_interactable_id, target_component, previous_value, "
            "new_value, application_status FROM narrative.event_effects "
            "WHERE event_id = :e ORDER BY created_at, event_effect_id"
        ),
        {"e": event_id},
    ).all()
    return EventAssessment(
        event_id=event_id,
        event_type_code=type_code,
        status=status,
        world_time_id=row.world_time_id,
        name=name,
        effects=[
            _assess_effect(
                connection, timeline_id=timeline_id, event_id=event_id, effect=e, lock=lock
            )
            for e in effects
        ],
    )


def _compensate(
    connection: Connection,
    *,
    timeline_id: uuid.UUID,
    event_id: uuid.UUID,
    correcting_event_id: uuid.UUID,
    world_time_id: uuid.UUID,
    effect: EffectAssessment,
) -> None:
    character = effect.target_entity_id
    if effect.component in _ITEM_COMPONENTS:
        _compensate_item(
            connection,
            timeline_id=timeline_id,
            event_id=event_id,
            correcting_event_id=correcting_event_id,
            effect=effect,
        )
    elif effect.component in _RUNTIME_STATE:
        table, status_table, status_column = _RUNTIME_STATE[effect.component]
        if effect.previous is None:  # the state did not exist before the event
            connection.execute(
                text(f"DELETE FROM campaign.{table} WHERE last_event_id = :e AND timeline_id = :t"),  # noqa: S608
                {"e": event_id, "t": timeline_id},
            )
        else:
            connection.execute(
                text(
                    f"UPDATE campaign.{table} SET {status_column} = "  # noqa: S608
                    f"(SELECT {status_column} FROM campaign.{status_table} WHERE code = :v), "
                    "last_event_id = :c, updated_at = now() "
                    "WHERE last_event_id = :e AND timeline_id = :t"
                ),
                {"v": effect.previous, "c": correcting_event_id, "e": event_id, "t": timeline_id},
            )
    elif effect.component in _DUNGEON_STATE:
        table, key, target_column, lookup, column = _DUNGEON_STATE[effect.component]
        target = (
            effect.target_entity_id
            if target_column == "target_entity_id"
            else (effect.area_targets or {}).get(target_column)
        )
        if lookup is not None and effect.previous is None:  # the state did not exist before
            connection.execute(
                text(  # noqa: S608 - fixed table and key names
                    f"DELETE FROM campaign.{table} WHERE {key} = :k AND timeline_id = :t "
                    "AND last_event_id IN (:e, :c)"
                ),
                {"k": target, "t": timeline_id, "e": event_id, "c": correcting_event_id},
            )
        else:
            value_sql = (
                f"(SELECT {lookup[1]} FROM campaign.{lookup[0]} WHERE code = :v)"
                if lookup is not None
                else ":v"
            )
            connection.execute(
                text(  # noqa: S608 - fixed table, key and column names
                    f"UPDATE campaign.{table} SET {column} = {value_sql}, last_event_id = :c, "
                    f"updated_at = now() WHERE {key} = :k AND timeline_id = :t "
                    "AND last_event_id IN (:e, :c)"
                ),
                {
                    "v": effect.previous,
                    "k": target,
                    "t": timeline_id,
                    "e": event_id,
                    "c": correcting_event_id,
                },
            )
    elif effect.component in _PROVENANCE_ROWS:
        for table, column in _PROVENANCE_ROWS[effect.component]:
            connection.execute(
                text(f"DELETE FROM {table} WHERE {column} = :e AND timeline_id = :t"),  # noqa: S608
                {"e": event_id, "t": timeline_id},
            )
    elif effect.component in _BELIEF_COLUMNS:
        connection.execute(
            text(  # noqa: S608 - the column comes from the fixed belief mapping
                f"UPDATE knowledge.entity_knowledge SET {_BELIEF_COLUMNS[effect.component]} = :v, "
                "last_event_id = :c, updated_at = now() "
                "WHERE last_event_id IN (:e, :c) AND timeline_id = :t"
            ),
            {"v": effect.previous, "c": correcting_event_id, "e": event_id, "t": timeline_id},
        )
    elif effect.component == "current_hit_points":
        connection.execute(
            text(
                "UPDATE campaign.character_state SET current_hit_points = :v, "
                "last_event_id = :e, updated_at = now() "
                "WHERE timeline_id = :t AND character_id = :c"
            ),
            {"v": effect.previous, "e": correcting_event_id, "t": timeline_id, "c": character},
        )
    elif effect.component == "character_build_id":
        connection.execute(
            text(
                "UPDATE campaign.character_state SET character_build_id = :v, "
                "last_event_id = :e, updated_at = now() "
                "WHERE timeline_id = :t AND character_id = :c"
            ),
            {"v": effect.previous, "e": correcting_event_id, "t": timeline_id, "c": character},
        )
    elif effect.new is not None:  # undo a join: the membership never happened
        party_id = connection.execute(
            text(
                "DELETE FROM campaign.party_memberships WHERE joined_event_id = :e "
                "AND timeline_id = :t RETURNING party_id"
            ),
            {"e": event_id, "t": timeline_id},
        ).scalar()
        _bump_party(connection, party_id)
    else:  # undo a leave: the member is still in the party
        party_id = connection.execute(
            text(
                "UPDATE campaign.party_memberships SET effective_to_world_time_id = NULL, "
                "left_event_id = NULL, left_reason = NULL WHERE left_event_id = :e "
                "AND timeline_id = :t RETURNING party_id"
            ),
            {"e": event_id, "t": timeline_id},
        ).scalar()
        _bump_party(connection, party_id)
    connection.execute(
        text("""
            INSERT INTO narrative.event_effects
                (event_id, target_entity_id, target_quest_objective_id,
                 target_knowledge_item_id, target_area_connection_id, target_area_feature_id,
                 target_area_hazard_id, target_area_interactable_id, target_component,
                 previous_value, new_value, effective_world_time_id)
            VALUES (:e, :c, :o, :k, :ac, :af, :ah, :ai, :component, CAST(:previous AS jsonb),
                    CAST(:new AS jsonb), :time)
        """),
        {
            "e": correcting_event_id,
            "c": character,
            "o": effect.target_quest_objective_id,
            "k": effect.target_knowledge_item_id,
            "ac": (effect.area_targets or {}).get("target_area_connection_id"),
            "af": (effect.area_targets or {}).get("target_area_feature_id"),
            "ah": (effect.area_targets or {}).get("target_area_hazard_id"),
            "ai": (effect.area_targets or {}).get("target_area_interactable_id"),
            "component": effect.component,
            "previous": None if effect.new is None else json.dumps(effect.new),
            "new": None if effect.previous is None else json.dumps(effect.previous),
            "time": world_time_id,
        },
    )


def _compensate_item(
    connection: Connection,
    *,
    timeline_id: uuid.UUID,
    event_id: uuid.UUID,
    correcting_event_id: uuid.UUID,
    effect: EffectAssessment,
) -> None:
    """Put one item component back. The `item_state` component also restores the item's token."""
    item = effect.target_entity_id
    keys = {"t": timeline_id, "i": item, "e": event_id, "c": correcting_event_id}
    previous = effect.previous
    component = effect.component
    if component == "item_state":
        assert isinstance(previous, dict)
        connection.execute(
            text(
                "UPDATE campaign.item_state SET quantity = :q, condition_percentage = :cp, "
                "is_equipped = :eq, is_destroyed = :d, "
                "last_event_id = CAST(:token AS uuid), updated_at = now() "
                "WHERE timeline_id = :t AND item_instance_id = :i"
            ),
            {
                **keys,
                "q": previous["quantity"],
                "cp": previous["condition_percentage"],
                "eq": previous["is_equipped"],
                "d": previous["is_destroyed"],
                # The token goes back to the item's previous event, so that event can be
                # corrected next.
                "token": previous["last_event_id"],
            },
        )
    elif component == "inventory_entries.location":
        place = previous if isinstance(previous, dict) else {}
        connection.execute(
            text(
                "UPDATE campaign.inventory_entries SET holder_entity_id = :h, container_id = :k, "
                "location_id = :l, last_event_id = :c, updated_at = now() "
                "WHERE timeline_id = :t AND item_instance_id = :i"
            ),
            {
                **keys,
                "h": place.get("holder_entity_id"),
                "k": place.get("container_id"),
                "l": place.get("location_id"),
            },
        )
    elif component == "item_ownership":
        if previous is None:  # the row did not exist before the event
            connection.execute(
                text(
                    "DELETE FROM campaign.item_ownership "
                    "WHERE timeline_id = :t AND item_instance_id = :i"
                ),
                keys,
            )
        else:
            assert isinstance(previous, dict)
            connection.execute(
                text(
                    "UPDATE campaign.item_ownership SET owner_entity_id = :o, "
                    "last_event_id = :c, updated_at = now() "
                    "WHERE timeline_id = :t AND item_instance_id = :i"
                ),
                {**keys, "o": previous.get("owner_entity_id")},
            )
    elif component == "item_attuned":
        # The attunement never happened. Nothing later is in force (the token named this event),
        # so the item's active attunement is the one this event made.
        connection.execute(
            text(
                "DELETE FROM campaign.item_attunements WHERE timeline_id = :t "
                "AND item_instance_id = :i AND broken_world_time_id IS NULL"
            ),
            keys,
        )
    else:  # item_attunement_ended: the character is still attuned
        connection.execute(
            text(
                "UPDATE campaign.item_attunements SET broken_world_time_id = NULL, "
                "last_event_id = :c, updated_at = now() "
                "WHERE timeline_id = :t AND item_instance_id = :i AND last_event_id = :e"
            ),
            keys,
        )


def _bump_party(connection: Connection, party_id: uuid.UUID | None) -> None:
    if party_id is not None:
        connection.execute(
            text("UPDATE campaign.parties SET updated_at = now() WHERE party_id = :p"),
            {"p": party_id},
        )


def _apply(
    connection: Connection,
    *,
    scope: OperationScope,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    event_id: uuid.UUID,
    kind: str,
    reason: str | None,
    replacement: dict[str, Any] | None,
) -> CorrectionResult:
    clean_reason = normalize_reason(reason, required=True)
    assert clean_reason is not None
    assessment = assess_event(
        connection, timeline_id=scope.timeline_id, event_id=event_id, lock=True
    )
    if assessment.status != "recorded":
        raise EventAlreadyCorrectedError(f"event {event_id} is {assessment.status}")
    if assessment.event_type_code == CORRECTING_EVENT_TYPE:
        raise EventNotCorrectableError(f"event {event_id} is a correction")
    if not assessment.can_correct:
        raise CorrectionNotReversibleError(f"event {event_id} has irreversible effects")

    correcting_event_id = _insert_event_row(
        connection,
        world_id=scope.world_id,
        timeline_id=scope.timeline_id,
        world_time_id=assessment.world_time_id,
        event_type_code=CORRECTING_EVENT_TYPE,
        name="A recorded event was corrected",
        campaign_id=campaign_id,
        cause_event_id=event_id,
    )
    for effect in assessment.effects:
        _compensate(
            connection,
            timeline_id=scope.timeline_id,
            event_id=event_id,
            correcting_event_id=correcting_event_id,
            world_time_id=assessment.world_time_id,
            effect=effect,
        )
    replacement_event_id: uuid.UUID | None = None
    if kind == CORRECTION_CORRECT:
        assert replacement is not None
        name, details = normalize_event_text(replacement["name"], replacement.get("details"))
        require_recordable_type(replacement["event_type_code"])
        replacement_event_id = _insert_event_row(
            connection,
            world_id=scope.world_id,
            timeline_id=scope.timeline_id,
            world_time_id=replacement.get("world_time_id") or assessment.world_time_id,
            event_type_code=replacement["event_type_code"],
            name=name,
            details=details,
            campaign_id=campaign_id,
            participants=tuple(
                EventParticipant(entity_id=c, role_code="actor")
                for c in replacement.get("character_ids", ())
            ),
            cause_event_id=correcting_event_id,
        )
    correction_id = connection.execute(
        text("""
            INSERT INTO narrative.event_corrections
                (corrected_event_id, correcting_event_id, replacement_event_id,
                 correction_kind, reason, created_by_user_id)
            VALUES (:corrected, :correcting, :replacement, :kind, :reason, :user)
            RETURNING event_correction_id
        """),
        {
            "corrected": event_id,
            "correcting": correcting_event_id,
            "replacement": replacement_event_id,
            "kind": kind,
            "reason": clean_reason,
            "user": actor_user_id,
        },
    ).scalar()
    assert isinstance(correction_id, uuid.UUID)
    new_status = "voided" if kind == CORRECTION_VOID else "corrected"
    connection.execute(
        text("UPDATE narrative.events SET event_status_id = :s WHERE event_id = :e"),
        {
            "s": lookup_id(
                connection, "narrative", "event_statuses", "event_status_id", new_status
            ),
            "e": event_id,
        },
    )
    return CorrectionResult(
        event_id=event_id,
        world_id=scope.world_id,
        correction_id=correction_id,
        correcting_event_id=correcting_event_id,
        replacement_event_id=replacement_event_id,
        kind=kind,
        new_status=new_status,
        changed_fields={
            "event_status": audit_change("event_status", "recorded", new_status),
            **audit_initial({"correction_kind": kind, "reason": clean_reason}),
        },
    )


def void_event(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    event_id: uuid.UUID,
    reason: str | None,
) -> CorrectionResult:
    scope = lock_operation_scope(connection, campaign_id=campaign_id, actor_user_id=actor_user_id)
    return _apply(
        connection,
        scope=scope,
        campaign_id=campaign_id,
        actor_user_id=actor_user_id,
        event_id=event_id,
        kind=CORRECTION_VOID,
        reason=reason,
        replacement=None,
    )


def correct_event(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    event_id: uuid.UUID,
    reason: str | None,
    replacement: dict[str, Any],
) -> CorrectionResult:
    scope = lock_operation_scope(connection, campaign_id=campaign_id, actor_user_id=actor_user_id)
    return _apply(
        connection,
        scope=scope,
        campaign_id=campaign_id,
        actor_user_id=actor_user_id,
        event_id=event_id,
        kind=CORRECTION_CORRECT,
        reason=reason,
        replacement=replacement,
    )
