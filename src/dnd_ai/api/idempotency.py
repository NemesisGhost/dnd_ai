"""Durable, PostgreSQL-backed `Idempotency-Key` handling for commands.

`dnd_ai.api.deps.get_idempotency_key` only ever passed the client's header
value through — nothing stored or deduplicated against it. This module is
the reusable reservation/replay logic every mutating command endpoint that
accepts an idempotency key can build on, first used by
`dnd_ai.api.items`.

## Scope and fingerprint

A key is scoped to `(actor_user_id, campaign_id, idempotency_key)` — the
authenticated caller, the campaign named in the URL (already authorized by
the time a route calls this module), and the client-chosen key itself.
Reusing the same key for a genuinely different request (a different
command, a different target resource, or a different payload) is *not*
treated as "the same logical request retried" — it is rejected as a
conflict, per `compute_request_fingerprint`'s own docstring below.

## Concurrency: reserve, execute, complete — no separate lock, no
## check-then-insert race

`begin_idempotent_request()` does exactly one statement to determine
whether this call owns the key: `INSERT ... ON CONFLICT (...) DO NOTHING
RETURNING ...`. This is not a check-then-insert race — PostgreSQL resolves
the conflict as part of the single INSERT statement, against its own
unique index, atomically. Two concurrent transactions racing for the same
key are handled by ordinary MVCC/index locking, not application code: the
second transaction's INSERT blocks until the first transaction's row
either commits (the second sees a real conflict and gets zero rows back)
or rolls back (the second sees no conflict at all and reserves the key
itself, exactly as if it had been first). No `SELECT ... FOR UPDATE`, no
advisory lock, no in-memory cache — the same first-write-wins guarantee
`dnd_ai.commands.items._lock_item_instance` gets from an explicit row
lock, here obtained from the unique constraint itself.

Because the reservation INSERT runs inside the *same* transaction as the
command it guards (the request's own `get_connection` transaction — see
`dnd_ai.api.deps`), a command that fails or is rolled back for any reason
never durably reserves the key at all: the whole transaction, including
that INSERT, rolls back together. The key is therefore never "permanently
consumed" by a failed attempt — a subsequent retry with the same key sees
no existing row and reserves fresh, without any explicit cleanup path or
key-expiry job.

`complete_idempotent_request()` fills in the reserved row with the
command's actual response, still inside the same transaction, immediately
before the route returns. No other transaction can ever observe the row
between those two points: it is invisible until commit, and by commit
time it is already complete — `ck_idempotent_requests_completion_consistent`
(migration 082) makes an inconsistent intermediate state a schema-level
impossibility, not just an application convention.

## Pre-campaign idempotency: `security.campaign_creation_reservations`

`POST /campaigns` (`dnd_ai.commands.campaigns.create_campaign`) has no
existing `campaign_id` to scope a `security.idempotent_requests` row
against — it is the one write in this codebase that *creates* the
campaign a reservation would otherwise be keyed to. `begin_campaign_
creation_request()`/`complete_campaign_creation_request()` are the
matching reserve/replay/complete functions for `security.campaign_
creation_reservations` (migration 088), scoped to `(actor_user_id,
idempotency_key)` alone — no `campaign_id` column, and no `command_name`
column, since exactly one command ever reserves a row here. Every
concurrency and rollback guarantee above applies unchanged: one atomic
`INSERT ... ON CONFLICT DO NOTHING RETURNING` resolves ownership of the
key with no check-then-insert race, run inside the same transaction
`create_campaign()` itself runs in, so a failed or rolled-back attempt
never durably reserves the key — a retry with the same key sees no row
and reserves fresh. `complete_campaign_creation_request()` additionally
records the resulting `campaign_id` directly on the row (not only inside
`response_body`), so the campaign a reservation produced can be queried
without parsing JSON.
"""

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection, text

from .errors import ConflictError


def compute_request_fingerprint(*, command_name: str, payload: dict[str, Any]) -> str:
    """A canonical fingerprint of "this exact logical request": the command
    being invoked plus every argument that determines its effect (path
    parameters the route resolves, such as `item_instance_id`, and the
    request body). `campaign_id` is deliberately excluded — it is already
    one of the three columns the store's own uniqueness scope pins, so
    including it here would be redundant, not additionally protective.

    `json.dumps(..., sort_keys=True)` over plain JSON-safe values (callers
    pass a pydantic `.model_dump(mode="json")` body plus `str()`-ed UUID
    path parameters) gives a stable, deterministic digest regardless of
    dict insertion order. sha256 rather than a weaker/faster hash: this
    value is a security-relevant equality check (a mismatch is what turns
    a reused key into a rejected conflict), not a cache key where collision
    resistance is unimportant."""
    canonical = json.dumps({"command_name": command_name, **payload}, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class IdempotentReservation:
    """This call is the first (and, for the duration of its transaction,
    only) holder of the key — proceed with the command normally and call
    `complete_idempotent_request()` with its result before returning."""

    idempotent_request_id: uuid.UUID


@dataclass(frozen=True)
class IdempotentReplay:
    """An earlier call already completed successfully under this exact
    key and fingerprint — return this response verbatim instead of
    running the command again."""

    response_status_code: int
    response_body: dict[str, Any]


def begin_idempotent_request(
    connection: Connection,
    *,
    actor_user_id: uuid.UUID,
    campaign_id: uuid.UUID,
    idempotency_key: str,
    command_name: str,
    payload: dict[str, Any],
    correlation_id: str | None,
) -> IdempotentReservation | IdempotentReplay:
    """Reserve `idempotency_key` for this caller/campaign, or return the
    already-completed response for a matching replay. Raises `ConflictError`
    (a fixed, non-disclosing 409 — see `dnd_ai.api.errors.ConflictError`)
    when the key is reused with a different command or payload, or when it
    still names an incomplete row — the latter should be unreachable in
    normal operation (see the module docstring's concurrency argument) and
    is treated as a conflict rather than trusted, exactly like any other
    "should not happen" state this codebase maps to a fixed contract rather
    than a guess."""
    fingerprint = compute_request_fingerprint(command_name=command_name, payload=payload)

    reserved = connection.execute(
        text("""
            INSERT INTO security.idempotent_requests
                (actor_user_id, campaign_id, idempotency_key, request_fingerprint, correlation_id)
            VALUES (:user, :campaign, :key, :fingerprint, :correlation)
            ON CONFLICT (actor_user_id, campaign_id, idempotency_key) DO NOTHING
            RETURNING idempotent_request_id
        """),
        {
            "user": actor_user_id,
            "campaign": campaign_id,
            "key": idempotency_key,
            "fingerprint": fingerprint,
            "correlation": correlation_id,
        },
    ).one_or_none()
    if reserved is not None:
        return IdempotentReservation(idempotent_request_id=reserved.idempotent_request_id)

    existing = connection.execute(
        text("""
            SELECT request_fingerprint, response_status_code, response_body
            FROM security.idempotent_requests
            WHERE actor_user_id = :user AND campaign_id = :campaign AND idempotency_key = :key
        """),
        {"user": actor_user_id, "campaign": campaign_id, "key": idempotency_key},
    ).one()

    if existing.request_fingerprint != fingerprint:
        raise ConflictError(
            f"idempotency key {idempotency_key!r} was already used for a different "
            "command or payload"
        )
    if existing.response_status_code is None or existing.response_body is None:
        raise ConflictError(f"idempotency key {idempotency_key!r} names an incomplete reservation")
    return IdempotentReplay(
        response_status_code=existing.response_status_code,
        response_body=existing.response_body,
    )


def complete_idempotent_request(
    connection: Connection,
    *,
    idempotent_request_id: uuid.UUID,
    response_status_code: int,
    response_body: dict[str, Any],
) -> None:
    """Fill in the reserved row with the command's actual response, still
    inside the reserving transaction — see the module docstring for why
    this must happen before that transaction commits, not after."""
    connection.execute(
        text("""
            UPDATE security.idempotent_requests
            SET response_status_code = :status, response_body = :body, completed_at = now()
            WHERE idempotent_request_id = :id
        """),
        {
            "status": response_status_code,
            "body": json.dumps(response_body),
            "id": idempotent_request_id,
        },
    )


_CREATE_CAMPAIGN_COMMAND_NAME = "create_campaign"


@dataclass(frozen=True)
class CampaignCreationReservation:
    """This call is the first (and, for the duration of its transaction,
    only) holder of the key — proceed with `create_campaign` normally and
    call `complete_campaign_creation_request()` with its result before
    returning. See the module docstring's "Pre-campaign idempotency"
    section."""

    campaign_creation_reservation_id: uuid.UUID


def begin_campaign_creation_request(
    connection: Connection,
    *,
    actor_user_id: uuid.UUID,
    idempotency_key: str,
    payload: dict[str, Any],
    correlation_id: str | None,
) -> CampaignCreationReservation | IdempotentReplay:
    """Reserve `idempotency_key` for `actor_user_id`'s own `create_campaign`
    call, or return the already-completed response for a matching replay.
    The pre-campaign counterpart to `begin_idempotent_request()` — same
    atomic-INSERT concurrency behavior, same fingerprint-mismatch/
    incomplete-reservation `ConflictError` cases — scoped to `(actor_user_id,
    idempotency_key)` alone since there is no `campaign_id` yet to add to
    the tuple. See the module docstring's "Pre-campaign idempotency"
    section for why this needs its own table rather than reusing `security.
    idempotent_requests`."""
    fingerprint = compute_request_fingerprint(
        command_name=_CREATE_CAMPAIGN_COMMAND_NAME, payload=payload
    )

    reserved = connection.execute(
        text("""
            INSERT INTO security.campaign_creation_reservations
                (actor_user_id, idempotency_key, request_fingerprint, correlation_id)
            VALUES (:user, :key, :fingerprint, :correlation)
            ON CONFLICT (actor_user_id, idempotency_key) DO NOTHING
            RETURNING campaign_creation_reservation_id
        """),
        {
            "user": actor_user_id,
            "key": idempotency_key,
            "fingerprint": fingerprint,
            "correlation": correlation_id,
        },
    ).one_or_none()
    if reserved is not None:
        return CampaignCreationReservation(
            campaign_creation_reservation_id=reserved.campaign_creation_reservation_id
        )

    existing = connection.execute(
        text("""
            SELECT request_fingerprint, response_status_code, response_body
            FROM security.campaign_creation_reservations
            WHERE actor_user_id = :user AND idempotency_key = :key
        """),
        {"user": actor_user_id, "key": idempotency_key},
    ).one()

    if existing.request_fingerprint != fingerprint:
        raise ConflictError(
            f"idempotency key {idempotency_key!r} was already used for a different "
            "command or payload"
        )
    if existing.response_status_code is None or existing.response_body is None:
        raise ConflictError(f"idempotency key {idempotency_key!r} names an incomplete reservation")
    return IdempotentReplay(
        response_status_code=existing.response_status_code,
        response_body=existing.response_body,
    )


def complete_campaign_creation_request(
    connection: Connection,
    *,
    campaign_creation_reservation_id: uuid.UUID,
    response_status_code: int,
    response_body: dict[str, Any],
    campaign_id: uuid.UUID,
) -> None:
    """Fill in the reserved row with `create_campaign`'s actual response and
    the campaign it produced, still inside the reserving transaction — the
    pre-campaign counterpart to `complete_idempotent_request()`."""
    connection.execute(
        text("""
            UPDATE security.campaign_creation_reservations
            SET response_status_code = :status, response_body = :body, completed_at = now(),
                created_campaign_id = :campaign
            WHERE campaign_creation_reservation_id = :id
        """),
        {
            "status": response_status_code,
            "body": json.dumps(response_body),
            "campaign": campaign_id,
            "id": campaign_creation_reservation_id,
        },
    )
