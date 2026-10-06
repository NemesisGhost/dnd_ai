"""Dungeon, area and structural-child authoring commands (Phase 15 checkpoint 15.3A-1, D-31).

A dungeon (`world.dungeons`) and each of its areas (`world.dungeon_areas`) are lifecycle-managed
location definitions. Connections between areas and the features, hazards and interactables in
an area are structural children of the dungeon aggregate: every change to one takes the
dungeon's `expected_row_version`, locks the dungeon `FOR UPDATE`, and bumps its root version
(decision D-31, option a). An area's own name, summary and typed fields are versioned by the
area entity itself. All of this writes **definition** rows only; what is currently true in a
timeline is `commands.dungeon_state`.

- A connection joins two different areas of the dungeon (endpoints never change afterwards).
- A child can be removed only while the dungeon is a draft (nothing can refer to it yet);
  afterwards it is changed in place, and `is_hidden` says whether the object is built to be
  concealed (never whether anyone found it).
- An area is created as a draft under an active dungeon and published separately, after its
  dungeon.

Lock order: authority scope, then entities by ascending id (the dungeon `FOR UPDATE`; its areas
`FOR SHARE`, or for an area edit the area `FOR UPDATE` and its dungeon `FOR SHARE`).
"""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection, text

from dnd_ai.domain.authoring import (
    ContentNotEditableError,
    ParentLocationInvalidError,
    normalize_description,
    normalize_name,
    normalize_reason,
)
from dnd_ai.domain.content_authoring import (
    AUTHORABLE_LOCATION_CATEGORIES,
    content_edit_blocked_reason,
    diff_fields,
    initial_fields,
)
from dnd_ai.domain.dungeon_authoring import (
    AREA_TYPE,
    DUNGEON_TYPE,
    MAX_AREAS,
    MAX_CHILDREN_PER_AREA,
    ConnectionInvalidError,
    ConnectionTypeInvalidError,
    DungeonLimitError,
    DungeonNotDraftError,
    normalize_child_text,
    normalize_long_text,
    normalize_rating,
)

from ._content import (
    ContentWriteResult,
    EntityNotFoundError,
    LockedContent,
    editable_target,
    insert_draft_entity,
    insert_gm_source,
    lock_authoring_scope,
    lock_entities,
    touch_entity,
    usable_reference,
)

_DUNGEON = frozenset({DUNGEON_TYPE})
_AREA = frozenset({AREA_TYPE})

# kind -> (table, id column, type column, rating column or None)
_CHILD_TABLES = {
    "feature": ("area_features", "area_feature_id", "feature_type", None),
    "hazard": ("area_hazards", "area_hazard_id", "hazard_type", "severity"),
    "interactable": ("area_interactables", "area_interactable_id", "interactable_type", None),
}


def _text_id(value: uuid.UUID | None) -> str | None:
    return None if value is None else str(value)


# --- the dungeon root ----------------------------------------------------------------------------


def create_dungeon(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    name: str | None,
    summary: str | None,
    danger_level: int | None = None,
    parent_location_id: uuid.UUID | None = None,
) -> ContentWriteResult:
    clean_name = normalize_name(name)
    clean_summary = normalize_description(summary)
    clean_danger = normalize_rating(danger_level, field="danger_level")
    scope = lock_authoring_scope(connection, campaign_id=campaign_id, actor_user_id=actor_user_id)
    if parent_location_id is not None:
        locked = lock_entities(connection, world_id=scope.world_id, share_ids=[parent_location_id])
        usable_reference(
            locked,
            parent_location_id,
            type_codes=AUTHORABLE_LOCATION_CATEGORIES,
            error=ParentLocationInvalidError,
        )
    source_id = insert_gm_source(connection, world_id=scope.world_id, actor_user_id=actor_user_id)
    entity_id, row_version = insert_draft_entity(
        connection,
        world_id=scope.world_id,
        entity_type_code=DUNGEON_TYPE,
        name=clean_name,
        summary=clean_summary,
        source_id=source_id,
        actor_user_id=actor_user_id,
    )
    connection.execute(
        text("INSERT INTO world.locations (location_id, parent_location_id) VALUES (:l, :p)"),
        {"l": entity_id, "p": parent_location_id},
    )
    connection.execute(
        text("INSERT INTO world.dungeons (dungeon_id, danger_level) VALUES (:l, :d)"),
        {"l": entity_id, "d": clean_danger},
    )
    return ContentWriteResult(
        entity_id=entity_id,
        world_id=scope.world_id,
        entity_type_code=DUNGEON_TYPE,
        row_version=row_version,
        created=True,
        changed=True,
        changed_fields=initial_fields(
            {
                "name": clean_name,
                "summary": clean_summary,
                "danger_level": clean_danger,
                "parent_location_id": _text_id(parent_location_id),
            }
        ),
        source_id=source_id,
    )


def update_dungeon(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    dungeon_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_row_version: int,
    name: str | None,
    summary: str | None,
    danger_level: int | None = None,
    parent_location_id: uuid.UUID | None = None,
    change_note: str | None = None,
) -> ContentWriteResult:
    normalize_reason(change_note)
    scope = lock_authoring_scope(connection, campaign_id=campaign_id, actor_user_id=actor_user_id)
    current = connection.execute(
        text(
            "SELECT l.parent_location_id, d.danger_level FROM world.locations l "
            "JOIN world.dungeons d ON d.dungeon_id = l.location_id WHERE l.location_id = :d"
        ),
        {"d": dungeon_id},
    ).one_or_none()
    share_ids = (
        [parent_location_id]
        if parent_location_id is not None
        and (current is None or parent_location_id != current.parent_location_id)
        else []
    )
    locked = lock_entities(
        connection, world_id=scope.world_id, update_ids=[dungeon_id], share_ids=share_ids
    )
    target = editable_target(
        locked,
        entity_id=dungeon_id,
        type_codes=_DUNGEON,
        expected_row_version=expected_row_version,
    )
    clean_name = normalize_name(name)
    clean_summary = normalize_description(summary)
    clean_danger = normalize_rating(danger_level, field="danger_level")
    assert current is not None
    before = {
        "name": target.canonical_name,
        "summary": target.summary,
        "danger_level": current.danger_level,
        "parent_location_id": _text_id(current.parent_location_id),
    }
    after = {
        "name": clean_name,
        "summary": clean_summary,
        "danger_level": clean_danger,
        "parent_location_id": _text_id(parent_location_id),
    }
    changed = diff_fields(before, after)
    if not changed:
        return ContentWriteResult(
            entity_id=dungeon_id,
            world_id=scope.world_id,
            entity_type_code=DUNGEON_TYPE,
            row_version=target.row_version,
            created=False,
            changed=False,
        )
    if "parent_location_id" in changed and parent_location_id is not None:
        usable_reference(
            locked,
            parent_location_id,
            type_codes=AUTHORABLE_LOCATION_CATEGORIES,
            error=ParentLocationInvalidError,
        )
    version = touch_entity(connection, entity_id=dungeon_id, name=clean_name, summary=clean_summary)
    if "parent_location_id" in changed:
        connection.execute(
            text("UPDATE world.locations SET parent_location_id = :p WHERE location_id = :l"),
            {"p": parent_location_id, "l": dungeon_id},
        )
    if "danger_level" in changed:
        connection.execute(
            text("UPDATE world.dungeons SET danger_level = :d WHERE dungeon_id = :l"),
            {"d": clean_danger, "l": dungeon_id},
        )
    return ContentWriteResult(
        entity_id=dungeon_id,
        world_id=scope.world_id,
        entity_type_code=DUNGEON_TYPE,
        row_version=version,
        created=False,
        changed=True,
        changed_fields=dict(changed),
    )


# --- areas ------------------------------------------------------------------------------------


def create_dungeon_area(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    dungeon_id: uuid.UUID,
    name: str | None,
    summary: str | None,
    area_type: str | None = None,
    dimensions: str | None = None,
    environmental_properties: str | None = None,
) -> ContentWriteResult:
    clean_name = normalize_name(name)
    clean_summary = normalize_description(summary)
    clean_type = normalize_child_text(area_type, field="area_type")
    clean_dimensions = normalize_child_text(dimensions, field="dimensions")
    clean_environment = normalize_long_text(
        environmental_properties, field="environmental_properties"
    )
    scope = lock_authoring_scope(connection, campaign_id=campaign_id, actor_user_id=actor_user_id)
    locked = lock_entities(connection, world_id=scope.world_id, share_ids=[dungeon_id])
    usable_reference(locked, dungeon_id, type_codes=_DUNGEON, error=ParentLocationInvalidError)
    count = connection.execute(
        text("SELECT count(*) FROM world.locations WHERE parent_location_id = :d"),
        {"d": dungeon_id},
    ).scalar()
    if isinstance(count, int) and count >= MAX_AREAS:
        raise DungeonLimitError(f"dungeon {dungeon_id} has {count} areas")
    source_id = insert_gm_source(connection, world_id=scope.world_id, actor_user_id=actor_user_id)
    entity_id, row_version = insert_draft_entity(
        connection,
        world_id=scope.world_id,
        entity_type_code=AREA_TYPE,
        name=clean_name,
        summary=clean_summary,
        source_id=source_id,
        actor_user_id=actor_user_id,
    )
    connection.execute(
        text("INSERT INTO world.locations (location_id, parent_location_id) VALUES (:l, :p)"),
        {"l": entity_id, "p": dungeon_id},
    )
    connection.execute(
        text("""
            INSERT INTO world.dungeon_areas
                (dungeon_area_id, area_type, dimensions, environmental_properties)
            VALUES (:l, :t, :d, :e)
        """),
        {"l": entity_id, "t": clean_type, "d": clean_dimensions, "e": clean_environment},
    )
    return ContentWriteResult(
        entity_id=entity_id,
        world_id=scope.world_id,
        entity_type_code=AREA_TYPE,
        row_version=row_version,
        created=True,
        changed=True,
        changed_fields=initial_fields(
            {
                "name": clean_name,
                "summary": clean_summary,
                "parent_location_id": str(dungeon_id),
                "area_type": clean_type,
                "dimensions": clean_dimensions,
                "environmental_properties": clean_environment,
            }
        ),
        source_id=source_id,
    )


def update_dungeon_area(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    dungeon_area_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_row_version: int,
    name: str | None,
    summary: str | None,
    area_type: str | None = None,
    dimensions: str | None = None,
    environmental_properties: str | None = None,
    change_note: str | None = None,
) -> ContentWriteResult:
    normalize_reason(change_note)
    scope = lock_authoring_scope(connection, campaign_id=campaign_id, actor_user_id=actor_user_id)
    current = connection.execute(
        text(
            "SELECT l.parent_location_id, a.area_type, a.dimensions, a.environmental_properties "
            "FROM world.locations l JOIN world.dungeon_areas a ON a.dungeon_area_id = l.location_id "
            "WHERE l.location_id = :a"
        ),
        {"a": dungeon_area_id},
    ).one_or_none()
    if current is None:
        raise EntityNotFoundError(f"area {dungeon_area_id} does not exist")
    locked = lock_entities(
        connection,
        world_id=scope.world_id,
        update_ids=[dungeon_area_id],
        share_ids=[current.parent_location_id],
    )
    target = editable_target(
        locked,
        entity_id=dungeon_area_id,
        type_codes=_AREA,
        expected_row_version=expected_row_version,
    )
    clean_name = normalize_name(name)
    clean_summary = normalize_description(summary)
    clean_type = normalize_child_text(area_type, field="area_type")
    clean_dimensions = normalize_child_text(dimensions, field="dimensions")
    clean_environment = normalize_long_text(
        environmental_properties, field="environmental_properties"
    )
    before = {
        "name": target.canonical_name,
        "summary": target.summary,
        "area_type": current.area_type,
        "dimensions": current.dimensions,
        "environmental_properties": current.environmental_properties,
    }
    after = {
        "name": clean_name,
        "summary": clean_summary,
        "area_type": clean_type,
        "dimensions": clean_dimensions,
        "environmental_properties": clean_environment,
    }
    changed = diff_fields(before, after)
    if not changed:
        return ContentWriteResult(
            entity_id=dungeon_area_id,
            world_id=scope.world_id,
            entity_type_code=AREA_TYPE,
            row_version=target.row_version,
            created=False,
            changed=False,
        )
    version = touch_entity(
        connection, entity_id=dungeon_area_id, name=clean_name, summary=clean_summary
    )
    connection.execute(
        text("""
            UPDATE world.dungeon_areas
            SET area_type = :t, dimensions = :d, environmental_properties = :e
            WHERE dungeon_area_id = :a
        """),
        {
            "t": clean_type,
            "d": clean_dimensions,
            "e": clean_environment,
            "a": dungeon_area_id,
        },
    )
    return ContentWriteResult(
        entity_id=dungeon_area_id,
        world_id=scope.world_id,
        entity_type_code=AREA_TYPE,
        row_version=version,
        created=False,
        changed=True,
        changed_fields=dict(changed),
    )


# --- structural children (the dungeon root's version covers all of them) -----------------------


@dataclass(frozen=True)
class _Aggregate:
    scope_world_id: uuid.UUID
    dungeon: LockedContent
    locked: dict[uuid.UUID, LockedContent]


def _lock_aggregate(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    dungeon_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_row_version: int,
    area_ids: tuple[uuid.UUID, ...],
) -> _Aggregate:
    scope = lock_authoring_scope(connection, campaign_id=campaign_id, actor_user_id=actor_user_id)
    locked = lock_entities(
        connection,
        world_id=scope.world_id,
        update_ids=[dungeon_id],
        share_ids=[a for a in area_ids if a != dungeon_id],
    )
    dungeon = editable_target(
        locked,
        entity_id=dungeon_id,
        type_codes=_DUNGEON,
        expected_row_version=expected_row_version,
    )
    for area_id in area_ids:
        area = locked.get(area_id)
        parent = connection.execute(
            text("SELECT parent_location_id FROM world.locations WHERE location_id = :a"),
            {"a": area_id},
        ).scalar()
        if area is None or area.entity_type_code != AREA_TYPE or parent != dungeon_id:
            raise EntityNotFoundError(f"area {area_id} is not part of dungeon {dungeon_id}")
        reason = content_edit_blocked_reason(area.canon_status, area.lifecycle_status)
        if reason is not None:
            raise ContentNotEditableError(f"area {area_id} cannot be edited: {reason}")
    return _Aggregate(scope.world_id, dungeon, locked)


def _bump(connection: Connection, aggregate: _Aggregate) -> int:
    return touch_entity(
        connection,
        entity_id=aggregate.dungeon.entity_id,
        name=aggregate.dungeon.canonical_name,
        summary=aggregate.dungeon.summary,
    )


def _child_result(
    aggregate: _Aggregate,
    *,
    row_version: int,
    table: str,
    record_id: uuid.UUID,
    action: str,
    fields: dict[str, object],
) -> ContentWriteResult:
    return ContentWriteResult(
        entity_id=aggregate.dungeon.entity_id,
        world_id=aggregate.scope_world_id,
        entity_type_code=DUNGEON_TYPE,
        row_version=row_version,
        created=action == "created",
        changed=True,
        changed_fields=fields,
        record_schema="world",
        record_table=table,
        record_id=record_id,
        action=action,
    )


def _noop(aggregate: _Aggregate) -> ContentWriteResult:
    return ContentWriteResult(
        entity_id=aggregate.dungeon.entity_id,
        world_id=aggregate.scope_world_id,
        entity_type_code=DUNGEON_TYPE,
        row_version=aggregate.dungeon.row_version,
        created=False,
        changed=False,
    )


def _require_draft(aggregate: _Aggregate) -> None:
    if aggregate.dungeon.canon_status != "draft":
        raise DungeonNotDraftError(f"dungeon {aggregate.dungeon.entity_id} is not a draft")


def _connection_type_id(connection: Connection, code: str | None) -> uuid.UUID:
    value = connection.execute(
        text("SELECT connection_type_id FROM world.connection_types WHERE code = :c"),
        {"c": code},
    ).scalar()
    if value is None:
        raise ConnectionTypeInvalidError(f"unknown connection type {code!r}")
    assert isinstance(value, uuid.UUID)
    return value


def _conditional(is_conditional: bool, description: str | None) -> str | None:
    clean = normalize_long_text(description, field="condition_description")
    if is_conditional and clean is None:
        raise ConnectionInvalidError("a conditional connection needs its condition")
    return clean if is_conditional else None


def add_connection(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    dungeon_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_row_version: int,
    from_area_id: uuid.UUID,
    to_area_id: uuid.UUID,
    connection_type: str | None,
    is_one_way: bool = False,
    is_hidden: bool = False,
    description: str | None = None,
    is_conditional: bool = False,
    condition_description: str | None = None,
) -> ContentWriteResult:
    if from_area_id == to_area_id:
        raise ConnectionInvalidError("a connection joins two different areas")
    clean_description = normalize_long_text(description, field="description")
    condition = _conditional(is_conditional, condition_description)
    aggregate = _lock_aggregate(
        connection,
        campaign_id=campaign_id,
        dungeon_id=dungeon_id,
        actor_user_id=actor_user_id,
        expected_row_version=expected_row_version,
        area_ids=(from_area_id, to_area_id),
    )
    type_id = _connection_type_id(connection, connection_type)
    row_id = connection.execute(
        text("""
            INSERT INTO world.area_connections
                (from_dungeon_area_id, to_dungeon_area_id, connection_type_id, is_one_way,
                 is_hidden, description, is_conditional, condition_description)
            VALUES (:f, :t, :type, :one, :hidden, :d, :cond, :cd)
            RETURNING area_connection_id
        """),
        {
            "f": from_area_id,
            "t": to_area_id,
            "type": type_id,
            "one": is_one_way,
            "hidden": is_hidden,
            "d": clean_description,
            "cond": is_conditional,
            "cd": condition,
        },
    ).scalar()
    assert isinstance(row_id, uuid.UUID)
    return _child_result(
        aggregate,
        row_version=_bump(connection, aggregate),
        table="area_connections",
        record_id=row_id,
        action="created",
        fields=initial_fields(
            {
                "from_dungeon_area_id": str(from_area_id),
                "to_dungeon_area_id": str(to_area_id),
                "connection_type": connection_type,
                "is_one_way": is_one_way,
                "is_hidden": is_hidden,
                "description": clean_description,
                "is_conditional": is_conditional,
                "condition_description": condition,
            }
        ),
    )


def _connection_row(connection: Connection, dungeon_id: uuid.UUID, connection_id: uuid.UUID) -> Any:
    row = connection.execute(
        text("""
            SELECT ac.area_connection_id, ac.from_dungeon_area_id, ac.to_dungeon_area_id,
                   ct.code AS connection_type, ac.is_one_way, ac.is_hidden, ac.description,
                   ac.is_conditional, ac.condition_description
            FROM world.area_connections ac
            JOIN world.connection_types ct ON ct.connection_type_id = ac.connection_type_id
            JOIN world.locations l ON l.location_id = ac.from_dungeon_area_id
            WHERE ac.area_connection_id = :c AND l.parent_location_id = :d
            FOR UPDATE OF ac
        """),
        {"c": connection_id, "d": dungeon_id},
    ).one_or_none()
    if row is None:
        raise EntityNotFoundError(f"connection {connection_id} is not part of dungeon {dungeon_id}")
    return row


def update_connection(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    dungeon_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_row_version: int,
    area_connection_id: uuid.UUID,
    connection_type: str | None,
    is_one_way: bool = False,
    is_hidden: bool = False,
    description: str | None = None,
    is_conditional: bool = False,
    condition_description: str | None = None,
) -> ContentWriteResult:
    """Endpoints never change; to rewire, remove the connection (while draft) and add another."""
    clean_description = normalize_long_text(description, field="description")
    condition = _conditional(is_conditional, condition_description)
    aggregate = _lock_aggregate(
        connection,
        campaign_id=campaign_id,
        dungeon_id=dungeon_id,
        actor_user_id=actor_user_id,
        expected_row_version=expected_row_version,
        area_ids=(),
    )
    row = _connection_row(connection, dungeon_id, area_connection_id)
    before = {
        "connection_type": row.connection_type,
        "is_one_way": row.is_one_way,
        "is_hidden": row.is_hidden,
        "description": row.description,
        "is_conditional": row.is_conditional,
        "condition_description": row.condition_description,
    }
    after = {
        "connection_type": connection_type,
        "is_one_way": is_one_way,
        "is_hidden": is_hidden,
        "description": clean_description,
        "is_conditional": is_conditional,
        "condition_description": condition,
    }
    changed = diff_fields(before, after)
    if not changed:
        return _noop(aggregate)
    type_id = _connection_type_id(connection, connection_type)
    connection.execute(
        text("""
            UPDATE world.area_connections
            SET connection_type_id = :type, is_one_way = :one, is_hidden = :hidden,
                description = :d, is_conditional = :cond, condition_description = :cd
            WHERE area_connection_id = :c
        """),
        {
            "type": type_id,
            "one": is_one_way,
            "hidden": is_hidden,
            "d": clean_description,
            "cond": is_conditional,
            "cd": condition,
            "c": area_connection_id,
        },
    )
    return _child_result(
        aggregate,
        row_version=_bump(connection, aggregate),
        table="area_connections",
        record_id=area_connection_id,
        action="updated",
        fields=dict(changed),
    )


def remove_connection(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    dungeon_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_row_version: int,
    area_connection_id: uuid.UUID,
) -> ContentWriteResult:
    aggregate = _lock_aggregate(
        connection,
        campaign_id=campaign_id,
        dungeon_id=dungeon_id,
        actor_user_id=actor_user_id,
        expected_row_version=expected_row_version,
        area_ids=(),
    )
    _require_draft(aggregate)
    row = _connection_row(connection, dungeon_id, area_connection_id)
    connection.execute(
        text("DELETE FROM world.area_connections WHERE area_connection_id = :c"),
        {"c": area_connection_id},
    )
    return _child_result(
        aggregate,
        row_version=_bump(connection, aggregate),
        table="area_connections",
        record_id=area_connection_id,
        action="deleted",
        fields=initial_fields(
            {
                "from_dungeon_area_id": str(row.from_dungeon_area_id),
                "to_dungeon_area_id": str(row.to_dungeon_area_id),
            }
        ),
    )


def _child_fields(
    kind: str,
    *,
    child_type: str | None,
    description: str | None,
    is_hidden: bool,
    severity: int | None,
) -> dict[str, object]:
    fields: dict[str, object] = {
        _CHILD_TABLES[kind][2]: normalize_child_text(child_type, field=_CHILD_TABLES[kind][2]),
        "description": normalize_long_text(description, field="description"),
        "is_hidden": is_hidden,
    }
    if _CHILD_TABLES[kind][3] is not None:
        fields["severity"] = normalize_rating(severity, field="severity")
    return fields


def add_area_child(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    dungeon_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_row_version: int,
    dungeon_area_id: uuid.UUID,
    kind: str,
    child_type: str | None,
    description: str | None,
    is_hidden: bool = False,
    severity: int | None = None,
) -> ContentWriteResult:
    table, id_column, type_column, rating = _CHILD_TABLES[kind]
    fields = _child_fields(
        kind,
        child_type=child_type,
        description=description,
        is_hidden=is_hidden,
        severity=severity,
    )
    aggregate = _lock_aggregate(
        connection,
        campaign_id=campaign_id,
        dungeon_id=dungeon_id,
        actor_user_id=actor_user_id,
        expected_row_version=expected_row_version,
        area_ids=(dungeon_area_id,),
    )
    count = connection.execute(
        text(f"SELECT count(*) FROM world.{table} WHERE dungeon_area_id = :a"),  # noqa: S608
        {"a": dungeon_area_id},
    ).scalar()
    if isinstance(count, int) and count >= MAX_CHILDREN_PER_AREA:
        raise DungeonLimitError(f"area {dungeon_area_id} has {count} {table}")
    columns = ["dungeon_area_id", type_column, "description", "is_hidden"]
    if rating is not None:
        columns.append(rating)
    values = {
        "dungeon_area_id": dungeon_area_id,
        type_column: fields[type_column],
        "description": fields["description"],
        "is_hidden": is_hidden,
    }
    if rating is not None:
        values[rating] = fields["severity"]
    row_id = connection.execute(
        text(  # noqa: S608 - table and column names come from the fixed mapping above
            f"INSERT INTO world.{table} ({', '.join(columns)}) "
            f"VALUES ({', '.join(':' + c for c in columns)}) RETURNING {id_column}"
        ),
        values,
    ).scalar()
    assert isinstance(row_id, uuid.UUID)
    return _child_result(
        aggregate,
        row_version=_bump(connection, aggregate),
        table=table,
        record_id=row_id,
        action="created",
        fields=initial_fields({"dungeon_area_id": str(dungeon_area_id), **fields}),
    )


def _child_row(
    connection: Connection, dungeon_id: uuid.UUID, kind: str, child_id: uuid.UUID
) -> Any:
    table, id_column, _, _ = _CHILD_TABLES[kind]
    row = (
        connection.execute(
            text(  # noqa: S608 - fixed table and column names
                f"SELECT c.*, l.parent_location_id FROM world.{table} c "
                "JOIN world.locations l ON l.location_id = c.dungeon_area_id "
                f"WHERE c.{id_column} = :c AND l.parent_location_id = :d FOR UPDATE OF c"
            ),
            {"c": child_id, "d": dungeon_id},
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise EntityNotFoundError(f"{kind} {child_id} is not part of dungeon {dungeon_id}")
    return row


def update_area_child(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    dungeon_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_row_version: int,
    kind: str,
    child_id: uuid.UUID,
    child_type: str | None,
    description: str | None,
    is_hidden: bool = False,
    severity: int | None = None,
) -> ContentWriteResult:
    table, id_column, type_column, rating = _CHILD_TABLES[kind]
    after = _child_fields(
        kind,
        child_type=child_type,
        description=description,
        is_hidden=is_hidden,
        severity=severity,
    )
    aggregate = _lock_aggregate(
        connection,
        campaign_id=campaign_id,
        dungeon_id=dungeon_id,
        actor_user_id=actor_user_id,
        expected_row_version=expected_row_version,
        area_ids=(),
    )
    row = _child_row(connection, dungeon_id, kind, child_id)
    area = aggregate.locked.get(row["dungeon_area_id"])
    if area is None:
        locked = lock_entities(
            connection, world_id=aggregate.scope_world_id, share_ids=[row["dungeon_area_id"]]
        )
        area = locked.get(row["dungeon_area_id"])
    if area is None or area.lifecycle_status != "active":
        raise ContentNotEditableError(f"area {row['dungeon_area_id']} cannot be edited")
    before = {key: row[key] for key in after}
    changed = diff_fields(before, after)
    if not changed:
        return _noop(aggregate)
    assignments = ", ".join(f"{column} = :{column}" for column in after)
    connection.execute(
        text(  # noqa: S608 - fixed table and column names
            f"UPDATE world.{table} SET {assignments} WHERE {id_column} = :id"
        ),
        {**after, "id": child_id},
    )
    del type_column, rating
    return _child_result(
        aggregate,
        row_version=_bump(connection, aggregate),
        table=table,
        record_id=child_id,
        action="updated",
        fields=dict(changed),
    )


def remove_area_child(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    dungeon_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_row_version: int,
    kind: str,
    child_id: uuid.UUID,
) -> ContentWriteResult:
    table, id_column, _, _ = _CHILD_TABLES[kind]
    aggregate = _lock_aggregate(
        connection,
        campaign_id=campaign_id,
        dungeon_id=dungeon_id,
        actor_user_id=actor_user_id,
        expected_row_version=expected_row_version,
        area_ids=(),
    )
    _require_draft(aggregate)
    row = _child_row(connection, dungeon_id, kind, child_id)
    connection.execute(
        text(f"DELETE FROM world.{table} WHERE {id_column} = :c"),  # noqa: S608
        {"c": child_id},
    )
    return _child_result(
        aggregate,
        row_version=_bump(connection, aggregate),
        table=table,
        record_id=child_id,
        action="deleted",
        fields=initial_fields({"dungeon_area_id": str(row["dungeon_area_id"])}),
    )
