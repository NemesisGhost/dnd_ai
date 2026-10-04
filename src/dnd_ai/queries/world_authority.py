"""World-authority resolution (docs/adr/0014-world-authoring-authority.md).

`resolve_world_authority` is the single read that answers "what may this user
do to this world", resolved from the database on every call. It is never
cached, never derived from campaign roles, `is_platform_administrator`, or
`created_by`, and never trusts an earlier lookup: a command re-resolves under
its own lock at mutation time.

Authority requires **all** of:

- an open (`ended_at IS NULL`) `security.world_memberships` row,
- whose membership status is `active` (and the status row itself is active),
- whose world role is active, and
- whose user account has an `active` lifecycle status.

A world with no memberships (an unclaimed legacy world), a nonexistent world,
and a user with no authority all resolve to `None` — indistinguishably, since
the caller turns each into the same non-disclosing 404.
"""

import uuid

from sqlalchemy import Connection, text

from dnd_ai.domain.world_authority import WorldAuthority


def resolve_world_authority(
    connection: Connection, *, user_id: uuid.UUID, world_id: uuid.UUID
) -> WorldAuthority | None:
    rows = connection.execute(
        text("""
            SELECT wr.code AS role_code, wls.code AS world_status
            FROM security.world_memberships wm
            JOIN security.membership_statuses ms
              ON ms.membership_status_id = wm.membership_status_id
            JOIN security.world_roles wr ON wr.world_role_id = wm.world_role_id
            JOIN security.users u ON u.user_id = wm.user_id
            JOIN core.lifecycle_statuses uls ON uls.lifecycle_status_id = u.lifecycle_status_id
            JOIN core.worlds w ON w.world_id = wm.world_id
            JOIN core.lifecycle_statuses wls ON wls.lifecycle_status_id = w.lifecycle_status_id
            WHERE wm.world_id = :world_id
              AND wm.user_id = :user_id
              AND wm.ended_at IS NULL
              AND ms.code = 'active' AND ms.is_active
              AND wr.is_active
              AND uls.code = 'active'
        """),
        {"world_id": world_id, "user_id": user_id},
    ).all()
    if not rows:
        return None
    return WorldAuthority(
        world_id=world_id,
        user_id=user_id,
        role_codes=frozenset(str(row.role_code) for row in rows),
        world_lifecycle_status=str(rows[0].world_status),
    )
