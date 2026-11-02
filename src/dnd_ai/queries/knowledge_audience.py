"""Who knows one claim: the GM audience read model (Phase 15 checkpoint 15.2E-3).

For one knowledge item on the campaign timeline: the parties that know it, the individual
knowers (characters, NPCs, organizations) with their beliefs, and the locations where it is
public. This is the `canon.edit` read; players see knowledge only through the
perspective-scoped knowledge reads. `last_event_id` is the token a belief change names.
"""

import uuid
from dataclasses import dataclass, field

from sqlalchemy import Connection, text


@dataclass(frozen=True)
class PartyAudience:
    party_knowledge_id: uuid.UUID
    party_id: uuid.UUID
    party_name: str
    awareness_level: str


@dataclass(frozen=True)
class KnowerAudience:
    entity_knowledge_id: uuid.UUID
    knower_entity_id: uuid.UUID
    knower_name: str
    knower_type: str
    awareness_level: str
    confidence: int | None
    interpretation: str | None
    willing_to_share: bool
    last_event_id: uuid.UUID | None


@dataclass(frozen=True)
class PublicAudience:
    public_knowledge_id: uuid.UUID
    location_id: uuid.UUID
    location_name: str
    awareness_level: str


@dataclass(frozen=True)
class KnowledgeAudience:
    knowledge_item_id: uuid.UUID
    parties: list[PartyAudience] = field(default_factory=list)
    knowers: list[KnowerAudience] = field(default_factory=list)
    public: list[PublicAudience] = field(default_factory=list)


def get_knowledge_audience(
    connection: Connection,
    *,
    world_id: uuid.UUID,
    timeline_id: uuid.UUID,
    knowledge_item_id: uuid.UUID,
) -> KnowledgeAudience | None:
    """`None` when the claim is not a knowledge item of this world."""
    exists = connection.execute(
        text("""
            SELECT 1 FROM core.entities e
            JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id
            WHERE e.entity_id = :k AND e.world_id = :w AND et.code = 'knowledge_item'
        """),
        {"k": knowledge_item_id, "w": world_id},
    ).scalar()
    if exists is None:
        return None
    parties = connection.execute(
        text("""
            SELECT pk.party_knowledge_id, pk.party_id, p.name, pk.awareness_level
            FROM campaign.party_knowledge pk JOIN campaign.parties p ON p.party_id = pk.party_id
            WHERE pk.timeline_id = :t AND pk.knowledge_item_id = :k
            ORDER BY lower(p.name), pk.party_knowledge_id
        """),
        {"t": timeline_id, "k": knowledge_item_id},
    ).all()
    knowers = connection.execute(
        text("""
            SELECT ek.entity_knowledge_id, ek.knower_entity_id, e.canonical_name, et.code AS kind,
                   ek.awareness_level, ek.confidence, ek.interpretation, ek.willing_to_share,
                   ek.last_event_id
            FROM knowledge.entity_knowledge ek
            JOIN core.entities e ON e.entity_id = ek.knower_entity_id
            JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id
            WHERE ek.timeline_id = :t AND ek.knowledge_item_id = :k
            ORDER BY lower(e.canonical_name), ek.entity_knowledge_id
        """),
        {"t": timeline_id, "k": knowledge_item_id},
    ).all()
    public = connection.execute(
        text("""
            SELECT pk.public_knowledge_id, pk.location_id, e.canonical_name, pk.awareness_level
            FROM knowledge.public_knowledge pk JOIN core.entities e ON e.entity_id = pk.location_id
            WHERE pk.timeline_id = :t AND pk.knowledge_item_id = :k
            ORDER BY lower(e.canonical_name), pk.public_knowledge_id
        """),
        {"t": timeline_id, "k": knowledge_item_id},
    ).all()
    return KnowledgeAudience(
        knowledge_item_id=knowledge_item_id,
        parties=[PartyAudience(r[0], r[1], str(r[2]), str(r[3])) for r in parties],
        knowers=[
            KnowerAudience(
                r.entity_knowledge_id,
                r.knower_entity_id,
                str(r.canonical_name),
                str(r.kind),
                str(r.awareness_level),
                r.confidence,
                r.interpretation,
                bool(r.willing_to_share),
                r.last_event_id,
            )
            for r in knowers
        ],
        public=[PublicAudience(r[0], r[1], str(r[2]), str(r[3])) for r in public],
    )
