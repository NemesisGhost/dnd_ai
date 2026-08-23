"""Argon2id password hashing and policy for local D&D AI accounts
(docs/PLAN.md §23.1, Phase 11R workstream A).

Framework-free per docs/architecture/SYSTEM_ARCHITECTURE.md §5.4 — no
FastAPI/SQLAlchemy types here, only `argon2-cffi` and stdlib. `dnd_ai.
commands.local_auth` is the only caller that persists anything this module
produces.

Policy, per docs/PLAN.md §23.1 verbatim: "Accept passphrases of at least 15
characters, permit at least 64 characters plus spaces and Unicode, reject
common/compromised values through a locally enforceable denylist or
approved privacy-preserving check, and do not impose composition formulas
or periodic forced changes." There is deliberately no uppercase/digit/
symbol composition rule and no password-history/rotation check here —
composition rules are explicitly excluded by the plan, and this codebase
has no requirement (yet) to retain prior password hashes to enforce reuse
rejection.
"""

import unicodedata

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHash, VerificationError, VerifyMismatchError

from .errors import SafeMessageError

MIN_PASSWORD_LENGTH = 15
# A generous upper bound, comfortably above the "at least 64 characters"
# floor the plan requires supporting — not a policy choice about what a
# *good* password looks like, but a bound on how much text a single
# Argon2id hash call will ever be asked to digest, so a request body cannot
# turn password hashing into an unbounded-cost operation.
MAX_PASSWORD_LENGTH = 512

# argon2-cffi's own encoded hash format ("$argon2id$v=19$m=...,t=...,p=...
# $<salt>$<hash>") already carries the algorithm, version, and every
# hashing parameter used to produce it — there is no separate "parameters"
# column to maintain; PasswordHasher.check_needs_rehash(encoded) is how a
# future change to _PASSWORD_HASHER's parameters is detected and applied
# lazily, at the next successful login, rather than migrated in bulk.
_PASSWORD_HASHER = PasswordHasher()

# A fixed, valid Argon2id hash of a value nobody will ever submit as a real
# password, used only to give a nonexistent-user login attempt the same
# hashing cost as a real one (dnd_ai.commands.local_auth.authenticate_local_user's
# constant-work verification) — never itself accepted as a real credential,
# since no security.local_credentials row ever stores it.
DUMMY_PASSWORD_HASH = _PASSWORD_HASHER.hash(
    "dnd-ai-constant-time-placeholder-hash-do-not-use-as-a-real-password"
)


class PasswordPolicyError(SafeMessageError):
    """The submitted password fails the local account password policy —
    too short, too long, or on the locally enforced common/weak denylist.
    HTTP 400 via the base `SafeMessageError` contract; the specific reason
    is a deliberately fixed, generic message (never "too short" vs. "too
    common" specifically) so a client cannot use the failure reason itself
    to narrow down what a target account's real password might be closer
    to — the same non-disclosure discipline docs/PLAN.md §23.1/§23.4
    requires for login/activation/reset responses generally."""

    safe_error_code = "password_policy_violation"
    safe_message = (
        "Choose a passphrase of at least 15 characters that is not a commonly used value."
    )


# A small, deterministic, locally enforceable denylist — docs/PLAN.md
# §23.1's "locally enforceable denylist," not a live breach-database
# lookup (which would be a network dependency at password-set time and is
# explicitly out of scope: automated tests must never require a live
# external call, matching the same discipline this project already
# applies to AI-provider and OIDC/JWKS calls). Every entry is at least 15
# characters — anything shorter is already rejected by
# MIN_PASSWORD_LENGTH before this set is even consulted — so this
# specifically catches the "technically long enough, but a well-known weak
# passphrase" case (keyboard walks, repeated/sequential runs, common
# stock phrases), compared case-insensitively after Unicode normalization.
_COMMON_LONG_PASSWORDS: frozenset[str] = frozenset(
    {
        "password12345678",
        "passwordpassword",
        "letmeinletmein12",
        "qwertyuiopqwerty",
        "qwertyuiopasdfgh",
        "1234567890123456",
        "12345678901234567890",
        "abcdefghijklmnop",
        "correcthorsebatterystaple",
        "iloveyouiloveyou",
        "trustno1trustno1",
        "welcometotheteam",
        "changeme12345678",
        "administrator123",
        "dragonwarriorloves",
        "thequickbrownfoxjumps",
        "superman123456789",
        "whatever1234567890",
        "football1234567890",
        "baseball1234567890",
        "princess1234567890",
        "sunshine1234567890",
    }
)


def _normalize_for_denylist(raw_password: str) -> str:
    # NFKC before casefolding so visually-equivalent Unicode variants of an
    # ASCII denylist entry cannot slip past a naive lower()/strip() compare.
    return unicodedata.normalize("NFKC", raw_password).casefold()


def _is_low_entropy_run(normalized: str) -> bool:
    """Rejects a password that is a single repeated character (`"aaaa...a"`)
    or a cyclically ascending/descending run of digits
    (`"123456789012345"`/`"987654321098765"`, wrapping through 9->0 or
    0->9 exactly like a finger walking a number pad or keyboard row) — the
    two low-effort patterns that pass every length check but carry
    essentially no real entropy, and that a small fixed denylist can never
    enumerate exhaustively since they scale with length. Each step's
    difference is taken modulo 10 specifically so the wraparound case
    (`...9012...`) is recognized as the same uniform pattern as a
    non-wrapping run, rather than breaking the run and evading detection.
    Deterministic and local; no dependency on the fixed denylist set
    above."""
    if len(set(normalized)) == 1:
        return True
    if normalized.isdigit() and len(normalized) >= 2:
        digits = [int(ch) for ch in normalized]
        # zip(digits, digits[1:]) is the standard adjacent-pairs idiom —
        # digits[1:] is deliberately one element shorter, so strict=True
        # would be wrong here (it would raise ValueError on every call,
        # not detect a real mismatch); strict=False (stop at the shorter
        # iterable) is exactly what pairing adjacent elements requires.
        diffs = [(b - a) % 10 for a, b in zip(digits, digits[1:], strict=False)]
        if all(d == 1 for d in diffs) or all(d == 9 for d in diffs):
            return True
    return False


def validate_password_policy(raw_password: str) -> None:
    """Raises `PasswordPolicyError` unless `raw_password` satisfies
    docs/PLAN.md §23.1's policy. Called by every command that sets or
    changes a password (`dnd_ai.commands.local_auth`) before hashing —
    never after, since there is no reason to pay Argon2id's cost for a
    password this rejects outright."""
    if not (MIN_PASSWORD_LENGTH <= len(raw_password) <= MAX_PASSWORD_LENGTH):
        raise PasswordPolicyError()
    normalized = _normalize_for_denylist(raw_password)
    if normalized in _COMMON_LONG_PASSWORDS or _is_low_entropy_run(normalized):
        raise PasswordPolicyError()


def hash_password(raw_password: str) -> str:
    """The Argon2id-encoded hash string to persist in
    `security.local_credentials.password_hash`. Caller must have already
    called `validate_password_policy` — this function does not re-check
    policy, only hashes."""
    return _PASSWORD_HASHER.hash(raw_password)


def verify_password(raw_password: str, encoded_hash: str) -> bool:
    """`True` iff `raw_password` matches `encoded_hash`. Never raises for a
    mismatched/malformed hash — every Argon2id verification failure mode
    collapses to `False`, so a caller cannot distinguish "wrong password"
    from "corrupt hash" from the return value alone."""
    try:
        _PASSWORD_HASHER.verify(encoded_hash, raw_password)
    except (VerifyMismatchError, VerificationError, InvalidHash):
        return False
    return True


def password_needs_rehash(encoded_hash: str) -> bool:
    """`True` when `encoded_hash` was produced with different parameters
    than `_PASSWORD_HASHER`'s current ones — the caller (`dnd_ai.commands.
    local_auth.authenticate_local_user`) rehashes and stores a fresh hash
    of the just-verified plaintext when this is `True`, so a future
    parameter change (e.g. a raised memory cost) rolls out lazily at each
    user's next successful login rather than requiring a bulk migration or
    forcing every user to reset their password."""
    return _PASSWORD_HASHER.check_needs_rehash(encoded_hash)
