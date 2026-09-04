"""Audience-filtered session list/detail query.

Phase 13D backend-readiness gap: `dnd_ai.api.sessions` previously exposed
only `end_session` (a GM write) — there was no read side at all, so the
portal's Session detail screen (docs/UI_DESIGN.md §5.8) had no endpoint to
call. `dnd_ai.domain.access._TARGET_COLUMNS` already names `session_id` as
a resource-grant target column (alongside `quest_id`/`event_id`/etc.), so
the authorization machinery for a per-session grant already existed; only
the query and route were missing. This module is the query half.

`campaign.sessions` carries `campaign_id` directly (unlike the world-scoped
quest/character/dungeon/knowledge domains), so no world/timeline
cross-check is needed here — a session that resolves against the caller's
own `campaign_id` is already known to belong to that campaign.

Audience filtering: a session's own fields (`session_number`, `title`,
`status_code`, timing, `summary`) carry no GM/player split in this schema —
`dnd_ai.queries.summary`'s own docstring already establishes this ("Session
state and the prior-session recap carry no such split... returned
identically to any `campaign.view` caller"). The one split this module
does apply is per-session-grant visibility (`denied_session_ids`, resolved
by the caller from `AccessContext.resource_grant_targets("campaign.view",
field_name="session_id")` or a direct `has_capability(..., session_id=...)`
check) — a GM can hide one specific session (e.g. a session recap the GM
is not ready to reveal) from members who otherwise hold campaign-wide
`campaign.view`, the same "deny overrides an allow/baseline" precedence
every other resource-grant check in this codebase already applies.

A session's linked events reuse `dnd_ai.queries.summary.
get_campaign_summary_view`'s own draft/voided event-visibility rule
verbatim (same columns, same `include_draft_events`/
`denied_draft_event_ids`/`allowed_draft_event_ids` contract) rather than
inventing a second one — see that module's docstring for the full
rationale. This module does not re-aggregate session participants,
locations visited, or encounter/quest/character-state changes; those
remain deferred (see docs/PHASE13D_BACKEND_READINESS.md).

This module is framework-free and performs no authorization decisions of
its own: `denied_session_ids`, `include_draft_events`, and the two
`*_draft_event_ids` sets must already be authorized/resolved by the time
they reach here, exactly like every other query module in this package.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Connection, text

from dnd_ai.domain.errors import DomainAuthorizationError


class SessionNotFoundError(DomainAuthorizationError):
    """Raised by `get_session_view()` for a nonexistent `session_id`, or one
    belonging to a different campaign than `campaign_id` — identically, so
    a caller can never distinguish the two (mirroring `dnd_ai.queries.
    dungeon.DungeonAreaNotFoundError`'s identical cross-tenant reasoning).
    The supplied session/campaign ids are included only in the
    constructor's `detail` argument (`str(self)`), never in
    `safe_message`."""


@dataclass(frozen=True)
class SessionListItemView:
    session_id: uuid.UUID
    session_number: int
    title: str | None
    status_code: str
    started_at: datetime | None
    ended_at: datetime | None


@dataclass(frozen=True)
class SessionEventView:
    event_id: uuid.UUID
    name: str
    summary: str | None
    event_type_code: str
    event_status_code: str
    world_time_id: uuid.UUID
    details: str | None


@dataclass(frozen=True)
class SessionView:
    session_id: uuid.UUID
    session_number: int
    title: str | None
    status_code: str
    started_at: datetime | None
    ended_at: datetime | None
    summary: str | None
    start_world_time_id: uuid.UUID | None
    end_world_time_id: uuid.UUID | None
    events: tuple[SessionEventView, ...]


def list_campaign_sessions(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    denied_session_ids: frozenset[uuid.UUID] = frozenset(),
) -> tuple[SessionListItemView, ...]:
    """Every session for `campaign_id`, most recent first, excluding any
    `denied_session_ids` (a per-session `campaign.view` deny — see this
    module's docstring). `campaign_id` is trusted as already authorized
    (`require_campaign_capability`), matching `dnd_ai.queries.summary.
    get_campaign_summary_view`'s identical trust boundary. No `allowed_
    session_ids` counterpart exists: unlike a draft event (baseline
    visibility `False` for a non-GM), a session's baseline visibility is
    always `True` for any `campaign.view` caller, so there is no
    default-hidden state for an explicit allow to ever add back."""
    rows = connection.execute(
        text("""
            SELECT s.session_id, s.session_number, s.title, ls.code AS status_code,
                   s.started_at, s.ended_at
            FROM campaign.sessions s
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = s.lifecycle_status_id
            WHERE s.campaign_id = :campaign
              AND NOT (s.session_id = ANY(CAST(:denied AS uuid[])))
            ORDER BY s.session_number DESC
        """),
        {"campaign": campaign_id, "denied": list(denied_session_ids)},
    ).mappings()
    return tuple(
        SessionListItemView(
            session_id=row["session_id"],
            session_number=row["session_number"],
            title=row["title"],
            status_code=row["status_code"],
            started_at=row["started_at"],
            ended_at=row["ended_at"],
        )
        for row in rows
    )


def get_session_view(
    connection: Connection,
    *,
    session_id: uuid.UUID,
    campaign_id: uuid.UUID,
    include_draft_events: bool,
    denied_draft_event_ids: frozenset[uuid.UUID] = frozenset(),
    allowed_draft_event_ids: frozenset[uuid.UUID] = frozenset(),
) -> SessionView:
    """One session's own fields plus its linked `narrative.events` rows
    (`narrative.events.session_id`), filtered by the same draft/voided
    rule `dnd_ai.queries.summary.get_campaign_summary_view` already applies
    — see this module's docstring. Raises `SessionNotFoundError` for a
    nonexistent session or one belonging to a different campaign than
    `campaign_id` (always the caller's own already-authorized campaign,
    never caller-supplied from anywhere else)."""
    session_row = (
        connection.execute(
            text("""
                SELECT s.session_id, s.campaign_id, s.session_number, s.title,
                       ls.code AS status_code, s.started_at, s.ended_at, s.summary,
                       s.start_world_time_id, s.end_world_time_id
                FROM campaign.sessions s
                JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = s.lifecycle_status_id
                WHERE s.session_id = :session
            """),
            {"session": session_id},
        )
        .mappings()
        .one_or_none()
    )
    if session_row is None or session_row["campaign_id"] != campaign_id:
        raise SessionNotFoundError(
            f"session {session_id} does not exist in campaign {campaign_id} "
            f"(actual campaign: {session_row['campaign_id'] if session_row is not None else None})"
        )

    event_rows = connection.execute(
        text("""
            SELECT e.event_id, ce.canonical_name AS name, ce.summary, et.code AS event_type_code,
                   es.code AS event_status_code, e.world_time_id, e.details
            FROM narrative.events e
            JOIN core.entities ce ON ce.entity_id = e.event_id
            JOIN narrative.event_types et ON et.event_type_id = e.event_type_id
            JOIN narrative.event_statuses es ON es.event_status_id = e.event_status_id
            JOIN core.world_times wt ON wt.world_time_id = e.world_time_id
            WHERE e.session_id = :session
              AND es.code != 'voided'
              AND (
                    es.code != 'draft'
                    OR (
                          NOT (e.event_id = ANY(CAST(:denied_draft_events AS uuid[])))
                          AND (
                                :include_draft
                                OR e.event_id = ANY(CAST(:allowed_draft_events AS uuid[]))
                              )
                       )
                  )
            ORDER BY wt.sort_key, e.created_at
        """),
        {
            "session": session_id,
            "include_draft": include_draft_events,
            "denied_draft_events": list(denied_draft_event_ids),
            "allowed_draft_events": list(allowed_draft_event_ids),
        },
    ).mappings()
    events = tuple(
        SessionEventView(
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

    return SessionView(
        session_id=session_row["session_id"],
        session_number=session_row["session_number"],
        title=session_row["title"],
        status_code=session_row["status_code"],
        started_at=session_row["started_at"],
        ended_at=session_row["ended_at"],
        summary=session_row["summary"],
        start_world_time_id=session_row["start_world_time_id"],
        end_world_time_id=session_row["end_world_time_id"],
        events=events,
    )
