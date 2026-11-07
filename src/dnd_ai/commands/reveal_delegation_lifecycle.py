"""Closing reveal delegations from the role and membership commands (P03-A A1).

A delegation (`security.character_reveal_delegations`) is bound to the grantee's specific built-in
`gm` assignment. The membership and role commands close the rows their change makes unusable,
inside their own transaction and with an `end_reason`, rather than through a trigger chain
(docs/DATABASE_CONVENTIONS.md section 20.4). This module is deliberately free of imports from
`memberships`, which calls it.

Lock order. Every caller already holds the rows it changes (the role row for a revoke or change,
the member's role rows and then the membership row for ending a membership), so the delegation row
is the next lock after them, ahead of the campaign row that the retention trigger takes at commit.
`grant_character_reveal_delegation` takes the same sequence (design section 3).
"""

import uuid
from datetime import datetime

from sqlalchemy import Connection, text

END_REASON_REVOKED_BY_OWNER = "revoked_by_owner"
END_REASON_GM_ROLE_REVOKED = "gm_role_revoked"
END_REASON_GM_ROLE_CHANGED = "gm_role_changed"
END_REASON_GM_ASSIGNMENT_LAPSED = "gm_assignment_lapsed"
END_REASON_MEMBERSHIP_ENDED = "membership_ended"
END_REASON_MEMBERSHIP_STATUS_CHANGED = "membership_status_changed"


def close_reveal_delegations_for_role(
    connection: Connection,
    *,
    gm_membership_role_id: uuid.UUID,
    end_reason: str,
    closed_at: datetime | None = None,
) -> tuple[uuid.UUID, ...]:
    """Closes the live delegation bound to this role assignment, if any. A no-op for every role
    that is not a delegation's `gm` assignment, so the role commands call it without checking the
    role's code."""
    return _close(
        connection,
        where="gm_membership_role_id = :target",
        target=gm_membership_role_id,
        end_reason=end_reason,
        closed_at=closed_at,
    )


def close_reveal_delegations_for_membership(
    connection: Connection,
    *,
    grantee_campaign_membership_id: uuid.UUID,
    end_reason: str,
    closed_at: datetime | None = None,
) -> tuple[uuid.UUID, ...]:
    """Closes the live delegation held by this membership, if any. Delegations the membership
    *granted* are untouched: the grantor is provenance, not authority."""
    return _close(
        connection,
        where="grantee_campaign_membership_id = :target",
        target=grantee_campaign_membership_id,
        end_reason=end_reason,
        closed_at=closed_at,
    )


def _close(
    connection: Connection,
    *,
    where: str,
    target: uuid.UUID,
    end_reason: str,
    closed_at: datetime | None,
) -> tuple[uuid.UUID, ...]:
    # `clock_timestamp()`, not `now()`: the closure must not predate the row's own `granted_at`
    # when a command waited behind the grant, and a closure is a fact at the instant it is written.
    rows = connection.execute(
        text(f"""
            UPDATE security.character_reveal_delegations
            SET revoked_at = COALESCE(CAST(:closed_at AS timestamptz), clock_timestamp()),
                end_reason = :end_reason
            WHERE revoked_at IS NULL AND {where}
            RETURNING character_reveal_delegation_id
        """),  # noqa: S608 - `where` is one of two literals in this module
        {"target": target, "end_reason": end_reason, "closed_at": closed_at},
    ).scalars()
    return tuple(rows)
