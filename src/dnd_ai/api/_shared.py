"""Helpers shared across command routers — the API-layer twin of
`dnd_ai.commands._shared`, promoted here once a second router needed the
identical lookup, mirroring that module's own promote-on-second-use
history (see its docstring)."""

import uuid

from sqlalchemy import Connection, text


def timeline_world_id(connection: Connection, timeline_id: uuid.UUID) -> uuid.UUID:
    """The campaign's own pinned timeline's world — the same inline lookup
    `dnd_ai.commands.encounters` already performs at each of its own
    campaign-scoped entry points, used here so a command's own `world_id`
    argument is always server-resolved from `access.timeline_id`, never
    caller-supplied. First used by `dnd_ai.api.events`, promoted here once
    `dnd_ai.api.integration` needed the identical lookup."""
    value = connection.execute(
        text("SELECT world_id FROM campaign.timelines WHERE timeline_id = :t"),
        {"t": timeline_id},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value
