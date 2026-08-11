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

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy import Connection, Engine, create_engine

from dnd_ai.config import settings

_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
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
    """Placeholder passthrough for the `Idempotency-Key` request header.

    Storing and deduplicating against it is deferred to the first mutating
    command endpoint that needs it — most Phase 6-9 commands already derive
    their own idempotency from domain state (e.g. unique constraints on the
    row a retried command would otherwise duplicate), per
    docs/DEVELOPMENT.md §9. A generic dedup store is only worth building
    once a concrete command shows that isn't enough.
    """
    return idempotency_key
