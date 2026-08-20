"""CORS/preflight regression tests for the Foundry-adapter transport-layer
security fix (Issue 1). `src/dnd_ai/api/app.py` installs `CORSMiddleware`
using `dnd_ai.config.settings.foundry_allowed_origins` as its allowlist —
these tests monkeypatch that already-loaded singleton (never `Settings()`
directly, since `create_app()`/`dnd_ai.config.settings` is a module-level
value read once at import time) and call `create_app()` fresh per test, so
each test gets its own middleware stack built from its own allowlist.

No PostgreSQL is needed: every request below is either `GET /healthz`
(deliberately database-independent, `dnd_ai.api.app`'s own docstring) or an
`OPTIONS` preflight, which `starlette.middleware.cors.CORSMiddleware`
answers directly — it never calls the wrapped application at all for a
preflight, so the target path's own dependencies (auth, database) never
run. `tests/database/test_api_cors.py` covers the complementary claim that
CORS never changes what an *actual*, non-preflight authenticated request
resolves to — that needs a real database and OIDC wiring
(`dnd_ai.api.auth.get_authenticated_user_id` depends on both even to reject
a request outright), so it belongs there, not here. `TestClient`'s
lifespan does not touch the database either, since
`dnd_ai.config.settings.environment` is not `"production"` in this test
process (`dnd_ai.api.app._lifespan`'s own docstring).
"""

import pytest
from fastapi.testclient import TestClient

import dnd_ai.config as config
from dnd_ai.api.app import create_app

pytestmark = pytest.mark.unit

_ALLOWED_ORIGIN = "https://foundry.example.com"

# An arbitrary authenticated-looking path — CORS preflight is answered by
# CORSMiddleware directly (confirmed against starlette's own source: a
# preflight never calls the wrapped application), so this path's real
# dependencies (auth, database) are never exercised by any test below.
_PROTECTED_PATH = "/campaigns/00000000-0000-0000-0000-000000000000/events"


@pytest.fixture
def app_with_origin(monkeypatch: pytest.MonkeyPatch):
    def _make(origin: str | None):
        monkeypatch.setattr(config.settings, "foundry_allowed_origins", origin)
        return create_app()

    return _make


def test_preflight_from_an_allowed_origin_succeeds_with_the_required_headers(
    app_with_origin,
) -> None:
    app = app_with_origin(_ALLOWED_ORIGIN)
    with TestClient(app) as client:
        response = client.options(
            _PROTECTED_PATH,
            headers={
                "Origin": _ALLOWED_ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type,idempotency-key",
            },
        )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == _ALLOWED_ORIGIN
    allowed_methods = response.headers["access-control-allow-methods"]
    assert "POST" in allowed_methods
    allowed_headers = response.headers["access-control-allow-headers"].lower()
    assert "authorization" in allowed_headers
    assert "content-type" in allowed_headers
    assert "idempotency-key" in allowed_headers


def test_preflight_requesting_x_foundry_actor_id_is_permitted(app_with_origin) -> None:
    app = app_with_origin(_ALLOWED_ORIGIN)
    with TestClient(app) as client:
        response = client.options(
            _PROTECTED_PATH,
            headers={
                "Origin": _ALLOWED_ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "x-foundry-actor-id",
            },
        )
    assert response.status_code == 200
    assert "x-foundry-actor-id" in response.headers["access-control-allow-headers"].lower()


def test_the_following_actual_request_exposes_its_response_to_the_allowed_origin(
    app_with_origin,
) -> None:
    app = app_with_origin(_ALLOWED_ORIGIN)
    with TestClient(app) as client:
        response = client.get("/healthz", headers={"Origin": _ALLOWED_ORIGIN})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == _ALLOWED_ORIGIN
    # allow_credentials=False (dnd_ai.api.app.create_app) — the module
    # authenticates with an Authorization header, never a cookie, so
    # credentialed CORS must never be enabled.
    assert "access-control-allow-credentials" not in response.headers


@pytest.mark.parametrize(
    "foreign_origin",
    [
        "https://evil.example.com",
        # A subdomain of the allowed origin must never match — exact-origin
        # allowlisting only, no wildcarded-subdomain behavior.
        "https://sub.foundry.example.com",
        # Same host, wrong scheme.
        "http://foundry.example.com",
        # Origin header cannot legitimately carry a path, but a
        # non-browser client could still send one — it must not match by
        # prefix.
        "https://foundry.example.com/evil",
    ],
)
def test_ordinary_disallowed_origins_receive_no_permissive_cors_headers(
    app_with_origin, foreign_origin: str
) -> None:
    app = app_with_origin(_ALLOWED_ORIGIN)
    with TestClient(app) as client:
        response = client.get("/healthz", headers={"Origin": foreign_origin})
    # The request itself still succeeds server-side (CORS is a
    # browser-enforced read restriction, not a server-side access
    # control) — it just must carry no header that would let a browser
    # expose the response to that origin's JavaScript.
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_a_disallowed_origins_preflight_is_also_rejected(app_with_origin) -> None:
    app = app_with_origin(_ALLOWED_ORIGIN)
    with TestClient(app) as client:
        response = client.options(
            _PROTECTED_PATH,
            headers={
                "Origin": "https://evil.example.com",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization",
            },
        )
    assert "access-control-allow-origin" not in response.headers


def test_an_unconfigured_allowlist_permits_no_cross_origin_access(app_with_origin) -> None:
    """No unsafe fallback: leaving DND_AI_FOUNDRY_ALLOWED_ORIGINS unset must
    never widen to "allow anything" — it must narrow to "allow nothing.\""""
    app = app_with_origin(None)
    with TestClient(app) as client:
        response = client.get("/healthz", headers={"Origin": _ALLOWED_ORIGIN})
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


### See tests/database/test_api_cors.py for "CORS does not broaden
### authentication" — that assertion requires a real, authenticated
### (non-preflight) request, which needs a real database connection and
### OIDC wiring even to be rejected (see this module's own docstring).
