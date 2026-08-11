"""Tests for the FastAPI app skeleton — error contract, correlation IDs,
and routing (docs/architecture/SYSTEM_ARCHITECTURE.md §5.2). No database:
these exercise only `dnd_ai.api.app`/`.errors`/`.correlation`, never a real
command or query.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from dnd_ai.api.app import create_app
from dnd_ai.api.errors import ApiError, ForbiddenError
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


def test_safe_message_error_echoes_its_own_message() -> None:
    """A domain error that opts into the explicit safe-message contract
    (dnd_ai.domain.errors.SafeMessageError) gets its own text echoed, since
    authoring it that way is exactly what the contract is for."""
    app = create_app()

    @app.get("/raise-safe-message-error")
    def _raise_safe_message_error() -> None:
        raise SafeMessageError("no row with code 'bogus'")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/raise-safe-message-error")

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "validation_failed"
    assert body["error"]["message"] == "no row with code 'bogus'"


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
