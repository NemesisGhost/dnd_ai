"""Run a session: participants, start, log, and end (Phase 15 checkpoint 15.2D-2).

Decision D-14: participants are characters only. Decision D-13: play status is
derived, and at most one session per campaign is in progress (checked under a
per-campaign advisory lock, with a unique partial index as the database backstop).

- `start_session` stamps `started_at` and the session's world time. The time is the
  caller's, or the campaign clock's; with neither the command asks for one.
- `add_session_participant` / `remove_session_participant` change who is present, until
  the session has ended. A participant is a published, active character of the world;
  a `player_character` or `npc` role must match the character's kind (`guest` takes any).
- `record_session_log_entry` records one `session_narrative` event on the campaign's
  timeline, linked to the session. The entry is the campaign-visible name of the event;
  `details` is GM-only. Entries are append-only (recorded events are immutable).
- `end_session` ends a session that is in progress, at the caller's or the clock's time,
  strictly after it began.

Lock order: operation scope (world, membership rows, account, campaign `FOR SHARE`),
the per-campaign play advisory lock (start only), the session row (`FOR UPDATE`; `FOR
SHARE` for a log entry, so an end waits for an entry already being written and a later
entry sees the ended session), the character entity `FOR SHARE`, then participant rows.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError

from dnd_ai.domain.authoring import StaleWriteError
from dnd_ai.domain.data_classification import audit_change, audit_initial
from dnd_ai.domain.session_authoring import (
    PARTICIPATION_ROLES,
    SESSION_ACTIVE,
    AnotherSessionInProgressError,
    ParticipantExistsError,
    ParticipantInvalidError,
    ParticipantRemovedError,
    SessionAlreadyStartedError,
    SessionEndNotAfterStartError,
    SessionNotActiveError,
    SessionNotInProgressError,
    SessionNotOpenError,
    SessionTimeRequiredError,
    normalize_description,
    normalize_log_details,
    normalize_log_entry,
)
from dnd_ai.domain.world_time import WorldTimeReferenceInvalidError
from dnd_ai.queries.campaign_clock import resolve_effective_clock

from ._content import lock_entities
from ._operations import OperationScope, lock_operation_scope
from .events import EventParticipant, _insert_event_row
from .session_authoring import LockedSession, lock_campaign_session
from .sessions import SessionNotFoundError

_PARTICIPANT_KINDS = frozenset({"npc", "player_character"})
_UNIQUE_VIOLATION = "23505"


@dataclass(frozen=True)
class PlayResult:
    session_id: uuid.UUID
    world_id: uuid.UUID
    row_version: int
    changed_fields: dict[str, object]
    participant_id: uuid.UUID | None = None
    event_id: uuid.UUID | None = None
    character_id: uuid.UUID | None = None


def _sort_key(connection: Connection, *, world_id: uuid.UUID, world_time_id: uuid.UUID) -> int:
    key = connection.execute(
        text("SELECT sort_key FROM core.world_times WHERE world_time_id = :t AND world_id = :w"),
        {"t": world_time_id, "w": world_id},
    ).scalar()
    if key is None:
        raise WorldTimeReferenceInvalidError(f"world time {world_time_id} is not in {world_id}")
    assert isinstance(key, int)
    return key


def _time_or_clock(
    connection: Connection, scope: OperationScope, world_time_id: uuid.UUID | None
) -> uuid.UUID:
    """The explicit world time, checked to be in the world, or the campaign clock's."""
    if world_time_id is not None:
        _sort_key(connection, world_id=scope.world_id, world_time_id=world_time_id)
        return world_time_id
    clock = resolve_effective_clock(connection, timeline_id=scope.timeline_id)
    if clock is None:
        raise SessionTimeRequiredError("the campaign clock is not set")
    return clock.world_time_id


def _bump_session(connection: Connection, session_id: uuid.UUID) -> int:
    version = connection.execute(
        text(
            "UPDATE campaign.sessions SET updated_at = now() "
            "WHERE session_id = :s RETURNING row_version"
        ),
        {"s": session_id},
    ).scalar()
    assert isinstance(version, int)
    return version


def _require_version_and_active(
    current: LockedSession, *, session_id: uuid.UUID, expected_row_version: int
) -> None:
    if current.row_version != expected_row_version:
        raise StaleWriteError(f"session {session_id} is at {current.row_version}")
    if current.lifecycle_status != SESSION_ACTIVE:
        raise SessionNotActiveError(f"session {session_id} is {current.lifecycle_status}")


def _in_progress(current: LockedSession) -> bool:
    return current.started_at is not None and current.ended_at is None


def start_session(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    session_id: uuid.UUID,
    expected_row_version: int,
    start_world_time_id: uuid.UUID | None = None,
) -> PlayResult:
    scope = lock_operation_scope(connection, campaign_id=campaign_id, actor_user_id=actor_user_id)
    connection.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"campaign.sessions.play:{campaign_id}"},
    )
    current = lock_campaign_session(connection, campaign_id=campaign_id, session_id=session_id)
    _require_version_and_active(
        current, session_id=session_id, expected_row_version=expected_row_version
    )
    if current.started_at is not None:
        raise SessionAlreadyStartedError(f"session {session_id} already started")
    other = connection.execute(
        text("""
            SELECT 1 FROM campaign.sessions
            WHERE campaign_id = :c AND session_id <> :s
              AND started_at IS NOT NULL AND ended_at IS NULL
            LIMIT 1
        """),
        {"c": campaign_id, "s": session_id},
    ).scalar()
    if other is not None:
        raise AnotherSessionInProgressError(f"campaign {campaign_id} already has a session playing")
    time_id = _time_or_clock(connection, scope, start_world_time_id)
    row = connection.execute(
        text("""
            UPDATE campaign.sessions
            -- now() is frozen for a transaction; the end adds a microsecond so that
            -- ended_at is strictly after started_at (ck_sessions_ended_after_started).
            SET started_at = now(), start_world_time_id = :t
            WHERE session_id = :s RETURNING row_version
        """),
        {"t": time_id, "s": session_id},
    ).one()
    return PlayResult(
        session_id=session_id,
        world_id=scope.world_id,
        row_version=int(row.row_version),
        changed_fields={
            "start_world_time_id": audit_change("start_world_time_id", None, str(time_id))
        },
    )


def _lock_participant_character(
    connection: Connection, scope: OperationScope, character_id: uuid.UUID
) -> str:
    locked = lock_entities(connection, world_id=scope.world_id, share_ids=[character_id])
    character = locked.get(character_id)
    if (
        character is None
        or character.entity_type_code not in _PARTICIPANT_KINDS
        or character.canon_status != "canon"
        or character.lifecycle_status != "active"
    ):
        raise ParticipantInvalidError(f"{character_id} cannot take part")
    return character.entity_type_code


def add_session_participant(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    session_id: uuid.UUID,
    expected_row_version: int,
    character_id: uuid.UUID,
    participation_role: str,
) -> PlayResult:
    if participation_role not in PARTICIPATION_ROLES:
        raise ParticipantInvalidError(f"unknown role {participation_role!r}")
    scope = lock_operation_scope(connection, campaign_id=campaign_id, actor_user_id=actor_user_id)
    current = lock_campaign_session(connection, campaign_id=campaign_id, session_id=session_id)
    _require_version_and_active(
        current, session_id=session_id, expected_row_version=expected_row_version
    )
    if current.ended_at is not None:
        raise SessionNotOpenError(f"session {session_id} has ended")
    kind = _lock_participant_character(connection, scope, character_id)
    if participation_role != "guest" and participation_role != kind:
        raise ParticipantInvalidError(f"{character_id} is a {kind}, not a {participation_role}")
    try:
        participant_id = connection.execute(
            text("""
                INSERT INTO campaign.session_participants
                    (session_id, character_id, participation_role, added_by_user_id)
                VALUES (:s, :c, :role, :user) RETURNING session_participant_id
            """),
            {"s": session_id, "c": character_id, "role": participation_role, "user": actor_user_id},
        ).scalar()
    except IntegrityError as exc:
        if getattr(exc.orig, "sqlstate", None) == _UNIQUE_VIOLATION:
            raise ParticipantExistsError(f"{character_id} is already present") from exc
        raise
    assert isinstance(participant_id, uuid.UUID)
    return PlayResult(
        session_id=session_id,
        world_id=scope.world_id,
        row_version=_bump_session(connection, session_id),
        participant_id=participant_id,
        character_id=character_id,
        changed_fields=audit_initial(
            {"member_entity_id": str(character_id), "participation_role": participation_role}
        ),
    )


def remove_session_participant(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    session_id: uuid.UUID,
    expected_row_version: int,
    session_participant_id: uuid.UUID,
) -> PlayResult:
    scope = lock_operation_scope(connection, campaign_id=campaign_id, actor_user_id=actor_user_id)
    current = lock_campaign_session(connection, campaign_id=campaign_id, session_id=session_id)
    _require_version_and_active(
        current, session_id=session_id, expected_row_version=expected_row_version
    )
    if current.ended_at is not None:
        raise SessionNotOpenError(f"session {session_id} has ended")
    row = connection.execute(
        text("""
            SELECT character_id, removed_at FROM campaign.session_participants
            WHERE session_participant_id = :p AND session_id = :s FOR UPDATE
        """),
        {"p": session_participant_id, "s": session_id},
    ).one_or_none()
    if row is None:
        raise SessionNotFoundError(f"participant {session_participant_id} is not in {session_id}")
    if row.removed_at is not None:
        raise ParticipantRemovedError(f"participant {session_participant_id} was removed")
    connection.execute(
        text(
            "UPDATE campaign.session_participants SET removed_at = now() "
            "WHERE session_participant_id = :p"
        ),
        {"p": session_participant_id},
    )
    return PlayResult(
        session_id=session_id,
        world_id=scope.world_id,
        row_version=_bump_session(connection, session_id),
        participant_id=session_participant_id,
        character_id=row.character_id,
        changed_fields={
            "member_entity_id": audit_change("member_entity_id", str(row.character_id), None)
        },
    )


def record_session_log_entry(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    session_id: uuid.UUID,
    entry: str | None,
    details: str | None = None,
    world_time_id: uuid.UUID | None = None,
    character_ids: tuple[uuid.UUID, ...] = (),
) -> PlayResult:
    clean_entry = normalize_log_entry(entry)
    clean_details = normalize_log_details(details)
    scope = lock_operation_scope(connection, campaign_id=campaign_id, actor_user_id=actor_user_id)
    row = connection.execute(
        text("""
            SELECT s.started_at, s.ended_at, s.lifecycle_status_id, s.row_version
            FROM campaign.sessions s
            WHERE s.session_id = :s AND s.campaign_id = :c FOR SHARE OF s
        """),
        {"s": session_id, "c": campaign_id},
    ).one_or_none()
    if row is None:
        raise SessionNotFoundError(f"session {session_id} is not in campaign {campaign_id}")
    status = connection.execute(
        text("SELECT code FROM core.lifecycle_statuses WHERE lifecycle_status_id = :s"),
        {"s": row.lifecycle_status_id},
    ).scalar()
    if status != SESSION_ACTIVE:
        raise SessionNotActiveError(f"session {session_id} is {status}")
    if row.started_at is None or row.ended_at is not None:
        raise SessionNotInProgressError(f"session {session_id} is not in progress")
    time_id = _time_or_clock(connection, scope, world_time_id)
    event_id = _insert_event_row(
        connection,
        world_id=scope.world_id,
        timeline_id=scope.timeline_id,
        world_time_id=time_id,
        event_type_code="session_narrative",
        name=clean_entry,
        details=clean_details,
        campaign_id=campaign_id,
        session_id=session_id,
        participants=tuple(EventParticipant(entity_id=c, role_code="actor") for c in character_ids),
    )
    return PlayResult(
        session_id=session_id,
        world_id=scope.world_id,
        row_version=int(row.row_version),
        event_id=event_id,
        changed_fields=audit_initial(
            {
                "entry": clean_entry,
                "world_time_id": str(time_id),
                "has_details": clean_details is not None,
            }
        ),
    )


def end_session(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    session_id: uuid.UUID,
    expected_row_version: int,
    end_world_time_id: uuid.UUID | None = None,
    summary: str | None = None,
) -> PlayResult:
    clean_summary = normalize_description(summary)
    scope = lock_operation_scope(connection, campaign_id=campaign_id, actor_user_id=actor_user_id)
    current = lock_campaign_session(connection, campaign_id=campaign_id, session_id=session_id)
    _require_version_and_active(
        current, session_id=session_id, expected_row_version=expected_row_version
    )
    if not _in_progress(current):
        raise SessionNotInProgressError(f"session {session_id} is not in progress")
    time_id = _time_or_clock(connection, scope, end_world_time_id)
    start_time_id = connection.execute(
        text("SELECT start_world_time_id FROM campaign.sessions WHERE session_id = :s"),
        {"s": session_id},
    ).scalar()
    if start_time_id is not None:
        start_key = _sort_key(connection, world_id=scope.world_id, world_time_id=start_time_id)
        end_key = _sort_key(connection, world_id=scope.world_id, world_time_id=time_id)
        if end_key <= start_key:
            raise SessionEndNotAfterStartError(f"end {end_key} <= start {start_key}")
    row = connection.execute(
        text("""
            UPDATE campaign.sessions
            SET ended_at = now() + interval '1 microsecond', end_world_time_id = :t,
                summary = COALESCE(:summary, summary)
            WHERE session_id = :s RETURNING row_version
        """),
        {"t": time_id, "summary": clean_summary, "s": session_id},
    ).one()
    return PlayResult(
        session_id=session_id,
        world_id=scope.world_id,
        row_version=int(row.row_version),
        changed_fields={"end_world_time_id": audit_change("end_world_time_id", None, str(time_id))},
    )
