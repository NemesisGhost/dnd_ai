"""OIDC bearer-token authentication wiring (docs/PLAN.md Phase 10
deliverables — "authentication verification"). `dnd_ai.domain.tokens` does
the framework-free signature/claims verification; this module is the
FastAPI-specific plumbing around it: the JWKS client singleton, header
extraction, and the request-scoped dependencies command/query endpoints
will eventually depend on.

`get_jwks_client()` mirrors `dnd_ai.api.deps.get_engine`'s shape exactly —
a process-wide singleton, lazily built under a lock (see its own docstring
for why an unsynchronized lazy-init is its own race), overridable
wholesale in tests via `app.dependency_overrides`. It returns a
`_JWKSClient`, this module's own wrapper around `jwt.PyJWKClient`, not
that class directly — several of `PyJWKClient`'s own behaviors are unsafe
against a `kid` taken straight from an unauthenticated caller's bearer
token, or under ordinary concurrent request traffic:

1. `PyJWKClient.get_signing_key()` forces an *unconditional* network
   refetch of the JWKS document whenever the requested `kid` isn't in the
   currently cached set, with no rate limit and (by default) a 30-second
   timeout. A caller submitting many distinct bogus `kid`s can otherwise
   trigger one outbound identity-provider request — and tie up the
   handling worker for up to 30s — per bogus value. `_JWKSClient` bounds
   *forced* refreshes to at most one per
   `_JWKS_FORCED_REFRESH_COOLDOWN_SECONDS`, using a single shared
   timestamp (never a per-`kid` structure, so nothing here grows with how
   many distinct bogus `kid`s a caller submits) serialized with a lock,
   and lowers the network timeout to `_JWKS_FETCH_TIMEOUT_SECONDS`.
2. Neither `PyJWKClient` nor its `JWKSetCache` does any locking of its
   own (verified against the installed `jwt.jwks_client`/`jwt.jwk_set_cache`
   source, not assumed) — a cold or TTL-expired Tier-1 cache is exactly as
   unsynchronized as an unrecognized `kid` is: concurrent requests can each
   independently observe "no cached data" and each perform their own
   outbound fetch. `_JWKSClient.get_signing_key()` only ever reads the
   cache lock-free (`_peek_signing_keys()`, which can never itself trigger
   I/O); anything that might need to fetch — a cold/expired cache or an
   unresolved `kid` — goes through `self._lock`, which rechecks the cache
   immediately after acquiring it (double-checked locking) so a fetch a
   waiting peer already performed is reused instead of repeated. Ordinary
   cached-key verification (the common case) never touches the lock at
   all.
3. `PyJWKClient`'s optional per-key cache (`cache_keys=True`) is a plain
   LRU with **no time-based expiry** — once populated, a given `kid` keeps
   serving the same key material until evicted by LRU pressure or the
   process restarts, regardless of the JWKS-set cache's own `lifespan`.
   `_JWKSClient` never enables it (`cache_keys=False` on the underlying
   client): every lookup resolves against the Tier-1 JWKS-*set* cache,
   which does expire on `lifespan`, so key material for any `kid` can
   never outlive that TTL (or this module's own forced-refresh cooldown)
   without a real refetch.

Deliberately out of scope here: updating `security.external_identities.
last_authenticated_at`/`.claims_snapshot` on a successful verification.
That is a write with its own atomicity and audit shape (CLAUDE.md rule 6)
and belongs in a dedicated login/session-establishment command later —
turning every authenticated request into an implicit write here would be
both inconsistent with that rule and unnecessary write load for a bare
verification dependency.
"""

import threading
import time
import uuid
from typing import Annotated, cast

import jwt
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from fastapi import Depends, Header
from sqlalchemy import Connection

from dnd_ai.config import settings
from dnd_ai.domain.access import resolve_user_by_external_identity
from dnd_ai.domain.tokens import VerifiedTokenClaims, verify_bearer_token

from .deps import get_connection
from .errors import UnauthorizedError

# Tier-1 (JWKS-set) cache TTL — long enough that routine per-request traffic
# never refetches the document, short enough that a rotated signing key is
# picked up promptly without restarting the process.
_JWKS_SET_LIFESPAN_SECONDS = 300.0

# Bounds how often an unrecognized `kid` may force a network refetch of the
# JWKS document (see this module's docstring, point 1). Deliberately much
# shorter than the Tier-1 lifespan above — a legitimately rotated key still
# becomes usable quickly — but long enough to cap the outbound request rate
# to the identity provider at one fetch per window, no matter how many
# distinct bogus `kid`s a caller submits within it.
_JWKS_FORCED_REFRESH_COOLDOWN_SECONDS = 30.0

# 5s, not PyJWKClient's 30s default. A JWKS document is a small, close-to-
# static fetch a healthy identity provider answers in well under a second;
# capping the wait bounds how long a single authentication request (and the
# worker handling it) can be tied up if the endpoint is slow or unreachable.
_JWKS_FETCH_TIMEOUT_SECONDS = 5.0


class _JWKSClient:
    """Wraps `jwt.PyJWKClient` to close the gaps described in this
    module's docstring. Never raises anything but what the underlying
    `jwt.PyJWKClient` call itself raises (`jwt.exceptions.PyJWTError` and
    its subclasses) — `get_signing_key` returns a resolved key or raises;
    it never returns a placeholder, so a caller (`dnd_ai.domain.tokens.
    verify_bearer_token`) that treats any exception here as an
    authentication failure fails closed automatically."""

    def __init__(
        self,
        jwks_url: str,
        *,
        lifespan: float = _JWKS_SET_LIFESPAN_SECONDS,
        forced_refresh_cooldown: float = _JWKS_FORCED_REFRESH_COOLDOWN_SECONDS,
        timeout: float = _JWKS_FETCH_TIMEOUT_SECONDS,
    ) -> None:
        self._client = jwt.PyJWKClient(
            jwks_url,
            cache_keys=False,
            cache_jwk_set=True,
            lifespan=lifespan,
            timeout=timeout,
        )
        self._forced_refresh_cooldown = forced_refresh_cooldown
        self._lock = threading.Lock()
        self._last_forced_refresh: float | None = None

    def get_signing_key(self, kid: str) -> RSAPublicKey:
        signing_keys = self._peek_signing_keys()
        matched = jwt.PyJWKClient.match_kid(signing_keys, kid) if signing_keys is not None else None
        if matched is None:
            matched = self._resolve_under_lock(kid)
        key = matched.key
        # verify_bearer_token has already rejected any token whose header
        # `alg` isn't RS256 before this is ever called, but a misconfigured
        # JWKS (e.g. an EC or HMAC key under the matching kid) is still
        # possible — fail the same way an unresolvable kid does, not with
        # an unrelated type error surfacing from jwt.decode() itself.
        if not isinstance(key, RSAPublicKey):
            raise TypeError(f"JWKS key for kid={kid!r} is not an RSA public key")
        return key

    def _peek_signing_keys(self) -> list[jwt.PyJWK] | None:
        """Read-only: the currently cached, unexpired signing keys, or
        `None` if the Tier-1 JWKS-set cache is empty or expired. Never
        performs network I/O under any circumstance — safe to call
        without `self._lock`, and safe to treat as a consistent snapshot,
        unlike `PyJWKClient.get_signing_keys()`/`.get_jwk_set()`
        themselves, which fetch as a side effect of a cache miss.

        Deliberately does not call `PyJWKClient.get_jwk_set(refresh=False)`
        — that method fetches on its own whenever `JWKSetCache.get()`
        returns `None`, which is exactly the unsynchronized-fetch
        behavior this wrapper exists to avoid on any lock-free path. This
        reimplements only its cache-*hit* half: `JWKSetCache.get()`
        returns the raw dict `fetch_data()` originally cached (verified
        against the installed `jwt.jwks_client`/`jwt.jwk_set_cache`
        source — despite `PyJWTSetWithTimestamp`'s own type hint saying
        `PyJWKSet`), which still needs `jwt.PyJWKSet.from_dict()` to
        become `PyJWK` objects; `PyJWKClient` itself re-parses on every
        call, cache hit or not, so doing the same here costs nothing
        extra relative to the codepath this replaces."""
        cache = self._client.jwk_set_cache
        if cache is None:
            return None
        # jwt.JWKSetCache.get()'s own declared return type is
        # Optional[PyJWKSet], but per the docstring above it actually
        # returns the raw dict fetch_data() cached — a type-hint/runtime
        # mismatch in the installed library itself, not a mistake here.
        # cast() tells mypy to trust the verified runtime behavior rather
        # than the (incorrect) stub, which otherwise treats the isinstance
        # check below as an impossible PyJWKSet/dict overlap.
        data = cast(object, cache.get())
        if data is None or not isinstance(data, dict):
            return None
        try:
            jwk_set = jwt.PyJWKSet.from_dict(data)
        except jwt.PyJWKSetError:
            return None
        return [key for key in jwk_set.keys if key.public_key_use in ("sig", None) and key.key_id]

    def _resolve_under_lock(self, kid: str) -> jwt.PyJWK:
        """Reached only on a cache-read miss (cold, TTL-expired, or
        genuinely missing `kid`) — every path that might need to perform
        network I/O funnels through here, all under `self._lock`."""
        with self._lock:
            # Double-checked locking: recheck now that we hold the lock —
            # a peer thread may have already fetched or refreshed while
            # this thread was waiting for it.
            signing_keys = self._peek_signing_keys()
            if signing_keys is not None:
                matched = jwt.PyJWKClient.match_kid(signing_keys, kid)
                if matched is not None:
                    return matched
                # Cache is warm but doesn't contain kid — gate behind the
                # forced-refresh cooldown (finding 1's DoS bound).
                return self._forced_refresh_and_match_locked(kid)
            # Cache is cold or TTL-expired for every thread reaching here.
            # A plain (non-forced) fetch happens at most once per
            # contending group of threads — bounded by holding the lock
            # for its duration, not gated by the forced-refresh cooldown,
            # since this path is never attacker-rate-driven (it's already
            # bounded by `lifespan`, and PyJWKClient.get_signing_keys()
            # below is itself what performs the fetch; the lock is what
            # keeps concurrent callers to one call instead of one each).
            signing_keys = self._client.get_signing_keys()
            matched = jwt.PyJWKClient.match_kid(signing_keys, kid)
            if matched is not None:
                return matched
            return self._forced_refresh_and_match_locked(kid)

    def _forced_refresh_and_match_locked(self, kid: str) -> jwt.PyJWK:
        """Caller must already hold `self._lock`."""
        now = time.monotonic()
        if (
            self._last_forced_refresh is None
            or now - self._last_forced_refresh >= self._forced_refresh_cooldown
        ):
            try:
                signing_keys = self._client.get_signing_keys(refresh=True)
            finally:
                # Advance the cooldown regardless of outcome. A failed
                # fetch must not let the very next request retry
                # immediately — that would defeat the rate bound just as
                # surely as a successful one that still misses, and would
                # let a struggling/unreachable identity provider be
                # hammered on every incoming request.
                self._last_forced_refresh = time.monotonic()
        else:
            # Still cooling down: reuse whatever the Tier-1 cache
            # currently holds — possibly already refreshed by a peer
            # request that raced us for the lock — rather than fetching
            # again.
            signing_keys = self._client.get_signing_keys()
        matched = jwt.PyJWKClient.match_kid(signing_keys, kid)
        if matched is None:
            raise jwt.PyJWKClientError(f"Unable to find a signing key that matches: {kid!r}")
        return matched


_jwks_client: _JWKSClient | None = None

# Guards lazy construction of the module-wide _jwks_client singleton.
# Without this, concurrent first callers could each observe
# `_jwks_client is None` before any of them assigns it, constructing
# multiple independent _JWKSClient instances — each with its own cache,
# lock, and forced-refresh cooldown, defeating every guarantee above for
# whichever requests happen to land on the "losing" instances.
_jwks_client_init_lock = threading.Lock()


def get_jwks_client() -> _JWKSClient:
    global _jwks_client
    if _jwks_client is not None:
        return _jwks_client
    with _jwks_client_init_lock:
        # Double-checked locking: another thread may have already
        # constructed and published the singleton while this thread was
        # waiting for the lock.
        if _jwks_client is None:
            # config._require_oidc_settings_in_production guarantees this
            # is populated in production; a None here outside production
            # is a deployment/config defect (an auth-requiring route was
            # reached without OIDC configured), not a client-facing
            # failure — the AssertionError surfaces as the generic 500
            # contract in api.errors, exactly like any other unclassified
            # server defect.
            assert settings.oidc_jwks_url is not None
            _jwks_client = _JWKSClient(settings.oidc_jwks_url)
        return _jwks_client


def dispose_jwks_client() -> None:
    """Called from the app's lifespan shutdown, mirroring
    `dnd_ai.api.deps.dispose_engine`. Tests that override `get_jwks_client`
    manage their own client's lifetime and never touch this."""
    global _jwks_client
    with _jwks_client_init_lock:
        _jwks_client = None


def get_verified_token_claims(
    jwks_client: Annotated[_JWKSClient, Depends(get_jwks_client)],
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

    return verify_bearer_token(
        token,
        issuer=settings.oidc_issuer,
        audience=settings.oidc_audience,
        get_signing_key=jwks_client.get_signing_key,
    )


def get_authenticated_user_id(
    claims: Annotated[VerifiedTokenClaims, Depends(get_verified_token_claims)],
    connection: Annotated[Connection, Depends(get_connection)],
) -> uuid.UUID:
    """Resolves a verified token to the `security.users` row linked to its
    `(issuer, subject)` pair, via the already-existing
    `dnd_ai.domain.access.resolve_user_by_external_identity`. Raises
    `UnauthorizedError` for an unknown or revoked identity, or one linked
    to a user without an active lifecycle status — this dependency only
    establishes *who is making the request*; provisioning a new user on
    first login is a separate application command, per that function's
    own docstring, not something a read dependency does implicitly."""
    user_id = resolve_user_by_external_identity(
        connection, issuer=claims.issuer, subject=claims.subject
    )
    if user_id is None:
        raise UnauthorizedError()
    return user_id
