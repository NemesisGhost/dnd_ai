"""Tests for dnd_ai.domain.credentials — generic opaque-secret generation
and hashing shared by browser sessions, activation/reset tokens, and
(Phase 11R workstream D) Foundry pairing codes/device secrets/access
tokens.
"""

import pytest

from dnd_ai.domain.credentials import generate_opaque_secret, hash_opaque_secret

pytestmark = pytest.mark.unit


def test_generate_opaque_secret_is_high_entropy_and_unique() -> None:
    first = generate_opaque_secret()
    second = generate_opaque_secret()
    assert first != second
    assert len(first) >= 32


def test_hash_opaque_secret_is_deterministic() -> None:
    secret = generate_opaque_secret()
    assert hash_opaque_secret(secret) == hash_opaque_secret(secret)


def test_hash_opaque_secret_is_a_64_char_hex_digest() -> None:
    digest = hash_opaque_secret("anything")
    assert len(digest) == 64
    int(digest, 16)  # raises ValueError if not valid hex


def test_hash_opaque_secret_differs_for_different_inputs() -> None:
    assert hash_opaque_secret("a") != hash_opaque_secret("b")
