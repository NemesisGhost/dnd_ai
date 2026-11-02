"""Reads behind world sharing (docs/adr/0020-scoped-system-world-and-campaign-roles.md).

`list_world_access` is what the Sharing page shows a world Owner: every open role
assignment and every open use grant, with display names and who granted them.
`find_active_account` is the non-disclosing, exact-login-name lookup the sharing
commands use to turn a typed login name into an account: an unknown name, a
disabled account and an OIDC-only account all resolve to `None`, so the lookup can
never be used to enumerate accounts.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Connection, text

from dnd_ai.commands.local_auth import normalize_login_name
from dnd_ai.domain.access import LOCAL_AUTH_ISSUER


@dataclass(frozen=True)
class ActiveAccount:
    user_id: uuid.UUID
    display_name: str


@dataclass(frozen=True)
class WorldRoleAssignmentView:
    world_membership_id: uuid.UUID
    user_id: uuid.UUID
    display_name: str
    role_code: str
    role_display_name: str
    granted_at: datetime
    granted_by_display_name: str | None
    account_active: bool


@dataclass(frozen=True)
class WorldUseGrantView:
    world_use_grant_id: uuid.UUID
    user_id: uuid.UUID
    display_name: str
    granted_at: datetime
    granted_by_display_name: str | None
    account_active: bool


@dataclass(frozen=True)
class WorldAccessView:
    assignments: list[WorldRoleAssignmentView]
    use_grants: list[WorldUseGrantView]


def find_active_account(connection: Connection, *, login_name: str) -> ActiveAccount | None:
    """The one active local account named `login_name` (exact, normalized), or
    `None`."""
    row = connection.execute(
        text("""
            SELECT u.user_id, u.display_name
            FROM security.external_identities ei
            JOIN security.users u ON u.user_id = ei.user_id
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = u.lifecycle_status_id
            WHERE ei.issuer = :issuer
              AND ei.subject = :subject
              AND ei.revoked_at IS NULL
              AND ls.code = 'active'
        """),
        {"issuer": LOCAL_AUTH_ISSUER, "subject": normalize_login_name(login_name)},
    ).one_or_none()
    if row is None:
        return None
    return ActiveAccount(user_id=row.user_id, display_name=str(row.display_name))


def list_world_access(connection: Connection, *, world_id: uuid.UUID) -> WorldAccessView:
    assignments = connection.execute(
        text("""
            SELECT wm.world_membership_id, wm.user_id, u.display_name, wr.code AS role_code,
                   wr.display_name AS role_display_name, wm.joined_at,
                   gb.display_name AS granted_by_display_name,
                   (uls.code = 'active') AS account_active
            FROM security.world_memberships wm
            JOIN security.membership_statuses ms
              ON ms.membership_status_id = wm.membership_status_id
            JOIN security.world_roles wr ON wr.world_role_id = wm.world_role_id
            JOIN security.users u ON u.user_id = wm.user_id
            JOIN core.lifecycle_statuses uls ON uls.lifecycle_status_id = u.lifecycle_status_id
            LEFT JOIN security.users gb ON gb.user_id = wm.granted_by_user_id
            WHERE wm.world_id = :w AND wm.ended_at IS NULL AND ms.code = 'active' AND ms.is_active
            ORDER BY wr.sort_order, lower(u.display_name), wm.world_membership_id
        """),
        {"w": world_id},
    ).all()
    grants = connection.execute(
        text("""
            SELECT g.world_use_grant_id, g.user_id, u.display_name, g.granted_at,
                   gb.display_name AS granted_by_display_name,
                   (uls.code = 'active') AS account_active
            FROM security.world_use_grants g
            JOIN security.users u ON u.user_id = g.user_id
            JOIN core.lifecycle_statuses uls ON uls.lifecycle_status_id = u.lifecycle_status_id
            LEFT JOIN security.users gb ON gb.user_id = g.granted_by_user_id
            WHERE g.world_id = :w AND g.revoked_at IS NULL
            ORDER BY lower(u.display_name), g.world_use_grant_id
        """),
        {"w": world_id},
    ).all()
    return WorldAccessView(
        assignments=[
            WorldRoleAssignmentView(
                world_membership_id=r.world_membership_id,
                user_id=r.user_id,
                display_name=str(r.display_name),
                role_code=str(r.role_code),
                role_display_name=str(r.role_display_name),
                granted_at=r.joined_at,
                granted_by_display_name=r.granted_by_display_name,
                account_active=bool(r.account_active),
            )
            for r in assignments
        ],
        use_grants=[
            WorldUseGrantView(
                world_use_grant_id=r.world_use_grant_id,
                user_id=r.user_id,
                display_name=str(r.display_name),
                granted_at=r.granted_at,
                granted_by_display_name=r.granted_by_display_name,
                account_active=bool(r.account_active),
            )
            for r in grants
        ],
    )
