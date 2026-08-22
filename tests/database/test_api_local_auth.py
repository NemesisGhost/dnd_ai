"""API-layer smoke coverage for `dnd_ai.api.local_auth` and the local-
session branch of `dnd_ai.api.auth.get_authenticated_user_id` (docs/PLAN.md
§23.1, §23.4 — Phase 11R workstream A/B).

Deep behavioral correctness (password policy, single-use token
consumption, session expiry/revocation, constant-work login, ...) is
already covered at the command layer
(`tests/database/test_local_auth_commands.py`). This file proves the HTTP
wiring itself, plus the two things that only exist at the HTTP layer: the
`Set-Cookie`/cookie-read plumbing and CSRF/Origin/rate-limit enforcement —
matching the same "wiring, not re-proof" scope
`tests/database/test_api_ai_and_corpus.py`'s own docstring establishes for
its domain.

Two authentication styles are used deliberately, for different routes:
account-management endpoints (`/admin/accounts*`) are exercised with a
plain OIDC-principal dependency override (`oidc_principal`, the existing
test convention) since they accept any human auth method and CSRF is a
no-op for a non-cookie caller; the self-service/session endpoints
(`/auth/change-password`, `/auth/logout`, `/auth/sessions*`) are
exercised through a *real* `/auth/login` call and the resulting cookie/
CSRF token, since CSRF enforcement only ever applies to a
`LOCAL_SESSION_AUTH_METHOD` principal — overriding the dependency directly
would bypass the exact mechanism these tests exist to prove.
"""

import uuid
from collections.abc import Callable, Iterator
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from dnd_ai.api.app import create_app
from dnd_ai.api.auth import get_authenticated_user_id
from dnd_ai.api.deps import get_engine
from dnd_ai.api.local_auth import get_login_rate_limiter, get_token_consumption_rate_limiter
from dnd_ai.commands.local_auth import _create_local_account_impl
from dnd_ai.domain.rate_limit import RateLimiter
from tests.factories import make_platform_administrator, make_user, oidc_principal

pytestmark = pytest.mark.database

_DEV_ORIGIN = "http://localhost:5173"
_VALID_PASSWORD = "a genuinely random passphrase 1"
_OTHER_VALID_PASSWORD = "a different random passphrase 2"


@pytest.fixture
def admin_user_id(postgres_engine: Engine) -> Iterator[uuid.UUID]:
    with postgres_engine.begin() as connection:
        user_id = make_platform_administrator(connection)
    yield user_id


def _generous_rate_limiter() -> RateLimiter:
    return RateLimiter(max_attempts=10_000, window=timedelta(minutes=15))


@pytest.fixture
def client_factory(postgres_engine: Engine) -> Callable[[], TestClient]:
    """A fresh app/client with generous rate limits by default — the
    dedicated rate-limit test below overrides them back down explicitly.
    No `get_authenticated_user_id` override here: the local-session cookie
    branch is exactly what most tests in this file exercise for real."""

    def _make() -> TestClient:
        app = create_app()
        app.dependency_overrides[get_engine] = lambda: postgres_engine
        app.dependency_overrides[get_login_rate_limiter] = _generous_rate_limiter
        app.dependency_overrides[get_token_consumption_rate_limiter] = _generous_rate_limiter
        return TestClient(app, raise_server_exceptions=False)

    return _make


@pytest.fixture
def admin_client_factory(postgres_engine: Engine) -> Callable[[uuid.UUID], TestClient]:
    def _make(user_id: uuid.UUID) -> TestClient:
        app = create_app()
        app.dependency_overrides[get_engine] = lambda: postgres_engine
        app.dependency_overrides[get_login_rate_limiter] = _generous_rate_limiter
        app.dependency_overrides[get_token_consumption_rate_limiter] = _generous_rate_limiter
        app.dependency_overrides[get_authenticated_user_id] = lambda: oidc_principal(user_id)
        return TestClient(app, raise_server_exceptions=False)

    return _make


def _activate_via_api(
    client: TestClient, postgres_engine: Engine, admin_user_id: uuid.UUID, *, login_name: str
) -> None:
    with postgres_engine.begin() as connection:
        result = _create_local_account_impl(
            connection,
            created_by_user_id=admin_user_id,
            login_name=login_name,
            display_name="Test Account",
        )
    response = client.post(
        "/auth/activate",
        json={"token": result.raw_token, "password": _VALID_PASSWORD},
        headers={"Origin": _DEV_ORIGIN},
    )
    assert response.status_code == 200, response.text


# ---------------------------------------------------------------------------
# Admin account management (OIDC-principal-authenticated, no CSRF)
# ---------------------------------------------------------------------------


def test_create_account_requires_platform_administrator(
    admin_client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine
) -> None:
    with postgres_engine.begin() as connection:
        plain_user_id = make_user(connection)
    with admin_client_factory(plain_user_id) as client:
        response = client.post(
            "/admin/accounts",
            json={"login_name": f"forbidden-{uuid.uuid4().hex[:8]}", "display_name": "Nope"},
        )
    assert response.status_code == 404, response.text


def test_create_account_succeeds_for_platform_administrator(
    admin_client_factory: Callable[[uuid.UUID], TestClient], admin_user_id: uuid.UUID
) -> None:
    with admin_client_factory(admin_user_id) as client:
        response = client.post(
            "/admin/accounts",
            json={
                "login_name": f"newuser-{uuid.uuid4().hex[:8]}",
                "display_name": "New User",
            },
        )
    assert response.status_code == 201, response.text
    body = response.json()
    assert uuid.UUID(body["user_id"])
    assert body["raw_activation_token"]


# ---------------------------------------------------------------------------
# Activation -> login -> session bootstrap
# ---------------------------------------------------------------------------


def test_full_activation_and_login_flow(
    client_factory: Callable[[], TestClient], postgres_engine: Engine, admin_user_id: uuid.UUID
) -> None:
    login_name = f"flow-{uuid.uuid4().hex[:8]}"
    with client_factory() as client:
        _activate_via_api(client, postgres_engine, admin_user_id, login_name=login_name)

        login_response = client.post(
            "/auth/login",
            json={"login_name": login_name, "password": _VALID_PASSWORD},
            headers={"Origin": _DEV_ORIGIN},
        )
        assert login_response.status_code == 200, login_response.text
        assert "csrf_token" in login_response.json()
        cookie_name = next(iter(client.cookies.keys()), None)
        assert cookie_name is not None

        session_response = client.get("/auth/session")
        assert session_response.status_code == 200, session_response.text
        session_body = session_response.json()
        assert session_body["user_id"] == login_response.json()["user_id"]
        assert session_body["csrf_token"]


def test_login_rejects_wrong_password(
    client_factory: Callable[[], TestClient], postgres_engine: Engine, admin_user_id: uuid.UUID
) -> None:
    login_name = f"wrongpw-{uuid.uuid4().hex[:8]}"
    with client_factory() as client:
        _activate_via_api(client, postgres_engine, admin_user_id, login_name=login_name)
        response = client.post(
            "/auth/login",
            json={"login_name": login_name, "password": "totally wrong"},
            headers={"Origin": _DEV_ORIGIN},
        )
    assert response.status_code == 401, response.text


def test_login_rejects_unknown_login_name_with_the_same_status_as_wrong_password(
    client_factory: Callable[[], TestClient],
) -> None:
    with client_factory() as client:
        response = client.post(
            "/auth/login",
            json={"login_name": "no-such-user-at-all", "password": _VALID_PASSWORD},
            headers={"Origin": _DEV_ORIGIN},
        )
    assert response.status_code == 401, response.text


def test_session_endpoint_requires_authentication(client_factory: Callable[[], TestClient]) -> None:
    with client_factory() as client:
        response = client.get("/auth/session")
    assert response.status_code == 401, response.text


# ---------------------------------------------------------------------------
# CSRF / Origin enforcement
# ---------------------------------------------------------------------------


def test_change_password_without_csrf_header_is_rejected(
    client_factory: Callable[[], TestClient], postgres_engine: Engine, admin_user_id: uuid.UUID
) -> None:
    login_name = f"csrf-{uuid.uuid4().hex[:8]}"
    with client_factory() as client:
        _activate_via_api(client, postgres_engine, admin_user_id, login_name=login_name)
        client.post(
            "/auth/login",
            json={"login_name": login_name, "password": _VALID_PASSWORD},
            headers={"Origin": _DEV_ORIGIN},
        )
        response = client.post(
            "/auth/change-password",
            json={"current_password": _VALID_PASSWORD, "new_password": _OTHER_VALID_PASSWORD},
            headers={"Origin": _DEV_ORIGIN},
        )
    assert response.status_code == 403, response.text


def test_change_password_with_wrong_csrf_token_is_rejected(
    client_factory: Callable[[], TestClient], postgres_engine: Engine, admin_user_id: uuid.UUID
) -> None:
    login_name = f"csrf2-{uuid.uuid4().hex[:8]}"
    with client_factory() as client:
        _activate_via_api(client, postgres_engine, admin_user_id, login_name=login_name)
        client.post(
            "/auth/login",
            json={"login_name": login_name, "password": _VALID_PASSWORD},
            headers={"Origin": _DEV_ORIGIN},
        )
        response = client.post(
            "/auth/change-password",
            json={"current_password": _VALID_PASSWORD, "new_password": _OTHER_VALID_PASSWORD},
            headers={"Origin": _DEV_ORIGIN, "X-CSRF-Token": "not-the-real-token"},
        )
    assert response.status_code == 403, response.text


def test_change_password_from_a_disallowed_origin_is_rejected(
    client_factory: Callable[[], TestClient], postgres_engine: Engine, admin_user_id: uuid.UUID
) -> None:
    login_name = f"csrf3-{uuid.uuid4().hex[:8]}"
    with client_factory() as client:
        _activate_via_api(client, postgres_engine, admin_user_id, login_name=login_name)
        login_response = client.post(
            "/auth/login",
            json={"login_name": login_name, "password": _VALID_PASSWORD},
            headers={"Origin": _DEV_ORIGIN},
        )
        csrf_token = login_response.json()["csrf_token"]
        response = client.post(
            "/auth/change-password",
            json={"current_password": _VALID_PASSWORD, "new_password": _OTHER_VALID_PASSWORD},
            headers={"Origin": "https://evil.example.com", "X-CSRF-Token": csrf_token},
        )
    assert response.status_code == 403, response.text


def test_change_password_with_correct_csrf_and_origin_succeeds(
    client_factory: Callable[[], TestClient], postgres_engine: Engine, admin_user_id: uuid.UUID
) -> None:
    login_name = f"csrf4-{uuid.uuid4().hex[:8]}"
    with client_factory() as client:
        _activate_via_api(client, postgres_engine, admin_user_id, login_name=login_name)
        login_response = client.post(
            "/auth/login",
            json={"login_name": login_name, "password": _VALID_PASSWORD},
            headers={"Origin": _DEV_ORIGIN},
        )
        csrf_token = login_response.json()["csrf_token"]
        response = client.post(
            "/auth/change-password",
            json={"current_password": _VALID_PASSWORD, "new_password": _OTHER_VALID_PASSWORD},
            headers={"Origin": _DEV_ORIGIN, "X-CSRF-Token": csrf_token},
        )
        assert response.status_code == 204, response.text

        relogin = client.post(
            "/auth/login",
            json={"login_name": login_name, "password": _OTHER_VALID_PASSWORD},
            headers={"Origin": _DEV_ORIGIN},
        )
    assert relogin.status_code == 200, relogin.text


def test_get_requests_do_not_require_csrf(
    client_factory: Callable[[], TestClient], postgres_engine: Engine, admin_user_id: uuid.UUID
) -> None:
    login_name = f"csrfget-{uuid.uuid4().hex[:8]}"
    with client_factory() as client:
        _activate_via_api(client, postgres_engine, admin_user_id, login_name=login_name)
        client.post(
            "/auth/login",
            json={"login_name": login_name, "password": _VALID_PASSWORD},
            headers={"Origin": _DEV_ORIGIN},
        )
        response = client.get("/auth/sessions")
    assert response.status_code == 200, response.text


# ---------------------------------------------------------------------------
# Logout and session listing/revocation
# ---------------------------------------------------------------------------


def test_logout_revokes_the_session(
    client_factory: Callable[[], TestClient], postgres_engine: Engine, admin_user_id: uuid.UUID
) -> None:
    login_name = f"logout-{uuid.uuid4().hex[:8]}"
    with client_factory() as client:
        _activate_via_api(client, postgres_engine, admin_user_id, login_name=login_name)
        login_response = client.post(
            "/auth/login",
            json={"login_name": login_name, "password": _VALID_PASSWORD},
            headers={"Origin": _DEV_ORIGIN},
        )
        csrf_token = login_response.json()["csrf_token"]
        logout_response = client.post(
            "/auth/logout", headers={"Origin": _DEV_ORIGIN, "X-CSRF-Token": csrf_token}
        )
        assert logout_response.status_code == 204, logout_response.text

        after_logout = client.get("/auth/session")
    assert after_logout.status_code == 401, after_logout.text


def test_list_and_revoke_sessions(
    client_factory: Callable[[], TestClient], postgres_engine: Engine, admin_user_id: uuid.UUID
) -> None:
    login_name = f"listrev-{uuid.uuid4().hex[:8]}"
    with client_factory() as client:
        _activate_via_api(client, postgres_engine, admin_user_id, login_name=login_name)
        login_response = client.post(
            "/auth/login",
            json={"login_name": login_name, "password": _VALID_PASSWORD},
            headers={"Origin": _DEV_ORIGIN},
        )
        csrf_token = login_response.json()["csrf_token"]

        list_response = client.get("/auth/sessions")
        assert list_response.status_code == 200, list_response.text
        sessions = list_response.json()
        assert len(sessions) == 1
        assert sessions[0]["is_current"] is True
        current_session_id = sessions[0]["browser_session_id"]

        revoke_response = client.delete(
            f"/auth/sessions/{current_session_id}",
            headers={"Origin": _DEV_ORIGIN, "X-CSRF-Token": csrf_token},
        )
        assert revoke_response.status_code == 204, revoke_response.text

        after_revoke = client.get("/auth/session")
    assert after_revoke.status_code == 401, after_revoke.text


# ---------------------------------------------------------------------------
# Password reset (admin-issued)
# ---------------------------------------------------------------------------


def test_password_reset_flow(
    admin_client_factory: Callable[[uuid.UUID], TestClient],
    client_factory: Callable[[], TestClient],
    postgres_engine: Engine,
    admin_user_id: uuid.UUID,
) -> None:
    login_name = f"reset-{uuid.uuid4().hex[:8]}"
    with client_factory() as client:
        _activate_via_api(client, postgres_engine, admin_user_id, login_name=login_name)
        with postgres_engine.begin() as connection:
            target_user_id = connection.execute(
                text(
                    "SELECT user_id FROM security.external_identities "
                    "WHERE issuer = 'local' AND subject = :s"
                ),
                {"s": login_name},
            ).scalar()

        with admin_client_factory(admin_user_id) as admin_client:
            issue_response = admin_client.post(
                f"/admin/accounts/{target_user_id}/password-reset", json={}
            )
        assert issue_response.status_code == 201, issue_response.text
        raw_reset_token = issue_response.json()["raw_reset_token"]

        reset_response = client.post(
            "/auth/password-reset",
            json={"token": raw_reset_token, "new_password": _OTHER_VALID_PASSWORD},
            headers={"Origin": _DEV_ORIGIN},
        )
        assert reset_response.status_code == 200, reset_response.text
        assert reset_response.json()["sessions_revoked"] is True

        old_password_login = client.post(
            "/auth/login",
            json={"login_name": login_name, "password": _VALID_PASSWORD},
            headers={"Origin": _DEV_ORIGIN},
        )
        assert old_password_login.status_code == 401

        new_password_login = client.post(
            "/auth/login",
            json={"login_name": login_name, "password": _OTHER_VALID_PASSWORD},
            headers={"Origin": _DEV_ORIGIN},
        )
    assert new_password_login.status_code == 200, new_password_login.text


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


def test_login_is_rate_limited(postgres_engine: Engine) -> None:
    # One shared instance, captured by the override closure — FastAPI
    # calls the override on every request, so a lambda that *constructs* a
    # fresh RateLimiter each time would give every request its own,
    # always-empty limiter and never actually rate limit anything.
    shared_limiter = RateLimiter(max_attempts=2, window=timedelta(minutes=15))

    app = create_app()
    app.dependency_overrides[get_engine] = lambda: postgres_engine
    app.dependency_overrides[get_login_rate_limiter] = lambda: shared_limiter
    app.dependency_overrides[get_token_consumption_rate_limiter] = _generous_rate_limiter
    with TestClient(app, raise_server_exceptions=False) as client:
        for _ in range(2):
            response = client.post(
                "/auth/login",
                json={"login_name": "irrelevant", "password": "irrelevant-too-but-long-enough"},
                headers={"Origin": _DEV_ORIGIN},
            )
            assert response.status_code == 401
        limited_response = client.post(
            "/auth/login",
            json={"login_name": "irrelevant", "password": "irrelevant-too-but-long-enough"},
            headers={"Origin": _DEV_ORIGIN},
        )
    assert limited_response.status_code == 429, limited_response.text
