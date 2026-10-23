"""Editor read models for world relationships (Phase 15 checkpoint 15.3A-2a, D-18).

For `canon.edit` holders only: one relationship with its kind, participants, typed fields,
lifecycle, authored perspectives and (for the campaign timeline) its current shared status, and
the list of every relationship an entity takes part in, archived and private ones included.
Readers who cannot edit use the audience-filtered reads in `queries.relationship` and
`queries.world_explorer`, which hide an archived relationship and one whose subtype says it is
not public.
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
    policy_conflicts,
    relationship_period_status,
)

from .campaign_clock import resolve_effective_clock, world_time_point


@dataclass(frozen=True)
class Participant:
    entity_id: uuid.UUID
    name: str
    entity_type_code: str
    canon_status: str
    lifecycle_status: str
    role: str
    role_label: str


@dataclass(frozen=True)
class PerspectiveRow:
    holder_entity_id: uuid.UUID
    holder_name: str
    affinity: int | None
    trust: int | None
    respect: int | None
    fear: int | None
    obligation: int | None
    emotional_tone: str | None
    private_interpretation: str | None


@dataclass(frozen=True)
class RelationshipAuthoringView:
    relationship_id: uuid.UUID
    kind: str
    kind_label: str
    relationship_type: str
    relationship_type_label: str
    description: str | None
    started_world_time_id: uuid.UUID | None
    started: str | None
    ended_world_time_id: uuid.UUID | None
    ended: str | None
    lifecycle_status: str
    row_version: int
    typed: dict[str, Any]
    participants: list[Participant]
    perspectives: list[PerspectiveRow] = field(default_factory=list)
    current_status: str | None = None
    available_actions: list[str] = field(default_factory=list)
    policy_conflicts: list[str] = field(default_factory=list)
    # Derived for editors from the effective campaign clock; see `relationship_period_status`.
    period_status: str = "undated"
    as_of: str | None = None
    current_status_label: str | None = None


@dataclass(frozen=True)
class RelationshipSummary:
    relationship_id: uuid.UUID
    kind: str
    relationship_type: str
    relationship_type_label: str
    description: str | None
    lifecycle_status: str
    ended: bool
    is_public: bool | None
    row_version: int
    participants: list[Participant]
    policy_conflicts: list[str] = field(default_factory=list)
    started_world_time_id: uuid.UUID | None = None
    started: str | None = None
    ended_world_time_id: uuid.UUID | None = None
    ended_at: str | None = None
    period_status: str = "undated"
    in_force: bool | None = None
    is_hidden: bool | None = None
    current_status: str | None = None
    current_status_label: str | None = None


@dataclass(frozen=True)
class RelationshipList:
    items: list[RelationshipSummary]
    # The campaign clock the period statuses compare against; None when no clock is set.
    as_of: str | None


_KIND_LABEL = {k.code: k.label for k in RELATIONSHIP_KINDS}


def relationship_kind(connection: Connection, relationship_id: uuid.UUID) -> str:
    for code, table in (
        (KIND_FAMILY, "family_relationships"),
        (KIND_EMPLOYMENT, "employment_relationships"),
        (KIND_OWNERSHIP, "ownership_relationships"),
        (KIND_POLITICAL, "political_relationships"),
        (KIND_ROUTE, "route_relationships"),
    ):
        if (
            connection.execute(
                text(f"SELECT 1 FROM world.{table} WHERE relationship_id = :r"),  # noqa: S608
                {"r": relationship_id},
            ).scalar()
            is not None
        ):
            return code
    # Membership belongs to checkpoint 15.3A-2b and is shown as its own kind.
    if (
        connection.execute(
            text("SELECT 1 FROM world.organization_memberships WHERE relationship_id = :r"),
            {"r": relationship_id},
        ).scalar()
        is not None
    ):
        return "membership"
    return "general"


def active_type_codes(connection: Connection) -> frozenset[str]:
    """Relationship types the platform lookup currently offers."""
    return frozenset(
        str(code)
        for code in connection.execute(
            text("SELECT code FROM world.relationship_types WHERE is_active")
        ).scalars()
    )


def _conflicts(
    type_code: str, participants: list[Participant], active: frozenset[str]
) -> list[str]:
    return policy_conflicts(
        type_code,
        [(p.role, p.entity_type_code, p.name) for p in participants],
        type_offered=type_code in active,
        entity_ids=[p.entity_id for p in participants],
    )


def entity_type_code_in_world(
    connection: Connection, *, world_id: uuid.UUID, entity_id: uuid.UUID
) -> str | None:
    """The subtype code of an entity in this world, or None when there is no such entity here."""
    code = connection.execute(
        text("""
            SELECT et.code FROM core.entities e
            JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id
            WHERE e.entity_id = :e AND e.world_id = :w
        """),
        {"e": entity_id, "w": world_id},
    ).scalar()
    return None if code is None else str(code)


def _participants(connection: Connection, relationship_id: uuid.UUID) -> list[Participant]:
    rows = connection.execute(
        text("""
            SELECT p.entity_id, e.canonical_name, et.code AS type_code, cs.code AS canon,
                   ls.code AS lifecycle, r.code AS role, r.display_name AS role_label
            FROM world.relationship_participants p
            JOIN core.entities e ON e.entity_id = p.entity_id
            JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id
            JOIN core.canon_statuses cs ON cs.canon_status_id = e.canon_status_id
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = e.lifecycle_status_id
            JOIN world.relationship_participant_roles r
              ON r.relationship_participant_role_id = p.participant_role_id
            WHERE p.relationship_id = :r
            ORDER BY p.created_at, p.relationship_participant_id
        """),
        {"r": relationship_id},
    ).all()
    return [
        Participant(
            entity_id=r.entity_id,
            name=str(r.canonical_name),
            entity_type_code=str(r.type_code),
            canon_status=str(r.canon),
            lifecycle_status=str(r.lifecycle),
            role=str(r.role),
            role_label=str(r.role_label),
        )
        for r in rows
    ]


def _typed(connection: Connection, relationship_id: uuid.UUID, kind: str) -> dict[str, Any]:
    queries = {
        KIND_FAMILY: "SELECT family_unit_name FROM world.family_relationships",
        KIND_EMPLOYMENT: "SELECT job_title FROM world.employment_relationships",
        KIND_OWNERSHIP: "SELECT ownership_share, is_public FROM world.ownership_relationships",
        KIND_POLITICAL: "SELECT is_active, treaty_terms FROM world.political_relationships",
        "membership": "SELECT role, rank, is_public FROM world.organization_memberships",
        KIND_ROUTE: (
            "SELECT distance_text, travel_time_text, travel_mode, is_hidden "
            "FROM world.route_relationships"
        ),
    }
    if kind not in queries:
        return {}
    row = (
        connection.execute(
            text(f"{queries[kind]} WHERE relationship_id = :r"),  # noqa: S608 - fixed text
            {"r": relationship_id},
        )
        .mappings()
        .one_or_none()
    )
    return {} if row is None else dict(row)


def get_relationship_authoring(
    connection: Connection,
    *,
    world_id: uuid.UUID,
    timeline_id: uuid.UUID,
    relationship_id: uuid.UUID,
) -> RelationshipAuthoringView | None:
    row = connection.execute(
        text("""
            SELECT r.description, r.started_world_time_id, r.ended_world_time_id, r.row_version,
                   rt.code AS type_code, rt.display_name AS type_label, ls.code AS lifecycle
            FROM world.relationships r
            JOIN world.relationship_types rt ON rt.relationship_type_id = r.relationship_type_id
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = r.lifecycle_status_id
            WHERE r.relationship_id = :r AND r.world_id = :w
        """),
        {"r": relationship_id, "w": world_id},
    ).one_or_none()
    if row is None:
        return None
    kind = relationship_kind(connection, relationship_id)
    participants = _participants(connection, relationship_id)
    names = {p.entity_id: p.name for p in participants}
    perspectives = [
        PerspectiveRow(
            holder_entity_id=p.perspective_holder_entity_id,
            holder_name=names.get(p.perspective_holder_entity_id, ""),
            affinity=p.affinity,
            trust=p.trust,
            respect=p.respect,
            fear=p.fear,
            obligation=p.obligation,
            emotional_tone=p.emotional_tone,
            private_interpretation=p.private_interpretation,
        )
        for p in connection.execute(
            text(
                "SELECT perspective_holder_entity_id, affinity, trust, respect, fear, obligation, "
                "emotional_tone, private_interpretation FROM world.relationship_perspectives "
                "WHERE relationship_id = :r ORDER BY created_at, relationship_perspective_id"
            ),
            {"r": relationship_id},
        )
    ]
    status_row = connection.execute(
        text("""
            SELECT st.code, st.display_name FROM campaign.relationship_state rs
            JOIN campaign.relationship_statuses st
              ON st.relationship_status_id = rs.relationship_status_id
            WHERE rs.timeline_id = :t AND rs.relationship_id = :r
              AND rs.perspective_holder_entity_id IS NULL
        """),
        {"t": timeline_id, "r": relationship_id},
    ).one_or_none()
    clock = resolve_effective_clock(connection, timeline_id=timeline_id)
    start_key = (
        None
        if row.started_world_time_id is None
        else world_time_point(connection, row.started_world_time_id)[0]
    )
    end_key = (
        None
        if row.ended_world_time_id is None
        else world_time_point(connection, row.ended_world_time_id)[0]
    )
    archived = str(row.lifecycle) != "active"
    actions: list[str] = ["restore"] if archived else ["update", "archive", "set_perspective"]
    if not archived and row.ended_world_time_id is None and row.started_world_time_id is not None:
        actions.append("end")
    return RelationshipAuthoringView(
        relationship_id=relationship_id,
        kind=kind,
        kind_label=_KIND_LABEL.get(kind, kind.title()),
        relationship_type=str(row.type_code),
        relationship_type_label=str(row.type_label),
        description=row.description,
        started_world_time_id=row.started_world_time_id,
        started=(
            None
            if row.started_world_time_id is None
            else world_time_point(connection, row.started_world_time_id)[1]
        ),
        ended_world_time_id=row.ended_world_time_id,
        ended=(
            None
            if row.ended_world_time_id is None
            else world_time_point(connection, row.ended_world_time_id)[1]
        ),
        lifecycle_status=str(row.lifecycle),
        row_version=int(row.row_version),
        typed=_typed(connection, relationship_id, kind),
        participants=participants,
        perspectives=perspectives,
        current_status=None if status_row is None else str(status_row.code),
        available_actions=actions,
        policy_conflicts=_conflicts(
            str(row.type_code), participants, active_type_codes(connection)
        ),
        period_status=relationship_period_status(
            start_key, end_key, None if clock is None else clock.sort_key
        ),
        as_of=None if clock is None else clock.display,
        current_status_label=None if status_row is None else str(status_row.display_name),
    )


def list_entity_relationships(
    connection: Connection,
    *,
    world_id: uuid.UUID,
    timeline_id: uuid.UUID,
    entity_id: uuid.UUID,
    include_archived: bool,
) -> RelationshipList:
    rows = connection.execute(
        text("""
            SELECT r.relationship_id, r.description, r.started_world_time_id,
                   r.ended_world_time_id, r.row_version,
                   rt.code AS type_code, rt.display_name AS type_label, ls.code AS lifecycle,
                   sw.sort_key AS start_key, ew.sort_key AS end_key,
                   st.code AS status_code, st.display_name AS status_label
            FROM world.relationships r
            JOIN world.relationship_types rt ON rt.relationship_type_id = r.relationship_type_id
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = r.lifecycle_status_id
            LEFT JOIN core.world_times sw ON sw.world_time_id = r.started_world_time_id
            LEFT JOIN core.world_times ew ON ew.world_time_id = r.ended_world_time_id
            LEFT JOIN campaign.relationship_state rs
              ON rs.relationship_id = r.relationship_id AND rs.timeline_id = :t
             AND rs.perspective_holder_entity_id IS NULL
            LEFT JOIN campaign.relationship_statuses st
              ON st.relationship_status_id = rs.relationship_status_id
            WHERE r.world_id = :w
              AND EXISTS (SELECT 1 FROM world.relationship_participants p
                          WHERE p.relationship_id = r.relationship_id AND p.entity_id = :e)
              AND (CAST(:archived AS boolean) OR ls.code = 'active')
            ORDER BY r.created_at, r.relationship_id
        """),
        {"w": world_id, "e": entity_id, "t": timeline_id, "archived": include_archived},
    ).all()
    clock = resolve_effective_clock(connection, timeline_id=timeline_id)
    clock_key = None if clock is None else clock.sort_key
    summaries: list[RelationshipSummary] = []
    active = active_type_codes(connection)
    for r in rows:
        kind = relationship_kind(connection, r.relationship_id)
        typed = _typed(connection, r.relationship_id, kind)
        participants = _participants(connection, r.relationship_id)
        summaries.append(
            RelationshipSummary(
                relationship_id=r.relationship_id,
                kind=kind,
                relationship_type=str(r.type_code),
                relationship_type_label=str(r.type_label),
                description=r.description,
                lifecycle_status=str(r.lifecycle),
                ended=r.ended_world_time_id is not None,
                is_public=typed.get("is_public"),
                row_version=int(r.row_version),
                participants=participants,
                policy_conflicts=_conflicts(str(r.type_code), participants, active),
                started_world_time_id=r.started_world_time_id,
                started=(
                    None
                    if r.started_world_time_id is None
                    else world_time_point(connection, r.started_world_time_id)[1]
                ),
                ended_world_time_id=r.ended_world_time_id,
                ended_at=(
                    None
                    if r.ended_world_time_id is None
                    else world_time_point(connection, r.ended_world_time_id)[1]
                ),
                period_status=relationship_period_status(r.start_key, r.end_key, clock_key),
                in_force=typed.get("is_active") if kind == KIND_POLITICAL else None,
                is_hidden=typed.get("is_hidden") if kind == KIND_ROUTE else None,
                current_status=None if r.status_code is None else str(r.status_code),
                current_status_label=None if r.status_label is None else str(r.status_label),
            )
        )
    return RelationshipList(items=summaries, as_of=None if clock is None else clock.display)
