"""The consistent error contract every API response uses
(docs/architecture/SYSTEM_ARCHITECTURE.md §5.2, §20 "Failure handling").

Every error response is one JSON envelope:

    {"error": {"code": "<stable_snake_case_code>", "message": "<human text>",
                "correlation_id": "<uuid or client-supplied value>",
                "error_codes": ["int_parsing", "missing"]}}

`error_codes` is present only for request-validation failures (see
`handle_validation_error` below) and never carries a field *location* —
only pydantic's own error-*type* codes, each independently bounded and
allowlisted by `_sanitize_validation_error_types` before being echoed
(finding 4 of this pass). An earlier version of this module echoed a
`loc`-derived "field" alongside each type code, on the theory that a
*location* — as opposed to the rejected *value* — was safe because it
described shape, not content. That was wrong: `loc` can itself be
caller-controlled text verbatim — an `extra="forbid"` model's rejected
extra key, a `dict[str, X]` body's own key, a discriminator value, an
input-derived alias — and no amount of character-shape filtering
("identifier-looking, under 60 characters") reliably tells a legitimate
dynamic key apart from a secret-looking one of the same shape (finding 1
of this pass: `SUPER_SECRET_TOKEN_ABC123` *is* identifier-shaped). Rather
than keep guessing, this module now omits every field location from the
generic validation response entirely; only the closed-vocabulary error
*type* codes remain, capped in count and validated against a fixed
identifier pattern.

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
`ValueError`) follows the identical discipline: `status_code`, `error_code`,
and `safe_message` are fixed, type-level class attributes, never derived
from or overridable through the constructor. The constructor accepts only
an optional `detail` string, available via `str(self)` for local/
interactive debugging only — never returned in a response, never logged.
An earlier version of this module also accepted `error_code=`/`status_code=`
constructor keyword arguments for "ad hoc" cases; that let any raise site
turn arbitrary runtime values into public response fields and log fields,
exactly the discipline this contract exists to prevent, so both are gone —
a real case gets its own narrowly scoped subclass (see `UnauthorizedError`/
`ForbiddenError`/`NotFoundError`/`ConflictError` below) instead. As further
defense in depth, `handle_api_error` below never trusts a subclass's
`status_code`/`error_code` blindly either: `_validated_api_error_response`
checks both against a small, fixed, server-owned vocabulary before they
reach a response or a log line, and falls back to the base class's own
fixed internal-error contract (500/`internal_error`) for anything that
doesn't match — including `ApiError` raised bare, with no subclass at all.

Framework-raised `StarletteHTTPException`s (FastAPI's own routing 404/405,
or any `HTTPException(...)` a call site raises directly) are handled the
same way: `exc.detail` is never trusted or echoed — it can be an arbitrary
string, dict, or list, supplied by FastAPI's routing internals or by any
future call site — only `exc.status_code` (an int the framework itself
sets from routing/dispatch logic, not free text) selects a fixed,
closed-vocabulary message from `_HTTP_EXCEPTION_MESSAGES`.

Logging: every handler below — including `handle_validation_error`, since
this pass's finding 3 closed the one handler that previously logged
nothing at all rather than something unsafe — logs one fixed-shape, safe
line through `_log_error()`: exception class, the response's own error
code and status, the request's correlation ID, and the matched route
*template* (never the concrete request path, which can itself embed a
resource ID or arbitrary caller-supplied text). None of them ever logs
`str(exc)`, a traceback, raw validation errors/locations/rejected input, a
request body, or any other exception-specific text; that is deliberate,
not an oversight, and applies even to `logger.exception`-style calls that
would otherwise capture a traceback FastAPI/SQLAlchemy/psycopg routinely
embed a DSN, credential, or query parameter inside.
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

# Request-validation error-type sanitization. `loc` (a field's *location*)
# is never echoed at all — see this module's docstring for why character-
# shape filtering on `loc` was not a reliable way to tell a legitimate
# dynamic key from a secret-looking one. `type` (pydantic's own stable
# error-type code, e.g. "int_parsing", "missing", "extra_forbidden") is a
# closed vocabulary pydantic itself defines for its built-in validators,
# but a custom validator can raise a `PydanticCustomError` with an
# arbitrary type string, so this module still bounds and allowlists it
# rather than trusting it outright: anything outside a short, lowercase,
# identifier-shaped pattern is replaced with a fixed fallback code. The
# error list itself is capped in count.
_MAX_VALIDATION_ERRORS = 20
_MAX_VALIDATION_ERROR_TYPE_LENGTH = 64
_VALIDATION_ERROR_TYPE_PATTERN = re.compile(
    rf"[a-z][a-z0-9_]{{0,{_MAX_VALIDATION_ERROR_TYPE_LENGTH - 1}}}"
)
_FALLBACK_VALIDATION_ERROR_TYPE = "invalid"

# ApiError's server-owned status/code vocabulary (finding 2). Every real
# ApiError subclass's (status_code, error_code) pair is listed here; a
# status code or error code that doesn't match — a stray typo in a future
# subclass, or a class attribute mutated at runtime some other way — is
# treated the same as an unclassified failure: the fixed internal-error
# contract, never trusted as-is. Kept in sync with `UnauthorizedError`/
# `ForbiddenError`/`NotFoundError`/`ConflictError` below.
_KNOWN_API_ERROR_STATUS_CODES = frozenset({401, 403, 404, 409})
_API_ERROR_CODE_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,63}")


class ApiError(Exception):
    """Base for errors an endpoint raises deliberately, with a chosen
    status code and stable error code, rather than an unexpected failure.

    `status_code`, `error_code`, and `safe_message` are fixed, type-level
    class attributes — the same discipline `dnd_ai.domain.errors.
    SafeMessageError` uses, and for the same reason: a raise site cannot
    make arbitrary values client-visible (or logged) just by choosing what
    to pass to the constructor. The constructor accepts only an optional
    `detail` string, available via `str(self)`/`repr(self)` purely for
    local, interactive debugging; `dnd_ai.api.errors` never reads it for a
    response or a log line (see `_log_error`). There is deliberately no
    `error_code=`/`status_code=` constructor override — a real case defines
    its own narrowly scoped subclass (as `UnauthorizedError`/
    `ForbiddenError`/`NotFoundError`/`ConflictError` do below) rather than
    this module growing a generalized, dynamically-parameterized error
    registry. `handle_api_error` additionally never trusts even a
    subclass's `status_code`/`error_code` outright — see
    `_validated_api_error_response` and `_KNOWN_API_ERROR_STATUS_CODES`
    above.
    """

    status_code: int = 500
    error_code: str = "internal_error"
    safe_message: str = "The request could not be processed."

    def __init__(self, detail: str | None = None) -> None:
        super().__init__(detail or self.safe_message)


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
    template only. Never `str(exc)`, `repr(exc)`, a traceback, or (for
    `handle_validation_error`) any raw validation error, field location,
    rejected input, or request body: those routinely embed exactly what
    finding 2 of the prior pass lists as unsafe (DSNs, credentials, SQL
    parameters, resource IDs, arbitrary request content) and there is no
    reliable way to scrub them generically. A domain error that wants
    specific, safe-to-log context defines it explicitly (see
    `dnd_ai.domain.errors.SafeMessageError`'s `safe_message`) rather than
    this function reaching into the exception's own text."""
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


def _sanitize_validation_error_types(errors: Sequence[Any]) -> list[str]:
    """`error["type"]` only, never `error["loc"]` — see this module's
    docstring for why a field *location* is never echoed at all, no matter
    how it's filtered. Each `type` is itself replaced with a fixed fallback
    unless it matches a short, lowercase, identifier-shaped pattern (a
    custom pydantic validator can raise `PydanticCustomError` with an
    arbitrary type string, so even this closed-looking vocabulary isn't
    trusted outright). The error list is capped in count — an oversized
    error collection is its own kind of unbounded response."""
    sanitized = []
    for error in errors[:_MAX_VALIDATION_ERRORS]:
        error_type = error["type"]
        sanitized.append(
            error_type
            if isinstance(error_type, str) and _VALIDATION_ERROR_TYPE_PATTERN.fullmatch(error_type)
            else _FALLBACK_VALIDATION_ERROR_TYPE
        )
    return sanitized


def _validated_api_error_response(exc: ApiError) -> tuple[int, str, str]:
    """Finding 2: even a subclass's own class-attribute `status_code`/
    `error_code` are checked against a small, fixed, server-owned
    vocabulary before reaching a response or a log line, rather than
    trusted outright — anything that doesn't match (a stray typo in a
    future subclass, a class attribute mutated some other way at runtime)
    falls back to `ApiError`'s own fixed internal-error contract, exactly
    like any other unclassified failure."""
    if exc.status_code in _KNOWN_API_ERROR_STATUS_CODES and _API_ERROR_CODE_PATTERN.fullmatch(
        exc.error_code
    ):
        return exc.status_code, exc.error_code, exc.safe_message
    return ApiError.status_code, ApiError.error_code, ApiError.safe_message


def _envelope(
    request: Request,
    *,
    code: str,
    message: str,
    error_codes: list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    error: dict[str, Any] = {
        "code": code,
        "message": message,
        "correlation_id": _correlation_id(request),
    }
    if error_codes is not None:
        error["error_codes"] = error_codes
    return {"error": error}


def install_error_handlers(app: FastAPI) -> None:
    """Register every exception handler so all error responses — deliberate
    `ApiError`s, framework routing/validation errors, domain `ValueError`s,
    database conflicts, and anything unanticipated — share one envelope
    shape. Registered once by `dnd_ai.api.app.create_app()`."""

    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        # _validated_api_error_response re-checks exc's own class attributes
        # against a fixed vocabulary before anything about exc reaches the
        # response or the log line; see this module's docstring and ApiError's
        # own docstring for why the constructor's detail text never does.
        status_code, error_code, message = _validated_api_error_response(exc)
        _log_error(request, exc, status_code=status_code, error_code=error_code)
        return JSONResponse(
            status_code=status_code,
            content=_envelope(request, code=error_code, message=message),
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
        # "msg"/"url" built from it) for every error, and a "loc" entry that can
        # itself be caller-supplied text (an extra="forbid" model's rejected extra
        # key, a dict[str, X] body's own key, a discriminator value, an
        # input-derived alias) — none of that is echoed or logged. Only
        # `_sanitize_validation_error_types` — pydantic's own error-type codes,
        # bounded and allowlisted, never a location — reaches the response; the
        # log line carries only the fixed classification below, exactly like
        # every other handler in this module.
        _log_error(request, exc, status_code=422, error_code="invalid_request")
        return JSONResponse(
            status_code=422,
            content=_envelope(
                request,
                code="invalid_request",
                message="The request did not pass validation.",
                error_codes=_sanitize_validation_error_types(exc.errors()),
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
