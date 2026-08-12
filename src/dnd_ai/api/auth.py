"""OIDC bearer-token authentication wiring (docs/PLAN.md Phase 10
deliverables — "authentication verification"). `dnd_ai.domain.tokens` does
the framework-free signature/claims verification; this module is the
FastAPI-specific plumbing around it: the JWKS client singleton, header
extraction, and the request-scoped dependencies command/query endpoints
will eventually depend on.

`get_jwks_client()` mirrors `dnd_ai.api.deps.get_engine`'s shape exactly —
a process-wide singleton, lazily built, overridable wholesale in tests via
`app.dependency_overrides`. It wraps `jwt.PyJWKClient`, which fetches a
JWKS document over plain `urllib` (no new runtime HTTP-client dependency)
and caches the fetched key set for `lifespan` seconds — routine key
rotation on the identity-provider side is picked up automatically without
a fetch on every request.

Deliberately out of scope here: updating `security.external_identities.
last_authenticated_at`/`.claims_snapshot` on a successful verification.
That is a write with its own atomicity and audit shape (CLAUDE.md rule 6)
and belongs in a dedicated login/session-establishment command later —
turning every authenticated request into an implicit write here would be
both inconsistent with that rule and unnecessary write load for a bare
verification dependency.
"""

import uuid
from typing import Annotated

import jwt
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from fastapi import Depends, Header
from sqlalchemy import Connection

from dnd_ai.config import settings
from dnd_ai.domain.access import resolve_user_by_external_identity
from dnd_ai.domain.tokens import VerifiedTokenClaims, verify_bearer_token

from .deps import get_connection
from .errors import UnauthorizedError

_jwks_client: jwt.PyJWKClient | None = None

# 5 minutes — long enough that routine per-request traffic never refetches
# the JWKS document, short enough that a rotated signing key is picked up
# promptly without restarting the process.
_JWKS_CACHE_LIFESPAN_SECONDS = 300


def get_jwks_client() -> jwt.PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        # config._require_oidc_settings_in_production guarantees this is
        # populated in production; a None here outside production is a
        # deployment/config defect (an auth-requiring route was reached
        # without OIDC configured), not a client-facing failure — the
        # AssertionError surfaces as the generic 500 contract in
        # api.errors, exactly like any other unclassified server defect.
        assert settings.oidc_jwks_url is not None
        _jwks_client = jwt.PyJWKClient(
            settings.oidc_jwks_url,
            cache_keys=True,
            lifespan=_JWKS_CACHE_LIFESPAN_SECONDS,
        )
    return _jwks_client


def dispose_jwks_client() -> None:
    """Called from the app's lifespan shutdown, mirroring
    `dnd_ai.api.deps.dispose_engine`. Tests that override `get_jwks_client`
    manage their own client's lifetime and never touch this."""
    global _jwks_client
    _jwks_client = None


def get_verified_token_claims(
    jwks_client: Annotated[jwt.PyJWKClient, Depends(get_jwks_client)],
    authorization: Annotated[str | None, Header()] = None,
) -> VerifiedTokenClaims:
    """Extracts and verifies the `Authorization: Bearer <token>` header.

    A missing or malformed header raises `UnauthorizedError` directly —
    that is a pure HTTP-layer concern, not something
    `dnd_ai.domain.tokens` (which never sees HTTP headers) should know
    about. An otherwise well-formed but invalid token (bad signature,
    wrong issuer/audience, expired, ...) raises `dnd_ai.domain.errors.
    AuthenticationError` from `verify_bearer_token` itself, which
    `dnd_ai.api.errors`' generic `SafeMessageError` handler already maps
    to the identical 401 response — no per-route wiring needed for that
    case."""
    if authorization is None:
        raise UnauthorizedError()
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise UnauthorizedError()

    assert settings.oidc_issuer is not None
    assert settings.oidc_audience is not None

    def get_signing_key(kid: str) -> RSAPublicKey:
        key = jwks_client.get_signing_key(kid).key
        # verify_bearer_token has already rejected any token whose header
        # `alg` isn't RS256 before this is ever called, but a misconfigured
        # JWKS (e.g. an EC or HMAC key under the matching kid) is still
        # possible — fail the same way an unresolvable kid does, not with
        # an unrelated type error surfacing from jwt.decode() itself.
        if not isinstance(key, RSAPublicKey):
            raise TypeError(f"JWKS key for kid={kid!r} is not an RSA public key")
        return key

    return verify_bearer_token(
        token,
        issuer=settings.oidc_issuer,
        audience=settings.oidc_audience,
        get_signing_key=get_signing_key,
    )


def get_authenticated_user_id(
    claims: Annotated[VerifiedTokenClaims, Depends(get_verified_token_claims)],
    connection: Annotated[Connection, Depends(get_connection)],
) -> uuid.UUID:
    """Resolves a verified token to the `security.users` row linked to its
    `(issuer, subject)` pair, via the already-existing
    `dnd_ai.domain.access.resolve_user_by_external_identity`. Raises
    `UnauthorizedError` for an unknown or revoked identity — this
    dependency only establishes *who is making the request*; provisioning
    a new user on first login is a separate application command, per that
    function's own docstring, not something a read dependency does
    implicitly."""
    user_id = resolve_user_by_external_identity(
        connection, issuer=claims.issuer, subject=claims.subject
    )
    if user_id is None:
        raise UnauthorizedError()
    return user_id
