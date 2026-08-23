"""Tests for dnd_ai.domain.passwords — Argon2id hashing and the
docs/PLAN.md §23.1 password policy. No database, no live provider — pure
function tests only, per that module's own docstring.
"""

import pytest
from argon2 import PasswordHasher

from dnd_ai.domain.passwords import (
    DUMMY_PASSWORD_HASH,
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    PasswordPolicyError,
    hash_password,
    password_needs_rehash,
    validate_password_policy,
    verify_password,
)

pytestmark = pytest.mark.unit

_VALID_PASSWORD = "a genuinely random passphrase 42"


def test_hash_and_verify_round_trip() -> None:
    encoded = hash_password(_VALID_PASSWORD)
    assert verify_password(_VALID_PASSWORD, encoded)


def test_verify_rejects_wrong_password() -> None:
    encoded = hash_password(_VALID_PASSWORD)
    assert not verify_password("a different passphrase entirely", encoded)


def test_verify_never_raises_for_malformed_hash() -> None:
    assert not verify_password(_VALID_PASSWORD, "not-a-real-argon2-hash")
    assert not verify_password(_VALID_PASSWORD, "")


def test_dummy_password_hash_is_a_valid_argon2id_hash_never_matching_a_real_password() -> None:
    assert DUMMY_PASSWORD_HASH.startswith("$argon2id$")
    assert not verify_password(_VALID_PASSWORD, DUMMY_PASSWORD_HASH)


def test_password_needs_rehash_true_for_weaker_parameters() -> None:
    weaker_hasher = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)
    weaker_encoded = weaker_hasher.hash(_VALID_PASSWORD)
    assert password_needs_rehash(weaker_encoded)


def test_password_needs_rehash_false_for_a_freshly_produced_hash() -> None:
    assert not password_needs_rehash(hash_password(_VALID_PASSWORD))


def test_validate_password_policy_accepts_a_long_random_passphrase() -> None:
    validate_password_policy("correct thunderhorse velvet mansion 7")


def test_validate_password_policy_accepts_unicode_and_spaces_up_to_64_chars() -> None:
    validate_password_policy("réservé mañana 日本語のパスフレーズ ok テスト12" * 1)


@pytest.mark.parametrize(
    "raw_password",
    [
        "short",
        "a" * (MIN_PASSWORD_LENGTH - 1),
    ],
)
def test_validate_password_policy_rejects_too_short(raw_password: str) -> None:
    with pytest.raises(PasswordPolicyError):
        validate_password_policy(raw_password)


def test_validate_password_policy_rejects_too_long() -> None:
    with pytest.raises(PasswordPolicyError):
        validate_password_policy("a" * (MAX_PASSWORD_LENGTH + 1))


def test_validate_password_policy_accepts_exactly_the_minimum_length() -> None:
    assert len("correct-thunder") == MIN_PASSWORD_LENGTH
    validate_password_policy("correct-thunder")


@pytest.mark.parametrize(
    "raw_password",
    [
        "aaaaaaaaaaaaaaaaaaaa",
        "123456789012345",
        "987654321098765",
        "password12345678",
        "PASSWORD12345678",
        "correcthorsebatterystaple",
    ],
)
def test_validate_password_policy_rejects_denylisted_or_low_entropy_values(
    raw_password: str,
) -> None:
    with pytest.raises(PasswordPolicyError):
        validate_password_policy(raw_password)


def test_validate_password_policy_error_message_does_not_vary_by_reason() -> None:
    """docs/PLAN.md §23.1/§23.4: rejection reasons must not disclose which
    specific rule failed — length vs. denylist."""
    too_short = None
    denylisted = None
    try:
        validate_password_policy("short")
    except PasswordPolicyError as exc:
        too_short = exc.safe_message
    try:
        validate_password_policy("aaaaaaaaaaaaaaaaaaaa")
    except PasswordPolicyError as exc:
        denylisted = exc.safe_message
    assert too_short == denylisted
