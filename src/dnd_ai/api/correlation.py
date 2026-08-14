"""Correlation identifiers (docs/architecture/SYSTEM_ARCHITECTURE.md §19
"Observability" — every request should carry a correlation ID).

A client may supply `X-Correlation-Id`; otherwise one is generated. Either
way the same value is echoed back on the response and attached to
`request.state.correlation_id` so `dnd_ai.api.errors` can include it in
every error envelope (and log line — see that module's `_log_error`) and,
later, so commands can pass it through to audit records.

A client-supplied value is validated and normalized before any of that,
never trusted verbatim. The accepted shape is deliberately narrow: a
canonical UUID (the same shape this middleware itself generates, and the
shape most client tracing/logging libraries already emit) — nothing else.
Bounding *length and character set* alone (an earlier version of this
module accepted `[A-Za-z0-9._-]{1,100}`) is not enough: that range still
admits arbitrary token- or password-like text, which would then be echoed
on the response and included in every log line for the request (finding
5). Restricting to one closed, fixed-length identifier format removes that
risk structurally rather than trying to distinguish "identifier-shaped"
from "secret-shaped" text within a wide character class. Anything that
doesn't parse as a canonical UUID — including a well-formed but
non-UUID identifier, control characters, or an overlong value — falls back
to a freshly generated one rather than rejecting the request outright: a
malformed correlation ID is the client's tooling being unhelpful, not a
reason to fail the request it's attached to. A matching value is
normalized to lowercase (RFC 4122 case is not significant, and every
value this middleware itself generates is already lowercase) so two
clients that differ only in hex-digit case are not treated as carrying
different correlation IDs downstream.
"""

import re
import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

CORRELATION_ID_HEADER = "X-Correlation-Id"


def get_request_correlation_id(request: Request) -> str | None:
    """The current request's correlation ID, as `CorrelationIdMiddleware`
    already validated and attached to `request.state.correlation_id` — a
    canonical, lowercase UUID string, or `None` if the middleware hasn't
    run (e.g. a unit test constructing a bare `Request`). FastAPI-dependency
    shaped (takes `Request`, nothing else) so route handlers can depend on
    it directly; `dnd_ai.api.errors._correlation_id` reads the exact same
    attribute for error envelopes/log lines rather than duplicating this
    logic."""
    value = getattr(request.state, "correlation_id", None)
    return value if isinstance(value, str) else None


_CANONICAL_UUID_PATTERN = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


def _sanitize_client_correlation_id(value: str | None) -> str | None:
    if value is None:
        return None
    if not _CANONICAL_UUID_PATTERN.fullmatch(value):
        return None
    return value.lower()


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
