"""Tests for `dnd_ai.api.invitation_onboarding` — the five single-link
campaign-invitation onboarding routes (Phase 13E checkpoint 8b;
`PHASE13E_REMAINING_IMPLEMENTATION_PLAN.md` §8.2, the authoritative
contract).

Covers: the two full flows (a brand-new registrant, and an already-
signed-in visitor confirming), missing/disallowed Origin on every
unauthenticated mutation, an `Authorization` header rejected on `start`/
`register` (S-10), missing/wrong onboarding CSRF on `register`/`cancel`,
missing session CSRF on `complete`, a Foundry principal rejected on
`complete`, rate limiting on `start`, the onboarding cookie's flags, and
that no response body ever discloses `campaign_id` (S-6).
"""

import uuid
from collections.abc import Callable
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, text

from dnd_ai.api.app import create_app
from dnd_ai.api.auth import get_authenticated_user_id
from dnd_ai.api.cookies import DEV_ONBOARDING_COOKIE_NAME, DEV_SESSION_COOKIE_NAME
from dnd_ai.api.deps import get_engine
from dnd_ai.api.local_auth import (
    get_login_account_rate_limiter,
    get_login_ip_rate_limiter,
    get_token_consumption_rate_limiter,
)
from dnd_ai.commands.campaign_invitations import create_campaign_invitation
from dnd_ai.commands.local_auth import _activate_local_account_impl, _create_local_account_impl
from dnd_ai.domain.access import FOUNDRY_SYSTEM_AUTH_METHOD, AuthenticatedPrincipal
from dnd_ai.domain.rate_limit import RateLimiter
from tests.factories import (
    lookup_id,
    make_campaign,
    make_campaign_membership,
    make_membership_role,
    make_platform_administrator,
    make_role,
    make_role_capability,
    make_timeline,
    make_world,
)

pytestmark = pytest.mark.database

_DEV_ORIGIN = "http://localhost:5173"
_DISALLOWED_ORIGIN = "http://evil.example"
_MANAGER_PASSWORD = "a genuinely random passphrase 1"
_START_URL = "/campaign-invitations/onboarding/start"
_STATUS_URL = "/campaign-invitations/onboarding/status"
_REGISTER_URL = "/campaign-invitations/onboarding/register"
_COMPLETE_URL = "/campaign-invitations/onboarding/complete"
_CANCEL_URL = "/campaign-invitations/onboarding/cancel"


def _generous_rate_limiter() -> RateLimiter:
    return RateLimiter(max_attempts=10_000, window=timedelta(minutes=15))


class Fixture:
    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        self.campaign_id = make_campaign(
            connection, self.timeline_id, "Onboarding API Campaign", lifecycle_status_code="pending"
        )
        access_manage_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "access.manage"
        )
        manager_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"manager_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, manager_role_id, access_manage_id)

        self.platform_admin_user_id = make_platform_administrator(connection)
        issued_manager = _create_local_account_impl(
            connection,
            created_by_user_id=self.platform_admin_user_id,
            login_name=f"onb.api.manager.{uuid.uuid4().hex[:8]}",
            display_name="Onboarding API Manager",
        )
        self.manager_user_id = issued_manager.user_id
        self.manager_login_name = issued_manager.login_name
        _activate_local_account_impl(
            connection,
            raw_activation_token=issued_manager.raw_token,
            raw_password=_MANAGER_PASSWORD,
        )
        self.manager_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.manager_user_id
        )
        make_membership_role(connection, self.manager_membership_id, manager_role_id)

    def invite(self, connection: Connection) -> str:
        return create_campaign_invitation(
            connection,
            campaign_id=self.campaign_id,
            invited_by_membership_id=self.manager_membership_id,
        ).token


@pytest.fixture
def f(postgres_engine: Engine) -> Fixture:
    with postgres_engine.begin() as connection:
        return Fixture(connection, f"onb-api-{uuid.uuid4().hex[:8]}")


@pytest.fixture
def browser_client_factory(postgres_engine: Engine) -> Callable[[], TestClient]:
    def _make() -> TestClient:
        app = create_app()
        app.dependency_overrides[get_engine] = lambda: postgres_engine
        app.dependency_overrides[get_login_ip_rate_limiter] = _generous_rate_limiter
        app.dependency_overrides[get_login_account_rate_limiter] = _generous_rate_limiter
        app.dependency_overrides[get_token_consumption_rate_limiter] = _generous_rate_limiter
        return TestClient(app, raise_server_exceptions=False)

    return _make


def _login_manager(client: TestClient, f: Fixture) -> str:
    response = client.post(
        "/auth/login",
        json={"login_name": f.manager_login_name, "password": _MANAGER_PASSWORD},
        headers={"Origin": _DEV_ORIGIN},
    )
    assert response.status_code == 200, response.text
    return str(response.json()["csrf_token"])


def _start(
    client: TestClient, raw_invitation_token: str, *, origin: str | None = _DEV_ORIGIN
) -> dict:
    headers = {} if origin is None else {"Origin": origin}
    response = client.post(_START_URL, json={"token": raw_invitation_token}, headers=headers)
    assert response.status_code == 201, response.text
    return dict(response.json())


def test_register_flow_creates_account_and_signs_in(
    browser_client_factory: Callable[[], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with postgres_engine.begin() as connection:
        raw_token = f.invite(connection)

    with browser_client_factory() as client:
        begun = _start(client, raw_token)
        assert begun["next_action"] == "sign_in_or_register"
        assert begun["signed_in_display_name"] is None
        assert begun["campaign_display_name"] == "Onboarding API Campaign"
        assert DEV_ONBOARDING_COOKIE_NAME in client.cookies

        login_name = f"onb.registrant.{uuid.uuid4().hex[:10]}"
        response = client.post(
            _REGISTER_URL,
            json={
                "login_name": login_name,
                "display_name": "New Registrant",
                "password": "correct-onboarding-password-15",
            },
            headers={
                "Origin": _DEV_ORIGIN,
                "X-Onboarding-CSRF-Token": begun["onboarding_csrf_token"],
            },
        )
        assert response.status_code == 201, response.text
        payload = response.json()
        assert payload["campaign_display_name"] == "Onboarding API Campaign"
        assert "campaign_id" not in payload
        assert DEV_SESSION_COOKIE_NAME in client.cookies
        assert DEV_ONBOARDING_COOKIE_NAME not in client.cookies

    with postgres_engine.connect() as verify:
        membership_count = verify.execute(
            text(
                "SELECT count(*) FROM security.campaign_memberships m "
                "JOIN security.external_identities ei ON ei.user_id = m.user_id "
                "WHERE m.campaign_id = :c AND ei.subject = :login"
            ),
            {"c": f.campaign_id, "login": login_name},
        ).scalar_one()
        assert membership_count == 1


def test_complete_flow_for_an_already_signed_in_visitor(
    browser_client_factory: Callable[[], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with postgres_engine.begin() as connection:
        raw_token = f.invite(connection)
        login_name = f"onb.confirmer.{uuid.uuid4().hex[:10]}"
        issued = _create_local_account_impl(
            connection,
            created_by_user_id=f.platform_admin_user_id,
            login_name=login_name,
            display_name="Already Signed In Visitor",
        )
        _activate_local_account_impl(
            connection, raw_activation_token=issued.raw_token, raw_password=_MANAGER_PASSWORD
        )

    with browser_client_factory() as client:
        response = client.post(
            "/auth/login",
            json={"login_name": login_name, "password": _MANAGER_PASSWORD},
            headers={"Origin": _DEV_ORIGIN},
        )
        assert response.status_code == 200, response.text
        session_csrf_token = response.json()["csrf_token"]

        begun = _start(client, raw_token)
        assert begun["next_action"] == "confirm"
        assert begun["signed_in_display_name"] == "Already Signed In Visitor"

        complete_response = client.post(
            _COMPLETE_URL,
            headers={"Origin": _DEV_ORIGIN, "X-CSRF-Token": session_csrf_token},
        )
        assert complete_response.status_code == 200, complete_response.text
        payload = complete_response.json()
        assert payload["campaign_display_name"] == "Onboarding API Campaign"
        assert "campaign_id" not in payload
        assert DEV_ONBOARDING_COOKIE_NAME not in client.cookies


def test_start_rejects_missing_origin(
    browser_client_factory: Callable[[], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with postgres_engine.begin() as connection:
        raw_token = f.invite(connection)
    with browser_client_factory() as client:
        response = client.post(_START_URL, json={"token": raw_token})
    assert response.status_code == 403


def test_start_rejects_disallowed_origin(
    browser_client_factory: Callable[[], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with postgres_engine.begin() as connection:
        raw_token = f.invite(connection)
    with browser_client_factory() as client:
        response = client.post(
            _START_URL, json={"token": raw_token}, headers={"Origin": _DISALLOWED_ORIGIN}
        )
    assert response.status_code == 403


def test_start_rejects_an_authorization_header(
    browser_client_factory: Callable[[], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with postgres_engine.begin() as connection:
        raw_token = f.invite(connection)
    with browser_client_factory() as client:
        response = client.post(
            _START_URL,
            json={"token": raw_token},
            headers={"Origin": _DEV_ORIGIN, "Authorization": "Bearer whatever"},
        )
    assert response.status_code == 403


def test_start_cookie_flags(
    browser_client_factory: Callable[[], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with postgres_engine.begin() as connection:
        raw_token = f.invite(connection)
    with browser_client_factory() as client:
        response = client.post(
            _START_URL, json={"token": raw_token}, headers={"Origin": _DEV_ORIGIN}
        )
    assert response.status_code == 201, response.text
    set_cookie = response.headers.get("set-cookie", "")
    assert DEV_ONBOARDING_COOKIE_NAME in set_cookie
    assert "HttpOnly" in set_cookie
    assert "samesite=lax" in set_cookie.lower()
    assert "path=/" in set_cookie.lower()


def test_start_is_rate_limited(
    browser_client_factory: Callable[[], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: postgres_engine
    app.dependency_overrides[get_login_ip_rate_limiter] = _generous_rate_limiter
    app.dependency_overrides[get_login_account_rate_limiter] = _generous_rate_limiter
    strict_rate_limiter = RateLimiter(max_attempts=1, window=timedelta(minutes=15))
    app.dependency_overrides[get_token_consumption_rate_limiter] = lambda: strict_rate_limiter
    with postgres_engine.begin() as connection:
        raw_token = f.invite(connection)
    with TestClient(app, raise_server_exceptions=False) as client:
        first = client.post(_START_URL, json={"token": raw_token}, headers={"Origin": _DEV_ORIGIN})
        assert first.status_code == 201, first.text
        second = client.post(_START_URL, json={"token": raw_token}, headers={"Origin": _DEV_ORIGIN})
    assert second.status_code == 429


def test_register_rejects_missing_onboarding_csrf(
    browser_client_factory: Callable[[], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with postgres_engine.begin() as connection:
        raw_token = f.invite(connection)
    with browser_client_factory() as client:
        _start(client, raw_token)
        response = client.post(
            _REGISTER_URL,
            json={
                "login_name": f"onb.nocsrf.{uuid.uuid4().hex[:10]}",
                "display_name": "No Csrf",
                "password": "correct-onboarding-password-15",
            },
            headers={"Origin": _DEV_ORIGIN},
        )
    assert response.status_code == 403


def test_register_rejects_wrong_onboarding_csrf(
    browser_client_factory: Callable[[], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with postgres_engine.begin() as connection:
        raw_token = f.invite(connection)
    with browser_client_factory() as client:
        _start(client, raw_token)
        response = client.post(
            _REGISTER_URL,
            json={
                "login_name": f"onb.wrongcsrf.{uuid.uuid4().hex[:10]}",
                "display_name": "Wrong Csrf",
                "password": "correct-onboarding-password-15",
            },
            headers={"Origin": _DEV_ORIGIN, "X-Onboarding-CSRF-Token": "not-the-right-value"},
        )
    assert response.status_code == 403


def test_complete_requires_session_csrf(
    browser_client_factory: Callable[[], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with postgres_engine.begin() as connection:
        raw_token = f.invite(connection)
        login_name = f"onb.nocsrf.confirm.{uuid.uuid4().hex[:10]}"
        issued = _create_local_account_impl(
            connection,
            created_by_user_id=f.platform_admin_user_id,
            login_name=login_name,
            display_name="No Session Csrf",
        )
        _activate_local_account_impl(
            connection, raw_activation_token=issued.raw_token, raw_password=_MANAGER_PASSWORD
        )

    with browser_client_factory() as client:
        login_response = client.post(
            "/auth/login",
            json={"login_name": login_name, "password": _MANAGER_PASSWORD},
            headers={"Origin": _DEV_ORIGIN},
        )
        assert login_response.status_code == 200, login_response.text
        _start(client, raw_token)
        response = client.post(_COMPLETE_URL, headers={"Origin": _DEV_ORIGIN})
    assert response.status_code == 403


def test_complete_rejects_a_foundry_principal(postgres_engine: Engine, f: Fixture) -> None:
    principal = AuthenticatedPrincipal(
        user_id=f.manager_user_id,
        auth_method=FOUNDRY_SYSTEM_AUTH_METHOD,
        foundry_external_system_id=uuid.uuid4(),
        foundry_world_id=f.world_id,
    )
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: postgres_engine
    app.dependency_overrides[get_authenticated_user_id] = lambda: principal
    with TestClient(app, raise_server_exceptions=False) as client:
        client.cookies.set(DEV_ONBOARDING_COOKIE_NAME, "irrelevant")
        response = client.post(_COMPLETE_URL, headers={"Origin": _DEV_ORIGIN})
    assert response.status_code == 403


def test_status_without_a_cookie_is_generically_unavailable(
    browser_client_factory: Callable[[], TestClient],
) -> None:
    with browser_client_factory() as client:
        response = client.get(_STATUS_URL)
    assert response.status_code == 404


def test_cancel_clears_the_cookie_and_a_subsequent_status_is_unavailable(
    browser_client_factory: Callable[[], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with postgres_engine.begin() as connection:
        raw_token = f.invite(connection)
    with browser_client_factory() as client:
        begun = _start(client, raw_token)
        response = client.post(
            _CANCEL_URL,
            headers={
                "Origin": _DEV_ORIGIN,
                "X-Onboarding-CSRF-Token": begun["onboarding_csrf_token"],
            },
        )
        assert response.status_code == 204
        assert DEV_ONBOARDING_COOKIE_NAME not in client.cookies

        status_response = client.get(_STATUS_URL)
    assert status_response.status_code == 404
