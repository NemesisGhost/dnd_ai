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

Forward migration:
    Seeds one new `audit.change_actions` row (`code = 'denied'`) via the
    existing idempotent `apply_seed` mechanism (docs/DATABASE_CONVENTIONS.md
    §25.4) — re-running the full `audit.change_actions` seed file is a
    no-op for the six rows revision 007 already inserted (`ON CONFLICT
    (code) DO NOTHING`) and inserts only the new one. No table or column
    changes: `audit.change_log`'s existing columns (`actor_service`,
    `changed_fields`, and the rest) already fully represent this event —
    see docs/DATABASE_CONVENTIONS.md §24 and revision 007's own schema.

Rollback:
    Supported. Deletes the `denied` row by code — safe only because
    nothing yet references it by foreign key (`audit.change_log.
    change_action_id` does, but only rows this same deployment's own audit
    writes would have created since this migration applied; a downgrade
    immediately after upgrade, before any login failure has occurred, has
    nothing referencing it to break). A production downgrade after real
    failed-login audit rows have accumulated would violate `audit.
    change_log`'s `change_action_id` foreign key — the same class of
    caveat every lookup-row-removing downgrade in this codebase carries.

Data implications:
    Seeds one row. No other rows created, updated, or removed.

Locking considerations:
    None. A single-row `INSERT ... ON CONFLICT DO NOTHING` against a small,
    already-existing lookup table.

See: database/migrations/versions/007_audit_change_log.py (the table and
     the original six seeded codes)
     database/seeds/audit.change_actions.yaml (the seed file this
     migration re-applies)
     docs/DATABASE_CONVENTIONS.md §24 (audit conventions)
     src/dnd_ai/api/local_auth.py (the local-auth/session audit call sites
     this code, and the pre-existing six, are used from)
"""

from alembic import op

from dnd_ai.persistence.seeds import apply_seed

# revision identifiers, used by Alembic.
revision = "103_login_failure_audit_action"
down_revision = "102_revoke_foundry_system_keys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""
    apply_seed(op, "audit", "change_actions")


def downgrade() -> None:
    """Revert the migration."""
    op.execute("DELETE FROM audit.change_actions WHERE code = 'denied';")
