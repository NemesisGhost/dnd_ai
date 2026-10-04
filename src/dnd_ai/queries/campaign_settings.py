"""Campaign settings and archived-campaign read models (Phase 14).

Both are authorized by the *caller's own* `access.manage` membership in the
campaign (the route dependency for settings; the SQL join for the archived
list), never by world authority: a world owner does not see campaigns they do
not manage. Names returned are only those of the campaign's own world,
timeline, and pinned ruleset version.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, text

from dnd_ai.domain.authoring_policy import BlockedAction, campaign_actions


@dataclass(frozen=True)
class CampaignSettings:
    campaign_id: uuid.UUID
    name: str
    description: str | None
    lifecycle_status: str
    row_version: int
    world_id: uuid.UUID
    world_name: str
    timeline_id: uuid.UUID
    timeline_name: str
    ruleset_version_id: uuid.UUID
    ruleset_display_name: str
    ruleset_version_label: str
    available_actions: list[str]
    blocked_actions: list[BlockedAction]


@dataclass(frozen=True)
class ArchivedCampaign:
    campaign_id: uuid.UUID
    name: str
    world_name: str
    timeline_name: str
    row_version: int


def get_campaign_settings(
    connection: Connection, *, campaign_id: uuid.UUID
) -> CampaignSettings | None:
    row = connection.execute(
        text("""
            SELECT c.campaign_id, c.name, c.description, cls.code AS campaign_status,
                   c.row_version, w.world_id, w.name AS world_name, wls.code AS world_status,
                   t.timeline_id, t.name AS timeline_name, tls.code AS timeline_status,
                   rv.ruleset_version_id, rs.display_name AS ruleset_display_name,
                   rv.version_label
            FROM campaign.campaigns c
            JOIN core.lifecycle_statuses cls ON cls.lifecycle_status_id = c.lifecycle_status_id
            JOIN campaign.timelines t ON t.timeline_id = c.timeline_id
            JOIN core.lifecycle_statuses tls ON tls.lifecycle_status_id = t.lifecycle_status_id
            JOIN core.worlds w ON w.world_id = t.world_id
            JOIN core.lifecycle_statuses wls ON wls.lifecycle_status_id = w.lifecycle_status_id
            JOIN rules.ruleset_versions rv ON rv.ruleset_version_id = c.ruleset_version_id
            JOIN rules.rulesets rs ON rs.ruleset_id = rv.ruleset_id
            WHERE c.campaign_id = :c
        """),
        {"c": campaign_id},
    ).one_or_none()
    if row is None:
        return None
    has_manager = bool(
        connection.execute(
            text("SELECT security.campaign_has_access_manager(:c)"), {"c": campaign_id}
        ).scalar()
    )
    available, blocked = campaign_actions(
        campaign_status=str(row.campaign_status),
        world_status=str(row.world_status),
        timeline_status=str(row.timeline_status),
        has_access_manager=has_manager,
    )
    return CampaignSettings(
        campaign_id=row.campaign_id,
        name=str(row.name),
        description=row.description,
        lifecycle_status=str(row.campaign_status),
        row_version=int(row.row_version),
        world_id=row.world_id,
        world_name=str(row.world_name),
        timeline_id=row.timeline_id,
        timeline_name=str(row.timeline_name),
        ruleset_version_id=row.ruleset_version_id,
        ruleset_display_name=str(row.ruleset_display_name),
        ruleset_version_label=str(row.version_label),
        available_actions=available,
        blocked_actions=blocked,
    )


def list_archived_campaigns(
    connection: Connection,
    *,
    user_id: uuid.UUID,
    limit: int,
    after: tuple[str, uuid.UUID] | None,
) -> list[ArchivedCampaign]:
    """Archived campaigns where `user_id` holds an active, unrevoked,
    unexpired `access.manage` membership, ordered `(name, campaign_id)`.
    Fetches `limit + 1` rows for keyset paging."""
    rows = connection.execute(
        text("""
            SELECT DISTINCT c.campaign_id, c.name, w.name AS world_name,
                            t.name AS timeline_name, c.row_version
            FROM campaign.campaigns c
            JOIN core.lifecycle_statuses cls ON cls.lifecycle_status_id = c.lifecycle_status_id
            JOIN campaign.timelines t ON t.timeline_id = c.timeline_id
            JOIN core.worlds w ON w.world_id = t.world_id
            JOIN security.campaign_memberships cm ON cm.campaign_id = c.campaign_id
            JOIN security.membership_statuses ms
              ON ms.membership_status_id = cm.membership_status_id
            JOIN security.membership_roles mr
              ON mr.campaign_membership_id = cm.campaign_membership_id
            JOIN security.roles r ON r.role_id = mr.role_id
            JOIN security.role_capabilities rc ON rc.role_id = r.role_id
            JOIN security.capabilities cap ON cap.capability_id = rc.capability_id
            WHERE cls.code = 'archived'
              AND cm.user_id = :user_id
              AND cm.ended_at IS NULL
              AND ms.code = 'active' AND ms.is_active
              AND mr.revoked_at IS NULL
              AND (mr.expires_at IS NULL OR mr.expires_at > now())
              AND r.is_active
              AND cap.code = 'access.manage' AND cap.is_active
              AND (CAST(:after_name AS text) IS NULL
                   OR (c.name, c.campaign_id) > (:after_name, CAST(:after_id AS uuid)))
            ORDER BY c.name, c.campaign_id
            LIMIT :limit
        """),
        {
            "user_id": user_id,
            "after_name": None if after is None else after[0],
            "after_id": None if after is None else after[1],
            "limit": limit + 1,
        },
    ).all()
    return [
        ArchivedCampaign(
            campaign_id=row.campaign_id,
            name=str(row.name),
            world_name=str(row.world_name),
            timeline_name=str(row.timeline_name),
            row_version=int(row.row_version),
        )
        for row in rows
    ]
