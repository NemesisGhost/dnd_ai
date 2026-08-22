"""API-layer coverage for `dnd_ai.api.foundry_pairing` (docs/PLAN.md
§23.5 — Phase 11R workstream E).

Deep command-layer behavioral correctness (single-use pairing-code
consumption, revalidation on token exchange, revocation cascades, ...) is
already covered by `tests/database/test_foundry_pairing_commands.py`. This
file proves the HTTP wiring itself: routing, request/response shapes,
`require_campaign_capability`/`require_human_user_id` gating, the public
(no-principal) pairing/token endpoints, cross-campaign GM scoping, and
rate limiting — the same "wiring, not re-proof" scope `tests/database/
test_api_local_auth.py`'s own docstring establishes for its domain.

`oidc_principal` (the existing test convention — see `tests/factories.py`)
overrides `get_authenticated_user_id` directly for every capability-gated
route here, since none of them are CSRF-sensitive (CSRF only applies to a
`LOCAL_SESSION_AUTH_METHOD` principal, per `dnd_ai.api.auth._enforce_csrf_
and_origin`) and a real login flow would only add unrelated setup. The
public `/foundry/pair` and `/foundry/token` endpoints are exercised with
real `Authorization` headers instead, since they never go through
`get_authenticated_user_id` at all.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from dnd_ai.api.app import create_app
from dnd_ai.api.auth import get_authenticated_user_id
from dnd_ai.api.deps import get_engine
from dnd_ai.api.foundry_pairing import (
    get_foundry_pairing_rate_limiter,
    get_foundry_token_rate_limiter,
)
from dnd_ai.commands._shared import lookup_id
from dnd_ai.domain.foundry_pairing import FOUNDRY_SCOPES
from dnd_ai.domain.rate_limit import RateLimiter
from tests.factories import (
    make_campaign,
    make_campaign_membership,
    make_external_system,
    make_membership_role,
    make_role,
    make_role_capability,
    make_timeline,
    make_user,
    make_world,
    oidc_principal,
)

pytestmark = pytest.mark.database


def _generous_rate_limiter() -> RateLimiter:
    return RateLimiter(max_attempts=10_000, window=timedelta(minutes=15))


@pytest.fixture
def client_factory(postgres_engine: Engine) -> Callable[[], TestClient]:
    def _make() -> TestClient:
        app = create_app()
        app.dependency_overrides[get_engine] = lambda: postgres_engine
        app.dependency_overrides[get_foundry_pairing_rate_limiter] = _generous_rate_limiter
        app.dependency_overrides[get_foundry_token_rate_limiter] = _generous_rate_limiter
        return TestClient(app, raise_server_exceptions=False)

    return _make


@pytest.fixture
def principal_client_factory(postgres_engine: Engine) -> Callable[[uuid.UUID], TestClient]:
    def _make(user_id: uuid.UUID) -> TestClient:
        app = create_app()
        app.dependency_overrides[get_engine] = lambda: postgres_engine
        app.dependency_overrides[get_foundry_pairing_rate_limiter] = _generous_rate_limiter
        app.dependency_overrides[get_foundry_token_rate_limiter] = _generous_rate_limiter
        app.dependency_overrides[get_authenticated_user_id] = lambda: oidc_principal(user_id)
        return TestClient(app, raise_server_exceptions=False)

    return _make


def _grant_role(
    postgres_engine: Engine, *, campaign_id: uuid.UUID, user_id: uuid.UUID, capability_code: str
) -> None:
    with postgres_engine.begin() as connection:
        membership_id = make_campaign_membership(connection, campaign_id, user_id)
        role_id = make_role(connection, campaign_id=campaign_id)
        capability_id = lookup_id(
            connection, "security", "capabilities", "capability_id", capability_code
        )
        make_role_capability(connection, role_id, capability_id)
        make_membership_role(connection, membership_id, role_id)


@dataclass(frozen=True)
class _CampaignSetup:
    world_id: uuid.UUID
    campaign_id: uuid.UUID
    external_system_id: uuid.UUID


def _make_campaign(postgres_engine: Engine, *, slug_prefix: str) -> _CampaignSetup:
    with postgres_engine.connect() as connection:
        world_id = make_world(connection, slug=f"{slug_prefix}-{uuid.uuid4().hex[:8]}")
        timeline_id = make_timeline(connection, world_id)
        campaign_id = make_campaign(connection, timeline_id, lifecycle_status_code="pending")
        external_system_id = make_external_system(connection, world_id)
        connection.commit()
    return _CampaignSetup(
        world_id=world_id, campaign_id=campaign_id, external_system_id=external_system_id
    )


def _fully_paired_device(
    client_factory: Callable[[], TestClient],
    principal_client_factory: Callable[[uuid.UUID], TestClient],
    *,
    setup: _CampaignSetup,
    member_user_id: uuid.UUID,
) -> tuple[str, str, str]:
    """Returns (foundry_device_id, foundry_connection_id, raw_device_secret)
    for a freshly paired device belonging to member_user_id."""
    with principal_client_factory(member_user_id) as client:
        created = client.post(
            f"/campaigns/{setup.campaign_id}/foundry/pairing-codes",
            json={
                "external_system_id": str(setup.external_system_id),
                "requested_scopes": sorted(FOUNDRY_SCOPES),
            },
        )
    assert created.status_code == 201, created.text
    with client_factory() as client:
        paired = client.post(
            "/foundry/pair",
            json={
                "raw_code": created.json()["raw_code"],
                "foundry_user_id": f"foundry-user-{uuid.uuid4().hex[:8]}",
                "foundry_origin": "https://foundry.example.test",
                "device_label": "test-device",
            },
        )
    assert paired.status_code == 201, paired.text
    body = paired.json()
    return body["foundry_device_id"], body["foundry_connection_id"], body["raw_device_secret"]


# ---------------------------------------------------------------------------
# Pairing-code creation
# ---------------------------------------------------------------------------


def test_create_pairing_code_endpoint_succeeds_for_a_campaign_member(
    principal_client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine
) -> None:
    setup = _make_campaign(postgres_engine, slug_prefix="fp-create")
    with postgres_engine.begin() as connection:
        user_id = make_user(connection, "Member")
    _grant_role(
        postgres_engine,
        campaign_id=setup.campaign_id,
        user_id=user_id,
        capability_code="campaign.view",
    )

    with principal_client_factory(user_id) as client:
        response = client.post(
            f"/campaigns/{setup.campaign_id}/foundry/pairing-codes",
            json={
                "external_system_id": str(setup.external_system_id),
                "requested_scopes": sorted(FOUNDRY_SCOPES),
            },
        )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["raw_code"]
    assert sorted(body["requested_scopes"]) == sorted(FOUNDRY_SCOPES)


def test_create_pairing_code_endpoint_rejects_a_non_member(
    principal_client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine
) -> None:
    setup = _make_campaign(postgres_engine, slug_prefix="fp-nonmember")
    with postgres_engine.begin() as connection:
        user_id = make_user(connection, "Not A Member")

    with principal_client_factory(user_id) as client:
        response = client.post(
            f"/campaigns/{setup.campaign_id}/foundry/pairing-codes",
            json={
                "external_system_id": str(setup.external_system_id),
                "requested_scopes": sorted(FOUNDRY_SCOPES),
            },
        )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Full pairing lifecycle: create -> consume -> exchange -> list -> revoke
# ---------------------------------------------------------------------------


def test_full_pairing_lifecycle_end_to_end(
    principal_client_factory: Callable[[uuid.UUID], TestClient],
    client_factory: Callable[[], TestClient],
    postgres_engine: Engine,
) -> None:
    setup = _make_campaign(postgres_engine, slug_prefix="fp-lifecycle")
    with postgres_engine.begin() as connection:
        user_id = make_user(connection, "Pairing Member")
    _grant_role(
        postgres_engine,
        campaign_id=setup.campaign_id,
        user_id=user_id,
        capability_code="campaign.view",
    )

    with principal_client_factory(user_id) as client:
        created = client.post(
            f"/campaigns/{setup.campaign_id}/foundry/pairing-codes",
            json={
                "external_system_id": str(setup.external_system_id),
                "requested_scopes": sorted(FOUNDRY_SCOPES),
            },
        )
    assert created.status_code == 201, created.text
    raw_code = created.json()["raw_code"]

    with client_factory() as client:
        paired = client.post(
            "/foundry/pair",
            json={
                "raw_code": raw_code,
                "foundry_user_id": "foundry-user-1",
                "foundry_origin": "https://foundry.example.test",
                "device_label": "device-one",
            },
        )
    assert paired.status_code == 201, paired.text
    paired_body = paired.json()
    assert paired_body["campaign_id"] == str(setup.campaign_id)
    foundry_device_id = paired_body["foundry_device_id"]

    # Consuming the same code again fails (single-use).
    with client_factory() as client:
        replay = client.post(
            "/foundry/pair",
            json={
                "raw_code": raw_code,
                "foundry_user_id": "foundry-user-1",
                "foundry_origin": "https://foundry.example.test",
                "device_label": "device-two",
            },
        )
    assert replay.status_code == 404

    with client_factory() as client:
        exchanged = client.post(
            "/foundry/token",
            headers={
                "Authorization": f"FoundryDevice {foundry_device_id}.{paired_body['raw_device_secret']}"
            },
        )
    assert exchanged.status_code == 200, exchanged.text
    assert exchanged.json()["raw_access_token"] != paired_body["raw_access_token"]

    with principal_client_factory(user_id) as client:
        listed = client.get("/foundry/devices")
    assert listed.status_code == 200
    assert [d["foundry_device_id"] for d in listed.json()] == [foundry_device_id]
    assert listed.json()[0]["is_revoked"] is False

    with principal_client_factory(user_id) as client:
        revoked = client.delete(f"/foundry/devices/{foundry_device_id}")
    assert revoked.status_code == 204

    with client_factory() as client:
        exchange_after_revoke = client.post(
            "/foundry/token",
            headers={
                "Authorization": f"FoundryDevice {foundry_device_id}.{paired_body['raw_device_secret']}"
            },
        )
    assert exchange_after_revoke.status_code == 401


def test_consume_foundry_pairing_code_endpoint_rejects_an_unknown_code(
    client_factory: Callable[[], TestClient],
) -> None:
    with client_factory() as client:
        response = client.post(
            "/foundry/pair",
            json={
                "raw_code": "not-a-real-code",
                "foundry_user_id": "foundry-user-1",
                "foundry_origin": "https://foundry.example.test",
                "device_label": "device-one",
            },
        )
    assert response.status_code == 404


def test_foundry_token_endpoint_rejects_a_malformed_authorization_header(
    client_factory: Callable[[], TestClient],
) -> None:
    with client_factory() as client:
        response = client.post("/foundry/token", headers={"Authorization": "Bearer whatever"})
    assert response.status_code == 401


def test_foundry_token_endpoint_rejects_an_unknown_device(
    client_factory: Callable[[], TestClient],
) -> None:
    with client_factory() as client:
        response = client.post(
            "/foundry/token",
            headers={"Authorization": f"FoundryDevice {uuid.uuid4()}.some-secret"},
        )
    assert response.status_code == 401


def test_foundry_token_endpoint_is_rate_limited(postgres_engine: Engine) -> None:
    shared_limiter = RateLimiter(max_attempts=2, window=timedelta(minutes=15))
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: postgres_engine
    app.dependency_overrides[get_foundry_pairing_rate_limiter] = _generous_rate_limiter
    app.dependency_overrides[get_foundry_token_rate_limiter] = lambda: shared_limiter
    device_id = uuid.uuid4()
    with TestClient(app, raise_server_exceptions=False) as client:
        for _ in range(2):
            response = client.post(
                "/foundry/token",
                headers={"Authorization": f"FoundryDevice {device_id}.wrong-secret"},
            )
            assert response.status_code == 401
        limited = client.post(
            "/foundry/token",
            headers={"Authorization": f"FoundryDevice {device_id}.wrong-secret"},
        )
    assert limited.status_code == 429, limited.text


# ---------------------------------------------------------------------------
# GM campaign administration (access.manage), cross-campaign scoping
# ---------------------------------------------------------------------------


def test_gm_can_list_and_revoke_a_campaign_member_device(
    client_factory: Callable[[], TestClient],
    principal_client_factory: Callable[[uuid.UUID], TestClient],
    postgres_engine: Engine,
) -> None:
    setup = _make_campaign(postgres_engine, slug_prefix="fp-gm")
    with postgres_engine.begin() as connection:
        member_user_id = make_user(connection, "Player")
        gm_user_id = make_user(connection, "GM")
    _grant_role(
        postgres_engine,
        campaign_id=setup.campaign_id,
        user_id=member_user_id,
        capability_code="campaign.view",
    )
    _grant_role(
        postgres_engine,
        campaign_id=setup.campaign_id,
        user_id=gm_user_id,
        capability_code="access.manage",
    )

    foundry_device_id, _connection_id, _secret = _fully_paired_device(
        client_factory, principal_client_factory, setup=setup, member_user_id=member_user_id
    )

    with principal_client_factory(gm_user_id) as client:
        listed = client.get(f"/campaigns/{setup.campaign_id}/foundry/devices")
    assert listed.status_code == 200
    assert [d["foundry_device_id"] for d in listed.json()] == [foundry_device_id]
    assert listed.json()[0]["user_id"] == str(member_user_id)

    with principal_client_factory(gm_user_id) as client:
        revoked = client.delete(
            f"/campaigns/{setup.campaign_id}/foundry/devices/{foundry_device_id}"
        )
    assert revoked.status_code == 204

    with principal_client_factory(member_user_id) as client:
        listed_after = client.get("/foundry/devices")
    assert listed_after.json()[0]["is_revoked"] is True


def test_gm_cannot_revoke_a_device_in_a_different_campaign(
    client_factory: Callable[[], TestClient],
    principal_client_factory: Callable[[uuid.UUID], TestClient],
    postgres_engine: Engine,
) -> None:
    setup = _make_campaign(postgres_engine, slug_prefix="fp-owncamp")
    other_setup = _make_campaign(postgres_engine, slug_prefix="fp-othercamp")
    with postgres_engine.begin() as connection:
        member_user_id = make_user(connection, "Player")
        gm_user_id = make_user(connection, "GM Elsewhere")
    _grant_role(
        postgres_engine,
        campaign_id=setup.campaign_id,
        user_id=member_user_id,
        capability_code="campaign.view",
    )
    _grant_role(
        postgres_engine,
        campaign_id=other_setup.campaign_id,
        user_id=gm_user_id,
        capability_code="access.manage",
    )

    foundry_device_id, foundry_connection_id, _secret = _fully_paired_device(
        client_factory, principal_client_factory, setup=setup, member_user_id=member_user_id
    )

    with principal_client_factory(gm_user_id) as client:
        device_response = client.delete(
            f"/campaigns/{other_setup.campaign_id}/foundry/devices/{foundry_device_id}"
        )
    assert device_response.status_code == 404

    with principal_client_factory(gm_user_id) as client:
        connection_response = client.delete(
            f"/campaigns/{other_setup.campaign_id}/foundry/connections/{foundry_connection_id}"
        )
    assert connection_response.status_code == 404

    # Proves the device really is untouched, not merely "the endpoint
    # returned an error" — the owning member still sees it active.
    with principal_client_factory(member_user_id) as client:
        listed = client.get("/foundry/devices")
    assert listed.json()[0]["is_revoked"] is False


def test_gm_can_revoke_a_campaign_connection(
    client_factory: Callable[[], TestClient],
    principal_client_factory: Callable[[uuid.UUID], TestClient],
    postgres_engine: Engine,
) -> None:
    setup = _make_campaign(postgres_engine, slug_prefix="fp-connrevoke")
    with postgres_engine.begin() as connection:
        member_user_id = make_user(connection, "Player")
        gm_user_id = make_user(connection, "GM")
    _grant_role(
        postgres_engine,
        campaign_id=setup.campaign_id,
        user_id=member_user_id,
        capability_code="campaign.view",
    )
    _grant_role(
        postgres_engine,
        campaign_id=setup.campaign_id,
        user_id=gm_user_id,
        capability_code="access.manage",
    )

    foundry_device_id, foundry_connection_id, _secret = _fully_paired_device(
        client_factory, principal_client_factory, setup=setup, member_user_id=member_user_id
    )

    with principal_client_factory(gm_user_id) as client:
        response = client.delete(
            f"/campaigns/{setup.campaign_id}/foundry/connections/{foundry_connection_id}"
        )
    assert response.status_code == 204

    with principal_client_factory(member_user_id) as client:
        listed = client.get("/foundry/devices")
    assert listed.json()[0]["foundry_device_id"] == foundry_device_id
    assert listed.json()[0]["is_revoked"] is True


# ---------------------------------------------------------------------------
# Self-service rotation
# ---------------------------------------------------------------------------


def test_rotate_own_device_endpoint_succeeds(
    client_factory: Callable[[], TestClient],
    principal_client_factory: Callable[[uuid.UUID], TestClient],
    postgres_engine: Engine,
) -> None:
    setup = _make_campaign(postgres_engine, slug_prefix="fp-rotate")
    with postgres_engine.begin() as connection:
        member_user_id = make_user(connection, "Player")
    _grant_role(
        postgres_engine,
        campaign_id=setup.campaign_id,
        user_id=member_user_id,
        capability_code="campaign.view",
    )

    foundry_device_id, _connection_id, _secret = _fully_paired_device(
        client_factory, principal_client_factory, setup=setup, member_user_id=member_user_id
    )

    with principal_client_factory(member_user_id) as client:
        rotated = client.post(f"/foundry/devices/{foundry_device_id}/rotate", json={})
    assert rotated.status_code == 200, rotated.text
    assert rotated.json()["old_foundry_device_id"] == foundry_device_id
    assert rotated.json()["new_foundry_device_id"] != foundry_device_id

    with client_factory() as client:
        old_secret_exchange = client.post(
            "/foundry/token", headers={"Authorization": f"FoundryDevice {foundry_device_id}.stale"}
        )
    assert old_secret_exchange.status_code == 401
