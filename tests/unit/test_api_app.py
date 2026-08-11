"""Tests for the FastAPI app skeleton — error contract, correlation IDs,
and routing (docs/architecture/SYSTEM_ARCHITECTURE.md §5.2). No database:
these exercise only `dnd_ai.api.app`/`.errors`/`.correlation`, never a real
command or query.
"""

import pytest
from fastapi.testclient import TestClient

from dnd_ai.api.app import create_app
from dnd_ai.api.errors import ApiError, ForbiddenError

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


def test_value_error_maps_to_400_validation_envelope() -> None:
    app = create_app()

    @app.get("/raise-value-error")
    def _raise_value_error() -> None:
        raise ValueError("something was invalid")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/raise-value-error")

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "validation_failed"
    assert body["error"]["message"] == "something was invalid"


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
