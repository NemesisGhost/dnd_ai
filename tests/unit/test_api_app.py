"""Tests for the FastAPI app skeleton — error contract, correlation IDs,
and routing (docs/architecture/SYSTEM_ARCHITECTURE.md §5.2). No database:
these exercise only `dnd_ai.api.app`/`.errors`/`.correlation`, never a real
command or query.
"""

import logging
import uuid

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel
from starlette.requests import Request

from dnd_ai.api.app import create_app
from dnd_ai.api.errors import ApiError, ForbiddenError, _route_template
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
    assert body["error"]["code"] == "http_error"
    assert "correlation_id" in body["error"]


def test_correlation_id_is_generated_when_absent() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/healthz")
    correlation_id = response.headers["X-Correlation-Id"]
    assert correlation_id


def test_correlation_id_is_echoed_when_supplied() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/healthz", headers={"X-Correlation-Id": "test-correlation-id"})
    assert response.headers["X-Correlation-Id"] == "test-correlation-id"


def test_correlation_id_appears_in_error_envelope() -> None:
    with TestClient(create_app()) as client:
        response = client.get(
            "/does-not-exist", headers={"X-Correlation-Id": "test-correlation-id"}
        )
    assert response.json()["error"]["correlation_id"] == "test-correlation-id"


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


def test_api_error_maps_to_its_declared_status_and_code() -> None:
    app = create_app()

    @app.get("/raise-forbidden")
    def _raise_forbidden() -> None:
        raise ForbiddenError("not allowed to do that")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/raise-forbidden")

    assert response.status_code == 403
    body = response.json()
    assert body["error"] == {
        "code": "forbidden",
        "message": "not allowed to do that",
        "correlation_id": body["error"]["correlation_id"],
    }


def test_api_error_supports_ad_hoc_status_and_code_override() -> None:
    app = create_app()

    @app.get("/raise-custom")
    def _raise_custom() -> None:
        raise ApiError("teapot", error_code="im_a_teapot", status_code=418)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/raise-custom")

    assert response.status_code == 418
    assert response.json()["error"]["code"] == "im_a_teapot"


def test_unexpected_exception_maps_to_500_internal_error() -> None:
    app = create_app()

    @app.get("/raise-unexpected")
    def _raise_unexpected() -> None:
        raise RuntimeError("boom")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/raise-unexpected")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"


def test_request_validation_error_never_echoes_the_rejected_value() -> None:
    """Finding 4 regression: a deliberately secret-looking invalid value must
    never appear anywhere in the 422 response — not in a field, not buried in
    a message string."""
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
    assert body["error"]["fields"] == [{"field": "body.count", "code": "int_parsing"}]


def test_request_validation_error_response_shape() -> None:
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
        "fields": [{"field": "body.count", "code": "missing"}],
    }


# ---------------------------------------------------------------------------
# Correlation-ID validation (finding 2) — a client-supplied header is
# bounded and character-restricted before it is ever trusted, echoed, or
# logged.
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
