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
    Conditionally supported (second correction — see "Conditional downgrade
    policy" below). Deletes the `denied` row by code, the complete, correct
    inverse of the `INSERT` above — but only once a read-only precondition
    check confirms nothing in `audit.change_log` still references it.
    `audit.change_log.change_action_id REFERENCES audit.change_actions
    (change_action_id) ON DELETE RESTRICT` (revision `007_audit_change_
    log`) would itself refuse the `DELETE` once a real `denied` row exists,
    but letting that surface as a raw foreign-key-violation error is not
    "reverse those changes safely" — an operator sees a generic constraint
    error, not why, or what to do about it. `downgrade()` now checks first
    and raises a specific, actionable `RuntimeError` before touching
    anything, so a downgrade that cannot safely proceed never gets far
    enough to leave a partial change behind either.

Conditional downgrade policy:
    - No `audit.change_log` row anywhere yet has `change_action_id`
      resolving to `code = 'denied'` (the common case: no failed login has
      ever been recorded, or the deployment predates real traffic):
      `downgrade()` deletes the `denied` row and exits successfully — the
      exact pre-103 `audit.change_actions` content is restored.
    - One or more `audit.change_log` rows already reference `denied`:
      `downgrade()` raises `RuntimeError` immediately, before the `DELETE`
      (or anything else) runs, and changes nothing. The message states
      plainly that (a) the downgrade cannot proceed because durable
      `denied` security-audit history exists, (b) those records are never
      deleted or relabeled to force it through — reassigning them to an
      existing code such as `failed`/`rejected`/`error` would misrepresent
      what actually happened just as much as deleting them would, silently
      corrupting audit history a security review may depend on — and (c)
      rolling back past this revision in that situation requires restoring
      a database backup taken before `103_login_failure_audit_action` was
      applied, not an Alembic downgrade. The Alembic revision stays at 103,
      `audit.change_actions`'s `denied` row and every referencing
      `audit.change_log` row are untouched, and no other revision-103
      schema change is affected — this migration makes no schema change
      besides the one seeded row (see "Data implications" below).
    - The precondition check is a read-only `SELECT EXISTS (...)` against
      `audit.change_log` joined to `audit.change_actions` — it never
      disables, defers, or bypasses the `ON DELETE RESTRICT` foreign key
      itself; that constraint stays exactly as revision 007 defined it and
      would still refuse the `DELETE` on its own if this check were ever
      wrong. The check exists to fail with a clear explanation *before* a
      caller ever reaches that generic constraint error, not to replace
      the constraint as the actual safety mechanism.

Data implications:
    Seeds one row. No other rows created, updated, or removed.

Locking considerations:
    None. A single-row `INSERT ... ON CONFLICT DO NOTHING` against a small,
    already-existing lookup table.

See: database/migrations/versions/007_audit_change_log.py (the table, its
     own still-current `apply_seed` call, the frozen seed file this
     migration must never share content with again, and the `ON DELETE
     RESTRICT` foreign key the conditional downgrade check below exists to
     explain rather than replace)
     database/seeds/audit.change_actions.yaml (007's frozen input — the
     six original rows only)
     docs/DATABASE_CONVENTIONS.md §25.4 (the frozen-seed-file convention
     this migration originally violated)
     tests/database/test_login_failure_audit_action_migration.py (single-
     step upgrade/downgrade/re-upgrade coverage for this exact revision,
     the regression proof that 102 alone seeds only the original six
     codes, and the reversible/protected-history downgrade coverage for
     the conditional policy above)
     src/dnd_ai/api/local_auth.py (the local-auth/session audit call sites
     this code, and the pre-existing six, are used from)
"""

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = "103_login_failure_audit_action"
down_revision = "102_revoke_foundry_system_keys"
branch_labels = None
depends_on = None

# Kept as one literal, not re-derived from a query result, so the message
# downgrade() raises never depends on what it just read from the database —
# see that function's own docstring for the exact conditional policy this
# implements.
_DOWNGRADE_BLOCKED_BY_DENIED_HISTORY = (
    "Cannot downgrade revision 103_login_failure_audit_action: durable 'denied' "
    "security-audit history exists in audit.change_log. These records will not be "
    "deleted or relabeled to force the downgrade through — reassigning them to another "
    "change action (e.g. 'failed', 'rejected', 'error') would misrepresent what actually "
    "happened just as destructively as deleting them, corrupting audit history a security "
    "review may depend on. Rolling back past this revision requires restoring a database "
    "backup taken before 103_login_failure_audit_action was applied, not an Alembic "
    "downgrade."
)


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


def _denied_change_action_is_referenced() -> bool:
    """Read-only precondition check for `downgrade()` (never disables,
    defers, or bypasses `audit.change_log.change_action_id`'s own `ON
    DELETE RESTRICT` foreign key — see this module's "Conditional
    downgrade policy" docstring section) — `True` once at least one
    `audit.change_log` row's `change_action_id` resolves to `code =
    'denied'`, checked by joining rather than trusting any cached id,
    since a fresh downgrade run never assumes what `upgrade()` inserted
    this row as."""
    bind = op.get_bind()
    return bool(
        bind.execute(
            text("""
                SELECT EXISTS (
                    SELECT 1
                    FROM audit.change_log cl
                    JOIN audit.change_actions ca ON ca.change_action_id = cl.change_action_id
                    WHERE ca.code = 'denied'
                )
            """)
        ).scalar()
    )


def downgrade() -> None:
    """Revert the migration — conditionally. See this module's own
    "Conditional downgrade policy" docstring section for the full policy;
    in short: deletes the `denied` row and succeeds when nothing
    references it, or raises `RuntimeError` and changes nothing at all
    when durable `denied` audit history exists. The precondition check
    runs, and this function can still raise, before any destructive
    statement — a downgrade that cannot proceed safely never gets far
    enough to leave a partial change behind."""
    if _denied_change_action_is_referenced():
        raise RuntimeError(_DOWNGRADE_BLOCKED_BY_DENIED_HISTORY)
    op.execute("DELETE FROM audit.change_actions WHERE code = 'denied';")
