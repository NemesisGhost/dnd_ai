"""Correlation identifiers (docs/architecture/SYSTEM_ARCHITECTURE.md §19
"Observability" — every request should carry a correlation ID).

A client may supply `X-Correlation-Id`; otherwise one is generated. Either
way the same value is echoed back on the response and attached to
`request.state.correlation_id` so `dnd_ai.api.errors` can include it in
every error envelope (and log line — see that module's `_log_error`) and,
later, so commands can pass it through to audit records.

A client-supplied value is validated and bounded before any of that,
never trusted verbatim: an arbitrary header value could otherwise carry
control characters or newlines into a log line (log injection), or simply
be unbounded in length. `_MAX_CLIENT_CORRELATION_ID_LENGTH` and
`_CLIENT_CORRELATION_ID_PATTERN` intentionally accept a plain UUID (the
value this middleware itself generates) and similar bounded, printable
identifier shapes; anything else falls back to a freshly generated one
rather than rejecting the request outright — a malformed correlation ID is
the client's tooling being unhelpful, not a reason to fail the request it's
attached to.
"""

import re
import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

CORRELATION_ID_HEADER = "X-Correlation-Id"

_MAX_CLIENT_CORRELATION_ID_LENGTH = 100
_CLIENT_CORRELATION_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]+")


def _sanitize_client_correlation_id(value: str | None) -> str | None:
    if value is None:
        return None
    if not 1 <= len(value) <= _MAX_CLIENT_CORRELATION_ID_LENGTH:
        return None
    if not _CLIENT_CORRELATION_ID_PATTERN.fullmatch(value):
        return None
    return value


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        correlation_id = _sanitize_client_correlation_id(
            request.headers.get(CORRELATION_ID_HEADER)
        ) or str(uuid.uuid4())
        request.state.correlation_id = correlation_id
        response = await call_next(request)
        response.headers[CORRELATION_ID_HEADER] = correlation_id
        return response
