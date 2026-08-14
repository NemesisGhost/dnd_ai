"""Request-scoped dependencies: database transaction/session management and
the idempotency-key passthrough (docs/architecture/SYSTEM_ARCHITECTURE.md
§7 "Transaction boundary", docs/PLAN.md Phase 10 deliverables).

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
from sqlalchemy import Connection, Engine, create_engine

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
