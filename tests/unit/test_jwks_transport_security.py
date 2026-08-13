"""Tests for `dnd_ai.api.auth`'s JWKS redirect-downgrade protection (see
that module's docstring, point 5) — `_validate_jwks_transport_url()`,
`_ValidatingRedirectHandler`, and `_build_validating_fetch_data()`.

Two layers, deliberately:

- Pure-unit tests exercise `_validate_jwks_transport_url()` directly with
  no sockets at all, including the *literal* https-to-http downgrade
  named in the review finding this module closes.
- Real-local-HTTP-server tests (`127.0.0.1`, an OS-assigned ephemeral
  port — never the public internet) drive `_JWKSClient.get_signing_key()`
  through genuine `urllib`/`http.server` plumbing, proving the mechanism
  is actually wired into the real fetch path, not just correct in
  isolation. They use `allowed_schemes={"http"}` standing in for
  production's `{"https"}` and a redirect target of a *different*
  disallowed scheme — `_validate_jwks_transport_url` never special-cases
  the string `"https"`, so this is a fully faithful exercise of the same
  code path production takes, without needing a local TLS setup whose
  own correctness would be beside the point of what's being tested here.
"""

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from jwt.algorithms import RSAAlgorithm

import dnd_ai.api.auth as auth_module
from dnd_ai.api.auth import _JWKSClient
from tests.jwt_helpers import generate_test_rsa_keypair

pytestmark = pytest.mark.unit


def _jwk_dict(kid: str, public_key: RSAPublicKey) -> dict[str, object]:
    jwk = RSAAlgorithm.to_jwk(public_key, as_dict=True)
    jwk["kid"] = kid
    return jwk


# ---------------------------------------------------------------------------
# Pure unit tests — no sockets
# ---------------------------------------------------------------------------


def test_validate_jwks_transport_url_rejects_disallowed_scheme() -> None:
    with pytest.raises(auth_module._JWKSTransportSecurityError):
        auth_module._validate_jwks_transport_url(
            "ftp://downgraded.example/", allowed_schemes=frozenset({"https"}), what="fetch URL"
        )


def test_validate_jwks_transport_url_rejects_embedded_credentials() -> None:
    with pytest.raises(auth_module._JWKSTransportSecurityError):
        auth_module._validate_jwks_transport_url(
            "https://user:pass@idp.example/",
            allowed_schemes=frozenset({"https"}),
            what="fetch URL",
        )


def test_validate_jwks_transport_url_allows_configured_scheme() -> None:
    # Must not raise.
    auth_module._validate_jwks_transport_url(
        "https://idp.example/jwks", allowed_schemes=frozenset({"https"}), what="fetch URL"
    )


def test_validate_jwks_transport_url_rejects_https_to_http_downgrade_literally() -> None:
    """The exact scenario named in the review finding, using the literal
    https/http scheme strings — the real-server tests below additionally
    prove the *mechanism* is actually wired into genuine urllib/
    http.server plumbing, using scheme values that don't require a local
    TLS setup."""
    with pytest.raises(auth_module._JWKSTransportSecurityError):
        auth_module._validate_jwks_transport_url(
            "http://downgraded.example/keys",
            allowed_schemes=auth_module.OIDC_PRODUCTION_URL_SCHEMES,
            what="redirect target",
        )


def test_validate_jwks_transport_url_rejects_credentials_in_redirect_target_literally() -> None:
    with pytest.raises(auth_module._JWKSTransportSecurityError):
        auth_module._validate_jwks_transport_url(
            "https://user:pass@idp.example/keys",
            allowed_schemes=auth_module.OIDC_PRODUCTION_URL_SCHEMES,
            what="redirect target",
        )


# ---------------------------------------------------------------------------
# Real local HTTP server — genuine urllib/http.server plumbing, no fakes
# ---------------------------------------------------------------------------


class _RoutingServer(ThreadingHTTPServer):
    """A `ThreadingHTTPServer` whose response per path is configured by
    the test via `.routes`, set/mutated directly on the instance."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.routes: dict[str, dict[str, object]] = {}


class _RoutingHandler(BaseHTTPRequestHandler):
    server: _RoutingServer

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's own naming convention
        route = self.server.routes.get(self.path)
        if route is None:
            self.send_response(404)
            self.end_headers()
            return
        if route["type"] == "redirect":
            self.send_response(302)
            self.send_header("Location", str(route["location"]))
            self.end_headers()
            return
        body = json.dumps(route["payload"]).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass  # silence BaseHTTPRequestHandler's default stderr access log


@pytest.fixture
def http_server() -> Iterator[_RoutingServer]:
    server = _RoutingServer(("127.0.0.1", 0), _RoutingHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _base_url(server: _RoutingServer) -> str:
    return f"http://127.0.0.1:{server.server_port}"


def test_a_valid_response_without_any_redirect_works(http_server: _RoutingServer) -> None:
    keypair = generate_test_rsa_keypair()
    http_server.routes["/jwks"] = {
        "type": "json",
        "payload": {"keys": [_jwk_dict(keypair.kid, keypair.public_key)]},
    }
    client = _JWKSClient(
        f"{_base_url(http_server)}/jwks",
        allowed_url_schemes=frozenset({"http"}),
        timeout=2.0,
    )

    resolved = client.get_signing_key(keypair.kid)

    assert resolved.public_numbers() == keypair.public_key.public_numbers()


def test_a_same_scheme_credential_free_redirect_is_followed(http_server: _RoutingServer) -> None:
    """Legitimate HTTPS (here, same-scheme) redirects — e.g. a JWKS URL
    redirecting to a CDN-hosted copy of the same document — are
    deliberately supported, not blanket-rejected; see this module's
    docstring."""
    keypair = generate_test_rsa_keypair()
    base = _base_url(http_server)
    http_server.routes["/redirect"] = {"type": "redirect", "location": f"{base}/jwks"}
    http_server.routes["/jwks"] = {
        "type": "json",
        "payload": {"keys": [_jwk_dict(keypair.kid, keypair.public_key)]},
    }
    client = _JWKSClient(f"{base}/redirect", allowed_url_schemes=frozenset({"http"}), timeout=2.0)

    resolved = client.get_signing_key(keypair.kid)

    assert resolved.public_numbers() == keypair.public_key.public_numbers()


def test_a_redirect_to_a_disallowed_scheme_is_rejected_without_caching(
    http_server: _RoutingServer,
) -> None:
    """`allowed_schemes={"http"}` here stands in for production's
    `{"https"}` — the mechanism never special-cases either literal
    string, so a redirect from the allowed scheme to one outside the
    configured policy is rejected the same way regardless of which
    concrete schemes are involved (the literal https-to-http case is
    covered directly, with no server needed, above). The redirect target
    is deliberately never actually reachable (port 1) — `_JWKSClient`
    must never even attempt to connect to it."""
    keypair = generate_test_rsa_keypair()
    base = _base_url(http_server)
    http_server.routes["/redirect"] = {
        "type": "redirect",
        "location": "https://127.0.0.1:1/unreachable",
    }
    client = _JWKSClient(
        f"{base}/redirect",
        allowed_url_schemes=frozenset({"http"}),
        timeout=2.0,
        # Isolates this test from the (separately tested) failure-retry
        # cooldown — the second call below is a deliberate fresh attempt
        # proving recovery, not a cooldown-bypass check.
        failure_retry_cooldown=0.0,
    )

    with pytest.raises(jwt.PyJWKClientConnectionError):
        client.get_signing_key(keypair.kid)

    # Nothing was accepted or cached by the blocked redirect — a
    # subsequent, now-valid response at the same URL still resolves
    # cleanly rather than reusing/being poisoned by anything from the
    # rejected attempt.
    http_server.routes["/redirect"] = {
        "type": "json",
        "payload": {"keys": [_jwk_dict(keypair.kid, keypair.public_key)]},
    }
    resolved = client.get_signing_key(keypair.kid)
    assert resolved.public_numbers() == keypair.public_key.public_numbers()


def test_a_redirect_containing_embedded_credentials_is_rejected(
    http_server: _RoutingServer,
) -> None:
    keypair = generate_test_rsa_keypair()
    base = _base_url(http_server)
    http_server.routes["/redirect"] = {
        "type": "redirect",
        "location": f"http://user:pass@127.0.0.1:{http_server.server_port}/jwks",
    }
    http_server.routes["/jwks"] = {
        "type": "json",
        "payload": {"keys": [_jwk_dict(keypair.kid, keypair.public_key)]},
    }
    client = _JWKSClient(
        f"{base}/redirect",
        allowed_url_schemes=frozenset({"http"}),
        timeout=2.0,
        failure_retry_cooldown=0.0,
    )

    with pytest.raises(jwt.PyJWKClientConnectionError):
        client.get_signing_key(keypair.kid)
