"""The complementary half of `tests/unit/test_cors.py`'s CORS regression
coverage: proving CORS never broadens *authentication* — a request from an
allowed origin with no `Authorization` header must still be rejected 401,
exactly as it would be with no `Origin` header at all.

This cannot be a pure unit test: `dnd_ai.api.auth.get_authenticated_user_id`
depends on a real database connection (`Depends(get_connection)`) even to
reach its own "missing Authorization header" check, and — for the OIDC
branch a missing header still falls through to — on `get_jwks_client()`
succeeding, which asserts `dnd_ai.config.settings.oidc_jwks_url` is
configured (a legitimate non-production state locally, per that function's
own comment, that would otherwise surface as a 500 having nothing to do
with CORS). `get_jwks_client` is overridden below via
`app.dependency_overrides` exactly as `dnd_ai.api.auth.get_authenticated_
user_id`'s own docstring says it can be — the fake client is never actually
called, since `get_verified_token_claims` rejects a missing header before
ever touching it.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

import dnd_ai.config as config
from dnd_ai.api.app import create_app
from dnd_ai.api.auth import get_jwks_client
from dnd_ai.api.deps import get_engine

pytestmark = pytest.mark.database

_ALLOWED_ORIGIN = "https://foundry.example.com"
_PROTECTED_PATH = "/campaigns/00000000-0000-0000-0000-000000000000/events"
_PROTECTED_BODY = {
    "world_time_id": "00000000-0000-0000-0000-000000000000",
    "event_type_code": "other",
    "name": "cors smoke test",
}


def _make_app(monkeypatch: pytest.MonkeyPatch, postgres_engine: Engine, origin: str | None):
    monkeypatch.setattr(config.settings, "foundry_allowed_origins", origin)
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: postgres_engine
    # Never actually called for a request with no Authorization header —
    # get_verified_token_claims rejects that before touching the client —
    # so a bare placeholder is sufficient.
    app.dependency_overrides[get_jwks_client] = lambda: object()
    return app


def test_cors_does_not_broaden_authentication(
    monkeypatch: pytest.MonkeyPatch, postgres_engine: Engine
) -> None:
    """A request from an allowed origin with no Authorization header must
    still be rejected 401 — CORS only controls whether a browser may read
    the response, never whether the server accepts the request."""
    app = _make_app(monkeypatch, postgres_engine, _ALLOWED_ORIGIN)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            _PROTECTED_PATH, json=_PROTECTED_BODY, headers={"Origin": _ALLOWED_ORIGIN}
        )
    assert response.status_code == 401
    # The 401 is still exposed to the allowed origin — an authorization
    # failure must be readable by legitimate frontend error handling, not
    # silently swallowed by a missing CORS header.
    assert response.headers["access-control-allow-origin"] == _ALLOWED_ORIGIN


def test_cors_does_not_broaden_authentication_for_a_disallowed_origin(
    monkeypatch: pytest.MonkeyPatch, postgres_engine: Engine
) -> None:
    app = _make_app(monkeypatch, postgres_engine, _ALLOWED_ORIGIN)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            _PROTECTED_PATH,
            json=_PROTECTED_BODY,
            headers={"Origin": "https://evil.example.com"},
        )
    assert response.status_code == 401
    assert "access-control-allow-origin" not in response.headers


def test_cors_does_not_broaden_authentication_with_no_origin_header_at_all(
    monkeypatch: pytest.MonkeyPatch, postgres_engine: Engine
) -> None:
    """Same rejection, no CORS involved at all — establishes that the 401
    above is the route's own ordinary behavior, not something CORS
    incidentally causes or prevents."""
    app = _make_app(monkeypatch, postgres_engine, _ALLOWED_ORIGIN)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(_PROTECTED_PATH, json=_PROTECTED_BODY)
    assert response.status_code == 401
