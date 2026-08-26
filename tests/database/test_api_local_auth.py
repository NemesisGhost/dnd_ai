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

import contextlib
import uuid
from collections.abc import Callable, Iterator
from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from dnd_ai.api.app import create_app
from dnd_ai.api.auth import get_authenticated_user_id
from dnd_ai.api.deps import get_engine
from dnd_ai.api.local_auth import (
    get_login_account_rate_limiter,
    get_login_ip_rate_limiter,
    get_token_consumption_rate_limiter,
)
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
        app.dependency_overrides[get_login_ip_rate_limiter] = _generous_rate_limiter
        app.dependency_overrides[get_login_account_rate_limiter] = _generous_rate_limiter
        app.dependency_overrides[get_token_consumption_rate_limiter] = _generous_rate_limiter
        return TestClient(app, raise_server_exceptions=False)

    return _make


@pytest.fixture
def admin_client_factory(postgres_engine: Engine) -> Callable[[uuid.UUID], TestClient]:
    def _make(user_id: uuid.UUID) -> TestClient:
        app = create_app()
        app.dependency_overrides[get_engine] = lambda: postgres_engine
        app.dependency_overrides[get_login_ip_rate_limiter] = _generous_rate_limiter
        app.dependency_overrides[get_login_account_rate_limiter] = _generous_rate_limiter
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
        assert session_body["user"]["user_id"] == login_response.json()["user_id"]
        assert session_body["csrf_token"]
        assert session_body["campaigns"] == []
        assert session_body["selected_campaign_id"] is None
        assert session_body["features"] == {
            "ask": False,
            "ai_summaries": False,
            "gm_briefs": False,
            "cited_rules": False,
        }


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


def _login_app(
    postgres_engine: Engine,
    *,
    ip_rate_limiter: RateLimiter,
    account_rate_limiter: RateLimiter,
) -> FastAPI:
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: postgres_engine
    app.dependency_overrides[get_login_ip_rate_limiter] = lambda: ip_rate_limiter
    app.dependency_overrides[get_login_account_rate_limiter] = lambda: account_rate_limiter
    app.dependency_overrides[get_token_consumption_rate_limiter] = _generous_rate_limiter
    return app


def _attempt_login(
    client: TestClient, *, login_name: str, password: str = "wrong-but-long-enough"
) -> int:
    return client.post(
        "/auth/login",
        json={"login_name": login_name, "password": password},
        headers={"Origin": _DEV_ORIGIN},
    ).status_code


def test_login_is_rate_limited(postgres_engine: Engine) -> None:
    # One shared instance per limiter, captured by the override closure —
    # FastAPI calls the override on every request, so a lambda that
    # *constructs* a fresh RateLimiter each time would give every request
    # its own, always-empty limiter and never actually rate limit
    # anything.
    ip_limiter = RateLimiter(max_attempts=2, window=timedelta(minutes=15))
    account_limiter = RateLimiter(max_attempts=10_000, window=timedelta(minutes=15))
    app = _login_app(
        postgres_engine, ip_rate_limiter=ip_limiter, account_rate_limiter=account_limiter
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        for _ in range(2):
            assert _attempt_login(client, login_name="irrelevant") == 401
        assert _attempt_login(client, login_name="irrelevant") == 429


def test_ip_wide_limiter_blocks_regardless_of_varying_login_names(postgres_engine: Engine) -> None:
    """The exact bypass this correction closes: an unauthenticated caller
    that varies `login_name` on every request must not obtain a fresh
    rate-limit bucket each time — the IP-wide ceiling applies regardless
    of what name is submitted."""
    ip_limiter = RateLimiter(max_attempts=5, window=timedelta(minutes=15))
    account_limiter = RateLimiter(max_attempts=10_000, window=timedelta(minutes=15))
    app = _login_app(
        postgres_engine, ip_rate_limiter=ip_limiter, account_rate_limiter=account_limiter
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        for i in range(5):
            assert _attempt_login(client, login_name=f"never-existed-{i}") == 401
        # A sixth attempt, with yet another brand-new login_name, is still
        # blocked — proving the ceiling is keyed on the caller's address,
        # not on the (now-exhausted) composite pair.
        assert _attempt_login(client, login_name="never-existed-yet-again") == 429


def test_account_wide_limiter_blocks_across_multiple_source_addresses(
    postgres_engine: Engine,
) -> None:
    """One targeted login name, attacked from several different source
    addresses, must still hit an account-wide ceiling — an IP-wide limiter
    alone would let a distributed attacker reset the count merely by
    switching addresses."""
    ip_limiter = RateLimiter(max_attempts=10_000, window=timedelta(minutes=15))
    account_limiter = RateLimiter(max_attempts=4, window=timedelta(minutes=15))
    app = _login_app(
        postgres_engine, ip_rate_limiter=ip_limiter, account_rate_limiter=account_limiter
    )
    target_login_name = "targeted-account-does-not-need-to-exist"
    with contextlib.ExitStack() as stack:
        # Five distinct source addresses hitting the same shared `app` (and
        # therefore the same overridden limiter instances) — proves the
        # ceiling follows the account, not any one address.
        clients = [
            stack.enter_context(
                TestClient(app, raise_server_exceptions=False, client=(f"203.0.113.{i}", 51000))
            )
            for i in range(5)
        ]
        for client in clients[:4]:
            assert _attempt_login(client, login_name=target_login_name) == 401
        # A fifth attempt against the same account, from yet another
        # address, is still blocked.
        assert _attempt_login(clients[4], login_name=target_login_name) == 429


def test_distinct_legitimate_users_are_not_collapsed_into_one_account_bucket(
    client_factory: Callable[[], TestClient], postgres_engine: Engine, admin_user_id: uuid.UUID
) -> None:
    login_a = f"bucketa-{uuid.uuid4().hex[:8]}"
    login_b = f"bucketb-{uuid.uuid4().hex[:8]}"
    with client_factory() as client:
        _activate_via_api(client, postgres_engine, admin_user_id, login_name=login_a)
        _activate_via_api(client, postgres_engine, admin_user_id, login_name=login_b)

        # A few failed attempts against account B must not affect account
        # A's own bucket.
        for _ in range(3):
            assert _attempt_login(client, login_name=login_b) == 401

        response = client.post(
            "/auth/login",
            json={"login_name": login_a, "password": _VALID_PASSWORD},
            headers={"Origin": _DEV_ORIGIN},
        )
    assert response.status_code == 200, response.text


def test_oversized_login_name_is_rejected_before_any_backend_work(
    client_factory: Callable[[], TestClient], postgres_engine: Engine
) -> None:
    # This shared session database routinely already has login_failure
    # rows from earlier tests by the time this one runs — the assertion
    # below proves this specific request added none, not that none exist
    # at all.
    before = _audit_row_count(postgres_engine, command_name="local_auth.login_failure")
    oversized_login_name = "x" * 65  # one past dnd_ai.commands.local_auth's 64-char maximum
    with client_factory() as client:
        response = client.post(
            "/auth/login",
            json={"login_name": oversized_login_name, "password": "irrelevant-but-long-enough"},
            headers={"Origin": _DEV_ORIGIN},
        )
    assert response.status_code == 422, response.text
    assert _audit_row_count(postgres_engine, command_name="local_auth.login_failure") == before


def test_oversized_password_is_rejected_before_any_backend_work(
    client_factory: Callable[[], TestClient], postgres_engine: Engine
) -> None:
    before = _audit_row_count(postgres_engine, command_name="local_auth.login_failure")
    oversized_password = "x" * 513  # one past MAX_PASSWORD_LENGTH
    with client_factory() as client:
        response = client.post(
            "/auth/login",
            json={"login_name": "irrelevant", "password": oversized_password},
            headers={"Origin": _DEV_ORIGIN},
        )
    assert response.status_code == 422, response.text
    assert _audit_row_count(postgres_engine, command_name="local_auth.login_failure") == before


def test_rate_limited_attempts_do_not_create_unbounded_audit_rows(postgres_engine: Engine) -> None:
    ip_limiter = RateLimiter(max_attempts=3, window=timedelta(minutes=15))
    account_limiter = RateLimiter(max_attempts=10_000, window=timedelta(minutes=15))
    app = _login_app(
        postgres_engine, ip_rate_limiter=ip_limiter, account_rate_limiter=account_limiter
    )
    login_name = f"unbounded-audit-check-{uuid.uuid4().hex[:8]}"
    with TestClient(app, raise_server_exceptions=False) as client:
        # 3 admitted (and therefore audited) failures, then many more
        # rate-limited (and therefore never-audited) ones.
        for _ in range(3):
            assert _attempt_login(client, login_name=login_name) == 401
        for _ in range(20):
            assert _attempt_login(client, login_name=login_name) == 429

    with postgres_engine.begin() as connection:
        count = connection.execute(
            text("""
                SELECT count(*) FROM audit.change_log cl
                JOIN audit.change_actions ca ON ca.change_action_id = cl.change_action_id
                WHERE cl.command_name = 'local_auth.login_failure'
                  AND cl.changed_fields ->> 'login_name' = :login_name
            """),
            {"login_name": login_name},
        ).scalar_one()
    assert count == 3


# ---------------------------------------------------------------------------
# Administrative account lifecycle (Phase 13B blocker 3)
# ---------------------------------------------------------------------------


def _create_and_activate(
    client: TestClient, postgres_engine: Engine, admin_user_id: uuid.UUID, *, login_name: str
) -> uuid.UUID:
    _activate_via_api(client, postgres_engine, admin_user_id, login_name=login_name)
    with postgres_engine.begin() as connection:
        user_id = connection.execute(
            text(
                "SELECT user_id FROM security.external_identities "
                "WHERE issuer = 'local' AND subject = :s"
            ),
            {"s": login_name},
        ).scalar()
    assert isinstance(user_id, uuid.UUID)
    return user_id


def test_disable_account_requires_platform_administrator(
    admin_client_factory: Callable[[uuid.UUID], TestClient],
    postgres_engine: Engine,
) -> None:
    with postgres_engine.begin() as connection:
        plain_user_id = make_user(connection)
        target_user_id = make_user(connection)
    with admin_client_factory(plain_user_id) as client:
        response = client.post(f"/admin/accounts/{target_user_id}/disable")
    assert response.status_code == 404, response.text


def test_disable_account_rejects_missing_target(
    admin_client_factory: Callable[[uuid.UUID], TestClient], admin_user_id: uuid.UUID
) -> None:
    with admin_client_factory(admin_user_id) as client:
        response = client.post(f"/admin/accounts/{uuid.uuid4()}/disable")
    assert response.status_code == 404, response.text


def test_disable_account_rejects_the_sole_active_administrator_with_a_safe_error(
    admin_client_factory: Callable[[uuid.UUID], TestClient],
    postgres_engine: Engine,
    admin_user_id: uuid.UUID,
) -> None:
    # Neutralize every other already-committed active administrator in
    # this shared session database (there are typically several, from
    # earlier tests' own admin_user_id fixtures) so admin_user_id is
    # genuinely the sole one, on this test's own connection only —
    # restored afterward so no lasting effect touches later tests.
    with postgres_engine.begin() as connection:
        other_active_admin_ids = [
            row[0]
            for row in connection.execute(
                text("""
                    SELECT u.user_id FROM security.users u
                    JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = u.lifecycle_status_id
                    WHERE u.is_platform_administrator AND ls.code = 'active'
                      AND u.user_id != :keep
                """),
                {"keep": admin_user_id},
            )
        ]
        if other_active_admin_ids:
            inactive_status = connection.execute(
                text(
                    "SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'inactive'"
                )
            ).scalar_one()
            connection.execute(
                text(
                    "UPDATE security.users SET lifecycle_status_id = :status "
                    "WHERE user_id = ANY(:ids)"
                ),
                {"status": inactive_status, "ids": other_active_admin_ids},
            )
    try:
        with admin_client_factory(admin_user_id) as client:
            response = client.post(f"/admin/accounts/{admin_user_id}/disable")
        assert response.status_code == 409, response.text
        body = response.json()
        assert body["error"]["code"] == "last_active_platform_administrator"
        # A fixed, safe message only — never any other user's id, name, or
        # status.
        assert str(admin_user_id) not in body["error"]["message"]
    finally:
        if other_active_admin_ids:
            with postgres_engine.begin() as connection:
                active_status = connection.execute(
                    text(
                        "SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'active'"
                    )
                ).scalar_one()
                connection.execute(
                    text(
                        "UPDATE security.users SET lifecycle_status_id = :status "
                        "WHERE user_id = ANY(:ids)"
                    ),
                    {"status": active_status, "ids": other_active_admin_ids},
                )


def test_disable_account_revokes_active_sessions_and_blocks_next_login(
    client_factory: Callable[[], TestClient],
    admin_client_factory: Callable[[uuid.UUID], TestClient],
    postgres_engine: Engine,
    admin_user_id: uuid.UUID,
) -> None:
    login_name = f"disable-{uuid.uuid4().hex[:8]}"
    with client_factory() as client:
        target_user_id = _create_and_activate(
            client, postgres_engine, admin_user_id, login_name=login_name
        )
        login_response = client.post(
            "/auth/login",
            json={"login_name": login_name, "password": _VALID_PASSWORD},
            headers={"Origin": _DEV_ORIGIN},
        )
        assert login_response.status_code == 200, login_response.text

        with admin_client_factory(admin_user_id) as admin_client:
            disable_response = admin_client.post(f"/admin/accounts/{target_user_id}/disable")
        assert disable_response.status_code == 200, disable_response.text
        body = disable_response.json()
        assert body["previous_lifecycle_status"] == "active"
        assert body["new_lifecycle_status"] == "inactive"

        # The session that was valid before disablement is rejected on its
        # very next request.
        after_disable = client.get("/auth/session")
        assert after_disable.status_code == 401, after_disable.text

        relogin = client.post(
            "/auth/login",
            json={"login_name": login_name, "password": _VALID_PASSWORD},
            headers={"Origin": _DEV_ORIGIN},
        )
    assert relogin.status_code == 401, relogin.text


def test_reactivate_account_restores_login_but_not_the_old_session(
    client_factory: Callable[[], TestClient],
    admin_client_factory: Callable[[uuid.UUID], TestClient],
    postgres_engine: Engine,
    admin_user_id: uuid.UUID,
) -> None:
    login_name = f"reactivate-{uuid.uuid4().hex[:8]}"
    with client_factory() as client:
        target_user_id = _create_and_activate(
            client, postgres_engine, admin_user_id, login_name=login_name
        )
        first_login = client.post(
            "/auth/login",
            json={"login_name": login_name, "password": _VALID_PASSWORD},
            headers={"Origin": _DEV_ORIGIN},
        )
        assert first_login.status_code == 200, first_login.text

        with admin_client_factory(admin_user_id) as admin_client:
            admin_client.post(f"/admin/accounts/{target_user_id}/disable")
            reactivate_response = admin_client.post(f"/admin/accounts/{target_user_id}/reactivate")
        assert reactivate_response.status_code == 200, reactivate_response.text
        body = reactivate_response.json()
        assert body["previous_lifecycle_status"] == "inactive"
        assert body["new_lifecycle_status"] == "active"

        # The old cookie/session is not resurrected...
        stale_session = client.get("/auth/session")
        assert stale_session.status_code == 401, stale_session.text

        # ...but a fresh login succeeds.
        relogin = client.post(
            "/auth/login",
            json={"login_name": login_name, "password": _VALID_PASSWORD},
            headers={"Origin": _DEV_ORIGIN},
        )
    assert relogin.status_code == 200, relogin.text


def test_admin_revoke_sessions_requires_platform_administrator(
    admin_client_factory: Callable[[uuid.UUID], TestClient],
    postgres_engine: Engine,
) -> None:
    with postgres_engine.begin() as connection:
        plain_user_id = make_user(connection)
        target_user_id = make_user(connection)
    with admin_client_factory(plain_user_id) as client:
        response = client.post(f"/admin/accounts/{target_user_id}/revoke-sessions")
    assert response.status_code == 404, response.text


def test_admin_revoke_sessions_rejects_missing_target(
    admin_client_factory: Callable[[uuid.UUID], TestClient], admin_user_id: uuid.UUID
) -> None:
    with admin_client_factory(admin_user_id) as client:
        response = client.post(f"/admin/accounts/{uuid.uuid4()}/revoke-sessions")
    assert response.status_code == 404, response.text


def test_admin_revoke_sessions_revokes_multiple_sessions_and_leaves_the_account_active(
    client_factory: Callable[[], TestClient],
    admin_client_factory: Callable[[uuid.UUID], TestClient],
    postgres_engine: Engine,
    admin_user_id: uuid.UUID,
) -> None:
    login_name = f"revokeall-{uuid.uuid4().hex[:8]}"
    with client_factory() as first_browser, client_factory() as second_browser:
        target_user_id = _create_and_activate(
            first_browser, postgres_engine, admin_user_id, login_name=login_name
        )
        assert (
            first_browser.post(
                "/auth/login",
                json={"login_name": login_name, "password": _VALID_PASSWORD},
                headers={"Origin": _DEV_ORIGIN},
            ).status_code
            == 200
        )
        assert (
            second_browser.post(
                "/auth/login",
                json={"login_name": login_name, "password": _VALID_PASSWORD},
                headers={"Origin": _DEV_ORIGIN},
            ).status_code
            == 200
        )

        with admin_client_factory(admin_user_id) as admin_client:
            response = admin_client.post(f"/admin/accounts/{target_user_id}/revoke-sessions")
        assert response.status_code == 200, response.text
        assert response.json()["revoked_count"] == 2

        assert first_browser.get("/auth/session").status_code == 401
        assert second_browser.get("/auth/session").status_code == 401

        # The account itself was never disabled — a fresh login still works.
        relogin = first_browser.post(
            "/auth/login",
            json={"login_name": login_name, "password": _VALID_PASSWORD},
            headers={"Origin": _DEV_ORIGIN},
        )
    assert relogin.status_code == 200, relogin.text


def test_admin_revoke_sessions_does_not_affect_other_users(
    client_factory: Callable[[], TestClient],
    admin_client_factory: Callable[[uuid.UUID], TestClient],
    postgres_engine: Engine,
    admin_user_id: uuid.UUID,
) -> None:
    login_a = f"isolationa-{uuid.uuid4().hex[:8]}"
    login_b = f"isolationb-{uuid.uuid4().hex[:8]}"
    with client_factory() as client_a, client_factory() as client_b:
        user_a = _create_and_activate(client_a, postgres_engine, admin_user_id, login_name=login_a)
        _create_and_activate(client_b, postgres_engine, admin_user_id, login_name=login_b)
        client_a.post(
            "/auth/login",
            json={"login_name": login_a, "password": _VALID_PASSWORD},
            headers={"Origin": _DEV_ORIGIN},
        )
        client_b.post(
            "/auth/login",
            json={"login_name": login_b, "password": _VALID_PASSWORD},
            headers={"Origin": _DEV_ORIGIN},
        )

        with admin_client_factory(admin_user_id) as admin_client:
            admin_client.post(f"/admin/accounts/{user_a}/revoke-sessions")

        assert client_a.get("/auth/session").status_code == 401
    assert client_b.get("/auth/session").status_code == 200


# ---------------------------------------------------------------------------
# Durable security-action auditing (Phase 13B blocker 3)
# ---------------------------------------------------------------------------


def _latest_audit_row(postgres_engine: Engine, *, command_name: str) -> dict[str, object] | None:
    with postgres_engine.begin() as connection:
        row = (
            connection.execute(
                text("""
                    SELECT cl.*, ca.code AS change_action_code
                    FROM audit.change_log cl
                    JOIN audit.change_actions ca ON ca.change_action_id = cl.change_action_id
                    WHERE cl.command_name = :command_name
                    ORDER BY cl.change_log_id DESC
                    LIMIT 1
                """),
                {"command_name": command_name},
            )
            .mappings()
            .one_or_none()
        )
    return dict(row) if row is not None else None


def _audit_row_count(postgres_engine: Engine, *, command_name: str) -> int:
    """Total rows for `command_name`, across this shared session database
    — used where a test needs to prove *no new row was added by its own
    request* (a before/after comparison), since this database routinely
    already has rows for a given `command_name` from earlier tests by the
    time any one test runs; unlike `_latest_audit_row`, "is there a row at
    all" is never the right question here."""
    with postgres_engine.begin() as connection:
        return connection.execute(
            text("SELECT count(*) FROM audit.change_log WHERE command_name = :command_name"),
            {"command_name": command_name},
        ).scalar_one()


def test_successful_login_is_audited(
    client_factory: Callable[[], TestClient], postgres_engine: Engine, admin_user_id: uuid.UUID
) -> None:
    login_name = f"auditlogin-{uuid.uuid4().hex[:8]}"
    with client_factory() as client:
        target_user_id = _create_and_activate(
            client, postgres_engine, admin_user_id, login_name=login_name
        )
        response = client.post(
            "/auth/login",
            json={"login_name": login_name, "password": _VALID_PASSWORD},
            headers={"Origin": _DEV_ORIGIN},
        )
    assert response.status_code == 200, response.text
    row = _latest_audit_row(postgres_engine, command_name="local_auth.login_success")
    assert row is not None
    assert row["actor_user_id"] == target_user_id
    assert row["change_action_code"] == "created"


def test_failed_login_is_audited_without_disclosing_the_reason(
    client_factory: Callable[[], TestClient], postgres_engine: Engine
) -> None:
    login_name = f"auditfail-{uuid.uuid4().hex[:8]}"
    with client_factory() as client:
        response = client.post(
            "/auth/login",
            json={"login_name": login_name, "password": "totally wrong but long enough"},
            headers={"Origin": _DEV_ORIGIN},
        )
    assert response.status_code == 401, response.text
    row = _latest_audit_row(postgres_engine, command_name="local_auth.login_failure")
    assert row is not None
    assert row["actor_user_id"] is None
    assert row["actor_service"] == "local_auth"
    assert row["change_action_code"] == "denied"
    assert row["changed_fields"] == {"login_name": login_name.strip().lower()}
    # No password, ever — the only caller-influenced content stored is the
    # login name itself.
    assert "totally wrong" not in str(row)


def test_account_disablement_is_audited_with_status_transition(
    admin_client_factory: Callable[[uuid.UUID], TestClient],
    client_factory: Callable[[], TestClient],
    postgres_engine: Engine,
    admin_user_id: uuid.UUID,
) -> None:
    login_name = f"auditdisable-{uuid.uuid4().hex[:8]}"
    with client_factory() as client:
        target_user_id = _create_and_activate(
            client, postgres_engine, admin_user_id, login_name=login_name
        )
    with admin_client_factory(admin_user_id) as admin_client:
        response = admin_client.post(f"/admin/accounts/{target_user_id}/disable")
    assert response.status_code == 200, response.text
    row = _latest_audit_row(postgres_engine, command_name="local_auth.disable_account")
    assert row is not None
    assert row["actor_user_id"] == admin_user_id
    assert row["record_id"] == target_user_id
    assert row["previous_status"] == "active"
    assert row["new_status"] == "inactive"


def test_admin_revoke_all_sessions_is_audited_with_session_count(
    admin_client_factory: Callable[[uuid.UUID], TestClient],
    client_factory: Callable[[], TestClient],
    postgres_engine: Engine,
    admin_user_id: uuid.UUID,
) -> None:
    login_name = f"auditrevokeall-{uuid.uuid4().hex[:8]}"
    with client_factory() as client:
        target_user_id = _create_and_activate(
            client, postgres_engine, admin_user_id, login_name=login_name
        )
        client.post(
            "/auth/login",
            json={"login_name": login_name, "password": _VALID_PASSWORD},
            headers={"Origin": _DEV_ORIGIN},
        )
    with admin_client_factory(admin_user_id) as admin_client:
        response = admin_client.post(f"/admin/accounts/{target_user_id}/revoke-sessions")
    assert response.status_code == 200, response.text
    row = _latest_audit_row(postgres_engine, command_name="local_auth.admin_revoke_all_sessions")
    assert row is not None
    assert row["changed_fields"] == {"revoked_session_count": 1}


def test_password_change_is_audited(
    client_factory: Callable[[], TestClient], postgres_engine: Engine, admin_user_id: uuid.UUID
) -> None:
    login_name = f"auditchangepw-{uuid.uuid4().hex[:8]}"
    with client_factory() as client:
        target_user_id = _create_and_activate(
            client, postgres_engine, admin_user_id, login_name=login_name
        )
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
    row = _latest_audit_row(postgres_engine, command_name="local_auth.change_password")
    assert row is not None
    assert row["actor_user_id"] == target_user_id


def test_audit_rows_never_contain_password_or_token_fields(
    client_factory: Callable[[], TestClient], postgres_engine: Engine, admin_user_id: uuid.UUID
) -> None:
    """Bounded, non-secret content only — no audit row this workstream
    writes has a column shaped to carry a password, token, or session
    secret at all (`audit.change_log`'s schema, unchanged by this
    workstream, has no such column), and the one column that carries
    caller-influenced text (`changed_fields`) only ever receives a fixed,
    server-chosen key set — never body/token content."""
    login_name = f"auditnosecret-{uuid.uuid4().hex[:8]}"
    with client_factory() as client:
        _create_and_activate(client, postgres_engine, admin_user_id, login_name=login_name)
        client.post(
            "/auth/login",
            json={"login_name": login_name, "password": _VALID_PASSWORD},
            headers={"Origin": _DEV_ORIGIN},
        )
    row = _latest_audit_row(postgres_engine, command_name="local_auth.login_success")
    assert row is not None
    serialized = str(row)
    assert _VALID_PASSWORD not in serialized
