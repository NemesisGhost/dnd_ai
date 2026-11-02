"""Timeline detail read model (Phase 14): the summary plus children, the
campaigns the *caller* manages on it, and server-computed actions from the
same policy the commands enforce, restricted to the actions the caller's world
capabilities allow (`dnd_ai.domain.world_authority.TIMELINE_ACTION_CAPABILITIES`)
— a `world_viewer` sees the timeline and is offered no action on it."""

import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, text

from dnd_ai.domain.authoring_policy import BlockedAction, timeline_actions
from dnd_ai.domain.world_authority import TIMELINE_ACTION_CAPABILITIES, authorized_actions
from dnd_ai.queries.timelines import (
    TimelineSummary,
    get_timeline_summary,
    list_child_timelines,
    timeline_has_blocking_campaigns,
)
from dnd_ai.queries.worlds import ManagedCampaign, list_managed_campaigns


@dataclass(frozen=True)
class TimelineDetail:
    summary: TimelineSummary
    children: list[TimelineSummary]
    managed_campaigns: list[ManagedCampaign]
    available_actions: list[str]
    blocked_actions: list[BlockedAction]


def get_timeline_detail(
    connection: Connection,
    *,
    user_id: uuid.UUID,
    world_id: uuid.UUID,
    timeline_id: uuid.UUID,
    capabilities: frozenset[str],
) -> TimelineDetail | None:
    summary = get_timeline_summary(connection, world_id=world_id, timeline_id=timeline_id)
    if summary is None:
        return None
    world_status = connection.execute(
        text("""
            SELECT ls.code FROM core.worlds w
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = w.lifecycle_status_id
            WHERE w.world_id = :w
        """),
        {"w": world_id},
    ).scalar()
    blocking = timeline_has_blocking_campaigns(connection, timeline_id=timeline_id)
    available, blocked = authorized_actions(
        *timeline_actions(
            world_status=str(world_status),
            timeline_status=summary.lifecycle_status,
            is_primary=summary.is_primary,
            has_blocking_campaigns=blocking,
        ),
        capabilities=capabilities,
        required=TIMELINE_ACTION_CAPABILITIES,
    )
    return TimelineDetail(
        summary=summary,
        children=list_child_timelines(
            connection, world_id=world_id, parent_timeline_id=timeline_id
        ),
        managed_campaigns=list_managed_campaigns(
            connection, user_id=user_id, world_id=world_id, timeline_id=timeline_id
        ),
        available_actions=available,
        blocked_actions=blocked,
    )
