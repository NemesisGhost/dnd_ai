"""HTTP-layer coverage for `dnd_ai.api.user_preferences` and the preference
fields of `GET /auth/session` (docs/UI_DESIGN.md §4.7).

Uses a *real* `/auth/login` cookie session (CSRF and Origin only apply to a
local-session principal), plus a Foundry-principal override to prove the
routes are human-only. Command/query semantics are covered in
`tests/database/test_user_preferences_commands.py`.
"""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import Connection, Engine, text

from dnd_ai.api.app import create_app
from dnd_ai.api.auth import get_authenticated_user_id
from dnd_ai.api.deps import get_engine
from dnd_ai.api.local_auth import (
    get_login_account_rate_limiter,
    get_login_ip_rate_limiter,
    get_token_consumption_rate_limiter,
)
from dnd_ai.commands.local_auth import _create_local_account_impl
from dnd_ai.domain.access import FOUNDRY_ACCESS_AUTH_METHOD, AuthenticatedPrincipal
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
    make_user,
    make_world,
    system_role_id,
)

pytestmark = pytest.mark.database

_ORIGIN = "http://localhost:5173"
_PASSWORD = "a genuinely random passphrase 1"
_STARTUP = "/auth/preferences/campaign-startup"
_VISITED = "/auth/preferences/last-visited-campaign"


def _generous() -> RateLimiter:
    return RateLimiter(max_attempts=10_000, window=timedelta(minutes=15))


@dataclass
class Session:
    client: TestClient
    csrf: str
    user_id: uuid.UUID
    campaign_a: uuid.UUID
    campaign_b: uuid.UUID
    foreign_campaign: uuid.UUID
    engine: Engine

    @property
    def headers(self) -> dict[str, str]:
        return {"Origin": _ORIGIN, "X-CSRF-Token": self.csrf}

    def stored(self) -> dict[str, object] | None:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    text(
                        "SELECT preferred_campaign_id, last_visited_campaign_id "
                        "FROM security.user_portal_preferences WHERE user_id = :u"
                    ),
                    {"u": self.user_id},
                )
                .mappings()
                .one_or_none()
            )
        return dict(row) if row is not None else None


def _managed_campaign(connection: Connection, timeline_id: uuid.UUID, name: str) -> uuid.UUID:
    """A committed campaign must retain an access manager (DATABASE_MODEL.md
    §22 rule 19); a separate manager user keeps the test user an ordinary
    member whose membership can be revoked."""
    campaign_id = make_campaign(connection, timeline_id, name)
    manager_id = make_user(connection, "Prefs Manager")
    membership_id = make_campaign_membership(connection, campaign_id, manager_id)
    role_id = make_role(connection, campaign_id=campaign_id)
    make_role_capability(
        connection,
        role_id,
        lookup_id(connection, "security", "capabilities", "capability_id", "access.manage"),
    )
    make_membership_role(connection, membership_id, role_id)
    return campaign_id


@pytest.fixture
def session(postgres_engine: Engine) -> Iterator[Session]:
    with postgres_engine.begin() as connection:
        admin_id = make_platform_administrator(connection)
        world_id = make_world(connection, slug=f"prefs-api-{uuid.uuid4().hex[:8]}")
        timeline_id = make_timeline(connection, world_id, is_primary=True)
        campaign_a = _managed_campaign(connection, timeline_id, "Pref A")
        campaign_b = _managed_campaign(connection, timeline_id, "Pref B")
        foreign = _managed_campaign(connection, timeline_id, "Pref Foreign")
        login_name = f"prefs-{uuid.uuid4().hex[:8]}"
        created = _create_local_account_impl(
            connection,
            created_by_user_id=admin_id,
            login_name=login_name,
            display_name="Prefs User",
        )
        player_role_id = system_role_id(connection, "player")
        for campaign_id in (campaign_a, campaign_b):
            make_membership_role(
                connection,
                make_campaign_membership(connection, campaign_id, created.user_id),
                player_role_id,
            )

    app = create_app()
    app.dependency_overrides[get_engine] = lambda: postgres_engine
    app.dependency_overrides[get_login_ip_rate_limiter] = _generous
    app.dependency_overrides[get_login_account_rate_limiter] = _generous
    app.dependency_overrides[get_token_consumption_rate_limiter] = _generous
    with TestClient(app, raise_server_exceptions=False) as client:
        activated = client.post(
            "/auth/activate",
            json={"token": created.raw_token, "password": _PASSWORD},
            headers={"Origin": _ORIGIN},
        )
        assert activated.status_code == 200, activated.text
        login = client.post(
            "/auth/login",
            json={"login_name": login_name, "password": _PASSWORD},
            headers={"Origin": _ORIGIN},
        )
        assert login.status_code == 200, login.text
        try:
            yield Session(
                client=client,
                csrf=login.json()["csrf_token"],
                user_id=created.user_id,
                campaign_a=campaign_a,
                campaign_b=campaign_b,
                foreign_campaign=foreign,
                engine=postgres_engine,
            )
        finally:
            # Committed active campaigns would leak into the shared session
            # database and trip other suites' "no dependents" invariants.
            with postgres_engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE campaign.campaigns SET lifecycle_status_id = "
                        "(SELECT lifecycle_status_id FROM core.lifecycle_statuses "
                        "WHERE code = 'archived') WHERE campaign_id = ANY(:ids)"
                    ),
                    {"ids": [campaign_a, campaign_b, foreign]},
                )


# ---------------------------------------------------------------------------
# Happy paths and bootstrap reflection
# ---------------------------------------------------------------------------


def test_startup_and_last_visited_round_trip_through_the_bootstrap(session: Session) -> None:
    put_startup = session.client.put(
        _STARTUP, json={"preferred_campaign_id": str(session.campaign_b)}, headers=session.headers
    )
    put_visited = session.client.put(
        _VISITED, json={"campaign_id": str(session.campaign_a)}, headers=session.headers
    )
    assert put_startup.status_code == 204, put_startup.text
    assert put_visited.status_code == 204, put_visited.text
    assert put_startup.content == b""

    body = session.client.get("/auth/session").json()

    assert body["startup_campaign_id"] == str(session.campaign_b)
    assert body["campaign_preferences"] == {
        "startup_mode": "preferred_campaign",
        "preferred_campaign_id": str(session.campaign_b),
        "last_visited_campaign_id": str(session.campaign_a),
    }


def test_null_preferred_campaign_clears_the_fixed_choice(session: Session) -> None:
    session.client.put(
        _STARTUP, json={"preferred_campaign_id": str(session.campaign_a)}, headers=session.headers
    )
    cleared = session.client.put(
        _STARTUP, json={"preferred_campaign_id": None}, headers=session.headers
    )
    assert cleared.status_code == 204
    assert session.stored() == {
        "preferred_campaign_id": None,
        "last_visited_campaign_id": None,
    }


def test_session_get_never_writes_preferences(session: Session) -> None:
    for _ in range(2):
        assert session.client.get("/auth/session").status_code == 200
    assert session.stored() is None


def test_membership_revocation_takes_effect_immediately(session: Session) -> None:
    session.client.put(
        _STARTUP, json={"preferred_campaign_id": str(session.campaign_b)}, headers=session.headers
    )
    with session.engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE security.campaign_memberships "
                "SET ended_at = joined_at + interval '1 second' "
                "WHERE campaign_id = :c AND user_id = :u"
            ),
            {"c": session.campaign_b, "u": session.user_id},
        )

    body = session.client.get("/auth/session").json()

    assert body["campaign_preferences"]["preferred_campaign_id"] is None
    assert body["campaign_preferences"]["startup_mode"] == "resume_last_visited"
    assert str(session.campaign_b) not in str(body)
    # Stored row is untouched; it simply no longer applies.
    assert session.stored() is not None


def test_repeated_writes_are_deterministic(session: Session) -> None:
    for campaign in (session.campaign_a, session.campaign_b, session.campaign_b):
        response = session.client.put(
            _VISITED, json={"campaign_id": str(campaign)}, headers=session.headers
        )
        assert response.status_code == 204
    assert session.stored() == {
        "preferred_campaign_id": None,
        "last_visited_campaign_id": session.campaign_b,
    }


def test_preferences_hold_only_campaign_ids_no_authorization_data(session: Session) -> None:
    session.client.put(
        _STARTUP, json={"preferred_campaign_id": str(session.campaign_a)}, headers=session.headers
    )
    stored = session.stored()
    assert stored is not None
    assert set(stored) == {"preferred_campaign_id", "last_visited_campaign_id"}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


def test_unknown_and_unauthorized_campaigns_return_identical_404(session: Session) -> None:
    unauthorized = session.client.put(
        _VISITED, json={"campaign_id": str(session.foreign_campaign)}, headers=session.headers
    )
    unknown = session.client.put(
        _VISITED, json={"campaign_id": str(uuid.uuid4())}, headers=session.headers
    )
    unauthorized_startup = session.client.put(
        _STARTUP,
        json={"preferred_campaign_id": str(session.foreign_campaign)},
        headers=session.headers,
    )
    assert unauthorized.status_code == unknown.status_code == 404
    assert unauthorized_startup.status_code == 404

    def _without_correlation(response: Response) -> dict[str, object]:
        error = dict(response.json()["error"])
        error.pop("correlation_id")
        return error

    assert (
        _without_correlation(unauthorized)
        == _without_correlation(unknown)
        == _without_correlation(unauthorized_startup)
    )
    assert str(session.foreign_campaign) not in unauthorized.text
    assert session.stored() is None


@pytest.mark.parametrize("path", [_STARTUP, _VISITED])
def test_missing_csrf_header_is_rejected(session: Session, path: str) -> None:
    body = (
        {"preferred_campaign_id": None}
        if path == _STARTUP
        else {"campaign_id": str(session.campaign_a)}
    )
    response = session.client.put(path, json=body, headers={"Origin": _ORIGIN})
    assert response.status_code == 403
    assert session.stored() is None


def test_wrong_csrf_token_is_rejected(session: Session) -> None:
    response = session.client.put(
        _VISITED,
        json={"campaign_id": str(session.campaign_a)},
        headers={"Origin": _ORIGIN, "X-CSRF-Token": "not-the-token"},
    )
    assert response.status_code == 403
    assert session.stored() is None


def test_disallowed_origin_is_rejected(session: Session) -> None:
    response = session.client.put(
        _VISITED,
        json={"campaign_id": str(session.campaign_a)},
        headers={"Origin": "https://evil.example.com", "X-CSRF-Token": session.csrf},
    )
    assert response.status_code == 403
    assert session.stored() is None


@pytest.mark.parametrize(
    ("path", "body"),
    [
        (_STARTUP, {}),
        (_STARTUP, {"preferred_campaign_id": "not-a-uuid"}),
        (_VISITED, {}),
        (_VISITED, {"campaign_id": None}),
        (_VISITED, {"campaign_id": "nope"}),
    ],
)
def test_malformed_bodies_return_422(session: Session, path: str, body: dict[str, object]) -> None:
    response = session.client.put(path, json=body, headers=session.headers)
    assert response.status_code == 422
    assert session.stored() is None


def test_unauthenticated_requests_return_401(postgres_engine: Engine) -> None:
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: postgres_engine
    with TestClient(app, raise_server_exceptions=False) as client:
        startup = client.put(_STARTUP, json={"preferred_campaign_id": None})
        visited = client.put(_VISITED, json={"campaign_id": str(uuid.uuid4())})
    assert startup.status_code == visited.status_code == 401


def test_expired_session_returns_401(session: Session) -> None:
    with session.engine.begin() as connection:
        connection.execute(
            text("UPDATE security.browser_sessions SET revoked_at = now() WHERE user_id = :u"),
            {"u": session.user_id},
        )
    response = session.client.put(
        _VISITED, json={"campaign_id": str(session.campaign_a)}, headers=session.headers
    )
    assert response.status_code == 401


def test_delegated_foundry_principal_cannot_write_preferences(
    postgres_engine: Engine, session: Session
) -> None:
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: postgres_engine
    principal = AuthenticatedPrincipal(
        user_id=session.user_id,
        auth_method=FOUNDRY_ACCESS_AUTH_METHOD,
        foundry_external_system_id=uuid.uuid4(),
        foundry_world_id=uuid.uuid4(),
        campaign_id=session.campaign_a,
        foundry_connection_id=uuid.uuid4(),
        foundry_device_id=uuid.uuid4(),
        foundry_scopes=frozenset({"encounter_read"}),
    )
    app.dependency_overrides[get_authenticated_user_id] = lambda: principal
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.put(_VISITED, json={"campaign_id": str(session.campaign_a)})
    assert response.status_code == 403
    assert session.stored() is None


def test_oidc_principal_is_accepted_without_csrf(postgres_engine: Engine, session: Session) -> None:
    from tests.factories import oidc_principal

    app = create_app()
    app.dependency_overrides[get_engine] = lambda: postgres_engine
    app.dependency_overrides[get_authenticated_user_id] = lambda: oidc_principal(session.user_id)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.put(_VISITED, json={"campaign_id": str(session.campaign_a)})
    assert response.status_code == 204
    assert session.stored() == {
        "preferred_campaign_id": None,
        "last_visited_campaign_id": session.campaign_a,
    }
