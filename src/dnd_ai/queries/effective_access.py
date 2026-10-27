"""Read-only per-member effective-access explanation (Phase 13E-B checkpoint
13, docs/UI_DESIGN.md §6.4 "Effective-access explanation" / §8.3).

`resolve_member_effective_access` answers "why can this person see what they
can see" for one campaign member: every capability the member currently
holds, each with the role assignments, character relationships, direct
resource grants, and access-group resource grants that contribute to it, plus
a separate list of the capabilities an active `deny` resource grant currently
overrides for a specific target (independent of whether the member also holds
that capability more broadly through a role or relationship — a `deny` only
ever narrows a *specific* target, never the capability as a whole, matching
`dnd_ai.domain.access.AccessContext.has_capability`'s own per-target
deny-overrides-allow-overrides-baseline resolution).

Applies the identical "currently true" filters `dnd_ai.domain.access.
resolve_access_context` and `dnd_ai.queries.access_overview` already use for
roles, character relationships, and resource grants (revoked_at IS NULL,
expiry, timeline scope, target/character/group currently active,
`cap.is_active`) — this explanation can never show a source that resolver
would not also currently authorize through. Every label is drawn from the
same audience-safe field set `dnd_ai.queries.access_overview` already
returns (role/relationship-type/capability display names, a resource-grant's
own free-text `reason`, an access group's `name`, and a character's
`canonical_name` as `target_display_name` — never a non-character target's
raw identity, matching that module's own "specific display identity of a
non-character resource-grant target...is a larger surface than this focused
read needs" note).

Pure read: no idempotency key, no `audit.change_log` row, no mutation, no
second session, and no request is ever authorized as the explained member —
the caller remains the only authenticated actor throughout, exactly as
`dnd_ai.queries.access_overview.get_campaign_access_overview` already is for
the same `access.manage` capability."""

import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, text

from dnd_ai.domain import access as _access

_GRANT_TARGET_COLUMNS = (
    "character_id",
    "entity_id",
    "knowledge_item_id",
    "quest_id",
    "session_id",
    "event_id",
)


@dataclass(frozen=True)
class EffectiveAccessSourceView:
    # One of "role" | "character_relationship" | "resource_grant" |
    # "access_group" — see this module's own docstring.
    kind: str
    label: str
    target_display_name: str | None = None


@dataclass(frozen=True)
class EffectiveAccessCapabilityView:
    code: str
    display_name: str
    sources: tuple[EffectiveAccessSourceView, ...]


@dataclass(frozen=True)
class EffectiveAccessDenialView:
    capability_code: str
    target_type: str
    target_display_name: str | None = None


@dataclass(frozen=True)
class MemberEffectiveAccessView:
    display_name: str
    capabilities: tuple[EffectiveAccessCapabilityView, ...]
    denials: tuple[EffectiveAccessDenialView, ...]


def resolve_member_effective_access(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    campaign_membership_id: uuid.UUID,
    timeline_id: uuid.UUID,
) -> MemberEffectiveAccessView | None:
    """Every capability `campaign_membership_id` currently holds in
    `campaign_id`, each with the sources that contribute to it, plus every
    capability an active `deny` resource grant currently overrides for a
    specific target. Returns `None` if `campaign_membership_id` does not
    belong to `campaign_id` or is not currently open (`ended_at IS NULL`) —
    `dnd_ai.api.effective_access` maps this to the same non-disclosing 404
    `require_campaign_capability` already gives for a missing/foreign
    membership, so a caller can never learn which case applied. `timeline_id`
    must already be the campaign's own pinned timeline (the caller's
    resolved `AccessContext.timeline_id`), matching every other
    timeline-scoped filter in this codebase."""
    member_row = (
        connection.execute(
            text("""
                SELECT u.display_name
                FROM security.campaign_memberships cm
                JOIN security.users u ON u.user_id = cm.user_id
                WHERE cm.campaign_membership_id = :membership_id
                  AND cm.campaign_id = :campaign_id
                  AND cm.ended_at IS NULL
            """),
            {"membership_id": campaign_membership_id, "campaign_id": campaign_id},
        )
        .mappings()
        .one_or_none()
    )
    if member_row is None:
        return None
    display_name = str(member_row["display_name"])

    capability_display_names: dict[str, str] = {}
    sources_by_capability: dict[str, list[EffectiveAccessSourceView]] = {}
    denials: list[EffectiveAccessDenialView] = []

    def _add_source(code: str, cap_display_name: str, source: EffectiveAccessSourceView) -> None:
        capability_display_names[code] = cap_display_name
        sources_by_capability.setdefault(code, []).append(source)

    for row in connection.execute(
        text("""
            SELECT cap.code, cap.display_name AS capability_display_name,
                   r.display_name AS role_display_name
            FROM security.membership_roles mr
            JOIN security.roles r ON r.role_id = mr.role_id
            JOIN security.role_capabilities rc ON rc.role_id = r.role_id
            JOIN security.capabilities cap ON cap.capability_id = rc.capability_id
            WHERE mr.campaign_membership_id = :membership_id
              AND mr.revoked_at IS NULL
              AND (mr.expires_at IS NULL OR mr.expires_at > now())
              AND r.is_active
              AND cap.is_active
            ORDER BY cap.code, r.sort_order, r.display_name
        """),
        {"membership_id": campaign_membership_id},
    ).mappings():
        _add_source(
            str(row["code"]),
            str(row["capability_display_name"]),
            EffectiveAccessSourceView(kind="role", label=str(row["role_display_name"])),
        )

    for row in connection.execute(
        text("""
            SELECT cap.code, cap.display_name AS capability_display_name,
                   rt.display_name AS relationship_type_display_name,
                   rt.code AS relationship_type_code,
                   e.canonical_name AS character_display_name
            FROM security.membership_character_relationships mcr
            JOIN security.character_relationship_type_capabilities rtc
              ON rtc.character_relationship_type_id = mcr.character_relationship_type_id
            JOIN security.capabilities cap ON cap.capability_id = rtc.capability_id
            JOIN security.character_relationship_types rt
              ON rt.character_relationship_type_id = mcr.character_relationship_type_id
            JOIN core.entities e ON e.entity_id = mcr.character_id
            JOIN core.lifecycle_statuses cls ON cls.lifecycle_status_id = e.lifecycle_status_id
            WHERE mcr.campaign_membership_id = :membership_id
              AND mcr.revoked_at IS NULL
              AND (mcr.expires_at IS NULL OR mcr.expires_at > now())
              AND mcr.effective_to_world_time_id IS NULL
              AND (mcr.timeline_id IS NULL OR mcr.timeline_id = :timeline_id)
              AND rt.is_active
              AND cap.is_active
              AND cls.code = 'active'
            ORDER BY cap.code, e.canonical_name
        """),
        {"membership_id": campaign_membership_id, "timeline_id": timeline_id},
    ).mappings():
        # Same conjunction as `resolve_access_context`: the panel must not show
        # a source the resolver would not honour.
        if not _access.relationship_capability_permitted(
            str(row["relationship_type_code"]), str(row["code"])
        ):
            continue
        _add_source(
            str(row["code"]),
            str(row["capability_display_name"]),
            EffectiveAccessSourceView(
                kind="character_relationship",
                label=str(row["relationship_type_display_name"]),
                target_display_name=str(row["character_display_name"]),
            ),
        )

    target_column_list = ", ".join(f"rg.{column}" for column in _GRANT_TARGET_COLUMNS)

    for row in connection.execute(
        text(f"""
            SELECT cap.code, cap.display_name AS capability_display_name, rg.effect, rg.reason,
                   target_entity.canonical_name AS target_entity_display_name,
                   {target_column_list}
            FROM security.resource_grants rg
            JOIN security.capabilities cap ON cap.capability_id = rg.capability_id
            LEFT JOIN core.entities target_entity
              ON target_entity.entity_id = COALESCE(
                     rg.character_id, rg.entity_id, rg.knowledge_item_id, rg.quest_id, rg.event_id
                 )
            LEFT JOIN core.lifecycle_statuses target_entity_status
              ON target_entity_status.lifecycle_status_id = target_entity.lifecycle_status_id
            LEFT JOIN campaign.sessions target_session ON target_session.session_id = rg.session_id
            LEFT JOIN core.lifecycle_statuses target_session_status
              ON target_session_status.lifecycle_status_id = target_session.lifecycle_status_id
            WHERE rg.campaign_id = :campaign_id
              AND rg.grantee_campaign_membership_id = :membership_id
              AND rg.revoked_at IS NULL
              AND (rg.expires_at IS NULL OR rg.expires_at > now())
              AND (rg.timeline_id IS NULL OR rg.timeline_id = :timeline_id)
              AND cap.is_active
              AND (
                    (rg.session_id IS NULL AND target_entity_status.code = 'active')
                    OR (rg.session_id IS NOT NULL AND target_session_status.code = 'active')
                  )
            ORDER BY rg.granted_at, rg.resource_grant_id
        """),
        {
            "campaign_id": campaign_id,
            "membership_id": campaign_membership_id,
            "timeline_id": timeline_id,
        },
    ).mappings():
        target_column = next(column for column in _GRANT_TARGET_COLUMNS if row[column] is not None)
        target_type = target_column.removesuffix("_id")
        target_display_name = (
            str(row["target_entity_display_name"]) if target_column == "character_id" else None
        )
        code = str(row["code"])
        capability_display_name = str(row["capability_display_name"])
        if row["effect"] == "allow":
            _add_source(
                code,
                capability_display_name,
                EffectiveAccessSourceView(
                    kind="resource_grant",
                    label=str(row["reason"]) if row["reason"] else "Direct resource grant",
                    target_display_name=target_display_name,
                ),
            )
        else:
            denials.append(
                EffectiveAccessDenialView(
                    capability_code=code,
                    target_type=target_type,
                    target_display_name=target_display_name,
                )
            )

    for row in connection.execute(
        text(f"""
            SELECT cap.code, cap.display_name AS capability_display_name, rg.effect, rg.reason,
                   ag.name AS access_group_name,
                   target_entity.canonical_name AS target_entity_display_name,
                   {target_column_list}
            FROM security.resource_grants rg
            JOIN security.capabilities cap ON cap.capability_id = rg.capability_id
            JOIN security.access_groups ag ON ag.access_group_id = rg.grantee_access_group_id
            JOIN core.lifecycle_statuses ag_status
              ON ag_status.lifecycle_status_id = ag.lifecycle_status_id
            LEFT JOIN core.entities target_entity
              ON target_entity.entity_id = COALESCE(
                     rg.character_id, rg.entity_id, rg.knowledge_item_id, rg.quest_id, rg.event_id
                 )
            LEFT JOIN core.lifecycle_statuses target_entity_status
              ON target_entity_status.lifecycle_status_id = target_entity.lifecycle_status_id
            LEFT JOIN campaign.sessions target_session ON target_session.session_id = rg.session_id
            LEFT JOIN core.lifecycle_statuses target_session_status
              ON target_session_status.lifecycle_status_id = target_session.lifecycle_status_id
            WHERE rg.campaign_id = :campaign_id
              AND ag_status.code = 'active'
              AND rg.grantee_access_group_id IN (
                  SELECT agm.access_group_id
                  FROM security.access_group_memberships agm
                  WHERE agm.campaign_membership_id = :membership_id
                    AND agm.removed_at IS NULL
              )
              AND rg.revoked_at IS NULL
              AND (rg.expires_at IS NULL OR rg.expires_at > now())
              AND (rg.timeline_id IS NULL OR rg.timeline_id = :timeline_id)
              AND cap.is_active
              AND (
                    (rg.session_id IS NULL AND target_entity_status.code = 'active')
                    OR (rg.session_id IS NOT NULL AND target_session_status.code = 'active')
                  )
            ORDER BY rg.granted_at, rg.resource_grant_id
        """),
        {
            "campaign_id": campaign_id,
            "membership_id": campaign_membership_id,
            "timeline_id": timeline_id,
        },
    ).mappings():
        target_column = next(column for column in _GRANT_TARGET_COLUMNS if row[column] is not None)
        target_type = target_column.removesuffix("_id")
        target_display_name = (
            str(row["target_entity_display_name"]) if target_column == "character_id" else None
        )
        code = str(row["code"])
        capability_display_name = str(row["capability_display_name"])
        if row["effect"] == "allow":
            _add_source(
                code,
                capability_display_name,
                EffectiveAccessSourceView(
                    kind="access_group",
                    label=str(row["access_group_name"]),
                    target_display_name=target_display_name,
                ),
            )
        else:
            denials.append(
                EffectiveAccessDenialView(
                    capability_code=code,
                    target_type=target_type,
                    target_display_name=target_display_name,
                )
            )

    capabilities = tuple(
        EffectiveAccessCapabilityView(
            code=code,
            display_name=capability_display_names[code],
            sources=tuple(sources_by_capability[code]),
        )
        for code in sorted(sources_by_capability)
    )
    denials_sorted = tuple(
        sorted(
            denials,
            key=lambda denial: (
                denial.capability_code,
                denial.target_type,
                denial.target_display_name or "",
            ),
        )
    )

    return MemberEffectiveAccessView(
        display_name=display_name, capabilities=capabilities, denials=denials_sorted
    )
