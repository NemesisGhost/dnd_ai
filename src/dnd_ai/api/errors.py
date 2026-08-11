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
of them). Even a *location* component can be caller-controlled — an
`extra="forbid"` model's rejected extra key, or a `dict[str, X]` body's own
key, becomes a `loc` entry verbatim — so `_sanitize_validation_fields`
bounds how many field errors, how many location components each, and how
long/what-shaped each component may be before it is ever echoed; anything
outside that closed shape is replaced with a fixed placeholder rather than
truncated (a truncated secret is still a partial secret).

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
SafeMessageError` (see that module for its contract). Both
`SafeMessageError` and its `DomainAuthorizationError` subclass are handled
below via one handler, so any command or query raising one — now or in the
future — gets the right response automatically; nothing about it is
specific to any single error type.

`ApiError` (raised deliberately by endpoint code, as opposed to a domain
`ValueError`) follows the identical discipline: `safe_message` is a fixed,
type-level class attribute, never derived from the constructor argument.
The constructor's `detail` argument remains available via `str(self)` for
local/interactive debugging only — never returned in a response, never
logged. A raise site cannot make arbitrary text client-visible just by
choosing what string to pass; only a subclass that deliberately defines
its own fixed `safe_message` can expose something specific.

Framework-raised `StarletteHTTPException`s (FastAPI's own routing 404/405,
or any `HTTPException(...)` a call site raises directly) are handled the
same way: `exc.detail` is never trusted or echoed — it can be an arbitrary
string, dict, or list, supplied by FastAPI's routing internals or by any
future call site — only `exc.status_code` (an int the framework itself
sets from routing/dispatch logic, not free text) selects a fixed,
closed-vocabulary message from `_HTTP_EXCEPTION_MESSAGES`.

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
import re
from collections.abc import Sequence
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse
from starlette.routing import Route

from dnd_ai.domain.errors import SafeMessageError

logger = logging.getLogger(__name__)

# PostgreSQL SQLSTATE classes (docs/architecture/SYSTEM_ARCHITECTURE.md §20)
# — see handle_integrity_error. Class 23 is "Integrity Constraint
# Violation"; unique_violation/exclusion_violation are the two shapes a
# concurrent writer produces (two requests racing to create/claim the same
# row). That is a genuine conflict — HTTP 409 — but not, by itself, a
# demonstrated case where retrying the *same* request is meaningful (a
# unique violation can just as easily mean the request should never
# succeed at all); the response deliberately makes no retry promise. A
# command that recognizes a specific, genuine optimistic-concurrency or
# idempotency conflict should represent that with its own application/
# domain exception whose public contract can say whether re-reading or
# retrying is appropriate — this generic mapping does not.
_CONFLICT_INTEGRITY_SQLSTATES = frozenset({"23505", "23P01"})  # unique, exclusion

# not_null/foreign_key/check/restrict violation: the request itself asked
# for something invalid (a missing required field, a reference to something
# that doesn't exist, a value outside an allowed range) — retrying the same
# request verbatim cannot help; the request must change.
_INVALID_REQUEST_INTEGRITY_SQLSTATES = frozenset({"23502", "23503", "23514", "23001"})

# A missing or unrecognized SQLSTATE is not confidently classifiable as
# either of the above — that ambiguity is itself evidence of an
# application/schema/runtime defect (an unanticipated constraint, a driver
# this code doesn't know how to introspect, a fake/other DBAPI exception in
# a test) rather than something the caller could have asked for
# differently. It maps to a fixed 500, exactly like any other unclassified
# failure — never a guess at 400 vs. 409 (finding 2).

# Standard routing statuses FastAPI/Starlette itself raises `HTTPException`
# for, mapped to a fixed, closed-vocabulary (error_code, message) — never
# `exc.detail`, which is free text/dict/list a call site (framework or
# application) supplies and this module has no way to vet.
_HTTP_EXCEPTION_MESSAGES: dict[int, tuple[str, str]] = {
    404: ("not_found", "The requested resource does not exist or is not accessible."),
    405: ("method_not_allowed", "The HTTP method is not allowed for this route."),
}
_DEFAULT_HTTP_EXCEPTION_ERROR_CODE = "http_error"
_DEFAULT_HTTP_EXCEPTION_MESSAGE = "The request could not be processed."

# Request-validation field-location sanitization (finding 4). A pydantic
# `loc` component is safe to echo only when it is short and shaped like an
# ordinary field name or array index — never merely because it happened to
# be under some byte limit, since a truncated secret is still a partial
# secret. Anything outside that closed shape is replaced wholesale.
_MAX_VALIDATION_FIELD_ERRORS = 20
_MAX_VALIDATION_LOC_COMPONENTS = 10
_MAX_VALIDATION_LOC_COMPONENT_LENGTH = 60
_MAX_VALIDATION_LOC_INDEX = 100_000
_VALIDATION_LOC_COMPONENT_PATTERN = re.compile(
    rf"[A-Za-z0-9_]{{1,{_MAX_VALIDATION_LOC_COMPONENT_LENGTH}}}"
)
_REDACTED_LOC_COMPONENT = "<redacted>"


class ApiError(Exception):
    """Base for errors an endpoint raises deliberately, with a chosen
    status code and stable error code, rather than an unexpected failure.

    `safe_message` is a fixed, type-level class attribute — the same
    discipline `dnd_ai.domain.errors.SafeMessageError` uses, and for the
    same reason: a raise site cannot make arbitrary text client-visible
    just by choosing what string to pass to the constructor. The `detail`
    constructor argument remains available via `str(self)`/`repr(self)`
    purely for local, interactive debugging; `dnd_ai.api.errors` never
    reads it for a response or a log line (see `_log_error`). A subclass
    that has something genuinely safe and specific to say sets its own
    fixed `safe_message` (as the subclasses below do), or overrides it as
    a `@property` computed from a closed, server-owned vocabulary — never
    from `detail` or other caller-influenced input.
    """

    status_code: int = 500
    error_code: str = "internal_error"
    safe_message: str = "The request could not be processed."

    def __init__(
        self,
        detail: str | None = None,
        *,
        error_code: str | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(detail or self.safe_message)
        if error_code is not None:
            self.error_code = error_code
        if status_code is not None:
            self.status_code = status_code


class UnauthorizedError(ApiError):
    """No valid authenticated identity — corresponds to HTTP 401."""

    status_code = 401
    error_code = "unauthorized"
    safe_message = "Authentication is required."


class ForbiddenError(ApiError):
    """An authenticated identity without the required capability — HTTP
    403. Per §19.7, prefer `NotFoundError` when revealing that a resource
    exists at all would itself be a disclosure."""

    status_code = 403
    error_code = "forbidden"
    safe_message = "You do not have permission to perform this action."


class NotFoundError(ApiError):
    status_code = 404
    error_code = "not_found"
    safe_message = "The requested resource does not exist or is not accessible."


class ConflictError(ApiError):
    """A conflicting-change response (§20). Deliberately makes no retry
    promise — see `_CONFLICT_INTEGRITY_SQLSTATES` above for why a generic
    conflict cannot claim retrying will help. A command that recognizes a
    specific, genuine optimistic-concurrency case should say so through its
    own subclass with its own `safe_message`."""

    status_code = 409
    error_code = "conflict"
    safe_message = "The request could not be completed due to a conflicting change."


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


def _sanitize_validation_loc_component(component: object) -> str:
    """A single `loc` entry is safe to echo only when it is shaped like an
    ordinary field name (identifier characters, bounded length) or a
    bounded array index — never merely because it happened to fit under
    some byte limit. `loc` can otherwise carry an `extra="forbid"` model's
    rejected extra key, or a `dict[str, X]` body's own key, verbatim from
    the request — either of which could as easily be a token or password
    as an ordinary field name, and this function has no way to tell those
    apart, so anything outside the closed shape below is replaced
    wholesale rather than truncated."""
    if isinstance(component, int) and not isinstance(component, bool):
        return (
            str(component)
            if 0 <= component <= _MAX_VALIDATION_LOC_INDEX
            else _REDACTED_LOC_COMPONENT
        )
    text = str(component)
    return text if _VALIDATION_LOC_COMPONENT_PATTERN.fullmatch(text) else _REDACTED_LOC_COMPONENT


def _sanitize_validation_fields(errors: Sequence[Any]) -> list[dict[str, str]]:
    """See `_sanitize_validation_loc_component` and this module's docstring
    (finding 4). Also bounds how many field errors are returned at all —
    an oversized error list is its own kind of unbounded response."""
    fields = []
    for error in errors[:_MAX_VALIDATION_FIELD_ERRORS]:
        loc = error["loc"][:_MAX_VALIDATION_LOC_COMPONENTS]
        field = ".".join(_sanitize_validation_loc_component(part) for part in loc)
        fields.append({"field": field, "code": error["type"]})
    return fields


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
        # exc.safe_message is the only thing about exc this handler ever reads for
        # the response or the log line; see this module's docstring and ApiError's
        # own docstring for why the constructor's detail text never is.
        _log_error(request, exc, status_code=exc.status_code, error_code=exc.error_code)
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(request, code=exc.error_code, message=exc.safe_message),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        # exc.detail is framework/caller-influenced text — FastAPI's own routing
        # detail, or a raw string/dict/list any call site could pass to
        # HTTPException(...) — never trusted or echoed. Only exc.status_code (an
        # int FastAPI/Starlette sets from routing/dispatch logic, not free text)
        # selects a fixed, closed-vocabulary message.
        error_code, message = _HTTP_EXCEPTION_MESSAGES.get(
            exc.status_code, (_DEFAULT_HTTP_EXCEPTION_ERROR_CODE, _DEFAULT_HTTP_EXCEPTION_MESSAGE)
        )
        _log_error(request, exc, status_code=exc.status_code, error_code=error_code)
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(request, code=error_code, message=message),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # exc.errors() carries an "input" entry with the raw rejected value (and a
        # "msg"/"url" built from it) for every error — exactly what finding 4 says
        # never to return. "type" is pydantic's own stable error-type code (e.g.
        # int_parsing) — a closed vocabulary pydantic defines, never caller text —
        # so it is always safe to echo. "loc" is a field *location*, but one or
        # more of its components can themselves be caller-supplied (an
        # extra="forbid" model's rejected extra key, a dict[str, X] body's own
        # key) — see `_sanitize_validation_fields`.
        return JSONResponse(
            status_code=422,
            content=_envelope(
                request,
                code="invalid_request",
                message="The request did not pass validation.",
                fields=_sanitize_validation_fields(exc.errors()),
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
        # constraint name, the offending values, or both):
        sqlstate = _integrity_error_sqlstate(exc)
        level = logging.WARNING
        if sqlstate in _CONFLICT_INTEGRITY_SQLSTATES:
            # Two writers raced for the same row — a genuine conflict, but not a
            # demonstrated case where retrying the same request would help, so the
            # response makes no retry promise (finding 3).
            status_code, error_code, message = (
                409,
                "conflict",
                "The request could not be completed due to a conflicting change.",
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
            # A missing or unrecognized SQLSTATE is not confidently classifiable as
            # either of the above — that ambiguity is itself evidence of an
            # application/schema/runtime defect (an unanticipated constraint, a
            # driver this code doesn't know how to introspect), not something the
            # caller could have asked for differently. Fixed 500, never a guess at
            # 400 vs. 409 (finding 2).
            status_code, error_code, message = (
                500,
                "internal_error",
                "An unexpected error occurred.",
            )
            level = logging.ERROR
        _log_error(request, exc, status_code=status_code, error_code=error_code, level=level)
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
