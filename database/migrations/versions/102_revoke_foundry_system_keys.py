"""Revoke every legacy FoundrySystem key at the data level

Revision ID: 102_revoke_foundry_system_keys
Revises: 101_change_log_foundry_pairing
Create Date: 2026-08-22 12:00:00.000000

Purpose:
    Workstream 11R High-severity finding 2: the legacy `FoundrySystem`
    shared credential remained permanently, unconditionally acceptable at
    the authentication boundary alongside its paired-device `FoundryAccess`
    replacement, with no deployment-configurable disabled-by-default
    switch, no deadline, and its own HTTP issuance endpoint still
    reachable — so a still-valid legacy key could bypass every per-device
    protection (listing, expiry, exact-campaign binding, individual
    revocation) the pairing model exists to provide, indefinitely. The
    accompanying code change (`src/dnd_ai/api/auth.py`) rejects the
    `FoundrySystem` scheme unconditionally at `get_authenticated_user_id`
    itself and removes `issue_foundry_system_key_endpoint`'s HTTP surface
    entirely — this migration is the data-level half of that same
    correction: revoking every key that already exists, so the fix does
    not depend solely on the code path never being reintroduced or
    bypassed. Defense in depth, not the primary fix.

    This repository found no evidence of a real deployed client still
    depending on the `FoundrySystem` scheme — the sole first-party client,
    `foundry-module/`, was already fully converted to paired-device
    `FoundryAccess` by Workstream 11R workstream H, before this
    correction — so a compatibility window was deliberately not built; see
    the Workstream 11R verification record for the full determination.

Forward migration:
    `integration.external_systems`: every row with a non-NULL `system_key_
    hash` gets `system_key_hash = NULL` and `system_key_principal_user_id
    = NULL`. `is_active` and every other column are untouched — this is
    the same column `resolve_foundry_system_principal`'s own `WHERE
    es.is_active` check reads for the *external system registration*
    itself (a Phase 9 concept, migration 079), unrelated to the Phase 11
    workstream 2 credential this migration retires; clearing it would
    incorrectly also deactivate the registration's own (still-legitimate)
    identifier-mapping and combat-sync history.

    No schema change: both columns (migration 089/092) are left in place,
    per Workstream 11R item 7/finding 2's "keep old schema columns
    temporarily" — `resolve_foundry_system_principal`/`hash_foundry_
    system_key` remain defined in the domain layer even though nothing in
    the API layer calls them any more, and dropping the columns now would
    foreclose that option for no benefit, since a NULL `system_key_hash`
    already cannot authenticate anything (`resolve_foundry_system_
    principal`'s own `WHERE es.system_key_hash = :hash` never matches
    NULL).

Rollback:
    Supported, but a genuine no-op on the data: there is no way to restore
    a hash that was cleared (nor would doing so be safe — a downgrade must
    not silently reintroduce a defect this migration exists to close). The
    `downgrade()` function exists only for alembic's own linear-history
    bookkeeping; it deliberately performs no `UPDATE` of its own. Every
    external system this migration revoked stays revoked after a
    downgrade — the same "acceptable, and correct, for a downgrade"
    reasoning migration `092_foundry_key_principal`'s own docstring already
    establishes for its identical clear-every-existing-binding forward
    migration.

Locking considerations:
    A single `UPDATE ... WHERE system_key_hash IS NOT NULL` against
    `integration.external_systems` — the same small, adapter-facing table
    (one row per registered external system) migration 089/092's own
    schema changes already reasoned is not expected to hold a lock for
    material duration.

See: database/migrations/versions/089_foundry_system_credentials.py
     (system_key_hash's own creation)
     database/migrations/versions/092_foundry_key_principal.py
     (system_key_principal_user_id — the identical "every existing row
     loses its binding" data-implications shape this migration repeats)
     src/dnd_ai/api/auth.py (get_authenticated_user_id — the code-level
     half of this same correction: unconditional FoundrySystem rejection)
     src/dnd_ai/api/integration.py (issue_foundry_system_key_endpoint's
     removal — legacy issuance is no longer reachable over HTTP either)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "102_revoke_foundry_system_keys"
down_revision = "101_change_log_foundry_pairing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    op.execute("""
        UPDATE integration.external_systems
        SET system_key_hash = NULL,
            system_key_principal_user_id = NULL
        WHERE system_key_hash IS NOT NULL;
    """)


def downgrade() -> None:
    """Revert the migration.

    Deliberately a no-op on data — see this module's own "Rollback"
    section above for why a cleared FoundrySystem key is never restored.
    """
