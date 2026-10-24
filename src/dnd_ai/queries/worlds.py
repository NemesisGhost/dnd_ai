"""World read models for the authoring surfaces (Phase 14).

`list_worlds` returns only worlds on which the caller holds authority — the
authority join is part of the SQL, so unauthorized rows never leave the
database and pagination is applied after filtering. `get_world_detail` assumes
the caller has already been authorized for `world.view` (the route dependency)
and builds the read model, including the server-computed
`available_actions` / `blocked_actions` from the same policy functions the
commands call (`dnd_ai.domain.authoring_policy`), restricted to the actions the
caller's world roles carry the capability for
(`dnd_ai.domain.world_authority.WORLD_ACTION_CAPABILITIES`) — a `world_viewer`
is offered none.

`managed_campaigns` deliberately lists only campaigns on which the *caller*
holds an active `access.manage` membership: a world owner learns nothing about
campaigns they do not manage (docs/PLAN.md Phase 14, §8 rule 7).
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, text

from dnd_ai.domain.authoring_policy import BlockedAction, world_actions
from dnd_ai.domain.system_authority import WORLD_ADMINISTER
from dnd_ai.domain.world_authority import (
    WORLD_ACTION_CAPABILITIES,
    WorldAuthority,
    authorized_actions,
    capabilities_for_roles,
)
from dnd_ai.queries.system_authority import has_system_capability
from dnd_ai.queries.timelines import TimelineSummary, list_timeline_summaries

NAME_SORT_PREFIX = 200


@dataclass(frozen=True)
class WorldSummary:
    world_id: uuid.UUID
    name: str
    description: str | None
    lifecycle_status: str
    row_version: int
    primary_timeline_id: uuid.UUID | None
    capabilities: list[str]
    sort_name: str
    # Display only: the caller's world role codes and whether they hold a use grant.
    role_codes: list[str]
    has_use_grant: bool


@dataclass(frozen=True)
class RulesetVersionOption:
    ruleset_version_id: uuid.UUID
    version_label: str


@dataclass(frozen=True)
class AllowedRuleset:
    ruleset_id: uuid.UUID
    code: str
    display_name: str
    is_default: bool
    current_version: RulesetVersionOption | None


@dataclass(frozen=True)
class ManagedCampaign:
    campaign_id: uuid.UUID
    name: str
    lifecycle_status: str
    timeline_id: uuid.UUID


@dataclass(frozen=True)
class WorldDetail:
    summary: WorldSummary
    default_ruleset_id: uuid.UUID | None
    allowed_rulesets: list[AllowedRuleset]
    timelines: list[TimelineSummary]
    managed_campaigns: list[ManagedCampaign]
    available_actions: list[str]
    blocked_actions: list[BlockedAction]


def list_worlds(
    connection: Connection,
    *,
    user_id: uuid.UUID,
    status: str,
    limit: int,
    after: tuple[str, uuid.UUID] | None,
) -> list[WorldSummary]:
    """Authorized worlds ordered by `(lower(name), world_id)`; fetches
    `limit + 1` rows so the caller can build a keyset page."""
    may_administer = has_system_capability(
        connection, user_id=user_id, capability_code=WORLD_ADMINISTER
    )
    rows = connection.execute(
        text("""
            WITH my_roles AS (
                SELECT wm.world_id, wr.code AS role_code
                FROM security.world_memberships wm
                JOIN security.membership_statuses ms
                  ON ms.membership_status_id = wm.membership_status_id
                JOIN security.world_roles wr ON wr.world_role_id = wm.world_role_id
                WHERE wm.user_id = :user_id
                  AND wm.ended_at IS NULL
                  AND ms.code = 'active' AND ms.is_active
                  AND wr.is_active
            ), my_grants AS (
                SELECT g.world_id
                FROM security.world_use_grants g
                WHERE g.user_id = :user_id AND g.revoked_at IS NULL
            ), my_worlds AS (
                SELECT world_id FROM my_roles
                UNION
                SELECT world_id FROM my_grants
            )
            SELECT w.world_id, w.name, w.description, wls.code AS lifecycle_code,
                   w.row_version, lower(w.name) AS sort_name,
                   (SELECT t.timeline_id FROM campaign.timelines t
                     WHERE t.world_id = w.world_id AND t.is_primary) AS primary_timeline_id,
                   COALESCE(
                       (SELECT array_agg(DISTINCT r.role_code) FROM my_roles r
                         WHERE r.world_id = w.world_id),
                       ARRAY[]::text[]
                   ) AS role_codes,
                   EXISTS (SELECT 1 FROM my_grants g WHERE g.world_id = w.world_id)
                       AS has_use_grant
            FROM my_worlds mw
            JOIN core.worlds w ON w.world_id = mw.world_id
            JOIN core.lifecycle_statuses wls ON wls.lifecycle_status_id = w.lifecycle_status_id
            JOIN security.users u ON u.user_id = :user_id
            JOIN core.lifecycle_statuses uls ON uls.lifecycle_status_id = u.lifecycle_status_id
            WHERE uls.code = 'active'
              AND (CAST(:status AS text) = 'all' OR wls.code = :status)
              AND (CAST(:after_name AS text) IS NULL
                   OR (lower(w.name), w.world_id) > (:after_name, CAST(:after_id AS uuid)))
            ORDER BY lower(w.name), w.world_id
            LIMIT :limit
        """),
        {
            "user_id": user_id,
            "status": status,
            "after_name": None if after is None else after[0],
            "after_id": None if after is None else after[1],
            "limit": limit + 1,
        },
    ).all()
    return [
        WorldSummary(
            world_id=row.world_id,
            name=str(row.name),
            description=row.description,
            lifecycle_status=str(row.lifecycle_code),
            row_version=int(row.row_version),
            primary_timeline_id=row.primary_timeline_id,
            capabilities=sorted(
                capabilities_for_roles(
                    frozenset(row.role_codes),
                    has_use_grant=bool(row.has_use_grant),
                    may_administer=may_administer,
                )
            ),
            sort_name=str(row.sort_name),
            role_codes=sorted(row.role_codes),
            has_use_grant=bool(row.has_use_grant),
        )
        for row in rows
    ]


def list_managed_campaigns(
    connection: Connection,
    *,
    user_id: uuid.UUID,
    world_id: uuid.UUID,
    timeline_id: uuid.UUID | None = None,
) -> list[ManagedCampaign]:
    """Campaigns on this world (optionally one timeline) where `user_id` holds
    an active, non-expiring-or-unexpired `access.manage` membership. Archived
    campaigns are included (so an owner can find one to reactivate); deleted
    ones are not."""
    rows = connection.execute(
        text("""
            SELECT DISTINCT c.campaign_id, c.name, cls.code AS lifecycle_code, c.timeline_id
            FROM campaign.campaigns c
            JOIN campaign.timelines t ON t.timeline_id = c.timeline_id
            JOIN core.lifecycle_statuses cls ON cls.lifecycle_status_id = c.lifecycle_status_id
            JOIN security.campaign_memberships cm ON cm.campaign_id = c.campaign_id
            JOIN security.membership_statuses ms
              ON ms.membership_status_id = cm.membership_status_id
            JOIN security.membership_roles mr
              ON mr.campaign_membership_id = cm.campaign_membership_id
            JOIN security.roles r ON r.role_id = mr.role_id
            JOIN security.role_capabilities rc ON rc.role_id = r.role_id
            JOIN security.capabilities cap ON cap.capability_id = rc.capability_id
            WHERE t.world_id = :world_id
              AND (CAST(:timeline_id AS uuid) IS NULL OR c.timeline_id = :timeline_id)
              AND cls.code <> 'deleted'
              AND cm.user_id = :user_id
              AND cm.ended_at IS NULL
              AND ms.code = 'active' AND ms.is_active
              AND mr.revoked_at IS NULL
              AND (mr.expires_at IS NULL OR mr.expires_at > now())
              AND r.is_active
              AND cap.code = 'access.manage' AND cap.is_active
            ORDER BY c.name, c.campaign_id
        """),
        {"world_id": world_id, "timeline_id": timeline_id, "user_id": user_id},
    ).all()
    return [
        ManagedCampaign(
            campaign_id=row.campaign_id,
            name=str(row.name),
            lifecycle_status=str(row.lifecycle_code),
            timeline_id=row.timeline_id,
        )
        for row in rows
    ]


def world_has_blocking_campaigns(connection: Connection, *, world_id: uuid.UUID) -> bool:
    """Any non-archived campaign on any of the world's timelines. A boolean
    only: callers must never disclose a count, name, or ID from it."""
    return bool(
        connection.execute(
            text("""
                SELECT EXISTS (
                    SELECT 1
                    FROM campaign.campaigns c
                    JOIN campaign.timelines t ON t.timeline_id = c.timeline_id
                    JOIN core.lifecycle_statuses cls
                      ON cls.lifecycle_status_id = c.lifecycle_status_id
                    WHERE t.world_id = :w AND cls.code NOT IN ('archived', 'deleted')
                )
            """),
            {"w": world_id},
        ).scalar()
    )


def get_world_detail(
    connection: Connection,
    *,
    user_id: uuid.UUID,
    world_id: uuid.UUID,
    authority: WorldAuthority,
) -> WorldDetail | None:
    row = connection.execute(
        text("""
            SELECT w.world_id, w.name, w.description, wls.code AS lifecycle_code,
                   w.row_version, w.default_ruleset_id, lower(w.name) AS sort_name,
                   (SELECT t.timeline_id FROM campaign.timelines t
                     WHERE t.world_id = w.world_id AND t.is_primary) AS primary_timeline_id
            FROM core.worlds w
            JOIN core.lifecycle_statuses wls ON wls.lifecycle_status_id = w.lifecycle_status_id
            WHERE w.world_id = :w
        """),
        {"w": world_id},
    ).one_or_none()
    if row is None:
        return None

    allowed = [
        AllowedRuleset(
            ruleset_id=r.ruleset_id,
            code=str(r.code),
            display_name=str(r.display_name),
            is_default=r.ruleset_id == row.default_ruleset_id,
            current_version=(
                None
                if r.ruleset_version_id is None
                else RulesetVersionOption(
                    ruleset_version_id=r.ruleset_version_id, version_label=str(r.version_label)
                )
            ),
        )
        for r in connection.execute(
            text("""
                SELECT rs.ruleset_id, rs.code, rs.display_name,
                       rv.ruleset_version_id, rv.version_label
                FROM rules.world_rulesets wr
                JOIN rules.rulesets rs ON rs.ruleset_id = wr.ruleset_id
                LEFT JOIN rules.ruleset_versions rv
                  ON rv.ruleset_id = rs.ruleset_id AND rv.is_current
                WHERE wr.world_id = :w
                ORDER BY rs.display_name, rs.ruleset_id
            """),
            {"w": world_id},
        ).all()
    ]
    blocking = world_has_blocking_campaigns(connection, world_id=world_id)
    capabilities = authority.capabilities
    available, blocked = authorized_actions(
        *world_actions(lifecycle_status=str(row.lifecycle_code), has_blocking_campaigns=blocking),
        capabilities=capabilities,
        required=WORLD_ACTION_CAPABILITIES,
    )
    summary = WorldSummary(
        world_id=row.world_id,
        name=str(row.name),
        description=row.description,
        lifecycle_status=str(row.lifecycle_code),
        row_version=int(row.row_version),
        primary_timeline_id=row.primary_timeline_id,
        capabilities=sorted(authority.capabilities),
        sort_name=str(row.sort_name),
        role_codes=sorted(authority.role_codes),
        has_use_grant=authority.has_use_grant,
    )
    return WorldDetail(
        summary=summary,
        default_ruleset_id=row.default_ruleset_id,
        allowed_rulesets=allowed,
        timelines=list_timeline_summaries(connection, world_id=world_id),
        managed_campaigns=list_managed_campaigns(connection, user_id=user_id, world_id=world_id),
        available_actions=available,
        blocked_actions=blocked,
    )
