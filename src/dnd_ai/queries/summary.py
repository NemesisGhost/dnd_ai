"""Campaign/session summary query (docs/PLAN.md Phase 10 deliverable
"deterministic, audience-filtered summary and detail query services for
current campaign/session state, active quests, recent events, locations,
characters, NPCs/factions, inventory, knowledge, and the prior-session
recap"; docs/PLAN.md §25 step 15).

Scope: this first cut covers three of that list's items — current session
state, recent events, and the prior-session recap — the pieces with no
existing dedicated query yet. Active quests, locations, characters,
NPCs/factions, inventory, and knowledge are deliberately *not*
re-aggregated here: `dnd_ai.queries.quest`/`.character`/`.inventory`/
`.knowledge` already serve each of those with their own, already-tested
audience-filtering rules (workstreams 12-18), and duplicating that logic
into one "mega-query" would either drift from those rules or reimplement
them a second time for no benefit. A client assembling a full dashboard
composes this endpoint with those, the same way a web page issues several
requests rather than one endpoint owning every screen.

Audience filtering: `narrative.events.event_status_id` (`draft`/
`recorded`/`voided`/`corrected`) is the one piece of this summary with a
schema-grounded, non-invented audience split — a `draft` event is not yet
finalized (§12: "a recorded (non-draft) event is immutable"), so a non-GM
caller (`include_draft_events=False`) never sees one, the same "fetch
nothing rather than fetch-and-withhold" discipline every other query
module in this package follows for its own GM-only content. `voided`
events are excluded for *every* caller, GM included — a retracted event is
not "what happened" anymore, so it does not belong in a "recent events"
read regardless of audience. Session state and the prior-session recap
carry no such split in this schema and are returned identically to any
`campaign.view` caller.

This module is framework-free and performs no authorization of its own:
`include_draft_events` must already be an authorized decision (a resolved
`canon.edit` capability check) by the time it reaches here.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Connection, text

# A fixed, deterministic bound rather than a client-tunable parameter —
# pagination is a separate concern this first cut does not need.
_RECENT_EVENTS_LIMIT = 20


@dataclass(frozen=True)
class SessionSummaryView:
    session_id: uuid.UUID
    session_number: int
    title: str | None
    status_code: str
    started_at: datetime | None
    ended_at: datetime | None


@dataclass(frozen=True)
class RecentEventView:
    event_id: uuid.UUID
    name: str
    summary: str | None
    event_type_code: str
    event_status_code: str
    world_time_id: uuid.UUID
    details: str | None


@dataclass(frozen=True)
class CampaignSummaryView:
    current_session: SessionSummaryView | None
    previous_session_recap: str | None
    recent_events: tuple[RecentEventView, ...]


def get_campaign_summary_view(
    connection: Connection, *, campaign_id: uuid.UUID, include_draft_events: bool
) -> CampaignSummaryView:
    """The current session, the most recently completed session's own
    recap text, and up to the most recent `_RECENT_EVENTS_LIMIT` events
    for `campaign_id`. `campaign_id` is trusted as already authorized
    (`require_campaign_capability`) — unlike every world-scoped query in
    this package, no existence/cross-world check is needed here: a
    campaign that resolved access at all already exists, and every table
    this function reads is scoped by `campaign_id` directly."""
    current_session_row = (
        connection.execute(
            text("""
                SELECT s.session_id, s.session_number, s.title, ls.code AS status_code,
                       s.started_at, s.ended_at
                FROM campaign.sessions s
                JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = s.lifecycle_status_id
                WHERE s.campaign_id = :campaign
                ORDER BY s.session_number DESC
                LIMIT 1
            """),
            {"campaign": campaign_id},
        )
        .mappings()
        .one_or_none()
    )
    current_session = (
        None
        if current_session_row is None
        else SessionSummaryView(
            session_id=current_session_row["session_id"],
            session_number=current_session_row["session_number"],
            title=current_session_row["title"],
            status_code=current_session_row["status_code"],
            started_at=current_session_row["started_at"],
            ended_at=current_session_row["ended_at"],
        )
    )

    previous_session_recap = connection.execute(
        text("""
            SELECT summary FROM campaign.sessions
            WHERE campaign_id = :campaign AND ended_at IS NOT NULL
            ORDER BY session_number DESC
            LIMIT 1
        """),
        {"campaign": campaign_id},
    ).scalar()

    event_rows = connection.execute(
        text("""
            SELECT e.event_id, ce.canonical_name AS name, ce.summary, et.code AS event_type_code,
                   es.code AS event_status_code, e.world_time_id, e.details
            FROM narrative.events e
            JOIN core.entities ce ON ce.entity_id = e.event_id
            JOIN narrative.event_types et ON et.event_type_id = e.event_type_id
            JOIN narrative.event_statuses es ON es.event_status_id = e.event_status_id
            JOIN core.world_times wt ON wt.world_time_id = e.world_time_id
            WHERE e.campaign_id = :campaign
              AND es.code != 'voided'
              AND (:include_draft OR es.code != 'draft')
            ORDER BY wt.sort_key DESC, e.created_at DESC
            LIMIT :event_limit
        """),
        {
            "campaign": campaign_id,
            "include_draft": include_draft_events,
            "event_limit": _RECENT_EVENTS_LIMIT,
        },
    ).mappings()
    recent_events = tuple(
        RecentEventView(
            event_id=row["event_id"],
            name=row["name"],
            summary=row["summary"],
            event_type_code=row["event_type_code"],
            event_status_code=row["event_status_code"],
            world_time_id=row["world_time_id"],
            details=row["details"],
        )
        for row in event_rows
    )

    return CampaignSummaryView(
        current_session=current_session,
        previous_session_recap=previous_session_recap,
        recent_events=recent_events,
    )
