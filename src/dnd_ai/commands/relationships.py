"""EvolveRelationshipReaction and UpdateOrganizationStatus — the commands
that let a dungeon event change a relationship's current status/subjective
reaction or an organization's operational status, atomically
(docs/PLAN.md Phase 8 exit criterion: "NPC and faction reactions can
evolve from events").

Mirrors dnd_ai.commands.quests.advance_objective's shape: lock a
structural row that always exists (world.relationships / world.organizations)
before touching the possibly-absent campaign.relationship_state /
campaign.organization_state row, so two concurrent evolutions of the same
scope serialize rather than race, then record the causing narrative.events
row, update the state table to match, and link the two through a
narrative.event_effects row — all in one transaction.
"""

import json
import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, Engine, text

from ._shared import lookup_id
from .events import EventParticipant, _insert_event_row


@dataclass(frozen=True)
class EvolveRelationshipReactionResult:
    relationship_state_id: uuid.UUID
    event_id: uuid.UUID
    previous_status_code: str | None
    new_status_code: str


@dataclass(frozen=True)
class UpdateOrganizationStatusResult:
    organization_state_id: uuid.UUID
    event_id: uuid.UUID
    previous_status_code: str | None
    new_status_code: str


def _relationship_world(connection: Connection, relationship_id: uuid.UUID) -> uuid.UUID:
    world_id = connection.execute(
        text("SELECT world_id FROM world.relationships WHERE relationship_id = :r"),
        {"r": relationship_id},
    ).scalar()
    if world_id is None:
        raise ValueError(f"relationship {relationship_id} does not exist")
    assert isinstance(world_id, uuid.UUID)
    return world_id


def _lock_relationship(connection: Connection, relationship_id: uuid.UUID) -> None:
    """Acquire an exclusive row lock on the relationship itself (a
    structural row that always exists, unlike its possibly-absent
    campaign.relationship_state row) before touching campaign.
    relationship_state at all — the same first-write concurrency guard
    advance_objective applies via _lock_quest_objective."""
    connection.execute(
        text(
            "SELECT relationship_id FROM world.relationships WHERE relationship_id = :r FOR UPDATE"
        ),
        {"r": relationship_id},
    )


def _lock_relationship_state(
    connection: Connection,
    *,
    timeline_id: uuid.UUID,
    relationship_id: uuid.UUID,
    perspective_holder_entity_id: uuid.UUID | None,
) -> tuple[uuid.UUID, str] | None:
    row = connection.execute(
        text("""
            SELECT relationship_state_id,
                   (SELECT code FROM campaign.relationship_statuses
                    WHERE relationship_status_id = rs.relationship_status_id) AS status_code
            FROM campaign.relationship_state rs
            WHERE rs.timeline_id = :timeline AND rs.relationship_id = :relationship
              AND rs.perspective_holder_entity_id IS NOT DISTINCT FROM :holder
            FOR UPDATE
        """),
        {
            "timeline": timeline_id,
            "relationship": relationship_id,
            "holder": perspective_holder_entity_id,
        },
    ).one_or_none()
    if row is None:
        return None
    relationship_state_id, status_code = row
    assert isinstance(relationship_state_id, uuid.UUID)
    assert isinstance(status_code, str)
    return relationship_state_id, status_code


def evolve_relationship_reaction(
    engine: Engine,
    *,
    relationship_id: uuid.UUID,
    timeline_id: uuid.UUID,
    world_time_id: uuid.UUID,
    new_status_code: str,
    perspective_holder_entity_id: uuid.UUID | None = None,
    affinity: int | None = None,
    trust: int | None = None,
    respect: int | None = None,
    fear: int | None = None,
    obligation: int | None = None,
    emotional_tone: str | None = None,
    private_interpretation: str | None = None,
    actor_entity_id: uuid.UUID | None = None,
    campaign_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    cause_interaction_id: uuid.UUID | None = None,
    cause_event_id: uuid.UUID | None = None,
    event_details: str | None = None,
) -> EvolveRelationshipReactionResult:
    """Record the narrative.events row that changes a relationship's
    current status and update campaign.relationship_state to match,
    atomically. perspective_holder_entity_id follows campaign.quest_state's
    party_id convention: NULL updates the shared/objective status; set,
    it updates that one participant's own subjective reaction — see
    docs/architecture/DATABASE_MODEL.md §17.
    """
    with engine.begin() as connection:
        world_id = _relationship_world(connection, relationship_id)
        _lock_relationship(connection, relationship_id)

        existing = _lock_relationship_state(
            connection,
            timeline_id=timeline_id,
            relationship_id=relationship_id,
            perspective_holder_entity_id=perspective_holder_entity_id,
        )
        previous_status_code = existing[1] if existing is not None else None

        event_id = _insert_event_row(
            connection,
            world_id=world_id,
            timeline_id=timeline_id,
            world_time_id=world_time_id,
            event_type_code="relationship_changed",
            name="Relationship changed",
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

        new_status_id = lookup_id(
            connection,
            "campaign",
            "relationship_statuses",
            "relationship_status_id",
            new_status_code,
        )

        if existing is None:
            relationship_state_id = connection.execute(
                text("""
                    INSERT INTO campaign.relationship_state
                        (timeline_id, relationship_id, perspective_holder_entity_id,
                         relationship_status_id, affinity, trust, respect, fear, obligation,
                         emotional_tone, private_interpretation, last_event_id)
                    VALUES (:timeline, :relationship, :holder, :status, :affinity, :trust,
                            :respect, :fear, :obligation, :tone, :interpretation, :event)
                    RETURNING relationship_state_id
                """),
                {
                    "timeline": timeline_id,
                    "relationship": relationship_id,
                    "holder": perspective_holder_entity_id,
                    "status": new_status_id,
                    "affinity": affinity,
                    "trust": trust,
                    "respect": respect,
                    "fear": fear,
                    "obligation": obligation,
                    "tone": emotional_tone,
                    "interpretation": private_interpretation,
                    "event": event_id,
                },
            ).scalar()
            assert isinstance(relationship_state_id, uuid.UUID)
        else:
            relationship_state_id = existing[0]
            connection.execute(
                text("""
                    UPDATE campaign.relationship_state
                    SET relationship_status_id = :status, affinity = :affinity, trust = :trust,
                        respect = :respect, fear = :fear, obligation = :obligation,
                        emotional_tone = :tone, private_interpretation = :interpretation,
                        last_event_id = :event, updated_at = now()
                    WHERE relationship_state_id = :id
                """),
                {
                    "status": new_status_id,
                    "affinity": affinity,
                    "trust": trust,
                    "respect": respect,
                    "fear": fear,
                    "obligation": obligation,
                    "tone": emotional_tone,
                    "interpretation": private_interpretation,
                    "event": event_id,
                    "id": relationship_state_id,
                },
            )

        connection.execute(
            text("""
                INSERT INTO narrative.event_effects
                    (event_id, target_relationship_id, target_component, previous_value,
                     new_value, effective_world_time_id)
                VALUES (:event, :relationship, 'relationship_status_id', :previous, :new, :world_time)
            """),
            {
                "event": event_id,
                "relationship": relationship_id,
                "previous": json.dumps(previous_status_code),
                "new": json.dumps(new_status_code),
                "world_time": world_time_id,
            },
        )

    return EvolveRelationshipReactionResult(
        relationship_state_id=relationship_state_id,
        event_id=event_id,
        previous_status_code=previous_status_code,
        new_status_code=new_status_code,
    )


def _organization_world(connection: Connection, organization_id: uuid.UUID) -> uuid.UUID:
    world_id = connection.execute(
        text("SELECT world_id FROM core.entities WHERE entity_id = :o"),
        {"o": organization_id},
    ).scalar()
    if world_id is None:
        raise ValueError(f"organization {organization_id} does not exist")
    assert isinstance(world_id, uuid.UUID)
    return world_id


def _lock_organization(connection: Connection, organization_id: uuid.UUID) -> None:
    connection.execute(
        text(
            "SELECT organization_id FROM world.organizations WHERE organization_id = :o FOR UPDATE"
        ),
        {"o": organization_id},
    )


def _lock_organization_state(
    connection: Connection, *, timeline_id: uuid.UUID, organization_id: uuid.UUID
) -> tuple[uuid.UUID, str] | None:
    row = connection.execute(
        text("""
            SELECT organization_state_id,
                   (SELECT code FROM campaign.organization_statuses
                    WHERE organization_status_id = os.organization_status_id) AS status_code
            FROM campaign.organization_state os
            WHERE os.timeline_id = :timeline AND os.organization_id = :organization
            FOR UPDATE
        """),
        {"timeline": timeline_id, "organization": organization_id},
    ).one_or_none()
    if row is None:
        return None
    organization_state_id, status_code = row
    assert isinstance(organization_state_id, uuid.UUID)
    assert isinstance(status_code, str)
    return organization_state_id, status_code


def update_organization_status(
    engine: Engine,
    *,
    organization_id: uuid.UUID,
    timeline_id: uuid.UUID,
    world_time_id: uuid.UUID,
    new_status_code: str,
    actor_entity_id: uuid.UUID | None = None,
    campaign_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    cause_interaction_id: uuid.UUID | None = None,
    cause_event_id: uuid.UUID | None = None,
    event_details: str | None = None,
) -> UpdateOrganizationStatusResult:
    """Record the narrative.events row that changes an organization's
    current operational status and update campaign.organization_state to
    match, atomically — the organization half of the "NPC and faction
    reactions can evolve from events" exit criterion (a faction being
    banned, going underground, or dissolving as a result of play)."""
    with engine.begin() as connection:
        world_id = _organization_world(connection, organization_id)
        _lock_organization(connection, organization_id)

        existing = _lock_organization_state(
            connection, timeline_id=timeline_id, organization_id=organization_id
        )
        previous_status_code = existing[1] if existing is not None else None

        event_id = _insert_event_row(
            connection,
            world_id=world_id,
            timeline_id=timeline_id,
            world_time_id=world_time_id,
            event_type_code="organization_status_changed",
            name="Organization status changed",
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

        new_status_id = lookup_id(
            connection,
            "campaign",
            "organization_statuses",
            "organization_status_id",
            new_status_code,
        )

        if existing is None:
            organization_state_id = connection.execute(
                text("""
                    INSERT INTO campaign.organization_state
                        (timeline_id, organization_id, organization_status_id, last_event_id)
                    VALUES (:timeline, :organization, :status, :event)
                    RETURNING organization_state_id
                """),
                {
                    "timeline": timeline_id,
                    "organization": organization_id,
                    "status": new_status_id,
                    "event": event_id,
                },
            ).scalar()
            assert isinstance(organization_state_id, uuid.UUID)
        else:
            organization_state_id = existing[0]
            connection.execute(
                text("""
                    UPDATE campaign.organization_state
                    SET organization_status_id = :status, last_event_id = :event, updated_at = now()
                    WHERE organization_state_id = :id
                """),
                {"status": new_status_id, "event": event_id, "id": organization_state_id},
            )

        connection.execute(
            text("""
                INSERT INTO narrative.event_effects
                    (event_id, target_entity_id, target_component, previous_value,
                     new_value, effective_world_time_id)
                VALUES (:event, :organization, 'organization_status_id', :previous, :new, :world_time)
            """),
            {
                "event": event_id,
                "organization": organization_id,
                "previous": json.dumps(previous_status_code),
                "new": json.dumps(new_status_code),
                "world_time": world_time_id,
            },
        )

    return UpdateOrganizationStatusResult(
        organization_state_id=organization_state_id,
        event_id=event_id,
        previous_status_code=previous_status_code,
        new_status_code=new_status_code,
    )
