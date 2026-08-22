"""Tests for `dnd_ai.api.auth` — the OIDC bearer-token dependencies wired
into FastAPI (header extraction, JWKS resolution, and resolution to a
`security.users` row), plus (Phase 11 workstream 2) the `FoundrySystem`
credential path `get_authenticated_user_id` also recognizes.
`dnd_ai.domain.tokens`' own signature/claims verification is covered
directly, with no database, by `tests/unit/test_token_verification.py`;
this module proves the request-scoped wiring around it end to end against
real PostgreSQL — `get_engine` overridden the same way `test_api_deps.py`
already establishes, and `get_jwks_client` overridden with a fake JWKS
client (a dict lookup against a locally generated keypair, never a live
identity provider or JWKS HTTP server — the same no-live-provider strategy
the unit tests use).
"""

import uuid
from collections.abc import Callable
from typing import Annotated

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, text

from dnd_ai.api.access import AccessContext, require_campaign_capability
from dnd_ai.api.app import create_app
from dnd_ai.api.auth import (
    get_authenticated_user_id,
    get_jwks_client,
    get_verified_token_claims,
    require_human_user_id,
)
from dnd_ai.api.deps import get_connection, get_engine
from dnd_ai.commands._shared import lookup_id
from dnd_ai.commands.foundry_pairing import (
    consume_foundry_pairing_code,
    create_foundry_pairing_code,
    revoke_foundry_connection,
    revoke_foundry_device,
)
from dnd_ai.commands.integration import issue_foundry_system_key, link_foundry_identity
from dnd_ai.config import settings
from dnd_ai.domain.access import (
    FOUNDRY_ACCESS_AUTH_METHOD,
    OIDC_AUTH_METHOD,
    AuthenticatedPrincipal,
)
from dnd_ai.domain.foundry_pairing import FOUNDRY_SCOPES
from dnd_ai.domain.tokens import VerifiedTokenClaims
from tests.factories import (
    make_campaign,
    make_campaign_membership,
    make_external_identity,
    make_external_system,
    make_membership_role,
    make_role,
    make_role_capability,
    make_timeline,
    make_user,
    make_world,
)
from tests.jwt_helpers import RSAKeypair, generate_test_rsa_keypair, make_signed_jwt

pytestmark = pytest.mark.database

_ISSUER = "https://test-idp.example"
_AUDIENCE = "test-audience"


class _FakeJWKSClient:
    """Stands in for `dnd_ai.api.auth._JWKSClient` — a plain dict lookup
    against a locally generated keypair, so these tests never fetch a JWKS
    document over the network. Matches `_JWKSClient.get_signing_key`'s
    contract exactly: returns the `RSAPublicKey` directly (not a `PyJWK`-
    like wrapper with a `.key` attribute), and raises on an unresolvable
    kid rather than returning something invalid."""

    def __init__(self, keypair: RSAKeypair) -> None:
        self._keypair = keypair

    def get_signing_key(self, kid: str) -> RSAPublicKey:
        if kid != self._keypair.kid:
            raise jwt.PyJWKClientError(f"no signing key for kid={kid!r}")
        return self._keypair.public_key


@pytest.fixture
def keypair() -> RSAKeypair:
    return generate_test_rsa_keypair()


@pytest.fixture
def client_factory(
    postgres_engine: Engine, keypair: RSAKeypair, monkeypatch: pytest.MonkeyPatch
) -> Callable[[], TestClient]:
    monkeypatch.setattr(settings, "oidc_issuer", _ISSUER)
    monkeypatch.setattr(settings, "oidc_audience", _AUDIENCE)

    app = create_app()
    app.dependency_overrides[get_engine] = lambda: postgres_engine
    app.dependency_overrides[get_jwks_client] = lambda: _FakeJWKSClient(keypair)

    @app.get("/test-claims")
    def _claims(
        claims: Annotated[VerifiedTokenClaims, Depends(get_verified_token_claims)],
    ) -> dict[str, str | None]:
        return {"issuer": claims.issuer, "subject": claims.subject, "email": claims.email}

    @app.get("/test-authenticated-user")
    def _authenticated_user(
        principal: Annotated[AuthenticatedPrincipal, Depends(get_authenticated_user_id)],
        # Proves the dependency really opened its own connection via
        # get_connection, not just resolved a claim in isolation.
        _connection: Annotated[Connection, Depends(get_connection)],
    ) -> dict[str, str]:
        return {"user_id": str(principal.user_id)}

    @app.get("/test-authenticated-principal")
    def _authenticated_principal(
        principal: Annotated[AuthenticatedPrincipal, Depends(get_authenticated_user_id)],
        _connection: Annotated[Connection, Depends(get_connection)],
    ) -> dict[str, str | list[str] | None]:
        def _opt(value: uuid.UUID | None) -> str | None:
            return str(value) if value is not None else None

        return {
            "user_id": str(principal.user_id),
            "auth_method": principal.auth_method,
            "foundry_external_system_id": _opt(principal.foundry_external_system_id),
            "foundry_world_id": _opt(principal.foundry_world_id),
            "foundry_claimed_actor_id": principal.foundry_claimed_actor_id,
            "campaign_id": _opt(principal.campaign_id),
            "foundry_connection_id": _opt(principal.foundry_connection_id),
            "foundry_device_id": _opt(principal.foundry_device_id),
            "foundry_scopes": sorted(principal.foundry_scopes)
            if principal.foundry_scopes is not None
            else None,
        }

    @app.get("/test-campaigns/{campaign_id}/foundry-access-gate")
    def _foundry_access_gate(
        access: Annotated[
            AccessContext,
            Depends(
                require_campaign_capability(
                    "canon.edit", allow_foundry_access=True, foundry_scope="combat_sync"
                )
            ),
        ],
    ) -> dict[str, str]:
        return {"campaign_id": str(access.campaign_id)}

    @app.get("/test-campaigns/{campaign_id}/foundry-access-scope-gate")
    def _foundry_access_scope_gate(
        access: Annotated[
            AccessContext,
            Depends(
                require_campaign_capability(
                    "canon.edit", allow_foundry_access=True, foundry_scope="character_state_sync"
                )
            ),
        ],
    ) -> dict[str, str]:
        return {"campaign_id": str(access.campaign_id)}

    @app.get("/test-campaigns/{campaign_id}/foundry-access-not-opted-in")
    def _foundry_access_not_opted_in(
        access: Annotated[AccessContext, Depends(require_campaign_capability("canon.edit"))],
    ) -> dict[str, str]:
        return {"campaign_id": str(access.campaign_id)}

    @app.get("/test-oidc-only-user")
    def _oidc_only_user(
        user_id: Annotated[uuid.UUID, Depends(require_human_user_id)],
    ) -> dict[str, str]:
        return {"user_id": str(user_id)}

    def _make() -> TestClient:
        return TestClient(app, raise_server_exceptions=False)

    return _make


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# get_verified_token_claims — header extraction + JWKS resolution, no DB
# ---------------------------------------------------------------------------


def test_missing_authorization_header_is_rejected(client_factory: Callable[[], TestClient]) -> None:
    with client_factory() as client:
        response = client.get("/test-claims")
    assert response.status_code == 401


@pytest.mark.parametrize(
    "header_value", ["not-a-bearer-token", "Basic dXNlcjpwYXNz", "Bearer", "Bearer "]
)
def test_malformed_authorization_header_is_rejected(
    header_value: str, client_factory: Callable[[], TestClient]
) -> None:
    with client_factory() as client:
        response = client.get("/test-claims", headers={"Authorization": header_value})
    assert response.status_code == 401


def test_an_invalid_token_is_rejected(
    keypair: RSAKeypair, client_factory: Callable[[], TestClient]
) -> None:
    token = make_signed_jwt(keypair, issuer="https://wrong-issuer.example", audience=_AUDIENCE)
    with client_factory() as client:
        response = client.get("/test-claims", headers=_bearer(token))
    assert response.status_code == 401


def test_a_valid_token_resolves_to_its_claims(
    keypair: RSAKeypair, client_factory: Callable[[], TestClient]
) -> None:
    token = make_signed_jwt(
        keypair,
        issuer=_ISSUER,
        audience=_AUDIENCE,
        subject="some-subject",
        extra_claims={"email": "player@example.com"},
    )
    with client_factory() as client:
        response = client.get("/test-claims", headers=_bearer(token))
    assert response.status_code == 200
    assert response.json() == {
        "issuer": _ISSUER,
        "subject": "some-subject",
        "email": "player@example.com",
    }


# ---------------------------------------------------------------------------
# get_authenticated_user_id — resolution against security.external_identities
# ---------------------------------------------------------------------------


def test_a_token_for_an_unlinked_identity_is_rejected(
    keypair: RSAKeypair, client_factory: Callable[[], TestClient]
) -> None:
    token = make_signed_jwt(
        keypair, issuer=_ISSUER, audience=_AUDIENCE, subject=f"unknown-{uuid.uuid4().hex[:8]}"
    )
    with client_factory() as client:
        response = client.get("/test-authenticated-user", headers=_bearer(token))
    assert response.status_code == 401


def test_a_token_for_a_revoked_identity_is_rejected(
    keypair: RSAKeypair, client_factory: Callable[[], TestClient], postgres_engine: Engine
) -> None:
    # A dedicated, committed connection — the FastAPI app's own request
    # runs on a separate connection (via the overridden get_engine), so
    # setup data must actually be committed to be visible to it, unlike
    # the always-rolled-back db_connection fixture used elsewhere.
    subject = f"subject-{uuid.uuid4().hex[:8]}"
    with postgres_engine.connect() as setup_connection:
        user_id = make_user(setup_connection, "Revoked Identity Tester")
        make_external_identity(
            setup_connection, user_id, issuer=_ISSUER, subject=subject, revoked=True
        )
        setup_connection.commit()

    token = make_signed_jwt(keypair, issuer=_ISSUER, audience=_AUDIENCE, subject=subject)
    with client_factory() as client:
        response = client.get("/test-authenticated-user", headers=_bearer(token))
    assert response.status_code == 401


def test_a_token_for_an_inactive_linked_user_is_rejected(
    keypair: RSAKeypair, client_factory: Callable[[], TestClient], postgres_engine: Engine
) -> None:
    subject = f"subject-{uuid.uuid4().hex[:8]}"
    with postgres_engine.connect() as setup_connection:
        user_id = make_user(setup_connection, "Archived Identity Tester", status_code="archived")
        make_external_identity(setup_connection, user_id, issuer=_ISSUER, subject=subject)
        setup_connection.commit()

    token = make_signed_jwt(keypair, issuer=_ISSUER, audience=_AUDIENCE, subject=subject)
    with client_factory() as client:
        response = client.get("/test-authenticated-user", headers=_bearer(token))
    assert response.status_code == 401


def test_a_token_for_a_linked_active_identity_resolves_the_correct_user(
    keypair: RSAKeypair, client_factory: Callable[[], TestClient], postgres_engine: Engine
) -> None:
    subject = f"subject-{uuid.uuid4().hex[:8]}"
    with postgres_engine.connect() as setup_connection:
        user_id = make_user(setup_connection, "Linked Identity Tester")
        make_external_identity(setup_connection, user_id, issuer=_ISSUER, subject=subject)
        setup_connection.commit()

    token = make_signed_jwt(keypair, issuer=_ISSUER, audience=_AUDIENCE, subject=subject)
    with client_factory() as client:
        response = client.get("/test-authenticated-user", headers=_bearer(token))
    assert response.status_code == 200
    assert response.json() == {"user_id": str(user_id)}


# ---------------------------------------------------------------------------
# get_authenticated_user_id — the FoundrySystem credential is retired
# (Workstream 11R High-severity finding 2): every request bearing an
# `Authorization: FoundrySystem ...` header is rejected with 401,
# unconditionally, before any database lookup, JWKS resolution, or
# distinction between "malformed"/"unknown"/"technically still valid" is
# ever made — see dnd_ai.api.auth's own docstring ("Foundry-adapter
# authentication, legacy scheme retired") for the full account. This
# collapses what used to be a dozen-plus tests proving the scheme's
# correct *acceptance* behavior into a much smaller set proving its
# uniform *rejection* — there is no behavior left to distinguish.
# ---------------------------------------------------------------------------


def _foundry_headers(
    external_system_id: uuid.UUID, raw_key: str, claimed_actor_id: str | None = None
) -> dict[str, str]:
    headers = {"Authorization": f"FoundrySystem {external_system_id}.{raw_key}"}
    if claimed_actor_id is not None:
        headers["X-Foundry-Actor-Id"] = claimed_actor_id
    return headers


@pytest.mark.parametrize(
    "credential",
    [
        "not-a-uuid.some-key",
        "no-separator-at-all",
        "",
        f"{uuid.uuid4()}.some-raw-key",  # well-formed but for an unknown system
    ],
)
def test_a_foundrysystem_credential_is_rejected_regardless_of_shape(
    credential: str, client_factory: Callable[[], TestClient]
) -> None:
    with client_factory() as client:
        response = client.get(
            "/test-authenticated-user",
            headers={
                "Authorization": f"FoundrySystem {credential}",
                "X-Foundry-Actor-Id": "some-foundry-user",
            },
        )
    assert response.status_code == 401


def test_a_technically_still_valid_foundrysystem_credential_is_rejected(
    client_factory: Callable[[], TestClient], postgres_engine: Engine
) -> None:
    # The strongest form of this regression: mint a credential that would
    # have authenticated successfully under the pre-retirement design
    # (linked identity, bound principal, active system, active user — every
    # precondition satisfied) via the domain-layer commands directly (the
    # HTTP issuance endpoint that used to do this is itself removed — see
    # dnd_ai.api.integration's own docstring, "Legacy FoundrySystem key
    # issuance retired"), then prove it is bounced at the authentication
    # boundary anyway. A credential this genuinely well-formed is exactly
    # the case a merely-partial fix (e.g. rejecting only malformed/unknown
    # credentials) could still miss.
    with postgres_engine.connect() as setup_connection:
        world_id = make_world(setup_connection, slug=f"foundry-auth-{uuid.uuid4().hex[:8]}")
        external_system_id = make_external_system(setup_connection, world_id)
        user_id = make_user(setup_connection, "Foundry-Bound GM")
        setup_connection.commit()
    link_foundry_identity(
        postgres_engine,
        external_system_id=external_system_id,
        foundry_user_id="gm-foundry-id",
        user_id=user_id,
    )
    key_result = issue_foundry_system_key(
        postgres_engine,
        external_system_id=external_system_id,
        principal_foundry_user_id="gm-foundry-id",
    )

    with client_factory() as client:
        response = client.get(
            "/test-authenticated-user",
            headers=_foundry_headers(external_system_id, key_result.raw_key, "gm-foundry-id"),
        )
    assert response.status_code == 401


def test_a_foundrysystem_credential_is_rejected_even_with_no_oidc_configured(
    client_factory: Callable[[], TestClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Regression for the exact failure mode a naive "just remove the
    # branch and fall through to OIDC" fix would reintroduce: with OIDC
    # entirely unconfigured (a fully supported local-auth-only deployment,
    # docs/PLAN.md §23.1), falling through to get_jwks_client() would raise
    # an unrelated AssertionError (a 500) instead of the plain 401 a
    # retired credential scheme must always produce. Rejection must happen
    # before the OIDC path is ever touched.
    monkeypatch.setattr(settings, "oidc_issuer", None)
    monkeypatch.setattr(settings, "oidc_audience", None)
    monkeypatch.setattr(settings, "oidc_jwks_url", None)
    with client_factory() as client:
        response = client.get(
            "/test-authenticated-user",
            headers={"Authorization": f"FoundrySystem {uuid.uuid4()}.some-key"},
        )
    assert response.status_code == 401


def test_an_oidc_bearer_token_still_authenticates_when_the_foundry_path_exists(
    keypair: RSAKeypair, client_factory: Callable[[], TestClient], postgres_engine: Engine
) -> None:
    # Regression guard: retiring the FoundrySystem branch must not change
    # the OIDC path's behavior for an ordinary Bearer token at all.
    subject = f"subject-{uuid.uuid4().hex[:8]}"
    with postgres_engine.connect() as setup_connection:
        user_id = make_user(setup_connection, "Still OIDC Tester")
        make_external_identity(setup_connection, user_id, issuer=_ISSUER, subject=subject)
        setup_connection.commit()

    token = make_signed_jwt(keypair, issuer=_ISSUER, audience=_AUDIENCE, subject=subject)
    with client_factory() as client:
        response = client.get("/test-authenticated-user", headers=_bearer(token))
    assert response.status_code == 200
    assert response.json() == {"user_id": str(user_id)}


# ---------------------------------------------------------------------------
# get_authenticated_user_id — AuthenticatedPrincipal scope (OIDC)
# ---------------------------------------------------------------------------


def test_an_oidc_token_carries_no_foundry_system_world_or_claimed_actor(
    keypair: RSAKeypair, client_factory: Callable[[], TestClient], postgres_engine: Engine
) -> None:
    subject = f"subject-{uuid.uuid4().hex[:8]}"
    with postgres_engine.connect() as setup_connection:
        user_id = make_user(setup_connection, "Principal Shape Tester")
        make_external_identity(setup_connection, user_id, issuer=_ISSUER, subject=subject)
        setup_connection.commit()

    token = make_signed_jwt(keypair, issuer=_ISSUER, audience=_AUDIENCE, subject=subject)
    with client_factory() as client:
        response = client.get("/test-authenticated-principal", headers=_bearer(token))
    assert response.status_code == 200
    assert response.json() == {
        "user_id": str(user_id),
        "auth_method": OIDC_AUTH_METHOD,
        "foundry_external_system_id": None,
        "foundry_world_id": None,
        "foundry_claimed_actor_id": None,
        "campaign_id": None,
        "foundry_connection_id": None,
        "foundry_device_id": None,
        "foundry_scopes": None,
    }


# ---------------------------------------------------------------------------
# require_human_user_id — rejects a FoundrySystem credential outright
# (dnd_ai.api.campaigns/.campaign_invitations' own routes)
# ---------------------------------------------------------------------------


def test_require_human_user_id_rejects_a_foundrysystem_credential(
    client_factory: Callable[[], TestClient],
) -> None:
    # 401, not 403: the credential is rejected at get_authenticated_user_id
    # itself now, before require_human_user_id's own auth_method check —
    # the same-shaped, well-formed-but-unbound credential is enough here
    # since the point is that this route never even reaches that check.
    with client_factory() as client:
        response = client.get(
            "/test-oidc-only-user",
            headers={"Authorization": f"FoundrySystem {uuid.uuid4()}.some-key"},
        )
    assert response.status_code == 401


def test_require_human_user_id_accepts_an_oidc_token(
    keypair: RSAKeypair, client_factory: Callable[[], TestClient], postgres_engine: Engine
) -> None:
    subject = f"subject-{uuid.uuid4().hex[:8]}"
    with postgres_engine.connect() as setup_connection:
        user_id = make_user(setup_connection, "OIDC Only Tester")
        make_external_identity(setup_connection, user_id, issuer=_ISSUER, subject=subject)
        setup_connection.commit()

    token = make_signed_jwt(keypair, issuer=_ISSUER, audience=_AUDIENCE, subject=subject)
    with client_factory() as client:
        response = client.get("/test-oidc-only-user", headers=_bearer(token))
    assert response.status_code == 200
    assert response.json() == {"user_id": str(user_id)}


# ---------------------------------------------------------------------------
# FoundryAccess — the paired-device credential (Phase 11R workstream C,
# docs/PLAN.md §23.5). Mirrors the FoundrySystem section above; the two
# schemes are accepted side by side (see dnd_ai.api.auth's own docstring
# for why neither workstream removes the other).
# ---------------------------------------------------------------------------


def _grant_canon_edit(
    connection: Connection, *, campaign_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    """Grants user_id a role holding canon.edit in campaign_id — the same
    pre-seeded capability (migration 080) and make_role/.../make_membership_
    role setup tests/database/test_api_integration.py's own Foundry-adapter
    fixture already establishes for the legacy FoundrySystem credential."""
    membership_id = make_campaign_membership(connection, campaign_id, user_id)
    role_id = make_role(connection, campaign_id=campaign_id)
    canon_edit_id = lookup_id(connection, "security", "capabilities", "capability_id", "canon.edit")
    make_role_capability(connection, role_id, canon_edit_id)
    make_membership_role(connection, membership_id, role_id)


def _bind_foundry_access(
    postgres_engine: Engine,
    *,
    principal_user_name: str = "Paired GM",
    requested_scopes: frozenset[str] | set[str] = FOUNDRY_SCOPES,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID, str]:
    """Sets up one full pairing: a world, external system, campaign, and a
    canon.edit-holding membership (see _grant_canon_edit), then issues and
    consumes a pairing code. Returns (user_id, campaign_id,
    external_system_id, world_id, raw_access_token). `requested_scopes`
    defaults to the full closed vocabulary so most callers never need to
    think about scope at all; scope-enforcement tests below pass a
    narrower set explicitly."""
    with postgres_engine.connect() as setup_connection:
        world_id = make_world(setup_connection, slug=f"foundry-access-{uuid.uuid4().hex[:8]}")
        timeline_id = make_timeline(setup_connection, world_id)
        campaign_id = make_campaign(setup_connection, timeline_id, lifecycle_status_code="pending")
        external_system_id = make_external_system(setup_connection, world_id)
        user_id = make_user(setup_connection, principal_user_name)
        _grant_canon_edit(setup_connection, campaign_id=campaign_id, user_id=user_id)
        setup_connection.commit()

    issued = create_foundry_pairing_code(
        postgres_engine,
        requesting_user_id=user_id,
        campaign_id=campaign_id,
        external_system_id=external_system_id,
        requested_scopes=requested_scopes,
    )
    consumed = consume_foundry_pairing_code(
        postgres_engine,
        raw_code=issued.raw_code,
        foundry_user_id=f"foundry-user-{uuid.uuid4().hex[:8]}",
        foundry_origin="https://foundry.example.test",
        device_label="test-device",
    )
    return user_id, campaign_id, external_system_id, world_id, consumed.raw_access_token


def _foundry_access_headers(raw_access_token: str) -> dict[str, str]:
    return {"Authorization": f"FoundryAccess {raw_access_token}"}


def test_a_valid_foundryaccess_credential_resolves_the_bound_principal_and_scope(
    client_factory: Callable[[], TestClient], postgres_engine: Engine
) -> None:
    user_id, campaign_id, external_system_id, world_id, raw_access_token = _bind_foundry_access(
        postgres_engine
    )

    with client_factory() as client:
        response = client.get(
            "/test-authenticated-principal", headers=_foundry_access_headers(raw_access_token)
        )
    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == str(user_id)
    assert body["auth_method"] == FOUNDRY_ACCESS_AUTH_METHOD
    assert body["foundry_external_system_id"] == str(external_system_id)
    assert body["foundry_world_id"] == str(world_id)
    assert body["campaign_id"] == str(campaign_id)
    assert body["foundry_connection_id"] is not None
    assert body["foundry_device_id"] is not None
    assert body["foundry_claimed_actor_id"] is None
    assert body["foundry_scopes"] == sorted(FOUNDRY_SCOPES)


def test_an_unknown_foundryaccess_token_is_rejected(
    client_factory: Callable[[], TestClient],
) -> None:
    with client_factory() as client:
        response = client.get(
            "/test-authenticated-user", headers=_foundry_access_headers("not-a-real-token")
        )
    assert response.status_code == 401


def test_an_empty_foundryaccess_credential_is_rejected(
    client_factory: Callable[[], TestClient],
) -> None:
    with client_factory() as client:
        response = client.get(
            "/test-authenticated-user", headers={"Authorization": "FoundryAccess "}
        )
    assert response.status_code == 401


def test_a_revoked_foundryaccess_device_is_rejected(
    client_factory: Callable[[], TestClient], postgres_engine: Engine
) -> None:
    user_id, _campaign_id, _system, _world, raw_access_token = _bind_foundry_access(postgres_engine)
    with client_factory() as client:
        ok_response = client.get(
            "/test-authenticated-user", headers=_foundry_access_headers(raw_access_token)
        )
    assert ok_response.status_code == 200

    with postgres_engine.begin() as connection:
        device_id = connection.execute(
            text(
                "SELECT fd.foundry_device_id FROM security.foundry_devices fd "
                "JOIN security.foundry_connections fc "
                "  ON fc.foundry_connection_id = fd.foundry_connection_id "
                "WHERE fc.user_id = :user"
            ),
            {"user": user_id},
        ).scalar()
        revoke_foundry_device(connection, foundry_device_id=device_id, revoked_by_user_id=user_id)

    with client_factory() as client:
        response = client.get(
            "/test-authenticated-user", headers=_foundry_access_headers(raw_access_token)
        )
    assert response.status_code == 401


def test_a_revoked_foundryaccess_connection_is_rejected(
    client_factory: Callable[[], TestClient], postgres_engine: Engine
) -> None:
    user_id, _campaign_id, _system, _world, raw_access_token = _bind_foundry_access(postgres_engine)
    with postgres_engine.begin() as connection:
        connection_id = connection.execute(
            text(
                "SELECT foundry_connection_id FROM security.foundry_connections WHERE user_id = :user"
            ),
            {"user": user_id},
        ).scalar()
        revoke_foundry_connection(
            connection, foundry_connection_id=connection_id, revoked_by_user_id=user_id
        )

    with client_factory() as client:
        response = client.get(
            "/test-authenticated-user", headers=_foundry_access_headers(raw_access_token)
        )
    assert response.status_code == 401


def test_require_human_user_id_rejects_a_foundryaccess_credential(
    client_factory: Callable[[], TestClient], postgres_engine: Engine
) -> None:
    _, _, _, _, raw_access_token = _bind_foundry_access(postgres_engine)
    with client_factory() as client:
        response = client.get(
            "/test-oidc-only-user", headers=_foundry_access_headers(raw_access_token)
        )
    assert response.status_code == 403


def test_foundry_access_gate_rejects_when_not_opted_in(
    client_factory: Callable[[], TestClient], postgres_engine: Engine
) -> None:
    _, campaign_id, _, _, raw_access_token = _bind_foundry_access(postgres_engine)
    with client_factory() as client:
        response = client.get(
            f"/test-campaigns/{campaign_id}/foundry-access-not-opted-in",
            headers=_foundry_access_headers(raw_access_token),
        )
    assert response.status_code == 403


def test_foundry_access_gate_accepts_its_own_paired_campaign(
    client_factory: Callable[[], TestClient], postgres_engine: Engine
) -> None:
    _, campaign_id, _, _, raw_access_token = _bind_foundry_access(postgres_engine)
    with client_factory() as client:
        response = client.get(
            f"/test-campaigns/{campaign_id}/foundry-access-gate",
            headers=_foundry_access_headers(raw_access_token),
        )
    assert response.status_code == 200
    assert response.json() == {"campaign_id": str(campaign_id)}


def test_foundry_access_gate_rejects_a_different_campaign(
    client_factory: Callable[[], TestClient], postgres_engine: Engine
) -> None:
    # The bound user also holds canon.edit in the *other* campaign — proving
    # the exact-campaign_id check itself blocks this, not merely the
    # ordinary membership/capability check every principal type already
    # goes through (which would trivially also reject a campaign this user
    # has no membership in at all).
    user_id, _own_campaign_id, _, _, raw_access_token = _bind_foundry_access(postgres_engine)
    with postgres_engine.connect() as setup_connection:
        other_world_id = make_world(
            setup_connection, slug=f"foundry-access-other-{uuid.uuid4().hex[:8]}"
        )
        other_timeline_id = make_timeline(setup_connection, other_world_id)
        other_campaign_id = make_campaign(
            setup_connection, other_timeline_id, lifecycle_status_code="pending"
        )
        _grant_canon_edit(setup_connection, campaign_id=other_campaign_id, user_id=user_id)
        setup_connection.commit()

    with client_factory() as client:
        response = client.get(
            f"/test-campaigns/{other_campaign_id}/foundry-access-gate",
            headers=_foundry_access_headers(raw_access_token),
        )
    # Indistinguishable from "no membership" — see dnd_ai.api.access's own
    # docstring for the non-disclosing reasoning this mirrors.
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Foundry scope enforcement (Workstream 11R High-severity finding 1):
# `/test-campaigns/{campaign_id}/foundry-access-gate` requires foundry_
# scope="combat_sync"; its sibling `/test-campaigns/{campaign_id}/foundry-
# access-scope-gate` requires "character_state_sync" — two routes gating
# the identical canon.edit capability but different Foundry scopes, so a
# connection's own granted scopes are what determines which it can reach,
# never the underlying application capability alone.
# ---------------------------------------------------------------------------


def test_a_token_with_only_encounter_read_cannot_reach_a_combat_sync_gated_route(
    client_factory: Callable[[], TestClient], postgres_engine: Engine
) -> None:
    _, campaign_id, _, _, raw_access_token = _bind_foundry_access(
        postgres_engine, requested_scopes=frozenset({"encounter_read"})
    )
    with client_factory() as client:
        response = client.get(
            f"/test-campaigns/{campaign_id}/foundry-access-gate",
            headers=_foundry_access_headers(raw_access_token),
        )
    assert response.status_code == 403


def test_a_token_with_only_encounter_read_cannot_reach_a_character_state_sync_gated_route(
    client_factory: Callable[[], TestClient], postgres_engine: Engine
) -> None:
    _, campaign_id, _, _, raw_access_token = _bind_foundry_access(
        postgres_engine, requested_scopes=frozenset({"encounter_read"})
    )
    with client_factory() as client:
        response = client.get(
            f"/test-campaigns/{campaign_id}/foundry-access-scope-gate",
            headers=_foundry_access_headers(raw_access_token),
        )
    assert response.status_code == 403


def test_a_token_with_only_combat_sync_cannot_reach_a_character_state_sync_gated_route(
    client_factory: Callable[[], TestClient], postgres_engine: Engine
) -> None:
    # combat_sync and character_state_sync are two distinct scopes in the
    # closed vocabulary — holding one must not implicitly grant the other.
    _, campaign_id, _, _, raw_access_token = _bind_foundry_access(
        postgres_engine, requested_scopes=frozenset({"combat_sync"})
    )
    with client_factory() as client:
        combat_response = client.get(
            f"/test-campaigns/{campaign_id}/foundry-access-gate",
            headers=_foundry_access_headers(raw_access_token),
        )
        character_state_response = client.get(
            f"/test-campaigns/{campaign_id}/foundry-access-scope-gate",
            headers=_foundry_access_headers(raw_access_token),
        )
    assert combat_response.status_code == 200
    assert character_state_response.status_code == 403


def test_a_token_with_exactly_the_required_scope_succeeds(
    client_factory: Callable[[], TestClient], postgres_engine: Engine
) -> None:
    _, campaign_id, _, _, raw_access_token = _bind_foundry_access(
        postgres_engine, requested_scopes=frozenset({"character_state_sync"})
    )
    with client_factory() as client:
        response = client.get(
            f"/test-campaigns/{campaign_id}/foundry-access-scope-gate",
            headers=_foundry_access_headers(raw_access_token),
        )
    assert response.status_code == 200


def test_a_valid_scope_without_the_required_application_capability_is_still_denied(
    client_factory: Callable[[], TestClient], postgres_engine: Engine
) -> None:
    # Scope is an ADDITIONAL restriction, never a replacement for the
    # ordinary campaign-capability check — a connection granted every
    # scope in the closed vocabulary still cannot reach a canon.edit-gated
    # route if the bound platform user itself never held canon.edit.
    with postgres_engine.connect() as setup_connection:
        world_id = make_world(setup_connection, slug=f"foundry-access-nocap-{uuid.uuid4().hex[:8]}")
        timeline_id = make_timeline(setup_connection, world_id)
        campaign_id = make_campaign(setup_connection, timeline_id, lifecycle_status_code="pending")
        external_system_id = make_external_system(setup_connection, world_id)
        user_id = make_user(setup_connection, "Capless Paired User")
        # Membership with no role/capability at all — deliberately never
        # calls _grant_canon_edit.
        make_campaign_membership(setup_connection, campaign_id, user_id)
        setup_connection.commit()

    issued = create_foundry_pairing_code(
        postgres_engine,
        requesting_user_id=user_id,
        campaign_id=campaign_id,
        external_system_id=external_system_id,
        requested_scopes=FOUNDRY_SCOPES,
    )
    consumed = consume_foundry_pairing_code(
        postgres_engine,
        raw_code=issued.raw_code,
        foundry_user_id=f"foundry-user-{uuid.uuid4().hex[:8]}",
        foundry_origin="https://foundry.example.test",
        device_label="test-device",
    )

    with client_factory() as client:
        response = client.get(
            f"/test-campaigns/{campaign_id}/foundry-access-gate",
            headers=_foundry_access_headers(consumed.raw_access_token),
        )
    assert response.status_code == 403


def test_removing_a_scope_from_the_connection_affects_the_very_next_request(
    client_factory: Callable[[], TestClient], postgres_engine: Engine
) -> None:
    # foundry_scopes is resolved fresh from security.foundry_connections.
    # granted_scopes on every request (dnd_ai.domain.foundry_pairing.
    # resolve_foundry_access_principal's own docstring) — never cached, and
    # never frozen onto the access-token row. Narrowing a connection's
    # granted scopes (here, simulating an administrative scope change
    # directly at the data level, since no dedicated "edit scopes" command
    # exists yet — re-pairing with a narrower requested_scopes set upserts
    # the identical column in production) must take effect on the very next
    # request, even though the already-issued access token itself is
    # completely untouched and nowhere near its own expiry.
    _, campaign_id, _, _, raw_access_token = _bind_foundry_access(
        postgres_engine, requested_scopes=frozenset({"combat_sync", "character_state_sync"})
    )

    with client_factory() as client:
        before_response = client.get(
            f"/test-campaigns/{campaign_id}/foundry-access-scope-gate",
            headers=_foundry_access_headers(raw_access_token),
        )
    assert before_response.status_code == 200

    with postgres_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE security.foundry_connections SET granted_scopes = ARRAY['combat_sync'] "
                "WHERE campaign_id = :c"
            ),
            {"c": campaign_id},
        )

    with client_factory() as client:
        after_response = client.get(
            f"/test-campaigns/{campaign_id}/foundry-access-scope-gate",
            headers=_foundry_access_headers(raw_access_token),
        )
    assert after_response.status_code == 403


def test_local_session_and_oidc_principals_are_unaffected_by_foundry_scope_gates(
    keypair: RSAKeypair, client_factory: Callable[[], TestClient], postgres_engine: Engine
) -> None:
    # Neither auth method carries a foundry_scopes concept at all — the
    # scope check inside require_campaign_capability is gated entirely on
    # is_foundry_access, so an OIDC caller who otherwise holds canon.edit
    # in the campaign must reach a foundry_scope-gated route exactly as it
    # would reach any other canon.edit-gated route, unaffected by which
    # Foundry scope that route happens to declare.
    subject = f"subject-{uuid.uuid4().hex[:8]}"
    with postgres_engine.connect() as setup_connection:
        world_id = make_world(setup_connection, slug=f"foundry-access-oidc-{uuid.uuid4().hex[:8]}")
        timeline_id = make_timeline(setup_connection, world_id)
        campaign_id = make_campaign(setup_connection, timeline_id, lifecycle_status_code="pending")
        user_id = make_user(setup_connection, "OIDC GM Unaffected By Scope")
        make_external_identity(setup_connection, user_id, issuer=_ISSUER, subject=subject)
        _grant_canon_edit(setup_connection, campaign_id=campaign_id, user_id=user_id)
        setup_connection.commit()

    token = make_signed_jwt(keypair, issuer=_ISSUER, audience=_AUDIENCE, subject=subject)
    with client_factory() as client:
        response = client.get(
            f"/test-campaigns/{campaign_id}/foundry-access-gate", headers=_bearer(token)
        )
    assert response.status_code == 200
    assert response.json() == {"campaign_id": str(campaign_id)}
