"""The current control and history of one character (P15-C11-S02-T01, `GET .../control-assignments`).

One read for the holders of `character.assign_control` (the built-in owner and `gm`, and a delegated assistant GM).

**One statement, one snapshot** (plan section 3.1, "Read"; correction S02-R1). `read_character_control` runs exactly one
SQL statement, with no row lock. It embeds the authority statement `read_authority_snapshot` would run
(`build_authority_statement`, with the assign-control component) as its first CTE, and beside it, in the same statement:

- the effective campaign clock (`CAMPAIGN_CLOCK_CTE`, the very CTE the authority statement uses) and the clock's
  display point (`clock_point`: the same timeline chain carrying the world-time id, so the display row is read too);
- every assignment row of the character in the campaign, newest first, with each row's in-effect test
  (`control_assignments_in_effect_from_sql`, the very fragment the resolver uses) and its period's display rows.

The history is produced only when the statement's own authority source is a holder's, so it never leaves the database
for a caller that statement refused. The route judges the refusals from the same row, in the route's order (the campaign
gate's 404 and 403, then the fixed 403 `character_assign_control_required`), so the decision, the clock, the statuses
and the history are always one MVCC snapshot. A revocation or clock change committed before the statement is seen by all
of them; one committed after it does not change a response the statement already produced (statement coherence, not
commit-time serialization).

Status vocabulary: `in_effect`, `upcoming` (a dated row before its start), `ended` (a dated row at or after its end, or
a row whose type or character is no longer eligible), `undetermined` (a dated row and no clock), `revoked`. An ongoing
row reads "ongoing since" its grant instant and never carries a fictional date.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Connection, RowMapping, text

from dnd_ai.domain.access import (
    CAMPAIGN_CLOCK_CTE,
    AuthoritySnapshot,
    build_authority_statement,
    control_assignments_in_effect_from_sql,
)
from dnd_ai.domain.world_time import full_display_text

HISTORY_LIMIT = 200
_HOLDER_SOURCES = ("campaign_owner", "gm", "delegation")

# The effective clock's world-time point: the same chain and the same rule as `CAMPAIGN_CLOCK_CTE` (and the Python
# `resolve_effective_clock`): the timeline's own clock row, else the parent's effective clock bounded at the branch
# point, else none. It carries the world-time id so the display row is read in this statement; `key` must equal
# `campaign_clock.key` (checked on every read).
_CLOCK_POINT_CTE = """
    clock_point AS (
        WITH RECURSIVE pchain AS (
            SELECT t.timeline_id AS tl, t.parent_timeline_id AS parent,
                   t.branch_world_time_id AS branch_wt,
                   (SELECT wt.sort_key FROM core.world_times wt
                     WHERE wt.world_time_id = t.branch_world_time_id) AS branch_key,
                   tc.current_world_time_id AS own_wt,
                   (SELECT wt.sort_key FROM core.world_times wt
                     WHERE wt.world_time_id = tc.current_world_time_id) AS own_key
            FROM campaign.timelines t
            LEFT JOIN campaign.timeline_clocks tc ON tc.timeline_id = t.timeline_id
            WHERE t.timeline_id = (SELECT timeline_id FROM camp)
          UNION ALL
            SELECT t.timeline_id, t.parent_timeline_id, t.branch_world_time_id,
                   (SELECT wt.sort_key FROM core.world_times wt
                     WHERE wt.world_time_id = t.branch_world_time_id),
                   tc.current_world_time_id,
                   (SELECT wt.sort_key FROM core.world_times wt
                     WHERE wt.world_time_id = tc.current_world_time_id)
            FROM pchain c
            JOIN campaign.timelines t ON t.timeline_id = c.parent
            LEFT JOIN campaign.timeline_clocks tc ON tc.timeline_id = t.timeline_id
        ), peff AS (
            SELECT c.tl, c.own_key AS key, c.own_wt AS wt FROM pchain c WHERE c.parent IS NULL
          UNION ALL
            SELECT c.tl,
                   CASE WHEN c.own_wt IS NOT NULL THEN c.own_key
                        WHEN e.key IS NULL OR e.key > c.branch_key THEN c.branch_key
                        ELSE e.key END,
                   CASE WHEN c.own_wt IS NOT NULL THEN c.own_wt
                        WHEN e.key IS NULL OR e.key > c.branch_key THEN c.branch_wt
                        ELSE e.wt END
            FROM pchain c JOIN peff e ON e.tl = c.parent
        )
        SELECT CAST(key AS bigint) AS key, wt FROM peff WHERE tl = (SELECT timeline_id FROM camp)
    )
"""


def _display_columns(prefix: str, alias: str) -> str:
    """The world-time display fields of `alias` (a `core.world_times` row), prefixed, as `clock_display` reads them."""
    return f"""
           {alias}.world_time_id AS {prefix}_id,
           {alias}.label AS {prefix}_label, {alias}.year AS {prefix}_year, {alias}.day AS {prefix}_day,
           {alias}.hour AS {prefix}_hour, {alias}.minute AS {prefix}_minute,
           {alias}.calendar_id AS {prefix}_calendar_id, {alias}_cal.display_name AS {prefix}_calendar_name,
           {alias}_mon.name AS {prefix}_month_name, {alias}_cal.epoch_label AS {prefix}_epoch_label"""


def _display_joins(alias: str, world_time: str) -> str:
    return f"""
    LEFT JOIN core.world_times {alias} ON {alias}.world_time_id = {world_time}
    LEFT JOIN core.calendars {alias}_cal ON {alias}_cal.calendar_id = {alias}.calendar_id
    LEFT JOIN core.calendar_months {alias}_mon
      ON {alias}_mon.calendar_id = {alias}.calendar_id AND {alias}_mon.month_number = {alias}.month_number"""


def _read_sql(authority_sql: str) -> str:
    holders = ", ".join(f"'{source}'" for source in _HOLDER_SOURCES)
    return f"""
    WITH auth AS MATERIALIZED (
{authority_sql}
    ),
    camp AS (
        SELECT c.timeline_id FROM campaign.campaigns c WHERE c.campaign_id = :campaign_id
    ),
    {CAMPAIGN_CLOCK_CTE.strip()},
    {_CLOCK_POINT_CTE.strip()},
    history AS (
        SELECT h.membership_character_relationship_id AS h_control_assignment_id,
               crt.code AS h_role,
               h.assignment_period_kind AS h_kind,
               h.campaign_membership_id AS h_campaign_membership_id,
               mu.display_name AS h_display_name,
               h.granted_at AS h_granted_at,
               gu.display_name AS h_granted_by,
               lower(h.effective_period) AS h_from_key,
               upper(h.effective_period) AS h_to_key,
               h.revoked_at AS h_revoked_at,
               ru.display_name AS h_revoked_by,
               h.revocation_reason AS h_revocation_reason,
               h.notes AS h_notes,
               h.membership_character_relationship_id IN (
                   SELECT mcr.membership_character_relationship_id
                   {control_assignments_in_effect_from_sql("h.campaign_membership_id")}
               ) AS h_in_effect,
               {_display_columns("hf", "hf")},
               {_display_columns("ht", "ht")}
        FROM security.membership_character_relationships h
        JOIN security.character_relationship_types crt
          ON crt.character_relationship_type_id = h.character_relationship_type_id
        JOIN security.campaign_memberships hm ON hm.campaign_membership_id = h.campaign_membership_id
        JOIN security.users mu ON mu.user_id = hm.user_id
        LEFT JOIN security.campaign_memberships gm ON gm.campaign_membership_id = h.granted_by_membership_id
        LEFT JOIN security.users gu ON gu.user_id = gm.user_id
        LEFT JOIN security.campaign_memberships rm ON rm.campaign_membership_id = h.revoked_by_membership_id
        LEFT JOIN security.users ru ON ru.user_id = rm.user_id
        {_display_joins("hf", "h.effective_from_world_time_id")}
        {_display_joins("ht", "h.effective_to_world_time_id")}
        WHERE h.campaign_id = :campaign_id
          AND h.character_id = :character_id
          AND h.is_control_assignment
          AND (SELECT assign_control_source FROM auth) IN ({holders})
        ORDER BY h.granted_at DESC, h.membership_character_relationship_id DESC
        LIMIT :history_limit
    ),
    point AS (
        SELECT cp.key AS clock_point_key, {_display_columns("clock", "cw")}
        FROM (SELECT 1) AS one
        LEFT JOIN clock_point cp ON TRUE
        {_display_joins("cw", "cp.wt")}
    )
    SELECT auth.*,
           (SELECT key FROM campaign_clock) AS read_clock_key,
           point.*,
           history.*
    FROM auth
    CROSS JOIN point
    LEFT JOIN history ON TRUE
    ORDER BY history.h_granted_at DESC NULLS LAST, history.h_control_assignment_id DESC NULLS LAST
"""  # noqa: S608 - every interpolated fragment is a module constant or built from module constants


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


@dataclass(frozen=True)
class ControlRead:
    """The read's one statement: the authority snapshot it judged and the control state it read with it. `control` is
    `None` when that snapshot's assign-control source is not a holder's (the statement then read no history)."""

    snapshot: AuthoritySnapshot
    control: CharacterControl | None


def _display(row: RowMapping, prefix: str) -> str | None:
    if row[f"{prefix}_id"] is None:
        return None
    return (
        full_display_text(
            label=row[f"{prefix}_label"],
            calendar_name=row[f"{prefix}_calendar_name"],
            has_calendar=row[f"{prefix}_calendar_id"] is not None,
            year=row[f"{prefix}_year"],
            month_name=row[f"{prefix}_month_name"],
            day=row[f"{prefix}_day"],
            hour=row[f"{prefix}_hour"],
            minute=row[f"{prefix}_minute"],
            epoch_label=row[f"{prefix}_epoch_label"],
        )
        or "Unplaced time"
    )


def _status(row: Any, clock_key: int | None) -> str:
    if row["h_revoked_at"] is not None:
        return "revoked"
    if row["h_in_effect"]:
        return "in_effect"
    if row["h_kind"] == "dated":
        if clock_key is None:
            return "undetermined"
        if clock_key < row["h_from_key"]:
            return "upcoming"
    return "ended"


def read_character_control(
    connection: Connection,
    *,
    user_id: uuid.UUID,
    campaign_id: uuid.UUID,
    character_id: uuid.UUID,
) -> ControlRead:
    """Run the read's one statement and return its snapshot and, for a holder, the character's control state."""
    statement = build_authority_statement(
        user_id=user_id, campaign_id=campaign_id, with_assign_control=True
    )
    parameters = {
        **statement.parameters,
        "character_id": character_id,
        "history_limit": HISTORY_LIMIT + 1,
    }
    rows = connection.execute(text(_read_sql(statement.sql)), parameters).mappings().all()
    first = rows[0]
    snapshot = statement.snapshot(first)
    clock_key = first["read_clock_key"]
    if first["clock_point_key"] != clock_key or (
        snapshot.access is not None and snapshot.access.control_clock_key != clock_key
    ):
        raise RuntimeError(
            "the read's clock point, its campaign clock and the authority statement's clock disagree"
        )
    if snapshot.assign_control_authority not in _HOLDER_SOURCES:
        return ControlRead(snapshot=snapshot, control=None)

    history = [row for row in rows if row["h_control_assignment_id"] is not None]
    truncated = len(history) > HISTORY_LIMIT
    history = history[:HISTORY_LIMIT]
    assignments: list[ControlAssignmentRow] = []
    controller: ControlHolder | None = None
    co_controllers: list[ControlHolder] = []
    for row in history:
        status = _status(row, clock_key)
        holder = ControlHolder(
            row["h_campaign_membership_id"], str(row["h_display_name"]), str(row["h_kind"])
        )
        if status == "in_effect":
            if row["h_role"] == "primary_controller":
                controller = holder
            else:
                co_controllers.append(holder)
        dated = row["h_kind"] == "dated"
        assignments.append(
            ControlAssignmentRow(
                control_assignment_id=row["h_control_assignment_id"],
                role=str(row["h_role"]),
                kind=str(row["h_kind"]),
                campaign_membership_id=row["h_campaign_membership_id"],
                display_name=str(row["h_display_name"]),
                status=status,
                granted_at=row["h_granted_at"],
                granted_by=row["h_granted_by"],
                ongoing_since=None if dated else row["h_granted_at"],
                effective_from=_display(row, "hf") if dated else None,
                effective_to=_display(row, "ht") if dated else None,
                revoked_at=row["h_revoked_at"],
                revoked_by=row["h_revoked_by"],
                revocation_reason=row["h_revocation_reason"],
                reason=row["h_notes"],
            )
        )
    return ControlRead(
        snapshot=snapshot,
        control=CharacterControl(
            controller=controller,
            co_controllers=co_controllers,
            gm_operated=controller is None and not co_controllers,
            clock_set=clock_key is not None,
            clock_display=_display(first, "clock"),
            assignments=assignments,
            truncated=truncated,
        ),
    )
