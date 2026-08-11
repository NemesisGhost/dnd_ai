"""Correlation identifiers (docs/architecture/SYSTEM_ARCHITECTURE.md §19
"Observability" — every request should carry a correlation ID).

A client may supply `X-Correlation-Id`; otherwise one is generated. Either
way the same value is echoed back on the response and attached to
`request.state.correlation_id` so `dnd_ai.api.errors` can include it in
every error envelope and, later, so commands can pass it through to audit
records.
"""

import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

CORRELATION_ID_HEADER = "X-Correlation-Id"


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        correlation_id = request.headers.get(CORRELATION_ID_HEADER) or str(uuid.uuid4())
        request.state.correlation_id = correlation_id
        response = await call_next(request)
        response.headers[CORRELATION_ID_HEADER] = correlation_id
        return response
