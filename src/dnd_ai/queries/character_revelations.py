"""The GM list of a character's revelations (P03-A A3a).

Readable by the D8 read rule (effective character-scoped `canon.edit`, or current reveal
authority; a whole-character deny removes the character): it is the same audience as the profile
draft. The list never appears in any audience response. Names are the membership holder's display
name and the group's name, which GMs already see in the session roster and the access overview.
"""

import uuid
from typing import Any

from sqlalchemy import Connection, text

from dnd_ai.domain.access import AccessContext
from dnd_ai.domain.public_profiles import AUDIENCE_CAMPAIGN_CURRENT

from .character_public_profile import _readable


def list_character_revelations(
    connection: Connection, *, access: AccessContext, character_id: uuid.UUID
) -> dict[str, Any] | None:
    """Live and ended revelations, newest first, or `None` (404) when the caller may not read this
    character's profile."""
    if _readable(connection, access, character_id) is None:
        return None
    rows = connection.execute(
        text("""
            SELECT r.character_revelation_id, k.code AS audience_kind,
                   r.target_campaign_membership_id, tu.display_name AS target_member_name,
                   r.target_access_group_id, g.name AS target_group_name,
                   r.created_by_membership_id, cu.display_name AS created_by_name,
                   r.authority_source_code, r.created_at,
                   r.ended_at, r.end_reason, r.ended_by_membership_id
            FROM security.character_revelations r
            JOIN security.revelation_audience_kinds k
                ON k.revelation_audience_kind_id = r.revelation_audience_kind_id
            JOIN security.campaign_memberships cm ON cm.campaign_membership_id = r.created_by_membership_id
            JOIN security.users cu ON cu.user_id = cm.user_id
            LEFT JOIN security.campaign_memberships tm
                ON tm.campaign_membership_id = r.target_campaign_membership_id
            LEFT JOIN security.users tu ON tu.user_id = tm.user_id
            LEFT JOIN security.access_groups g ON g.access_group_id = r.target_access_group_id
            WHERE r.campaign_id = :campaign AND r.character_id = :character
            ORDER BY r.created_at DESC, r.character_revelation_id
        """),
        {"campaign": access.campaign_id, "character": character_id},
    ).all()
    snapshots: dict[uuid.UUID, list[Any]] = {}
    ids = [
        row.character_revelation_id
        for row in rows
        if row.audience_kind == AUDIENCE_CAMPAIGN_CURRENT
    ]
    if ids:
        for member in connection.execute(
            text("""
                SELECT m.character_revelation_id, m.campaign_membership_id, u.display_name,
                       m.added_at, m.removed_at, m.removal_reason
                FROM security.character_revelation_members m
                JOIN security.campaign_memberships cm
                    ON cm.campaign_membership_id = m.campaign_membership_id
                JOIN security.users u ON u.user_id = cm.user_id
                WHERE m.character_revelation_id = ANY(:ids)
                ORDER BY m.added_at, m.character_revelation_member_id
            """),
            {"ids": ids},
        ):
            snapshots.setdefault(member.character_revelation_id, []).append(member)

    entries: list[dict[str, Any]] = []
    for row in rows:
        entry: dict[str, Any] = {
            "character_revelation_id": str(row.character_revelation_id),
            "audience_kind": row.audience_kind,
            "target_campaign_membership_id": _text(row.target_campaign_membership_id),
            "target_member_name": row.target_member_name,
            "target_access_group_id": _text(row.target_access_group_id),
            "target_access_group_name": row.target_group_name,
            "created_by_membership_id": str(row.created_by_membership_id),
            "created_by_name": row.created_by_name,
            "authority_source": row.authority_source_code,
            "created_at": row.created_at.isoformat(),
            "live": row.ended_at is None,
            "ended_at": row.ended_at.isoformat() if row.ended_at else None,
            "end_reason": row.end_reason,
        }
        if row.audience_kind == AUDIENCE_CAMPAIGN_CURRENT:
            members = snapshots.get(row.character_revelation_id, [])
            entry["audience_size"] = sum(1 for m in members if m.removed_at is None)
            entry["snapshot_members"] = [
                {
                    "campaign_membership_id": str(m.campaign_membership_id),
                    "display_name": m.display_name,
                    "added_at": m.added_at.isoformat(),
                    "removed_at": m.removed_at.isoformat() if m.removed_at else None,
                    "removal_reason": m.removal_reason,
                }
                for m in members
            ]
        entries.append(entry)
    return {"character_id": str(character_id), "revelations": entries}


def _text(value: uuid.UUID | None) -> str | None:
    return None if value is None else str(value)
