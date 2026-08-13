"""Tests for `dnd_ai.domain.tokens.verify_bearer_token` — signature,
issuer, audience, expiry, and claim-shape verification. No database, no
live identity provider or JWKS HTTP server: every token is signed with a
keypair generated locally in this process (`tests/jwt_helpers.py`), and
`get_signing_key` is a plain dict lookup — the "no-live-provider test
strategy" this workstream exists to establish.
"""

import base64
import hashlib
import hmac
import json
from datetime import timedelta

import jwt
import pytest
from cryptography.hazmat.primitives import serialization

from dnd_ai.domain.errors import AuthenticationError
from dnd_ai.domain.tokens import verify_bearer_token
from tests.jwt_helpers import generate_test_rsa_keypair, make_signed_jwt

pytestmark = pytest.mark.unit

_ISSUER = "https://test-idp.example"
_AUDIENCE = "test-audience"


def test_a_valid_token_is_accepted() -> None:
    keypair = generate_test_rsa_keypair()
    token = make_signed_jwt(
        keypair,
        issuer=_ISSUER,
        audience=_AUDIENCE,
        subject="user-123",
        extra_claims={"email": "player@example.com"},
    )

    claims = verify_bearer_token(
        token,
        issuer=_ISSUER,
        audience=_AUDIENCE,
        get_signing_key=lambda kid: keypair.public_key,
    )

    assert claims.issuer == _ISSUER
    assert claims.subject == "user-123"
    assert claims.email == "player@example.com"


def test_a_valid_token_with_no_email_claim_is_accepted() -> None:
    keypair = generate_test_rsa_keypair()
    token = make_signed_jwt(keypair, issuer=_ISSUER, audience=_AUDIENCE)

    claims = verify_bearer_token(
        token, issuer=_ISSUER, audience=_AUDIENCE, get_signing_key=lambda kid: keypair.public_key
    )

    assert claims.email is None


def test_an_expired_token_is_rejected() -> None:
    keypair = generate_test_rsa_keypair()
    token = make_signed_jwt(
        keypair,
        issuer=_ISSUER,
        audience=_AUDIENCE,
        issued_delta=timedelta(hours=-2),
        expires_delta=timedelta(hours=-1),
    )

    with pytest.raises(AuthenticationError):
        verify_bearer_token(
            token,
            issuer=_ISSUER,
            audience=_AUDIENCE,
            get_signing_key=lambda kid: keypair.public_key,
        )


def test_a_token_with_the_wrong_issuer_is_rejected() -> None:
    keypair = generate_test_rsa_keypair()
    token = make_signed_jwt(keypair, issuer="https://someone-else.example", audience=_AUDIENCE)

    with pytest.raises(AuthenticationError):
        verify_bearer_token(
            token,
            issuer=_ISSUER,
            audience=_AUDIENCE,
            get_signing_key=lambda kid: keypair.public_key,
        )


def test_a_token_with_the_wrong_audience_is_rejected() -> None:
    keypair = generate_test_rsa_keypair()
    token = make_signed_jwt(keypair, issuer=_ISSUER, audience="someone-elses-audience")

    with pytest.raises(AuthenticationError):
        verify_bearer_token(
            token,
            issuer=_ISSUER,
            audience=_AUDIENCE,
            get_signing_key=lambda kid: keypair.public_key,
        )


def test_a_token_signed_by_a_different_key_is_rejected() -> None:
    """Proves signature verification actually checks the key material, not
    merely that the resolver returned *some* key."""
    signing_keypair = generate_test_rsa_keypair()
    a_different_keypair = generate_test_rsa_keypair()
    token = make_signed_jwt(signing_keypair, issuer=_ISSUER, audience=_AUDIENCE)

    with pytest.raises(AuthenticationError):
        verify_bearer_token(
            token,
            issuer=_ISSUER,
            audience=_AUDIENCE,
            get_signing_key=lambda kid: a_different_keypair.public_key,
        )


def test_a_token_with_no_kid_header_is_rejected() -> None:
    keypair = generate_test_rsa_keypair()
    claims = {"iss": _ISSUER, "aud": _AUDIENCE, "sub": "user-123"}
    token = jwt.encode(claims, key=keypair.private_key, algorithm="RS256")  # no kid header

    with pytest.raises(AuthenticationError):
        verify_bearer_token(
            token,
            issuer=_ISSUER,
            audience=_AUDIENCE,
            get_signing_key=lambda kid: keypair.public_key,
        )


def test_a_token_with_an_unresolvable_kid_is_rejected() -> None:
    keypair = generate_test_rsa_keypair()
    token = make_signed_jwt(keypair, issuer=_ISSUER, audience=_AUDIENCE, kid="unknown-kid")

    def get_signing_key(kid: str) -> object:
        raise KeyError(kid)

    with pytest.raises(AuthenticationError):
        verify_bearer_token(
            token, issuer=_ISSUER, audience=_AUDIENCE, get_signing_key=get_signing_key
        )


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


@pytest.mark.parametrize("algorithm", ["HS256", "none"])
def test_a_token_with_a_disallowed_algorithm_is_rejected(algorithm: str) -> None:
    keypair = generate_test_rsa_keypair()
    claims = {"iss": _ISSUER, "aud": _AUDIENCE, "sub": "user-123"}
    header = _b64url(json.dumps({"alg": algorithm, "kid": keypair.kid}).encode())
    payload = _b64url(json.dumps(claims).encode())
    if algorithm == "none":
        # A classic JWT-library footgun: an attacker-crafted token that
        # claims alg=none and carries no signature at all.
        token = f"{header}.{payload}."
    else:
        # HS256 "signed" with the RSA public key's PEM bytes as an HMAC
        # secret — the well-known RS256-to-HS256 algorithm-confusion attack.
        # PyJWT's own encode() refuses to build this directly (it detects
        # the key looks like a PEM/asymmetric key), which is exactly why
        # this constructs the forged token by hand instead — an attacker
        # exploiting this class of bug isn't calling our encoder either.
        public_pem = keypair.public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        signing_input = f"{header}.{payload}".encode()
        signature = hmac.new(public_pem, signing_input, hashlib.sha256).digest()
        token = f"{header}.{payload}.{_b64url(signature)}"

    with pytest.raises(AuthenticationError):
        verify_bearer_token(
            token,
            issuer=_ISSUER,
            audience=_AUDIENCE,
            get_signing_key=lambda kid: keypair.public_key,
        )


def test_a_malformed_token_is_rejected() -> None:
    def unreachable_signing_key(kid: str) -> object:
        raise AssertionError("get_signing_key must not be called for an unparseable token")

    with pytest.raises(AuthenticationError):
        verify_bearer_token(
            "not-a-jwt-at-all",
            issuer=_ISSUER,
            audience=_AUDIENCE,
            get_signing_key=unreachable_signing_key,
        )


@pytest.mark.parametrize("omitted_claim", ["exp", "iss", "sub"])
def test_a_token_missing_a_required_claim_is_rejected(omitted_claim: str) -> None:
    keypair = generate_test_rsa_keypair()
    token = make_signed_jwt(
        keypair, issuer=_ISSUER, audience=_AUDIENCE, omit_claims=(omitted_claim,)
    )

    with pytest.raises(AuthenticationError):
        verify_bearer_token(
            token,
            issuer=_ISSUER,
            audience=_AUDIENCE,
            get_signing_key=lambda kid: keypair.public_key,
        )


def test_a_token_with_a_non_string_email_claim_is_rejected() -> None:
    keypair = generate_test_rsa_keypair()
    token = make_signed_jwt(
        keypair, issuer=_ISSUER, audience=_AUDIENCE, extra_claims={"email": 12345}
    )

    with pytest.raises(AuthenticationError):
        verify_bearer_token(
            token,
            issuer=_ISSUER,
            audience=_AUDIENCE,
            get_signing_key=lambda kid: keypair.public_key,
        )
