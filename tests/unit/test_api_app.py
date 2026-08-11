"""Tests for the FastAPI app skeleton — error contract, correlation IDs,
and routing (docs/architecture/SYSTEM_ARCHITECTURE.md §5.2). No database:
these exercise only `dnd_ai.api.app`/`.errors`/`.correlation`, never a real
command or query.
"""

import logging
import uuid
from collections.abc import Callable
from typing import Annotated

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from starlette.requests import Request

from dnd_ai.api.app import create_app
from dnd_ai.api.correlation import _sanitize_client_correlation_id
from dnd_ai.api.errors import (
    ApiError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
    _route_template,
    _sanitize_validation_error_types,
)
from dnd_ai.domain.access import UnauthorizedTimelineError
from dnd_ai.domain.errors import DomainAuthorizationError, SafeMessageError

pytestmark = pytest.mark.unit


def test_healthz_returns_ok() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_unknown_route_returns_error_envelope() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/does-not-exist")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "not_found"
    assert body["error"]["message"] == (
        "The requested resource does not exist or is not accessible."
    )
    assert "correlation_id" in body["error"]


def test_method_not_allowed_returns_fixed_non_disclosing_message() -> None:
    """A wrong-method request against a route declared GET-only returns the
    fixed 405 envelope *and* a server-constructed `Allow` header naming
    exactly the route's own declared methods."""
    app = create_app()

    @app.get("/get-only")
    def _get_only() -> dict[str, str]:
        return {"status": "ok"}

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/get-only")

    assert response.status_code == 405
    body = response.json()
    assert body["error"]["code"] == "method_not_allowed"
    assert body["error"]["message"] == "The HTTP method is not allowed for this route."
    assert response.headers["Allow"] == "GET"


def test_method_not_allowed_allow_header_lists_multiple_methods_sorted() -> None:
    """A route declared for more than one method reports all of them in
    the `Allow` header, joined in a deterministic (sorted) order — unlike
    Starlette/FastAPI's own raw `", ".join(route.methods)`, which iterates
    a plain `set` and is not guaranteed to be ordered the same way twice."""
    app = create_app()

    @app.api_route("/multi-method", methods=["GET", "POST"])
    def _multi_method() -> dict[str, str]:
        return {"status": "ok"}

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.delete("/multi-method")

    assert response.status_code == 405
    assert response.headers["Allow"] == "GET, POST"


def test_method_not_allowed_allow_header_unions_separately_registered_routes() -> None:
    """The regression this pass fixes: Starlette's router remembers only
    the *first* route whose path matches but whose method doesn't, so when
    the same path is registered as two separate routes — one per method,
    as `@app.get(...)`/`@app.post(...)` naturally do — `request.scope
    ["route"]` alone would report only whichever one happened to be
    registered first. The `Allow` header must union every route matching
    the path, not just that one."""
    app = create_app()

    @app.get("/same")
    def _get_same() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/same")
    def _post_same() -> dict[str, str]:
        return {"status": "ok"}

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.put("/same")

    assert response.status_code == 405
    assert response.headers["Allow"] == "GET, POST"


def test_method_not_allowed_allow_header_excludes_unrelated_paths() -> None:
    """A route registered at a different path must never contribute its
    methods to another path's `Allow` header, even though both routes
    exist on the same application and the union is computed across all of
    them."""
    app = create_app()

    @app.get("/same")
    def _get_same() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/unrelated")
    def _post_unrelated() -> dict[str, str]:
        return {"status": "ok"}

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.put("/same")

    assert response.status_code == 405
    assert response.headers["Allow"] == "GET"


def test_http_exception_405_never_forwards_untrusted_headers_from_exc() -> None:
    """Negative regression: a directly raised `HTTPException(status_code=
    405, headers={...})` can carry any header a caller or a careless call
    site chose — including a forged `Allow` value or an arbitrary secret
    header. None of that is ever forwarded; the `Allow` header returned is
    always recomputed from the matched route's own declared methods, and
    no other header from `exc.headers` reaches the response at all."""
    app = create_app()

    @app.get("/raise-405-with-untrusted-headers")
    def _raise_with_untrusted_headers() -> None:
        raise HTTPException(
            status_code=405,
            detail="irrelevant",
            headers={
                "Allow": "EVIL_METHOD, HACKED",
                "X-Secret-Header": "leak-me-please",
            },
        )

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/raise-405-with-untrusted-headers")

    assert response.status_code == 405
    assert response.headers["Allow"] == "GET"
    assert "X-Secret-Header" not in response.headers
    assert "leak-me-please" not in response.text
    assert "leak-me-please" not in response.headers.get("Allow", "")


def test_http_exception_explicit_supported_status_behaves_like_routing() -> None:
    """finding 3: a directly raised HTTPException(status_code=404, ...) is
    supported identically to FastAPI's own routing 404 — the same fixed
    mapping applies regardless of how the status was produced — and its
    `detail` is never echoed."""
    app = create_app()

    secret_looking_detail = "token=SUPER_SECRET_ABC123_DO_NOT_LEAK"

    @app.get("/raise-explicit-404")
    def _raise_explicit_404() -> None:
        raise HTTPException(status_code=404, detail=secret_looking_detail)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/raise-explicit-404")

    assert response.status_code == 404
    assert secret_looking_detail not in response.text
    body = response.json()
    assert body["error"]["code"] == "not_found"
    assert body["error"]["message"] == (
        "The requested resource does not exist or is not accessible."
    )


def test_http_exception_unknown_but_http_shaped_status_falls_back_to_internal_error() -> None:
    """finding 3: exc.status_code is not trusted just because it's a
    plausible HTTP status — 418 isn't in `_SUPPORTED_HTTP_EXCEPTION_STATUSES`,
    so it must never reach the response; the fixed 500/internal_error
    contract is returned instead, and the dict `detail` is never echoed."""
    app = create_app()

    secret_looking_detail = {"leak": "token=SUPER_SECRET_ABC123_DO_NOT_LEAK"}

    @app.get("/raise-http-exception-418")
    def _raise_http_exception() -> None:
        raise HTTPException(status_code=418, detail=secret_looking_detail)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/raise-http-exception-418")

    assert response.status_code == 500
    assert "SUPER_SECRET_ABC123_DO_NOT_LEAK" not in response.text
    body = response.json()
    assert body["error"]["code"] == "internal_error"
    assert body["error"]["message"] == "An unexpected error occurred."


def test_http_exception_out_of_range_status_falls_back_to_internal_error() -> None:
    """finding 3: an out-of-range status (not a plausible HTTP status at
    all) gets the identical fixed internal-error fallback — never
    forwarded to JSONResponse verbatim."""
    app = create_app()

    @app.get("/raise-http-exception-out-of-range")
    def _raise_http_exception() -> None:
        raise HTTPException(status_code=999, detail="irrelevant")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/raise-http-exception-out-of-range")

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal_error"
    assert body["error"]["message"] == "An unexpected error occurred."


def test_correlation_id_is_generated_when_absent() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/healthz")
    correlation_id = response.headers["X-Correlation-Id"]
    assert correlation_id


def test_correlation_id_is_echoed_when_supplied() -> None:
    """Finding 5: only a canonical UUID is trusted and echoed verbatim."""
    valid_id = str(uuid.uuid4())
    with TestClient(create_app()) as client:
        response = client.get("/healthz", headers={"X-Correlation-Id": valid_id})
    assert response.headers["X-Correlation-Id"] == valid_id


def test_correlation_id_appears_in_error_envelope() -> None:
    valid_id = str(uuid.uuid4())
    with TestClient(create_app()) as client:
        response = client.get("/does-not-exist", headers={"X-Correlation-Id": valid_id})
    assert response.json()["error"]["correlation_id"] == valid_id


def test_unclassified_value_error_maps_to_fixed_non_disclosing_message() -> None:
    """finding 3: a bare, unclassified ValueError's own text is never
    echoed to the client — only a fixed, generic message. Using a
    deliberately secret-looking message proves the text really is
    discarded, not merely re-worded."""
    app = create_app()

    secret_looking_detail = "internal detail: token=SUPER_SECRET_ABC123"

    @app.get("/raise-value-error")
    def _raise_value_error() -> None:
        raise ValueError(secret_looking_detail)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/raise-value-error")

    assert response.status_code == 400
    assert secret_looking_detail not in response.text
    body = response.json()
    assert body["error"] == {
        "code": "validation_failed",
        "message": "The request could not be processed.",
        "correlation_id": body["error"]["correlation_id"],
    }


def test_bare_safe_message_error_never_echoes_constructor_text() -> None:
    """finding 4: raising SafeMessageError does not, by itself, make the
    constructor's text safe to return — only a subclass that explicitly
    defines its own fixed `safe_message` can expose something specific."""
    app = create_app()

    secret_looking_text = "token=SUPER_SECRET_ABC123_DO_NOT_LEAK"

    @app.get("/raise-safe-message-error")
    def _raise_safe_message_error() -> None:
        raise SafeMessageError(secret_looking_text)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/raise-safe-message-error")

    assert response.status_code == 400
    assert secret_looking_text not in response.text
    body = response.json()
    assert body["error"]["code"] == "validation_failed"
    assert body["error"]["message"] == "The request could not be processed."


def test_safe_message_error_subclass_may_expose_its_own_fixed_message() -> None:
    """The opt-in path finding 4 describes: a subclass defines its own
    fixed `safe_message`, independent of whatever the constructor argument
    was — proving the contract still supports exposing something specific
    when an author has deliberately vetted it."""
    app = create_app()

    class _KnownLookupCodeError(SafeMessageError):
        safe_message = "no lookup row for the requested code"

    @app.get("/raise-known-safe-message-error")
    def _raise_known_safe_message_error() -> None:
        raise _KnownLookupCodeError("raw diagnostic text a client never sees")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/raise-known-safe-message-error")

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["message"] == "no lookup row for the requested code"


def test_domain_authorization_error_maps_to_404_non_disclosing() -> None:
    app = create_app()

    secret_looking_detail = "campaign 11111111-1111-1111-1111-111111111111 forbidden detail"

    @app.get("/raise-domain-authorization-error")
    def _raise_domain_authorization_error() -> None:
        raise DomainAuthorizationError(secret_looking_detail)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/raise-domain-authorization-error")

    assert response.status_code == 404
    assert secret_looking_detail not in response.text
    body = response.json()
    assert body["error"] == {
        "code": "not_found",
        "message": "The requested resource does not exist or is not accessible.",
        "correlation_id": body["error"]["correlation_id"],
    }


def test_unauthorized_timeline_error_response_omits_every_supplied_uuid() -> None:
    """finding 3's explicit regression: resolve_access_context() embeds the
    requested, campaign, and canonical timeline UUIDs in
    UnauthorizedTimelineError's own message (for server-side logs) — none
    of the three may reach an API response."""
    app = create_app()

    requested_timeline_id = uuid.uuid4()
    campaign_id = uuid.uuid4()
    canonical_timeline_id = uuid.uuid4()

    @app.get("/raise-unauthorized-timeline")
    def _raise_unauthorized_timeline() -> None:
        raise UnauthorizedTimelineError(
            f"timeline {requested_timeline_id} is not campaign {campaign_id}'s own timeline "
            f"({canonical_timeline_id})"
        )

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/raise-unauthorized-timeline")

    assert response.status_code == 404
    for leaked_id in (requested_timeline_id, campaign_id, canonical_timeline_id):
        assert str(leaked_id) not in response.text
    assert response.json()["error"]["message"] == (
        "The requested resource does not exist or is not accessible."
    )


@pytest.mark.parametrize(
    ("error_class", "expected_status", "expected_code", "expected_message"),
    [
        (
            UnauthorizedError,
            401,
            "unauthorized",
            "Authentication is required.",
        ),
        (
            ForbiddenError,
            403,
            "forbidden",
            "You do not have permission to perform this action.",
        ),
        (
            NotFoundError,
            404,
            "not_found",
            "The requested resource does not exist or is not accessible.",
        ),
        (
            ConflictError,
            409,
            "conflict",
            "The request could not be completed due to a conflicting change.",
        ),
    ],
)
def test_every_supported_api_error_subclass_maps_to_its_registered_contract(
    error_class: type[ApiError],
    expected_status: int,
    expected_code: str,
    expected_message: str,
) -> None:
    """finding 1: each of the four recognized ApiError subclasses maps to
    its exact registered `(status_code, error_code, safe_message)` triple
    from `_API_ERROR_CONTRACTS` — not merely "a status in some known set
    paired with an identifier-shaped code"."""
    app = create_app()

    @app.get(f"/raise-{error_class.__name__}")
    def _raise() -> None:
        raise error_class("irrelevant diagnostic detail")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(f"/raise-{error_class.__name__}")

    assert response.status_code == expected_status
    body = response.json()
    assert body["error"] == {
        "code": expected_code,
        "message": expected_message,
        "correlation_id": body["error"]["correlation_id"],
    }


def test_bare_api_error_never_echoes_constructor_detail_text() -> None:
    """finding 1: ApiError follows the same discipline as SafeMessageError
    (finding 4 of the prior pass) — the constructor's `detail` argument
    never becomes client-visible just because a raise site chose it."""
    app = create_app()

    secret_looking_detail = "token=SUPER_SECRET_ABC123_DO_NOT_LEAK"

    @app.get("/raise-api-error-with-secret")
    def _raise_api_error() -> None:
        raise ApiError(secret_looking_detail)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/raise-api-error-with-secret")

    assert response.status_code == 500
    assert secret_looking_detail not in response.text
    body = response.json()
    assert body["error"]["code"] == "internal_error"
    assert body["error"]["message"] == "An unexpected error occurred."


def test_api_error_constructor_rejects_status_and_code_overrides() -> None:
    """finding 2: an earlier version of this module accepted
    `error_code=`/`status_code=` constructor kwargs, letting a raise site
    turn arbitrary runtime values into public response/log fields. Both are
    gone — the constructor accepts only `detail`, so attempting either
    override is a `TypeError` at the raise site, not a silently accepted
    value."""
    with pytest.raises(TypeError):
        ApiError("detail", error_code="im_a_teapot")  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        ApiError("detail", status_code=418)  # type: ignore[call-arg]


def test_api_error_unknown_subclass_falls_back_to_internal_error() -> None:
    """finding 1: `_API_ERROR_CONTRACTS` is keyed by *exact* recognized
    type — a brand-new subclass is unrecognized regardless of how
    well-formed its own status/code/message look, since only the four
    subclasses this module explicitly registers are ever exposed. A
    well-formed-looking contract proves this is about registration, not
    about detecting obviously-broken values."""
    app = create_app()

    class _NewWellFormedSubclass(ApiError):
        status_code = 409
        error_code = "conflict"
        safe_message = "A specific, plausible-looking message."

    @app.get("/raise-new-subclass")
    def _raise_new_subclass() -> None:
        raise _NewWellFormedSubclass("raw diagnostic text a client never sees")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/raise-new-subclass")

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal_error"
    assert body["error"]["message"] == "An unexpected error occurred."


def test_api_error_with_tampered_class_attributes_falls_back_to_internal_error() -> None:
    """finding 1: even a subclass's own status_code/error_code/safe_message
    aren't trusted outright — `_validated_api_error_response` re-checks
    them against `_API_ERROR_CONTRACTS`, a small, fixed, server-owned
    vocabulary. Simulates a class attribute that doesn't match any real
    subclass's registered contract (a stray typo, or some other way a
    value outside the known vocabulary ends up on the class) and proves
    the response and the log both fall back to the fixed internal-error
    contract rather than trusting it."""
    app = create_app()

    class _MistypedError(ApiError):
        status_code = 599  # not a status any registered contract uses
        error_code = "totally not a known code; DROP TABLE"
        safe_message = "this should never reach a client"

    @app.get("/raise-mistyped-api-error")
    def _raise_mistyped() -> None:
        raise _MistypedError("diagnostic detail")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/raise-mistyped-api-error")

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal_error"
    assert body["error"]["message"] == "An unexpected error occurred."


def test_api_error_logged_error_code_is_also_validated(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """finding 1: the logged error_code comes from the same validated
    triple as the response — a class attribute outside the known
    vocabulary never reaches the log line either."""
    app = create_app()

    class _MistypedError(ApiError):
        status_code = 599
        error_code = "not_a_known_code"

    @app.get("/raise-mistyped-api-error-logged")
    def _raise_mistyped() -> None:
        raise _MistypedError("diagnostic detail")

    with caplog.at_level(logging.DEBUG), TestClient(app, raise_server_exceptions=False) as client:
        client.get("/raise-mistyped-api-error-logged")

    logged_text = "\n".join(r.getMessage() for r in caplog.records)
    assert "not_a_known_code" not in logged_text
    assert "error_code=internal_error" in logged_text
    assert "status_code=500" in logged_text


def test_api_error_identifier_shaped_unknown_code_with_valid_status_falls_back() -> None:
    """finding 1: a *recognized* type (`ForbiddenError`) whose `error_code`
    is mutated at the instance level to an unfamiliar-but-plausible-looking
    value, while `status_code` stays a perfectly valid known status (403),
    still doesn't match the registered contract exactly — proving this
    module validates the whole triple together, not each field
    independently against "is this status known" / "is this code
    identifier-shaped"."""
    app = create_app()

    @app.get("/raise-forbidden-with-unknown-code")
    def _raise() -> None:
        exc = ForbiddenError("diagnostic detail")
        exc.error_code = "not_actually_forbidden"
        raise exc

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/raise-forbidden-with-unknown-code")

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal_error"
    assert body["error"]["message"] == "An unexpected error occurred."


def test_api_error_known_code_paired_with_wrong_status_falls_back() -> None:
    """finding 1: `ForbiddenError`'s own `error_code` ("forbidden") is
    real, and 404 is a real status another registered contract uses — but
    403/forbidden and 404 were never registered together, so this
    mismatched pairing still falls back rather than being accepted because
    each half looks individually legitimate."""
    app = create_app()

    @app.get("/raise-forbidden-with-wrong-status")
    def _raise() -> None:
        exc = ForbiddenError("diagnostic detail")
        exc.status_code = 404
        raise exc

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/raise-forbidden-with-wrong-status")

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal_error"
    assert body["error"]["message"] == "An unexpected error occurred."


def test_api_error_altered_public_message_on_known_type_falls_back() -> None:
    """finding 1: status_code and error_code both stay exactly as
    registered for `ForbiddenError`, but `safe_message` is altered — the
    complete triple no longer matches, so this still falls back rather
    than exposing the altered message."""
    app = create_app()

    @app.get("/raise-forbidden-with-altered-message")
    def _raise() -> None:
        exc = ForbiddenError("diagnostic detail")
        exc.safe_message = "a message this module never vetted for this type"
        raise exc

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/raise-forbidden-with-altered-message")

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal_error"
    assert body["error"]["message"] == "An unexpected error occurred."


def test_unexpected_exception_maps_to_500_internal_error() -> None:
    app = create_app()

    @app.get("/raise-unexpected")
    def _raise_unexpected() -> None:
        raise RuntimeError("boom")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/raise-unexpected")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"


def _raise_unregistered_api_error_subclass() -> None:
    class _Unregistered(ApiError):
        pass

    raise _Unregistered("diagnostic detail a client never sees")


def _raise_unsupported_http_exception_status() -> None:
    raise HTTPException(status_code=418, detail="diagnostic detail a client never sees")


def _raise_unclassified_integrity_error() -> None:
    class _FakeOrigWithoutRecognizedSqlstate(Exception):
        sqlstate = "99999"

    raise IntegrityError(
        "INSERT ...", {}, _FakeOrigWithoutRecognizedSqlstate("unrecognized failure")
    )


def _raise_genuinely_unexpected_exception() -> None:
    raise RuntimeError("diagnostic detail a client never sees")


@pytest.mark.parametrize(
    "raise_fn",
    [
        _raise_unregistered_api_error_subclass,
        _raise_unsupported_http_exception_status,
        _raise_unclassified_integrity_error,
        _raise_genuinely_unexpected_exception,
    ],
    ids=[
        "unregistered_api_error_subclass",
        "unsupported_http_exception_status",
        "unclassified_integrity_error",
        "genuinely_unexpected_exception",
    ],
)
def test_every_unclassified_fallback_path_returns_the_canonical_internal_error_contract(
    raise_fn: Callable[[], None],
) -> None:
    """Every kind of "nothing more specific is known" failure — an
    unregistered `ApiError` subclass, an unsupported `HTTPException`
    status, an `IntegrityError` with an unrecognized SQLSTATE, and a
    genuinely unexpected `Exception` — must return the identical fixed
    500/`internal_error` contract, word for word, regardless of which
    handler happened to catch it."""
    app = create_app()
    app.get("/raise-fallback")(raise_fn)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/raise-fallback")

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal_error"
    assert body["error"]["message"] == "An unexpected error occurred."


def test_request_validation_error_never_echoes_the_rejected_value() -> None:
    """A deliberately secret-looking invalid value must never appear
    anywhere in the 422 response — not in a location, not in the message,
    not buried anywhere else."""
    app = create_app()

    class _Payload(BaseModel):
        count: int

    @app.post("/validate-test")
    def _validate_test(payload: _Payload) -> dict[str, int]:
        return {"count": payload.count}

    secret_looking_value = "SECRET_TOKEN_ABC123_DO_NOT_LEAK"

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/validate-test", json={"count": secret_looking_value})

    assert response.status_code == 422
    assert secret_looking_value not in response.text
    body = response.json()
    assert body["error"]["code"] == "invalid_request"
    assert secret_looking_value not in body["error"]["message"]
    assert body["error"]["error_codes"] == ["invalid_format"]
    assert "fields" not in body["error"]


def test_request_validation_error_response_shape() -> None:
    """finding 1: the generic validation response never carries a field
    *location* at all — only the bounded, sanitized `error_codes` list."""
    app = create_app()

    class _Payload(BaseModel):
        count: int

    @app.post("/validate-test")
    def _validate_test(payload: _Payload) -> dict[str, int]:
        return {"count": payload.count}

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/validate-test", json={})

    assert response.status_code == 422
    body = response.json()
    assert body["error"] == {
        "code": "invalid_request",
        "message": "The request did not pass validation.",
        "correlation_id": body["error"]["correlation_id"],
        "error_codes": ["missing"],
    }


def test_validation_error_never_echoes_an_identifier_shaped_secret_dict_key(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """finding 1: a `dict[str, X]` body's own key becomes a `loc` entry
    verbatim, and `SUPER_SECRET_TOKEN_ABC123` is exactly as
    identifier-shaped as an ordinary field name — proving no amount of
    character-shape filtering on the location can tell them apart is why
    this module no longer echoes locations at all. Absent from both the
    response and any captured log line."""
    app = create_app()

    class _Payload(BaseModel):
        counts: dict[str, int]

    @app.post("/validate-dict-body")
    def _validate(payload: _Payload) -> dict[str, int]:
        return payload.counts

    secret_key = "SUPER_SECRET_TOKEN_ABC123"

    with caplog.at_level(logging.DEBUG), TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/validate-dict-body", json={"counts": {secret_key: "not-an-int"}})

    assert response.status_code == 422
    assert secret_key not in response.text
    body = response.json()
    assert body["error"]["error_codes"] == ["invalid_format"]
    assert "fields" not in body["error"]
    assert secret_key not in "\n".join(r.getMessage() for r in caplog.records)


def test_validation_error_never_echoes_a_short_token_like_dict_key() -> None:
    """finding 1: even a short, unremarkable-looking dynamic key — the
    shape an ordinary field name could just as easily have — is never
    echoed as a location, since this module can't reliably tell a
    legitimate dynamic key from a short token/secret of the same shape."""
    app = create_app()

    class _Payload(BaseModel):
        counts: dict[str, int]

    @app.post("/validate-dict-body-short-key")
    def _validate(payload: _Payload) -> dict[str, int]:
        return payload.counts

    token_like_key = "ab12cd"

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/validate-dict-body-short-key", json={"counts": {token_like_key: "not-an-int"}}
        )

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["error_codes"] == ["invalid_format"]
    assert "fields" not in body["error"]


def test_validation_error_never_echoes_an_ordinary_declared_model_field_location() -> None:
    """finding 1: even a field name declared on the endpoint's own request
    schema — as unremarkable as a location gets — is never echoed either;
    the generic validation response carries no location for any field,
    declared or not."""
    app = create_app()

    class _Payload(BaseModel):
        count: int

    @app.post("/validate-declared-field")
    def _validate(payload: _Payload) -> dict[str, int]:
        return {"count": payload.count}

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/validate-declared-field", json={"count": "not-an-int"})

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["error_codes"] == ["invalid_format"]
    assert "fields" not in body["error"]
    assert "count" not in response.text


def test_validation_error_caps_an_oversized_error_collection() -> None:
    """finding 1/4: an oversized error collection is its own kind of
    unbounded response — capped at `_MAX_VALIDATION_ERRORS` (20) even when
    the request produces many more individual validation failures."""
    app = create_app()

    class _Payload(BaseModel):
        counts: dict[str, int]

    @app.post("/validate-oversized-collection")
    def _validate(payload: _Payload) -> dict[str, int]:
        return payload.counts

    oversized_body = {"counts": {f"key_{i}": "not-an-int" for i in range(30)}}

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/validate-oversized-collection", json=oversized_body)

    assert response.status_code == 422
    body = response.json()
    # 30 rejected keys produce 30 raw pydantic errors — proves the response is
    # actually capped, not merely coincidentally under the limit.
    assert len(body["error"]["error_codes"]) == 20


def test_validation_error_logging_is_sanitized_and_fixed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """finding 3: `handle_validation_error` now logs through the same
    sanitized `_log_error` path every other handler uses — only the fixed
    classification (exception class, 422, invalid_request, correlation ID,
    route template). Secret-bearing rejected input and a secret-looking
    dynamic dict key must both be absent from every captured log line."""
    app = create_app()

    class _Payload(BaseModel):
        count: int
        extras: dict[str, int]

    @app.post("/validate-logging")
    def _validate(payload: _Payload) -> dict[str, int]:
        return payload.extras

    secret_value = "password=Sup3rSecretPW!"
    secret_key = "token_SUPER_SECRET_ABC123_DO_NOT_LEAK"

    with caplog.at_level(logging.DEBUG), TestClient(app, raise_server_exceptions=False) as client:
        client.post(
            "/validate-logging",
            json={"count": secret_value, "extras": {secret_key: "not-an-int"}},
        )

    logged_text = "\n".join(r.getMessage() for r in caplog.records)
    assert secret_value not in logged_text
    assert secret_key not in logged_text
    assert "int_parsing" not in logged_text  # no raw per-error detail either
    assert "RequestValidationError" in logged_text
    assert "status_code=422" in logged_text
    assert "error_code=invalid_request" in logged_text


def test_validation_error_maps_representative_builtin_types_to_public_vocabulary() -> None:
    """finding 2: real, distinct pydantic failures for missing/wrong-type/
    out-of-range values through the actual validation pipeline map onto
    the small, fixed public vocabulary this module owns."""
    app = create_app()

    class _Payload(BaseModel):
        count: Annotated[int, Field(gt=0)]
        label: str
        wrong_type: int

    @app.post("/validate-representative-types")
    def _validate(payload: _Payload) -> dict[str, int]:
        return {"count": payload.count}

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/validate-representative-types",
            json={"count": -5, "wrong_type": ["not", "an", "int"]},
        )

    assert response.status_code == 422
    body = response.json()
    # label missing -> "missing"; count=-5 violates gt=0 -> "out_of_range";
    # wrong_type is a list, not coercible to int at all -> "invalid_type".
    assert set(body["error"]["error_codes"]) == {"missing", "out_of_range", "invalid_type"}


def test_validation_error_maps_unmapped_builtin_pydantic_code_to_invalid() -> None:
    """finding 2: `extra_forbidden` is a real, ordinary, built-in pydantic
    error type — but this module's vocabulary deliberately doesn't include
    it, proving an unmapped *legitimate* pydantic code falls back to
    `invalid` exactly like an unmapped custom one does; this module does
    not attempt to mirror pydantic's entire internal vocabulary."""
    app = create_app()

    class _Payload(BaseModel):
        model_config = ConfigDict(extra="forbid")
        count: int

    @app.post("/validate-unmapped-builtin-code")
    def _validate(payload: _Payload) -> dict[str, int]:
        return {"count": payload.count}

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/validate-unmapped-builtin-code", json={"count": 1, "extra_field": "x"}
        )

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["error_codes"] == ["invalid"]


def test_sanitize_validation_error_types_maps_by_exact_lookup_never_by_shape() -> None:
    """finding 2, direct sanitizer-level regression: a well-formed,
    *mapped* pydantic type code is translated to its public code; an
    identifier-shaped custom code (`secret_token_abc123` — exactly what a
    `PydanticCustomError` could produce) and an ordinary-looking but
    unmapped real pydantic code (`value_error`) both fall back to
    `invalid` — proving this is exact-membership lookup, never a
    shape/regex check that a syntactically-clean secret could pass. The
    error list is capped at `_MAX_VALIDATION_ERRORS`."""
    mapped_missing = {"type": "missing"}
    mapped_type = {"type": "int_type"}
    mapped_parsing = {"type": "int_parsing"}
    mapped_range = {"type": "greater_than"}
    identifier_shaped_secret = {"type": "secret_token_abc123"}
    unmapped_ordinary_code = {"type": "value_error"}
    oversized_type = {"type": "x" * 200}
    unsafe_shaped_type = {"type": "SUPER_SECRET; DROP TABLE users;--"}
    non_string_type = {"type": 12345}

    assert _sanitize_validation_error_types([mapped_missing]) == ["missing"]
    assert _sanitize_validation_error_types([mapped_type]) == ["invalid_type"]
    assert _sanitize_validation_error_types([mapped_parsing]) == ["invalid_format"]
    assert _sanitize_validation_error_types([mapped_range]) == ["out_of_range"]
    assert _sanitize_validation_error_types([identifier_shaped_secret]) == ["invalid"]
    assert _sanitize_validation_error_types([unmapped_ordinary_code]) == ["invalid"]
    assert _sanitize_validation_error_types([oversized_type]) == ["invalid"]
    assert _sanitize_validation_error_types([unsafe_shaped_type]) == ["invalid"]
    assert _sanitize_validation_error_types([non_string_type]) == ["invalid"]

    many_errors = [mapped_missing] * 25
    assert len(_sanitize_validation_error_types(many_errors)) == 20


# ---------------------------------------------------------------------------
# Correlation-ID validation (finding 5) — only a canonical UUID is trusted,
# echoed, or logged; anything else is replaced with a freshly generated one.
# ---------------------------------------------------------------------------


def test_correlation_id_with_control_characters_is_replaced() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/healthz", headers={"X-Correlation-Id": "abc\r\ninjected: true"})
    returned = response.headers["X-Correlation-Id"]
    assert returned != "abc\r\ninjected: true"
    assert "\r" not in returned
    assert "\n" not in returned


def test_correlation_id_exceeding_max_length_is_replaced() -> None:
    too_long = "a" * 500
    with TestClient(create_app()) as client:
        response = client.get("/healthz", headers={"X-Correlation-Id": too_long})
    assert response.headers["X-Correlation-Id"] != too_long
    assert len(response.headers["X-Correlation-Id"]) < 200


def test_correlation_id_empty_value_is_replaced() -> None:
    assert _sanitize_client_correlation_id("") is None


def test_correlation_id_token_like_but_character_valid_text_is_replaced(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """finding 5: the previous `[A-Za-z0-9._-]{1,100}` character class
    admitted this shape — it must now be rejected since it is not a
    canonical UUID, and it must never reach a response or a log line."""
    token_like_value = "session_token.SUPER_SECRET_ABC123-DO_NOT_LEAK"

    assert _sanitize_client_correlation_id(token_like_value) is None

    app = create_app()
    with caplog.at_level(logging.DEBUG), TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/does-not-exist", headers={"X-Correlation-Id": token_like_value})

    assert response.headers["X-Correlation-Id"] != token_like_value
    assert token_like_value not in response.text
    assert token_like_value not in "\n".join(r.getMessage() for r in caplog.records)


def test_correlation_id_with_uuid_format_is_preserved() -> None:
    valid_id = str(uuid.uuid4())
    with TestClient(create_app()) as client:
        response = client.get("/healthz", headers={"X-Correlation-Id": valid_id})
    assert response.headers["X-Correlation-Id"] == valid_id


# ---------------------------------------------------------------------------
# Logging (finding 2) — every handler's log line is safe by construction:
# exception class, status/error code, correlation ID, and route template
# only. A deliberately secret-bearing exception message must never appear
# in any captured log record for any of these handlers.
# ---------------------------------------------------------------------------

_SECRET_BEARING_STRINGS = (
    "password=Sup3rSecretPW!",
    "postgresql://app:Sup3rSecretPW!@dbhost.internal:5432/dnd_ai",
    "11111111-1111-1111-1111-111111111111",
    "SET session_replication_role = 'origin'; -- token_value=abc123XYZ",
)

_COMBINED_SECRET_MESSAGE = " | ".join(_SECRET_BEARING_STRINGS)


def _assert_no_secrets_in_logs(caplog: pytest.LogCaptureFixture) -> None:
    captured_log_text = "\n".join(record.getMessage() for record in caplog.records)
    for secret in _SECRET_BEARING_STRINGS:
        assert secret not in captured_log_text


def test_value_error_logging_omits_every_secret_bearing_string(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = create_app()

    @app.get("/raise-value-error-with-secrets")
    def _raise() -> None:
        raise ValueError(_COMBINED_SECRET_MESSAGE)

    with caplog.at_level(logging.DEBUG), TestClient(app, raise_server_exceptions=False) as client:
        client.get("/raise-value-error-with-secrets")

    _assert_no_secrets_in_logs(caplog)
    assert "ValueError" in "\n".join(r.getMessage() for r in caplog.records)


def test_safe_message_error_logging_omits_every_secret_bearing_string(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = create_app()

    @app.get("/raise-safe-message-error-with-secrets")
    def _raise() -> None:
        raise DomainAuthorizationError(_COMBINED_SECRET_MESSAGE)

    with caplog.at_level(logging.DEBUG), TestClient(app, raise_server_exceptions=False) as client:
        client.get("/raise-safe-message-error-with-secrets")

    _assert_no_secrets_in_logs(caplog)


def test_unexpected_exception_logging_omits_every_secret_bearing_string(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = create_app()

    @app.get("/raise-unexpected-with-secrets")
    def _raise() -> None:
        raise RuntimeError(_COMBINED_SECRET_MESSAGE)

    with caplog.at_level(logging.DEBUG), TestClient(app, raise_server_exceptions=False) as client:
        client.get("/raise-unexpected-with-secrets")

    _assert_no_secrets_in_logs(caplog)
    captured_log_text = "\n".join(r.getMessage() for r in caplog.records)
    assert "RuntimeError" in captured_log_text
    assert "Traceback" not in captured_log_text


def test_api_error_logging_omits_every_secret_bearing_string(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """finding 1: ApiError's constructor `detail` argument never reaches a
    log line, exactly like SafeMessageError's constructor argument."""
    app = create_app()

    @app.get("/raise-api-error-with-secrets")
    def _raise() -> None:
        raise ApiError(_COMBINED_SECRET_MESSAGE)

    with caplog.at_level(logging.DEBUG), TestClient(app, raise_server_exceptions=False) as client:
        client.get("/raise-api-error-with-secrets")

    _assert_no_secrets_in_logs(caplog)


def test_http_exception_dict_detail_logging_omits_every_secret_bearing_string(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """finding 1: a directly raised HTTPException's `detail` never reaches
    a log line, whether it is a string, dict, or list."""
    app = create_app()

    @app.get("/raise-http-exception-with-secrets")
    def _raise() -> None:
        raise HTTPException(status_code=400, detail={"leak": _COMBINED_SECRET_MESSAGE})

    with caplog.at_level(logging.DEBUG), TestClient(app, raise_server_exceptions=False) as client:
        client.get("/raise-http-exception-with-secrets")

    _assert_no_secrets_in_logs(caplog)


def test_route_template_uses_the_matched_pattern_not_the_concrete_path() -> None:
    app = create_app()

    @app.get("/campaigns/{campaign_id}/raise")
    def _raise(campaign_id: str) -> None:
        raise ValueError("boom")

    matched_route = next(
        route
        for route in app.router.routes
        if getattr(route, "path", None) == "/campaigns/{campaign_id}/raise"
    )
    scope = {"type": "http", "route": matched_route, "path": "/campaigns/some-real-id-123/raise"}
    assert _route_template(Request(scope)) == "/campaigns/{campaign_id}/raise"


def test_route_template_falls_back_when_no_route_matched() -> None:
    scope = {"type": "http", "path": "/does-not-exist"}
    assert _route_template(Request(scope)) == "<unmatched>"
