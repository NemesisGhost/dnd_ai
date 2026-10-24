"""Tests for `dnd_ai.api.local_auth.list_platform_accounts_endpoint` — the
`GET /admin/accounts` platform-account directory (Phase 13E checkpoint 9;
owner decision D-2, `PHASE13E_REMAINING_IMPLEMENTATION_PLAN.md` §14).

Covers: a platform administrator sees the list; a non-administrator,
including a campaign owner holding `access.manage`, gets a non-disclosing
404; a pending account shows the activation-token login name; search
matches display name and login name; `email` never appears in any
response; keyset pagination is stable; `accounts.manage` is
reported only in the session bootstrap for both an administrator and an
ordinary user.
"""

import uuid
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from dnd_ai.api.app import create_app
from dnd_ai.api.auth import get_authenticated_user_id
from dnd_ai.api.deps import get_engine
from dnd_ai.commands.local_auth import _create_local_account_impl
from tests.factories import (
    lookup_id,
    make_campaign,
    make_campaign_membership,
    make_platform_administrator,
    make_role,
    make_role_capability,
    make_timeline,
    make_user,
    make_world,
    oidc_principal,
)

pytestmark = pytest.mark.database

_ACCOUNTS_URL = "/admin/accounts"


@pytest.fixture
def client_factory(postgres_engine: Engine) -> Callable[[uuid.UUID], TestClient]:
    def _make(user_id: uuid.UUID) -> TestClient:
        app = create_app()
        app.dependency_overrides[get_engine] = lambda: postgres_engine
        app.dependency_overrides[get_authenticated_user_id] = lambda: oidc_principal(user_id)
        return TestClient(app, raise_server_exceptions=False)

    return _make


def test_a_platform_administrator_sees_the_list(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine
) -> None:
    with postgres_engine.begin() as connection:
        admin_user_id = make_platform_administrator(connection, "Directory Admin")
        make_user(connection, "Directory Other User")

    with client_factory(admin_user_id) as client:
        # Scoped to this test's own fixtures -- the shared session database
        # accumulates many accounts across the whole test run, and the
        # unfiltered first page is not guaranteed to include them.
        response = client.get(_ACCOUNTS_URL, params={"q": "Directory"})
    assert response.status_code == 200, response.text
    payload = response.json()
    display_names = {item["display_name"] for item in payload["items"]}
    assert "Directory Admin" in display_names
    assert "Directory Other User" in display_names


def test_a_non_administrator_gets_a_non_disclosing_404(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine
) -> None:
    with postgres_engine.begin() as connection:
        plain_user_id = make_user(connection, "Directory Plain User")

    with client_factory(plain_user_id) as client:
        response = client.get(_ACCOUNTS_URL)
    assert response.status_code == 404


def test_a_campaign_owner_with_access_manage_still_gets_404(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine
) -> None:
    with postgres_engine.begin() as connection:
        world_id = make_world(connection, slug=f"pa-{uuid.uuid4().hex[:8]}")
        timeline_id = make_timeline(connection, world_id, is_primary=True)
        campaign_id = make_campaign(
            connection, timeline_id, "Directory Campaign", lifecycle_status_code="pending"
        )
        access_manage_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "access.manage"
        )
        owner_role_id = make_role(
            connection, campaign_id=campaign_id, code=f"owner_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, owner_role_id, access_manage_id)
        owner_user_id = make_user(connection, "Directory Campaign Owner")
        owner_membership_id = make_campaign_membership(connection, campaign_id, owner_user_id)
        from tests.factories import make_membership_role

        make_membership_role(connection, owner_membership_id, owner_role_id)

    with client_factory(owner_user_id) as client:
        response = client.get(_ACCOUNTS_URL)
    assert response.status_code == 404


def test_pending_account_shows_the_activation_token_login_name(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine
) -> None:
    login_name = f"pa.pending.{uuid.uuid4().hex[:8]}"
    with postgres_engine.begin() as connection:
        admin_user_id = make_platform_administrator(connection, "Pending Directory Admin")
        issued = _create_local_account_impl(
            connection,
            created_by_user_id=admin_user_id,
            login_name=login_name,
            display_name="Pending Registrant",
        )

    with client_factory(admin_user_id) as client:
        response = client.get(_ACCOUNTS_URL, params={"q": "Pending Registrant"})
    assert response.status_code == 200, response.text
    matches = [item for item in response.json()["items"] if item["user_id"] == str(issued.user_id)]
    assert len(matches) == 1
    assert matches[0]["login_name"] == login_name
    assert matches[0]["has_local_credential"] is False
    assert matches[0]["has_outstanding_activation"] is True
    assert "email" not in matches[0]


def test_search_matches_login_name_of_an_activated_account(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine
) -> None:
    login_name = f"pa.activated.{uuid.uuid4().hex[:8]}"
    with postgres_engine.begin() as connection:
        admin_user_id = make_platform_administrator(connection, "Search Directory Admin")
        issued = _create_local_account_impl(
            connection,
            created_by_user_id=admin_user_id,
            login_name=login_name,
            display_name="Some Other Display Name",
        )
        from dnd_ai.commands.local_auth import _activate_local_account_impl

        _activate_local_account_impl(
            connection,
            raw_activation_token=issued.raw_token,
            raw_password="a genuinely random passphrase 1",
        )

    with client_factory(admin_user_id) as client:
        response = client.get(_ACCOUNTS_URL, params={"q": login_name})
    assert response.status_code == 200, response.text
    matches = [item for item in response.json()["items"] if item["user_id"] == str(issued.user_id)]
    assert len(matches) == 1
    assert matches[0]["login_name"] == login_name
    assert matches[0]["has_local_credential"] is True
    assert matches[0]["has_outstanding_activation"] is False


def test_keyset_pagination_returns_every_row_exactly_once(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine
) -> None:
    prefix = f"pa-page-{uuid.uuid4().hex[:6]}"
    with postgres_engine.begin() as connection:
        admin_user_id = make_platform_administrator(connection, f"{prefix}-admin")
        created_ids = {str(admin_user_id)}
        for i in range(5):
            created_ids.add(str(make_user(connection, f"{prefix}-user-{i}")))

    seen_ids: set[str] = set()
    cursor: str | None = None
    with client_factory(admin_user_id) as client:
        for _ in range(20):
            params = {"q": prefix, "limit": 2}
            if cursor is not None:
                params["cursor"] = cursor
            response = client.get(_ACCOUNTS_URL, params=params)
            assert response.status_code == 200, response.text
            payload = response.json()
            for item in payload["items"]:
                assert item["user_id"] not in seen_ids
                seen_ids.add(item["user_id"])
            cursor = payload["next_cursor"]
            if cursor is None:
                break
    assert seen_ids == created_ids


def test_session_bootstrap_reports_platform_administrator_status(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine
) -> None:
    with postgres_engine.begin() as connection:
        admin_user_id = make_platform_administrator(connection, "Bootstrap Admin")
        plain_user_id = make_user(connection, "Bootstrap Plain User")

    with client_factory(admin_user_id) as client:
        admin_response = client.get("/auth/session")
    assert admin_response.status_code == 200, admin_response.text
    assert "accounts.manage" in admin_response.json()["global_capabilities"]

    with client_factory(plain_user_id) as client:
        plain_response = client.get("/auth/session")
    assert plain_response.status_code == 200, plain_response.text
    assert "accounts.manage" not in plain_response.json()["global_capabilities"]
