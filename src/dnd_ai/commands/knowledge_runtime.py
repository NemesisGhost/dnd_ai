"""Knowledge runtime commands (Phase 15 checkpoint 15.2E-3, decision D-17).

Who knows a claim is per-knower timeline state. These commands record it, each with one
causal event, its effect rows and the state rows, atomically, on the campaign's own
timeline (world time from the request or the campaign clock):

- `reveal_knowledge_to_party` wraps the existing party writer (`commands.knowledge`) in the
  authoring kernel; the party's discovery and its current belief land together.
- `record_character_knowledge` gives a character, NPC or organization its own belief.
- `record_knowledge_transfer` records one knower telling another (a transfer row plus the
  recipient's belief, with the interpretation actually conveyed).
- `change_belief` revises a belief (awareness, confidence, interpretation, willingness to
  share) without touching the claim's truth; the caller names the event that last wrote the
  row it saw (`expected_last_event_id`), and a row that moved is a stale write.
- `make_knowledge_public` makes a claim known at a location.

Lock order: operation scope, the claim and the named entities `FOR SHARE` in id order (so a
statement edit, which takes the claim `FOR UPDATE`, cannot interleave), a per-(timeline,
claim, knower) advisory lock that serializes the first write, then the belief row.
"""

import json
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection, text

from dnd_ai.domain.authoring import AuthoringValidationError, StaleWriteError
from dnd_ai.domain.data_classification import audit_change, audit_initial
from dnd_ai.domain.knowledge_runtime import (
    BELIEF_COMPONENTS,
    COMPONENT_LEARNED,
    COMPONENT_PUBLIC,
    KNOWER_TYPE_CODES,
    LOCATION_TYPE_CODES,
    TRANSFER_METHODS,
    AlreadyPublicError,
    KnowerAlreadyKnowsError,
    KnowerInvalidError,
    LocationInvalidError,
    SourceDoesNotKnowError,
    normalize_awareness,
    normalize_confidence,
    normalize_interpretation,
)

from ._content import lock_entities
from ._operations import OperationScope, lock_operation_scope
from ._shared import EntityNotTargetableError
from .events import EventParticipant, _insert_event_row
from .knowledge import _reveal_knowledge_to_party_impl
from .quest_runtime import time_or_clock


@dataclass(frozen=True)
class KnowledgeResult:
    world_id: uuid.UUID
    knowledge_item_id: uuid.UUID
    table: str
    record_id: uuid.UUID
    changed: bool
    event_id: uuid.UUID | None
    changed_fields: dict[str, object]
    knower_entity_id: uuid.UUID | None = None


def _lock_claim(
    connection: Connection,
    scope: OperationScope,
    knowledge_item_id: uuid.UUID,
    *others: uuid.UUID,
) -> dict[uuid.UUID, Any]:
    """Lock the claim and the other named entities `FOR SHARE`; the claim must be a
    published, active knowledge item of this world."""
    locked = lock_entities(
        connection, world_id=scope.world_id, share_ids=[knowledge_item_id, *others]
    )
    claim = locked.get(knowledge_item_id)
    if (
        claim is None
        or claim.entity_type_code != "knowledge_item"
        or claim.canon_status != "canon"
        or claim.lifecycle_status != "active"
    ):
        raise EntityNotTargetableError(f"knowledge item {knowledge_item_id} is not published")
    return locked


def _require_knower(locked: dict[uuid.UUID, Any], knower_id: uuid.UUID, *, what: str) -> None:
    knower = locked.get(knower_id)
    if (
        knower is None
        or knower.entity_type_code not in KNOWER_TYPE_CODES
        or knower.canon_status != "canon"
        or knower.lifecycle_status != "active"
    ):
        raise KnowerInvalidError(f"{what} {knower_id} cannot hold knowledge")


def _serialize(
    connection: Connection, scope: OperationScope, knowledge_item_id: uuid.UUID, key: object
) -> None:
    connection.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"knowledge.runtime:{scope.timeline_id}:{knowledge_item_id}:{key}"},
    )


def _effect(
    connection: Connection,
    *,
    event_id: uuid.UUID,
    world_time_id: uuid.UUID,
    component: str,
    previous: object,
    new: object,
    entity_id: uuid.UUID | None = None,
    knowledge_item_id: uuid.UUID | None = None,
) -> None:
    connection.execute(
        text("""
            INSERT INTO narrative.event_effects
                (event_id, target_entity_id, target_knowledge_item_id, target_component,
                 previous_value, new_value, effective_world_time_id)
            VALUES (:e, :entity, :item, :c, CAST(:previous AS jsonb), CAST(:new AS jsonb), :t)
        """),
        {
            "e": event_id,
            "entity": entity_id,
            "item": knowledge_item_id,
            "c": component,
            "previous": json.dumps(previous),
            "new": json.dumps(new),
            "t": world_time_id,
        },
    )


def reveal_knowledge_to_party(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    knowledge_item_id: uuid.UUID,
    party_id: uuid.UUID,
    awareness_level: str = "aware",
    world_time_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    note: str | None = None,
) -> KnowledgeResult:
    awareness = normalize_awareness(awareness_level)
    scope = lock_operation_scope(connection, campaign_id=campaign_id, actor_user_id=actor_user_id)
    _lock_claim(connection, scope, knowledge_item_id)
    time_id = time_or_clock(connection, scope, world_time_id)
    result = _reveal_knowledge_to_party_impl(
        connection,
        knowledge_item_id=knowledge_item_id,
        party_id=party_id,
        timeline_id=scope.timeline_id,
        world_time_id=time_id,
        awareness_level=awareness,
        campaign_id=campaign_id,
        session_id=session_id,
        event_details=note,
    )
    return KnowledgeResult(
        world_id=scope.world_id,
        knowledge_item_id=knowledge_item_id,
        table="party_knowledge",
        record_id=result.party_knowledge_id,
        changed=not result.already_known,
        event_id=result.event_id,
        changed_fields=(
            {}
            if result.already_known
            else audit_initial({"party_id": str(party_id), "awareness_level": awareness})
        ),
    )


def record_character_knowledge(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    knowledge_item_id: uuid.UUID,
    knower_entity_id: uuid.UUID,
    awareness_level: str = "aware",
    confidence: int | None = None,
    interpretation: str | None = None,
    willing_to_share: bool = True,
    world_time_id: uuid.UUID | None = None,
    note: str | None = None,
) -> KnowledgeResult:
    awareness = normalize_awareness(awareness_level)
    confident = normalize_confidence(confidence)
    belief = normalize_interpretation(interpretation)
    scope = lock_operation_scope(connection, campaign_id=campaign_id, actor_user_id=actor_user_id)
    locked = _lock_claim(connection, scope, knowledge_item_id, knower_entity_id)
    _require_knower(locked, knower_entity_id, what="knower")
    _serialize(connection, scope, knowledge_item_id, knower_entity_id)
    if _current_row(connection, scope, knowledge_item_id, knower_entity_id) is not None:
        raise KnowerAlreadyKnowsError(f"{knower_entity_id} already has {knowledge_item_id}")
    time_id = time_or_clock(connection, scope, world_time_id)
    event_id = _insert_event_row(
        connection,
        world_id=scope.world_id,
        timeline_id=scope.timeline_id,
        world_time_id=time_id,
        event_type_code="knowledge_learned",
        name="Knowledge learned",
        details=normalize_interpretation(note),
        campaign_id=campaign_id,
        participants=(EventParticipant(entity_id=knower_entity_id, role_code="target"),),
    )
    row_id = _insert_belief(
        connection,
        scope=scope,
        knowledge_item_id=knowledge_item_id,
        knower_entity_id=knower_entity_id,
        awareness=awareness,
        confidence=confident,
        interpretation=belief,
        willing_to_share=willing_to_share,
        time_id=time_id,
        event_id=event_id,
    )
    _effect(
        connection,
        event_id=event_id,
        world_time_id=time_id,
        component=COMPONENT_LEARNED,
        previous=None,
        new={"knowledge_item_id": str(knowledge_item_id), "awareness_level": awareness},
        entity_id=knower_entity_id,
    )
    return KnowledgeResult(
        world_id=scope.world_id,
        knowledge_item_id=knowledge_item_id,
        table="entity_knowledge",
        record_id=row_id,
        changed=True,
        event_id=event_id,
        knower_entity_id=knower_entity_id,
        changed_fields=audit_initial(
            {
                "knower_entity_id": str(knower_entity_id),
                "awareness_level": awareness,
                "confidence": confident,
                "interpretation": belief,
                "willing_to_share": willing_to_share,
            }
        ),
    )


def _current_row(
    connection: Connection,
    scope: OperationScope,
    knowledge_item_id: uuid.UUID,
    knower_entity_id: uuid.UUID,
    *,
    update: bool = False,
) -> Any:
    return connection.execute(
        text(
            "SELECT entity_knowledge_id, awareness_level, confidence, interpretation, "
            "willing_to_share, last_event_id FROM knowledge.entity_knowledge "
            "WHERE timeline_id = :t AND knowledge_item_id = :k AND knower_entity_id = :e"
            + (" FOR UPDATE" if update else " FOR SHARE")
        ),
        {"t": scope.timeline_id, "k": knowledge_item_id, "e": knower_entity_id},
    ).one_or_none()


def _insert_belief(
    connection: Connection,
    *,
    scope: OperationScope,
    knowledge_item_id: uuid.UUID,
    knower_entity_id: uuid.UUID,
    awareness: str,
    confidence: int | None,
    interpretation: str | None,
    willing_to_share: bool,
    time_id: uuid.UUID,
    event_id: uuid.UUID,
) -> uuid.UUID:
    row_id = connection.execute(
        text("""
            INSERT INTO knowledge.entity_knowledge
                (timeline_id, knowledge_item_id, knower_entity_id, awareness_level, confidence,
                 interpretation, learned_at_world_time_id, willing_to_share,
                 learned_via_event_id, last_event_id)
            VALUES (:t, :k, :e, :awareness, :confidence, :interpretation, :time, :willing,
                    :event, :event)
            RETURNING entity_knowledge_id
        """),
        {
            "t": scope.timeline_id,
            "k": knowledge_item_id,
            "e": knower_entity_id,
            "awareness": awareness,
            "confidence": confidence,
            "interpretation": interpretation,
            "time": time_id,
            "willing": willing_to_share,
            "event": event_id,
        },
    ).scalar()
    assert isinstance(row_id, uuid.UUID)
    return row_id


def record_knowledge_transfer(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    knowledge_item_id: uuid.UUID,
    source_entity_id: uuid.UUID,
    recipient_entity_id: uuid.UUID,
    transfer_method: str = "dialogue",
    awareness_level: str = "aware",
    modified_interpretation: str | None = None,
    world_time_id: uuid.UUID | None = None,
    note: str | None = None,
) -> KnowledgeResult:
    if transfer_method not in TRANSFER_METHODS:
        raise AuthoringValidationError("transfer_method is not a known method")
    if source_entity_id == recipient_entity_id:
        raise KnowerInvalidError("a knower cannot tell themselves")
    awareness = normalize_awareness(awareness_level)
    conveyed = normalize_interpretation(modified_interpretation)
    scope = lock_operation_scope(connection, campaign_id=campaign_id, actor_user_id=actor_user_id)
    locked = _lock_claim(
        connection, scope, knowledge_item_id, source_entity_id, recipient_entity_id
    )
    _require_knower(locked, source_entity_id, what="source")
    _require_knower(locked, recipient_entity_id, what="recipient")
    _serialize(connection, scope, knowledge_item_id, recipient_entity_id)
    source = _current_row(connection, scope, knowledge_item_id, source_entity_id)
    if source is None:
        raise SourceDoesNotKnowError(f"{source_entity_id} does not know {knowledge_item_id}")
    if _current_row(connection, scope, knowledge_item_id, recipient_entity_id) is not None:
        raise KnowerAlreadyKnowsError(f"{recipient_entity_id} already has {knowledge_item_id}")
    time_id = time_or_clock(connection, scope, world_time_id)
    event_id = _insert_event_row(
        connection,
        world_id=scope.world_id,
        timeline_id=scope.timeline_id,
        world_time_id=time_id,
        event_type_code="knowledge_transferred",
        name="Knowledge shared",
        details=normalize_interpretation(note),
        campaign_id=campaign_id,
        participants=(
            EventParticipant(entity_id=source_entity_id, role_code="actor"),
            EventParticipant(entity_id=recipient_entity_id, role_code="target"),
        ),
    )
    _insert_belief(
        connection,
        scope=scope,
        knowledge_item_id=knowledge_item_id,
        knower_entity_id=recipient_entity_id,
        awareness=awareness,
        confidence=None,
        interpretation=conveyed if conveyed is not None else source.interpretation,
        willing_to_share=True,
        time_id=time_id,
        event_id=event_id,
    )
    transfer_id = connection.execute(
        text("""
            INSERT INTO knowledge.information_transfers
                (timeline_id, source_entity_knowledge_id, recipient_entity_id,
                 modified_interpretation, transfer_method, caused_by_event_id,
                 occurred_at_world_time_id)
            VALUES (:t, :source, :recipient, :modified, :method, :event, :time)
            RETURNING information_transfer_id
        """),
        {
            "t": scope.timeline_id,
            "source": source.entity_knowledge_id,
            "recipient": recipient_entity_id,
            "modified": conveyed,
            "method": transfer_method,
            "event": event_id,
            "time": time_id,
        },
    ).scalar()
    assert isinstance(transfer_id, uuid.UUID)
    _effect(
        connection,
        event_id=event_id,
        world_time_id=time_id,
        component=COMPONENT_LEARNED,
        previous=None,
        new={"knowledge_item_id": str(knowledge_item_id), "awareness_level": awareness},
        entity_id=recipient_entity_id,
    )
    return KnowledgeResult(
        world_id=scope.world_id,
        knowledge_item_id=knowledge_item_id,
        table="information_transfers",
        record_id=transfer_id,
        changed=True,
        event_id=event_id,
        knower_entity_id=recipient_entity_id,
        changed_fields=audit_initial(
            {
                "knower_entity_id": str(source_entity_id),
                "recipient_entity_id": str(recipient_entity_id),
                "transfer_method": transfer_method,
                "awareness_level": awareness,
                "interpretation": conveyed,
            }
        ),
    )


def change_belief(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    entity_knowledge_id: uuid.UUID,
    expected_last_event_id: uuid.UUID | None,
    changes: dict[str, Any],
    world_time_id: uuid.UUID | None = None,
    note: str | None = None,
) -> KnowledgeResult:
    """Revise one belief. `changes` holds only the fields the caller sent, from
    `awareness_level`, `confidence`, `interpretation` and `willing_to_share`."""
    clean: dict[str, Any] = {}
    if "awareness_level" in changes:
        clean["awareness_level"] = normalize_awareness(changes["awareness_level"])
    if "confidence" in changes:
        clean["confidence"] = normalize_confidence(changes["confidence"])
    if "interpretation" in changes:
        clean["interpretation"] = normalize_interpretation(changes["interpretation"])
    if "willing_to_share" in changes:
        if not isinstance(changes["willing_to_share"], bool):
            raise AuthoringValidationError("willing_to_share must be true or false")
        clean["willing_to_share"] = changes["willing_to_share"]
    if not clean:
        raise AuthoringValidationError("send at least one belief field to change")

    scope = lock_operation_scope(connection, campaign_id=campaign_id, actor_user_id=actor_user_id)
    found = connection.execute(
        text(
            "SELECT knowledge_item_id, knower_entity_id FROM knowledge.entity_knowledge "
            "WHERE entity_knowledge_id = :id AND timeline_id = :t"
        ),
        {"id": entity_knowledge_id, "t": scope.timeline_id},
    ).one_or_none()
    if found is None:
        raise EntityNotTargetableError(f"belief {entity_knowledge_id} is not on this timeline")
    item_id, knower_id = found.knowledge_item_id, found.knower_entity_id
    locked = _lock_claim(connection, scope, item_id, knower_id)
    _require_knower(locked, knower_id, what="knower")
    _serialize(connection, scope, item_id, knower_id)
    row = _current_row(connection, scope, item_id, knower_id, update=True)
    if row is None:
        raise EntityNotTargetableError(f"belief {entity_knowledge_id} is gone")
    if row.last_event_id != expected_last_event_id:
        raise StaleWriteError(f"belief {entity_knowledge_id} changed")
    differing = {k: v for k, v in clean.items() if getattr(row, k) != v}
    if not differing:
        return KnowledgeResult(
            world_id=scope.world_id,
            knowledge_item_id=item_id,
            table="entity_knowledge",
            record_id=row.entity_knowledge_id,
            changed=False,
            event_id=None,
            changed_fields={},
            knower_entity_id=knower_id,
        )
    time_id = time_or_clock(connection, scope, world_time_id)
    event_id = _insert_event_row(
        connection,
        world_id=scope.world_id,
        timeline_id=scope.timeline_id,
        world_time_id=time_id,
        event_type_code="belief_changed",
        name="Belief changed",
        details=normalize_interpretation(note),
        campaign_id=campaign_id,
        participants=(EventParticipant(entity_id=knower_id, role_code="target"),),
    )
    assignments = ", ".join(f"{column} = :{column}" for column in differing)
    connection.execute(
        text(  # noqa: S608 - column names come from the fixed set above
            f"UPDATE knowledge.entity_knowledge SET {assignments}, last_event_id = :event, "
            "updated_at = now() WHERE entity_knowledge_id = :id"
        ),
        {**differing, "event": event_id, "id": row.entity_knowledge_id},
    )
    for column, value in differing.items():
        _effect(
            connection,
            event_id=event_id,
            world_time_id=time_id,
            component=BELIEF_COMPONENTS[column],
            previous=getattr(row, column),
            new=value,
            entity_id=knower_id,
        )
    return KnowledgeResult(
        world_id=scope.world_id,
        knowledge_item_id=item_id,
        table="entity_knowledge",
        record_id=row.entity_knowledge_id,
        changed=True,
        event_id=event_id,
        knower_entity_id=knower_id,
        changed_fields={
            column: audit_change(column, getattr(row, column), value)
            for column, value in differing.items()
        },
    )


def make_knowledge_public(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    knowledge_item_id: uuid.UUID,
    location_id: uuid.UUID,
    awareness_level: str = "aware",
    world_time_id: uuid.UUID | None = None,
    note: str | None = None,
) -> KnowledgeResult:
    awareness = normalize_awareness(awareness_level)
    scope = lock_operation_scope(connection, campaign_id=campaign_id, actor_user_id=actor_user_id)
    locked = _lock_claim(connection, scope, knowledge_item_id, location_id)
    place = locked.get(location_id)
    if (
        place is None
        or place.entity_type_code not in LOCATION_TYPE_CODES
        or place.canon_status != "canon"
        or place.lifecycle_status != "active"
    ):
        raise LocationInvalidError(f"{location_id} is not a published location")
    _serialize(connection, scope, knowledge_item_id, location_id)
    existing = connection.execute(
        text(
            "SELECT 1 FROM knowledge.public_knowledge WHERE timeline_id = :t "
            "AND knowledge_item_id = :k AND location_id = :l FOR UPDATE"
        ),
        {"t": scope.timeline_id, "k": knowledge_item_id, "l": location_id},
    ).scalar()
    if existing is not None:
        raise AlreadyPublicError(f"{knowledge_item_id} is already public at {location_id}")
    time_id = time_or_clock(connection, scope, world_time_id)
    event_id = _insert_event_row(
        connection,
        world_id=scope.world_id,
        timeline_id=scope.timeline_id,
        world_time_id=time_id,
        event_type_code="knowledge_made_public",
        name="Knowledge made public",
        details=normalize_interpretation(note),
        campaign_id=campaign_id,
    )
    row_id = connection.execute(
        text("""
            INSERT INTO knowledge.public_knowledge
                (timeline_id, knowledge_item_id, location_id, awareness_level,
                 known_since_world_time_id, last_event_id)
            VALUES (:t, :k, :l, :awareness, :time, :event)
            RETURNING public_knowledge_id
        """),
        {
            "t": scope.timeline_id,
            "k": knowledge_item_id,
            "l": location_id,
            "awareness": awareness,
            "time": time_id,
            "event": event_id,
        },
    ).scalar()
    assert isinstance(row_id, uuid.UUID)
    _effect(
        connection,
        event_id=event_id,
        world_time_id=time_id,
        component=COMPONENT_PUBLIC,
        previous=None,
        new={"location_id": str(location_id), "awareness_level": awareness},
        knowledge_item_id=knowledge_item_id,
    )
    return KnowledgeResult(
        world_id=scope.world_id,
        knowledge_item_id=knowledge_item_id,
        table="public_knowledge",
        record_id=row_id,
        changed=True,
        event_id=event_id,
        changed_fields=audit_initial(
            {"location_id": str(location_id), "awareness_level": awareness}
        ),
    )
