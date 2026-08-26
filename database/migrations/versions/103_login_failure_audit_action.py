"""Add the 'denied' audit change action

Revision ID: 103_login_failure_audit_action
Revises: 102_revoke_foundry_system_keys
Create Date: 2026-08-25 09:00:00.000000

Purpose:
    Phase 13B blocker 3: durable security-action auditing for local-account
    and browser-session commands (login, logout, activation, password
    reset/change, administrative account disablement/reactivation/
    revoke-all-sessions). Every one of those events maps onto an existing
    `audit.change_actions` code except one: a failed login attempt produces
    no data change at all (no `security.browser_sessions` row is created,
    unlike a successful login), so none of the six existing codes —
    `created`, `updated`, `status_changed`, `archived`, `restored`,
    `deleted` — describe it; each of those names a completed data change,
    and a failed login is specifically the absence of one. This migration
    adds the single new code that gap requires — `denied` — rather than
    reusing a mismatched existing one or building a second, unrelated audit
    mechanism for failed attempts.

    `src/dnd_ai/api/local_auth.py`'s `_record_login_failure_audit` is the
    sole writer of rows with this code, on its own committed transaction —
    see that function's own docstring for why a failed login needs a
    transaction independent of the request's own (which rolls back on the
    same `UnauthorizedError` that reports the failure).

Forward migration (correction — see "Correction" below for what changed):
    A direct, explicit `INSERT ... ON CONFLICT (code) DO NOTHING` for the
    one new `audit.change_actions` row (`code = 'denied'`) — never
    `dnd_ai.persistence.seeds.apply_seed`/`database/seeds/
    audit.change_actions.yaml`. That file is revision `007_audit_change_
    log`'s own frozen input (docs/DATABASE_CONVENTIONS.md §25.4: "Once a
    migration applying a database/seeds/*.yaml file has been applied
    anywhere ..., that file is frozen: do not edit it ... To change or add
    content, add a new *.yaml file and a new migration") — 007's own
    `upgrade()` still calls `apply_seed(op, "audit", "change_actions")`
    every time it runs, re-reading that file's *current* content, not the
    six-row content it had when 007 was written. `dnd_ai.persistence.
    seeds.load_seed_data` resolves exactly one filename per table
    (`f"{schema}.{table}.yaml"`, no override), so there was never a way to
    add a *second*, appropriately-named seed file for this table through
    that mechanism without changing `dnd_ai.persistence.seeds` itself — out
    of scope for a single-table, single-row addition. An explicit,
    self-contained `INSERT` needs neither.

Correction (this migration's own record_id-adjacent security-audit-review
finding — not a new migration):
    This migration originally added its one new row by editing
    `database/seeds/audit.change_actions.yaml` in place (appending `code:
    denied`) and calling `apply_seed(op, "audit", "change_actions")`
    exactly as `007_audit_change_log` does — a direct violation of the
    frozen-seed-file rule above, and one with a concrete, observable
    consequence: because 007's `upgrade()` re-reads that same file's
    *current* content on every fresh database, 007 itself started
    inserting the `denied` row (via that file, before this migration ever
    ran), making this migration's own `apply_seed` call a permanent no-op.
    `downgrade()`, unaware of that, still unconditionally deleted the
    `denied` row — meaning `alembic downgrade 102_revoke_foundry_system_
    keys` (leaving 007 applied) incorrectly removed a row that, under the
    then-current seed file, 007 was actually responsible for; a database
    reporting revision 102 would then be missing a row every *other*
    database at revision 102 has. The seed file has been restored to its
    original, 007-era six-row content, and this migration now owns the
    `denied` row exclusively via the direct `INSERT` above — the only
    change of any kind revision 007 makes going forward.

Rollback:
    Supported. Deletes the `denied` row by code — this is now a complete,
    correct inverse of the `INSERT` above: nothing else in this migration's
    chain of ancestors inserts, references, or depends on that row.
    Safe only because nothing yet references it by foreign key (`audit.
    change_log.change_action_id` does, but only rows this same
    deployment's own audit writes would have created since this migration
    applied; a downgrade immediately after upgrade, before any login
    failure has occurred, has nothing referencing it to break). A
    production downgrade after real failed-login audit rows have
    accumulated would violate `audit.change_log`'s `change_action_id`
    foreign key — the same class of caveat every lookup-row-removing
    downgrade in this codebase carries.

Data implications:
    Seeds one row. No other rows created, updated, or removed.

Locking considerations:
    None. A single-row `INSERT ... ON CONFLICT DO NOTHING` against a small,
    already-existing lookup table.

See: database/migrations/versions/007_audit_change_log.py (the table, its
     own still-current `apply_seed` call, and the frozen seed file this
     migration must never share content with again)
     database/seeds/audit.change_actions.yaml (007's frozen input — the
     six original rows only)
     docs/DATABASE_CONVENTIONS.md §25.4 (the frozen-seed-file convention
     this migration originally violated)
     tests/database/test_login_failure_audit_action_migration.py (single-
     step upgrade/downgrade/re-upgrade coverage for this exact revision,
     plus the regression proof that 102 alone seeds only the original six
     codes)
     src/dnd_ai/api/local_auth.py (the local-auth/session audit call sites
     this code, and the pre-existing six, are used from)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "103_login_failure_audit_action"
down_revision = "102_revoke_foundry_system_keys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""
    op.execute("""
        INSERT INTO audit.change_actions (code, display_name, description, sort_order, is_active)
        VALUES (
            'denied',
            'Denied',
            'An attempted action was not authorized, or did not succeed, and produced no '
            'data change — for example a failed login attempt. Used when a security-'
            'relevant attempt must still be durably recorded even though none of the '
            'other change actions (which all describe a completed data change) apply.',
            70,
            true
        )
        ON CONFLICT (code) DO NOTHING;
    """)


def downgrade() -> None:
    """Revert the migration."""
    op.execute("DELETE FROM audit.change_actions WHERE code = 'denied';")
