"""System-authority resolution (docs/adr/0020-scoped-system-world-and-campaign-roles.md).

`resolve_system_roles` answers "which system roles does this user hold right now":
the user's unrevoked `security.user_system_roles` rows whose role is active,
provided the account itself is `active`. Resolved from the database on every call,
never cached. An inactive, unknown or role-less account resolves to the empty set,
and therefore to no system capability.

System authority is independent of world and campaign authority: nothing here reads
a campaign membership or a world role, and nothing here is read by
`dnd_ai.domain.access.resolve_access_context`.
"""

import uuid

from sqlalchemy import Connection, text

from dnd_ai.domain.system_authority import capabilities_for_system_roles


def resolve_system_roles(connection: Connection, *, user_id: uuid.UUID) -> frozenset[str]:
    rows = connection.execute(
        text("""
            SELECT sr.code
            FROM security.user_system_roles usr
            JOIN security.system_roles sr ON sr.system_role_id = usr.system_role_id
            JOIN security.users u ON u.user_id = usr.user_id
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = u.lifecycle_status_id
            WHERE usr.user_id = :user_id
              AND usr.revoked_at IS NULL
              AND sr.is_active
              AND ls.code = 'active'
        """),
        {"user_id": user_id},
    ).all()
    return frozenset(str(row.code) for row in rows)


def resolve_system_capabilities(
    connection: Connection, *, user_id: uuid.UUID, allow_in_app_admin_grant: bool = False
) -> frozenset[str]:
    return capabilities_for_system_roles(
        resolve_system_roles(connection, user_id=user_id),
        allow_in_app_admin_grant=allow_in_app_admin_grant,
    )


def has_system_capability(
    connection: Connection, *, user_id: uuid.UUID, capability_code: str
) -> bool:
    return capability_code in resolve_system_capabilities(connection, user_id=user_id)
