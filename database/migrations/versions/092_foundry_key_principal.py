"""Bind a Foundry system credential to exactly one platform principal;
record untrusted Foundry-actor metadata separately

Revision ID: 092_foundry_key_principal
Revises: 091_change_log_ext_system
Create Date: 2026-08-19 18:00:00.000000

Purpose:
    Closes a Critical authentication design flaw in the Foundry-adapter
    credential model, distinct from (and more severe than) the workstream 2
    scope defect migrations 089-091 already closed. That correction bound a
    FoundrySystem credential to the world it authenticated for; it did not
    change the fact that the credential itself (`integration.
    external_systems.system_key_hash`) authenticates as *whichever* Foundry
    user id a caller names in the `X-Foundry-User-Id` header, resolved via
    `security.external_identities`. `foundry-module/scripts/settings.mjs`
    stores that same credential as a Foundry world-scoped `game.settings`
    value — distributed by Foundry itself to every client connected to the
    world, `config: false` notwithstanding (that only hides it from the
    settings UI; it does not make Foundry deliver it to fewer clients).
    Any connected player who extracts the shared credential from their own
    browser could therefore name the GM's own visible Foundry user id and
    authenticate as the GM — `game.user.isGM` is a client-side display
    check with no bearing on what an arbitrary HTTP client can send.

    Fixed at the credential model, not with additional client-side checks
    (per docs/PLAN.md Phase 11's "Second security correction," and
    `src/dnd_ai/domain/access.py`'s own docstring, which have the full
    account): a FoundrySystem credential now authenticates as exactly one
    platform principal, bound at issuance time
    (`dnd_ai.commands.integration.issue_foundry_system_key`, which now
    requires the caller to name an already-linked Foundry user id and
    resolves + stores the platform user it maps to) — never a client-
    selected one. This is intentionally the smallest change consistent
    with this MVP's own already-GM-only operational shape
    (`foundry-module/scripts/hooks.mjs`: "Exactly one client drives sync
    per world — the GM's"): the credential is issued for, and the module's
    connection setting is now stored client-scoped (this browser profile
    only, never distributed by Foundry to other clients) for, that one GM.
    Delegating to arbitrary *other* Foundry users (true per-player identity)
    is out of scope for this MVP and is not delivered — see foundry-module/
    README.md's corrected trust-boundary section.

    A Foundry user id supplied by the client (still sent, renamed
    `X-Foundry-Actor-Id` to make its new, purely-descriptive status
    unambiguous — see `dnd_ai.api.auth`) is no longer resolved to a
    `user_id` at all; it is recorded only as untrusted audit metadata
    (`audit.change_log.acting_foundry_actor_id`, this migration), never as
    the authorization principal — conventions §24.3's audit requirement is
    satisfied by *both* new columns together: `system_key_principal_user_id`
    is how the platform decides who is acting; `acting_foundry_actor_id` is
    what the client additionally claimed about it, kept clearly and
    permanently distinguishable from that decision.

Forward migration:
    `integration.external_systems`:
      - `system_key_principal_user_id UUID NULL REFERENCES security.users
        (user_id) ON DELETE SET NULL` — the one platform user this row's
        `system_key_hash` authenticates as. `NULL` until `issue_foundry_
        system_key` binds it (and for every row created before this
        migration) — `dnd_ai.domain.access.resolve_foundry_system_principal`
        now requires this to be non-NULL (and to name a currently-active
        user) before a presented key can authenticate at all, so an
        already-issued-but-unbound key (impossible going forward, since
        issuance and binding are now the same call) or a key whose bound
        user was deleted both fail closed rather than falling back to any
        client-supplied identity. `ON DELETE SET NULL`, not `RESTRICT`: a
        deleted platform user must not block deleting/retaining the
        external-system registration itself, and a credential that has lost
        its bound principal this way is exactly the "cannot authenticate
        until re-bound" state a brand-new, never-issued key is already in.
      - `ix_external_systems_system_key_principal_user_id`: a partial index
        (`WHERE system_key_principal_user_id IS NOT NULL`), the same "small
        adapter-facing table, index only the populated case" shape
        migration 091's own `ix_change_log_acting_external_system_id` uses
        — supports "which external systems currently authenticate as this
        user" without indexing the common NULL case.

    `audit.change_log`:
      - `acting_foundry_actor_id TEXT NULL` — the client-claimed,
        server-unverified Foundry-side actor id from the (renamed)
        `X-Foundry-Actor-Id` header, recorded alongside (never instead of)
        `actor_user_id`/`acting_external_system_id` for a change made
        through a delegated Foundry credential. No foreign key: unlike
        `acting_external_system_id`, this value is never looked up against
        any table — recording it as free text, exactly as received, is the
        point; validating or normalizing it would misrepresent it as
        trusted.

Rollback:
    Supported. Drops both new columns (and the new index) in reverse
    order. Any FoundrySystem credential's principal binding, and any
    already-recorded claimed-actor audit metadata, is lost on downgrade —
    acceptable for a downgrade, which already accepts losing the
    correction's own effect, exactly like migration 091's own rollback note
    for `acting_external_system_id`.

Data implications:
    Every existing `integration.external_systems` row gets
    `system_key_principal_user_id = NULL` — any `system_key_hash` issued
    before this migration can no longer authenticate anything (there is no
    data from which to safely infer which platform user it should be
    bound to) until a GM re-runs `issue_foundry_system_key` with an
    already-linked Foundry user id. This is the correct, safe outcome for
    a Critical authentication defect: the alternative (guessing a binding,
    or leaving the old client-selectable-identity path open as a fallback)
    would either bind incorrectly or fail to close the vulnerability this
    migration exists to fix. Every existing `audit.change_log` row gets
    `acting_foundry_actor_id = NULL` (metadata-only add, nothing to
    backfill).

Locking considerations:
    Both `ADD COLUMN` statements are metadata-only on PostgreSQL 11+ (no
    default, so no table rewrite). The `external_systems` `ADD CONSTRAINT
    ... FOREIGN KEY` requires a validation scan of that table, which is
    small, adapter-facing infrastructure (one row per registered external
    system — migration 089's own reasoning for its sibling constraint on
    the same table); `CREATE INDEX` (not `CONCURRENTLY`) on the same small
    table is likewise not expected to hold a lock for material duration.
    `audit.change_log` can be large and high-volume (migration 091's own
    note), but its new column carries no constraint of its own — nothing
    beyond the metadata-only `ADD COLUMN` touches it here.

See: database/migrations/versions/089_foundry_system_credentials.py
     (system_key_hash's own creation — this migration binds a principal to
     the same row rather than adding a parallel credential table)
     database/migrations/versions/091_change_log_ext_system.py
     (acting_external_system_id — the sibling audit column this migration's
     acting_foundry_actor_id is deliberately kept distinct from)
     src/dnd_ai/domain/access.py (resolve_foundry_system_principal — this
     column's only reader; AuthenticatedPrincipal.foundry_claimed_actor_id)
     src/dnd_ai/commands/integration.py (issue_foundry_system_key — this
     column's only writer)
     src/dnd_ai/api/audit.py (record_change_log — acting_foundry_actor_id's
     only writer)
     foundry-module/README.md ("Trust boundary" section — the client-side
     half of this correction)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "092_foundry_key_principal"
down_revision = "091_change_log_ext_system"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    op.execute("""
        ALTER TABLE integration.external_systems
            ADD COLUMN system_key_principal_user_id UUID
                REFERENCES security.users(user_id) ON DELETE SET NULL;
    """)
    op.execute("""
        COMMENT ON COLUMN integration.external_systems.system_key_principal_user_id IS
        'The one platform user this row''s system_key_hash authenticates as '
        '(dnd_ai.domain.access.resolve_foundry_system_principal). NULL until '
        'dnd_ai.commands.integration.issue_foundry_system_key binds it, or '
        'if the bound user is later deleted — a credential in either state '
        'cannot authenticate at all. Never a client-selected identity: this '
        'is the sole source of truth for which security.users row a '
        'FoundrySystem credential resolves to.';
    """)
    op.execute("""
        CREATE INDEX ix_external_systems_system_key_principal_user_id
        ON integration.external_systems (system_key_principal_user_id)
        WHERE system_key_principal_user_id IS NOT NULL;
    """)

    op.execute("""
        ALTER TABLE audit.change_log
            ADD COLUMN acting_foundry_actor_id TEXT;
    """)
    op.execute("""
        COMMENT ON COLUMN audit.change_log.acting_foundry_actor_id IS
        'The Foundry-side actor id the client claimed via X-Foundry-Actor-Id '
        'for a change made through a delegated FoundrySystem credential — '
        'recorded verbatim, never verified, never used to select or '
        'authorize the acting principal (that is acting_external_system_id '
        'plus the credential''s own bound system_key_principal_user_id). '
        'NULL for every OIDC-authenticated change and for any Foundry '
        'request that supplied no claimed actor.';
    """)


def downgrade() -> None:
    """Revert the migration."""

    op.execute("""
        ALTER TABLE audit.change_log
            DROP COLUMN IF EXISTS acting_foundry_actor_id;
    """)

    op.execute("DROP INDEX IF EXISTS integration.ix_external_systems_system_key_principal_user_id;")
    op.execute("""
        ALTER TABLE integration.external_systems
            DROP COLUMN IF EXISTS system_key_principal_user_id;
    """)
