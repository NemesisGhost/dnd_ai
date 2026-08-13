"""Test-only JWT minting utilities for the OIDC token-verification
workstream (`dnd_ai.domain.tokens`, `dnd_ai.api.auth`).

Kept separate from `tests/factories.py` (database-row builders only) since
nothing here touches a database — this is pure crypto/JWT construction, the
"no-live-provider test strategy" `dnd_ai.api.app`'s own docstring named as
still-needed: a locally generated RSA keypair stands in for an identity
provider, with no live IdP or JWKS HTTP server anywhere in the test suite.
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey


@dataclass(frozen=True)
class RSAKeypair:
    kid: str
    private_key: RSAPrivateKey
    public_key: RSAPublicKey


def generate_test_rsa_keypair(*, kid: str | None = None) -> RSAKeypair:
    """A fresh 2048-bit RSA keypair, distinct per call — enough to prove
    signature verification actually checks the key, not just that *some*
    key was present (e.g. `test_a_token_signed_by_a_different_key_is_rejected`
    generates a second keypair specifically to sign with the wrong one)."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return RSAKeypair(
        kid=kid or f"test-kid-{uuid.uuid4().hex[:8]}",
        private_key=private_key,
        public_key=private_key.public_key(),
    )


def make_signed_jwt(
    keypair: RSAKeypair,
    *,
    issuer: str = "https://test-idp.example",
    audience: str = "test-audience",
    subject: str = "test-subject",
    algorithm: str = "RS256",
    kid: str | None = None,
    expires_delta: timedelta = timedelta(minutes=5),
    issued_delta: timedelta = timedelta(0),
    extra_claims: Mapping[str, object] | None = None,
    omit_claims: tuple[str, ...] = (),
) -> str:
    """Mints a JWT signed with `keypair.private_key`. `kid` defaults to the
    keypair's own `kid` — pass a different value to simulate a token whose
    header names a key ID that isn't (or is no longer) in the resolver's
    key set. `omit_claims` drops a standard claim entirely, for exercising
    the `options={"require": [...]}` path in `verify_bearer_token`."""
    now = datetime.now(UTC) + issued_delta
    claims: dict[str, object] = {
        "iss": issuer,
        "aud": audience,
        "sub": subject,
        "iat": now,
        "exp": now + expires_delta,
    }
    if extra_claims:
        claims.update(extra_claims)
    for claim in omit_claims:
        claims.pop(claim, None)
    return jwt.encode(
        claims,
        key=keypair.private_key,
        algorithm=algorithm,
        headers={"kid": kid or keypair.kid},
    )
