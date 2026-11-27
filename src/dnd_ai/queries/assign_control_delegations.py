"""The assign-control delegations of one campaign (P15-C11-S02-T02, `GET .../assign-control-delegations`).

One read for the live built-in owners and GMs (the only holders who can grant or revoke a delegation); the route judges
that authority first. It lists every delegation of the campaign, live and closed, newest first, at most 200 with
`truncated`. Whether a live row is **in force** is judged in the statement itself, at the transaction's instant: it is
unrevoked, its bound built-in `assistant_gm` assignment is live (unrevoked, unexpired, the role active), and the grantee
is an open, active member with an active account. A live row whose bound assignment is not live reads "not in force:
assistant GM role ended". Writes nothing and takes no lock.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Connection, text

HISTORY_LIMIT = 200

STATUS_IN_FORCE = "in_force"
STATUS_ROLE_ENDED = "role_ended"
STATUS_REVOKED = "revoked"
STATUS_CLOSED_ROLE_LAPSED = "closed_role_lapsed"

STATUS_TEXT = {
    STATUS_IN_FORCE: "in force",
    STATUS_ROLE_ENDED: "not in force: assistant GM role ended",
    STATUS_REVOKED: "revoked",
    STATUS_CLOSED_ROLE_LAPSED: "closed: assistant GM role ended",
}

_SQL = text("""
    SELECT d.character_assign_control_delegation_id AS delegation_id,
           d.grantee_campaign_membership_id,
           gu.display_name AS display_name,
           d.reason,
           d.granted_at,
           bu.display_name AS granted_by,
           d.revoked_at,
           ru.display_name AS revoked_by,
           d.revocation_reason,
           d.end_reason,
           (d.revoked_at IS NULL AND EXISTS (
               SELECT 1
               FROM security.membership_roles mr
               JOIN security.roles r ON r.role_id = mr.role_id
               JOIN security.campaign_memberships cm ON cm.campaign_membership_id = mr.campaign_membership_id
               JOIN security.membership_statuses ms ON ms.membership_status_id = cm.membership_status_id
               JOIN security.users u ON u.user_id = cm.user_id
               JOIN core.lifecycle_statuses uls ON uls.lifecycle_status_id = u.lifecycle_status_id
               WHERE mr.membership_role_id = d.assistant_gm_membership_role_id
                 AND mr.campaign_membership_id = d.grantee_campaign_membership_id
                 AND cm.campaign_id = d.campaign_id
                 AND r.campaign_id IS NULL AND r.code = 'assistant_gm' AND r.is_active
                 AND mr.revoked_at IS NULL
                 AND (mr.expires_at IS NULL OR mr.expires_at > now())
                 AND cm.ended_at IS NULL AND ms.code = 'active' AND ms.is_active
                 AND uls.code = 'active'
           )) AS in_force
    FROM security.character_assign_control_delegations d
    JOIN security.campaign_memberships gm ON gm.campaign_membership_id = d.grantee_campaign_membership_id
    JOIN security.users gu ON gu.user_id = gm.user_id
    LEFT JOIN security.campaign_memberships bm ON bm.campaign_membership_id = d.granted_by_membership_id
    LEFT JOIN security.users bu ON bu.user_id = bm.user_id
    LEFT JOIN security.campaign_memberships rm ON rm.campaign_membership_id = d.revoked_by_membership_id
    LEFT JOIN security.users ru ON ru.user_id = rm.user_id
    WHERE d.campaign_id = :campaign_id
    ORDER BY d.granted_at DESC, d.character_assign_control_delegation_id DESC
    LIMIT :limit
""")


@dataclass(frozen=True)
class AssignControlDelegationRow:
    delegation_id: uuid.UUID
    grantee_campaign_membership_id: uuid.UUID
    display_name: str
    status: str
    status_text: str
    in_force: bool
    reason: str
    granted_at: datetime
    granted_by: str | None
    revoked_at: datetime | None
    revoked_by: str | None
    revocation_reason: str | None
    end_reason: str | None


@dataclass(frozen=True)
class AssignControlDelegations:
    delegations: list[AssignControlDelegationRow]
    truncated: bool


def _status(end_reason: str | None, revoked: bool, in_force: bool) -> str:
    if not revoked:
        return STATUS_IN_FORCE if in_force else STATUS_ROLE_ENDED
    return STATUS_REVOKED if end_reason == "revoked" else STATUS_CLOSED_ROLE_LAPSED


def get_assign_control_delegations(
    connection: Connection, *, campaign_id: uuid.UUID
) -> AssignControlDelegations:
    rows = list(
        connection.execute(
            _SQL, {"campaign_id": campaign_id, "limit": HISTORY_LIMIT + 1}
        ).mappings()
    )
    truncated = len(rows) > HISTORY_LIMIT
    result: list[AssignControlDelegationRow] = []
    for row in rows[:HISTORY_LIMIT]:
        status = _status(row["end_reason"], row["revoked_at"] is not None, bool(row["in_force"]))
        result.append(
            AssignControlDelegationRow(
                delegation_id=row["delegation_id"],
                grantee_campaign_membership_id=row["grantee_campaign_membership_id"],
                display_name=row["display_name"],
                status=status,
                status_text=STATUS_TEXT[status],
                in_force=status == STATUS_IN_FORCE,
                reason=row["reason"],
                granted_at=row["granted_at"],
                granted_by=row["granted_by"],
                revoked_at=row["revoked_at"],
                revoked_by=row["revoked_by"],
                revocation_reason=row["revocation_reason"],
                end_reason=row["end_reason"],
            )
        )
    return AssignControlDelegations(delegations=result, truncated=truncated)
