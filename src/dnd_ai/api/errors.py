"""The consistent error contract every API response uses
(docs/architecture/SYSTEM_ARCHITECTURE.md §5.2, §20 "Failure handling").

Every error response is one JSON envelope:

    {"error": {"code": "<stable_snake_case_code>", "message": "<human text>",
                "correlation_id": "<uuid or client-supplied value>",
                "error_codes": ["invalid_type", "missing"]}}

`error_codes` is present only for request-validation failures (see
`handle_validation_error` below) and never carries a field *location* — a
prior pass already established that no amount of character-shape
filtering on `loc` reliably tells a legitimate dynamic key apart from a
secret-looking one of the same shape, so a location is never echoed at
all. Each entry is one of a small, fixed, public vocabulary this module
owns (`missing`, `invalid_type`, `invalid_format`, `out_of_range`,
`invalid`) — never pydantic's own internal `type` string echoed directly.
An earlier version of this module accepted any lowercase, identifier-
shaped pydantic `type` string as "safe enough" to echo, on the theory
that pydantic's built-in error-type vocabulary was closed. That was
wrong on two counts: a custom validator can raise `PydanticCustomError`
with an arbitrary type string of exactly that shape (so
`secret_token_abc123` passed the same character check a real pydantic
type would), and even pydantic's own vocabulary is not something this
module should commit to mirroring — it is internal to pydantic and can
change between versions. `_sanitize_validation_error_types` now maps a
fixed, closed set of real pydantic type strings this module has
deliberately chosen to distinguish onto the five public codes above by
exact dict lookup — never by regex/shape — and anything not in that set,
built-in or custom, becomes `invalid`. The error list is still capped in
count.

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
`ForbiddenError`/`NotFoundError`/`ConflictError` below) instead.

`handle_api_error` never trusts even a recognized subclass's own
`status_code`/`error_code`/`safe_message` attributes at face value either.
A still-later version of this module tried to validate them independently
— any identifier-shaped `error_code` paired with any status from a small
set — which is not the same thing as the documented vocabulary and does
not enforce that a *particular* status, code, and message actually go
together as one of the contracts this module has deliberately defined.
`_API_ERROR_CONTRACTS` now maps each *exact recognized exception type* to
its one fixed `(status_code, error_code, safe_message)` triple;
`_validated_api_error_response` looks up `type(exc)` and additionally
checks that the exception's own current attributes still equal the
recorded triple exactly, so a subclass this module doesn't recognize, or
any mismatch — an unfamiliar `error_code`, a status paired with the wrong
code, or an altered message on an otherwise-known type — all fall back to
the fixed internal-error contract identically, in both the response and
the log line.

Framework-raised `StarletteHTTPException`s (FastAPI's own routing 404/405,
or any `HTTPException(...)` a call site raises directly) are handled the
same way, and for the same reason `exc.status_code` alone is not trusted
either, not just `exc.detail`: `_SUPPORTED_HTTP_EXCEPTION_STATUSES` is an
explicit, closed mapping of only the framework statuses this application
deliberately supports (currently just FastAPI/Starlette's own routing 404
and 405). Any other status — an unrecognized-but-HTTP-shaped code like 418
or 499, an out-of-range value like 99 or 999, or anything else a call site
might pass to `HTTPException(status_code=...)` — produces the fixed
500/`internal_error` contract instead of forwarding that status to the
response; `exc.detail` remains never trusted or echoed regardless of which
branch is taken. `exc.headers` is treated the same way: it is never
forwarded, since a directly raised `HTTPException(status_code=405,
headers={...})` could carry any header a caller or a careless call site
chose. A 405 response instead carries an `Allow` header this module
recomputes itself, from the matched route's own declared `methods` (see
`_method_not_allowed_allow_header`) — trusted routing data, not anything
read off `exc`.

Every unclassified/fallback path in this module — a bare or unrecognized
`ApiError`, an unsupported `HTTPException` status, an `IntegrityError`
with a missing or unrecognized SQLSTATE, and any genuinely unexpected
`Exception` — returns and logs the identical `_INTERNAL_ERROR_CONTRACT`
(500/`internal_error`/"An unexpected error occurred."), one constant
defined once near the top of this module. An earlier version of this
module had each of those paths hardcode its own copy of that contract,
and one of them (`ApiError`'s own base-class `safe_message`) had drifted
to different wording ("The request could not be processed.") — the same
*category* of failure described two different ways depending on which
handler happened to catch it, even though nothing about "an unclassified
failure occurred" differs between them.

Logging: every handler below computes exactly one validated
`(status_code, error_code, message)` triple and reuses the same
`status_code`/`error_code` for both `_log_error()` and the response —
never a second, independently derived classification for the log line, so
an unknown `ApiError` or `HTTPException` always logs the identical fixed
`internal_error`/500 it also returns, not something more specific it
failed to validate as safe. `_log_error()` itself logs one fixed-shape,
safe line: exception class, that status/error code, the request's
correlation ID, and the matched route *template* (never the concrete
request path, which can itself embed a resource ID or arbitrary
caller-supplied text). None of them ever logs `str(exc)`, a traceback,
raw validation errors/locations/rejected input, a request body, or any
other exception-specific text; that is deliberate, not an oversight, and
applies even to `logger.exception`-style calls that would otherwise
capture a traceback FastAPI/SQLAlchemy/psycopg routinely embed a DSN,
credential, or query parameter inside.
"""

import logging
from collections.abc import Sequence
from typing import Any, NamedTuple

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse
from starlette.routing import Route

from dnd_ai.domain.errors import SafeMessageError

logger = logging.getLogger(__name__)


class _ErrorContract(NamedTuple):
    """A complete, fixed `(status_code, error_code, safe_message)` triple —
    the unit every handler below validates and returns as one piece,
    never as independently-checked fields (see `ApiError`'s docstring for
    why that independent-field checking was itself a prior gap)."""

    status_code: int
    error_code: str
    safe_message: str


# The one canonical, immutable 500/internal_error contract every
# unclassified/fallback path in this module returns and logs — never a
# handler-specific literal invented ad hoc. Before this constant existed,
# an unknown/tampered ApiError used "The request could not be processed."
# (ApiError's own base-class safe_message) while an unsupported
# HTTPException status, an unclassified IntegrityError, and a genuinely
# unexpected Exception each separately hardcoded "An unexpected error
# occurred." — the same *category* of failure (nothing more specific is
# known) described with two different wordings depending on which handler
# happened to catch it. `ApiError`'s own class attributes are defined
# *from* this constant below, so a bare `ApiError()` is itself exactly
# this contract, not a fourth independently-maintained copy.
_INTERNAL_ERROR_CONTRACT = _ErrorContract(500, "internal_error", "An unexpected error occurred.")

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
# application) supplies and this module has no way to vet. This is the
# complete set of framework HTTP statuses this application supports; any
# other status — including a well-formed-looking one like 418 or an
# out-of-range one like 999 — is not forwarded to the response at all (see
# `handle_http_exception`'s fallback to the fixed internal-error contract).
_SUPPORTED_HTTP_EXCEPTION_STATUSES: dict[int, tuple[str, str]] = {
    404: ("not_found", "The requested resource does not exist or is not accessible."),
    405: ("method_not_allowed", "The HTTP method is not allowed for this route."),
}

# Request-validation public error-code vocabulary (finding 2). `loc` (a
# field's *location*) is never echoed at all — see this module's docstring
# for why character-shape filtering on `loc` was not a reliable way to
# tell a legitimate dynamic key from a secret-looking one. `type`
# (pydantic's own internal error-type string, e.g. "int_parsing",
# "missing") is not echoed either, even when it looks like ordinary
# pydantic vocabulary: a custom validator can raise `PydanticCustomError`
# with an arbitrary type string of the same shape, and pydantic's own
# vocabulary is internal to pydantic, not a contract this module should
# commit to mirroring. Instead, only the fixed public codes below are ever
# returned; `_VALIDATION_TYPE_TO_PUBLIC_CODE` maps a closed, explicit set
# of real pydantic type strings this module has chosen to distinguish onto
# them by exact dict lookup, and anything not a key in that dict — built-in
# or custom — maps to `invalid`.
_MAX_VALIDATION_ERRORS = 20

_PUBLIC_VALIDATION_MISSING = "missing"
_PUBLIC_VALIDATION_INVALID_TYPE = "invalid_type"
_PUBLIC_VALIDATION_INVALID_FORMAT = "invalid_format"
_PUBLIC_VALIDATION_OUT_OF_RANGE = "out_of_range"
_PUBLIC_VALIDATION_INVALID = "invalid"

_VALIDATION_TYPE_TO_PUBLIC_CODE: dict[str, str] = {
    "missing": _PUBLIC_VALIDATION_MISSING,
    # The value's Python/JSON type is entirely wrong for the field (e.g. a
    # list where an int was declared) — pydantic-core's own "*_type" codes.
    "int_type": _PUBLIC_VALIDATION_INVALID_TYPE,
    "float_type": _PUBLIC_VALIDATION_INVALID_TYPE,
    "bool_type": _PUBLIC_VALIDATION_INVALID_TYPE,
    "string_type": _PUBLIC_VALIDATION_INVALID_TYPE,
    "bytes_type": _PUBLIC_VALIDATION_INVALID_TYPE,
    "list_type": _PUBLIC_VALIDATION_INVALID_TYPE,
    "dict_type": _PUBLIC_VALIDATION_INVALID_TYPE,
    "model_type": _PUBLIC_VALIDATION_INVALID_TYPE,
    "uuid_type": _PUBLIC_VALIDATION_INVALID_TYPE,
    "date_type": _PUBLIC_VALIDATION_INVALID_TYPE,
    "datetime_type": _PUBLIC_VALIDATION_INVALID_TYPE,
    # A string/number of roughly the right kind that still couldn't be
    # parsed into the target shape — pydantic-core's own "*_parsing" codes.
    "int_parsing": _PUBLIC_VALIDATION_INVALID_FORMAT,
    "float_parsing": _PUBLIC_VALIDATION_INVALID_FORMAT,
    "bool_parsing": _PUBLIC_VALIDATION_INVALID_FORMAT,
    "uuid_parsing": _PUBLIC_VALIDATION_INVALID_FORMAT,
    "date_parsing": _PUBLIC_VALIDATION_INVALID_FORMAT,
    "datetime_parsing": _PUBLIC_VALIDATION_INVALID_FORMAT,
    "json_invalid": _PUBLIC_VALIDATION_INVALID_FORMAT,
    "string_pattern_mismatch": _PUBLIC_VALIDATION_INVALID_FORMAT,
    "url_parsing": _PUBLIC_VALIDATION_INVALID_FORMAT,
    # Parsed fine but outside an allowed bound.
    "greater_than": _PUBLIC_VALIDATION_OUT_OF_RANGE,
    "greater_than_equal": _PUBLIC_VALIDATION_OUT_OF_RANGE,
    "less_than": _PUBLIC_VALIDATION_OUT_OF_RANGE,
    "less_than_equal": _PUBLIC_VALIDATION_OUT_OF_RANGE,
    "multiple_of": _PUBLIC_VALIDATION_OUT_OF_RANGE,
    "too_short": _PUBLIC_VALIDATION_OUT_OF_RANGE,
    "too_long": _PUBLIC_VALIDATION_OUT_OF_RANGE,
    "string_too_short": _PUBLIC_VALIDATION_OUT_OF_RANGE,
    "string_too_long": _PUBLIC_VALIDATION_OUT_OF_RANGE,
}


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
    recognized subclass's own `status_code`/`error_code`/`safe_message`
    outright — see `_API_ERROR_CONTRACTS` and `_validated_api_error_response`
    below the subclasses.
    """

    status_code: int = _INTERNAL_ERROR_CONTRACT.status_code
    error_code: str = _INTERNAL_ERROR_CONTRACT.error_code
    safe_message: str = _INTERNAL_ERROR_CONTRACT.safe_message

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


# The complete, fixed public contract for every ApiError type this module
# recognizes (finding 1) — keyed by *exact* exception type, not by
# independently checking whether a status "looks like" it could pair with
# a code. `ApiError`'s own registered contract is `_INTERNAL_ERROR_CONTRACT`
# itself, since a bare `ApiError()` (no subclass) is itself the "nothing
# more specific is known" case — the same single constant every other
# unclassified/fallback path in this module also returns.
_API_ERROR_CONTRACTS: dict[type[ApiError], _ErrorContract] = {
    ApiError: _INTERNAL_ERROR_CONTRACT,
    UnauthorizedError: _ErrorContract(401, "unauthorized", UnauthorizedError.safe_message),
    ForbiddenError: _ErrorContract(403, "forbidden", ForbiddenError.safe_message),
    NotFoundError: _ErrorContract(404, "not_found", NotFoundError.safe_message),
    ConflictError: _ErrorContract(409, "conflict", ConflictError.safe_message),
}


def _validated_api_error_response(exc: ApiError) -> _ErrorContract:
    """Finding 1: looks up `type(exc)` — never `isinstance`, so a subclass
    of a recognized type that this module hasn't itself registered is
    treated as unrecognized, not silently inherited — and additionally
    requires the exception's own current `status_code`/`error_code`/
    `safe_message` to equal the recorded triple exactly. Any mismatch (a
    status paired with the wrong code, an altered message on an otherwise-
    known type, a class attribute mutated some other way at runtime) and
    any unrecognized type both fall back to the identical, canonical
    `_INTERNAL_ERROR_CONTRACT` — never partial credit for "looks close"."""
    contract = _API_ERROR_CONTRACTS.get(type(exc))
    observed = _ErrorContract(exc.status_code, exc.error_code, exc.safe_message)
    return contract if contract == observed else _INTERNAL_ERROR_CONTRACT


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


def _method_not_allowed_allow_header(request: Request) -> str | None:
    """A server-owned `Allow` header for a 405 response, built from the
    matched route's own declared `methods` — never from `exc.headers`.
    FastAPI/Starlette set `request.scope["route"]` to the matched route
    even on a method mismatch (a "partial" match — see `starlette.routing.
    Router.app` and `fastapi.routing.APIRoute.matches`), so this is
    available for both a routing-generated 405 and one an endpoint raises
    directly against its own matched route. `exc.headers` is deliberately
    never read here: a directly raised `HTTPException(status_code=405,
    headers={...})` can carry any header a caller or a careless call site
    chose, including one this module has no way to vet, so the value
    returned is always recomputed from trusted routing data instead of
    being taken from (or merged with) whatever the exception happened to
    carry."""
    route = request.scope.get("route")
    if isinstance(route, Route) and route.methods:
        return ", ".join(sorted(route.methods))
    return None


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
    how it's filtered. Each `type` is mapped onto the small, fixed public
    vocabulary in `_VALIDATION_TYPE_TO_PUBLIC_CODE` by exact dict lookup —
    never regex/shape — so a custom-validator-supplied type string of any
    shape, including one that looks like ordinary pydantic vocabulary,
    falls back to `_PUBLIC_VALIDATION_INVALID` exactly like any other
    unrecognized value. The error list is capped in count — an oversized
    error collection is its own kind of unbounded response."""
    sanitized = []
    for error in errors[:_MAX_VALIDATION_ERRORS]:
        error_type = error["type"]
        sanitized.append(
            _VALIDATION_TYPE_TO_PUBLIC_CODE.get(error_type, _PUBLIC_VALIDATION_INVALID)
            if isinstance(error_type, str)
            else _PUBLIC_VALIDATION_INVALID
        )
    return sanitized


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
        # HTTPException(...) — never trusted or echoed. exc.status_code isn't
        # trusted outright either (finding 3): only a status present in
        # _SUPPORTED_HTTP_EXCEPTION_STATUSES is ever forwarded to the response;
        # anything else — an unrecognized-but-HTTP-shaped code, an out-of-range
        # value, or anything else a call site passed to HTTPException(...) — is
        # exactly as unclassified as any other unexpected failure and gets the
        # canonical internal-error contract instead. exc.headers is likewise
        # never forwarded — see _method_not_allowed_allow_header for the one
        # header this handler does construct, from trusted routing data only.
        contract = _SUPPORTED_HTTP_EXCEPTION_STATUSES.get(exc.status_code)
        response_headers: dict[str, str] | None = None
        if contract is None:
            status_code, error_code, message = _INTERNAL_ERROR_CONTRACT
            level = logging.ERROR
        else:
            error_code, message = contract
            status_code = exc.status_code
            level = logging.INFO
            if status_code == 405:
                allow = _method_not_allowed_allow_header(request)
                if allow is not None:
                    response_headers = {"Allow": allow}
        _log_error(request, exc, status_code=status_code, error_code=error_code, level=level)
        return JSONResponse(
            status_code=status_code,
            content=_envelope(request, code=error_code, message=message),
            headers=response_headers,
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
        # `_sanitize_validation_error_types` — a small, fixed public vocabulary
        # this module owns, never a pydantic type string or a location — reaches
        # the response; the log line carries only the fixed classification below,
        # exactly like every other handler in this module.
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
            # caller could have asked for differently. The canonical internal-error
            # contract, never a guess at 400 vs. 409 (finding 2).
            status_code, error_code, message = _INTERNAL_ERROR_CONTRACT
            level = logging.ERROR
        _log_error(request, exc, status_code=status_code, error_code=error_code, level=level)
        return JSONResponse(
            status_code=status_code, content=_envelope(request, code=error_code, message=message)
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        status_code, error_code, message = _INTERNAL_ERROR_CONTRACT
        _log_error(
            request, exc, status_code=status_code, error_code=error_code, level=logging.ERROR
        )
        return JSONResponse(
            status_code=status_code,
            content=_envelope(request, code=error_code, message=message),
        )
