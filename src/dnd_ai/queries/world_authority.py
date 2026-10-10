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

`may_create_worlds` is the separate, global (not per-world) creation policy
(docs/adr/0018-world-creation-eligibility.md). It is the only definition of
who holds `world.create`: `create_world` enforces it inside its own
transaction and the session bootstrap reports it, so the two never disagree.
"""

import uuid

from sqlalchemy import Connection, text

from dnd_ai.domain.access import is_platform_administrator
from dnd_ai.domain.world_authority import WORLD_CREATOR_SYSTEM_ROLE_CODE, WorldAuthority


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


def holds_effective_system_gm_role(connection: Connection, *, user_id: uuid.UUID) -> bool:
    """True iff `user_id` currently holds the built-in `gm` system-template
    role in at least one campaign. Every link must be current: an active user,
    an open (`ended_at IS NULL`) membership in an `active` membership status, an
    `active` campaign, an unrevoked and unexpired role assignment, and an active
    role row whose code is `gm` **and** whose `campaign_id IS NULL`. A
    campaign-scoped custom role that happens to be named `gm` is a different
    role and never qualifies. Mirrors the membership and role predicates of
    `dnd_ai.domain.access.resolve_access_context`."""
    value = connection.execute(
        text("""
            SELECT EXISTS (
                SELECT 1
                FROM security.users u
                JOIN core.lifecycle_statuses uls
                  ON uls.lifecycle_status_id = u.lifecycle_status_id
                JOIN security.campaign_memberships cm ON cm.user_id = u.user_id
                JOIN security.membership_statuses ms
                  ON ms.membership_status_id = cm.membership_status_id
                JOIN campaign.campaigns c ON c.campaign_id = cm.campaign_id
                JOIN core.lifecycle_statuses cls
                  ON cls.lifecycle_status_id = c.lifecycle_status_id
                JOIN security.membership_roles mr
                  ON mr.campaign_membership_id = cm.campaign_membership_id
                JOIN security.roles r ON r.role_id = mr.role_id
                WHERE u.user_id = :user_id
                  AND uls.code = 'active'
                  AND cm.ended_at IS NULL
                  AND ms.code = 'active' AND ms.is_active
                  AND cls.code = 'active'
                  AND mr.revoked_at IS NULL
                  AND (mr.expires_at IS NULL OR mr.expires_at > now())
                  AND r.is_active
                  AND r.campaign_id IS NULL
                  AND r.code = :role_code
            )
        """),
        {"user_id": user_id, "role_code": WORLD_CREATOR_SYSTEM_ROLE_CODE},
    ).scalar()
    return bool(value)


def may_create_worlds(connection: Connection, *, user_id: uuid.UUID) -> bool:
    """The world-creation policy: an active platform administrator, or an
    active user holding an effective built-in `gm` assignment. Deny by
    default — an unknown user, an inactive account, and every other role
    (`campaign_owner`, `assistant_gm`, `player`, `observer`, a world role, a
    custom campaign-scoped `gm`) all resolve to False. Resolved from the
    database on every call and never cached.

    This decides *principal eligibility only*. The caller is responsible for
    having already established a human principal: Foundry device and machine
    principals never reach it (`dnd_ai.api.auth.require_human_user_id`)."""
    return is_platform_administrator(connection, user_id=user_id) or holds_effective_system_gm_role(
        connection, user_id=user_id
    )
