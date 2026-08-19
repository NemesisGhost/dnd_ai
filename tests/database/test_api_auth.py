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

from dnd_ai.api.app import create_app
from dnd_ai.api.auth import (
    get_authenticated_user_id,
    get_jwks_client,
    get_verified_token_claims,
    require_oidc_user_id,
)
from dnd_ai.api.deps import get_connection, get_engine
from dnd_ai.commands.integration import (
    UnlinkedFoundryPrincipalError,
    issue_foundry_system_key,
    link_foundry_identity,
)
from dnd_ai.config import settings
from dnd_ai.domain.access import (
    FOUNDRY_SYSTEM_AUTH_METHOD,
    OIDC_AUTH_METHOD,
    AuthenticatedPrincipal,
    hash_foundry_system_key,
)
from dnd_ai.domain.tokens import VerifiedTokenClaims
from tests.factories import make_external_identity, make_external_system, make_user, make_world
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
    ) -> dict[str, str | None]:
        return {
            "user_id": str(principal.user_id),
            "auth_method": principal.auth_method,
            "foundry_external_system_id": (
                str(principal.foundry_external_system_id)
                if principal.foundry_external_system_id is not None
                else None
            ),
            "foundry_world_id": (
                str(principal.foundry_world_id) if principal.foundry_world_id is not None else None
            ),
            "foundry_claimed_actor_id": principal.foundry_claimed_actor_id,
        }

    @app.get("/test-oidc-only-user")
    def _oidc_only_user(
        user_id: Annotated[uuid.UUID, Depends(require_oidc_user_id)],
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
# get_authenticated_user_id — the FoundrySystem credential path
#
# Second Phase 11 workstream 2 security correction (docs/PLAN.md, `dnd_ai.
# domain.access.resolve_foundry_system_principal`'s own docstring have the
# full account): a FoundrySystem credential now authenticates as exactly
# the one platform principal it was bound to at issuance
# (`issue_foundry_system_key`'s new required `principal_foundry_user_id`
# argument) — never a caller-selected identity. `link_foundry_identity`
# must therefore run *before* `issue_foundry_system_key` in every test
# below (the reverse of this file's pre-correction ordering), and
# `X-Foundry-Actor-Id` (renamed from `X-Foundry-User-Id`) is sent only as
# optional, purely descriptive metadata — never required, never an
# authorization input.
# ---------------------------------------------------------------------------


def _foundry_headers(
    external_system_id: uuid.UUID, raw_key: str, claimed_actor_id: str | None = None
) -> dict[str, str]:
    headers = {"Authorization": f"FoundrySystem {external_system_id}.{raw_key}"}
    if claimed_actor_id is not None:
        headers["X-Foundry-Actor-Id"] = claimed_actor_id
    return headers


def _bind_foundry_key(
    postgres_engine: Engine,
    *,
    external_system_id: uuid.UUID,
    principal_user_name: str,
    foundry_user_id: str,
) -> tuple[uuid.UUID, str]:
    """Test helper mirroring the required real-world order: link a Foundry
    user id to a fresh platform user, then issue a credential bound to
    that exact Foundry user id. Returns (principal_user_id, raw_key)."""
    with postgres_engine.connect() as setup_connection:
        user_id = make_user(setup_connection, principal_user_name)
        setup_connection.commit()
    link_foundry_identity(
        postgres_engine,
        external_system_id=external_system_id,
        foundry_user_id=foundry_user_id,
        user_id=user_id,
    )
    key_result = issue_foundry_system_key(
        postgres_engine,
        external_system_id=external_system_id,
        principal_foundry_user_id=foundry_user_id,
    )
    assert key_result.principal_user_id == user_id
    return user_id, key_result.raw_key


def test_a_foundrysystem_credential_with_no_claimed_actor_id_still_authenticates(
    client_factory: Callable[[], TestClient], postgres_engine: Engine
) -> None:
    # X-Foundry-Actor-Id is optional metadata, not a required authorization
    # input — omitting it entirely must not change who the credential
    # authenticates as. This replaces the pre-correction behavior, where a
    # missing header was rejected outright because it was, at the time, the
    # only source of the authenticated identity.
    with postgres_engine.connect() as setup_connection:
        world_id = make_world(setup_connection, slug=f"foundry-auth-{uuid.uuid4().hex[:8]}")
        external_system_id = make_external_system(setup_connection, world_id)
        setup_connection.commit()
    user_id, raw_key = _bind_foundry_key(
        postgres_engine,
        external_system_id=external_system_id,
        principal_user_name="Foundry-Bound GM",
        foundry_user_id="gm-foundry-id",
    )

    with client_factory() as client:
        response = client.get(
            "/test-authenticated-user",
            headers=_foundry_headers(external_system_id, raw_key),
        )
    assert response.status_code == 200
    assert response.json() == {"user_id": str(user_id)}


@pytest.mark.parametrize(
    "credential",
    [
        "not-a-uuid.some-key",
        "no-separator-at-all",
        "",
    ],
)
def test_a_malformed_foundrysystem_credential_is_rejected(
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


def test_a_foundrysystem_credential_for_an_unknown_external_system_is_rejected(
    client_factory: Callable[[], TestClient],
) -> None:
    with client_factory() as client:
        response = client.get(
            "/test-authenticated-user",
            headers=_foundry_headers(uuid.uuid4(), "some-raw-key", "some-foundry-user"),
        )
    assert response.status_code == 401


def test_a_foundrysystem_credential_with_the_wrong_key_is_rejected(
    client_factory: Callable[[], TestClient], postgres_engine: Engine
) -> None:
    with postgres_engine.connect() as setup_connection:
        world_id = make_world(setup_connection, slug=f"foundry-auth-{uuid.uuid4().hex[:8]}")
        external_system_id = make_external_system(setup_connection, world_id)
        setup_connection.commit()
    _bind_foundry_key(
        postgres_engine,
        external_system_id=external_system_id,
        principal_user_name="Foundry-Bound GM",
        foundry_user_id="gm-foundry-id",
    )

    with client_factory() as client:
        response = client.get(
            "/test-authenticated-user",
            headers=_foundry_headers(external_system_id, "definitely-the-wrong-key"),
        )
    assert response.status_code == 401


def test_issuing_a_key_for_an_unlinked_foundry_user_is_rejected(
    postgres_engine: Engine,
) -> None:
    # Second Phase 11 workstream 2 correction: issuance itself now requires
    # an existing link_foundry_identity mapping — a GM cannot bind a
    # credential to a Foundry user id nobody has linked yet.
    with postgres_engine.connect() as setup_connection:
        world_id = make_world(setup_connection, slug=f"foundry-auth-{uuid.uuid4().hex[:8]}")
        external_system_id = make_external_system(setup_connection, world_id)
        setup_connection.commit()

    with pytest.raises(UnlinkedFoundryPrincipalError):
        issue_foundry_system_key(
            postgres_engine,
            external_system_id=external_system_id,
            principal_foundry_user_id="never-linked-user",
        )


def test_a_foundrysystem_credential_with_no_bound_principal_is_rejected(
    client_factory: Callable[[], TestClient], postgres_engine: Engine
) -> None:
    # A system_key_hash that somehow exists with no
    # system_key_principal_user_id (impossible through the ordinary
    # issue_foundry_system_key path now that issuance always binds
    # atomically, but reachable via direct data manipulation, e.g. a
    # pre-migration-092 row) must never fall back to any client-supplied
    # identity — the credential simply cannot authenticate until re-bound.
    with postgres_engine.connect() as setup_connection:
        world_id = make_world(setup_connection, slug=f"foundry-auth-{uuid.uuid4().hex[:8]}")
        external_system_id = make_external_system(setup_connection, world_id)
        setup_connection.commit()
    raw_key = "unbound-raw-key-" + uuid.uuid4().hex
    key_hash = hash_foundry_system_key(raw_key)
    with postgres_engine.begin() as setup_connection:
        setup_connection.execute(
            text(
                "UPDATE integration.external_systems SET system_key_hash = :hash "
                "WHERE external_system_id = :s"
            ),
            {"hash": key_hash, "s": external_system_id},
        )

    with client_factory() as client:
        response = client.get(
            "/test-authenticated-user",
            headers=_foundry_headers(external_system_id, raw_key, "anyone-at-all"),
        )
    assert response.status_code == 401


def test_a_foundrysystem_credential_for_an_inactive_external_system_is_rejected(
    client_factory: Callable[[], TestClient], postgres_engine: Engine
) -> None:
    with postgres_engine.connect() as setup_connection:
        world_id = make_world(setup_connection, slug=f"foundry-auth-{uuid.uuid4().hex[:8]}")
        external_system_id = make_external_system(setup_connection, world_id)
        setup_connection.commit()
    _, raw_key = _bind_foundry_key(
        postgres_engine,
        external_system_id=external_system_id,
        principal_user_name="Foundry-Bound GM",
        foundry_user_id="gm-foundry-id",
    )
    with postgres_engine.begin() as setup_connection:
        setup_connection.execute(
            text(
                "UPDATE integration.external_systems SET is_active = false "
                "WHERE external_system_id = :s"
            ),
            {"s": external_system_id},
        )

    with client_factory() as client:
        response = client.get(
            "/test-authenticated-user",
            headers=_foundry_headers(external_system_id, raw_key, "gm-foundry-id"),
        )
    assert response.status_code == 401


def test_a_foundrysystem_credential_for_an_inactive_bound_user_is_rejected(
    client_factory: Callable[[], TestClient], postgres_engine: Engine
) -> None:
    # Mirrors resolve_user_by_external_identity's own "linked but not
    # active" check — a deactivated bound principal must not keep
    # authenticating merely because the credential still names them.
    with postgres_engine.connect() as setup_connection:
        world_id = make_world(setup_connection, slug=f"foundry-auth-{uuid.uuid4().hex[:8]}")
        external_system_id = make_external_system(setup_connection, world_id)
        setup_connection.commit()
    user_id, raw_key = _bind_foundry_key(
        postgres_engine,
        external_system_id=external_system_id,
        principal_user_name="Foundry-Bound GM",
        foundry_user_id="gm-foundry-id",
    )
    with postgres_engine.begin() as setup_connection:
        inactive_status_id = setup_connection.execute(
            text("SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'inactive'")
        ).scalar_one()
        setup_connection.execute(
            text("UPDATE security.users SET lifecycle_status_id = :status WHERE user_id = :u"),
            {"status": inactive_status_id, "u": user_id},
        )

    with client_factory() as client:
        response = client.get(
            "/test-authenticated-user",
            headers=_foundry_headers(external_system_id, raw_key, "gm-foundry-id"),
        )
    assert response.status_code == 401


def test_a_valid_foundrysystem_credential_resolves_the_bound_principal(
    client_factory: Callable[[], TestClient], postgres_engine: Engine
) -> None:
    with postgres_engine.connect() as setup_connection:
        world_id = make_world(setup_connection, slug=f"foundry-auth-{uuid.uuid4().hex[:8]}")
        external_system_id = make_external_system(setup_connection, world_id)
        setup_connection.commit()
    user_id, raw_key = _bind_foundry_key(
        postgres_engine,
        external_system_id=external_system_id,
        principal_user_name="Foundry-Bound GM",
        foundry_user_id="gm-foundry-id",
    )

    with client_factory() as client:
        response = client.get(
            "/test-authenticated-user",
            headers=_foundry_headers(external_system_id, raw_key, "gm-foundry-id"),
        )
    assert response.status_code == 200
    assert response.json() == {"user_id": str(user_id)}


def test_rotating_the_foundry_system_key_invalidates_the_old_one(
    client_factory: Callable[[], TestClient], postgres_engine: Engine
) -> None:
    with postgres_engine.connect() as setup_connection:
        world_id = make_world(setup_connection, slug=f"foundry-auth-{uuid.uuid4().hex[:8]}")
        external_system_id = make_external_system(setup_connection, world_id)
        setup_connection.commit()
    user_id, old_raw_key = _bind_foundry_key(
        postgres_engine,
        external_system_id=external_system_id,
        principal_user_name="Foundry-Bound GM",
        foundry_user_id="gm-foundry-id",
    )

    new_key = issue_foundry_system_key(
        postgres_engine,
        external_system_id=external_system_id,
        principal_foundry_user_id="gm-foundry-id",
    )
    assert new_key.raw_key != old_raw_key
    assert new_key.principal_user_id == user_id

    with client_factory() as client:
        old_response = client.get(
            "/test-authenticated-user",
            headers=_foundry_headers(external_system_id, old_raw_key, "gm-foundry-id"),
        )
        new_response = client.get(
            "/test-authenticated-user",
            headers=_foundry_headers(external_system_id, new_key.raw_key, "gm-foundry-id"),
        )
    assert old_response.status_code == 401
    assert new_response.status_code == 200
    assert new_response.json() == {"user_id": str(user_id)}


def test_rotating_the_foundry_system_key_can_rebind_it_to_a_different_principal(
    client_factory: Callable[[], TestClient], postgres_engine: Engine
) -> None:
    # Explicit coverage for issue_foundry_system_key's own documented
    # rotate-and-rebind-in-one-call behavior: rotating a credential while
    # naming a different already-linked Foundry user id atomically hands
    # it to that new principal, and the old principal's own binding is
    # gone (the old raw key is dead either way — this proves the *new*
    # key genuinely authenticates as the *new* principal, not the old one).
    with postgres_engine.connect() as setup_connection:
        world_id = make_world(setup_connection, slug=f"foundry-auth-{uuid.uuid4().hex[:8]}")
        external_system_id = make_external_system(setup_connection, world_id)
        setup_connection.commit()
    _bind_foundry_key(
        postgres_engine,
        external_system_id=external_system_id,
        principal_user_name="Original Foundry-Bound GM",
        foundry_user_id="gm-foundry-id",
    )
    new_user_id, new_raw_key = _bind_foundry_key(
        postgres_engine,
        external_system_id=external_system_id,
        principal_user_name="Replacement Foundry-Bound GM",
        foundry_user_id="replacement-gm-foundry-id",
    )

    with client_factory() as client:
        response = client.get(
            "/test-authenticated-user",
            headers=_foundry_headers(external_system_id, new_raw_key, "replacement-gm-foundry-id"),
        )
    assert response.status_code == 200
    assert response.json() == {"user_id": str(new_user_id)}


def test_an_oidc_bearer_token_still_authenticates_when_the_foundry_path_exists(
    keypair: RSAKeypair, client_factory: Callable[[], TestClient], postgres_engine: Engine
) -> None:
    # Regression guard: adding the FoundrySystem branch must not change the
    # OIDC path's behavior for an ordinary Bearer token at all.
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
# Adversarial regression: a claimed X-Foundry-Actor-Id can never change, or
# select, who a FoundrySystem credential authenticates as. This is the
# direct proof of the Critical defect's fix — see dnd_ai.domain.access.
# resolve_foundry_system_principal's own docstring for the full attack this
# closes: a connected player who extracted the (world-shared, at the time)
# credential could previously name the GM's own visible Foundry user id and
# authenticate as the GM.
# ---------------------------------------------------------------------------


def test_a_credential_holder_cannot_authenticate_as_a_different_linked_user_by_naming_them(
    client_factory: Callable[[], TestClient], postgres_engine: Engine
) -> None:
    # Reproduces the exact attack the vulnerability report describes,
    # against the corrected design: bind a credential to one principal (a
    # stand-in for "a player" — the worst case, more permissive than this
    # MVP's actual GM-only issuance practice, since it proves the
    # *mechanism* rejects the attack regardless of who holds a real
    # credential), then have its holder claim to be a *different*,
    # separately linked user (a stand-in for "the GM") via
    # X-Foundry-Actor-Id. The response must resolve to the credential's own
    # bound principal, never the claimed one.
    with postgres_engine.connect() as setup_connection:
        world_id = make_world(setup_connection, slug=f"foundry-auth-{uuid.uuid4().hex[:8]}")
        external_system_id = make_external_system(setup_connection, world_id)
        setup_connection.commit()
    gm_user_id, _ = _bind_foundry_key(
        postgres_engine,
        external_system_id=external_system_id,
        principal_user_name="The Real GM",
        foundry_user_id="gm-foundry-id",
    )
    player_user_id, player_raw_key = _bind_foundry_key(
        postgres_engine,
        external_system_id=external_system_id,
        principal_user_name="An Ordinary Player",
        foundry_user_id="player-foundry-id",
    )
    assert gm_user_id != player_user_id

    with client_factory() as client:
        response = client.get(
            "/test-authenticated-user",
            # The player's own credential, claiming the GM's Foundry id.
            headers=_foundry_headers(external_system_id, player_raw_key, "gm-foundry-id"),
        )
    assert response.status_code == 200
    assert response.json() == {"user_id": str(player_user_id)}
    assert response.json()["user_id"] != str(gm_user_id)


@pytest.mark.parametrize(
    "claimed_actor_id",
    [
        "gm-foundry-id",  # the credential holder's own real claimed id
        "player-foundry-id",  # a different, separately linked user's id
        "completely-unlinked-nonexistent-id",  # not linked to anyone at all
        None,  # header omitted entirely
    ],
)
def test_changing_the_claimed_actor_id_never_changes_the_authenticated_principal(
    claimed_actor_id: str | None,
    client_factory: Callable[[], TestClient],
    postgres_engine: Engine,
) -> None:
    with postgres_engine.connect() as setup_connection:
        world_id = make_world(setup_connection, slug=f"foundry-auth-{uuid.uuid4().hex[:8]}")
        external_system_id = make_external_system(setup_connection, world_id)
        setup_connection.commit()
    gm_user_id, raw_key = _bind_foundry_key(
        postgres_engine,
        external_system_id=external_system_id,
        principal_user_name="The Real GM",
        foundry_user_id="gm-foundry-id",
    )
    # A second linked identity purely so "player-foundry-id" above names a
    # real, resolvable mapping rather than an accidentally-unlinked one.
    with postgres_engine.connect() as setup_connection:
        player_user_id = make_user(setup_connection, "An Ordinary Player")
        setup_connection.commit()
    link_foundry_identity(
        postgres_engine,
        external_system_id=external_system_id,
        foundry_user_id="player-foundry-id",
        user_id=player_user_id,
    )

    with client_factory() as client:
        response = client.get(
            "/test-authenticated-user",
            headers=_foundry_headers(external_system_id, raw_key, claimed_actor_id),
        )
    assert response.status_code == 200
    assert response.json() == {"user_id": str(gm_user_id)}


# ---------------------------------------------------------------------------
# get_authenticated_user_id — AuthenticatedPrincipal scope (Phase 11
# workstream 2 security correction)
# ---------------------------------------------------------------------------


def test_a_valid_foundrysystem_credential_carries_its_own_system_world_and_claimed_actor(
    client_factory: Callable[[], TestClient], postgres_engine: Engine
) -> None:
    # The whole point of the first correction: a FoundrySystem-authenticated
    # request must resolve to more than a bare user_id — it must carry
    # which external_system_id/world_id actually authenticated it, so
    # dnd_ai.api.access.require_campaign_capability can scope authorization
    # to that world rather than the linked user's entire membership graph.
    # foundry_claimed_actor_id (second correction) is carried too, but only
    # ever as descriptive metadata — see the adversarial tests above for
    # proof it never influences user_id.
    with postgres_engine.connect() as setup_connection:
        world_id = make_world(setup_connection, slug=f"foundry-auth-{uuid.uuid4().hex[:8]}")
        external_system_id = make_external_system(setup_connection, world_id)
        setup_connection.commit()
    user_id, raw_key = _bind_foundry_key(
        postgres_engine,
        external_system_id=external_system_id,
        principal_user_name="Foundry-Bound GM",
        foundry_user_id="gm-foundry-id",
    )

    with client_factory() as client:
        response = client.get(
            "/test-authenticated-principal",
            headers=_foundry_headers(external_system_id, raw_key, "gm-foundry-id"),
        )
    assert response.status_code == 200
    assert response.json() == {
        "user_id": str(user_id),
        "auth_method": FOUNDRY_SYSTEM_AUTH_METHOD,
        "foundry_external_system_id": str(external_system_id),
        "foundry_world_id": str(world_id),
        "foundry_claimed_actor_id": "gm-foundry-id",
    }


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
    }


# ---------------------------------------------------------------------------
# require_oidc_user_id — rejects a FoundrySystem credential outright
# (dnd_ai.api.campaigns/.campaign_invitations' own routes)
# ---------------------------------------------------------------------------


def test_require_oidc_user_id_rejects_a_foundrysystem_credential(
    client_factory: Callable[[], TestClient], postgres_engine: Engine
) -> None:
    with postgres_engine.connect() as setup_connection:
        world_id = make_world(setup_connection, slug=f"foundry-auth-{uuid.uuid4().hex[:8]}")
        external_system_id = make_external_system(setup_connection, world_id)
        setup_connection.commit()
    _, raw_key = _bind_foundry_key(
        postgres_engine,
        external_system_id=external_system_id,
        principal_user_name="Foundry-Bound GM",
        foundry_user_id="gm-foundry-id",
    )

    with client_factory() as client:
        response = client.get(
            "/test-oidc-only-user",
            headers=_foundry_headers(external_system_id, raw_key, "gm-foundry-id"),
        )
    assert response.status_code == 403


def test_require_oidc_user_id_accepts_an_oidc_token(
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
