"""Tests for `dnd_ai.api.client_address.resolve_client_ip` — the shared
trusted-reverse-proxy resolver (Phase 13B correction; see that module's own
docstring for the full trust algorithm). Pure-Python: builds a `Request`
directly from a raw ASGI scope, no app/TestClient/database needed.
"""

import pytest
from starlette.requests import Request

import dnd_ai.config as config
from dnd_ai.api.client_address import resolve_client_ip

pytestmark = pytest.mark.unit


def _request(peer: str | None, *, x_forwarded_for: str | None = None) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if x_forwarded_for is not None:
        headers.append((b"x-forwarded-for", x_forwarded_for.encode()))
    scope = {
        "type": "http",
        "headers": headers,
        "client": (peer, 12345) if peer is not None else None,
    }
    return Request(scope)


@pytest.fixture(autouse=True)
def _no_trusted_proxies_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test starts from the safe default (nothing trusted) —
    matching this codebase's established pattern of `monkeypatch.setattr`
    directly on the module-level `dnd_ai.config.settings` singleton (see
    e.g. `tests/database/test_api_auth.py`'s identical use for
    `oidc_issuer` et al.) — each test that needs a trusted proxy overrides
    it explicitly."""
    monkeypatch.setattr(config.settings, "trusted_proxies", None)


def test_defaults_to_the_peer_address_with_no_trusted_proxies_configured() -> None:
    request = _request("198.51.100.1", x_forwarded_for="1.2.3.4")
    assert resolve_client_ip(request) == "198.51.100.1"


def test_falls_back_to_a_placeholder_when_the_asgi_server_supplied_no_peer() -> None:
    request = _request(None)
    assert resolve_client_ip(request) == "unknown"


def test_trusts_the_last_forwarded_entry_from_a_configured_trusted_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config.settings, "trusted_proxies", "203.0.113.1")
    # The trusted proxy always appends the address it directly observed —
    # the last entry — regardless of what an attacker prepended earlier in
    # the chain.
    request = _request("203.0.113.1", x_forwarded_for="9.9.9.9, 198.51.100.77")
    assert resolve_client_ip(request) == "198.51.100.77"


def test_ignores_forwarded_for_from_an_untrusted_peer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config.settings, "trusted_proxies", "203.0.113.1")
    request = _request("198.51.100.1", x_forwarded_for="9.9.9.9")
    assert resolve_client_ip(request) == "198.51.100.1"


def test_falls_back_to_the_peer_when_forwarded_for_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config.settings, "trusted_proxies", "203.0.113.1")
    request = _request("203.0.113.1")
    assert resolve_client_ip(request) == "203.0.113.1"


def test_falls_back_to_the_peer_when_forwarded_for_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config.settings, "trusted_proxies", "203.0.113.1")
    request = _request("203.0.113.1", x_forwarded_for="")
    assert resolve_client_ip(request) == "203.0.113.1"


def test_falls_back_to_the_peer_when_forwarded_for_is_malformed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config.settings, "trusted_proxies", "203.0.113.1")
    request = _request("203.0.113.1", x_forwarded_for="not-an-ip-address")
    assert resolve_client_ip(request) == "203.0.113.1"


def test_a_trusted_proxy_may_be_configured_as_a_cidr_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config.settings, "trusted_proxies", "203.0.113.0/24")
    request = _request("203.0.113.42", x_forwarded_for="198.51.100.5")
    assert resolve_client_ip(request) == "198.51.100.5"


def test_a_peer_just_outside_a_configured_cidr_network_is_not_trusted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config.settings, "trusted_proxies", "203.0.113.0/24")
    request = _request("203.0.114.1", x_forwarded_for="198.51.100.5")
    assert resolve_client_ip(request) == "203.0.114.1"
