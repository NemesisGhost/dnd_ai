"""The FastAPI application entry point (docs/PLAN.md Phase 10 deliverable
list, docs/architecture/SYSTEM_ARCHITECTURE.md §5.2).

Portable by design (ADR 0012, docs/LOCAL_DEPLOYMENT.md): FastAPI runs under
Uvicorn, in a container or otherwise, and talks to PostgreSQL over the
network — there is nothing AWS- or Lambda-specific in this module or
anywhere else in this package. A Lambda ASGI adapter is not required for
production and does not exist here; if one is ever added it belongs in an
isolated, optional module of its own, per ADR 0012's "Lambda, Mangum, API
Gateway, RDS, or another cloud adapter may be added as isolated optional
deployment adapters, but none is required for production."

OIDC bearer-token verification (`dnd_ai.api.auth`/`dnd_ai.domain.tokens`)
is delivered and used by the command endpoints below
(`dnd_ai.api.encounters`, `dnd_ai.api.items`, `dnd_ai.api.quests`) via
`dnd_ai.api.access`. This module remains the
plumbing every router builds on: app factory, error contract, correlation
IDs, health/readiness, per-request transaction management, and
authentication — routers register their own paths, this module only
mounts them.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI
from sqlalchemy import Engine, text
from starlette.responses import JSONResponse

from .auth import dispose_jwks_client
from .correlation import CorrelationIdMiddleware
from .deps import dispose_engine, get_engine
from .encounters import router as encounters_router
from .errors import install_error_handlers
from .items import router as items_router
from .quests import router as quests_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    try:
        yield
    finally:
        dispose_engine()
        dispose_jwks_client()


def create_app() -> FastAPI:
    app = FastAPI(title="D&D AI World Platform API", lifespan=_lifespan)
    app.add_middleware(CorrelationIdMiddleware)
    install_error_handlers(app)
    app.include_router(encounters_router)
    app.include_router(items_router)
    app.include_router(quests_router)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        """Cheap process-liveness only — no database, no I/O. This is what
        a container orchestrator restarts the process over if it stops
        answering; it must never itself depend on PostgreSQL being up, or a
        database outage would also make the process look dead rather than
        just not-yet-ready (docs/LOCAL_DEPLOYMENT.md "Operations")."""
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz(engine: Annotated[Engine, Depends(get_engine)]) -> JSONResponse:
        """Whether this instance can actually serve traffic: required
        configuration loaded (implicitly true by the time this runs —
        `dnd_ai.config.Settings()` fails process startup outright otherwise,
        see that module) and a minimal PostgreSQL round trip through the
        same engine/connection wiring every other endpoint uses — not a
        parallel, unrepresentative connection. Suitable for a Docker Compose
        `healthcheck:` hitting this over the private network
        (docs/LOCAL_DEPLOYMENT.md "Compose responsibilities and network
        policy") — never needs its own PostgreSQL or Uvicorn port exposed.
        Failure returns 503 and a fixed, non-secret body. The underlying
        exception is never logged as `str(exc)` or with its traceback
        (`exc_info=True`) — a driver connection failure routinely embeds
        the DSN, host, database name, or username in its message, and
        SQLAlchemy/psycopg exceptions are not guaranteed to keep a
        password out of that text either. Only the exception's class name
        (e.g. `OperationalError`) is logged — enough to distinguish
        "database unreachable" from "some other bug in this handler"
        operationally, without risking a secret in the log stream."""
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except Exception as exc:
            logger.warning(
                "readiness check failed: database round trip did not succeed (%s)",
                type(exc).__name__,
            )
            return JSONResponse(status_code=503, content={"status": "not_ready"})
        return JSONResponse(status_code=200, content={"status": "ready"})

    return app


app = create_app()
