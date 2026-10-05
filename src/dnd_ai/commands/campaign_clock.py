"""Advance and correct the campaign clock (Phase 15 checkpoint 15.2W-2).

Typed timeline state needs a causal event (rule 6): each command records one
`time_advanced` / `time_corrected` event, one `narrative.event_effects` row
(`current_world_time_id`, previous -> new), and writes the clock row, atomically.

- `advance_campaign_clock` moves the clock strictly later than its effective
  current value (a branch's inherited value included). The first write on a
  timeline creates its own row (`expected_row_version` 0).
- `correct_campaign_clock` sets the clock to any *different* time, citing the
  advance (or earlier correction) it corrects; the original event stays in
  history, and the correction event names it as its cause. Only a timeline's own
  clock can be corrected.

Lock order: operation scope (world, membership rows, account, campaign `FOR
SHARE`), then the timeline's clock row `FOR UPDATE`.
"""

import json
import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, text

from dnd_ai.domain.authoring import StaleWriteError
from dnd_ai.domain.campaign_clock import (
    CLOCK_COMPONENT,
    CLOCK_EVENT_ADVANCED,
    CLOCK_EVENT_CORRECTED,
    ClockNotAdvancedError,
    ClockNotSetError,
    ClockUnchangedError,
)
from dnd_ai.domain.data_classification import audit_change
from dnd_ai.domain.world_time import WorldTimeReferenceInvalidError
from dnd_ai.queries.campaign_clock import resolve_effective_clock

from ._operations import OperationScope, lock_operation_scope
from .events import _insert_event_row


@dataclass(frozen=True)
class ClockResult:
    timeline_id: uuid.UUID
    world_id: uuid.UUID
    world_time_id: uuid.UUID
    previous_world_time_id: uuid.UUID | None
    event_id: uuid.UUID
    row_version: int
    created: bool
    changed_fields: dict[str, object]


def _lock_own_clock(
    connection: Connection, timeline_id: uuid.UUID
) -> tuple[uuid.UUID, int, uuid.UUID | None] | None:
    row = connection.execute(
        text("""
            SELECT current_world_time_id, row_version, last_event_id
            FROM campaign.timeline_clocks WHERE timeline_id = :t FOR UPDATE
        """),
        {"t": timeline_id},
    ).one_or_none()
    if row is None:
        return None
    return row.current_world_time_id, int(row.row_version), row.last_event_id


def _target_sort_key(
    connection: Connection, *, world_id: uuid.UUID, world_time_id: uuid.UUID
) -> int:
    key = connection.execute(
        text("SELECT sort_key FROM core.world_times WHERE world_time_id = :t AND world_id = :w"),
        {"t": world_time_id, "w": world_id},
    ).scalar()
    if key is None:
        raise WorldTimeReferenceInvalidError(f"world time {world_time_id} is not in {world_id}")
    assert isinstance(key, int)
    return key


def _record(
    connection: Connection,
    *,
    scope: OperationScope,
    event_type: str,
    event_name: str,
    world_time_id: uuid.UUID,
    previous: uuid.UUID | None,
    cause_event_id: uuid.UUID | None,
    own: tuple[uuid.UUID, int, uuid.UUID | None] | None,
) -> ClockResult:
    event_id = _insert_event_row(
        connection,
        world_id=scope.world_id,
        timeline_id=scope.timeline_id,
        world_time_id=world_time_id,
        event_type_code=event_type,
        name=event_name,
        campaign_id=scope.campaign_id,
        cause_event_id=cause_event_id,
    )
    connection.execute(
        text("""
            INSERT INTO narrative.event_effects
                (event_id, target_component, previous_value, new_value, effective_world_time_id)
            VALUES (:event, :component, CAST(:previous AS jsonb), CAST(:new AS jsonb), :time)
        """),
        {
            "event": event_id,
            "component": CLOCK_COMPONENT,
            "previous": None if previous is None else json.dumps(str(previous)),
            "new": json.dumps(str(world_time_id)),
            "time": world_time_id,
        },
    )
    if own is None:
        version = connection.execute(
            text("""
                INSERT INTO campaign.timeline_clocks
                    (timeline_id, current_world_time_id, last_event_id)
                VALUES (:t, :time, :event)
                ON CONFLICT (timeline_id) DO NOTHING
                RETURNING row_version
            """),
            {"t": scope.timeline_id, "time": world_time_id, "event": event_id},
        ).scalar()
        if version is None:
            # A concurrent first write created the row between our check and this
            # insert: the caller's expected version (0) is stale.
            raise StaleWriteError(f"clock of timeline {scope.timeline_id} was just created")
    else:
        version = connection.execute(
            text("""
                UPDATE campaign.timeline_clocks
                SET current_world_time_id = :time, last_event_id = :event
                WHERE timeline_id = :t RETURNING row_version
            """),
            {"t": scope.timeline_id, "time": world_time_id, "event": event_id},
        ).scalar()
    assert isinstance(version, int)
    return ClockResult(
        timeline_id=scope.timeline_id,
        world_id=scope.world_id,
        world_time_id=world_time_id,
        previous_world_time_id=previous,
        event_id=event_id,
        row_version=version,
        created=own is None,
        changed_fields={
            "current_world_time_id": audit_change(
                "current_world_time_id",
                None if previous is None else str(previous),
                str(world_time_id),
            )
        },
    )


def advance_campaign_clock(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    world_time_id: uuid.UUID,
    expected_row_version: int,
) -> ClockResult:
    scope = lock_operation_scope(connection, campaign_id=campaign_id, actor_user_id=actor_user_id)
    own = _lock_own_clock(connection, scope.timeline_id)
    current_version = 0 if own is None else own[1]
    if expected_row_version != current_version:
        raise StaleWriteError(f"clock of timeline {scope.timeline_id} is at {current_version}")
    target_key = _target_sort_key(connection, world_id=scope.world_id, world_time_id=world_time_id)
    effective = resolve_effective_clock(connection, timeline_id=scope.timeline_id)
    if effective is not None and target_key <= effective.sort_key:
        raise ClockNotAdvancedError(f"{target_key} <= {effective.sort_key}")
    return _record(
        connection,
        scope=scope,
        event_type=CLOCK_EVENT_ADVANCED,
        event_name="The campaign clock advanced",
        world_time_id=world_time_id,
        previous=None if effective is None else effective.world_time_id,
        cause_event_id=None if own is None else own[2],
        own=own,
    )


def correct_campaign_clock(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    world_time_id: uuid.UUID,
    expected_row_version: int,
    corrects_event_id: uuid.UUID,
) -> ClockResult:
    scope = lock_operation_scope(connection, campaign_id=campaign_id, actor_user_id=actor_user_id)
    own = _lock_own_clock(connection, scope.timeline_id)
    if own is None:
        raise ClockNotSetError(f"timeline {scope.timeline_id} has no clock row")
    current_time, current_version, last_event = own
    if expected_row_version != current_version or corrects_event_id != last_event:
        raise StaleWriteError(f"clock of timeline {scope.timeline_id} is at {current_version}")
    _target_sort_key(connection, world_id=scope.world_id, world_time_id=world_time_id)
    if world_time_id == current_time:
        raise ClockUnchangedError(str(world_time_id))
    return _record(
        connection,
        scope=scope,
        event_type=CLOCK_EVENT_CORRECTED,
        event_name="The campaign clock was corrected",
        world_time_id=world_time_id,
        previous=current_time,
        cause_event_id=corrects_event_id,
        own=own,
    )
