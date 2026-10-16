"""Shared plumbing for campaign *operation* commands (Phase 15 completion).

Operations (world time, the campaign clock, sessions, parties, events, timeline
state) act on the campaign's own pinned timeline rather than on an authored
definition. They start from the same lock order and the same under-lock
authority re-check as the typed definition commands: this module delegates to
`dnd_ai.commands._content.lock_authoring_scope` (world `FOR SHARE`, the actor's
membership and role rows, the actor's account, the campaign `FOR SHARE`, then
`canon.edit` re-resolved from committed state) and adds the campaign's timeline.

No timeline row lock is taken: `archive_timeline` already refuses while a campaign
on it is active, and the campaign is held `FOR SHARE` for the whole command.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, text

from ._content import CANON_EDIT, lock_authoring_scope


@dataclass(frozen=True)
class OperationScope:
    world_id: uuid.UUID
    timeline_id: uuid.UUID
    campaign_id: uuid.UUID


def lock_operation_scope(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    capability: str = CANON_EDIT,
) -> OperationScope:
    """Lock and re-authorize; return the campaign's world and its own timeline.
    Raises the same non-disclosing errors as `lock_authoring_scope`."""
    if capability != CANON_EDIT:
        raise ValueError("operation commands currently authorize through canon.edit")
    scope = lock_authoring_scope(connection, campaign_id=campaign_id, actor_user_id=actor_user_id)
    timeline_id = connection.execute(
        text("SELECT timeline_id FROM campaign.campaigns WHERE campaign_id = :c"),
        {"c": campaign_id},
    ).scalar()
    assert isinstance(timeline_id, uuid.UUID)
    return OperationScope(
        world_id=scope.world_id, timeline_id=timeline_id, campaign_id=scope.campaign_id
    )
