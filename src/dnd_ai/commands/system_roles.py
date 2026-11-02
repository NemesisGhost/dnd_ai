"""System-role assignment writes (docs/adr/0020-scoped-system-world-and-campaign-roles.md).

`insert_system_role_assignments` is the single low-level writer of
`security.user_system_roles`: it validates every code against the closed
vocabulary, is idempotent per (user, role) while an assignment is open, and writes
no audit row itself -- the callers that own a business operation (account
creation, the initial-admin bootstrap, the operator script) already audit their
own change. It checks no authority; callers authorize first.
"""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import Connection, text

from dnd_ai.domain.access import is_platform_administrator
from dnd_ai.domain.errors import SafeMessageError
from dnd_ai.domain.system_authority import SYSTEM_ROLE_ADMIN, SYSTEM_ROLE_CODES


def insert_system_role_assignments(
    connection: Connection,
    *,
    user_id: uuid.UUID,
    role_codes: Iterable[str],
    granted_by_user_id: uuid.UUID | None,
) -> list[str]:
    """Open an assignment of each code in `role_codes` for `user_id` unless one is
    already open. Returns the codes that were newly assigned."""
    assigned: list[str] = []
    for role_code in dict.fromkeys(role_codes):
        if role_code not in SYSTEM_ROLE_CODES:
            raise ValueError(f"unknown system role code {role_code!r}")
        created = connection.execute(
            text("""
                INSERT INTO security.user_system_roles (user_id, system_role_id, granted_by_user_id)
                SELECT CAST(:user_id AS uuid), sr.system_role_id, CAST(:granted_by AS uuid)
                FROM security.system_roles sr
                WHERE sr.code = :code AND sr.is_active
                ON CONFLICT (user_id, system_role_id) WHERE revoked_at IS NULL DO NOTHING
                RETURNING user_system_role_id
            """),
            {"user_id": user_id, "granted_by": granted_by_user_id, "code": role_code},
        ).first()
        if created is not None:
            assigned.append(role_code)
    return assigned


class AdminGrantDisabledError(SafeMessageError):
    """The in-app Administrator grant is off (`DND_AI_ALLOW_IN_APP_ADMIN_GRANT`,
    the default). Raised before anything is written; the operator script is the
    only way to grant `admin` on such a deployment."""

    safe_status_code = 403
    safe_error_code = "admin_grant_disabled"
    safe_message = (
        "Granting the Administrator role is done by the operator script on this deployment."
    )


@dataclass(frozen=True)
class SystemRoleChange:
    user_id: uuid.UUID
    role_code: str
    changed: bool
    user_system_role_id: uuid.UUID | None


def _require_administrator(connection: Connection, admin_user_id: uuid.UUID) -> None:
    # Imported here: `local_auth` imports this module's low-level writer.
    from .local_auth import NotPlatformAdministratorError

    if not is_platform_administrator(connection, user_id=admin_user_id):
        raise NotPlatformAdministratorError(f"user {admin_user_id} is not a platform administrator")


def _lock_target(connection: Connection, target_user_id: uuid.UUID) -> None:
    from .local_auth import LocalAccountNotFoundError

    found = connection.execute(
        text("SELECT 1 FROM security.users WHERE user_id = :u FOR UPDATE"),
        {"u": target_user_id},
    ).first()
    if found is None:
        raise LocalAccountNotFoundError(f"user {target_user_id} does not exist")


def assign_system_role(
    connection: Connection,
    *,
    admin_user_id: uuid.UUID,
    target_user_id: uuid.UUID,
    role_code: str,
    allow_in_app_admin_grant: bool,
) -> SystemRoleChange:
    """Open a system-role assignment for `target_user_id` (an Administrator acting
    on any account, active or not, so a GM can be prepared before activation).
    Idempotent: an assignment that is already open is a no-op (`changed=False`).
    Granting `admin` additionally needs the deployment setting. Touches no
    campaign or world row and creates no membership."""
    if role_code not in SYSTEM_ROLE_CODES:
        raise ValueError(f"unknown system role code {role_code!r}")
    _require_administrator(connection, admin_user_id)
    if role_code == SYSTEM_ROLE_ADMIN and not allow_in_app_admin_grant:
        raise AdminGrantDisabledError(f"in-app admin grant is disabled (user {admin_user_id})")
    _lock_target(connection, target_user_id)
    row = connection.execute(
        text("""
            INSERT INTO security.user_system_roles (user_id, system_role_id, granted_by_user_id)
            SELECT :target, sr.system_role_id, :admin
            FROM security.system_roles sr
            WHERE sr.code = :code AND sr.is_active
            ON CONFLICT (user_id, system_role_id) WHERE revoked_at IS NULL DO NOTHING
            RETURNING user_system_role_id
        """),
        {"target": target_user_id, "admin": admin_user_id, "code": role_code},
    ).first()
    return SystemRoleChange(
        user_id=target_user_id,
        role_code=role_code,
        changed=row is not None,
        user_system_role_id=row.user_system_role_id if row is not None else None,
    )


def revoke_system_role(
    connection: Connection,
    *,
    admin_user_id: uuid.UUID,
    target_user_id: uuid.UUID,
    role_code: str,
) -> SystemRoleChange:
    """Revoke the open assignment of `role_code` (history is kept). Idempotent.
    Revoking `admin` from an account that is currently an active administrator is
    refused when it would leave no active administrator; it takes the same
    advisory lock as account disablement, so concurrent revocations and
    disablements serialize. No other scope is touched: campaign roles and world
    roles stay exactly as they were (a revoked GM keeps every campaign role)."""
    from .local_auth import (
        _PLATFORM_ADMINISTRATOR_LIFECYCLE_LOCK_KEY,
        LastActivePlatformAdministratorError,
        _count_active_platform_administrators,
    )

    if role_code not in SYSTEM_ROLE_CODES:
        raise ValueError(f"unknown system role code {role_code!r}")
    _require_administrator(connection, admin_user_id)
    if role_code == SYSTEM_ROLE_ADMIN:
        connection.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
            {"key": _PLATFORM_ADMINISTRATOR_LIFECYCLE_LOCK_KEY},
        )
    _lock_target(connection, target_user_id)
    if (
        role_code == SYSTEM_ROLE_ADMIN
        and is_platform_administrator(connection, user_id=target_user_id)
        and _count_active_platform_administrators(connection) <= 1
    ):
        raise LastActivePlatformAdministratorError(
            f"revoking admin from user {target_user_id} would leave no active administrator"
        )
    row = connection.execute(
        text("""
            UPDATE security.user_system_roles usr
            SET revoked_at = now(), revoked_by_user_id = :admin
            FROM security.system_roles sr
            WHERE usr.system_role_id = sr.system_role_id
              AND usr.user_id = :target AND sr.code = :code AND usr.revoked_at IS NULL
            RETURNING usr.user_system_role_id
        """),
        {"target": target_user_id, "admin": admin_user_id, "code": role_code},
    ).first()
    return SystemRoleChange(
        user_id=target_user_id,
        role_code=role_code,
        changed=row is not None,
        user_system_role_id=row.user_system_role_id if row is not None else None,
    )
