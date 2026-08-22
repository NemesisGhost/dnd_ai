"""Generic opaque-credential generation and hashing — shared by every
"server issues a random secret, shows it once, stores only a hash"
mechanism this codebase uses: browser session tokens and CSRF secrets,
account activation/password-reset tokens, and (Phase 11R workstream D)
Foundry pairing codes/device secrets/access tokens.

Deliberately separate from `dnd_ai.domain.access.hash_foundry_system_key`
(unchanged, still sha256 — this module's `hash_opaque_secret` is the same
algorithm, factored out so new call sites share one definition instead of
each re-deriving it). Plain SHA-256, not a slow KDF: every secret this
module hashes is server-generated with real cryptographic entropy
(`secrets.token_urlsafe`), never attacker-guessable text a slow KDF would
need to defend against — the same reasoning migration 089's own docstring
gives for `system_key_hash`. Passwords are the opposite case (low-entropy,
human-chosen, attacker-guessable) and are deliberately hashed with Argon2id
instead — see `dnd_ai.domain.passwords`.
"""

import hashlib
import secrets

# 256 bits of entropy, URL-safe — the same bound
# `dnd_ai.commands.integration._FOUNDRY_SYSTEM_KEY_ENTROPY_BYTES` already
# established for a server-issued opaque credential.
DEFAULT_SECRET_ENTROPY_BYTES = 32


def generate_opaque_secret(entropy_bytes: int = DEFAULT_SECRET_ENTROPY_BYTES) -> str:
    """A cryptographically random, URL-safe opaque secret. Returned to the
    caller exactly once by whichever command generates it; never logged,
    never stored anywhere but as `hash_opaque_secret(...)`'s output."""
    return secrets.token_urlsafe(entropy_bytes)


def hash_opaque_secret(raw_secret: str) -> str:
    """sha256 hex digest (64 hex characters) — the one comparison form any
    server-generated opaque secret is ever stored or checked against."""
    return hashlib.sha256(raw_secret.encode("utf-8")).hexdigest()
