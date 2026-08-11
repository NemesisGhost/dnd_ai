"""The consistent error contract every API response uses
(docs/architecture/SYSTEM_ARCHITECTURE.md §5.2, §20 "Failure handling").

Every error response is one JSON envelope:

    {"error": {"code": "<stable_snake_case_code>", "message": "<human text>",
                "correlation_id": "<uuid or client-supplied value>",
                "fields": [{"field": "body.count", "code": "int_parsing"}]}}

`fields` is present only for request-validation failures (see
`handle_validation_error` below) and is deliberately limited to a field's
*location* and pydantic's own stable *error-type* code — never the message
text FastAPI/pydantic generate, and never the rejected value itself
(finding 4: a client-supplied field location and type code are safe to
echo; the value that failed validation, and any framework-generated prose
built from it, are not — a query, header, or body field can just as easily
be a password, a token, or another secret-looking value as an ordinary
one, and this module has no way to tell that apart, so it never echoes any
of them).

`code` is a stable identifier a client can branch on; `message` is
diagnostic text that may change wording between releases but never embeds
caller-supplied input, and never embeds an unclassified domain exception's
raw text either.

Domain and command code raises plain `ValueError` for validation failures
per docs/DEVELOPMENT.md §9; it does not need to know about HTTP at all.
By default that gets a **fixed, non-disclosing message** here, not
`str(exc)` — a bare `ValueError`'s text was authored for a developer
reading a traceback, not vetted for what it's safe to hand an
unauthenticated or unauthorized client, and nothing forces every future
call site to get that vetting right. A domain error that *has* been
deliberately vetted opts in by subclassing `dnd_ai.domain.errors.
SafeMessageError` (see that module for its now-tightened contract). Both
`SafeMessageError` and its `DomainAuthorizationError` subclass are handled
below via one handler, so any command or query raising one — now or in the
future — gets the right response automatically; nothing about it is
specific to any single error type.

Logging (finding 2): every handler below logs one fixed-shape, safe line —
exception class, the response's own error code and status, the request's
correlation ID, and the matched route *template* (never the concrete
request path, which can itself embed a resource ID or arbitrary
caller-supplied text) — through `_log_error()`. None of them ever logs
`str(exc)`, a traceback, or any other exception-specific text; that is
deliberate, not an oversight, and applies even to `logger.exception`-style
calls that would otherwise capture a traceback FastAPI/SQLAlchemy/psycopg
routinely embed a DSN, credential, or query parameter inside.
"""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse
from starlette.routing import Route

from dnd_ai.domain.errors import SafeMessageError

logger = logging.getLogger(__name__)

# PostgreSQL SQLSTATE classes (docs/architecture/SYSTEM_ARCHITECTURE.md §20
# "optimistic concurrency failures return a retriable conflict") — see
# handle_integrity_error. Class 23 is "Integrity Constraint Violation";
# unique_violation/exclusion_violation are the two shapes a concurrent
# writer produces (two requests racing to create/claim the same row), so
# retrying — typically after re-reading current state — is meaningful.
_RETRIABLE_INTEGRITY_SQLSTATES = frozenset({"23505", "23P01"})  # unique, exclusion

# not_null/foreign_key/check/restrict violation: the request itself asked
# for something invalid (a missing required field, a reference to something
# that doesn't exist, a value outside an allowed range) — retrying the same
# request verbatim cannot help; the request must change.
_INVALID_REQUEST_INTEGRITY_SQLSTATES = frozenset({"23502", "23503", "23514", "23001"})


class ApiError(Exception):
    """Base for errors an endpoint raises deliberately, with a chosen
    status code and stable error code, rather than an unexpected failure."""

    status_code: int = 500
    error_code: str = "internal_error"

    def __init__(
        self, message: str, *, error_code: str | None = None, status_code: int | None = None
    ) -> None:
        super().__init__(message)
        self.message = message
        if error_code is not None:
            self.error_code = error_code
        if status_code is not None:
            self.status_code = status_code


class UnauthorizedError(ApiError):
    """No valid authenticated identity — corresponds to HTTP 401."""

    status_code = 401
    error_code = "unauthorized"


class ForbiddenError(ApiError):
    """An authenticated identity without the required capability — HTTP
    403. Per §19.7, prefer `NotFoundError` when revealing that a resource
    exists at all would itself be a disclosure."""

    status_code = 403
    error_code = "forbidden"


class NotFoundError(ApiError):
    status_code = 404
    error_code = "not_found"


class ConflictError(ApiError):
    """A retriable optimistic-concurrency conflict (§20)."""

    status_code = 409
    error_code = "conflict"


def _correlation_id(request: Request) -> str | None:
    value = getattr(request.state, "correlation_id", None)
    return value if isinstance(value, str) else None


def _route_template(request: Request) -> str:
    """The matched route's *pattern* (e.g. `/campaigns/{campaign_id}`), not
    `request.url.path` — the concrete path can itself embed a resource ID
    or arbitrary caller-supplied text (a 404 for a made-up path is not
    matched to any `Route` at all, so this deliberately does not fall back
    to the raw path in that case either)."""
    route = request.scope.get("route")
    if isinstance(route, Route):
        return route.path
    return "<unmatched>"


def _log_error(
    request: Request,
    exc: BaseException,
    *,
    status_code: int,
    error_code: str,
    level: int = logging.INFO,
) -> None:
    """The one place any handler below logs anything about a failure —
    exception class, response status/code, correlation ID, and route
    template only. Never `str(exc)`, `repr(exc)`, or a traceback: those
    routinely embed exactly what finding 2 lists as unsafe (DSNs,
    credentials, SQL parameters, resource IDs, arbitrary request content)
    and there is no reliable way to scrub them generically. A domain error
    that wants specific, safe-to-log context defines it explicitly (see
    `dnd_ai.domain.errors.SafeMessageError`'s `safe_message` and
    `docs/DEVELOPMENT.md`'s note on sanitized diagnostics) rather than this
    function reaching into the exception's own text."""
    logger.log(
        level,
        "api_error exception_class=%s status_code=%s error_code=%s correlation_id=%s route=%s",
        type(exc).__name__,
        status_code,
        error_code,
        _correlation_id(request),
        _route_template(request),
    )


def _integrity_error_sqlstate(exc: IntegrityError) -> str | None:
    orig = exc.orig
    sqlstate = getattr(orig, "sqlstate", None)
    if isinstance(sqlstate, str):
        return sqlstate
    diag = getattr(orig, "diag", None)
    sqlstate = getattr(diag, "sqlstate", None) if diag is not None else None
    return sqlstate if isinstance(sqlstate, str) else None


def _envelope(
    request: Request,
    *,
    code: str,
    message: str,
    fields: list[dict[str, str]] | None = None,
) -> dict[str, dict[str, Any]]:
    error: dict[str, Any] = {
        "code": code,
        "message": message,
        "correlation_id": _correlation_id(request),
    }
    if fields is not None:
        error["fields"] = fields
    return {"error": error}


def install_error_handlers(app: FastAPI) -> None:
    """Register every exception handler so all error responses — deliberate
    `ApiError`s, framework routing/validation errors, domain `ValueError`s,
    database conflicts, and anything unanticipated — share one envelope
    shape. Registered once by `dnd_ai.api.app.create_app()`."""

    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(request, code=exc.error_code, message=exc.message),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(request, code="http_error", message=str(exc.detail)),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # exc.errors() carries an "input" entry with the raw rejected value (and a
        # "msg"/"url" built from it) for every error — exactly what finding 4 says
        # never to return. Keep only "loc" (a field location, e.g. body.count) and
        # "type" (pydantic's own stable error-type code, e.g. int_parsing): both are
        # about *shape*, never the value itself, so they're safe to echo regardless
        # of whether that field happened to hold a password, a token, or anything
        # else secret-looking.
        fields = [
            {"field": ".".join(str(part) for part in error["loc"]), "code": error["type"]}
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=_envelope(
                request,
                code="invalid_request",
                message="The request did not pass validation.",
                fields=fields,
            ),
        )

    @app.exception_handler(SafeMessageError)
    async def handle_safe_message_error(request: Request, exc: SafeMessageError) -> JSONResponse:
        # exc.safe_message is the only thing about exc this handler ever reads for
        # the response; see dnd_ai.domain.errors for why str(exc) never is.
        _log_error(request, exc, status_code=exc.safe_status_code, error_code=exc.safe_error_code)
        return JSONResponse(
            status_code=exc.safe_status_code,
            content=_envelope(request, code=exc.safe_error_code, message=exc.safe_message),
        )

    @app.exception_handler(ValueError)
    async def handle_value_error(request: Request, exc: ValueError) -> JSONResponse:
        # An *unclassified* domain ValueError — never partial writes, since the
        # command's own transaction rolls back before this handler ever runs (see
        # api/deps.py) — but also never str(exc) verbatim, logged or returned: that
        # text was written for a developer reading a traceback, not vetted for a
        # client (or a log stream other people can read). A SafeMessageError
        # (handled above, since FastAPI dispatches to the most specific registered
        # handler) is how a call site opts into exposing something more specific.
        _log_error(request, exc, status_code=400, error_code="validation_failed")
        return JSONResponse(
            status_code=400,
            content=_envelope(
                request, code="validation_failed", message="The request could not be processed."
            ),
        )

    @app.exception_handler(IntegrityError)
    async def handle_integrity_error(request: Request, exc: IntegrityError) -> JSONResponse:
        # A constraint the application layer didn't pre-check. Classify by SQLSTATE
        # (never by the exception's own message text, which routinely embeds the
        # constraint name, the offending values, or both) rather than assuming every
        # IntegrityError is a retriable conflict:
        sqlstate = _integrity_error_sqlstate(exc)
        if sqlstate in _RETRIABLE_INTEGRITY_SQLSTATES:
            # Two writers raced for the same row — retrying (typically after
            # re-reading current state) is meaningful, per §20.
            status_code, error_code, message = (
                409,
                "conflict",
                "The request could not be completed due to a conflicting change. Retry.",
            )
        elif sqlstate in _INVALID_REQUEST_INTEGRITY_SQLSTATES:
            # not_null/foreign_key/check/restrict — the request itself is invalid;
            # retrying it unchanged cannot help.
            status_code, error_code, message = (
                400,
                "validation_failed",
                "The request could not be processed.",
            )
        else:
            # An unrecognized SQLSTATE (or none available at all, e.g. a fake/other
            # DBAPI driver's exception in a test) — conservative by construction:
            # not confidently a retriable conflict, so no promise that retrying
            # helps, and not confidently a plain bad request either.
            status_code, error_code, message = (
                400,
                "validation_failed",
                "The request could not be processed.",
            )
        _log_error(
            request, exc, status_code=status_code, error_code=error_code, level=logging.WARNING
        )
        return JSONResponse(
            status_code=status_code, content=_envelope(request, code=error_code, message=message)
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        _log_error(request, exc, status_code=500, error_code="internal_error", level=logging.ERROR)
        return JSONResponse(
            status_code=500,
            content=_envelope(
                request, code="internal_error", message="An unexpected error occurred."
            ),
        )
