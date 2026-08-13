"""Tests for `dnd_ai.api.auth._JWKSClient` and `get_jwks_client()` — the
bounded-refresh wrapper around `jwt.PyJWKClient` and its singleton
construction (see `dnd_ai.api.auth`'s own module docstring for the gaps
they close). No network, no live identity provider: a fake in-process
transport stands in for the JWKS HTTP endpoint by monkeypatching the
underlying `jwt.PyJWKClient`'s own `fetch_data`, so these tests exercise
the real caching/throttling/locking logic end to end without ever calling
`urllib`.

The concurrency tests use `_FakeTransport(hold_seconds=...)`, which
deliberately holds inside its fetch operation and tracks the maximum
number of callers ever inside it at once (`max_concurrent_calls`). A fast
fake would let one thread finish (and populate the cache) before a race
condition ever had a chance to manifest, silently passing even against
broken, unsynchronized code — the whole point of holding is to force any
genuinely concurrent fetch attempts to actually overlap in time, so
`max_concurrent_calls > 1` is a deterministic proof a race occurred, not
a matter of timing luck.

The failure-retry-cooldown tests use `_FakeClock`, an injectable stand-in
for `time.monotonic()` (`_JWKSClient`'s own `monotonic` constructor
parameter), so cooldown/TTL elapsing is simulated by advancing a counter
rather than sleeping for real — deterministic and fast, no timing
fragility.
"""

import threading
import time
from collections.abc import Callable, Iterable

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from jwt.algorithms import RSAAlgorithm

import dnd_ai.api.auth as auth_module
from dnd_ai.api.auth import _JWKSClient
from dnd_ai.config import settings
from tests.jwt_helpers import RSAKeypair, generate_test_rsa_keypair

pytestmark = pytest.mark.unit


def _jwk_dict(kid: str, public_key: RSAPublicKey) -> dict[str, object]:
    jwk = RSAAlgorithm.to_jwk(public_key, as_dict=True)
    jwk["kid"] = kid
    return jwk


class _FakeClock:
    """A deterministic stand-in for `time.monotonic()` — advanced
    explicitly rather than by sleeping for real, so cooldown/TTL tests
    aren't timing-fragile."""

    def __init__(self, start: float = 0.0) -> None:
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


def _assert_all_threads_finished(threads: list[threading.Thread]) -> None:
    """`Thread.join(timeout=...)` returning does not mean the thread
    finished — it can also mean the timeout elapsed while the thread is
    still running (e.g. deadlocked on a lock this code failed to
    release). Every concurrency test below asserts this explicitly rather
    than joining and moving on."""
    still_alive = [t.name for t in threads if t.is_alive()]
    assert not still_alive, f"threads still running after join timeout: {still_alive}"


class _FakeTransport:
    """Stands in for the JWKS HTTP endpoint. `keys` is mutable between
    calls to simulate the identity provider rotating its published key
    set. `fail_next`/`return_malformed_next` simulate exactly one
    transient failure; `always_fail`/`always_return_malformed` simulate a
    sustained outage (every call fails) for the failure-retry-cooldown
    tests — a one-shot flag can't prove "sequential failures stay
    bounded," since it stops failing after the first attempt. `hold_seconds`
    deliberately slows `produce()` down and `max_concurrent_calls` records
    the highest number of overlapping callers observed inside it — see
    this module's docstring."""

    def __init__(self, keys: Iterable[RSAKeypair], *, hold_seconds: float = 0.0) -> None:
        self.keys: dict[str, RSAPublicKey] = {kp.kid: kp.public_key for kp in keys}
        self.hold_seconds = hold_seconds
        self.call_count = 0
        self.max_concurrent_calls = 0
        self.fail_next = False
        self.always_fail = False
        self.return_malformed_next = False
        self.always_return_malformed = False
        self.malformed_payload: object = ["not", "a", "json", "object"]
        self._in_flight = 0
        self._instrumentation_lock = threading.Lock()

    def produce(self) -> object:
        with self._instrumentation_lock:
            self._in_flight += 1
            self.max_concurrent_calls = max(self.max_concurrent_calls, self._in_flight)
            self.call_count += 1
        try:
            if self.hold_seconds:
                time.sleep(self.hold_seconds)
            if self.always_fail or self.fail_next:
                self.fail_next = False
                raise jwt.PyJWKClientConnectionError("simulated transient network failure")
            if self.always_return_malformed or self.return_malformed_next:
                self.return_malformed_next = False
                return self.malformed_payload
            return {"keys": [_jwk_dict(kid, key) for kid, key in self.keys.items()]}
        finally:
            with self._instrumentation_lock:
                self._in_flight -= 1


def _install_fake_transport(client: _JWKSClient, transport: _FakeTransport) -> None:
    """Replaces the underlying `jwt.PyJWKClient.fetch_data` with one
    backed by `transport` — but still reproducing its real side effect of
    writing a successful fetch into the Tier-1 JWKS-set cache (and *not*
    writing on a raised exception). Overriding `fetch_data` outright
    without this would silently skip that write, making every lookup look
    like a cache miss — the Tier-1 cache would never actually cache
    anything, defeating the exact behavior these tests are meant to
    verify."""
    inner = client._client

    def fake_fetch_data() -> object:
        data = transport.produce()
        if inner.jwk_set_cache is not None:
            inner.jwk_set_cache.put(data)
        return data

    inner.fetch_data = fake_fetch_data  # type: ignore[method-assign]


def _make_client(
    transport: _FakeTransport,
    *,
    lifespan: float = 300.0,
    cooldown: float = 30.0,
    failure_cooldown: float = 30.0,
    monotonic: Callable[[], float] = time.monotonic,
) -> _JWKSClient:
    client = _JWKSClient(
        "https://test-idp.example/jwks",
        lifespan=lifespan,
        forced_refresh_cooldown=cooldown,
        failure_retry_cooldown=failure_cooldown,
        timeout=1.0,
        monotonic=monotonic,
    )
    _install_fake_transport(client, transport)
    return client


def _run_concurrently(
    fn: Callable[[int], None], count: int, *, join_timeout: float = 10.0
) -> list[threading.Thread]:
    threads = [threading.Thread(target=fn, args=(i,), name=f"worker-{i}") for i in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=join_timeout)
    _assert_all_threads_finished(threads)
    return threads


def test_a_known_kid_resolves_on_the_first_call() -> None:
    keypair = generate_test_rsa_keypair()
    transport = _FakeTransport([keypair])
    client = _make_client(transport)

    resolved = client.get_signing_key(keypair.kid)

    assert resolved.public_numbers() == keypair.public_key.public_numbers()
    assert transport.call_count == 1


def test_an_unresolvable_kid_raises() -> None:
    keypair = generate_test_rsa_keypair()
    transport = _FakeTransport([keypair])
    client = _make_client(transport)

    with pytest.raises(jwt.PyJWKClientError):
        client.get_signing_key("no-such-kid")


# ---------------------------------------------------------------------------
# Finding 1: bounded forced-refresh rate under attacker-controlled kids
# ---------------------------------------------------------------------------


def test_repeated_distinct_bogus_kids_do_not_trigger_unbounded_refreshes() -> None:
    """Sequential (single-threaded) bound — the concurrent version below
    additionally proves this holds under real thread contention."""
    keypair = generate_test_rsa_keypair()
    transport = _FakeTransport([keypair])
    client = _make_client(transport, cooldown=30.0)

    for i in range(20):
        with pytest.raises(jwt.PyJWKClientError):
            client.get_signing_key(f"bogus-kid-{i}")

    # At most one bootstrap (non-forced, cache-empty) fetch plus one forced
    # refresh for the very first miss — never one fetch per distinct bogus
    # kid. 20 distinct attacker-controlled kids must not cost 20 fetches.
    assert transport.call_count <= 2


def test_concurrent_requests_with_distinct_bogus_kids_stay_bounded() -> None:
    """The single-threaded bound above could still be defeated by a race
    the fast fake transport wouldn't expose: many threads each observing
    "cooldown not yet consumed" (or "kid not in cache") before any of
    them updates shared state, each triggering its own fetch. A
    deliberately slow, concurrency-instrumented transport proves the lock
    actually serializes these regardless of timing."""
    keypair = generate_test_rsa_keypair()
    transport = _FakeTransport([keypair], hold_seconds=0.1)
    client = _make_client(transport, cooldown=30.0)

    # Warm the cache first (a solo call) so this test isolates the bogus-
    # kid/cooldown path from cold-start concurrency, which is covered
    # separately below.
    client.get_signing_key(keypair.kid)
    calls_after_warmup = transport.call_count

    errors: list[jwt.PyJWKClientError] = []
    other_errors: list[BaseException] = []
    errors_lock = threading.Lock()

    def _attempt(i: int) -> None:
        try:
            client.get_signing_key(f"concurrent-bogus-{i}")
        except jwt.PyJWKClientError as exc:
            with errors_lock:
                errors.append(exc)
        except BaseException as exc:  # noqa: BLE001 - captured for the assertion below
            with errors_lock:
                other_errors.append(exc)

    _run_concurrently(_attempt, 20)

    assert not other_errors, other_errors
    assert len(errors) == 20
    assert transport.max_concurrent_calls == 1
    assert transport.call_count == calls_after_warmup + 1


def test_concurrent_cold_start_lookups_perform_one_fetch() -> None:
    """A cold (never-yet-populated) Tier-1 cache is exactly as
    unsynchronized as an unrecognized kid in the underlying PyJWKClient —
    neither it nor JWKSetCache does any locking of its own. Many
    concurrent first requests for the *same*, genuinely present kid must
    still cost only one fetch."""
    keypair = generate_test_rsa_keypair()
    transport = _FakeTransport([keypair], hold_seconds=0.1)
    client = _make_client(transport, cooldown=30.0)

    results: list[RSAPublicKey] = []
    errors: list[BaseException] = []
    results_lock = threading.Lock()

    def _attempt(_i: int) -> None:
        try:
            key = client.get_signing_key(keypair.kid)
            with results_lock:
                results.append(key)
        except BaseException as exc:  # noqa: BLE001
            with results_lock:
                errors.append(exc)

    _run_concurrently(_attempt, 10)

    assert not errors, errors
    assert len(results) == 10
    assert all(r.public_numbers() == keypair.public_key.public_numbers() for r in results)
    assert transport.max_concurrent_calls == 1
    assert transport.call_count == 1


def test_concurrent_lookups_after_cache_expiry_perform_one_refresh() -> None:
    """Same race as cold start, at the other end of the Tier-1 cache's
    life: once it expires, concurrent requests must share one refetch,
    not each independently observe "expired" and fetch."""
    keypair = generate_test_rsa_keypair()
    transport = _FakeTransport([keypair], hold_seconds=0.1)
    client = _make_client(transport, lifespan=0.05, cooldown=30.0)

    # Prime the cache with a solo call, then let it expire.
    client.get_signing_key(keypair.kid)
    assert transport.call_count == 1
    time.sleep(0.1)

    results: list[RSAPublicKey] = []
    errors: list[BaseException] = []
    results_lock = threading.Lock()

    def _attempt(_i: int) -> None:
        try:
            key = client.get_signing_key(keypair.kid)
            with results_lock:
                results.append(key)
        except BaseException as exc:  # noqa: BLE001
            with results_lock:
                errors.append(exc)

    _run_concurrently(_attempt, 10)

    assert not errors, errors
    assert len(results) == 10
    assert all(r.public_numbers() == keypair.public_key.public_numbers() for r in results)
    assert transport.max_concurrent_calls == 1
    assert transport.call_count == 2  # 1 warmup + 1 shared refresh


def test_a_legitimate_new_key_becomes_usable_after_the_cooldown_elapses() -> None:
    existing = generate_test_rsa_keypair()
    new = generate_test_rsa_keypair()
    transport = _FakeTransport([existing])
    # A large lifespan isolates this from the Tier-1 TTL so only the
    # forced-refresh cooldown governs when the new key becomes visible.
    client = _make_client(transport, lifespan=60.0, cooldown=0.05)

    with pytest.raises(jwt.PyJWKClientError):
        client.get_signing_key(new.kid)
    calls_after_first_miss = transport.call_count
    assert calls_after_first_miss <= 2

    # Immediately retrying within the cooldown must not cost another fetch.
    with pytest.raises(jwt.PyJWKClientError):
        client.get_signing_key(new.kid)
    assert transport.call_count == calls_after_first_miss

    # The identity provider "rotates in" the new key, and the cooldown
    # elapses — a bounded wait, not a process restart.
    transport.keys[new.kid] = new.public_key
    time.sleep(0.1)

    resolved = client.get_signing_key(new.kid)
    assert resolved.public_numbers() == new.public_key.public_numbers()
    assert transport.call_count == calls_after_first_miss + 1


def test_a_transient_fetch_failure_on_one_kid_does_not_discard_a_cached_key() -> None:
    cached = generate_test_rsa_keypair()
    transport = _FakeTransport([cached])
    client = _make_client(transport, lifespan=60.0, cooldown=30.0)

    # Populate the Tier-1 cache with a successful resolution.
    resolved = client.get_signing_key(cached.kid)
    assert resolved.public_numbers() == cached.public_key.public_numbers()
    calls_after_warmup = transport.call_count

    # An unrelated forced refresh (triggered by a different, unknown kid)
    # fails transiently.
    transport.fail_next = True
    with pytest.raises(jwt.PyJWKClientConnectionError):
        client.get_signing_key("some-other-unknown-kid")

    # The already-cached, still-valid key for `cached.kid` must still
    # resolve — the failed fetch must not have wiped the Tier-1 cache.
    resolved_again = client.get_signing_key(cached.kid)
    assert resolved_again.public_numbers() == cached.public_key.public_numbers()
    # No new successful fetch was needed to serve it — the cache held.
    assert transport.call_count == calls_after_warmup + 1  # +1 = the failed attempt only


def test_a_malformed_jwks_response_fails_closed() -> None:
    keypair = generate_test_rsa_keypair()
    transport = _FakeTransport([keypair])
    transport.return_malformed_next = True
    client = _make_client(transport)

    with pytest.raises(jwt.PyJWKClientError):
        client.get_signing_key(keypair.kid)


# ---------------------------------------------------------------------------
# Outage amplification: bounded failure-retry cooldown. A direct probe of
# five sequential requests against a failed transport, before this fix,
# produced five fetches — the lock bounded *concurrent* attempts but
# recorded no retry timer, so every request after the lock was released
# retried immediately. Cache expiry is time-driven, but each retry attempt
# is triggered by an incoming request, so this is exactly as reachable by
# an unauthenticated caller as the unknown-kid path.
# ---------------------------------------------------------------------------


def test_repeated_sequential_cold_cache_failures_cause_one_fetch_within_the_cooldown() -> None:
    keypair = generate_test_rsa_keypair()
    transport = _FakeTransport([keypair])
    transport.always_fail = True
    clock = _FakeClock()
    client = _make_client(transport, failure_cooldown=30.0, monotonic=clock)

    # The first request performs the real (failing) attempt.
    with pytest.raises(jwt.PyJWKClientConnectionError):
        client.get_signing_key(keypair.kid)

    # Every subsequent request, still within the cooldown, is short-
    # circuited by _JWKSClient itself — a different exception than the
    # transport's own failure, proving no further attempt was made.
    for _ in range(4):
        with pytest.raises(jwt.PyJWKClientError) as excinfo:
            client.get_signing_key(keypair.kid)
        assert not isinstance(excinfo.value, jwt.PyJWKClientConnectionError)

    assert transport.call_count == 1


def test_concurrent_cold_cache_failures_cause_one_fetch() -> None:
    """Only the one thread that actually reaches the transport (bounded
    to at most one by the lock, mirroring the cold-start-success case)
    sees `PyJWKClientConnectionError`; every other concurrent caller is
    short-circuited by the failure cooldown once it acquires the lock —
    both are `jwt.PyJWTError` (the common base), which is what matters
    here: every caller fails closed, and the transport is touched once."""
    keypair = generate_test_rsa_keypair()
    transport = _FakeTransport([keypair], hold_seconds=0.1)
    transport.always_fail = True
    client = _make_client(transport, failure_cooldown=30.0)

    errors: list[jwt.PyJWTError] = []
    other_errors: list[BaseException] = []
    errors_lock = threading.Lock()

    def _attempt(_i: int) -> None:
        try:
            client.get_signing_key(keypair.kid)
        except jwt.PyJWTError as exc:
            with errors_lock:
                errors.append(exc)
        except BaseException as exc:  # noqa: BLE001
            with errors_lock:
                other_errors.append(exc)

    _run_concurrently(_attempt, 10)

    assert not other_errors, other_errors
    assert len(errors) == 10
    assert transport.max_concurrent_calls == 1
    assert transport.call_count == 1


def test_repeated_failures_after_ttl_expiry_remain_bounded() -> None:
    keypair = generate_test_rsa_keypair()
    transport = _FakeTransport([keypair])
    clock = _FakeClock()
    # jwt.PyJWKClient's own Tier-1 cache tracks its TTL with the *real*
    # clock internally (it doesn't accept an injectable one — only this
    # wrapper's own cooldown timestamps do), so expiry here needs an
    # actual short sleep; the failure-retry cooldown below is still
    # driven entirely by the fake clock.
    client = _make_client(transport, lifespan=0.05, failure_cooldown=30.0, monotonic=clock)

    # Warm the cache successfully.
    resolved = client.get_signing_key(keypair.kid)
    assert resolved.public_numbers() == keypair.public_key.public_numbers()
    assert transport.call_count == 1

    time.sleep(0.1)  # let the Tier-1 cache actually expire
    transport.always_fail = True

    with pytest.raises(jwt.PyJWKClientConnectionError):
        client.get_signing_key(keypair.kid)

    for _ in range(4):
        with pytest.raises(jwt.PyJWKClientError) as excinfo:
            client.get_signing_key(keypair.kid)
        assert not isinstance(excinfo.value, jwt.PyJWKClientConnectionError)

    assert transport.call_count == 2  # 1 warmup + 1 shared failed refetch attempt


def test_exactly_one_retry_occurs_after_the_failure_cooldown_and_it_restores_resolution() -> None:
    keypair = generate_test_rsa_keypair()
    transport = _FakeTransport([keypair])
    transport.always_fail = True
    clock = _FakeClock()
    client = _make_client(transport, failure_cooldown=30.0, monotonic=clock)

    # The first request attempts a real fetch, which fails.
    with pytest.raises(jwt.PyJWKClientConnectionError):
        client.get_signing_key(keypair.kid)
    assert transport.call_count == 1

    # Still within the cooldown: short-circuited by _JWKSClient itself,
    # never reaching the transport at all — a different exception type
    # than the transport's own failure, proving no fetch was attempted.
    with pytest.raises(jwt.PyJWKClientError) as excinfo:
        client.get_signing_key(keypair.kid)
    assert not isinstance(excinfo.value, jwt.PyJWKClientConnectionError)
    assert transport.call_count == 1

    # The cooldown elapses and the identity provider has recovered.
    clock.advance(31.0)
    transport.always_fail = False

    resolved = client.get_signing_key(keypair.kid)
    assert resolved.public_numbers() == keypair.public_key.public_numbers()
    assert transport.call_count == 2  # exactly one retry attempt


def test_a_non_dict_jwks_response_does_not_poison_the_cache_or_repeatedly_fetch() -> None:
    """jwt.PyJWKClient.fetch_data() writes a response into the Tier-1
    cache *before* get_jwk_set() validates it's a JSON object — without
    eviction, this would keep "successfully" satisfying every cache read
    (valid by timestamp) and failing the same parse for the rest of
    `lifespan`, without ever attempting a real refetch."""
    keypair = generate_test_rsa_keypair()
    transport = _FakeTransport([keypair])
    transport.always_return_malformed = True
    clock = _FakeClock()
    client = _make_client(transport, lifespan=300.0, failure_cooldown=30.0, monotonic=clock)

    for _ in range(5):
        with pytest.raises(jwt.PyJWKClientError):
            client.get_signing_key(keypair.kid)
    assert transport.call_count == 1

    clock.advance(31.0)
    transport.always_return_malformed = False

    resolved = client.get_signing_key(keypair.kid)
    assert resolved.public_numbers() == keypair.public_key.public_numbers()
    assert transport.call_count == 2


def test_a_dict_shaped_but_unusable_jwks_response_does_not_poison_the_cache() -> None:
    """The other malformed shape: valid JSON, valid dict, but an empty
    key set — jwt.PyJWKSet itself raises PyJWKSetError for this, a
    *sibling* of PyJWKClientError (both extend PyJWTError directly, not
    each other), exercised separately to prove eviction isn't
    accidentally keyed to one specific exception type."""
    keypair = generate_test_rsa_keypair()
    transport = _FakeTransport([keypair])
    transport.malformed_payload = {"keys": []}
    transport.always_return_malformed = True
    clock = _FakeClock()
    client = _make_client(transport, failure_cooldown=30.0, monotonic=clock)

    # The first request performs the real attempt, which fails parsing.
    with pytest.raises(jwt.PyJWKSetError):
        client.get_signing_key(keypair.kid)

    # Subsequent requests, still within the cooldown, are short-circuited
    # by _JWKSClient itself (PyJWKClientError, not PyJWKSetError) — no
    # further parsing of the (now-evicted) payload was attempted.
    for _ in range(2):
        with pytest.raises(jwt.PyJWKClientError):
            client.get_signing_key(keypair.kid)
    assert transport.call_count == 1

    clock.advance(31.0)
    transport.always_return_malformed = False

    resolved = client.get_signing_key(keypair.kid)
    assert resolved.public_numbers() == keypair.public_key.public_numbers()
    assert transport.call_count == 2


# ---------------------------------------------------------------------------
# Finding 3: no non-expiring per-key cache
# ---------------------------------------------------------------------------


def test_key_material_for_an_existing_kid_is_replaced_after_the_lifespan_expires() -> None:
    """The regression this guards against: with PyJWKClient's own
    `cache_keys=True` per-key LRU (no TTL), a reused kid would keep
    returning `original`'s key material forever, even after the Tier-1
    JWKS-set cache has long since expired and been refetched with new
    material under the same kid."""
    kid = "reused-kid"
    original = generate_test_rsa_keypair(kid=kid)
    rotated = generate_test_rsa_keypair(kid=kid)
    assert original.public_key.public_numbers() != rotated.public_key.public_numbers()

    transport = _FakeTransport([original])
    # A large cooldown isolates this from the forced-refresh path — only
    # the Tier-1 lifespan TTL should govern here.
    client = _make_client(transport, lifespan=0.05, cooldown=60.0)

    first = client.get_signing_key(kid)
    assert first.public_numbers() == original.public_key.public_numbers()

    transport.keys[kid] = rotated.public_key
    time.sleep(0.15)

    second = client.get_signing_key(kid)
    assert second.public_numbers() == rotated.public_key.public_numbers()


# ---------------------------------------------------------------------------
# get_jwks_client() singleton construction
# ---------------------------------------------------------------------------


def test_concurrent_get_jwks_client_initialization_returns_one_shared_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without `_jwks_client_init_lock`, concurrent first callers could
    each observe `_jwks_client is None` before any of them assigns it,
    constructing independent `_JWKSClient` instances — each with its own
    cache, lock, and cooldown. `_SlowJWKSClient` deliberately widens the
    construction window (real construction is far too fast to reliably
    race against otherwise) so an unsynchronized implementation would
    provably construct more than once."""
    construction_count = 0
    construction_count_lock = threading.Lock()
    construction_started = threading.Event()
    release_construction = threading.Event()

    class _SlowJWKSClient(auth_module._JWKSClient):
        def __init__(
            self,
            jwks_url: str,
            *,
            lifespan: float = auth_module._JWKS_SET_LIFESPAN_SECONDS,
            forced_refresh_cooldown: float = auth_module._JWKS_FORCED_REFRESH_COOLDOWN_SECONDS,
            failure_retry_cooldown: float = auth_module._JWKS_FAILURE_RETRY_COOLDOWN_SECONDS,
            timeout: float = auth_module._JWKS_FETCH_TIMEOUT_SECONDS,
            monotonic: Callable[[], float] = time.monotonic,
        ) -> None:
            nonlocal construction_count
            with construction_count_lock:
                construction_count += 1
            construction_started.set()
            assert release_construction.wait(timeout=5), "test setup itself timed out"
            super().__init__(
                jwks_url,
                lifespan=lifespan,
                forced_refresh_cooldown=forced_refresh_cooldown,
                failure_retry_cooldown=failure_retry_cooldown,
                timeout=timeout,
                monotonic=monotonic,
            )

    monkeypatch.setattr(auth_module, "_JWKSClient", _SlowJWKSClient)
    monkeypatch.setattr(settings, "oidc_jwks_url", "https://test-idp.example/jwks")
    auth_module.dispose_jwks_client()

    results: list[object] = []
    errors: list[BaseException] = []
    results_lock = threading.Lock()

    def _attempt(_i: int) -> None:
        try:
            client = auth_module.get_jwks_client()
            with results_lock:
                results.append(client)
        except BaseException as exc:  # noqa: BLE001
            with results_lock:
                errors.append(exc)

    threads = [
        threading.Thread(target=_attempt, args=(i,), name=f"init-worker-{i}") for i in range(10)
    ]
    try:
        for thread in threads:
            thread.start()
        # Let (what should be exactly one) construction attempt actually
        # start, and give every other thread time to pile up waiting on
        # the init lock, before releasing it — maximizing the chance an
        # unsynchronized implementation would have already let several
        # of them past the `is None` check by now.
        assert construction_started.wait(timeout=5)
        time.sleep(0.05)
        release_construction.set()
        for thread in threads:
            thread.join(timeout=5)
        _assert_all_threads_finished(threads)
    finally:
        auth_module.dispose_jwks_client()

    assert not errors, errors
    assert len(results) == 10
    assert len({id(r) for r in results}) == 1
    assert construction_count == 1
