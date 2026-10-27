"""The reader projection of one character's relationships (the character page's player-facing
Relationships section).

`GET /campaigns/{id}/characters/{character_id}/relationships` shows what a caller who may open
the character page may know about its relationships. It applies the shared reader rule
(`READER_RELATIONSHIP_VISIBLE_SQL`: lifecycle `active`, no non-public subtype row) and suppresses
a relationship wholesale when any participant is not discoverable by the caller
(`all_participants_discoverable_sql`), exactly as `list_world_relationships` and
`get_relationship_view` do. It is always the reader view, even for a caller who can edit canon;
editors use the authoring list.

Fetch nothing rather than fetch-and-withhold: the SQL below never selects
`world.relationships.description`, participant `notes`, `political_relationships.treaty_terms`,
perspectives or any stance/tone/interpretation column (all GM_ONLY or editor-only — ADR 0016), and
the typed projection names only the CAMPAIGN_VISIBLE and structural columns. Period status is
derived server-side against the effective campaign clock (`relationship_period_status`); nothing
here takes a client-supplied world, timeline or party.

Framework-free and performs no authorization of its own: the caller has already decided that
the character may be opened and has built `visibility` from the same access context.
"""

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Connection, text

from dnd_ai.domain.relationship_authoring import (
    KIND_EMPLOYMENT,
    KIND_FAMILY,
    KIND_OWNERSHIP,
    KIND_POLITICAL,
    KIND_ROUTE,
    RELATIONSHIP_KINDS,
    RELATIONSHIP_TYPE_POLICIES,
    relationship_period_status,
)

from .campaign_clock import resolve_effective_clock, world_time_point
from .relationship_authoring import relationship_kind
from .world_explorer import (
    READER_RELATIONSHIP_VISIBLE_SQL,
    WorldEntityVisibility,
    _entity_visibility_params,
    all_participants_discoverable_sql,
    world_category_for_type_code,
)

_KIND_LABEL = {k.code: k.label for k in RELATIONSHIP_KINDS}

# Hard bound on one character's list. A character's edges are few; the bound only guards the
# response size, and the response says when it was applied.
MAX_CHARACTER_RELATIONSHIPS = 200

# The only typed columns the reader projection selects, by kind.
_READER_TYPED_SQL = {
    KIND_FAMILY: "SELECT family_unit_name FROM world.family_relationships",
    KIND_EMPLOYMENT: "SELECT job_title FROM world.employment_relationships",
    KIND_OWNERSHIP: "SELECT ownership_share FROM world.ownership_relationships",
    KIND_POLITICAL: "SELECT is_active AS in_force FROM world.political_relationships",
    "membership": 'SELECT role AS office, "rank" FROM world.organization_memberships',
    KIND_ROUTE: (
        "SELECT distance_text, travel_time_text, travel_mode FROM world.route_relationships"
    ),
}


@dataclass(frozen=True)
class ReaderParticipant:
    entity_id: uuid.UUID
    name: str
    entity_type_code: str
    # The World Explorer category the participant browses under (None for a type with no surface).
    category: str | None
    role: str
    role_label: str
    is_self: bool


@dataclass(frozen=True)
class CharacterRelationship:
    relationship_id: uuid.UUID
    kind: str
    kind_label: str
    relationship_type: str
    relationship_type_label: str
    symmetric: bool
    participants: tuple[ReaderParticipant, ...]
    started: str | None
    ended_at: str | None
    period_status: str
    current_status_label: str | None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CharacterRelationshipList:
    items: tuple[CharacterRelationship, ...]
    # The campaign clock the period statuses compare against; None when no clock is set.
    as_of: str | None
    truncated: bool


def _reader_typed(connection: Connection, relationship_id: uuid.UUID, kind: str) -> dict[str, Any]:
    sql = _READER_TYPED_SQL.get(kind)
    if sql is None:
        return {}
    row = (
        connection.execute(
            text(f"{sql} WHERE relationship_id = :r"),  # noqa: S608 - fixed text
            {"r": relationship_id},
        )
        .mappings()
        .one_or_none()
    )
    return {} if row is None else {k: v for k, v in row.items() if v is not None}


def list_character_relationships_for_reader(
    connection: Connection,
    *,
    world_id: uuid.UUID,
    timeline_id: uuid.UUID,
    character_id: uuid.UUID,
    visibility: WorldEntityVisibility,
) -> CharacterRelationshipList:
    params: dict[str, object] = {
        "w": world_id,
        "t": timeline_id,
        "c": character_id,
        "limit_plus_one": MAX_CHARACTER_RELATIONSHIPS + 1,
        **_entity_visibility_params(
            world_id=world_id, timeline_id=timeline_id, visibility=visibility
        ),
    }
    rows = connection.execute(
        text(f"""
            SELECT r.relationship_id, r.started_world_time_id, r.ended_world_time_id,
                   rt.code AS type_code, rt.display_name AS type_label,
                   sw.sort_key AS start_key, ew.sort_key AS end_key,
                   st.display_name AS status_label
            FROM world.relationships r
            JOIN world.relationship_types rt ON rt.relationship_type_id = r.relationship_type_id
            LEFT JOIN core.world_times sw ON sw.world_time_id = r.started_world_time_id
            LEFT JOIN core.world_times ew ON ew.world_time_id = r.ended_world_time_id
            LEFT JOIN campaign.relationship_state rs
              ON rs.relationship_id = r.relationship_id AND rs.timeline_id = :t
             AND rs.perspective_holder_entity_id IS NULL
            LEFT JOIN campaign.relationship_statuses st
              ON st.relationship_status_id = rs.relationship_status_id
            WHERE r.world_id = :w
              AND EXISTS (SELECT 1 FROM world.relationship_participants p
                          WHERE p.relationship_id = r.relationship_id AND p.entity_id = :c)
              AND {READER_RELATIONSHIP_VISIBLE_SQL}
              AND {all_participants_discoverable_sql()}
            ORDER BY r.created_at, r.relationship_id
            LIMIT :limit_plus_one
        """),
        params,
    ).all()
    truncated = len(rows) > MAX_CHARACTER_RELATIONSHIPS
    rows = rows[:MAX_CHARACTER_RELATIONSHIPS]

    clock = resolve_effective_clock(connection, timeline_id=timeline_id)
    clock_key = None if clock is None else clock.sort_key
    items: list[CharacterRelationship] = []
    for r in rows:
        kind = relationship_kind(connection, r.relationship_id)
        policy = RELATIONSHIP_TYPE_POLICIES.get(str(r.type_code))
        participants = tuple(
            ReaderParticipant(
                entity_id=p.entity_id,
                name=str(p.canonical_name),
                entity_type_code=str(p.type_code),
                category=world_category_for_type_code(str(p.type_code)),
                role=str(p.role),
                role_label=str(p.role_label),
                is_self=p.entity_id == character_id,
            )
            for p in connection.execute(
                text("""
                    SELECT p.entity_id, e.canonical_name, et.code AS type_code,
                           ro.code AS role, ro.display_name AS role_label
                    FROM world.relationship_participants p
                    JOIN core.entities e ON e.entity_id = p.entity_id
                    JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id
                    JOIN world.relationship_participant_roles ro
                      ON ro.relationship_participant_role_id = p.participant_role_id
                    WHERE p.relationship_id = :r
                    ORDER BY p.created_at, p.relationship_participant_id
                """),
                {"r": r.relationship_id},
            )
        )
        items.append(
            CharacterRelationship(
                relationship_id=r.relationship_id,
                kind=kind,
                kind_label=_KIND_LABEL.get(kind, kind.title()),
                relationship_type=str(r.type_code),
                relationship_type_label=str(r.type_label),
                symmetric=False if policy is None else policy.symmetric,
                participants=participants,
                started=(
                    None
                    if r.started_world_time_id is None
                    else world_time_point(connection, r.started_world_time_id)[1]
                ),
                ended_at=(
                    None
                    if r.ended_world_time_id is None
                    else world_time_point(connection, r.ended_world_time_id)[1]
                ),
                period_status=relationship_period_status(r.start_key, r.end_key, clock_key),
                current_status_label=None if r.status_label is None else str(r.status_label),
                details=_reader_typed(connection, r.relationship_id, kind),
            )
        )
    return CharacterRelationshipList(
        items=tuple(items), as_of=None if clock is None else clock.display, truncated=truncated
    )
