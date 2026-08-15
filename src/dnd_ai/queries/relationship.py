"""Effective relationship-state query (docs/PLAN.md Phase 10 deliverable
"query services for the effective dungeon, character, quest, relationship,
... state required by the vertical slice").

`world.relationships`/`.relationship_participants` describe what a
relationship is; `campaign.relationship_state` describes its current
status on a timeline, and is split between one shared, objective row
(`perspective_holder_entity_id IS NULL`) and independent subjective rows,
one per participant holding their own view (docs/architecture/
DATABASE_MODEL.md §10.1, migration 076's own partial unique indexes:
`ux_relationship_state_timeline_relationship_no_holder`/`..._holder`).

Audience filtering: the shared row and the participant list are always
returned to any authorized caller — who is related to whom is a structural
fact, not a subjective judgment. Subjective rows are different: each one
carries `affinity`/`trust`/`respect`/`fear`/`obligation`/`emotional_tone`
and a `private_interpretation` field the schema itself documents as
private (§10.1: "authored, world-scoped baseline subjective view..."). This
first cut is deliberately conservative rather than guessing a per-holder
character-relationship rule: subjective rows are returned only to a caller
holding `canon.edit` (a GM, `include_subjective=True`); everyone else gets
none, the same "fetch nothing rather than fetch-and-withhold" discipline
`dnd_ai.queries.character` already established for its own full-tier data.
Distinguishing "the current caller's own controlled character's
subjective view" from "everyone else's" is deferred until a caller
actually needs it — not invented speculatively here.

`world.relationship_perspectives` (the world-scoped, author-time baseline
this state table's own subjective rows evolve from) is out of scope for
this first cut; `campaign.relationship_state` is the current, timeline-
scoped read a live game session needs.

This module is framework-free and performs no authorization of its own:
`include_subjective` must already be an authorized decision (a resolved
`canon.edit` capability check) by the time it reaches here, the same
"authorization happens at the API/access boundary, the query only
filters" split every other query module in this package follows.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, text

from dnd_ai.domain.errors import DomainAuthorizationError


class RelationshipNotFoundError(DomainAuthorizationError):
    """Raised by `get_relationship_view()` for a nonexistent
    `relationship_id`, or one whose own world does not match the caller's
    `expected_world_id` — identically, so a caller can never distinguish
    "doesn't exist" from "belongs to a different world" (mirroring
    `dnd_ai.queries.dungeon.DungeonAreaNotFoundError`'s identical
    reasoning). The supplied relationship/world ids are included only in
    the constructor's `detail` argument (`str(self)`), never in
    `safe_message`."""


@dataclass(frozen=True)
class RelationshipParticipantView:
    entity_id: uuid.UUID
    role_code: str


@dataclass(frozen=True)
class RelationshipStateView:
    perspective_holder_entity_id: uuid.UUID | None
    status_code: str
    affinity: int | None
    trust: int | None
    respect: int | None
    fear: int | None
    obligation: int | None
    emotional_tone: str | None
    private_interpretation: str | None


@dataclass(frozen=True)
class RelationshipView:
    relationship_id: uuid.UUID
    relationship_type_code: str
    description: str | None
    participants: tuple[RelationshipParticipantView, ...]
    shared_state: RelationshipStateView | None
    subjective_states: tuple[RelationshipStateView, ...]


def get_relationship_view(
    connection: Connection,
    *,
    relationship_id: uuid.UUID,
    timeline_id: uuid.UUID,
    expected_world_id: uuid.UUID,
    include_subjective: bool,
) -> RelationshipView:
    """The effective state of one relationship: its participants, current
    shared status, and — only when `include_subjective=True` — every
    participant's own current subjective view. Raises
    `RelationshipNotFoundError` for a nonexistent relationship or one
    belonging to a different world than `expected_world_id` (always the
    caller's own resolved-timeline world — `dnd_ai.api._shared.
    timeline_world_id`, never caller-supplied)."""
    row = (
        connection.execute(
            text("""
                SELECT r.relationship_id, r.world_id, r.description, rt.code AS type_code
                FROM world.relationships r
                JOIN world.relationship_types rt ON rt.relationship_type_id = r.relationship_type_id
                WHERE r.relationship_id = :relationship
            """),
            {"relationship": relationship_id},
        )
        .mappings()
        .one_or_none()
    )

    if row is None or row["world_id"] != expected_world_id:
        raise RelationshipNotFoundError(
            f"relationship {relationship_id} does not exist in world {expected_world_id} "
            f"(actual world: {row['world_id'] if row is not None else None})"
        )

    participant_rows = connection.execute(
        text("""
            SELECT rp.entity_id, rpr.code AS role_code
            FROM world.relationship_participants rp
            JOIN world.relationship_participant_roles rpr
                ON rpr.relationship_participant_role_id = rp.participant_role_id
            WHERE rp.relationship_id = :relationship
            ORDER BY rp.relationship_participant_id
        """),
        {"relationship": relationship_id},
    ).mappings()
    participants = tuple(
        RelationshipParticipantView(entity_id=p["entity_id"], role_code=p["role_code"])
        for p in participant_rows
    )

    state_columns = """
        rs.perspective_holder_entity_id, rst.code AS status_code, rs.affinity, rs.trust,
        rs.respect, rs.fear, rs.obligation, rs.emotional_tone, rs.private_interpretation
    """
    state_from = """
        FROM campaign.relationship_state rs
        JOIN campaign.relationship_statuses rst ON rst.relationship_status_id = rs.relationship_status_id
        WHERE rs.timeline_id = :timeline AND rs.relationship_id = :relationship
    """

    shared_row = (
        connection.execute(
            text(
                f"SELECT {state_columns} {state_from} AND rs.perspective_holder_entity_id IS NULL"
            ),
            {"timeline": timeline_id, "relationship": relationship_id},
        )
        .mappings()
        .one_or_none()
    )
    shared_state = (
        None
        if shared_row is None
        else RelationshipStateView(
            perspective_holder_entity_id=shared_row["perspective_holder_entity_id"],
            status_code=shared_row["status_code"],
            affinity=shared_row["affinity"],
            trust=shared_row["trust"],
            respect=shared_row["respect"],
            fear=shared_row["fear"],
            obligation=shared_row["obligation"],
            emotional_tone=shared_row["emotional_tone"],
            private_interpretation=shared_row["private_interpretation"],
        )
    )

    subjective_states: tuple[RelationshipStateView, ...] = ()
    if include_subjective:
        subjective_rows = connection.execute(
            text(
                f"SELECT {state_columns} {state_from} AND rs.perspective_holder_entity_id IS NOT NULL "
                "ORDER BY rs.perspective_holder_entity_id"
            ),
            {"timeline": timeline_id, "relationship": relationship_id},
        ).mappings()
        subjective_states = tuple(
            RelationshipStateView(
                perspective_holder_entity_id=s["perspective_holder_entity_id"],
                status_code=s["status_code"],
                affinity=s["affinity"],
                trust=s["trust"],
                respect=s["respect"],
                fear=s["fear"],
                obligation=s["obligation"],
                emotional_tone=s["emotional_tone"],
                private_interpretation=s["private_interpretation"],
            )
            for s in subjective_rows
        )

    return RelationshipView(
        relationship_id=row["relationship_id"],
        relationship_type_code=row["type_code"],
        description=row["description"],
        participants=participants,
        shared_state=shared_state,
        subjective_states=subjective_states,
    )
