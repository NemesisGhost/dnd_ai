"""Schedule, edit, archive, and restore sessions (Phase 15 checkpoint 15.2D-1).

A session belongs to the route campaign; any other session id (nonexistent, or
another campaign's) is the same non-disclosing 404. `schedule_session` assigns the
number on the server under a per-campaign advisory lock (the unique
`(campaign_id, session_number)` index is the backstop), so two concurrent
schedules get consecutive numbers rather than a conflict.

Lock order: operation scope (world, membership rows, account, campaign `FOR
SHARE`), the per-campaign numbering advisory lock (schedule only), then the
session row `FOR UPDATE`.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Connection, text

from dnd_ai.domain.authoring import StaleWriteError, normalize_reason
from dnd_ai.domain.content_authoring import diff_fields, initial_fields
from dnd_ai.domain.session_authoring import (
    SESSION_ACTIVE,
    SESSION_ARCHIVED,
    SessionAlreadyStartedError,
    SessionInProgressError,
    SessionNotActiveError,
    SessionNotArchivedError,
    normalize_description,
    normalize_title,
)

from ._operations import lock_operation_scope
from ._shared import lookup_id
from .sessions import SessionNotFoundError


@dataclass(frozen=True)
class SessionResult:
    session_id: uuid.UUID
    session_number: int
    world_id: uuid.UUID
    row_version: int
    created: bool
    changed: bool
    changed_fields: dict[str, object]
    lifecycle_status: str
    previous_lifecycle_status: str | None = None


@dataclass(frozen=True)
class _Locked:
    session_number: int
    title: str | None
    summary: str | None
    scheduled_for: datetime | None
    started_at: datetime | None
    ended_at: datetime | None
    row_version: int
    lifecycle_status: str


def _lock_session(
    connection: Connection, *, campaign_id: uuid.UUID, session_id: uuid.UUID
) -> _Locked:
    # The row is locked without a join (a join inside a locking statement is
    # re-evaluated after a wait and can return nothing); the status code is a
    # separate read.
    row = connection.execute(
        text("""
            SELECT s.session_number, s.title, s.summary, s.scheduled_for, s.started_at,
                   s.ended_at, s.row_version, s.lifecycle_status_id
            FROM campaign.sessions s
            WHERE s.session_id = :s AND s.campaign_id = :c
            FOR UPDATE OF s
        """),
        {"s": session_id, "c": campaign_id},
    ).one_or_none()
    if row is None:
        raise SessionNotFoundError(f"session {session_id} is not in campaign {campaign_id}")
    status = connection.execute(
        text("SELECT code FROM core.lifecycle_statuses WHERE lifecycle_status_id = :s"),
        {"s": row.lifecycle_status_id},
    ).scalar()
    return _Locked(
        session_number=int(row.session_number),
        title=row.title,
        summary=row.summary,
        scheduled_for=row.scheduled_for,
        started_at=row.started_at,
        ended_at=row.ended_at,
        row_version=int(row.row_version),
        lifecycle_status=str(status),
    )


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def schedule_session(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    title: str | None,
    scheduled_for: datetime | None,
    summary: str | None = None,
) -> SessionResult:
    clean_title = normalize_title(title)
    clean_summary = normalize_description(summary)
    scope = lock_operation_scope(connection, campaign_id=campaign_id, actor_user_id=actor_user_id)
    connection.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"campaign.sessions.number:{campaign_id}"},
    )
    number = connection.execute(
        text(
            "SELECT coalesce(max(session_number), 0) + 1 FROM campaign.sessions "
            "WHERE campaign_id = :c"
        ),
        {"c": campaign_id},
    ).scalar()
    assert isinstance(number, int)
    row = connection.execute(
        text("""
            INSERT INTO campaign.sessions
                (campaign_id, session_number, title, summary, scheduled_for,
                 lifecycle_status_id, created_by_user_id)
            VALUES (:c, :n, :title, :summary, :scheduled, :status, :user)
            RETURNING session_id, row_version
        """),
        {
            "c": campaign_id,
            "n": number,
            "title": clean_title,
            "summary": clean_summary,
            "scheduled": scheduled_for,
            "status": lookup_id(
                connection, "core", "lifecycle_statuses", "lifecycle_status_id", SESSION_ACTIVE
            ),
            "user": actor_user_id,
        },
    ).one()
    return SessionResult(
        session_id=row.session_id,
        session_number=number,
        world_id=scope.world_id,
        row_version=int(row.row_version),
        created=True,
        changed=True,
        changed_fields=initial_fields(
            {
                "sequence_number": number,
                "title": clean_title,
                "summary": clean_summary,
                "scheduled_for": _iso(scheduled_for),
            }
        ),
        lifecycle_status=SESSION_ACTIVE,
    )


def update_session(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    session_id: uuid.UUID,
    expected_row_version: int,
    title: str | None,
    scheduled_for: datetime | None,
    summary: str | None = None,
) -> SessionResult:
    clean_title = normalize_title(title)
    clean_summary = normalize_description(summary)
    scope = lock_operation_scope(connection, campaign_id=campaign_id, actor_user_id=actor_user_id)
    current = _lock_session(connection, campaign_id=campaign_id, session_id=session_id)
    if current.row_version != expected_row_version:
        raise StaleWriteError(f"session {session_id} is at {current.row_version}")
    if current.lifecycle_status != SESSION_ACTIVE:
        raise SessionNotActiveError(f"session {session_id} is {current.lifecycle_status}")
    changed = diff_fields(
        {
            "title": current.title,
            "summary": current.summary,
            "scheduled_for": _iso(current.scheduled_for),
        },
        {
            "title": clean_title,
            "summary": clean_summary,
            "scheduled_for": _iso(scheduled_for),
        },
    )
    if "scheduled_for" in changed and current.started_at is not None:
        raise SessionAlreadyStartedError(f"session {session_id} started")
    if not changed:
        return SessionResult(
            session_id=session_id,
            session_number=current.session_number,
            world_id=scope.world_id,
            row_version=current.row_version,
            created=False,
            changed=False,
            changed_fields={},
            lifecycle_status=current.lifecycle_status,
        )
    version = connection.execute(
        text("""
            UPDATE campaign.sessions
            SET title = :title, summary = :summary, scheduled_for = :scheduled
            WHERE session_id = :s RETURNING row_version
        """),
        {
            "title": clean_title,
            "summary": clean_summary,
            "scheduled": scheduled_for,
            "s": session_id,
        },
    ).scalar()
    assert isinstance(version, int)
    return SessionResult(
        session_id=session_id,
        session_number=current.session_number,
        world_id=scope.world_id,
        row_version=version,
        created=False,
        changed=True,
        changed_fields=dict(changed),
        lifecycle_status=current.lifecycle_status,
    )


def _transition(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    session_id: uuid.UUID,
    expected_row_version: int,
    to_status: str,
) -> SessionResult:
    scope = lock_operation_scope(connection, campaign_id=campaign_id, actor_user_id=actor_user_id)
    current = _lock_session(connection, campaign_id=campaign_id, session_id=session_id)
    if current.row_version != expected_row_version:
        raise StaleWriteError(f"session {session_id} is at {current.row_version}")
    if to_status == SESSION_ARCHIVED:
        if current.lifecycle_status != SESSION_ACTIVE:
            raise SessionNotActiveError(f"session {session_id} is {current.lifecycle_status}")
        if current.started_at is not None and current.ended_at is None:
            raise SessionInProgressError(f"session {session_id} is being played")
    elif current.lifecycle_status != SESSION_ARCHIVED:
        raise SessionNotArchivedError(f"session {session_id} is {current.lifecycle_status}")
    version = connection.execute(
        text("""
            UPDATE campaign.sessions
            SET lifecycle_status_id = :status,
                archived_at = CASE WHEN :archived THEN now() ELSE NULL END
            WHERE session_id = :s RETURNING row_version
        """),
        {
            "status": lookup_id(
                connection, "core", "lifecycle_statuses", "lifecycle_status_id", to_status
            ),
            "archived": to_status == SESSION_ARCHIVED,
            "s": session_id,
        },
    ).scalar()
    assert isinstance(version, int)
    return SessionResult(
        session_id=session_id,
        session_number=current.session_number,
        world_id=scope.world_id,
        row_version=version,
        created=False,
        changed=True,
        changed_fields={},
        lifecycle_status=to_status,
        previous_lifecycle_status=current.lifecycle_status,
    )


def archive_session(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    session_id: uuid.UUID,
    expected_row_version: int,
    reason: str | None = None,
) -> SessionResult:
    normalize_reason(reason)
    return _transition(
        connection,
        campaign_id=campaign_id,
        actor_user_id=actor_user_id,
        session_id=session_id,
        expected_row_version=expected_row_version,
        to_status=SESSION_ARCHIVED,
    )


def restore_session(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    session_id: uuid.UUID,
    expected_row_version: int,
    reason: str,
) -> SessionResult:
    normalize_reason(reason, required=True)
    return _transition(
        connection,
        campaign_id=campaign_id,
        actor_user_id=actor_user_id,
        session_id=session_id,
        expected_row_version=expected_row_version,
        to_status=SESSION_ACTIVE,
    )
