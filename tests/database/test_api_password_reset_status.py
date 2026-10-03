"""`POST /auth/password-reset-status`: the advisory, read-only, non-consuming
pre-check the portal runs before showing the new-passphrase form. The
authoritative decision stays in `POST /auth/password-reset`; these tests prove
the pre-check agrees with it, changes nothing, and never discloses *why* a
token is unusable."""

import logging
import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from dnd_ai.api.app import create_app
from dnd_ai.api.deps import get_engine
from dnd_ai.api.local_auth import (
    get_activation_status_rate_limiter,
    get_login_account_rate_limiter,
    get_login_ip_rate_limiter,
    get_password_reset_status_rate_limiter,
    get_token_consumption_rate_limiter,
)
from dnd_ai.commands.local_auth import (
    _create_local_account_impl,
    _disable_local_account_impl,
    _issue_password_reset_token_impl,
    activate_local_account,
    create_browser_session,
)
from dnd_ai.domain.rate_limit import RateLimiter
from tests.factories import make_platform_administrator

pytestmark = pytest.mark.database

_ORIGIN = "http://localhost:5173"
_PASSWORD = "a genuinely random passphrase 1"
_NEW_PASSWORD = "another genuinely random passphrase 2"
_STATUS = "/auth/password-reset-status"


def _generous() -> RateLimiter:
    return RateLimiter(max_attempts=10_000, window=timedelta(minutes=15))


def _app_client(postgres_engine: Engine, *, status_limiter: RateLimiter | None = None):
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: postgres_engine
    app.dependency_overrides[get_login_ip_rate_limiter] = _generous
    app.dependency_overrides[get_login_account_rate_limiter] = _generous
    app.dependency_overrides[get_token_consumption_rate_limiter] = _generous
    app.dependency_overrides[get_activation_status_rate_limiter] = _generous
    limiter = status_limiter or _generous()
    app.dependency_overrides[get_password_reset_status_rate_limiter] = lambda: limiter
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def client(postgres_engine: Engine):
    with _app_client(postgres_engine) as test_client:
        yield test_client


@pytest.fixture
def admin_user_id(postgres_engine: Engine) -> uuid.UUID:
    with postgres_engine.begin() as connection:
        return make_platform_administrator(connection)


def _activated_account(postgres_engine: Engine, admin_user_id: uuid.UUID) -> uuid.UUID:
    with postgres_engine.begin() as connection:
        created = _create_local_account_impl(
            connection,
            created_by_user_id=admin_user_id,
            login_name=f"reset-status-{uuid.uuid4().hex[:8]}",
            display_name="Reset Status Test",
        )
    activate_local_account(
        postgres_engine, raw_activation_token=created.raw_token, raw_password=_PASSWORD
    )
    return created.user_id


def _issue(postgres_engine: Engine, admin_user_id: uuid.UUID) -> tuple[str, uuid.UUID]:
    user_id = _activated_account(postgres_engine, admin_user_id)
    with postgres_engine.begin() as connection:
        issued = _issue_password_reset_token_impl(
            connection, requested_by_user_id=admin_user_id, target_user_id=user_id
        )
    return issued.raw_token, user_id


def _status(client: TestClient, token: object):
    return client.post(_STATUS, json={"token": token}, headers={"Origin": _ORIGIN})


def _reset(client: TestClient, token: str):
    return client.post(
        "/auth/password-reset",
        json={"token": token, "new_password": _NEW_PASSWORD},
        headers={"Origin": _ORIGIN},
    )


def _audit_and_idempotency_counts(postgres_engine: Engine) -> tuple[int, int]:
    with postgres_engine.begin() as connection:
        audit = connection.execute(text("SELECT count(*) FROM audit.change_log")).scalar()
        idem = connection.execute(
            text("SELECT count(*) FROM security.idempotent_requests")
        ).scalar()
    return int(audit or 0), int(idem or 0)


def _state(postgres_engine: Engine, user_id: uuid.UUID) -> tuple[object, ...]:
    """Every row a preflight must leave untouched: tokens, credential, sessions."""
    with postgres_engine.begin() as connection:
        tokens = connection.execute(
            text("""
                SELECT password_reset_token_id, token_hash, consumed_at, expires_at,
                       revoke_sessions
                FROM security.password_reset_tokens WHERE user_id = :u ORDER BY 1
            """),
            {"u": user_id},
        ).all()
        credential = connection.execute(
            text("""
                SELECT password_hash, password_updated_at, updated_at
                FROM security.local_credentials WHERE user_id = :u
            """),
            {"u": user_id},
        ).all()
        sessions = connection.execute(
            text("""
                SELECT browser_session_id, revoked_at, last_used_at, idle_expires_at
                FROM security.browser_sessions WHERE user_id = :u ORDER BY 1
            """),
            {"u": user_id},
        ).all()
    return (tuple(map(tuple, tokens)), tuple(map(tuple, credential)), tuple(map(tuple, sessions)))


def _expire(postgres_engine: Engine, user_id: uuid.UUID) -> None:
    with postgres_engine.begin() as connection:
        # The table forbids expires_at <= created_at; move created_at back too.
        connection.execute(
            text("""
                UPDATE security.password_reset_tokens
                SET created_at = now() - interval '2 hours',
                    expires_at = now() - interval '1 hour'
                WHERE user_id = :u
            """),
            {"u": user_id},
        )


def test_current_unused_token_is_valid(
    client: TestClient, postgres_engine: Engine, admin_user_id: uuid.UUID
) -> None:
    token, _ = _issue(postgres_engine, admin_user_id)
    response = _status(client, token)
    assert response.status_code == 200
    assert response.json() == {"valid": True}


def test_unknown_token_is_invalid(client: TestClient) -> None:
    response = _status(client, "never-issued")
    assert response.status_code == 200
    assert response.json() == {"valid": False}


@pytest.mark.parametrize("token", ["", "%%%\u0000weird", "x" * 5000])
def test_malformed_token_is_invalid(client: TestClient, token: str) -> None:
    response = _status(client, token)
    assert response.status_code == 200
    assert response.json() == {"valid": False}


def test_expired_token_is_invalid(
    client: TestClient, postgres_engine: Engine, admin_user_id: uuid.UUID
) -> None:
    token, user_id = _issue(postgres_engine, admin_user_id)
    _expire(postgres_engine, user_id)
    assert _status(client, token).json() == {"valid": False}


def test_consumed_token_is_invalid_and_body_matches_unknown(
    client: TestClient, postgres_engine: Engine, admin_user_id: uuid.UUID
) -> None:
    token, _ = _issue(postgres_engine, admin_user_id)
    assert _reset(client, token).status_code == 200
    consumed = _status(client, token)
    unknown = _status(client, "never-issued")
    assert consumed.status_code == unknown.status_code == 200
    assert consumed.content == unknown.content == b'{"valid":false}'


def test_token_for_disabled_account_is_invalid(
    client: TestClient, postgres_engine: Engine, admin_user_id: uuid.UUID
) -> None:
    token, user_id = _issue(postgres_engine, admin_user_id)
    with postgres_engine.begin() as connection:
        _disable_local_account_impl(connection, admin_user_id=admin_user_id, target_user_id=user_id)
    disabled = _status(client, token)
    assert disabled.content == _status(client, "never-issued").content == b'{"valid":false}'
    assert _reset(client, token).status_code == 404


def test_token_for_account_without_credential_is_invalid(
    client: TestClient, postgres_engine: Engine, admin_user_id: uuid.UUID
) -> None:
    # Created but never activated: nothing to reset, so the final command would
    # have consumed the token and changed no password.
    with postgres_engine.begin() as connection:
        created = _create_local_account_impl(
            connection,
            created_by_user_id=admin_user_id,
            login_name=f"no-credential-{uuid.uuid4().hex[:8]}",
            display_name="No Credential",
        )
        issued = _issue_password_reset_token_impl(
            connection, requested_by_user_id=admin_user_id, target_user_id=created.user_id
        )
    assert _status(client, issued.raw_token).json() == {"valid": False}
    assert _reset(client, issued.raw_token).status_code == 404
    assert _state(postgres_engine, created.user_id)[0][0][2] is None  # still unconsumed


def test_status_check_changes_nothing(
    client: TestClient, postgres_engine: Engine, admin_user_id: uuid.UUID
) -> None:
    token, user_id = _issue(postgres_engine, admin_user_id)
    with postgres_engine.begin() as connection:
        create_browser_session(connection, user_id=user_id)
    state_before = _state(postgres_engine, user_id)
    counts_before = _audit_and_idempotency_counts(postgres_engine)

    for _ in range(3):
        assert _status(client, token).json() == {"valid": True}
    _status(client, "never-issued")

    assert _state(postgres_engine, user_id) == state_before
    assert _audit_and_idempotency_counts(postgres_engine) == counts_before
    assert state_before[0][0][2] is None  # token still unconsumed
    assert state_before[2][0][1] is None  # session still unrevoked


def test_same_token_resets_after_valid_check(
    client: TestClient, postgres_engine: Engine, admin_user_id: uuid.UUID
) -> None:
    token, user_id = _issue(postgres_engine, admin_user_id)
    assert _status(client, token).json() == {"valid": True}
    response = _reset(client, token)
    assert response.status_code == 200
    assert response.json()["user_id"] == str(user_id)
    assert _status(client, token).json() == {"valid": False}


def test_token_consumed_after_valid_check_is_rejected_by_final_reset(
    client: TestClient, postgres_engine: Engine, admin_user_id: uuid.UUID
) -> None:
    token, _ = _issue(postgres_engine, admin_user_id)
    assert _status(client, token).json() == {"valid": True}
    assert _reset(client, token).status_code == 200  # consumed "elsewhere"
    assert _reset(client, token).status_code == 404


def test_token_expired_after_valid_check_is_rejected_by_final_reset(
    client: TestClient, postgres_engine: Engine, admin_user_id: uuid.UUID
) -> None:
    token, user_id = _issue(postgres_engine, admin_user_id)
    assert _status(client, token).json() == {"valid": True}
    _expire(postgres_engine, user_id)
    state_before = _state(postgres_engine, user_id)

    response = _reset(client, token)

    assert response.status_code == 404
    assert _state(postgres_engine, user_id) == state_before  # nothing consumed or changed
    assert state_before[0][0][2] is None


def test_account_disabled_after_valid_check_is_rejected_by_final_reset(
    client: TestClient, postgres_engine: Engine, admin_user_id: uuid.UUID
) -> None:
    token, user_id = _issue(postgres_engine, admin_user_id)
    assert _status(client, token).json() == {"valid": True}
    with postgres_engine.begin() as connection:
        _disable_local_account_impl(connection, admin_user_id=admin_user_id, target_user_id=user_id)
    state_before = _state(postgres_engine, user_id)

    response = _reset(client, token)

    unknown = _reset(client, "never-issued")
    assert response.status_code == unknown.status_code == 404
    assert response.json()["error"]["code"] == unknown.json()["error"]["code"]
    assert response.json()["error"]["message"] == unknown.json()["error"]["message"]
    assert _state(postgres_engine, user_id) == state_before


def test_response_discloses_nothing_but_valid(
    client: TestClient, postgres_engine: Engine, admin_user_id: uuid.UUID
) -> None:
    token, user_id = _issue(postgres_engine, admin_user_id)
    body = _status(client, token).text
    assert body == '{"valid":true}'
    assert str(user_id) not in body


def test_status_check_is_rate_limited(postgres_engine: Engine) -> None:
    limiter = RateLimiter(max_attempts=2, window=timedelta(minutes=15))
    with _app_client(postgres_engine, status_limiter=limiter) as client:
        assert _status(client, "a").status_code == 200
        assert _status(client, "b").status_code == 200
        assert _status(client, "c").status_code == 429


def test_status_check_does_not_consume_reset_rate_budget(postgres_engine: Engine) -> None:
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: postgres_engine
    reset_limiter = RateLimiter(max_attempts=1, window=timedelta(minutes=15))
    status_limiter = _generous()
    app.dependency_overrides[get_token_consumption_rate_limiter] = lambda: reset_limiter
    app.dependency_overrides[get_password_reset_status_rate_limiter] = lambda: status_limiter
    with TestClient(app, raise_server_exceptions=False) as client:
        for _ in range(5):
            assert _status(client, "x").status_code == 200
        assert _reset(client, "x").status_code == 404  # budget still intact


@pytest.mark.parametrize("headers", [{}, {"Origin": "http://evil.example"}])
def test_status_check_requires_allowed_origin(
    client: TestClient, postgres_engine: Engine, admin_user_id: uuid.UUID, headers: dict[str, str]
) -> None:
    token, _ = _issue(postgres_engine, admin_user_id)
    response = client.post(_STATUS, json={"token": token}, headers=headers)
    assert response.status_code == 403


def test_status_check_is_post_only(client: TestClient) -> None:
    assert client.get(_STATUS).status_code == 405
    assert client.get(_STATUS, params={"token": "abc"}).status_code == 405


def test_token_and_hash_absent_from_logs_audit_and_error_bodies(
    client: TestClient,
    postgres_engine: Engine,
    admin_user_id: uuid.UUID,
    caplog: pytest.LogCaptureFixture,
) -> None:
    token, user_id = _issue(postgres_engine, admin_user_id)
    with postgres_engine.begin() as connection:
        token_hash = connection.execute(
            text("SELECT token_hash FROM security.password_reset_tokens WHERE user_id = :u"),
            {"u": user_id},
        ).scalar_one()
    with caplog.at_level(logging.DEBUG):
        responses = [
            _status(client, token),
            _status(client, token + "-tampered"),
            client.post(_STATUS, json={"token": 123}, headers={"Origin": _ORIGIN}),  # 422 body
        ]
    for needle in (token, str(token_hash)):
        assert needle not in caplog.text
        assert all(needle not in response.text for response in responses)
        with postgres_engine.begin() as connection:
            audit = connection.execute(
                text("SELECT row_to_json(cl)::text FROM audit.change_log cl")
            )
            assert not any(needle in (row[0] or "") for row in audit)
