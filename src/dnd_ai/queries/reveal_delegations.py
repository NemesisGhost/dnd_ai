"""Read-only state of reveal-authority delegations for the Access section (P15-C02-S03).

`character.reveal` has two sources (`dnd_ai.domain.reveal_authority`): a live built-in `campaign_owner`
assignment, and a delegation from an owner to a member holding the built-in `gm` role, bound to one specific `gm`
assignment. This module answers, on the server and with the commands' own predicates, the three questions the
portal must not decide for itself:

- **Who may act.** `can_manage` is true when the caller holds a live built-in owner assignment
  (`find_live_builtin_owner_assignment`, the predicate the D3 gate uses). `access.manage` alone is not it.
- **Who is eligible.** `members` is every membership that holds a live built-in `gm` assignment
  (`find_live_builtin_gm_assignment`'s definition, as one set query: built-in template, active role, assignment
  neither revoked nor expired, membership open and `active`, account active). A campaign-scoped role coded `gm`
  and the `assistant_gm` role are not it. The lowest `membership_role_id` is the member's assignment, as there.
- **What is effective.** A member's `delegation` is set only when an unrevoked delegation row is bound to that live
  assignment: the delegation authorizes. An unrevoked row bound to a lapsed assignment authorizes nothing
  (`resolve_reveal_authority`), yet nothing closes it when the assignment expires. So an open row whose grantee
  holds no live built-in `gm` assignment is reported as `lapsed_delegations`, so an owner can find it and close it
  with the existing revoke route. A stale row of a member who does hold a live assignment is not reported: that
  member is listed with no delegation, and the next grant closes the stale row as it always has.

This is a pure read: no lock, no write, no audit row, no lifecycle rule. Reasons, revocation reasons, delegation and
role ids, user ids and ended rows are never selected.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Connection, text

from dnd_ai.domain.access import BUILTIN_CAMPAIGN_GM_ROLE_CODE, find_live_builtin_owner_assignment


@dataclass(frozen=True)
class DelegationView:
    granted_at: datetime
    granted_by_name: str | None


@dataclass(frozen=True)
class GmMemberView:
    campaign_membership_id: uuid.UUID
    display_name: str
    delegation: DelegationView | None


@dataclass(frozen=True)
class LapsedDelegationView:
    campaign_membership_id: uuid.UUID
    display_name: str
    delegation: DelegationView


@dataclass(frozen=True)
class RevealDelegationState:
    can_manage: bool
    members: tuple[GmMemberView, ...]
    lapsed_delegations: tuple[LapsedDelegationView, ...]


# The members who hold a live built-in `gm` assignment, one assignment per member (the lowest id, as
# `find_live_builtin_gm_assignment`'s `ORDER BY membership_role_id LIMIT 1` chooses). "Live" is the same
# definition, judged at `now()`.
_LIVE_GM = """
    live_gm AS (
        SELECT DISTINCT ON (mr.campaign_membership_id)
               mr.campaign_membership_id, mr.membership_role_id
        FROM security.membership_roles mr
        JOIN security.roles r ON r.role_id = mr.role_id
        JOIN security.campaign_memberships cm
            ON cm.campaign_membership_id = mr.campaign_membership_id
        JOIN security.membership_statuses ms ON ms.membership_status_id = cm.membership_status_id
        JOIN security.users u ON u.user_id = cm.user_id
        JOIN core.lifecycle_statuses uls ON uls.lifecycle_status_id = u.lifecycle_status_id
        WHERE cm.campaign_id = :campaign
          AND r.campaign_id IS NULL
          AND r.code = :gm_code
          AND r.is_active
          AND mr.revoked_at IS NULL
          AND (mr.expires_at IS NULL OR mr.expires_at > now())
          AND cm.ended_at IS NULL
          AND ms.code = 'active'
          AND ms.is_active
          AND uls.code = 'active'
        ORDER BY mr.campaign_membership_id, mr.membership_role_id
    )
"""


def get_reveal_delegation_state(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    caller_campaign_membership_id: uuid.UUID,
) -> RevealDelegationState:
    can_manage = (
        find_live_builtin_owner_assignment(
            connection,
            campaign_id=campaign_id,
            campaign_membership_id=caller_campaign_membership_id,
        )
        is not None
    )
    params = {"campaign": campaign_id, "gm_code": BUILTIN_CAMPAIGN_GM_ROLE_CODE}
    member_rows = (
        connection.execute(
            text(f"""
                WITH {_LIVE_GM}
                SELECT cm.campaign_membership_id, u.display_name,
                       d.granted_at, granter.display_name AS granted_by_name,
                       (d.granted_at IS NOT NULL) AS has_delegation
                FROM live_gm
                JOIN security.campaign_memberships cm
                    ON cm.campaign_membership_id = live_gm.campaign_membership_id
                JOIN security.users u ON u.user_id = cm.user_id
                LEFT JOIN security.character_reveal_delegations d
                    ON d.grantee_campaign_membership_id = cm.campaign_membership_id
                   AND d.campaign_id = :campaign
                   AND d.revoked_at IS NULL
                   AND d.gm_membership_role_id = live_gm.membership_role_id
                LEFT JOIN security.campaign_memberships gcm
                    ON gcm.campaign_membership_id = d.granted_by_membership_id
                LEFT JOIN security.users granter ON granter.user_id = gcm.user_id
                ORDER BY u.display_name, cm.campaign_membership_id
            """),  # noqa: S608 - the CTE text is a module constant
            params,
        )
        .mappings()
        .all()
    )
    lapsed_rows = (
        connection.execute(
            text(f"""
                WITH {_LIVE_GM}
                SELECT cm.campaign_membership_id, u.display_name,
                       d.granted_at, granter.display_name AS granted_by_name
                FROM security.character_reveal_delegations d
                JOIN security.campaign_memberships cm
                    ON cm.campaign_membership_id = d.grantee_campaign_membership_id
                   AND cm.campaign_id = :campaign
                JOIN security.users u ON u.user_id = cm.user_id
                LEFT JOIN security.campaign_memberships gcm
                    ON gcm.campaign_membership_id = d.granted_by_membership_id
                LEFT JOIN security.users granter ON granter.user_id = gcm.user_id
                WHERE d.campaign_id = :campaign
                  AND d.revoked_at IS NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM live_gm
                      WHERE live_gm.campaign_membership_id = d.grantee_campaign_membership_id
                  )
                ORDER BY u.display_name, cm.campaign_membership_id
            """),  # noqa: S608 - the CTE text is a module constant
            params,
        )
        .mappings()
        .all()
    )
    return RevealDelegationState(
        can_manage=can_manage,
        members=tuple(
            GmMemberView(
                campaign_membership_id=row["campaign_membership_id"],
                display_name=row["display_name"],
                delegation=(
                    DelegationView(
                        granted_at=row["granted_at"], granted_by_name=row["granted_by_name"]
                    )
                    if row["has_delegation"]
                    else None
                ),
            )
            for row in member_rows
        ),
        lapsed_delegations=tuple(
            LapsedDelegationView(
                campaign_membership_id=row["campaign_membership_id"],
                display_name=row["display_name"],
                delegation=DelegationView(
                    granted_at=row["granted_at"], granted_by_name=row["granted_by_name"]
                ),
            )
            for row in lapsed_rows
        ),
    )
