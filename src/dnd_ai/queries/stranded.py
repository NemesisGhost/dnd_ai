"""Stranded worlds and campaigns (docs/adr/0020-scoped-system-world-and-campaign-roles.md).

A world is *stranded* when it has an open Owner assignment but no Owner who can
actually manage it: an Owner needs an active account **and** the system `gm`
role (decision D11). A campaign is stranded when no active account holds a
non-expiring `access.manage` assignment in it. Disabling an account, or revoking
system GM, can strand either; the database retention triggers do not notice,
because they look only at the assignment rows. The administrator who made the
change is told the IDs (and nothing else) so the recovery commands in
`dnd_ai.commands.recovery` can be applied.

Pure reads, no row locks: they report, they never authorize.
"""

import uuid

from sqlalchemy import Connection, text

# A manageable world owner: an open, active-status Owner assignment on an active
# account that currently holds an unrevoked system `gm` assignment.
_MANAGEABLE_OWNER_EXISTS = """
    EXISTS (
        SELECT 1
        FROM security.world_memberships mwm
        JOIN security.membership_statuses mms
          ON mms.membership_status_id = mwm.membership_status_id
        JOIN security.world_roles mwr ON mwr.world_role_id = mwm.world_role_id
        JOIN security.users mu ON mu.user_id = mwm.user_id
        JOIN core.lifecycle_statuses mls ON mls.lifecycle_status_id = mu.lifecycle_status_id
        WHERE mwm.world_id = w.world_id
          AND mwm.ended_at IS NULL
          AND mms.code = 'active' AND mms.is_active
          AND mwr.code = 'world_owner' AND mwr.is_active
          AND mls.code = 'active'
          AND EXISTS (
              SELECT 1
              FROM security.user_system_roles musr
              JOIN security.system_roles msr ON msr.system_role_id = musr.system_role_id
              WHERE musr.user_id = mu.user_id AND musr.revoked_at IS NULL
                AND msr.code = 'gm' AND msr.is_active
          )
    )
"""

_ACCESS_MANAGER_PREDICATE = """
    EXISTS (
        SELECT 1
        FROM security.campaign_memberships mcm
        JOIN security.membership_statuses mms
          ON mms.membership_status_id = mcm.membership_status_id
        JOIN security.users mu ON mu.user_id = mcm.user_id
        JOIN core.lifecycle_statuses mls ON mls.lifecycle_status_id = mu.lifecycle_status_id
        JOIN security.membership_roles mmr
          ON mmr.campaign_membership_id = mcm.campaign_membership_id
        JOIN security.roles mr ON mr.role_id = mmr.role_id
        JOIN security.role_capabilities mrc ON mrc.role_id = mr.role_id
        JOIN security.capabilities mcap ON mcap.capability_id = mrc.capability_id
        WHERE mcm.campaign_id = c.campaign_id
          AND mcm.ended_at IS NULL
          AND mms.code = 'active' AND mms.is_active
          AND mls.code = 'active'
          AND mmr.revoked_at IS NULL AND mmr.expires_at IS NULL
          AND mr.is_active
          AND mcap.code = 'access.manage' AND mcap.is_active
          {extra}
    )
"""


def stranded_world_ids_for_owner(connection: Connection, *, user_id: uuid.UUID) -> list[uuid.UUID]:
    """Worlds on which `user_id` holds an open Owner assignment and that currently
    have no manageable Owner at all."""
    rows = connection.execute(
        text(f"""
            SELECT DISTINCT w.world_id
            FROM core.worlds w
            JOIN security.world_memberships wm ON wm.world_id = w.world_id
            JOIN security.world_roles wr ON wr.world_role_id = wm.world_role_id
            WHERE wm.user_id = :u AND wm.ended_at IS NULL AND wr.code = 'world_owner'
              AND NOT {_MANAGEABLE_OWNER_EXISTS}
            ORDER BY w.world_id
        """),
        {"u": user_id},
    ).scalars()
    return list(rows)


def stranded_campaign_ids_for_manager(
    connection: Connection, *, user_id: uuid.UUID
) -> list[uuid.UUID]:
    """Active campaigns in which `user_id` holds `access.manage` and no *active*
    account does."""
    manager = _ACCESS_MANAGER_PREDICATE.format(extra="")
    rows = connection.execute(
        text(f"""
            SELECT DISTINCT c.campaign_id
            FROM campaign.campaigns c
            JOIN core.lifecycle_statuses cls ON cls.lifecycle_status_id = c.lifecycle_status_id
            WHERE cls.code = 'active'
              AND EXISTS (
                  SELECT 1
                  FROM security.campaign_memberships cm
                  JOIN security.membership_roles mr2
                    ON mr2.campaign_membership_id = cm.campaign_membership_id
                  JOIN security.role_capabilities rc2 ON rc2.role_id = mr2.role_id
                  JOIN security.capabilities cap2 ON cap2.capability_id = rc2.capability_id
                  WHERE cm.campaign_id = c.campaign_id AND cm.user_id = :u
                    AND cm.ended_at IS NULL AND mr2.revoked_at IS NULL
                    AND mr2.expires_at IS NULL AND cap2.code = 'access.manage'
              )
              AND NOT {manager}
            ORDER BY c.campaign_id
        """),
        {"u": user_id},
    ).scalars()
    return list(rows)


def world_has_manageable_owner(connection: Connection, *, world_id: uuid.UUID) -> bool:
    return bool(
        connection.execute(
            text(f"SELECT {_MANAGEABLE_OWNER_EXISTS} FROM core.worlds w WHERE w.world_id = :w"),
            {"w": world_id},
        ).scalar()
    )


def campaign_has_active_access_manager(connection: Connection, *, campaign_id: uuid.UUID) -> bool:
    manager = _ACCESS_MANAGER_PREDICATE.format(extra="")
    return bool(
        connection.execute(
            text(f"SELECT {manager} FROM campaign.campaigns c WHERE c.campaign_id = :c"),
            {"c": campaign_id},
        ).scalar()
    )
