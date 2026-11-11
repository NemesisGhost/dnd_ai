"""Read-only preflight for the campaign-owner gate (P03-A decision D3).

Reports existing data the gate, or two known gaps beside it, would touch. It changes nothing: the
connection is read-only. Run it before treating the gate as rollout-ready.

Usage (from the repository root):

    uv run python scripts/preflight_campaign_owner_gate.py

The database comes from DND_AI_DATABASE_URL, or DATABASE_URL when that is not set. The exit status
is 0 when every count is zero and 1 otherwise; ids and role codes are printed, no names.

Checks:

1. `non_owner_access_manage`: roles other than the built-in owner template that carry
   `access.manage`. Any row means the gate changes who can grant the owner role in that campaign.
2. `live_owner_on_ended_or_inactive`: unrevoked built-in owner assignments whose membership has
   ended, is not `active`, or whose account is not active. Invitation acceptance reopens a
   membership and would restore such an owner.
3. `expired_unrevoked_owner`: unrevoked built-in owner assignments whose expiry has passed. This is
   the data the expired-target transfer bug (follow-up F1) acts on.
4. `active_campaign_without_live_owner`: active campaigns with no live built-in owner. Where a
   custom role holds `access.manage`, the recovery precondition does not fire (follow-up F2).
"""

import os
import sys

from sqlalchemy import create_engine, text

_OWNER = "r.campaign_id IS NULL AND r.code = 'campaign_owner'"

_CHECKS: dict[str, str] = {
    "non_owner_access_manage": f"""
        SELECT r.role_id, r.campaign_id, r.code
        FROM security.roles r
        JOIN security.role_capabilities rc ON rc.role_id = r.role_id
        JOIN security.capabilities c ON c.capability_id = rc.capability_id
        WHERE c.code = 'access.manage' AND NOT ({_OWNER})
        ORDER BY r.campaign_id NULLS FIRST, r.code
    """,
    "live_owner_on_ended_or_inactive": f"""
        SELECT mr.membership_role_id, cm.campaign_id, cm.campaign_membership_id
        FROM security.membership_roles mr
        JOIN security.roles r ON r.role_id = mr.role_id
        JOIN security.campaign_memberships cm
            ON cm.campaign_membership_id = mr.campaign_membership_id
        JOIN security.membership_statuses ms ON ms.membership_status_id = cm.membership_status_id
        JOIN security.users u ON u.user_id = cm.user_id
        JOIN core.lifecycle_statuses uls ON uls.lifecycle_status_id = u.lifecycle_status_id
        WHERE {_OWNER} AND mr.revoked_at IS NULL
          AND (cm.ended_at IS NOT NULL OR ms.code <> 'active' OR NOT ms.is_active
               OR uls.code <> 'active')
        ORDER BY cm.campaign_id, mr.membership_role_id
    """,
    "expired_unrevoked_owner": f"""
        SELECT mr.membership_role_id, cm.campaign_id, cm.campaign_membership_id
        FROM security.membership_roles mr
        JOIN security.roles r ON r.role_id = mr.role_id
        JOIN security.campaign_memberships cm
            ON cm.campaign_membership_id = mr.campaign_membership_id
        WHERE {_OWNER} AND mr.revoked_at IS NULL
          AND mr.expires_at IS NOT NULL AND mr.expires_at <= now()
        ORDER BY cm.campaign_id, mr.membership_role_id
    """,
    "active_campaign_without_live_owner": f"""
        SELECT c.campaign_id
        FROM campaign.campaigns c
        JOIN core.lifecycle_statuses cls ON cls.lifecycle_status_id = c.lifecycle_status_id
        WHERE cls.code = 'active'
          AND NOT EXISTS (
            SELECT 1
            FROM security.membership_roles mr
            JOIN security.roles r ON r.role_id = mr.role_id
            JOIN security.campaign_memberships cm
                ON cm.campaign_membership_id = mr.campaign_membership_id
            JOIN security.membership_statuses ms
                ON ms.membership_status_id = cm.membership_status_id
            JOIN security.users u ON u.user_id = cm.user_id
            JOIN core.lifecycle_statuses uls ON uls.lifecycle_status_id = u.lifecycle_status_id
            WHERE cm.campaign_id = c.campaign_id AND {_OWNER}
              AND r.is_active AND mr.revoked_at IS NULL
              AND (mr.expires_at IS NULL OR mr.expires_at > now())
              AND cm.ended_at IS NULL AND ms.code = 'active' AND ms.is_active
              AND uls.code = 'active'
          )
        ORDER BY c.campaign_id
    """,
}


def main() -> int:
    url = os.environ.get("DND_AI_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        print("Set DND_AI_DATABASE_URL or DATABASE_URL.", file=sys.stderr)
        return 2
    engine = create_engine(url, execution_options={"postgresql_readonly": True})
    total = 0
    with engine.connect() as connection:
        connection.execute(text("SET TRANSACTION READ ONLY"))
        for name, query in _CHECKS.items():
            rows = connection.execute(text(query)).all()
            total += len(rows)
            print(f"{name}: {len(rows)}")
            for row in rows:
                print("  " + ", ".join(str(value) for value in row))
    print("clean" if total == 0 else f"{total} row(s) need review before rollout")
    return 0 if total == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
