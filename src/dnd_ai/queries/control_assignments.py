"""The current control and history of one character (P15-C11-S02-T01, `GET .../control-assignments`).

One read for the holders of `character.assign_control` (the built-in owner and `gm`). The caller's authority is judged
first, before any character lookup, so the refusal is one fixed 403 for an existing and a missing character.

The history is **one statement**: the effective campaign clock (`CAMPAIGN_CLOCK_CTE`, the very CTE the authority
statement uses) and every row's in-effect test (`control_assignments_in_effect_from_sql`, the very fragment the
resolver uses) are read in the same snapshot, so the panel can never show an assignment the resolver would not honour.
Status vocabulary: `in_effect`, `upcoming` (a dated row before its start), `ended` (a dated row at or after its end, or
a row whose type or character is no longer eligible), `undetermined` (a dated row and no clock), `revoked`. An ongoing
row reads "ongoing since" its grant instant and never carries a fictional date.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Connection, text

from dnd_ai.domain.access import (
    CAMPAIGN_CLOCK_CTE,
    control_assignments_in_effect_from_sql,
)
from dnd_ai.queries.campaign_clock import clock_display
from dnd_ai.queries.party_membership_period import MembershipClock

HISTORY_LIMIT = 200

_HISTORY_SQL = f"""
    WITH camp AS (
        SELECT c.timeline_id FROM campaign.campaigns c WHERE c.campaign_id = :campaign_id
    ),
    {CAMPAIGN_CLOCK_CTE.strip()}
    SELECT h.membership_character_relationship_id AS control_assignment_id,
           crt.code AS role,
           h.assignment_period_kind AS kind,
           h.campaign_membership_id,
           mu.display_name AS display_name,
           h.granted_at,
           gu.display_name AS granted_by,
           h.effective_from_world_time_id,
           h.effective_to_world_time_id,
           lower(h.effective_period) AS from_key,
           upper(h.effective_period) AS to_key,
           h.revoked_at,
           ru.display_name AS revoked_by,
           h.revocation_reason,
           h.notes,
           (SELECT key FROM campaign_clock) AS clock_key,
           h.membership_character_relationship_id IN (
               SELECT mcr.membership_character_relationship_id
               {control_assignments_in_effect_from_sql("h.campaign_membership_id")}
           ) AS in_effect
    FROM security.membership_character_relationships h
    JOIN security.character_relationship_types crt
      ON crt.character_relationship_type_id = h.character_relationship_type_id
    JOIN security.campaign_memberships hm ON hm.campaign_membership_id = h.campaign_membership_id
    JOIN security.users mu ON mu.user_id = hm.user_id
    LEFT JOIN security.campaign_memberships gm ON gm.campaign_membership_id = h.granted_by_membership_id
    LEFT JOIN security.users gu ON gu.user_id = gm.user_id
    LEFT JOIN security.campaign_memberships rm ON rm.campaign_membership_id = h.revoked_by_membership_id
    LEFT JOIN security.users ru ON ru.user_id = rm.user_id
    WHERE h.campaign_id = :campaign_id
      AND h.character_id = :character_id
      AND h.is_control_assignment
    ORDER BY h.granted_at DESC, h.membership_character_relationship_id DESC
    LIMIT :limit
"""  # noqa: S608 - the interpolated fragments are module constants


@dataclass(frozen=True)
class ControlHolder:
    campaign_membership_id: uuid.UUID
    display_name: str
    kind: str


@dataclass(frozen=True)
class ControlAssignmentRow:
    control_assignment_id: uuid.UUID
    role: str
    kind: str
    campaign_membership_id: uuid.UUID
    display_name: str
    status: str
    granted_at: datetime
    granted_by: str | None
    ongoing_since: datetime | None
    effective_from: str | None
    effective_to: str | None
    revoked_at: datetime | None
    revoked_by: str | None
    revocation_reason: str | None
    reason: str | None


@dataclass(frozen=True)
class CharacterControl:
    controller: ControlHolder | None
    co_controllers: list[ControlHolder]
    gm_operated: bool
    clock_set: bool
    clock_display: str | None
    assignments: list[ControlAssignmentRow]
    truncated: bool


def _status(row: Any) -> str:
    if row["revoked_at"] is not None:
        return "revoked"
    if row["in_effect"]:
        return "in_effect"
    if row["kind"] == "dated":
        key = row["clock_key"]
        if key is None:
            return "undetermined"
        if key < row["from_key"]:
            return "upcoming"
    return "ended"


def get_character_control(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    character_id: uuid.UUID,
    clock: MembershipClock,
) -> CharacterControl:
    rows = (
        connection.execute(
            text(_HISTORY_SQL),
            {"campaign_id": campaign_id, "character_id": character_id, "limit": HISTORY_LIMIT + 1},
        )
        .mappings()
        .all()
    )
    truncated = len(rows) > HISTORY_LIMIT
    rows = rows[:HISTORY_LIMIT]
    assignments: list[ControlAssignmentRow] = []
    controller: ControlHolder | None = None
    co_controllers: list[ControlHolder] = []
    for row in rows:
        status = _status(row)
        holder = ControlHolder(
            row["campaign_membership_id"], str(row["display_name"]), str(row["kind"])
        )
        if status == "in_effect":
            if row["role"] == "primary_controller":
                controller = holder
            else:
                co_controllers.append(holder)
        dated = row["kind"] == "dated"
        assignments.append(
            ControlAssignmentRow(
                control_assignment_id=row["control_assignment_id"],
                role=str(row["role"]),
                kind=str(row["kind"]),
                campaign_membership_id=row["campaign_membership_id"],
                display_name=str(row["display_name"]),
                status=status,
                granted_at=row["granted_at"],
                granted_by=row["granted_by"],
                ongoing_since=None if dated else row["granted_at"],
                effective_from=(
                    clock_display(connection, row["effective_from_world_time_id"])
                    if dated and row["effective_from_world_time_id"] is not None
                    else None
                ),
                effective_to=(
                    clock_display(connection, row["effective_to_world_time_id"])
                    if dated and row["effective_to_world_time_id"] is not None
                    else None
                ),
                revoked_at=row["revoked_at"],
                revoked_by=row["revoked_by"],
                revocation_reason=row["revocation_reason"],
                reason=row["notes"],
            )
        )
    return CharacterControl(
        controller=controller,
        co_controllers=co_controllers,
        gm_operated=controller is None and not co_controllers,
        clock_set=clock.is_set,
        clock_display=clock.display,
        assignments=assignments,
        truncated=truncated,
    )
