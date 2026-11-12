"""The pre-R01-S1 multi-statement `resolve_access_context`, kept verbatim as a test reference.

R01 slice S1 replaced the production function with one single-statement reader
(`dnd_ai.domain.access.read_authority_snapshot`). The plan (section 3, "One source of truth")
removes the old implementation only after a differential test passes, so this frozen copy is what
`tests/database/test_access_snapshot_differential.py` compares the new reader against. It is the
function exactly as it stood at 825f0ce, with ONE change: `now()` became
`COALESCE(CAST(:as_of AS timestamptz), now())`, so a comparison can be made at a fixed instant. It
is test-only and is never imported by production code.
"""

import uuid
from datetime import datetime

from sqlalchemy import Connection, text

from dnd_ai.domain.access import (
    _TARGET_COLUMNS,
    LIVE_REVELATIONS_FOR_MEMBERSHIP_SQL,
    AccessContext,
    RevelationSource,
    UnauthorizedTimelineError,
    _as_str,
    _as_uuid,
    _GrantKey,
    relationship_capability_permitted,
)


def reference_resolve_access_context(
    connection: Connection,
    *,
    user_id: uuid.UUID,
    campaign_id: uuid.UUID,
    timeline_id: uuid.UUID | None = None,
    as_of: datetime | None = None,
) -> AccessContext | None:
    """The old multi-statement resolver (see the module docstring)."""
    membership_id = connection.execute(
        text("""
            SELECT cm.campaign_membership_id
            FROM security.campaign_memberships cm
            JOIN security.membership_statuses ms
              ON ms.membership_status_id = cm.membership_status_id
            WHERE cm.campaign_id = :campaign_id
              AND cm.user_id = :user_id
              AND cm.ended_at IS NULL
              AND ms.code = 'active'
              AND ms.is_active
        """),
        {"campaign_id": campaign_id, "user_id": user_id},
    ).scalar()
    if membership_id is None:
        return None
    membership_id = _as_uuid(membership_id)

    campaign_row = connection.execute(
        text("""
            SELECT c.timeline_id, ls.code AS lifecycle_code
            FROM campaign.campaigns c
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = c.lifecycle_status_id
            WHERE c.campaign_id = :campaign_id
        """),
        {"campaign_id": campaign_id},
    ).one_or_none()
    if campaign_row is None:
        raise ValueError(f"campaign {campaign_id} does not exist")
    campaign_timeline_id = _as_uuid(campaign_row.timeline_id)
    campaign_lifecycle_status = _as_str(campaign_row.lifecycle_code)

    if timeline_id is not None and timeline_id != campaign_timeline_id:
        raise UnauthorizedTimelineError(
            f"timeline {timeline_id} is not campaign {campaign_id}'s own timeline "
            f"({campaign_timeline_id}) — resolve_access_context only resolves access "
            "for a campaign's own pinned timeline; see its docstring for the rule."
        )

    role_capabilities = frozenset(
        _as_str(code)
        for code in connection.execute(
            text("""
                SELECT DISTINCT cap.code
                FROM security.membership_roles mr
                JOIN security.roles r ON r.role_id = mr.role_id
                JOIN security.role_capabilities rc ON rc.role_id = r.role_id
                JOIN security.capabilities cap ON cap.capability_id = rc.capability_id
                WHERE mr.campaign_membership_id = :membership_id
                  AND mr.revoked_at IS NULL
                  AND (mr.expires_at IS NULL OR mr.expires_at > COALESCE(CAST(:as_of AS timestamptz), now()))
                  AND r.is_active
                  AND cap.is_active
            """),
            {"membership_id": membership_id, "as_of": as_of},
        ).scalars()
    )

    character_capabilities: dict[uuid.UUID, set[str]] = {}
    for row in connection.execute(
        text("""
            SELECT mcr.character_id, cap.code, crt.code AS type_code
            FROM security.membership_character_relationships mcr
            JOIN security.character_relationship_types crt
              ON crt.character_relationship_type_id = mcr.character_relationship_type_id
            JOIN security.character_relationship_type_capabilities rtc
              ON rtc.character_relationship_type_id = mcr.character_relationship_type_id
            JOIN security.capabilities cap ON cap.capability_id = rtc.capability_id
            JOIN core.entities e ON e.entity_id = mcr.character_id
            JOIN core.lifecycle_statuses cls ON cls.lifecycle_status_id = e.lifecycle_status_id
            JOIN core.canon_statuses ccs ON ccs.canon_status_id = e.canon_status_id
            WHERE mcr.campaign_membership_id = :membership_id
              AND mcr.revoked_at IS NULL
              AND (mcr.expires_at IS NULL OR mcr.expires_at > COALESCE(CAST(:as_of AS timestamptz), now()))
              AND mcr.effective_to_world_time_id IS NULL
              AND (mcr.timeline_id IS NULL OR mcr.timeline_id = :timeline_id)
              AND crt.is_active
              AND cap.is_active
              AND cls.code = 'active'
              -- A draft or unpublished character confers no perspective (Phase 15.2B-1).
              AND ccs.code = 'canon'
        """),
        {"membership_id": membership_id, "timeline_id": campaign_timeline_id, "as_of": as_of},
    ).mappings():
        # A database mapping is effective only if the code-defined matrix also
        # permits it (default deny for unknown/custom types and stray rows).
        if not relationship_capability_permitted(_as_str(row["type_code"]), _as_str(row["code"])):
            continue
        character_id = _as_uuid(row["character_id"])
        character_capabilities.setdefault(character_id, set()).add(_as_str(row["code"]))

    grant_effects: dict[_GrantKey, dict[str, str]] = {}
    target_column_list = ", ".join(f"rg.{column}" for column in _TARGET_COLUMNS)
    for row in connection.execute(
        text(f"""
            SELECT {target_column_list}, cap.code AS capability_code, rg.effect
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
              AND rg.revoked_at IS NULL
              AND (rg.expires_at IS NULL OR rg.expires_at > COALESCE(CAST(:as_of AS timestamptz), now()))
              AND (rg.timeline_id IS NULL OR rg.timeline_id = :timeline_id)
              AND cap.is_active
              AND (
                    (rg.session_id IS NULL AND target_entity_status.code = 'active')
                    OR (rg.session_id IS NOT NULL AND target_session_status.code = 'active')
                  )
              AND (
                    rg.grantee_campaign_membership_id = :membership_id
                    OR rg.grantee_access_group_id IN (
                        SELECT agm.access_group_id
                        FROM security.access_group_memberships agm
                        JOIN security.access_groups ag
                            ON ag.access_group_id = agm.access_group_id
                        JOIN core.lifecycle_statuses ag_status
                            ON ag_status.lifecycle_status_id = ag.lifecycle_status_id
                        WHERE agm.campaign_membership_id = :membership_id
                          AND agm.removed_at IS NULL
                          AND ag_status.code = 'active'
                    )
                  )
        """),
        {
            "campaign_id": campaign_id,
            "timeline_id": campaign_timeline_id,
            "membership_id": membership_id,
            "as_of": as_of,
        },
    ).mappings():
        target_field = next(column for column in _TARGET_COLUMNS if row[column] is not None)
        key = (target_field, _as_uuid(row[target_field]))
        capability_code = _as_str(row["capability_code"])
        bucket = grant_effects.setdefault(key, {})
        if bucket.get(capability_code) == "deny":
            continue
        bucket[capability_code] = _as_str(row["effect"])

    revelations: dict[uuid.UUID, set[RevelationSource]] = {}
    for revelation_row in connection.execute(
        text(LIVE_REVELATIONS_FOR_MEMBERSHIP_SQL),
        {"campaign_id": campaign_id, "membership_id": membership_id},
    ).mappings():
        revelations.setdefault(_as_uuid(revelation_row["character_id"]), set()).add(
            RevelationSource(
                character_revelation_id=_as_uuid(revelation_row["character_revelation_id"]),
                audience_kind=_as_str(revelation_row["audience_kind"]),
            )
        )

    return AccessContext(
        user_id=user_id,
        campaign_id=campaign_id,
        campaign_membership_id=membership_id,
        timeline_id=campaign_timeline_id,
        role_capabilities=role_capabilities,
        character_capabilities={
            character_id: frozenset(codes) for character_id, codes in character_capabilities.items()
        },
        grant_effects=grant_effects,
        campaign_lifecycle_status=campaign_lifecycle_status,
        revelations={
            character_id: frozenset(sources) for character_id, sources in revelations.items()
        },
    )
