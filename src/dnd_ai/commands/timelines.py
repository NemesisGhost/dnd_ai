"""Timeline authoring commands (Phase 14).

`insert_root_timeline` is the one row-writer shared by `create_world` (a
world's primary timeline) and `create_timeline` (additional, non-primary root
timelines). Authorization, lifecycle checks, idempotency, and audit belong to
the command or route that calls it, never to this helper.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, text

from ._shared import lookup_id


@dataclass(frozen=True)
class TimelineInsertResult:
    timeline_id: uuid.UUID
    row_version: int


def insert_root_timeline(
    connection: Connection,
    *,
    world_id: uuid.UUID,
    name: str,
    description: str | None,
    is_primary: bool,
) -> TimelineInsertResult:
    """Insert an active root timeline (no parent, no branch point). `name` and
    `description` must already be normalized by the caller."""
    active_status = lookup_id(
        connection, "core", "lifecycle_statuses", "lifecycle_status_id", "active"
    )
    row = connection.execute(
        text("""
            INSERT INTO campaign.timelines
                (world_id, name, description, is_primary, lifecycle_status_id)
            VALUES (:w, :name, :description, :primary, :status)
            RETURNING timeline_id, row_version
        """),
        {
            "w": world_id,
            "name": name,
            "description": description,
            "primary": is_primary,
            "status": active_status,
        },
    ).one()
    return TimelineInsertResult(timeline_id=row.timeline_id, row_version=int(row.row_version))
