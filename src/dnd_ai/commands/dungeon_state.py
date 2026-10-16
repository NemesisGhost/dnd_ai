"""Dungeon runtime state commands (Phase 15 checkpoint 15.3A-1, decision D-31).

`set_dungeon_state` is the GM's explicit command for what is currently true in the campaign's
timeline: an area searched, destroyed or on alert, a connection open or locked, a hazard armed
or triggered, an interactable activated, a feature destroyed. It writes the matching
`campaign.*_state` row and records one `dungeon_state_changed` event with one effect per changed
component, atomically. The definition is never touched, and the interaction commands that
resolve a check keep writing their own events through the same tables.

The caller names the event that last wrote the state row it saw (`expected_last_event_id`, `None`
when there is none); a row that moved is a stale write. The area, its dungeon and a connection's
two areas must be published (`canon` and `active`).

Lock order: operation scope, the areas and dungeon `FOR SHARE` in id order, a per-(timeline,
target) advisory lock that serializes a first write, then the state row `FOR UPDATE`.
"""

import json
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection, text

from dnd_ai.domain.authoring import AuthoringValidationError, StaleWriteError
from dnd_ai.domain.data_classification import audit_change
from dnd_ai.domain.dungeon_authoring import (
    STATE_KINDS,
    StateTargetInvalidError,
    normalize_alarm_level,
    normalize_long_text,
)

from ._content import lock_entities
from ._operations import OperationScope, lock_operation_scope
from ._shared import EntityNotTargetableError
from .events import _insert_event_row
from .quest_runtime import time_or_clock


@dataclass(frozen=True)
class _Field:
    column: str
    component: str
    kind: str  # bool | int | text | status
    default: Any
    lookup: tuple[str, str] | None = None  # (lookup table, id column) for a status


@dataclass(frozen=True)
class _Spec:
    table: str
    key: str
    target_column: str
    fields: dict[str, _Field]


SPECS: dict[str, _Spec] = {
    "area": _Spec(
        "location_state",
        "location_id",
        "target_entity_id",
        {
            "is_searched": _Field("is_searched", "location_is_searched", "bool", False),
            "is_destroyed": _Field("is_destroyed", "location_is_destroyed", "bool", False),
            "alarm_level": _Field("alarm_level", "location_alarm_level", "int", 0),
            "condition_notes": _Field("condition_notes", "location_condition_notes", "text", None),
        },
    ),
    "connection": _Spec(
        "area_connection_state",
        "area_connection_id",
        "target_area_connection_id",
        {
            "connection_status": _Field(
                "connection_status_id",
                "connection_status_id",
                "status",
                None,
                ("connection_statuses", "connection_status_id"),
            )
        },
    ),
    "feature": _Spec(
        "area_feature_state",
        "area_feature_id",
        "target_area_feature_id",
        {
            "is_destroyed": _Field("is_destroyed", "feature_is_destroyed", "bool", False),
            "condition_notes": _Field("condition_notes", "feature_condition_notes", "text", None),
        },
    ),
    "hazard": _Spec(
        "hazard_state",
        "area_hazard_id",
        "target_area_hazard_id",
        {
            "hazard_status": _Field(
                "hazard_status_id",
                "hazard_status_id",
                "status",
                None,
                ("hazard_statuses", "hazard_status_id"),
            )
        },
    ),
    "interactable": _Spec(
        "interactable_state",
        "area_interactable_id",
        "target_area_interactable_id",
        {
            "interactable_status": _Field(
                "interactable_status_id",
                "interactable_status_id",
                "status",
                None,
                ("interactable_statuses", "interactable_status_id"),
            )
        },
    ),
}

# How each kind's target is found and which areas it lives in.
_TARGET_AREAS = {
    "area": "SELECT :t AS a, NULL AS b",
    "connection": (
        "SELECT from_dungeon_area_id AS a, to_dungeon_area_id AS b "
        "FROM world.area_connections WHERE area_connection_id = :t"
    ),
    "feature": "SELECT dungeon_area_id AS a, NULL AS b FROM world.area_features WHERE area_feature_id = :t",
    "hazard": "SELECT dungeon_area_id AS a, NULL AS b FROM world.area_hazards WHERE area_hazard_id = :t",
    "interactable": (
        "SELECT dungeon_area_id AS a, NULL AS b FROM world.area_interactables "
        "WHERE area_interactable_id = :t"
    ),
}


@dataclass(frozen=True)
class DungeonStateResult:
    world_id: uuid.UUID
    area_id: uuid.UUID
    kind: str
    target_id: uuid.UUID
    table: str
    changed: bool
    event_id: uuid.UUID | None
    changed_fields: dict[str, object]


def _validate(spec_field: _Field, name: str, value: Any) -> Any:
    if spec_field.kind == "bool":
        if not isinstance(value, bool):
            raise AuthoringValidationError(f"{name} must be true or false")
        return value
    if spec_field.kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise AuthoringValidationError(f"{name} must be a whole number")
        return normalize_alarm_level(value)
    if spec_field.kind == "text":
        return normalize_long_text(value, field=name)
    if not isinstance(value, str):
        raise AuthoringValidationError(f"{name} must be a status code")
    return value


def _lock_published_areas(
    connection: Connection,
    scope: OperationScope,
    kind: str,
    target_id: uuid.UUID,
    dungeon_area_id: uuid.UUID,
) -> uuid.UUID:
    """The area the target belongs to, after checking the target's areas and their dungeon are
    published and locking them `FOR SHARE`."""
    row = connection.execute(text(_TARGET_AREAS[kind]), {"t": target_id}).one_or_none()
    if row is None or row.a is None:
        raise EntityNotTargetableError(f"{kind} {target_id} does not exist")
    area_ids = [row.a] + ([row.b] if row.b is not None else [])
    if dungeon_area_id not in area_ids:
        raise StateTargetInvalidError(f"{kind} {target_id} is not part of area {dungeon_area_id}")
    dungeon_ids = {
        connection.execute(
            text("SELECT parent_location_id FROM world.locations WHERE location_id = :a"),
            {"a": a},
        ).scalar()
        for a in area_ids
    }
    locked = lock_entities(
        connection, world_id=scope.world_id, share_ids=[*area_ids, *(d for d in dungeon_ids if d)]
    )
    for entity_id in (*area_ids, *(d for d in dungeon_ids if d)):
        entity = locked.get(entity_id)
        if (
            entity is None
            or entity.entity_type_code not in ("dungeon", "dungeon_area")
            or entity.canon_status != "canon"
            or entity.lifecycle_status != "active"
        ):
            raise EntityNotTargetableError(f"{entity_id} is not published")
    return dungeon_area_id


def set_dungeon_state(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    dungeon_area_id: uuid.UUID,
    kind: str,
    target_id: uuid.UUID,
    changes: dict[str, Any],
    expected_last_event_id: uuid.UUID | None,
    world_time_id: uuid.UUID | None = None,
    note: str | None = None,
) -> DungeonStateResult:
    if kind not in STATE_KINDS:
        raise StateTargetInvalidError(f"unknown state kind {kind!r}")
    spec = SPECS[kind]
    unknown = set(changes) - set(spec.fields)
    if unknown or not changes:
        raise StateTargetInvalidError(f"{kind} state has no field(s) {sorted(unknown) or 'given'}")
    clean = {name: _validate(spec.fields[name], name, value) for name, value in changes.items()}
    scope = lock_operation_scope(connection, campaign_id=campaign_id, actor_user_id=actor_user_id)
    area_id = _lock_published_areas(connection, scope, kind, target_id, dungeon_area_id)
    values: dict[str, Any] = {}
    for name, value in clean.items():
        field = spec.fields[name]
        if field.kind == "status":
            assert field.lookup is not None
            found = connection.execute(
                text(f"SELECT {field.lookup[1]} FROM campaign.{field.lookup[0]} WHERE code = :c"),  # noqa: S608
                {"c": value},
            ).scalar()
            if found is None:
                raise StateTargetInvalidError(f"{value!r} is not a valid {name}")
            values[name] = (value, found)
        else:
            values[name] = (value, value)

    connection.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"campaign.dungeon_state:{scope.timeline_id}:{kind}:{target_id}"},
    )
    columns = ", ".join([f.column for f in spec.fields.values()] + ["last_event_id"])
    row = (
        connection.execute(
            text(  # noqa: S608 - fixed table and column names
                f"SELECT {columns} FROM campaign.{spec.table} "
                f"WHERE timeline_id = :t AND {spec.key} = :k FOR UPDATE"
            ),
            {"t": scope.timeline_id, "k": target_id},
        )
        .mappings()
        .one_or_none()
    )
    last_event = None if row is None else row["last_event_id"]
    if last_event != expected_last_event_id:
        raise StaleWriteError(f"{kind} state {target_id} changed")

    def current(name: str) -> Any:
        field = spec.fields[name]
        if row is None:
            return field.default
        value = row[field.column]
        if field.kind == "status" and value is not None:
            assert field.lookup is not None
            return connection.execute(
                text(  # noqa: S608 - fixed lookup names
                    f"SELECT code FROM campaign.{field.lookup[0]} WHERE {field.lookup[1]} = :i"
                ),
                {"i": value},
            ).scalar()
        return value

    differing = {name: v for name, v in values.items() if current(name) != v[0]}
    if not differing:
        return DungeonStateResult(
            world_id=scope.world_id,
            area_id=area_id,
            kind=kind,
            target_id=target_id,
            table=spec.table,
            changed=False,
            event_id=None,
            changed_fields={},
        )

    time_id = time_or_clock(connection, scope, world_time_id)
    event_id = _insert_event_row(
        connection,
        world_id=scope.world_id,
        timeline_id=scope.timeline_id,
        world_time_id=time_id,
        event_type_code="dungeon_state_changed",
        name="Dungeon state changed",
        details=normalize_long_text(note, field="note"),
        campaign_id=campaign_id,
    )
    previous = {name: current(name) for name in differing}
    if row is None:
        insert_columns = [spec.fields[n].column for n in differing]
        connection.execute(
            text(  # noqa: S608 - fixed table and column names
                f"INSERT INTO campaign.{spec.table} (timeline_id, {spec.key}, "
                f"{', '.join(insert_columns)}, last_event_id) VALUES (:t, :k, "
                f"{', '.join(':v_' + c for c in insert_columns)}, :e)"
            ),
            {
                "t": scope.timeline_id,
                "k": target_id,
                "e": event_id,
                **{f"v_{spec.fields[n].column}": differing[n][1] for n in differing},
            },
        )
    else:
        assignments = ", ".join(
            f"{spec.fields[n].column} = :v_{spec.fields[n].column}" for n in differing
        )
        connection.execute(
            text(  # noqa: S608 - fixed table and column names
                f"UPDATE campaign.{spec.table} SET {assignments}, last_event_id = :e, "
                f"updated_at = now() WHERE timeline_id = :t AND {spec.key} = :k"
            ),
            {
                "t": scope.timeline_id,
                "k": target_id,
                "e": event_id,
                **{f"v_{spec.fields[n].column}": differing[n][1] for n in differing},
            },
        )
    for name, (value, _) in differing.items():
        field = spec.fields[name]
        connection.execute(
            text(  # noqa: S608 - the target column comes from the fixed spec
                f"INSERT INTO narrative.event_effects (event_id, {spec.target_column}, "
                "target_component, previous_value, new_value, effective_world_time_id) "
                "VALUES (:e, :target, :c, CAST(:previous AS jsonb), CAST(:new AS jsonb), :time)"
            ),
            {
                "e": event_id,
                "target": target_id,
                "c": field.component,
                "previous": json.dumps(previous[name]),
                "new": json.dumps(value),
                "time": time_id,
            },
        )
    # Status codes and flags are structural; the change log redacts free text.
    return DungeonStateResult(
        world_id=scope.world_id,
        area_id=area_id,
        kind=kind,
        target_id=target_id,
        table=spec.table,
        changed=True,
        event_id=event_id,
        changed_fields={n: audit_change(n, previous[n], differing[n][0]) for n in differing},
    )


__all__ = ["SPECS", "DungeonStateResult", "set_dungeon_state"]
