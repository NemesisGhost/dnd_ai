"""Editor read models for dungeons and their areas (Phase 15 checkpoint 15.3A-1, D-31).

Two views, both for `canon.edit` holders only (players read dungeon areas through
`queries.dungeon`, audience-filtered): the dungeon aggregate (its areas and every connection) and
one area with its features, hazards and interactables. The dungeon's `row_version` is the token
for every structural change; the area's own `row_version` covers only the area's fields. The
area view also carries the timeline's current state of each part (`state` with the event that
last wrote it) and the choices the state command offers.
"""

import uuid
from dataclasses import dataclass, field

from sqlalchemy import Connection, text

from dnd_ai.domain.content_authoring import content_edit_blocked_reason, evaluate_content_actions
from dnd_ai.domain.entity_lifecycle import BlockedAction
from dnd_ai.queries.content_preconditions import type_specific_blocks

STRUCTURE_ACTIONS = (
    "add_area",
    "add_connection",
    "update_connection",
    "add_feature",
    "update_feature",
    "add_hazard",
    "update_hazard",
    "add_interactable",
    "update_interactable",
)
REMOVE_ACTIONS = (
    "remove_connection",
    "remove_feature",
    "remove_hazard",
    "remove_interactable",
)


@dataclass(frozen=True)
class Reference:
    entity_id: uuid.UUID
    name: str
    canon_status: str
    lifecycle_status: str


@dataclass(frozen=True)
class AreaSummary:
    dungeon_area_id: uuid.UUID
    name: str
    area_type: str | None
    canon_status: str
    lifecycle_status: str
    row_version: int
    feature_count: int
    hazard_count: int
    interactable_count: int


@dataclass(frozen=True)
class ConnectionRow:
    area_connection_id: uuid.UUID
    from_area: Reference
    to_area: Reference
    connection_type: str
    connection_type_label: str
    is_one_way: bool
    is_hidden: bool
    description: str | None
    is_conditional: bool
    condition_description: str | None
    status: str | None = None
    state_event_id: uuid.UUID | None = None


@dataclass(frozen=True)
class DungeonAuthoringView:
    dungeon_id: uuid.UUID
    name: str
    summary: str | None
    danger_level: int | None
    parent: Reference | None
    canon_status: str
    lifecycle_status: str
    row_version: int
    available_actions: list[str]
    blocked_actions: list[BlockedAction]
    areas: list[AreaSummary] = field(default_factory=list)
    connections: list[ConnectionRow] = field(default_factory=list)


@dataclass(frozen=True)
class ChildRow:
    kind: str
    child_id: uuid.UUID
    child_type: str | None
    description: str | None
    is_hidden: bool
    severity: int | None = None
    # Timeline state (None when nothing has been recorded for this timeline).
    status: str | None = None
    is_destroyed: bool | None = None
    condition_notes: str | None = None
    state_event_id: uuid.UUID | None = None


@dataclass(frozen=True)
class AreaState:
    is_searched: bool = False
    is_destroyed: bool = False
    alarm_level: int = 0
    condition_notes: str | None = None
    state_event_id: uuid.UUID | None = None


@dataclass(frozen=True)
class AreaAuthoringView:
    dungeon_area_id: uuid.UUID
    name: str
    summary: str | None
    area_type: str | None
    dimensions: str | None
    environmental_properties: str | None
    dungeon: Reference
    dungeon_row_version: int
    canon_status: str
    lifecycle_status: str
    row_version: int
    available_actions: list[str]
    blocked_actions: list[BlockedAction]
    features: list[ChildRow] = field(default_factory=list)
    hazards: list[ChildRow] = field(default_factory=list)
    interactables: list[ChildRow] = field(default_factory=list)
    connections: list[ConnectionRow] = field(default_factory=list)
    state: AreaState = field(default_factory=AreaState)
    can_set_state: bool = False
    structure_actions: list[str] = field(default_factory=list)
    state_choices: dict[str, list[tuple[str, str]]] = field(default_factory=dict)


def _reference(connection: Connection, entity_id: uuid.UUID) -> Reference:
    row = connection.execute(
        text("""
            SELECT e.canonical_name, cs.code AS canon, ls.code AS lifecycle
            FROM core.entities e
            JOIN core.canon_statuses cs ON cs.canon_status_id = e.canon_status_id
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = e.lifecycle_status_id
            WHERE e.entity_id = :e
        """),
        {"e": entity_id},
    ).one()
    return Reference(entity_id, str(row.canonical_name), str(row.canon), str(row.lifecycle))


def list_connection_types(connection: Connection) -> list[tuple[str, str]]:
    rows = connection.execute(
        text("SELECT code, display_name FROM world.connection_types ORDER BY display_name, code")
    ).all()
    return [(str(r.code), str(r.display_name)) for r in rows]


def _statuses(connection: Connection, table: str) -> list[tuple[str, str]]:
    rows = connection.execute(
        text(f"SELECT code, display_name FROM campaign.{table} ORDER BY sort_order, code")  # noqa: S608
    ).all()
    return [(str(r.code), str(r.display_name)) for r in rows]


def _connection_rows(
    connection: Connection,
    *,
    timeline_id: uuid.UUID | None,
    dungeon_id: uuid.UUID | None = None,
    area_id: uuid.UUID | None = None,
) -> list[ConnectionRow]:
    rows = connection.execute(
        text("""
            SELECT ac.area_connection_id, ac.from_dungeon_area_id, ac.to_dungeon_area_id,
                   ct.code AS type_code, ct.display_name AS type_label, ac.is_one_way,
                   ac.is_hidden, ac.description, ac.is_conditional, ac.condition_description,
                   st.code AS status, acs.last_event_id
            FROM world.area_connections ac
            JOIN world.connection_types ct ON ct.connection_type_id = ac.connection_type_id
            JOIN world.locations fl ON fl.location_id = ac.from_dungeon_area_id
            LEFT JOIN campaign.area_connection_state acs
                   ON acs.area_connection_id = ac.area_connection_id
                  AND acs.timeline_id = CAST(:t AS uuid)
            LEFT JOIN campaign.connection_statuses st
                   ON st.connection_status_id = acs.connection_status_id
            WHERE (CAST(:d AS uuid) IS NOT NULL AND fl.parent_location_id = CAST(:d AS uuid))
               OR (CAST(:a AS uuid) IS NOT NULL
                   AND (ac.from_dungeon_area_id = CAST(:a AS uuid)
                        OR ac.to_dungeon_area_id = CAST(:a AS uuid)))
            ORDER BY ac.created_at, ac.area_connection_id
        """),
        {"t": timeline_id, "d": dungeon_id, "a": area_id},
    ).all()
    return [
        ConnectionRow(
            area_connection_id=r.area_connection_id,
            from_area=_reference(connection, r.from_dungeon_area_id),
            to_area=_reference(connection, r.to_dungeon_area_id),
            connection_type=str(r.type_code),
            connection_type_label=str(r.type_label),
            is_one_way=bool(r.is_one_way),
            is_hidden=bool(r.is_hidden),
            description=r.description,
            is_conditional=bool(r.is_conditional),
            condition_description=r.condition_description,
            status=None if r.status is None else str(r.status),
            state_event_id=r.last_event_id,
        )
        for r in rows
    ]


def get_dungeon_authoring(
    connection: Connection, *, world_id: uuid.UUID, dungeon_id: uuid.UUID
) -> DungeonAuthoringView | None:
    row = connection.execute(
        text("""
            SELECT e.canonical_name, e.summary, e.row_version, d.danger_level,
                   l.parent_location_id, cs.code AS canon, ls.code AS lifecycle
            FROM core.entities e
            JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id
            JOIN core.canon_statuses cs ON cs.canon_status_id = e.canon_status_id
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = e.lifecycle_status_id
            JOIN world.locations l ON l.location_id = e.entity_id
            JOIN world.dungeons d ON d.dungeon_id = e.entity_id
            WHERE e.entity_id = :d AND e.world_id = :w AND et.code = 'dungeon'
        """),
        {"d": dungeon_id, "w": world_id},
    ).one_or_none()
    if row is None:
        return None
    areas = [
        AreaSummary(
            dungeon_area_id=a.dungeon_area_id,
            name=str(a.canonical_name),
            area_type=a.area_type,
            canon_status=str(a.canon),
            lifecycle_status=str(a.lifecycle),
            row_version=int(a.row_version),
            feature_count=int(a.features),
            hazard_count=int(a.hazards),
            interactable_count=int(a.interactables),
        )
        for a in connection.execute(
            text("""
                SELECT da.dungeon_area_id, e.canonical_name, da.area_type, e.row_version,
                       cs.code AS canon, ls.code AS lifecycle,
                       (SELECT count(*) FROM world.area_features f
                         WHERE f.dungeon_area_id = da.dungeon_area_id) AS features,
                       (SELECT count(*) FROM world.area_hazards h
                         WHERE h.dungeon_area_id = da.dungeon_area_id) AS hazards,
                       (SELECT count(*) FROM world.area_interactables i
                         WHERE i.dungeon_area_id = da.dungeon_area_id) AS interactables
                FROM world.dungeon_areas da
                JOIN world.locations l ON l.location_id = da.dungeon_area_id
                JOIN core.entities e ON e.entity_id = da.dungeon_area_id
                JOIN core.canon_statuses cs ON cs.canon_status_id = e.canon_status_id
                JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = e.lifecycle_status_id
                WHERE l.parent_location_id = :d
                ORDER BY lower(e.canonical_name), da.dungeon_area_id
            """),
            {"d": dungeon_id},
        )
    ]
    extra = type_specific_blocks(connection, entity_id=dungeon_id, entity_type_code="dungeon")
    available, blocked = evaluate_content_actions(
        entity_type_code="dungeon",
        canon_status=str(row.canon),
        lifecycle_status=str(row.lifecycle),
        extra_blocked=extra or None,
    )
    if "update" in available:
        available = [*available, *STRUCTURE_ACTIONS]
        if str(row.canon) == "draft":
            available = [*available, *REMOVE_ACTIONS]
        else:
            blocked = [*blocked, *(BlockedAction(a, "dungeon_not_draft") for a in REMOVE_ACTIONS)]
    return DungeonAuthoringView(
        dungeon_id=dungeon_id,
        name=str(row.canonical_name),
        summary=row.summary,
        danger_level=row.danger_level,
        parent=None
        if row.parent_location_id is None
        else _reference(connection, row.parent_location_id),
        canon_status=str(row.canon),
        lifecycle_status=str(row.lifecycle),
        row_version=int(row.row_version),
        available_actions=available,
        blocked_actions=blocked,
        areas=areas,
        connections=_connection_rows(connection, timeline_id=None, dungeon_id=dungeon_id),
    )


def _children(
    connection: Connection, *, timeline_id: uuid.UUID, area_id: uuid.UUID
) -> tuple[list[ChildRow], list[ChildRow], list[ChildRow]]:
    features = [
        ChildRow(
            kind="feature",
            child_id=r.area_feature_id,
            child_type=r.feature_type,
            description=r.description,
            is_hidden=bool(r.is_hidden),
            is_destroyed=bool(r.is_destroyed) if r.last_event_id or r.has_state else None,
            condition_notes=r.condition_notes,
            state_event_id=r.last_event_id,
        )
        for r in connection.execute(
            text("""
                SELECT f.area_feature_id, f.feature_type, f.description, f.is_hidden,
                       s.is_destroyed, s.condition_notes, s.last_event_id,
                       (s.area_feature_id IS NOT NULL) AS has_state
                FROM world.area_features f
                LEFT JOIN campaign.area_feature_state s
                       ON s.area_feature_id = f.area_feature_id AND s.timeline_id = :t
                WHERE f.dungeon_area_id = :a ORDER BY f.created_at, f.area_feature_id
            """),
            {"t": timeline_id, "a": area_id},
        )
    ]
    hazards = [
        ChildRow(
            kind="hazard",
            child_id=r.area_hazard_id,
            child_type=r.hazard_type,
            description=r.description,
            is_hidden=bool(r.is_hidden),
            severity=r.severity,
            status=None if r.status is None else str(r.status),
            state_event_id=r.last_event_id,
        )
        for r in connection.execute(
            text("""
                SELECT h.area_hazard_id, h.hazard_type, h.description, h.is_hidden, h.severity,
                       st.code AS status, s.last_event_id
                FROM world.area_hazards h
                LEFT JOIN campaign.hazard_state s
                       ON s.area_hazard_id = h.area_hazard_id AND s.timeline_id = :t
                LEFT JOIN campaign.hazard_statuses st ON st.hazard_status_id = s.hazard_status_id
                WHERE h.dungeon_area_id = :a ORDER BY h.created_at, h.area_hazard_id
            """),
            {"t": timeline_id, "a": area_id},
        )
    ]
    interactables = [
        ChildRow(
            kind="interactable",
            child_id=r.area_interactable_id,
            child_type=r.interactable_type,
            description=r.description,
            is_hidden=bool(r.is_hidden),
            status=None if r.status is None else str(r.status),
            state_event_id=r.last_event_id,
        )
        for r in connection.execute(
            text("""
                SELECT i.area_interactable_id, i.interactable_type, i.description, i.is_hidden,
                       st.code AS status, s.last_event_id
                FROM world.area_interactables i
                LEFT JOIN campaign.interactable_state s
                       ON s.area_interactable_id = i.area_interactable_id AND s.timeline_id = :t
                LEFT JOIN campaign.interactable_statuses st
                       ON st.interactable_status_id = s.interactable_status_id
                WHERE i.dungeon_area_id = :a ORDER BY i.created_at, i.area_interactable_id
            """),
            {"t": timeline_id, "a": area_id},
        )
    ]
    return features, hazards, interactables


def get_area_authoring(
    connection: Connection,
    *,
    world_id: uuid.UUID,
    timeline_id: uuid.UUID,
    dungeon_area_id: uuid.UUID,
) -> AreaAuthoringView | None:
    row = connection.execute(
        text("""
            SELECT e.canonical_name, e.summary, e.row_version, da.area_type, da.dimensions,
                   da.environmental_properties, l.parent_location_id,
                   cs.code AS canon, ls.code AS lifecycle,
                   pe.row_version AS dungeon_version
            FROM core.entities e
            JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id
            JOIN core.canon_statuses cs ON cs.canon_status_id = e.canon_status_id
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = e.lifecycle_status_id
            JOIN world.locations l ON l.location_id = e.entity_id
            JOIN world.dungeon_areas da ON da.dungeon_area_id = e.entity_id
            JOIN core.entities pe ON pe.entity_id = l.parent_location_id
            WHERE e.entity_id = :a AND e.world_id = :w AND et.code = 'dungeon_area'
        """),
        {"a": dungeon_area_id, "w": world_id},
    ).one_or_none()
    if row is None:
        return None
    dungeon = _reference(connection, row.parent_location_id)
    extra = type_specific_blocks(
        connection, entity_id=dungeon_area_id, entity_type_code="dungeon_area"
    )
    available, blocked = evaluate_content_actions(
        entity_type_code="dungeon_area",
        canon_status=str(row.canon),
        lifecycle_status=str(row.lifecycle),
        extra_blocked=extra or None,
    )
    features, hazards, interactables = _children(
        connection, timeline_id=timeline_id, area_id=dungeon_area_id
    )
    state_row = connection.execute(
        text(
            "SELECT is_searched, is_destroyed, alarm_level, condition_notes, last_event_id "
            "FROM campaign.location_state WHERE timeline_id = :t AND location_id = :a"
        ),
        {"t": timeline_id, "a": dungeon_area_id},
    ).one_or_none()
    published = (
        str(row.canon) == "canon"
        and str(row.lifecycle) == "active"
        and dungeon.canon_status == "canon"
        and dungeon.lifecycle_status == "active"
    )
    structure: list[str] = []
    if (
        "update" in available
        and content_edit_blocked_reason(dungeon.canon_status, dungeon.lifecycle_status) is None
    ):
        structure = [a for a in STRUCTURE_ACTIONS if a != "add_area"]
        if dungeon.canon_status == "draft":
            structure = [*structure, *REMOVE_ACTIONS]
    return AreaAuthoringView(
        dungeon_area_id=dungeon_area_id,
        name=str(row.canonical_name),
        summary=row.summary,
        area_type=row.area_type,
        dimensions=row.dimensions,
        environmental_properties=row.environmental_properties,
        dungeon=dungeon,
        dungeon_row_version=int(row.dungeon_version),
        canon_status=str(row.canon),
        lifecycle_status=str(row.lifecycle),
        row_version=int(row.row_version),
        available_actions=available,
        blocked_actions=blocked,
        features=features,
        hazards=hazards,
        interactables=interactables,
        connections=_connection_rows(connection, timeline_id=timeline_id, area_id=dungeon_area_id),
        state=(
            AreaState()
            if state_row is None
            else AreaState(
                is_searched=bool(state_row.is_searched),
                is_destroyed=bool(state_row.is_destroyed),
                alarm_level=int(state_row.alarm_level),
                condition_notes=state_row.condition_notes,
                state_event_id=state_row.last_event_id,
            )
        ),
        can_set_state=published,
        structure_actions=structure,
        state_choices={
            "connection_status": _statuses(connection, "connection_statuses"),
            "hazard_status": _statuses(connection, "hazard_statuses"),
            "interactable_status": _statuses(connection, "interactable_statuses"),
        },
    )
