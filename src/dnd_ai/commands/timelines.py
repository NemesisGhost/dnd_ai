"""Timeline authoring commands (Phase 14).

`create_timeline`, `update_timeline`, `create_timeline_branch`,
`archive_timeline`, and `restore_timeline`, plus `insert_root_timeline`, the
one row-writer shared with `create_world` (a world's primary timeline).

Lock order (docs/architecture/SYSTEM_ARCHITECTURE.md §7.1): the world row
`FOR SHARE` first (it conflicts with `archive_world`'s `FOR UPDATE`, so a world
cannot be archived underneath a timeline write), then the timeline row —
`FOR UPDATE` for the timeline being edited/archived/restored, `FOR SHARE` for a
branch's *parent* (it conflicts with that parent's own archive). Authority
(`timeline.manage`) is re-resolved under those locks; every failure to find the
world, the authority, or the timeline *inside that world* is the same
non-disclosing 404.

**Branch points.** A branch is created at one of two kinds of point
(`BranchPoint`):

- `ExistingWorldTime` — the world time of a *recorded* event in
  `campaign.effective_events(parent)`, so inherited ancestor history counts.
  It must also not precede the parent's own branch point: the existing
  `effective_events` caps each ancestor at the *next timeline down's* branch
  point, so branching before one's parent's branch point would let the child
  see ancestor events newer than its own branch point.
- `LatestPoint` — "the present state of the parent's history": a new narrative
  world time one step after everything the parent can see (and never before the
  parent's own branch point). On an event-less timeline that is sort key 0,
  which is what lets a brand-new world branch without any SQL.

Nonexistent, other-world, and not-in-the-parent's-history world times are the
same `BranchPointInvalidError`. `branch_event_id` stays NULL in Phase 14
(attaching a causal event is Phase 15E). Inheritance is by world-time position,
exactly as `effective_events` computes it: a parent event recorded *later* at a
world time at or before the branch point is pre-branch history by definition.
"""

import uuid
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy import Connection, text

from dnd_ai.domain.authoring import (
    BranchPointInvalidError,
    StaleWriteError,
    TimelineNotFoundError,
    WorldNotAuthorizedError,
    normalize_description,
    normalize_label,
    normalize_name,
    normalize_reason,
)
from dnd_ai.domain.authoring_policy import (
    TIMELINE_ARCHIVE,
    TIMELINE_CREATE_BRANCH,
    TIMELINE_RESTORE,
    TIMELINE_UPDATE,
    WORLD_CREATE_TIMELINE,
    raise_for_reason,
    timeline_blocked_reason,
    world_blocked_reason,
)
from dnd_ai.domain.data_classification import audit_change
from dnd_ai.domain.world_authority import TIMELINE_MANAGE
from dnd_ai.queries.timelines import timeline_has_blocking_campaigns
from dnd_ai.queries.world_authority import resolve_world_authority

from ._shared import lifecycle_code, lookup_id


@dataclass(frozen=True)
class TimelineInsertResult:
    timeline_id: uuid.UUID
    row_version: int


@dataclass(frozen=True)
class ExistingWorldTime:
    world_time_id: uuid.UUID
    kind: Literal["existing_world_time"] = "existing_world_time"


@dataclass(frozen=True)
class LatestPoint:
    label: str
    kind: Literal["latest"] = "latest"


BranchPoint = ExistingWorldTime | LatestPoint


@dataclass(frozen=True)
class TimelineMutationResult:
    timeline_id: uuid.UUID
    world_id: uuid.UUID
    row_version: int
    lifecycle_status: str
    changed: bool
    previous_lifecycle_status: str | None = None
    changed_fields: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class CreateBranchResult:
    timeline_id: uuid.UUID
    world_id: uuid.UUID
    parent_timeline_id: uuid.UUID
    branch_world_time_id: uuid.UUID
    row_version: int
    created_world_time_id: uuid.UUID | None


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


def _lock_world_shared(
    connection: Connection, *, world_id: uuid.UUID, actor_user_id: uuid.UUID
) -> str:
    """`FOR SHARE` the world, then re-resolve `timeline.manage` under that
    lock. Returns the world's lifecycle code."""
    row = connection.execute(
        text("""
            SELECT w.lifecycle_status_id
            FROM core.worlds w
            WHERE w.world_id = :w
            FOR SHARE OF w
        """),
        {"w": world_id},
    ).one_or_none()
    if row is None:
        raise WorldNotAuthorizedError(f"world {world_id} does not exist")
    authority = resolve_world_authority(connection, user_id=actor_user_id, world_id=world_id)
    if authority is None or not authority.has_capability(TIMELINE_MANAGE):
        raise WorldNotAuthorizedError(f"user {actor_user_id} lacks timeline.manage on {world_id}")
    return lifecycle_code(connection, row.lifecycle_status_id)


@dataclass(frozen=True)
class _LockedTimeline:
    timeline_id: uuid.UUID
    name: str
    description: str | None
    is_primary: bool
    lifecycle_status: str
    row_version: int
    parent_timeline_id: uuid.UUID | None
    branch_sort_key: int | None


def _lock_timeline(
    connection: Connection,
    *,
    world_id: uuid.UUID,
    timeline_id: uuid.UUID,
    mode: Literal["update", "share"],
) -> _LockedTimeline:
    """Lock a timeline *bound to the world*: one that belongs to another world
    is the same error as one that does not exist."""
    lock = "FOR UPDATE OF t" if mode == "update" else "FOR SHARE OF t"
    row = connection.execute(
        text(f"""
            SELECT t.timeline_id, t.name, t.description, t.is_primary, t.lifecycle_status_id,
                   t.row_version, t.parent_timeline_id, t.branch_world_time_id
            FROM campaign.timelines t
            WHERE t.timeline_id = :t AND t.world_id = :w
            {lock}
        """),
        {"t": timeline_id, "w": world_id},
    ).one_or_none()
    if row is None:
        raise TimelineNotFoundError(f"timeline {timeline_id} is not in world {world_id}")
    branch_sort_key = (
        None
        if row.branch_world_time_id is None
        else connection.execute(
            text("SELECT sort_key FROM core.world_times WHERE world_time_id = :w"),
            {"w": row.branch_world_time_id},
        ).scalar()
    )
    return _LockedTimeline(
        timeline_id=row.timeline_id,
        name=str(row.name),
        description=row.description,
        is_primary=bool(row.is_primary),
        lifecycle_status=lifecycle_code(connection, row.lifecycle_status_id),
        row_version=int(row.row_version),
        parent_timeline_id=row.parent_timeline_id,
        branch_sort_key=None if branch_sort_key is None else int(branch_sort_key),
    )


def _require_timeline_action(
    connection: Connection,
    *,
    action: str,
    world_status: str,
    timeline: _LockedTimeline,
) -> None:
    reason = timeline_blocked_reason(
        action,
        world_status=world_status,
        timeline_status=timeline.lifecycle_status,
        is_primary=timeline.is_primary,
        has_blocking_campaigns=(
            action == TIMELINE_ARCHIVE
            and timeline_has_blocking_campaigns(connection, timeline_id=timeline.timeline_id)
        ),
    )
    if reason is not None:
        raise_for_reason(reason, f"{action} blocked for timeline {timeline.timeline_id}: {reason}")


def create_timeline(
    connection: Connection,
    *,
    world_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    name: str,
    description: str | None,
) -> TimelineInsertResult:
    """An additional, non-primary root timeline in an active world."""
    clean_name = normalize_name(name)
    clean_description = normalize_description(description)
    world_status = _lock_world_shared(connection, world_id=world_id, actor_user_id=actor_user_id)
    reason = world_blocked_reason(
        WORLD_CREATE_TIMELINE, lifecycle_status=world_status, has_blocking_campaigns=False
    )
    if reason is not None:
        raise_for_reason(reason, f"create_timeline blocked for world {world_id}")
    return insert_root_timeline(
        connection,
        world_id=world_id,
        name=clean_name,
        description=clean_description,
        is_primary=False,
    )


def update_timeline(
    connection: Connection,
    *,
    world_id: uuid.UUID,
    timeline_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_row_version: int,
    name: str,
    description: str | None,
) -> TimelineMutationResult:
    """Replace the timeline's editable fields. Lineage, primary flag, and world
    are not editable. A no-op writes, bumps, and audits nothing."""
    clean_name = normalize_name(name)
    clean_description = normalize_description(description)
    world_status = _lock_world_shared(connection, world_id=world_id, actor_user_id=actor_user_id)
    timeline = _lock_timeline(connection, world_id=world_id, timeline_id=timeline_id, mode="update")
    if timeline.row_version != expected_row_version:
        raise StaleWriteError(f"timeline {timeline_id} is at {timeline.row_version}")
    _require_timeline_action(
        connection, action=TIMELINE_UPDATE, world_status=world_status, timeline=timeline
    )
    changed: dict[str, object] = {}
    if clean_name != timeline.name:
        changed["name"] = {"from": timeline.name, "to": clean_name}
    if clean_description != timeline.description:
        changed["description"] = audit_change(
            "description", timeline.description, clean_description
        )
    if not changed:
        return TimelineMutationResult(
            timeline_id=timeline_id,
            world_id=world_id,
            row_version=timeline.row_version,
            lifecycle_status=timeline.lifecycle_status,
            changed=False,
        )
    new_version = connection.execute(
        text(
            "UPDATE campaign.timelines SET name = :n, description = :d "
            "WHERE timeline_id = :t RETURNING row_version"
        ),
        {"n": clean_name, "d": clean_description, "t": timeline_id},
    ).scalar()
    assert isinstance(new_version, int)
    return TimelineMutationResult(
        timeline_id=timeline_id,
        world_id=world_id,
        row_version=new_version,
        lifecycle_status=timeline.lifecycle_status,
        changed=True,
        changed_fields=changed,
    )


def _effective_history_bounds(
    connection: Connection, *, parent_timeline_id: uuid.UUID
) -> int | None:
    """The largest world-time sort key among recorded events in the parent's
    effective history, or `None` when it has none."""
    value = connection.execute(
        text("""
            SELECT max(wt.sort_key)
            FROM campaign.effective_events(:p) e
            JOIN core.world_times wt ON wt.world_time_id = e.world_time_id
        """),
        {"p": parent_timeline_id},
    ).scalar()
    return None if value is None else int(value)


def _resolve_existing_branch_point(
    connection: Connection,
    *,
    world_id: uuid.UUID,
    parent: _LockedTimeline,
    world_time_id: uuid.UUID,
) -> uuid.UUID:
    row = connection.execute(
        text("""
            SELECT wt.sort_key
            FROM core.world_times wt
            WHERE wt.world_time_id = :wt AND wt.world_id = :w
              AND EXISTS (
                  SELECT 1 FROM campaign.effective_events(:p) e
                  WHERE e.world_time_id = wt.world_time_id
              )
        """),
        {"wt": world_time_id, "w": world_id, "p": parent.timeline_id},
    ).one_or_none()
    if row is None:
        raise BranchPointInvalidError(f"world time {world_time_id} is not in the parent's history")
    if parent.branch_sort_key is not None and int(row.sort_key) < parent.branch_sort_key:
        raise BranchPointInvalidError("branch point precedes the parent's own branch point")
    return world_time_id


def _create_latest_world_time(
    connection: Connection, *, world_id: uuid.UUID, parent: _LockedTimeline, label: str
) -> uuid.UUID:
    latest = _effective_history_bounds(connection, parent_timeline_id=parent.timeline_id)
    sort_key = max(
        0 if latest is None else latest + 1,
        0 if parent.branch_sort_key is None else parent.branch_sort_key,
    )
    world_time_id = connection.execute(
        text("""
            INSERT INTO core.world_times (world_id, world_time_precision_id, label, sort_key)
            VALUES (
                :w,
                (SELECT world_time_precision_id FROM core.world_time_precisions
                 WHERE code = 'narrative'),
                :label, :sort_key
            )
            RETURNING world_time_id
        """),
        {"w": world_id, "label": label, "sort_key": sort_key},
    ).scalar()
    assert isinstance(world_time_id, uuid.UUID)
    return world_time_id


def create_timeline_branch(
    connection: Connection,
    *,
    world_id: uuid.UUID,
    parent_timeline_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    name: str,
    description: str | None,
    branch_point: BranchPoint,
) -> CreateBranchResult:
    """Branch an active timeline of an active world. The new timeline is never
    primary. Atomic: for a `LatestPoint` the world time and the timeline are
    created together or not at all."""
    clean_name = normalize_name(name)
    clean_description = normalize_description(description)
    clean_label = (
        normalize_label(branch_point.label) if isinstance(branch_point, LatestPoint) else None
    )
    world_status = _lock_world_shared(connection, world_id=world_id, actor_user_id=actor_user_id)
    parent = _lock_timeline(
        connection, world_id=world_id, timeline_id=parent_timeline_id, mode="share"
    )
    _require_timeline_action(
        connection, action=TIMELINE_CREATE_BRANCH, world_status=world_status, timeline=parent
    )

    created_world_time_id: uuid.UUID | None = None
    if isinstance(branch_point, ExistingWorldTime):
        branch_world_time_id = _resolve_existing_branch_point(
            connection, world_id=world_id, parent=parent, world_time_id=branch_point.world_time_id
        )
    else:
        assert clean_label is not None
        created_world_time_id = _create_latest_world_time(
            connection, world_id=world_id, parent=parent, label=clean_label
        )
        branch_world_time_id = created_world_time_id

    active_status = lookup_id(
        connection, "core", "lifecycle_statuses", "lifecycle_status_id", "active"
    )
    row = connection.execute(
        text("""
            INSERT INTO campaign.timelines
                (world_id, name, description, parent_timeline_id, branch_world_time_id,
                 is_primary, lifecycle_status_id)
            VALUES (:w, :name, :description, :parent, :branch, false, :status)
            RETURNING timeline_id, row_version
        """),
        {
            "w": world_id,
            "name": clean_name,
            "description": clean_description,
            "parent": parent_timeline_id,
            "branch": branch_world_time_id,
            "status": active_status,
        },
    ).one()
    return CreateBranchResult(
        timeline_id=row.timeline_id,
        world_id=world_id,
        parent_timeline_id=parent_timeline_id,
        branch_world_time_id=branch_world_time_id,
        row_version=int(row.row_version),
        created_world_time_id=created_world_time_id,
    )


def _transition_timeline(
    connection: Connection,
    *,
    action: str,
    target_status: str,
    world_id: uuid.UUID,
    timeline_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_row_version: int,
    reason: str | None,
) -> TimelineMutationResult:
    normalize_reason(reason)
    world_status = _lock_world_shared(connection, world_id=world_id, actor_user_id=actor_user_id)
    timeline = _lock_timeline(connection, world_id=world_id, timeline_id=timeline_id, mode="update")
    if timeline.row_version != expected_row_version:
        raise StaleWriteError(f"timeline {timeline_id} is at {timeline.row_version}")
    _require_timeline_action(
        connection, action=action, world_status=world_status, timeline=timeline
    )
    new_version = connection.execute(
        text("""
            UPDATE campaign.timelines
            SET lifecycle_status_id =
                (SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = :code)
            WHERE timeline_id = :t RETURNING row_version
        """),
        {"code": target_status, "t": timeline_id},
    ).scalar()
    assert isinstance(new_version, int)
    return TimelineMutationResult(
        timeline_id=timeline_id,
        world_id=world_id,
        row_version=new_version,
        lifecycle_status=target_status,
        changed=True,
        previous_lifecycle_status=timeline.lifecycle_status,
    )


def archive_timeline(
    connection: Connection,
    *,
    world_id: uuid.UUID,
    timeline_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_row_version: int,
    reason: str | None = None,
) -> TimelineMutationResult:
    """Archive an active, non-primary timeline of an active world with no
    non-archived campaign. Child branches are unaffected (they keep
    inheriting); no new branches or campaigns can attach to it afterward."""
    return _transition_timeline(
        connection,
        action=TIMELINE_ARCHIVE,
        target_status="archived",
        world_id=world_id,
        timeline_id=timeline_id,
        actor_user_id=actor_user_id,
        expected_row_version=expected_row_version,
        reason=reason,
    )


def restore_timeline(
    connection: Connection,
    *,
    world_id: uuid.UUID,
    timeline_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_row_version: int,
    reason: str | None = None,
) -> TimelineMutationResult:
    """Restore an archived timeline; the world must be active."""
    return _transition_timeline(
        connection,
        action=TIMELINE_RESTORE,
        target_status="active",
        world_id=world_id,
        timeline_id=timeline_id,
        actor_user_id=actor_user_id,
        expected_row_version=expected_row_version,
        reason=reason,
    )
