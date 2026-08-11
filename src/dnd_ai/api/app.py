"""The FastAPI application entry point (docs/PLAN.md Phase 10 deliverable
list, docs/architecture/SYSTEM_ARCHITECTURE.md §5.2).

Deliberately excludes, for now: the Lambda ASGI adapter and any AWS/
Terraform deployment path (API Gateway, IAM, CloudWatch — those are
infrastructure decisions for a later pass, not application code), OIDC
token verification (needs its own scoping pass: library choice, JWKS
caching, and a no-live-provider test strategy per
docs/architecture/SYSTEM_ARCHITECTURE.md §22), and command/query endpoints
(each needs a request/response contract designed against a specific
`dnd_ai.commands`/future `dnd_ai.queries` call). This module is the
plumbing those land on: app factory, error contract, correlation IDs, and
per-request transaction management.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .correlation import CorrelationIdMiddleware
from .deps import dispose_engine
from .errors import install_error_handlers


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    try:
        yield
    finally:
        dispose_engine()


def create_app() -> FastAPI:
    app = FastAPI(title="D&D AI World Platform API", lifespan=_lifespan)
    app.add_middleware(CorrelationIdMiddleware)
    install_error_handlers(app)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
