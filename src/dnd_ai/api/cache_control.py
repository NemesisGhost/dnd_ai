"""`Cache-Control: no-store` for application responses (Phase 15.1).

Authoring reads return drafts, GM-only fields, and per-actor action lists, and
every authenticated read depends on the caller's *current* authority. None of
it may be stored by a browser or an intermediary, or a user who lost
`canon.edit` could re-read a cached draft. One middleware sets the header on
every response that has not set its own, except the unauthenticated liveness
and readiness probes (`/healthz`, `/readyz`), which carry no user data and are
polled by the orchestrator.
"""

from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_EXEMPT_PATHS = frozenset({"/healthz", "/readyz"})


class NoStoreMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        if request.url.path not in _EXEMPT_PATHS and "cache-control" not in response.headers:
            response.headers["Cache-Control"] = "no-store"
        return response
