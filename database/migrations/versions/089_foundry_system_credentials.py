"""Add integration.external_systems.system_key_hash

Revision ID: 089_foundry_system_credentials
Revises: e3f791aca64d
Create Date: 2026-08-18 21:00:00.000000

Purpose:
    Phase 11 ("Foundry MVP") workstream 2: gives a Foundry adapter a real
    credential to authenticate with, closing the gap workstream 1
    (`link_foundry_identity`, migration-free — it reused the already-
    generic `security.external_identities` table) deliberately left open:
    that workstream maps *identity* ("Foundry user X in world W is
    platform user Y") but establishes no way for a request to prove it is
    actually acting for `integration.external_systems` row W in the first
    place. Without a system-level credential, any caller who already knows
    (or guesses) a Foundry user id could claim to be that user merely by
    naming them — `resolve_foundry_system_user_id` (`dnd_ai.domain.access`)
    requires both a valid, matching `system_key_hash` for the claimed
    `external_system_id` *and* an existing identity-linked Foundry user id
    before resolving a platform `user_id`.

    Deliberately a single nullable column on `integration.external_systems`
    rather than a new table: unlike `security.campaign_invitations`
    (invited/accepted/revoked/expired — a real per-invitation lifecycle),
    a Foundry system credential has no lifecycle of its own beyond
    "currently valid or not" — issuing a new one (`dnd_ai.commands.
    integration.issue_foundry_system_key`) simply overwrites the prior
    hash in place (rotation, not append), and `external_systems.updated_at`
    (already trigger-maintained) already records when that last happened.
    A separate table would only be justified by a rotation/revocation
    history this workstream has no requirement for yet.

    Hash-only storage (`system_key_hash`, never the raw key) mirrors
    `security.campaign_invitations.invitation_token_hash` exactly — see
    that table's own migration (080) and `dnd_ai.commands.
    campaign_invitations`' module docstring for why plain SHA-256 (not a
    slow KDF) is the right choice for a server-generated, 256-bit-entropy
    secret rather than attacker-guessable text. `dnd_ai.domain.access.
    hash_foundry_system_key` is the one place that hashing happens, shared
    by both the issuing command and the authentication path that verifies
    a presented key against this column.

Forward migration:
    `integration.external_systems`:
      - `system_key_hash TEXT NULL` — sha256 hex digest of the Foundry
        adapter's system-level credential; `NULL` until
        `issue_foundry_system_key` is called for that row, and again after
        `char_length(system_key_hash) = 64` is not satisfiable by anything
        but a real sha256 hex digest
      - `ck_external_systems_system_key_hash_length`: `CHECK (system_key_hash
        IS NULL OR char_length(system_key_hash) = 64)`
      - `ux_external_systems_system_key_hash`: `UNIQUE (system_key_hash)` —
        a `NULL`-valued column does not participate in `UNIQUE` matching
        (PostgreSQL treats every `NULL` as distinct), so any number of
        external systems may simultaneously have never had a key issued;
        once non-`NULL`, no two rows may ever share a hash

Rollback:
    Supported. Drops both constraints and the column.

Data implications:
    Every existing `integration.external_systems` row gets `system_key_hash
    = NULL` (no key issued) — Phase 9/10 registrations remain valid and
    simply cannot authenticate as a Foundry system until a GM issues a key
    for them.

Locking considerations:
    `ADD COLUMN system_key_hash TEXT` with no default is a metadata-only
    change on PostgreSQL 11+ (no table rewrite). The two `ADD CONSTRAINT`
    statements each require a full-table validation scan, but
    `integration.external_systems` is small, adapter-facing infrastructure
    (one row per registered external system, not a bulk domain table), so
    this is not expected to hold a lock for any material duration.

See: database/migrations/versions/079_integration_domain.py
     (integration.external_systems' own creation)
     database/migrations/versions/080_security_identity_and_access.py
     (security.campaign_invitations.invitation_token_hash — the closest
     existing "store only a hash" precedent this mirrors)
     src/dnd_ai/domain/access.py (hash_foundry_system_key,
     resolve_foundry_system_user_id — this column's only reader)
     src/dnd_ai/commands/integration.py (issue_foundry_system_key — this
     column's only writer)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "089_foundry_system_credentials"
down_revision = "e3f791aca64d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    op.execute("""
        ALTER TABLE integration.external_systems
            ADD COLUMN system_key_hash TEXT,
            ADD CONSTRAINT ck_external_systems_system_key_hash_length
                CHECK (system_key_hash IS NULL OR char_length(system_key_hash) = 64),
            ADD CONSTRAINT ux_external_systems_system_key_hash UNIQUE (system_key_hash);
    """)
    op.execute("""
        COMMENT ON COLUMN integration.external_systems.system_key_hash IS
        'sha256 hex digest of a Foundry-adapter system-level credential '
        '(dnd_ai.domain.access.hash_foundry_system_key). NULL until '
        'dnd_ai.commands.integration.issue_foundry_system_key is called for '
        'this row; issuing a new key overwrites this in place (rotation, not '
        'append) rather than tracking history. Never the raw key itself — see '
        'security.campaign_invitations.invitation_token_hash for the identical '
        'hash-only pattern.';
    """)


def downgrade() -> None:
    """Revert the migration."""

    op.execute("""
        ALTER TABLE integration.external_systems
            DROP CONSTRAINT IF EXISTS ux_external_systems_system_key_hash,
            DROP CONSTRAINT IF EXISTS ck_external_systems_system_key_hash_length,
            DROP COLUMN IF EXISTS system_key_hash;
    """)
