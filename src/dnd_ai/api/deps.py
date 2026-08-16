"""Request-scoped database transactions and idempotency-key parsing.

`get_engine` is a process-wide singleton overridden wholesale in tests via
`app.dependency_overrides` (docs/architecture/SYSTEM_ARCHITECTURE.md §5.2 —
the API layer owns this wiring, not `dnd_ai.config` or the command layer).
`get_connection` opens one transaction per request and commits or rolls
back around the handler, matching the one-transaction-per-world-change rule
every command already follows on its own when called directly; going
through the API just means the API layer, not the command, now owns that
boundary.
"""

import re
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Header
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


def get_connection(engine: Annotated[Engine, Depends(get_engine)]) -> Iterator[Connection]:
    """One connection, one transaction, for the lifetime of a single
    request. Commits when the handler returns normally; rolls back if it
    raises — including a `dnd_ai.api.errors.ApiError` or a domain
    `ValueError`, so a validation failure never leaves a partial write
    (docs/architecture/SYSTEM_ARCHITECTURE.md §20)."""
    with engine.connect() as connection, connection.begin():
        yield connection


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
