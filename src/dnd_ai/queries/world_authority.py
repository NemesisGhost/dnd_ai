"""World-authority resolution (docs/adr/0014-world-authoring-authority.md).

`resolve_world_authority` is the single read that answers "what may this user
do to this world", resolved from the database on every call. It is never
cached, never derived from campaign roles or
`created_by`, and never trusts an earlier lookup: a command re-resolves under
its own lock at mutation time.

Authority is the union of the caller's open, active world roles and an open
world-use grant, all on an `active` account; the world-management capabilities
are then gated on the holder's current system `world.administer` capability
(D11). A world with no memberships (an unclaimed legacy world), a nonexistent
world, and a user with no authority all resolve to `None` — indistinguishably,
since the caller turns each into the same non-disclosing 404.

`may_create_worlds` is the separate, global (not per-world) creation policy
(docs/adr/0020-scoped-system-world-and-campaign-roles.md, superseding ADR 0018). It is the only definition of
who holds `world.create`: `create_world` enforces it inside its own
transaction and the session bootstrap reports it, so the two never disagree.
"""

import uuid

from sqlalchemy import Connection, text

from dnd_ai.domain.system_authority import WORLD_ADMINISTER, WORLD_CREATE
from dnd_ai.domain.world_authority import WorldAuthority
from dnd_ai.queries.system_authority import has_system_capability


def resolve_world_authority(
    connection: Connection, *, user_id: uuid.UUID, world_id: uuid.UUID
) -> WorldAuthority | None:
    """The caller's resolved authority over `world_id`, or `None` when they hold
    none (an unknown world, an unclaimed legacy world, an inactive account and a
    user with neither a world role nor a use grant are indistinguishable).

    Roles come from open, active `security.world_memberships` rows (any number);
    the use grant from an open `security.world_use_grants` row. The world-
    management capabilities are then gated on the holder's *current* system
    `world.administer` capability (decision D11), re-read on every call."""
    world_row = connection.execute(
        text("""
            SELECT wls.code AS world_status
            FROM core.worlds w
            JOIN core.lifecycle_statuses wls ON wls.lifecycle_status_id = w.lifecycle_status_id
            WHERE w.world_id = :world_id
        """),
        {"world_id": world_id},
    ).one_or_none()
    if world_row is None:
        return None
    role_rows = connection.execute(
        text("""
            SELECT wr.code AS role_code
            FROM security.world_memberships wm
            JOIN security.membership_statuses ms
              ON ms.membership_status_id = wm.membership_status_id
            JOIN security.world_roles wr ON wr.world_role_id = wm.world_role_id
            JOIN security.users u ON u.user_id = wm.user_id
            JOIN core.lifecycle_statuses uls ON uls.lifecycle_status_id = u.lifecycle_status_id
            WHERE wm.world_id = :world_id
              AND wm.user_id = :user_id
              AND wm.ended_at IS NULL
              AND ms.code = 'active' AND ms.is_active
              AND wr.is_active
              AND uls.code = 'active'
        """),
        {"world_id": world_id, "user_id": user_id},
    ).all()
    has_use_grant = bool(
        connection.execute(
            text("""
                SELECT EXISTS (
                    SELECT 1
                    FROM security.world_use_grants g
                    JOIN security.users u ON u.user_id = g.user_id
                    JOIN core.lifecycle_statuses uls
                      ON uls.lifecycle_status_id = u.lifecycle_status_id
                    WHERE g.world_id = :world_id AND g.user_id = :user_id
                      AND g.revoked_at IS NULL AND uls.code = 'active'
                )
            """),
            {"world_id": world_id, "user_id": user_id},
        ).scalar()
    )
    if not role_rows and not has_use_grant:
        return None
    return WorldAuthority(
        world_id=world_id,
        user_id=user_id,
        role_codes=frozenset(str(row.role_code) for row in role_rows),
        world_lifecycle_status=str(world_row.world_status),
        may_administer=has_system_capability(
            connection, user_id=user_id, capability_code=WORLD_ADMINISTER
        ),
        has_use_grant=has_use_grant,
    )


def may_create_worlds(connection: Connection, *, user_id: uuid.UUID) -> bool:
    """The world-creation policy: the user holds the system `world.create`
    capability, i.e. an unrevoked system `gm` assignment on an active account
    (docs/adr/0020-scoped-system-world-and-campaign-roles.md, which supersedes
    ADR 0018). Deny by default -- an unknown user, an inactive account, a bare
    platform administrator, and every campaign or world role (including the
    built-in campaign `gm`) all resolve to False. Resolved from the database on
    every call and never cached.

    This decides *principal eligibility only*. The caller is responsible for
    having already established a human principal: Foundry device and machine
    principals never reach it (`dnd_ai.api.auth.require_human_user_id`)."""
    return has_system_capability(connection, user_id=user_id, capability_code=WORLD_CREATE)
