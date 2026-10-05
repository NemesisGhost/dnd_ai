"""`Cache-Control: no-store` middleware (Phase 15.1)."""

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from dnd_ai.api.app import create_app
from dnd_ai.api.cache_control import NoStoreMiddleware


def _client() -> TestClient:
    app = FastAPI()
    app.add_middleware(NoStoreMiddleware)

    @app.get("/data")
    def data() -> dict[str, str]:
        return {"a": "b"}

    @app.get("/custom")
    def custom() -> JSONResponse:
        return JSONResponse({"a": "b"}, headers={"Cache-Control": "max-age=60"})

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return TestClient(app)


def test_responses_are_no_store_by_default() -> None:
    assert _client().get("/data").headers["cache-control"] == "no-store"


def test_a_route_that_sets_its_own_policy_is_left_alone() -> None:
    assert _client().get("/custom").headers["cache-control"] == "max-age=60"


def test_error_responses_are_no_store_too() -> None:
    assert _client().get("/missing").headers["cache-control"] == "no-store"


def test_liveness_probe_is_exempt() -> None:
    assert "cache-control" not in _client().get("/healthz").headers


def test_the_real_app_installs_the_middleware() -> None:
    client = TestClient(create_app())
    assert "cache-control" not in client.get("/healthz").headers
    assert client.get("/no-such-route").headers["cache-control"] == "no-store"
