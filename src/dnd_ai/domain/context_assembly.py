"""Deterministic, audience-filtered context assembly for an NPC-conversation
agent invocation (docs/PLAN.md Phase 12, exit criteria: "The NPC receives
only permitted knowledge; party-private and character-private knowledge do
not leak," "Responses can reference current encounter, quest, and
relationship state").

`assemble_npc_conversation_context()` is the one function `dnd_ai.commands.
ai_npc.request_npc_conversation_turn` calls to build the payload recorded in
`ai.context_snapshots` and sent to the AI provider. It composes only
already-established, already-authorized query results and a small number of
narrowly scoped direct reads — it performs no authorization of its own
(the same "authorization happens at the API/access boundary" split every
`dnd_ai.queries.*` module already follows): `requesting_character_id`/
`requesting_party_id` must already be authorized (the caller's own resolved
character and `dnd_ai.api.access.resolve_party_perspective` result) by the
time they reach here.

The `revealable_knowledge` list is the mechanism that keeps an approved
`reveal_knowledge` proposal safe: it is the closed, pre-computed set of
`knowledge.knowledge_items` rows whose `subject_entity_id` is this NPC and
that `requesting_party_id` does **not** already know, per `campaign.
party_knowledge`. `dnd_ai.commands.ai_npc` only ever accepts a
`knowledge_item_id` from this set for a `reveal_knowledge` proposal — the
model is never free to name an arbitrary knowledge item, which is what
keeps "AI output cannot directly mutate canonical state" true even for an
auto-approved proposal: the *candidate set* itself is deterministic,
already-authored, database-computed, and audience-filtered before the model
ever sees it, not something the model's own text output could expand.
"""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection, text

from dnd_ai.queries.character import get_character_view


@dataclass(frozen=True)
class RevealableKnowledge:
    knowledge_item_id: uuid.UUID
    statement: str
    sensitivity: str


@dataclass(frozen=True)
class NpcConversationContext:
    npc_entity_id: uuid.UUID
    npc_name: str
    requesting_character_id: uuid.UUID
    requesting_character_name: str
    relationship_status_code: str | None
    affinity: int | None
    trust: int | None
    active_encounter_id: uuid.UUID | None
    known_facts_about_npc: tuple[str, ...]
    revealable_knowledge: tuple[RevealableKnowledge, ...]

    def as_prompt_payload(self) -> dict[str, Any]:
        """The exact structure persisted to `ai.context_snapshots.
        assembled_context` and sent to the AI provider — a plain, JSON-
        serializable dict, never the dataclass itself (JSONB storage,
        conventions §5.7)."""
        return {
            "npc": {"entity_id": str(self.npc_entity_id), "name": self.npc_name},
            "requesting_character": {
                "entity_id": str(self.requesting_character_id),
                "name": self.requesting_character_name,
            },
            "relationship": {
                "status": self.relationship_status_code,
                "affinity": self.affinity,
                "trust": self.trust,
            },
            "active_encounter_id": (
                str(self.active_encounter_id) if self.active_encounter_id is not None else None
            ),
            "known_facts_about_npc": list(self.known_facts_about_npc),
            "revealable_knowledge": [
                {"knowledge_item_id": str(k.knowledge_item_id), "statement": k.statement}
                for k in self.revealable_knowledge
            ],
        }


def _relationship_state(
    connection: Connection,
    *,
    timeline_id: uuid.UUID,
    npc_entity_id: uuid.UUID,
    other_entity_id: uuid.UUID,
) -> tuple[str | None, int | None, int | None]:
    """The NPC's own perspective (`perspective_holder_entity_id =
    npc_entity_id`) on its relationship with `other_entity_id`, if a
    `world.relationships` row connects the two — deliberately a direct
    query rather than `dnd_ai.queries.relationship.get_relationship_view`,
    which is keyed by a known `relationship_id`; there is no existing
    by-participant-pair lookup to reuse. Returns `(None, None, None)` when
    no relationship (or no NPC-perspective state row) exists — a
    conversational NPC and a character with no established relationship is
    an ordinary, unremarkable case, not an error."""
    row = connection.execute(
        text("""
            SELECT rs.affinity, rs.trust, cs.code AS status_code
            FROM world.relationship_participants rp_npc
            JOIN world.relationship_participants rp_other
                ON rp_other.relationship_id = rp_npc.relationship_id
               AND rp_other.entity_id = :other
            JOIN campaign.relationship_state rs
                ON rs.relationship_id = rp_npc.relationship_id
               AND rs.timeline_id = :timeline
               AND rs.perspective_holder_entity_id = :npc
            JOIN campaign.relationship_statuses cs
                ON cs.relationship_status_id = rs.relationship_status_id
            WHERE rp_npc.entity_id = :npc
            ORDER BY rs.updated_at DESC
            LIMIT 1
        """),
        {"npc": npc_entity_id, "other": other_entity_id, "timeline": timeline_id},
    ).one_or_none()
    if row is None:
        return None, None, None
    return row.status_code, row.affinity, row.trust


def _known_facts_about_npc(
    connection: Connection, *, timeline_id: uuid.UUID, party_id: uuid.UUID, npc_entity_id: uuid.UUID
) -> tuple[str, ...]:
    """What `party_id` already believes about `npc_entity_id`
    (`campaign.party_knowledge`'s own current-belief statement, falling
    back to the item's canonical statement when the party's belief carries
    no recorded distortion — the same resolution `dnd_ai.queries.knowledge`
    already documents for its own single-item case)."""
    rows = connection.execute(
        text("""
            SELECT COALESCE(pk.interpretation, ki.canonical_statement) AS statement
            FROM campaign.party_knowledge pk
            JOIN knowledge.knowledge_items ki ON ki.knowledge_item_id = pk.knowledge_item_id
            WHERE pk.timeline_id = :timeline AND pk.party_id = :party
              AND ki.subject_entity_id = :npc
            ORDER BY pk.created_at
        """),
        {"timeline": timeline_id, "party": party_id, "npc": npc_entity_id},
    ).scalars()
    return tuple(rows)


def _revealable_knowledge(
    connection: Connection, *, timeline_id: uuid.UUID, party_id: uuid.UUID, npc_entity_id: uuid.UUID
) -> tuple[RevealableKnowledge, ...]:
    """Knowledge items about `npc_entity_id` that `party_id` does not yet
    know — the closed candidate set a `reveal_knowledge` proposal may draw
    from. See this module's own docstring for why this is the mechanism
    that keeps an AI-authored proposal safe."""
    rows = connection.execute(
        text("""
            SELECT ki.knowledge_item_id, ki.canonical_statement, ki.sensitivity
            FROM knowledge.knowledge_items ki
            WHERE ki.subject_entity_id = :npc
              AND NOT EXISTS (
                  SELECT 1 FROM campaign.party_knowledge pk
                  WHERE pk.timeline_id = :timeline AND pk.party_id = :party
                    AND pk.knowledge_item_id = ki.knowledge_item_id
              )
            ORDER BY ki.created_at
        """),
        {"npc": npc_entity_id, "timeline": timeline_id, "party": party_id},
    ).all()
    return tuple(
        RevealableKnowledge(
            knowledge_item_id=row.knowledge_item_id,
            statement=row.canonical_statement,
            sensitivity=row.sensitivity,
        )
        for row in rows
    )


def assemble_npc_conversation_context(
    connection: Connection,
    *,
    npc_entity_id: uuid.UUID,
    timeline_id: uuid.UUID,
    expected_world_id: uuid.UUID,
    requesting_character_id: uuid.UUID,
    requesting_party_id: uuid.UUID,
) -> NpcConversationContext:
    """Assemble the full, audience-filtered context for one NPC-
    conversation turn. Raises whatever `get_character_view` raises
    (`CharacterNotFoundError`, a `DomainAuthorizationError`) for a
    nonexistent or cross-world `npc_entity_id`/`requesting_character_id` —
    the same fixed, non-disclosing contract every query in this codebase
    already uses."""
    npc = get_character_view(
        connection,
        character_id=npc_entity_id,
        timeline_id=timeline_id,
        expected_world_id=expected_world_id,
        include_full=True,
    )
    requester = get_character_view(
        connection,
        character_id=requesting_character_id,
        timeline_id=timeline_id,
        expected_world_id=expected_world_id,
        include_full=False,
    )
    status_code, affinity, trust = _relationship_state(
        connection,
        timeline_id=timeline_id,
        npc_entity_id=npc_entity_id,
        other_entity_id=requesting_character_id,
    )
    return NpcConversationContext(
        npc_entity_id=npc_entity_id,
        npc_name=npc.name,
        requesting_character_id=requesting_character_id,
        requesting_character_name=requester.name,
        relationship_status_code=status_code,
        affinity=affinity,
        trust=trust,
        active_encounter_id=npc.active_encounter_id,
        known_facts_about_npc=_known_facts_about_npc(
            connection,
            timeline_id=timeline_id,
            party_id=requesting_party_id,
            npc_entity_id=npc_entity_id,
        ),
        revealable_knowledge=_revealable_knowledge(
            connection,
            timeline_id=timeline_id,
            party_id=requesting_party_id,
            npc_entity_id=npc_entity_id,
        ),
    )
