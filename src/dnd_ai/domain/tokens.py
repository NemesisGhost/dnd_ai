"""Framework-free OIDC bearer-token verification (docs/architecture/
SYSTEM_ARCHITECTURE.md §5.4 — no HTTP or framework types here, the same
scoping `dnd_ai.domain.access` already uses; `dnd_ai.api.auth` is what
wires this into a FastAPI dependency).

`verify_bearer_token()` checks signature, issuer, audience, and expiry —
never anything less, and never trusts the token's own `alg` header claim
past confirming it says exactly `RS256`: `algorithms=["RS256"]` is always
passed explicitly to `jwt.decode()`, closing the classic `alg=none`/
algorithm-confusion class of JWT vulnerability (a token that claims a
different or absent algorithm is rejected before a signing key is even
resolved, not merely mismatched against the expected one after the fact).

The signing key itself is resolved through an injected `GetSigningKey`
callable (`kid -> RSAPublicKey`) rather than this module owning a JWKS
HTTP client directly. That keeps this module trivially unit-testable — a
fake resolver is just a dict lookup against a locally generated keypair,
no live identity provider or JWKS HTTP server required (the
"no-live-provider test strategy" `dnd_ai.api.app`'s own docstring named as
still-needed before this module existed) — and keeps JWKS fetching/caching
concerns (`dnd_ai.api.auth.get_jwks_client`, backed by `jwt.PyJWKClient`)
entirely in the API layer, where the rest of this codebase's request-scoped
singletons already live (`dnd_ai.api.deps.get_engine`).

Every failure mode below — a malformed token, an unresolvable `kid`, a bad
signature, a wrong issuer/audience, an expired token, or a missing
required claim — raises the single `dnd_ai.domain.errors.
AuthenticationError`. No other exception type escapes `verify_bearer_token`,
so a caller (`dnd_ai.api.auth.get_verified_token_claims`) never needs to
know which specific way a token was rejected; that generic-by-design
behavior already exists on `AuthenticationError` itself.
"""

from collections.abc import Callable
from dataclasses import dataclass

import jwt
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey

from .errors import AuthenticationError

#: Resolves a token's `kid` (key ID) header to the RSA public key that
#: should verify its signature. The production implementation
#: (`dnd_ai.api.auth`) adapts `jwt.PyJWKClient.get_signing_key(kid).key`;
#: tests inject a plain dict lookup against a locally generated keypair.
#: Any exception raised by this callable (unknown `kid`, JWKS fetch
#: failure, and so on) is treated identically to a verification failure.
GetSigningKey = Callable[[str], RSAPublicKey]

_ALLOWED_ALGORITHM = "RS256"
_DEFAULT_LEEWAY_SECONDS = 60


@dataclass(frozen=True)
class VerifiedTokenClaims:
    """The subset of a verified token's claims this codebase actually
    uses. `issuer`/`subject` together are the `(issuer, subject)` pair
    `dnd_ai.domain.access.resolve_user_by_external_identity` looks up
    against `security.external_identities`."""

    issuer: str
    subject: str
    email: str | None


def verify_bearer_token(
    token: str,
    *,
    issuer: str,
    audience: str,
    get_signing_key: GetSigningKey,
    leeway_seconds: int = _DEFAULT_LEEWAY_SECONDS,
) -> VerifiedTokenClaims:
    """Verify `token`'s signature, issuer, audience, and expiry, and return
    its claims. Raises `AuthenticationError` for every failure mode —
    a malformed token, an `alg` other than `RS256`, a missing or
    unresolvable `kid`, a bad signature, a wrong issuer/audience, an
    expired token, or a missing `exp`/`iss`/`sub` claim.

    `leeway_seconds` tolerates ordinary clock drift between this process
    and whatever issued the token (the default, 60 seconds, is a common
    OIDC-client convention, not a value derived from anything this
    codebase measured)."""
    try:
        header = jwt.get_unverified_header(token)
    except jwt.exceptions.InvalidTokenError as exc:
        raise AuthenticationError(f"malformed token: {exc}") from exc

    if header.get("alg") != _ALLOWED_ALGORITHM:
        raise AuthenticationError(
            f"unsupported token algorithm {header.get('alg')!r}; only "
            f"{_ALLOWED_ALGORITHM!r} is accepted"
        )

    kid = header.get("kid")
    if not isinstance(kid, str) or not kid:
        raise AuthenticationError("token header is missing a key ID (kid)")

    try:
        signing_key = get_signing_key(kid)
    except Exception as exc:
        raise AuthenticationError(f"could not resolve signing key for kid={kid!r}: {exc}") from exc

    try:
        payload = jwt.decode(
            token,
            key=signing_key,
            algorithms=[_ALLOWED_ALGORITHM],
            issuer=issuer,
            audience=audience,
            leeway=leeway_seconds,
            options={"require": ["exp", "iss", "sub"]},
        )
    except jwt.exceptions.InvalidTokenError as exc:
        raise AuthenticationError(f"token failed verification: {exc}") from exc

    subject = payload["sub"]
    resolved_issuer = payload["iss"]
    if not isinstance(subject, str) or not isinstance(resolved_issuer, str):
        raise AuthenticationError("token 'sub'/'iss' claims must be strings")

    email = payload.get("email")
    if email is not None and not isinstance(email, str):
        raise AuthenticationError("token 'email' claim must be a string when present")

    return VerifiedTokenClaims(issuer=resolved_issuer, subject=subject, email=email)
