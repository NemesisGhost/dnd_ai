"""Tests for `dnd_ai.api.auth._JWKSClient` — the bounded-refresh wrapper
around `jwt.PyJWKClient` (see that module's docstring for the two gaps it
closes). No network, no live identity provider: a fake in-process
transport stands in for the JWKS HTTP endpoint by monkeypatching the
underlying `jwt.PyJWKClient`'s own `fetch_data`, so these tests exercise
the real caching/throttling logic end to end without ever calling
`urllib`.
"""

import threading
import time
from collections.abc import Iterable

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from jwt.algorithms import RSAAlgorithm

from dnd_ai.api.auth import _JWKSClient
from tests.jwt_helpers import RSAKeypair, generate_test_rsa_keypair

pytestmark = pytest.mark.unit


def _jwk_dict(kid: str, public_key: RSAPublicKey) -> dict[str, object]:
    jwk = RSAAlgorithm.to_jwk(public_key, as_dict=True)
    jwk["kid"] = kid
    return jwk


class _FakeTransport:
    """Stands in for the JWKS HTTP endpoint. `keys` is mutable between
    calls to simulate the identity provider rotating its published key
    set; `fail_next` simulates one transient network/parse failure."""

    def __init__(self, keys: Iterable[RSAKeypair]) -> None:
        self.keys: dict[str, RSAPublicKey] = {kp.kid: kp.public_key for kp in keys}
        self.call_count = 0
        self.fail_next = False
        self.return_malformed_next = False

    def produce(self) -> object:
        self.call_count += 1
        if self.fail_next:
            self.fail_next = False
            raise jwt.PyJWKClientConnectionError("simulated transient network failure")
        if self.return_malformed_next:
            self.return_malformed_next = False
            return ["not", "a", "json", "object"]
        return {"keys": [_jwk_dict(kid, key) for kid, key in self.keys.items()]}


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
    transport: _FakeTransport, *, lifespan: float = 300.0, cooldown: float = 30.0
) -> _JWKSClient:
    client = _JWKSClient(
        "https://test-idp.example/jwks",
        lifespan=lifespan,
        forced_refresh_cooldown=cooldown,
        timeout=1.0,
    )
    _install_fake_transport(client, transport)
    return client


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
    """The single-threaded bound above could still be defeated by a race:
    many threads each observing "cooldown not yet consumed" before any of
    them updates it. This proves the lock actually serializes forced
    refreshes under real concurrency."""
    keypair = generate_test_rsa_keypair()
    transport = _FakeTransport([keypair])
    client = _make_client(transport, cooldown=30.0)

    errors: list[BaseException] = []
    other_errors: list[BaseException] = []

    def _attempt(kid: str) -> None:
        try:
            client.get_signing_key(kid)
        except jwt.PyJWKClientError as exc:
            errors.append(exc)
        except BaseException as exc:  # noqa: BLE001 - captured for the assertion below
            other_errors.append(exc)

    threads = [
        threading.Thread(target=_attempt, args=(f"concurrent-bogus-{i}",)) for i in range(20)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not other_errors, other_errors
    assert len(errors) == 20
    assert transport.call_count <= 2


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
