"""Request-scoped database transactions and idempotency-key parsing.

`get_engine` is a process-wide singleton overridden wholesale in tests via
`app.dependency_overrides` (docs/architecture/SYSTEM_ARCHITECTURE.md §5.2 —
the API layer owns this wiring, not `dnd_ai.config` or the command layer).
`get_connection` opens one transaction per request; `commit_request_transaction`
(an app-wide dependency, P03-A P3) ends it. The transaction is committed or
rolled back before the response is sent, so a 2xx means the write committed.
Going through the API just means the API layer, not the command, owns that
boundary (the one-transaction-per-world-change rule every command follows on
its own when called directly).
"""

import logging
import re
import threading
from collections.abc import AsyncIterator, Iterator
from typing import Annotated

import anyio
import anyio.lowlevel
import anyio.to_thread
from fastapi import Depends, Header, Request
from sqlalchemy import Connection, Engine, create_engine, text

from dnd_ai.config import settings

# Mirrors dnd_ai.api.correlation's own reasoning for X-Correlation-Id:
# bound length and character set before a client-supplied header value
# ever reaches a database column, a log line, or an error response.
# Unlike a correlation ID, a malformed key is not silently replaced with a
# generated one — that would silently defeat the caller's own idempotency
# contract — so it is rejected outright instead.
_IDEMPOTENCY_KEY_PATTERN = re.compile(r"[A-Za-z0-9._~-]{1,255}")

_engine: Engine | None = None

logger = logging.getLogger(__name__)

_STATE_NAME = "dnd_ai_request_transaction"


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        # Settings._require_explicit_database_url_outside_local_dev guarantees this
        # is populated by the time Settings() finishes constructing (either an
        # explicit value or the local-dev default) — never None here at runtime.
        assert settings.database_url is not None
        _engine = create_engine(settings.database_url)
    return _engine


def dispose_engine() -> None:
    """Called from the app's lifespan shutdown. Tests that override
    `get_engine` manage their own engine's lifetime and never touch this."""
    global _engine
    if _engine is not None:
        _engine.dispose()
        _engine = None


class DatabaseIdentityError(RuntimeError):
    """Raised when a live database connection does not authenticate as the
    exact role production requires. `dnd_ai.config.Settings` already
    refuses to start if the *configured* `DND_AI_DATABASE_URL` doesn't
    name that role, but a URL string is only a claim about identity, not
    proof of it — this proves what PostgreSQL actually granted the
    session, catching a connection pooler/proxy that maps the credential
    to a different login role, or an implicit/explicit `SET ROLE` that
    changes the effective identity after authentication. Carries a fixed,
    non-disclosing message only — matching `dnd_ai.api.app.readyz`'s own
    established discipline of never logging a driver exception's message
    or traceback, since either can embed the DSN, host, or username; never
    the database URL or password."""


def _check_database_identity(connection: Connection, *, expected_role: str) -> None:
    """`session_user` is who authenticated the connection; `current_user`
    is the role currently in effect for privilege checks — normally the
    same, but an implicit or explicit `SET ROLE` (or `SET SESSION
    AUTHORIZATION`) can make them diverge. Checking only one of the two
    would let that diversion slip past unnoticed, so both must equal
    `expected_role`."""
    row = connection.execute(text("SELECT session_user, current_user")).one()
    session_user, current_user = row[0], row[1]
    if session_user != expected_role or current_user != expected_role:
        raise DatabaseIdentityError(
            f"Database connection is not authenticated as {expected_role!r} "
            "(checked both session_user and current_user) — refusing to start."
        )


def verify_database_identity(engine: Engine, *, expected_role: str) -> None:
    """Live counterpart to `dnd_ai.config.Settings`'s static URL-identity
    check (see that module's docstring). Opens a real connection through
    `engine` and confirms the session actually authenticated as
    `expected_role`, rather than trusting that the configured URL's
    username is what PostgreSQL actually granted. Called from
    `dnd_ai.api.app`'s lifespan startup, only when
    `settings.environment == "production"` — outside production this is
    never invoked, so local/test connections (which routinely use the
    `postgres` admin credential on purpose) are unaffected."""
    with engine.connect() as connection:
        _check_database_identity(connection, expected_role=expected_role)


class RequestTransactionError(RuntimeError):
    """The request-transaction wiring is broken (no commit dependency installed, or a second
    request connection): a programming error, mapped to the fixed 500."""


class _RequestTransaction:
    """The request's one connection and whether its transaction has ended. Kept on
    `request.state` by `commit_request_transaction`."""

    def __init__(self) -> None:
        self.connection: Connection | None = None
        self.ended = False
        self._lock = threading.Lock()

    def take_for_ending(self) -> Connection | None:
        """The connection to end, once: a second caller (or a request with no connection) gets
        None."""
        with self._lock:
            if self.ended or self.connection is None:
                return None
            self.ended = True
            return self.connection


def _commit(connection: Connection) -> None:
    """The only COMMIT of a request transaction (a seam: tests replace it)."""
    connection.commit()


def _rollback(connection: Connection) -> None:
    """The only ROLLBACK of a request transaction (a seam: tests replace it)."""
    connection.rollback()


def _discard(connection: Connection) -> None:
    """Roll back, and close the connection. Never raises, so the error that brought the request
    here is the one that gets mapped. If the rollback fails, the connection is invalidated: the
    pool drops it, and PostgreSQL aborts the transaction (releasing its locks) when the session
    ends. Only the exception class is logged, never its message."""
    try:
        if connection.in_transaction():
            _rollback(connection)
    except Exception as exc:
        logger.error("request transaction rollback failed: %s", type(exc).__name__)
        try:
            connection.invalidate()
        except Exception as inner:
            logger.error("request connection invalidate failed: %s", type(inner).__name__)
    finally:
        try:
            connection.close()
        except Exception as exc:
            logger.error("request connection close failed: %s", type(exc).__name__)


def _finish(slot: _RequestTransaction, *, commit: bool) -> None:
    """End the request transaction once. To commit: COMMIT, then close (the connection returns to
    the pool only after the COMMIT has returned); a failed COMMIT discards and re-raises. Otherwise
    discard."""
    connection = slot.take_for_ending()
    if connection is None:
        return
    if not commit:
        _discard(connection)
        return
    try:
        _commit(connection)
    except BaseException:
        _discard(connection)
        raise
    try:
        connection.close()
    except Exception as exc:  # the transaction is committed; do not report it as failed
        logger.error("request connection close failed: %s", type(exc).__name__)


async def commit_request_transaction(request: Request) -> AsyncIterator[None]:
    """App-wide, function-scoped dependency: it exits after the handler's result is serialized and
    before the response is sent, so the request transaction is committed (or rolled back) first.

    An async generator, so it receives a cancellation too (a sync generator dependency's exit is
    skipped for one). The COMMIT or ROLLBACK runs in a worker thread inside a shielded cancel
    scope: a cancellation cannot abandon it half done, and the connection is closed (returned to
    the pool) only after it returns. After a successful commit a pending cancellation surfaces at
    the checkpoint, so no response is sent for it. On the exception path the original exception is
    re-raised unchanged and nothing is added."""
    slot = _RequestTransaction()
    setattr(request.state, _STATE_NAME, slot)
    try:
        yield
    except BaseException:
        if slot.connection is not None:
            with anyio.CancelScope(shield=True):
                await anyio.to_thread.run_sync(lambda: _finish(slot, commit=False))
        raise
    if slot.connection is None:
        return
    with anyio.CancelScope(shield=True):
        await anyio.to_thread.run_sync(lambda: _finish(slot, commit=True))
    await anyio.lowlevel.checkpoint_if_cancelled()


def end_request_transaction(request: Request) -> None:
    """For a route that does engine-side work (its command opens its own transactions): commit the
    request transaction, which carried authentication and authorization only, and close the
    request connection, before the first engine-side effect. A failed commit raises here (mapped
    as usual) before any engine effect. The request connection must not be used afterwards."""
    slot = getattr(request.state, _STATE_NAME, None)
    if slot is None:
        return
    _finish(slot, commit=True)


def get_connection(
    request: Request, engine: Annotated[Engine, Depends(get_engine)]
) -> Iterator[Connection]:
    """One connection, one transaction, for the lifetime of a single request. Committed or rolled
    back by `commit_request_transaction` before the response is sent (never here). Refuses, before
    any statement, when that dependency is not installed or the request already opened a
    connection."""
    slot = getattr(request.state, _STATE_NAME, None)
    if not isinstance(slot, _RequestTransaction):
        raise RequestTransactionError("no request transaction owner is installed")
    if slot.connection is not None or slot.ended:
        raise RequestTransactionError("a request may open only one request connection")
    connection = engine.connect()
    try:
        connection.begin()
    except BaseException:
        connection.close()
        raise
    slot.connection = connection
    try:
        yield connection
    finally:
        # Backstop only: the commit dependency has ended the transaction by now.
        if not slot.ended:
            logger.error("request transaction was not ended by its owner; discarding")
            _finish(slot, commit=False)


def get_idempotency_key(
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> str | None:
    """The `Idempotency-Key` request header, validated to a bounded,
    restricted character set before it can reach `dnd_ai.api.idempotency`'s
    durable store, any log line, or any error response — never trusted
    verbatim (see `_IDEMPOTENCY_KEY_PATTERN` above).

    A missing header returns `None` (the caller does not want idempotent
    handling for this request); a present-but-malformed value raises a
    plain `ValueError`, mapped by the existing generic handler
    (`dnd_ai.api.errors.handle_value_error`) to a fixed, non-disclosing
    400 — never silently replaced with a generated value, since that would
    defeat the caller's own idempotency contract without telling it.

    Storing and deduplicating against a well-formed key is
    `dnd_ai.api.idempotency`'s job, not this dependency's — this function
    only validates and passes the value through, the same "header
    extraction, not the whole mechanism" scope
    `dnd_ai.api.auth.get_verified_token_claims` keeps relative to
    `get_authenticated_user_id`.
    """
    if idempotency_key is None:
        return None
    if not _IDEMPOTENCY_KEY_PATTERN.fullmatch(idempotency_key):
        raise ValueError("Idempotency-Key header is malformed.")
    return idempotency_key
