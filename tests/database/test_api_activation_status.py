"""`POST /auth/activation-status`: the advisory, read-only, non-consuming
pre-check the portal runs before showing the Set passphrase form. The
authoritative decision stays in `POST /auth/activate`; these tests prove the
pre-check agrees with it, changes nothing, and never discloses *why* a token
is unusable."""

import logging
import threading
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
    get_token_consumption_rate_limiter,
)
from dnd_ai.commands.local_auth import (
    ActivationNotAcceptableError,
    _activate_local_account_impl,
    _create_local_account_impl,
    _disable_local_account_impl,
    _reactivate_local_account_impl,
    activate_local_account,
)
from dnd_ai.domain.rate_limit import RateLimiter
from tests.factories import make_platform_administrator

pytestmark = pytest.mark.database

_ORIGIN = "http://localhost:5173"
_PASSWORD = "a genuinely random passphrase 1"
_STATUS = "/auth/activation-status"


def _generous() -> RateLimiter:
    return RateLimiter(max_attempts=10_000, window=timedelta(minutes=15))


def _app_client(postgres_engine: Engine, *, status_limiter: RateLimiter | None = None):
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: postgres_engine
    app.dependency_overrides[get_login_ip_rate_limiter] = _generous
    app.dependency_overrides[get_login_account_rate_limiter] = _generous
    app.dependency_overrides[get_token_consumption_rate_limiter] = _generous
    limiter = status_limiter or _generous()
    app.dependency_overrides[get_activation_status_rate_limiter] = lambda: limiter
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def client(postgres_engine: Engine):
    with _app_client(postgres_engine) as test_client:
        yield test_client


@pytest.fixture
def admin_user_id(postgres_engine: Engine) -> uuid.UUID:
    with postgres_engine.begin() as connection:
        return make_platform_administrator(connection)


def _issue(postgres_engine: Engine, admin_user_id: uuid.UUID) -> tuple[str, uuid.UUID, str]:
    login_name = f"status-{uuid.uuid4().hex[:8]}"
    with postgres_engine.begin() as connection:
        result = _create_local_account_impl(
            connection,
            created_by_user_id=admin_user_id,
            login_name=login_name,
            display_name="Status Test",
        )
    return result.raw_token, result.user_id, login_name


def _status(client: TestClient, token: object) -> object:
    return client.post(_STATUS, json={"token": token}, headers={"Origin": _ORIGIN})


def _activate(client: TestClient, token: str):
    return client.post(
        "/auth/activate",
        json={"token": token, "password": _PASSWORD},
        headers={"Origin": _ORIGIN},
    )


def _audit_and_idempotency_counts(postgres_engine: Engine) -> tuple[int, int]:
    with postgres_engine.begin() as connection:
        audit = connection.execute(text("SELECT count(*) FROM audit.change_log")).scalar()
        idem = connection.execute(
            text("SELECT count(*) FROM security.idempotent_requests")
        ).scalar()
    return int(audit or 0), int(idem or 0)


def _token_state(postgres_engine: Engine, user_id: uuid.UUID) -> tuple[object, ...]:
    with postgres_engine.begin() as connection:
        row = connection.execute(
            text("""
                SELECT uat.consumed_at, uat.expires_at, u.lifecycle_status_id,
                       (SELECT count(*) FROM security.local_credentials lc
                         WHERE lc.user_id = uat.user_id),
                       (SELECT count(*) FROM security.external_identities ei
                         WHERE ei.user_id = uat.user_id)
                FROM security.user_activation_tokens uat
                JOIN security.users u ON u.user_id = uat.user_id
                WHERE uat.user_id = :user_id
            """),
            {"user_id": user_id},
        ).one()
    return tuple(row)


def _expire(postgres_engine: Engine, user_id: uuid.UUID) -> None:
    with postgres_engine.begin() as connection:
        # The table forbids expires_at <= created_at; move created_at back too.
        connection.execute(
            text("""
                UPDATE security.user_activation_tokens
                SET created_at = now() - interval '2 hours',
                    expires_at = now() - interval '1 hour'
                WHERE user_id = :user_id
            """),
            {"user_id": user_id},
        )


def test_valid_token_is_valid(
    client: TestClient, postgres_engine: Engine, admin_user_id: uuid.UUID
) -> None:
    token, _, _ = _issue(postgres_engine, admin_user_id)
    response = _status(client, token)
    assert response.status_code == 200
    assert response.json() == {"valid": True}


@pytest.mark.parametrize("token", ["", "not-a-real-token", "%%%\u0000weird", "x" * 5000])
def test_unknown_or_malformed_token_is_generically_invalid(client: TestClient, token: str) -> None:
    response = _status(client, token)
    assert response.status_code == 200
    assert response.json() == {"valid": False}


def test_expired_token_is_invalid(
    client: TestClient, postgres_engine: Engine, admin_user_id: uuid.UUID
) -> None:
    token, user_id, _ = _issue(postgres_engine, admin_user_id)
    _expire(postgres_engine, user_id)
    assert _status(client, token).json() == {"valid": False}


def test_consumed_token_is_invalid_and_body_matches_unknown(
    client: TestClient, postgres_engine: Engine, admin_user_id: uuid.UUID
) -> None:
    token, _, _ = _issue(postgres_engine, admin_user_id)
    assert _activate(client, token).status_code == 200
    consumed = _status(client, token)
    unknown = _status(client, "never-issued")
    assert consumed.status_code == unknown.status_code == 200
    assert consumed.content == unknown.content == b'{"valid":false}'


def test_login_name_claimed_by_another_account_is_invalid(
    client: TestClient, postgres_engine: Engine, admin_user_id: uuid.UUID
) -> None:
    # Same prerequisite final activation enforces (LoginNameAlreadyTakenError).
    token_a, user_a, login_name = _issue(postgres_engine, admin_user_id)
    with postgres_engine.begin() as connection:
        issued_b = _create_local_account_impl(
            connection,
            created_by_user_id=admin_user_id,
            login_name=f"{login_name}-b",
            display_name="Other",
        )
        connection.execute(
            text("UPDATE security.user_activation_tokens SET login_name = :n WHERE user_id = :u"),
            {"n": login_name, "u": issued_b.user_id},
        )
    token_b = issued_b.raw_token
    assert _activate(client, token_a).status_code == 200
    assert _status(client, token_b).json() == {"valid": False}
    assert _activate(client, token_b).status_code == 409


def test_status_check_changes_nothing(
    client: TestClient, postgres_engine: Engine, admin_user_id: uuid.UUID
) -> None:
    token, user_id, _ = _issue(postgres_engine, admin_user_id)
    state_before = _token_state(postgres_engine, user_id)
    counts_before = _audit_and_idempotency_counts(postgres_engine)

    for _ in range(3):
        assert _status(client, token).json() == {"valid": True}

    assert _token_state(postgres_engine, user_id) == state_before
    assert _audit_and_idempotency_counts(postgres_engine) == counts_before
    assert state_before[0] is None  # still unconsumed


def test_same_token_activates_after_valid_check(
    client: TestClient, postgres_engine: Engine, admin_user_id: uuid.UUID
) -> None:
    token, _, login_name = _issue(postgres_engine, admin_user_id)
    assert _status(client, token).json() == {"valid": True}
    response = _activate(client, token)
    assert response.status_code == 200
    assert response.json()["login_name"] == login_name


def test_token_consumed_after_valid_check_is_rejected_by_final_activation(
    client: TestClient, postgres_engine: Engine, admin_user_id: uuid.UUID
) -> None:
    token, user_id, _ = _issue(postgres_engine, admin_user_id)
    assert _status(client, token).json() == {"valid": True}
    assert _activate(client, token).status_code == 200  # consumed "elsewhere"
    second = _activate(client, token)
    assert second.status_code == 404
    assert _status(client, token).json() == {"valid": False}
    assert _token_state(postgres_engine, user_id)[3] == 1  # one credential, not two


def test_token_expired_after_valid_check_is_rejected_by_final_activation(
    client: TestClient, postgres_engine: Engine, admin_user_id: uuid.UUID
) -> None:
    token, user_id, _ = _issue(postgres_engine, admin_user_id)
    assert _status(client, token).json() == {"valid": True}
    _expire(postgres_engine, user_id)
    response = _activate(client, token)
    assert response.status_code == 404
    state = _token_state(postgres_engine, user_id)
    assert state[0] is None  # not consumed
    assert state[3] == 0 and state[4] == 0  # no credential, no identity


def test_response_discloses_nothing_but_valid(
    client: TestClient, postgres_engine: Engine, admin_user_id: uuid.UUID
) -> None:
    token, user_id, login_name = _issue(postgres_engine, admin_user_id)
    body = _status(client, token).text
    assert body == '{"valid":true}'
    assert login_name not in body and str(user_id) not in body


def test_status_check_is_rate_limited(postgres_engine: Engine) -> None:
    limiter = RateLimiter(max_attempts=2, window=timedelta(minutes=15))
    with _app_client(postgres_engine, status_limiter=limiter) as client:
        assert _status(client, "a").status_code == 200
        assert _status(client, "b").status_code == 200
        assert _status(client, "c").status_code == 429


def test_status_check_does_not_consume_activation_rate_budget(postgres_engine: Engine) -> None:
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: postgres_engine
    activation_limiter = RateLimiter(max_attempts=1, window=timedelta(minutes=15))
    status_limiter = _generous()
    app.dependency_overrides[get_token_consumption_rate_limiter] = lambda: activation_limiter
    app.dependency_overrides[get_activation_status_rate_limiter] = lambda: status_limiter
    with TestClient(app, raise_server_exceptions=False) as client:
        for _ in range(5):
            assert _status(client, "x").status_code == 200
        assert _activate(client, "x").status_code == 404  # budget still intact


@pytest.mark.parametrize("headers", [{}, {"Origin": "http://evil.example"}])
def test_status_check_requires_allowed_origin(
    client: TestClient, postgres_engine: Engine, admin_user_id: uuid.UUID, headers: dict[str, str]
) -> None:
    token, _, _ = _issue(postgres_engine, admin_user_id)
    response = client.post(_STATUS, json={"token": token}, headers=headers)
    assert response.status_code == 403


def test_status_check_is_post_only(client: TestClient) -> None:
    assert client.get(_STATUS).status_code == 405
    assert client.get(_STATUS, params={"token": "abc"}).status_code == 405


def test_machine_credentials_neither_authenticate_nor_bypass_origin(
    client: TestClient, postgres_engine: Engine, admin_user_id: uuid.UUID
) -> None:
    token, _, _ = _issue(postgres_engine, admin_user_id)
    foundry_headers = {"Authorization": "Bearer foundry-looking-credential"}
    # A machine credential does not stand in for the browser Origin check...
    assert client.post(_STATUS, json={"token": token}, headers=foundry_headers).status_code == 403
    # ...and is ignored (never authenticated) when Origin is present.
    response = client.post(
        _STATUS, json={"token": token}, headers={**foundry_headers, "Origin": _ORIGIN}
    )
    assert response.status_code == 200
    assert response.json() == {"valid": True}


def test_token_absent_from_logs_and_audit(
    client: TestClient,
    postgres_engine: Engine,
    admin_user_id: uuid.UUID,
    caplog: pytest.LogCaptureFixture,
) -> None:
    token, _, _ = _issue(postgres_engine, admin_user_id)
    with caplog.at_level(logging.DEBUG):
        _status(client, token)
        _status(client, token + "-tampered")
    assert token not in caplog.text
    with postgres_engine.begin() as connection:
        audit = connection.execute(text("SELECT row_to_json(cl)::text FROM audit.change_log cl"))
        assert not any(token in (row[0] or "") for row in audit)


# ---------------------------------------------------------------------------
# Account lifecycle eligibility: a token is usable only while its account is
# `active`, in both the advisory check and (authoritatively) final activation.
# ---------------------------------------------------------------------------


def _disable(postgres_engine: Engine, admin_user_id: uuid.UUID, user_id: uuid.UUID) -> None:
    with postgres_engine.begin() as connection:
        _disable_local_account_impl(connection, admin_user_id=admin_user_id, target_user_id=user_id)


def test_token_for_account_disabled_before_check_is_invalid(
    client: TestClient, postgres_engine: Engine, admin_user_id: uuid.UUID
) -> None:
    token, user_id, _ = _issue(postgres_engine, admin_user_id)
    _disable(postgres_engine, admin_user_id, user_id)
    disabled = _status(client, token)
    assert disabled.content == _status(client, "never-issued").content == b'{"valid":false}'
    assert _activate(client, token).status_code == 404


def test_account_disabled_after_valid_check_is_rejected_without_mutation(
    client: TestClient, postgres_engine: Engine, admin_user_id: uuid.UUID
) -> None:
    token, user_id, _ = _issue(postgres_engine, admin_user_id)
    assert _status(client, token).json() == {"valid": True}
    _disable(postgres_engine, admin_user_id, user_id)
    state_before = _token_state(postgres_engine, user_id)
    counts_before = _audit_and_idempotency_counts(postgres_engine)

    response = _activate(client, token)

    assert response.status_code == 404
    unknown = _activate(client, "never-issued")
    assert response.json()["error"]["code"] == unknown.json()["error"]["code"]
    assert response.json()["error"]["message"] == unknown.json()["error"]["message"]
    assert _token_state(postgres_engine, user_id) == state_before
    assert state_before[0] is None and state_before[3] == 0 and state_before[4] == 0
    assert _audit_and_idempotency_counts(postgres_engine) == counts_before


def test_reactivated_account_token_is_usable_again(
    client: TestClient, postgres_engine: Engine, admin_user_id: uuid.UUID
) -> None:
    token, user_id, _ = _issue(postgres_engine, admin_user_id)
    _disable(postgres_engine, admin_user_id, user_id)
    with postgres_engine.begin() as connection:
        _reactivate_local_account_impl(
            connection, admin_user_id=admin_user_id, target_user_id=user_id
        )
    assert _status(client, token).json() == {"valid": True}
    assert _activate(client, token).status_code == 200


def test_activation_racing_account_disable_waits_then_rejects(
    postgres_engine: Engine, admin_user_id: uuid.UUID
) -> None:
    token, user_id, _ = _issue(postgres_engine, admin_user_id)
    outcome: list[object] = []

    def _activate_in_thread() -> None:
        try:
            outcome.append(
                activate_local_account(
                    postgres_engine, raw_activation_token=token, raw_password=_PASSWORD
                )
            )
        except Exception as error:  # noqa: BLE001 - recorded for assertion
            outcome.append(error)

    with postgres_engine.connect() as admin_connection, admin_connection.begin():
        _disable_local_account_impl(
            admin_connection, admin_user_id=admin_user_id, target_user_id=user_id
        )  # uncommitted: holds FOR UPDATE on the users row
        worker = threading.Thread(target=_activate_in_thread)
        worker.start()
        worker.join(timeout=1.0)
        assert worker.is_alive(), "activation must wait for the in-flight disable"
    worker.join(timeout=10.0)  # disable committed; activation re-checks and rejects

    assert not worker.is_alive()
    assert len(outcome) == 1 and isinstance(outcome[0], ActivationNotAcceptableError)
    state = _token_state(postgres_engine, user_id)
    assert state[0] is None and state[3] == 0 and state[4] == 0


def test_disable_racing_in_flight_activation_does_not_deadlock(
    postgres_engine: Engine, admin_user_id: uuid.UUID
) -> None:
    token, user_id, _ = _issue(postgres_engine, admin_user_id)
    with postgres_engine.connect() as activation_connection, activation_connection.begin():
        _activate_local_account_impl(
            activation_connection, raw_activation_token=token, raw_password=_PASSWORD
        )  # uncommitted: holds token FOR UPDATE and users FOR SHARE
        worker = threading.Thread(target=_disable, args=(postgres_engine, admin_user_id, user_id))
        worker.start()
        worker.join(timeout=1.0)
        assert worker.is_alive(), "disable must wait for the in-flight activation"
    worker.join(timeout=10.0)
    assert not worker.is_alive()
    state = _token_state(postgres_engine, user_id)
    assert state[0] is not None and state[3] == 1  # activation committed first, then disabled
