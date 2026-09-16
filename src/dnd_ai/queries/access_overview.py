"""Read-only GM campaign access overview (Phase 13E-A, docs/PLAN.md Phase 13
"13E — GM access tools").

`get_campaign_access_overview` assembles, for one campaign, every currently
open membership (`security.campaign_memberships.ended_at IS NULL`) together
with its active roles, current character relationships, and explicit
membership-targeted resource grants — the same "currently true" slice
`dnd_ai.domain.access.resolve_access_context` resolves for a single caller,
here assembled for every member at once so a GM can review the campaign's
access as a whole. Each nested collection applies the identical
revoked/expired/timeline filter `resolve_access_context` already uses
(`revoked_at IS NULL`, `expires_at IS NULL OR expires_at > now()`,
`timeline_id IS NULL OR timeline_id = :timeline_id`), so this overview never
shows a relationship or grant that would not currently apply.

Deliberately out of scope for this first increment (documented here rather
than silently omitted):

- Access-group-targeted resource grants (`resource_grants.
  grantee_access_group_id`) — only membership-targeted grants are included.
  Groups are a separate, not-yet-surfaced concept on this screen.
- `security.users.lifecycle_status_id` (whether the underlying account is
  platform-active/disabled) — that is account-wide administration, a
  different capability scope than this campaign's `access.manage`
  (docs/UI_DESIGN.md's "do not merge account-wide administration with
  campaign administration unless the existing authorization model
  explicitly does so"). Only the campaign-scoped `membership_statuses` value
  is included.
- Pending/outstanding `security.campaign_invitations` — a closed membership
  never existed yet, so it is outside the same "current members" scope this
  overview covers; a future increment may add it once invitation mutations
  themselves are built here.
- The specific display identity of a non-character resource-grant target
  (`entity_id`/`knowledge_item_id`/`quest_id`/`session_id`/`event_id`) —
  resolving a display name for each of five unrelated resource kinds is a
  larger surface than this focused read needs; only the target *kind* is
  returned (`target_type`), never the raw id.

This is a pure read: no idempotency key, no `audit.change_log` row, no
mutation. Authorization is entirely the caller's concern
(`dnd_ai.api.access.require_campaign_capability("access.manage")`) — this
module trusts the `campaign_id`/`timeline_id` it is given, exactly like
`dnd_ai.queries.quest.list_campaign_quests`.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Connection, text

_GRANT_TARGET_COLUMNS = (
    "character_id",
    "entity_id",
    "knowledge_item_id",
    "quest_id",
    "session_id",
    "event_id",
)


@dataclass(frozen=True)
class MemberRoleView:
    role_id: uuid.UUID
    code: str
    display_name: str


@dataclass(frozen=True)
class MemberCharacterRelationshipView:
    membership_character_relationship_id: uuid.UUID
    character_id: uuid.UUID
    character_display_name: str
    relationship_type_code: str
    relationship_type_display_name: str
    granted_at: datetime
    expires_at: datetime | None


@dataclass(frozen=True)
class MemberResourceGrantView:
    resource_grant_id: uuid.UUID
    capability_code: str
    capability_display_name: str
    effect: str
    target_type: str
    reason: str | None
    granted_at: datetime
    expires_at: datetime | None


@dataclass(frozen=True)
class CampaignMemberView:
    campaign_membership_id: uuid.UUID
    display_name: str
    status_code: str
    status_display_name: str
    joined_at: datetime
    roles: tuple[MemberRoleView, ...]
    character_relationships: tuple[MemberCharacterRelationshipView, ...]
    grants: tuple[MemberResourceGrantView, ...]


def get_campaign_access_overview(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    timeline_id: uuid.UUID,
) -> tuple[CampaignMemberView, ...]:
    """Every currently open membership in `campaign_id`, each with its
    active roles, current character relationships, and explicit
    membership-targeted resource grants. `timeline_id` must already be the
    campaign's own pinned timeline (the caller's resolved `AccessContext.
    timeline_id` — never a caller-supplied value), matching every other
    timeline-scoped filter in `dnd_ai.domain.access`."""
    member_rows = (
        connection.execute(
            text("""
            SELECT cm.campaign_membership_id, u.display_name, cm.joined_at,
                   ms.code AS status_code, ms.display_name AS status_display_name
            FROM security.campaign_memberships cm
            JOIN security.users u ON u.user_id = cm.user_id
            JOIN security.membership_statuses ms ON ms.membership_status_id = cm.membership_status_id
            WHERE cm.campaign_id = :campaign_id
              AND cm.ended_at IS NULL
            ORDER BY u.display_name, cm.campaign_membership_id
        """),
            {"campaign_id": campaign_id},
        )
        .mappings()
        .all()
    )

    roles_by_membership: dict[uuid.UUID, list[MemberRoleView]] = {}
    for row in connection.execute(
        text("""
            SELECT mr.campaign_membership_id, r.role_id, r.code, r.display_name
            FROM security.membership_roles mr
            JOIN security.roles r ON r.role_id = mr.role_id
            JOIN security.campaign_memberships cm
              ON cm.campaign_membership_id = mr.campaign_membership_id
            WHERE cm.campaign_id = :campaign_id
              AND cm.ended_at IS NULL
              AND mr.revoked_at IS NULL
              AND (mr.expires_at IS NULL OR mr.expires_at > now())
              AND r.is_active
            ORDER BY r.sort_order, r.display_name
        """),
        {"campaign_id": campaign_id},
    ).mappings():
        roles_by_membership.setdefault(row["campaign_membership_id"], []).append(
            MemberRoleView(
                role_id=row["role_id"], code=row["code"], display_name=row["display_name"]
            )
        )

    relationships_by_membership: dict[uuid.UUID, list[MemberCharacterRelationshipView]] = {}
    for row in connection.execute(
        text("""
            SELECT mcr.campaign_membership_id, mcr.membership_character_relationship_id,
                   mcr.character_id, e.canonical_name AS character_display_name,
                   rt.code AS relationship_type_code,
                   rt.display_name AS relationship_type_display_name,
                   mcr.granted_at, mcr.expires_at
            FROM security.membership_character_relationships mcr
            JOIN security.campaign_memberships cm
              ON cm.campaign_membership_id = mcr.campaign_membership_id
            JOIN security.character_relationship_types rt
              ON rt.character_relationship_type_id = mcr.character_relationship_type_id
            JOIN core.entities e ON e.entity_id = mcr.character_id
            WHERE cm.campaign_id = :campaign_id
              AND cm.ended_at IS NULL
              AND mcr.revoked_at IS NULL
              AND (mcr.expires_at IS NULL OR mcr.expires_at > now())
              AND (mcr.timeline_id IS NULL OR mcr.timeline_id = :timeline_id)
            ORDER BY e.canonical_name, mcr.membership_character_relationship_id
        """),
        {"campaign_id": campaign_id, "timeline_id": timeline_id},
    ).mappings():
        relationships_by_membership.setdefault(row["campaign_membership_id"], []).append(
            MemberCharacterRelationshipView(
                membership_character_relationship_id=row["membership_character_relationship_id"],
                character_id=row["character_id"],
                character_display_name=row["character_display_name"],
                relationship_type_code=row["relationship_type_code"],
                relationship_type_display_name=row["relationship_type_display_name"],
                granted_at=row["granted_at"],
                expires_at=row["expires_at"],
            )
        )

    grants_by_membership: dict[uuid.UUID, list[MemberResourceGrantView]] = {}
    target_column_list = ", ".join(f"rg.{column}" for column in _GRANT_TARGET_COLUMNS)
    for row in connection.execute(
        text(f"""
            SELECT rg.grantee_campaign_membership_id, rg.resource_grant_id,
                   cap.code AS capability_code, cap.display_name AS capability_display_name,
                   rg.effect, rg.reason, rg.granted_at, rg.expires_at, {target_column_list}
            FROM security.resource_grants rg
            JOIN security.capabilities cap ON cap.capability_id = rg.capability_id
            JOIN security.campaign_memberships cm
              ON cm.campaign_membership_id = rg.grantee_campaign_membership_id
            WHERE rg.campaign_id = :campaign_id
              AND cm.ended_at IS NULL
              AND rg.grantee_campaign_membership_id IS NOT NULL
              AND rg.revoked_at IS NULL
              AND (rg.expires_at IS NULL OR rg.expires_at > now())
              AND (rg.timeline_id IS NULL OR rg.timeline_id = :timeline_id)
            ORDER BY rg.granted_at, rg.resource_grant_id
        """),
        {"campaign_id": campaign_id, "timeline_id": timeline_id},
    ).mappings():
        target_column = next(column for column in _GRANT_TARGET_COLUMNS if row[column] is not None)
        target_type = target_column.removesuffix("_id")
        grants_by_membership.setdefault(row["grantee_campaign_membership_id"], []).append(
            MemberResourceGrantView(
                resource_grant_id=row["resource_grant_id"],
                capability_code=row["capability_code"],
                capability_display_name=row["capability_display_name"],
                effect=row["effect"],
                target_type=target_type,
                reason=row["reason"],
                granted_at=row["granted_at"],
                expires_at=row["expires_at"],
            )
        )

    return tuple(
        CampaignMemberView(
            campaign_membership_id=row["campaign_membership_id"],
            display_name=row["display_name"],
            status_code=row["status_code"],
            status_display_name=row["status_display_name"],
            joined_at=row["joined_at"],
            roles=tuple(roles_by_membership.get(row["campaign_membership_id"], [])),
            character_relationships=tuple(
                relationships_by_membership.get(row["campaign_membership_id"], [])
            ),
            grants=tuple(grants_by_membership.get(row["campaign_membership_id"], [])),
        )
        for row in member_rows
    )
