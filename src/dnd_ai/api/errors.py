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
caller-supplied input either. Domain layers raise plain `ValueError` (and
its subclasses, such as `dnd_ai.commands._shared.LookupCodeNotFoundError`)
for validation failures per docs/DEVELOPMENT.md §9 — they do not need to
know about HTTP at all; this module is the only place that translates them
into a status code. A domain `ValueError`'s own message *is* echoed back
(`handle_value_error` below) since those are authored by this codebase as
already-safe, non-input-echoing diagnostic text (see e.g.
`dnd_ai.domain.access.UnauthorizedTimelineError`'s docstring) — unlike
`RequestValidationError`, whose text FastAPI/pydantic generate directly
from whatever the caller sent.
"""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)


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

    @app.exception_handler(ValueError)
    async def handle_value_error(request: Request, exc: ValueError) -> JSONResponse:
        # Domain validation failures (docs/DEVELOPMENT.md §9) surface as plain
        # ValueError/subclasses — never partial writes, since the command's own
        # transaction rolls back before this handler ever runs (see api/deps.py).
        return JSONResponse(
            status_code=400,
            content=_envelope(request, code="validation_failed", message=str(exc)),
        )

    @app.exception_handler(IntegrityError)
    async def handle_integrity_error(request: Request, exc: IntegrityError) -> JSONResponse:
        # A constraint the application layer didn't pre-check — e.g. a concurrent
        # writer won a race. Retriable, per §20 "optimistic concurrency failures
        # return a retriable conflict" — not the client's fault to fix by editing
        # the request.
        logger.warning("database constraint violation surfaced to API layer", exc_info=exc)
        return JSONResponse(
            status_code=409,
            content=_envelope(
                request,
                code="conflict",
                message="The request could not be completed due to a conflicting change. Retry.",
            ),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, _exc: Exception) -> JSONResponse:
        logger.exception("unhandled exception in API layer")
        return JSONResponse(
            status_code=500,
            content=_envelope(
                request, code="internal_error", message="An unexpected error occurred."
            ),
        )
