"""Platform-account directory (Phase 13E checkpoint 9; owner decision D-2,
`PHASE13E_REMAINING_IMPLEMENTATION_PLAN.md` §14).

`list_platform_accounts` is a real substring search over display name and
login name, deliberately narrower than nothing (§3d's exact-match `dnd_ai.
queries.access_overview.find_eligible_campaign_account` posture is
unchanged and continues to govern campaign access managers) but wider than
that campaign-scoped precedent: a platform administrator can already
disable any account and reset any password, so this directory adds no
meaningful privilege that role does not already have, and without it the
admin page would need a UUID the portal has no way to obtain.

Authorization lives **inside this query**, not only at the API layer
(mirroring `dnd_ai.commands.local_auth._create_local_account_impl`'s own
"checked here, inside the caller's own transaction" reasoning) — a direct
command/script caller is checked too, not only a route. `requesting_user_
id` failing the check raises `NotPlatformAdministratorError`, the fixed
non-disclosing 404 every other account-management operation in this
codebase already uses; a campaign owner holding `access.manage` gets the
identical response.

Never returns `email`, a password hash, or any token hash — only
`display_name` and a resolved `login_name`. `login_name` resolves from
`security.external_identities.subject` (issuer `LOCAL_AUTH_ISSUER`,
`revoked_at IS NULL`) for an activated account, falling back to the
newest unconsumed `security.user_activation_tokens.login_name` for a
pending one — until activation is consumed, that token row is the only
place a chosen login name lives (`dnd_ai.commands.local_auth` module
docstring).

Cursor decode/encode is the API layer's job, not this module's — the same
split `dnd_ai.queries.world_explorer.list_world_entities`/`dnd_ai.api.
world_explorer` already establish: this function takes already-decoded
`after_name`/`after_user_id` and fetches `limit + 1` rows under its own
deterministic `ORDER BY`; the caller (`dnd_ai.api.local_auth`) applies
`dnd_ai.api.pagination.build_page` to trim and mint the next cursor.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Connection, text

from dnd_ai.commands.local_auth import NotPlatformAdministratorError
from dnd_ai.domain.access import LOCAL_AUTH_ISSUER, is_platform_administrator

# The keyset name embedded in every cursor this endpoint mints
# (dnd_ai.api.pagination.encode_cursor/decode_typed_cursor) — exported so
# the API layer does not have to duplicate this literal.
ACCOUNT_LIST_KEYSET = "platform_accounts"


@dataclass(frozen=True)
class PlatformAccountView:
    user_id: uuid.UUID
    display_name: str
    login_name: str | None
    lifecycle_status_code: str
    is_platform_administrator: bool
    system_roles: tuple[str, ...]
    has_local_credential: bool
    has_outstanding_activation: bool
    last_login_at: datetime | None
    active_session_count: int


def list_platform_accounts(
    connection: Connection,
    *,
    requesting_user_id: uuid.UUID,
    query: str | None,
    status_code: str | None,
    system_role_code: str | None = None,
    limit: int,
    after_name: str | None,
    after_user_id: uuid.UUID | None,
) -> tuple[PlatformAccountView, ...]:
    """Keyset-paginated on `(lower(display_name), user_id)`. `query`, when
    given, is matched as a case-insensitive substring against
    `display_name` and the resolved `login_name` (active or pending).
    `status_code`, when given, filters to that exact `core.
    lifecycle_statuses.code`. Fetches `limit + 1` rows; the caller decides
    whether a next page exists from whether that many came back
    (`dnd_ai.api.pagination.build_page`'s own "over-fetch by one"
    convention) — this function never returns a total count."""
    if not is_platform_administrator(connection, user_id=requesting_user_id):
        raise NotPlatformAdministratorError(
            f"user {requesting_user_id} is not a platform administrator"
        )

    like_pattern = f"%{query}%" if query else None

    rows = (
        connection.execute(
            text("""
                SELECT
                    u.user_id, u.display_name, u.last_login_at,
                    EXISTS (
                        SELECT 1
                        FROM security.user_system_roles usr
                        JOIN security.system_roles sr ON sr.system_role_id = usr.system_role_id
                        WHERE usr.user_id = u.user_id AND usr.revoked_at IS NULL
                          AND sr.code = 'admin' AND sr.is_active
                    ) AS is_platform_administrator,
                    ARRAY(
                        SELECT sr.code
                        FROM security.user_system_roles usr
                        JOIN security.system_roles sr ON sr.system_role_id = usr.system_role_id
                        WHERE usr.user_id = u.user_id AND usr.revoked_at IS NULL
                        ORDER BY sr.sort_order
                    ) AS system_roles,
                    cls.code AS lifecycle_status_code,
                    local_ei.subject AS active_login_name,
                    pending_token.login_name AS pending_login_name,
                    EXISTS (
                        SELECT 1 FROM security.local_credentials lc WHERE lc.user_id = u.user_id
                    ) AS has_local_credential,
                    EXISTS (
                        SELECT 1 FROM security.user_activation_tokens uat
                        WHERE uat.user_id = u.user_id AND uat.consumed_at IS NULL
                          AND uat.expires_at > now()
                    ) AS has_outstanding_activation,
                    (
                        SELECT count(*) FROM security.browser_sessions bs
                        WHERE bs.user_id = u.user_id AND bs.revoked_at IS NULL
                          AND bs.idle_expires_at > now() AND bs.absolute_expires_at > now()
                    ) AS active_session_count
                FROM security.users u
                JOIN core.lifecycle_statuses cls ON cls.lifecycle_status_id = u.lifecycle_status_id
                LEFT JOIN security.external_identities local_ei
                       ON local_ei.user_id = u.user_id AND local_ei.issuer = :issuer
                          AND local_ei.revoked_at IS NULL
                LEFT JOIN LATERAL (
                    SELECT uat.login_name
                    FROM security.user_activation_tokens uat
                    WHERE uat.user_id = u.user_id AND uat.consumed_at IS NULL
                    ORDER BY uat.created_at DESC
                    LIMIT 1
                ) pending_token ON true
                WHERE (
                        CAST(:like_pattern AS text) IS NULL
                        OR u.display_name ILIKE CAST(:like_pattern AS text) ESCAPE '\\'
                        OR local_ei.subject ILIKE CAST(:like_pattern AS text) ESCAPE '\\'
                        OR pending_token.login_name ILIKE CAST(:like_pattern AS text) ESCAPE '\\'
                      )
                  AND (
                        CAST(:status_code AS text) IS NULL OR cls.code = CAST(:status_code AS text)
                      )
                  AND (
                        CAST(:system_role_code AS text) IS NULL OR EXISTS (
                            SELECT 1
                            FROM security.user_system_roles fusr
                            JOIN security.system_roles fsr
                              ON fsr.system_role_id = fusr.system_role_id
                            WHERE fusr.user_id = u.user_id AND fusr.revoked_at IS NULL
                              AND fsr.code = CAST(:system_role_code AS text)
                        )
                      )
                  AND (
                        NOT CAST(:has_cursor AS boolean)
                        OR (lower(u.display_name), u.user_id)
                           > (CAST(:after_name AS text), CAST(:after_user_id AS uuid))
                      )
                ORDER BY lower(u.display_name), u.user_id
                LIMIT :limit_plus_one
            """),
            {
                "issuer": LOCAL_AUTH_ISSUER,
                "like_pattern": like_pattern,
                "status_code": status_code,
                "system_role_code": system_role_code,
                "has_cursor": after_name is not None,
                "after_name": after_name,
                "after_user_id": after_user_id,
                "limit_plus_one": limit + 1,
            },
        )
        .mappings()
        .all()
    )

    return tuple(
        PlatformAccountView(
            user_id=row["user_id"],
            display_name=str(row["display_name"]),
            login_name=row["active_login_name"] or row["pending_login_name"],
            lifecycle_status_code=str(row["lifecycle_status_code"]),
            is_platform_administrator=bool(row["is_platform_administrator"]),
            system_roles=tuple(str(code) for code in row["system_roles"]),
            has_local_credential=bool(row["has_local_credential"]),
            has_outstanding_activation=bool(row["has_outstanding_activation"]),
            last_login_at=row["last_login_at"],
            active_session_count=int(row["active_session_count"]),
        )
        for row in rows
    )


__all__ = ["ACCOUNT_LIST_KEYSET", "PlatformAccountView", "list_platform_accounts"]
