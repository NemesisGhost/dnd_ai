"""RevealKnowledgeToParty — records that a party now knows an already-
authored `knowledge.knowledge_items` row, atomically with its causal event.

This is the one target command Phase 12's NPC-portrayal use case actually
proposes (`dnd_ai.commands.ai_npc`, `ai.proposed_changes.proposal_kind =
'reveal_knowledge'`) — but it is an ordinary domain command in its own
right, callable identically by a human-authored GM action, matching
docs/ENTITY_LIFECYCLE.md §10's "applying a proposal uses the same domain
command path as human-authored changes."

Distinct from `dnd_ai.commands.interactions._maybe_discover_target`, which
records a *structural* discovery (a hidden dungeon feature/connection/
hazard/interactable becoming known to exist). This command's effect is a
change to `campaign.party_knowledge` — the party's current effective belief
about a knowledge item (docs/architecture/DATABASE_MODEL.md §15) — which
`_maybe_discover_target` never writes at all; it only writes the discovery
*log* (`knowledge.party_discoveries`). This command writes both, atomically:
the log entry (when this party has not already discovered the item) and the
current-state row (`campaign.party_knowledge`, upserted the same
lock-then-insert-or-update shape `dnd_ai.commands.quests._advance_objective_
impl` uses for `campaign.objective_state`), linked to one causal
`narrative.events` row (`event_type_code='knowledge_revealed'`, the same
code `_maybe_discover_target` already established) via two
`narrative.event_effects` rows — one per table changed, mirroring how
`dnd_ai.commands.relationships` records more than one effect row for a
single causing event when more than one table actually changed.

Idempotent: revealing an already-known item (a `campaign.party_knowledge`
row for this `(timeline, party, knowledge_item)` already exists) is a
no-op — no new event, no new effect rows, `already_known=True` in the
result — the same "already discovered -> return None" idempotency
`_maybe_discover_target` applies to its own structural case.
"""

import json
import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, Engine, text

from ._shared import validate_campaign_party, validate_session_campaign
from .events import EventParticipant, _insert_event_row


class KnowledgeItemNotFoundError(ValueError):
    """Raised when `knowledge_item_id` does not resolve to an existing
    `knowledge.knowledge_items` row."""


@dataclass(frozen=True)
class RevealKnowledgeResult:
    event_id: uuid.UUID | None
    world_id: uuid.UUID
    party_knowledge_id: uuid.UUID
    already_known: bool


def _lock_knowledge_item(connection: Connection, knowledge_item_id: uuid.UUID) -> uuid.UUID:
    """Row-lock the always-present `knowledge.knowledge_items` row (via its
    `core.entities` identity, CLAUDE.md rule 4) before touching the
    possibly-absent `campaign.party_knowledge` row — the same "lock the
    structural row first" ordering `dnd_ai.commands.quests._lock_quest_
    objective` uses, so two concurrent reveals of the same item can never
    both observe "not yet known" and race to insert. Returns the item's
    owning `world_id`."""
    world_id = connection.execute(
        text("""
            SELECT e.world_id
            FROM knowledge.knowledge_items ki
            JOIN core.entities e ON e.entity_id = ki.knowledge_item_id
            WHERE ki.knowledge_item_id = :item
            FOR UPDATE OF ki
        """),
        {"item": knowledge_item_id},
    ).scalar()
    if world_id is None:
        raise KnowledgeItemNotFoundError(f"knowledge item {knowledge_item_id} does not exist")
    assert isinstance(world_id, uuid.UUID)
    return world_id


def _lock_party_knowledge(
    connection: Connection,
    *,
    timeline_id: uuid.UUID,
    party_id: uuid.UUID,
    knowledge_item_id: uuid.UUID,
) -> uuid.UUID | None:
    """Row-lock the current `campaign.party_knowledge` row for this
    `(timeline, party, item)`, if one exists. Only meaningful once
    `_lock_knowledge_item` has already been called — see that function's
    docstring."""
    return connection.execute(
        text("""
            SELECT party_knowledge_id FROM campaign.party_knowledge
            WHERE timeline_id = :timeline AND party_id = :party AND knowledge_item_id = :item
            FOR UPDATE
        """),
        {"timeline": timeline_id, "party": party_id, "item": knowledge_item_id},
    ).scalar()


def _reveal_knowledge_to_party_impl(
    connection: Connection,
    *,
    knowledge_item_id: uuid.UUID,
    party_id: uuid.UUID,
    timeline_id: uuid.UUID,
    world_time_id: uuid.UUID,
    awareness_level: str = "aware",
    campaign_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    actor_entity_id: uuid.UUID | None = None,
    cause_interaction_id: uuid.UUID | None = None,
    cause_event_id: uuid.UUID | None = None,
    event_details: str | None = None,
) -> RevealKnowledgeResult:
    """The actual work of `reveal_knowledge_to_party()`, on a connection the
    caller already has open — see `dnd_ai.commands.quests._advance_
    objective_impl`'s docstring for the composable-implementation/public-
    wrapper pattern this mirrors."""
    validate_session_campaign(connection, campaign_id=campaign_id, session_id=session_id)
    validate_campaign_party(connection, campaign_id=campaign_id, party_id=party_id)

    world_id = _lock_knowledge_item(connection, knowledge_item_id)
    existing = _lock_party_knowledge(
        connection, timeline_id=timeline_id, party_id=party_id, knowledge_item_id=knowledge_item_id
    )
    if existing is not None:
        return RevealKnowledgeResult(
            event_id=None, world_id=world_id, party_knowledge_id=existing, already_known=True
        )

    event_id = _insert_event_row(
        connection,
        world_id=world_id,
        timeline_id=timeline_id,
        world_time_id=world_time_id,
        event_type_code="knowledge_revealed",
        name="Knowledge revealed to party",
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

    connection.execute(
        text("""
            INSERT INTO knowledge.party_discoveries
                (timeline_id, knowledge_item_id, party_id, discovered_at_world_time_id,
                 discovered_via_event_id)
            VALUES (:timeline, :item, :party, :world_time, :event)
        """),
        {
            "timeline": timeline_id,
            "item": knowledge_item_id,
            "party": party_id,
            "world_time": world_time_id,
            "event": event_id,
        },
    )
    connection.execute(
        text("""
            INSERT INTO narrative.event_effects
                (event_id, target_entity_id, target_component, previous_value, new_value,
                 effective_world_time_id)
            VALUES (:event, :entity, 'party_discovered', :previous, :new, :world_time)
        """),
        {
            "event": event_id,
            "entity": knowledge_item_id,
            "previous": json.dumps(False),
            "new": json.dumps(True),
            "world_time": world_time_id,
        },
    )

    party_knowledge_id = connection.execute(
        text("""
            INSERT INTO campaign.party_knowledge
                (timeline_id, party_id, knowledge_item_id, awareness_level, last_event_id)
            VALUES (:timeline, :party, :item, :awareness, :event)
            RETURNING party_knowledge_id
        """),
        {
            "timeline": timeline_id,
            "party": party_id,
            "item": knowledge_item_id,
            "awareness": awareness_level,
            "event": event_id,
        },
    ).scalar()
    assert isinstance(party_knowledge_id, uuid.UUID)

    connection.execute(
        text("""
            INSERT INTO narrative.event_effects
                (event_id, target_knowledge_item_id, target_component, previous_value, new_value,
                 effective_world_time_id)
            VALUES (:event, :item, 'awareness_level', :previous, :new, :world_time)
        """),
        {
            "event": event_id,
            "item": knowledge_item_id,
            "previous": json.dumps(None),
            "new": json.dumps(awareness_level),
            "world_time": world_time_id,
        },
    )

    return RevealKnowledgeResult(
        event_id=event_id,
        world_id=world_id,
        party_knowledge_id=party_knowledge_id,
        already_known=False,
    )


def reveal_knowledge_to_party(
    engine: Engine,
    *,
    knowledge_item_id: uuid.UUID,
    party_id: uuid.UUID,
    timeline_id: uuid.UUID,
    world_time_id: uuid.UUID,
    awareness_level: str = "aware",
    campaign_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    actor_entity_id: uuid.UUID | None = None,
    cause_interaction_id: uuid.UUID | None = None,
    cause_event_id: uuid.UUID | None = None,
    event_details: str | None = None,
) -> RevealKnowledgeResult:
    """Reveal a knowledge item to a party, atomically. Public convenience
    API: opens and commits its own transaction. See
    `_reveal_knowledge_to_party_impl()` for the composable form a caller
    with its own transaction (e.g. an approved-proposal application, or an
    API command endpoint) uses instead."""
    with engine.begin() as connection:
        return _reveal_knowledge_to_party_impl(
            connection,
            knowledge_item_id=knowledge_item_id,
            party_id=party_id,
            timeline_id=timeline_id,
            world_time_id=world_time_id,
            awareness_level=awareness_level,
            campaign_id=campaign_id,
            session_id=session_id,
            actor_entity_id=actor_entity_id,
            cause_interaction_id=cause_interaction_id,
            cause_event_id=cause_event_id,
            event_details=event_details,
        )
