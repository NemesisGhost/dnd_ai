"""Party membership read model (Phase 15 checkpoint 15.2C-2).

Rows of the campaign's own timeline only: membership is timeline state, so a branch
shows none until something is written there. For `canon.edit` holders (the route
enforces it); members are named by their character entity.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, text

from .campaign_clock import world_time_point


@dataclass(frozen=True)
class MemberRow:
    party_membership_id: uuid.UUID
    character_id: uuid.UUID
    character_name: str
    joined_at: str
    left_at: str | None
    joined_reason: str | None
    left_reason: str | None
    is_current: bool


def list_party_members(
    connection: Connection, *, timeline_id: uuid.UUID, party_id: uuid.UUID
) -> list[MemberRow]:
    """Open memberships first (by name), then ended ones, latest end first."""
    rows = connection.execute(
        text("""
            SELECT pm.party_membership_id, pm.member_entity_id, e.canonical_name,
                   pm.effective_from_world_time_id, pm.effective_to_world_time_id,
                   pm.joined_reason, pm.left_reason, lower(pm.effective_period) AS start_key,
                   upper(pm.effective_period) AS end_key
            FROM campaign.party_memberships pm
            JOIN core.entities e ON e.entity_id = pm.member_entity_id
            WHERE pm.timeline_id = :t AND pm.party_id = :p
            ORDER BY (pm.effective_to_world_time_id IS NOT NULL),
                     lower(e.canonical_name), pm.effective_period DESC, pm.party_membership_id
        """),
        {"t": timeline_id, "p": party_id},
    ).all()
    result: list[MemberRow] = []
    for row in rows:
        _, joined = world_time_point(connection, row.effective_from_world_time_id)
        left = None
        if row.effective_to_world_time_id is not None:
            _, left = world_time_point(connection, row.effective_to_world_time_id)
        result.append(
            MemberRow(
                party_membership_id=row.party_membership_id,
                character_id=row.member_entity_id,
                character_name=str(row.canonical_name),
                joined_at=joined,
                left_at=left,
                joined_reason=row.joined_reason,
                left_reason=row.left_reason,
                is_current=row.effective_to_world_time_id is None,
            )
        )
    return result
