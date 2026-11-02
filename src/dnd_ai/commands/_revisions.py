"""Canonical definition revision capture (Phase 15 checkpoint 15.2R).

Every real change to a typed definition writes one full snapshot of the authored
record to `core.entity_revisions`, in the request transaction that made the
change. Snapshots are built directly from the authored record (the typed
authoring views), never from `audit.change_log`: audit is an accountability
record that holds no narrative (checkpoint 15.2A-3), so it cannot be revision
history. The store is GM-only and has no read path until checkpoint 15.3C-2.
"""

import dataclasses
import datetime
import decimal
import enum
import json
import uuid
from typing import Any

from sqlalchemy import Connection, text

REVISION_CREATED = "created"
REVISION_UPDATED = "updated"
REVISION_LIFECYCLE = "lifecycle"

# Server-computed presentation fields and the version (stored separately), never
# part of the authored record.
_EXCLUDED_VIEW_FIELDS = frozenset(
    {"available_actions", "blocked_actions", "field_locks", "row_version", "changed"}
)


def _json_default(value: object) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, datetime.datetime | datetime.date):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, set | frozenset):
        return sorted(str(v) for v in value)
    raise TypeError(f"cannot snapshot {type(value).__name__}")


def snapshot_from_view(view: object) -> dict[str, Any]:
    """The JSON-safe authored record held by a typed authoring view dataclass,
    minus server-computed presentation fields."""
    if not dataclasses.is_dataclass(view) or isinstance(view, type):
        raise TypeError("snapshot_from_view requires a dataclass instance")
    raw = {k: v for k, v in dataclasses.asdict(view).items() if k not in _EXCLUDED_VIEW_FIELDS}
    snapshot = json.loads(json.dumps(raw, default=_json_default))
    assert isinstance(snapshot, dict)
    return snapshot


def capture_revision(
    connection: Connection,
    *,
    entity_id: uuid.UUID,
    world_id: uuid.UUID,
    row_version: int,
    kind: str,
    snapshot: dict[str, Any],
    actor_user_id: uuid.UUID | None,
    correlation_id: str | None,
) -> None:
    """Insert one revision. Call after the change, on the same connection. A
    second revision for the same `(entity_id, row_version)` is a bug and fails
    on the unique constraint rather than being silently ignored."""
    connection.execute(
        text("""
            INSERT INTO core.entity_revisions
                (entity_id, world_id, row_version, revision_kind, snapshot,
                 created_by_user_id, correlation_id)
            VALUES (:entity, :world, :version, :kind, CAST(:snapshot AS jsonb),
                    :actor, CAST(:correlation AS uuid))
        """),
        {
            "entity": entity_id,
            "world": world_id,
            "version": row_version,
            "kind": kind,
            "snapshot": json.dumps(snapshot),
            "actor": actor_user_id,
            "correlation": correlation_id,
        },
    )
