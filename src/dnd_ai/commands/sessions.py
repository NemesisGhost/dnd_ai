"""End-session command (docs/PLAN.md §25 step 14, "End the session and
generate a summary").

`campaign.sessions` already carries the full lifecycle columns
(`ended_at`, `end_world_time_id`, `summary`) — no command populated them
through the application until now, the same gap `dnd_ai.commands.movement.
enter_location` closed for `character_location_history`. "Generate a
summary" (the second half of step 14) is already served by `GET /campaigns
/{campaign_id}/summary` (Phase 10 workstream 22); this command only
records the session bookkeeping itself. "Ended" is represented by
`ended_at IS NOT NULL`, not any `lifecycle_status_id` transition —
`core.lifecycle_statuses`' own vocabulary (pending/active/inactive/
archived/deleted) has no "ended" concept, and a session's row stays
operationally usable for as long as it exists.

Idempotent by construction: ending an already-ended session is a no-op,
returning its existing state rather than silently overwriting a GM's
prior summary text or raising.

`started_at` (the real-world wall-clock time play began — distinct from
`start_world_time_id`, the fictional-chronology point) is stamped to
`now()` alongside `ended_at` when it was never set: no `start_session`
command exists (out of scope here — not named by docs/PLAN.md §25), so a
session ended without one would otherwise leave `started_at NULL` while
`ended_at` is set, violating `campaign.sessions`' own `ck_sessions_ended_
requires_started` check constraint outright.

`end_world_time_id` is pre-checked against the campaign's own world and,
when the session already has a `start_world_time_id`, against strictly
later ordering — mirroring `campaign.enforce_session_world_times()`'s own
checks (revision 023) exactly, for the same unclassified-SQLSTATE reason
every other command in this codebase pre-checks a caller-supplied
world-time id: that `BEFORE INSERT/UPDATE` trigger raises the bare
`ERRCODE = 'integrity_constraint_violation'`, unrecognized by the generic
`IntegrityError` handler, which would otherwise surface an ordinary
cross-world or out-of-order mistake as an unclassified 500.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, Engine, text

from dnd_ai.domain.errors import DomainAuthorizationError


class SessionNotFoundError(DomainAuthorizationError):
    """Raised by `end_session()` when `session_id` does not resolve to a
    `campaign.sessions` row belonging to `campaign_id` — including a
    nonexistent session, identically. The supplied ids are included only
    in the constructor's `detail` argument (`str(self)`), never in
    `safe_message`."""


class EndWorldTimeNotInWorldError(DomainAuthorizationError):
    """Raised by `end_session()` when `end_world_time_id` does not belong
    to the session's own campaign world — including a nonexistent world
    time, identically. The supplied ids are included only in the
    constructor's `detail` argument (`str(self)`), never in
    `safe_message`."""


class InvalidSessionPeriodError(ValueError):
    """Raised by `end_session()` when the session already has a `start_
    world_time_id` and `end_world_time_id` does not resolve to a later
    `sort_key` — mirroring `campaign.enforce_session_world_times()`'s own
    ordering check."""


@dataclass(frozen=True)
class EndSessionResult:
    session_id: uuid.UUID
    already_ended: bool


def _end_session_impl(
    connection: Connection,
    *,
    session_id: uuid.UUID,
    campaign_id: uuid.UUID,
    end_world_time_id: uuid.UUID,
    summary: str | None = None,
) -> EndSessionResult:
    """The actual work of `end_session()`, on a connection the caller
    already has open — see `dnd_ai.commands.encounters._resolve_combat_
    turn_impl`'s docstring for the composable-implementation/public-wrapper
    pattern this mirrors."""
    row = (
        connection.execute(
            text("""
                SELECT s.campaign_id, s.ended_at, s.start_world_time_id, t.world_id
                FROM campaign.sessions s
                JOIN campaign.campaigns c ON c.campaign_id = s.campaign_id
                JOIN campaign.timelines t ON t.timeline_id = c.timeline_id
                WHERE s.session_id = :session
                FOR UPDATE OF s
            """),
            {"session": session_id},
        )
        .mappings()
        .one_or_none()
    )
    if row is None or row["campaign_id"] != campaign_id:
        raise SessionNotFoundError(
            f"session {session_id} does not belong to campaign {campaign_id} "
            f"(actual campaign: {row['campaign_id'] if row is not None else None})"
        )

    if row["ended_at"] is not None:
        return EndSessionResult(session_id=session_id, already_ended=True)

    end_row = (
        connection.execute(
            text("SELECT world_id, sort_key FROM core.world_times WHERE world_time_id = :wt"),
            {"wt": end_world_time_id},
        )
        .mappings()
        .one_or_none()
    )
    if end_row is None or end_row["world_id"] != row["world_id"]:
        raise EndWorldTimeNotInWorldError(
            f"world time {end_world_time_id} does not belong to world {row['world_id']} "
            f"(actual world: {end_row['world_id'] if end_row is not None else None})"
        )

    if row["start_world_time_id"] is not None:
        start_sort_key = connection.execute(
            text("SELECT sort_key FROM core.world_times WHERE world_time_id = :wt"),
            {"wt": row["start_world_time_id"]},
        ).scalar()
        if end_row["sort_key"] <= start_sort_key:
            raise InvalidSessionPeriodError(
                f"session end (sort_key {end_row['sort_key']}) must be later than its start "
                f"(sort_key {start_sort_key})"
            )

    connection.execute(
        text("""
            UPDATE campaign.sessions
            SET started_at = COALESCE(started_at, now()),
                -- now() is frozen for the whole transaction (docs/DATABASE_
                -- CONVENTIONS.md), so a bare now() here would tie ended_at
                -- exactly to a started_at set in this same statement,
                -- tripping ck_sessions_ended_after_started's strict ">".
                ended_at = now() + interval '1 microsecond',
                end_world_time_id = :end_wt, summary = COALESCE(:summary, summary)
            WHERE session_id = :session
        """),
        {"end_wt": end_world_time_id, "summary": summary, "session": session_id},
    )
    return EndSessionResult(session_id=session_id, already_ended=False)


def end_session(
    engine: Engine,
    *,
    session_id: uuid.UUID,
    campaign_id: uuid.UUID,
    end_world_time_id: uuid.UUID,
    summary: str | None = None,
) -> EndSessionResult:
    """Records `session_id` as ended. Public convenience API: opens and
    commits its own transaction. See `_end_session_impl()` for the
    composable form a caller with its own transaction (e.g. an API command
    endpoint) uses instead."""
    with engine.begin() as connection:
        return _end_session_impl(
            connection,
            session_id=session_id,
            campaign_id=campaign_id,
            end_world_time_id=end_world_time_id,
            summary=summary,
        )
