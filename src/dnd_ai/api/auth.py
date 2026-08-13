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
3. A *failed* fetch — whether triggered by a cold cache, a TTL-expired
   one, or a forced refresh for an unrecognized `kid` — previously
   recorded no retry timer at all, so the lock only bounded *concurrent*
   fetch attempts, never *sequential* ones: once released, the very next
   request retried immediately, and every attempt could block for up to
   `_JWKS_FETCH_TIMEOUT_SECONDS`. Cache expiry is time-driven, but each
   retry attempt is triggered by an incoming request — an unauthenticated
   caller sending a steady stream of requests during an identity-provider
   outage could keep the network fetch happening on every single one of
   them, indefinitely. `_JWKSClient` now records a dedicated
   `_JWKS_FAILURE_RETRY_COOLDOWN_SECONDS` timer (`_last_failed_fetch`,
   deliberately its own timestamp — never conflated with the Tier-1 TTL
   or the forced-refresh cooldown above, each of which keeps its own
   precise invariant) on any failed attempt, gating every one of the
   fetch paths above uniformly. `PyJWKClient.fetch_data()` also writes a
   successful-at-the-transport-level-but-otherwise-unusable response
   (malformed JSON shape, an empty or unparseable key set) into the
   Tier-1 cache *before* `get_jwk_set()` ever validates it — left alone,
   that would keep "successfully" satisfying every cache read and failing
   the same parse for the rest of `lifespan`, so `_JWKSClient` evicts it
   immediately so the cooldown's eventual retry actually attempts a fresh
   fetch rather than re-reading the same poison. A connection-level
   failure (nothing was ever written to the cache) evicts nothing, so an
   older, still-valid cached entry survives an unrelated failed forced
   refresh exactly as before.
4. `PyJWKClient`'s optional per-key cache (`cache_keys=True`) is a plain
   LRU with **no time-based expiry** — once populated, a given `kid` keeps
   serving the same key material until evicted by LRU pressure or the
   process restarts, regardless of the JWKS-set cache's own `lifespan`.
   `_JWKSClient` never enables it (`cache_keys=False` on the underlying
   client): every lookup resolves against the Tier-1 JWKS-*set* cache,
   which does expire on `lifespan`, so key material for any `kid` can
   never outlive that TTL (or this module's own forced-refresh cooldown)
   without a real refetch.
5. `PyJWKClient.fetch_data()` calls `urllib.request.urlopen(request,
   timeout=self.timeout, context=self.ssl_context)` directly, with no
   constructor hook to supply a custom opener or redirect handler
   (verified against the installed `jwt.jwks_client` source). Python's
   default `urllib.request.HTTPRedirectHandler` follows a redirect to
   *any* scheme — including a downgrade from `https` to plain `http`, or
   to a URL carrying embedded credentials — with no restriction of its
   own. An HTTPS-configured JWKS endpoint that is (or becomes, via a
   compromised or misconfigured intermediary) willing to issue such a
   redirect could otherwise have its key-set fetch silently downgraded to
   an unencrypted, tamperable one, defeating `oidc_jwks_url`'s HTTPS-only
   requirement in production (`dnd_ai.config`) after the fact.
   `_JWKSClient` replaces `fetch_data()` with `_build_validating_fetch_
   data()`'s version, which validates both the initial request URL and
   every redirect target against the same `allowed_url_schemes` policy
   `dnd_ai.config` already enforces for the configured value
   (`OIDC_PRODUCTION_URL_SCHEMES`/`OIDC_LOCAL_URL_SCHEMES` — one shared
   source of truth for both), and rejects embedded credentials in either.
   A same-scheme, credential-free redirect is still followed — this is
   deliberately a validated pass-through, not a blanket "no redirects"
   rule, since a JWKS URL redirecting to a CDN-hosted copy of the same
   document is a legitimate, common deployment shape. Building a fresh
   `urllib.request.OpenerDirector` per call (via `build_opener()`, never
   `install_opener()`) keeps this scoped to JWKS fetches only — it never
   mutates process-wide `urllib` state that unrelated code elsewhere in
   the process might depend on.

Deliberately out of scope here: updating `security.external_identities.
last_authenticated_at`/`.claims_snapshot` on a successful verification.
That is a write with its own atomicity and audit shape (CLAUDE.md rule 6)
and belongs in a dedicated login/session-establishment command later —
turning every authenticated request into an implicit write here would be
both inconsistent with that rule and unnecessary write load for a bare
verification dependency.
"""

import json
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable
from typing import Annotated, cast
from urllib.parse import urlsplit

import jwt
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from fastapi import Depends, Header
from sqlalchemy import Connection

from dnd_ai.config import OIDC_LOCAL_URL_SCHEMES, OIDC_PRODUCTION_URL_SCHEMES, settings
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

# Bounds how often a fetch may be *retried* after it fails, regardless of
# which path triggered it (cold cache, TTL expiry, or a forced refresh for
# an unrecognized kid) — see this module's docstring, point 3. Deliberately
# a separate timer from both the Tier-1 lifespan and the forced-refresh
# cooldown above: this one governs retry pacing specifically after a
# failure, not routine expiry or unknown-kid rate-limiting, and the three
# must never be conflated into one timestamp.
_JWKS_FAILURE_RETRY_COOLDOWN_SECONDS = 30.0


class _JWKSTransportSecurityError(urllib.error.URLError):
    """Raised by `_validate_jwks_transport_url`/`_ValidatingRedirectHandler`
    when a JWKS fetch URL or redirect target violates the allowed-scheme
    or no-embedded-credentials policy (see this module's docstring, point
    5). A `URLError` subclass so it's caught by the same `except (URLError,
    TimeoutError)` clause `_build_validating_fetch_data()` already needs
    for ordinary connection failures, converting uniformly to `jwt.
    PyJWKClientConnectionError` — `_JWKSClient`'s failure-retry-cooldown
    and cache-eviction logic then treats a blocked downgrade exactly like
    any other transport-level failure: nothing gets cached, and the
    existing cooldown paces any retry."""


def _validate_jwks_transport_url(url: str, *, allowed_schemes: frozenset[str], what: str) -> None:
    """Shared by the initial-request check and every redirect hop in
    `_build_validating_fetch_data()` below. Deliberately narrower than
    `dnd_ai.config._validate_oidc_url` (no host/fragment/emptiness
    checks) — this runs on *every* fetch attempt, including a redirect
    target a remote server chose, so it only enforces what actually
    matters for transport safety: the scheme stays within policy, and no
    credentials are smuggled in."""
    parsed = urlsplit(url)
    if parsed.scheme.lower() not in allowed_schemes:
        raise _JWKSTransportSecurityError(
            f"refusing JWKS {what} with disallowed scheme {parsed.scheme!r}: {url!r}"
        )
    if parsed.username is not None or parsed.password is not None:
        raise _JWKSTransportSecurityError(
            f"refusing JWKS {what} containing embedded credentials: {url!r}"
        )


class _ValidatingRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Validates every redirect target against `allowed_schemes` before
    following it — Python's own `HTTPRedirectHandler` places no
    restriction on what scheme a redirect may point to. A same-scheme,
    credential-free redirect is still followed (delegates to `super()`)
    — this is a validated pass-through, not a blanket rejection; see this
    module's docstring, point 5, for why that's the deliberate choice."""

    def __init__(self, allowed_schemes: frozenset[str]) -> None:
        super().__init__()
        self._allowed_schemes = allowed_schemes

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> urllib.request.Request | None:
        _validate_jwks_transport_url(
            newurl, allowed_schemes=self._allowed_schemes, what="redirect target"
        )
        return super().redirect_request(req, fp, code, msg, headers, newurl)  # type: ignore[arg-type]


def _build_validating_fetch_data(
    client: jwt.PyJWKClient, *, allowed_schemes: frozenset[str]
) -> Callable[[], object]:
    """Returns a `fetch_data` replacement for `client`, closing this
    module's docstring point 5. Otherwise mirrors the installed `jwt.
    PyJWKClient.fetch_data()` exactly — including writing a successful
    fetch to `client.jwk_set_cache` and converting any `URLError`/
    `TimeoutError` (including this module's own `_JWKSTransportSecurityError`)
    into `jwt.PyJWKClientConnectionError` — so every other `_JWKSClient`
    behavior (failure-retry cooldown, cache eviction only on a
    validation-stage failure, ...) continues to apply unchanged; only how
    the network request itself is made, and which redirects it will
    follow, differs from the library default."""

    def fetch_data() -> object:
        try:
            _validate_jwks_transport_url(
                client.uri, allowed_schemes=allowed_schemes, what="fetch URL"
            )
            redirect_handler = _ValidatingRedirectHandler(allowed_schemes)
            handlers: list[urllib.request.BaseHandler] = [redirect_handler]
            if client.ssl_context is not None:
                handlers.append(urllib.request.HTTPSHandler(context=client.ssl_context))
            opener = urllib.request.build_opener(*handlers)
            request = urllib.request.Request(url=client.uri, headers=client.headers)
            with opener.open(request, timeout=client.timeout) as response:
                jwk_set = json.load(response)
        except (urllib.error.URLError, TimeoutError) as exc:
            if isinstance(exc, urllib.error.HTTPError):
                exc.close()
            raise jwt.PyJWKClientConnectionError(
                f'Fail to fetch data from the url, err: "{exc}"'
            ) from exc
        if client.jwk_set_cache is not None:
            client.jwk_set_cache.put(jwk_set)
        return jwk_set

    return fetch_data


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
        failure_retry_cooldown: float = _JWKS_FAILURE_RETRY_COOLDOWN_SECONDS,
        timeout: float = _JWKS_FETCH_TIMEOUT_SECONDS,
        monotonic: Callable[[], float] = time.monotonic,
        allowed_url_schemes: frozenset[str] = OIDC_PRODUCTION_URL_SCHEMES,
    ) -> None:
        self._client = jwt.PyJWKClient(
            jwks_url,
            cache_keys=False,
            cache_jwk_set=True,
            lifespan=lifespan,
            timeout=timeout,
        )
        # Replaces PyJWKClient's own fetch_data — see this module's
        # docstring, point 5, and _build_validating_fetch_data's own
        # docstring for why.
        self._client.fetch_data = _build_validating_fetch_data(  # type: ignore[method-assign]
            self._client, allowed_schemes=allowed_url_schemes
        )
        self._forced_refresh_cooldown = forced_refresh_cooldown
        self._failure_retry_cooldown = failure_retry_cooldown
        # Injectable so tests can advance time deterministically instead of
        # sleeping for real — see tests/unit/test_jwks_client.py.
        self._monotonic = monotonic
        self._lock = threading.Lock()
        self._last_forced_refresh: float | None = None
        self._last_failed_fetch: float | None = None

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
        signing_keys = [
            key for key in jwk_set.keys if key.public_key_use in ("sig", None) and key.key_id
        ]
        # An empty result (every cached key filtered out — no signing-use
        # key, or none with a kid) is exactly as unusable as an unparseable
        # response; treat it identically as "no cache" rather than a
        # distinct empty-but-cached state, so it's gated by the same
        # failure-retry cooldown instead of the unknown-kid one.
        return signing_keys or None

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
            # for its duration. This is *not* rate-driven by the Tier-1
            # `lifespan` alone the way it might first appear: cache expiry
            # is time-driven, but each *retry attempt* is triggered by an
            # incoming request, so a failed fetch here is exactly as
            # capable of being hammered by request volume as the unknown-
            # kid path below — `_fetch_signing_keys_locked` applies the
            # same failure-retry cooldown to both.
            signing_keys = self._fetch_signing_keys_locked(refresh=False)
            matched = jwt.PyJWKClient.match_kid(signing_keys, kid)
            if matched is not None:
                return matched
            return self._forced_refresh_and_match_locked(kid)

    def _forced_refresh_and_match_locked(self, kid: str) -> jwt.PyJWK:
        """Caller must already hold `self._lock`. Reached either straight
        from `_resolve_under_lock` (cache warm, kid missing) or after a
        cold/expired-cache fetch that still didn't contain `kid`."""
        now = self._monotonic()
        if (
            self._last_forced_refresh is None
            or now - self._last_forced_refresh >= self._forced_refresh_cooldown
        ):
            try:
                signing_keys = self._fetch_signing_keys_locked(refresh=True)
            finally:
                # Advance the cooldown regardless of outcome — including a
                # failure-cooldown-gated no-op below. A caller must not be
                # able to keep forcing attempts every request, whether by
                # submitting a stream of bogus kids or by an unreachable
                # identity provider that keeps every attempt failing.
                self._last_forced_refresh = self._monotonic()
        else:
            # Still cooling down, and the cache is known-warm — this
            # branch is only reached right after a successful peek within
            # this same, unbroken lock acquisition (either directly, or
            # via the cold-cache fetch just above, which only calls this
            # method once it has *already* produced a warm cache) — so
            # this is a guaranteed cache hit. Deliberately bypasses
            # `_fetch_signing_keys_locked`/the failure-retry cooldown
            # entirely rather than risk resetting failure state that has
            # nothing to do with this read.
            signing_keys = self._client.get_signing_keys()
        matched = jwt.PyJWKClient.match_kid(signing_keys, kid)
        if matched is None:
            raise jwt.PyJWKClientError(f"Unable to find a signing key that matches: {kid!r}")
        return matched

    def _fetch_signing_keys_locked(self, *, refresh: bool) -> list[jwt.PyJWK]:
        """Caller must already hold `self._lock`. The single choke point
        every fetch-triggering path (cold cache, TTL expiry, and forced
        refresh for an unknown kid) goes through, so a failure on any one
        of them bounds retries — via `_last_failed_fetch` and
        `_JWKS_FAILURE_RETRY_COOLDOWN_SECONDS` — uniformly across all of
        them, rather than only the forced-refresh path having a cooldown
        of its own."""
        now = self._monotonic()
        if (
            self._last_failed_fetch is not None
            and now - self._last_failed_fetch < self._failure_retry_cooldown
        ):
            # No network I/O, no re-parsing of whatever might still be
            # cached — a recent attempt (from this path or the other)
            # already failed and the cooldown hasn't elapsed.
            raise jwt.PyJWKClientError(
                "JWKS fetch failed recently; retrying is on a bounded cooldown"
            )
        try:
            signing_keys = self._client.get_signing_keys(refresh=refresh)
        except jwt.PyJWKClientConnectionError:
            # Transport-level failure: jwt.PyJWKClient.fetch_data() raises
            # this *before* ever writing to its own Tier-1 cache (verified
            # against the installed jwt.jwks_client source), so whatever
            # was already cached, if anything, is untouched and must stay
            # that way — only the failure-retry timer advances.
            self._last_failed_fetch = self._monotonic()
            raise
        except Exception:
            # Anything else reaching here means the fetch succeeded at the
            # transport level but produced something unusable — a non-
            # JSON-object response (PyJWKClientError) or an invalid/empty
            # key set (PyJWKSetError, from PyJWKSet.from_dict()/__init__).
            # jwt.PyJWKClient.fetch_data() already wrote that bad response
            # into the Tier-1 cache *before* this validation ever ran, so
            # it must be evicted — left alone, it would keep "successfully"
            # satisfying every subsequent cache read (valid by timestamp)
            # and failing the same parse for the rest of `lifespan`,
            # without the failure cooldown's eventual retry ever getting a
            # chance to find out the identity provider has recovered.
            self._last_failed_fetch = self._monotonic()
            self._evict_cache()
            raise
        else:
            self._last_failed_fetch = None
            return signing_keys

    def _evict_cache(self) -> None:
        cache = self._client.jwk_set_cache
        if cache is not None:
            # JWKSetCache.put()'s own type hint requires a PyJWKSet, but
            # its actual implementation explicitly treats `None` as "clear
            # the cache" (verified against the installed
            # jwt.jwk_set_cache source) — an intentional, documented-by-
            # behavior call, not an abuse of an implementation detail the
            # type hint simply doesn't reflect (the same kind of stub/
            # runtime mismatch `_peek_signing_keys` already works around).
            cache.put(None)  # type: ignore[arg-type]


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
            # config._validate_oidc_settings guarantees this is populated
            # (and HTTPS, in production) once Settings() has constructed
            # at all; a None here is a deployment/config defect (an auth-
            # requiring route was reached without OIDC configured), not a
            # client-facing failure — the AssertionError surfaces as the
            # generic 500 contract in api.errors, exactly like any other
            # unclassified server defect.
            assert settings.oidc_jwks_url is not None
            allowed_schemes = (
                OIDC_PRODUCTION_URL_SCHEMES
                if settings.environment == "production"
                else OIDC_LOCAL_URL_SCHEMES
            )
            _jwks_client = _JWKSClient(settings.oidc_jwks_url, allowed_url_schemes=allowed_schemes)
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
