"""Add description length bound to security.access_groups

Revision ID: 106_access_group_desc_length
Revises: 105_access_group_status
Create Date: 2026-09-20 12:00:00.000000

Purpose:
    Phase 13E-B checkpoint-6 correction. `security.access_groups.
    description` has been unrestricted `TEXT` since revision 080 — unlike
    `name` (`ck_access_groups_name_length`, 1-200 characters, that same
    revision), no length bound exists on `description` at all.
    `dnd_ai.commands.access_groups.create_access_group()`/
    `update_access_group()` already trim `description` and normalize a
    blank result to `NULL`, but nothing stopped an unbounded string, or an
    empty string, from ever reaching this column — through the
    application (closed together with this revision by the matching
    Pydantic `Field(max_length=...)` at the API layer, `dnd_ai.api.
    access_groups`, and by `dnd_ai.commands.access_groups`'s own
    pre-check, `AccessGroupDescriptionTooLongError`) or a direct database
    write bypassing both.

    This revision adds `ck_access_groups_description_length`, mirroring
    `ck_access_groups_name_length`'s own shape: `description IS NULL OR
    char_length(description) BETWEEN 1 AND 2000` — a `NULL` description
    remains legal (the normalized "no description" case), but a non-`NULL`
    one must be 1-2000 characters, matching `dnd_ai.commands.access_groups.
    ACCESS_GROUP_DESCRIPTION_MAX_LENGTH` exactly.

Production-safety correction (this revision's own record — not a new
migration):
    Revisions 080 through 105 enforced no bound on `description` at all,
    so a database that already has real `security.access_groups` rows by
    the time this revision runs may contain either legal-at-the-time value
    this new `CHECK` would reject: an empty string (`''` — legal before
    this revision; the application's own blank-to-`NULL` normalization is
    an API/command-layer convention, never enforced by the schema itself
    before now) or a description longer than 2000 characters (no bound
    existed to stop one). The first cut of this migration added the
    `CHECK` immediately, unconditionally validating — which would abort
    the 105->106 upgrade outright, mid-deployment, on any database
    carrying either value, surfacing only a generic, unhelpful
    `CheckViolation` with no indication of which row(s) are responsible or
    what to do about it.

    This revision now applies an explicit, deliberate legacy-data policy
    instead, in this order:

    1. **The constraint is added `NOT VALID` *first*, before anything
       else.** `ALTER TABLE ... ADD CONSTRAINT ... CHECK (...) NOT VALID`
       takes a brief `ACCESS EXCLUSIVE` lock for the metadata change only
       (no scan) — but that lock still has to wait for every transaction
       already holding a weaker lock on `security.access_groups` (an
       in-flight `INSERT`/`UPDATE` from a still-running old application
       instance during a rolling deployment, say) to commit or roll back
       first, and once granted it blocks any *new* writer from starting
       until this migration's own transaction ends. This ordering is
       itself the concurrency fix — see "Concurrency guarantee" below for
       why running this step first, rather than after the preflight below,
       is what closes the race this revision corrects.
    2. **The read-only over-length preflight runs second, in the same
       transaction, immediately after step 1's lock is granted.** It never
       silently truncates: no authoritative document in this repository
       (`docs/DATABASE_CONVENTIONS.md`, `docs/ENTITY_LIFECYCLE.md`,
       `docs/PHASE13E_ACCESS_CONTRACT.md`) approves truncation as a data
       policy anywhere, and destroying real, user-authored text with no
       way to recover it is not a decision this migration is entitled to
       make silently. Instead it runs a read-only precondition check
       (mirroring `103_login_failure_audit_action`'s own
       conditional-downgrade precedent: a Python-side `SELECT` via
       `op.get_bind()`, not a raw-SQL `RAISE EXCEPTION`) for any `security.
       access_groups` row whose `description` exceeds 2000 characters. If
       any exist, it raises `RuntimeError` naming the exact
       `access_group_id`s affected (a stable, non-sensitive identifier —
       never the description text itself, arbitrary free-form content
       that may be sensitive) and instructing the operator to shorten or
       clear each one, then re-run the migration. Because this raise
       happens inside the same transaction that added the `NOT VALID`
       constraint in step 1, PostgreSQL rolls the whole transaction back
       on the way out — the constraint is undone along with everything
       else, and nothing in the database is left changed, so a failed
       attempt is always safe to retry after the data is fixed.
    3. **Empty-string descriptions are backfilled to `NULL` third, only
       once the preflight has passed.** This is not a new, invented
       normalization — it is the exact rule `dnd_ai.commands.
       access_groups.create_access_group()`/`update_access_group()` have
       already applied to every description passing through the
       application since checkpoint 6 first shipped ("a blank result [is]
       stored as NULL rather than an empty string"). Retroactively
       applying that same, already-documented, already-accepted rule to
       pre-existing rows destroys no textual content — an empty string
       carries none — and makes every row consistent with the invariant
       the application already guarantees going forward. This is the one
       and only data-mutating step this revision performs, and it must
       run before step 4 (`VALIDATE CONSTRAINT` would otherwise fail on
       any legacy `''`, which the `CHECK` treats as invalid — only `NULL`
       or 1-2000 characters pass).
    4. **`VALIDATE CONSTRAINT` runs fourth**, separately from `ADD
       CONSTRAINT` (never combined into one direct, validating `ADD
       CONSTRAINT ... CHECK (...)`). Its own scan takes only `SHARE UPDATE
       EXCLUSIVE`, which blocks other DDL but not ordinary reads or writes
       — unlike a plain `ADD CONSTRAINT ... CHECK (...)`, which holds
       `ACCESS EXCLUSIVE` (blocking every read and write) for the entire
       scan. Revision 105's own "Locking considerations" note ("not a
       concern at this data volume") reflected this checkpoint having no
       production deployment yet; this correction no longer assumes that.
       The scan is guaranteed to find nothing by the time it runs — steps
       2 and 3 already proved and enforced that no violating row remains,
       in the same transaction — so this step is chosen for lock behavior,
       not because validation might still fail here.
    5. **The column `COMMENT` is applied last**, once the constraint is
       fully installed and validated.

    Concurrency guarantee (why step 1 must come before step 2, not after):
    An earlier version of this revision ran the preflight *before* `ADD
    CONSTRAINT`. That left a real window during a rolling deployment: an
    old application instance, or a direct writer, could commit an empty or
    over-2000-character `description` *after* the preflight's `SELECT` had
    already run clean but *before* `ADD CONSTRAINT` took its lock — nothing
    in that ordering forced such a writer to wait. The later `VALIDATE
    CONSTRAINT` scan would then find that row and fail with a generic
    `CheckViolation`, bypassing this migration's own actionable,
    non-destructive error entirely — the identical class of surprise this
    whole revision exists to prevent, just moved one step later. Installing
    `ADD CONSTRAINT ... NOT VALID` *first* closes that window, by ordinary
    PostgreSQL lock semantics with no extra code required:
    - Any writer already in flight when `ADD CONSTRAINT` runs holds a
      lock (e.g. `ROW EXCLUSIVE` from its own `INSERT`/`UPDATE`) that
      conflicts with the `ACCESS EXCLUSIVE` `ADD CONSTRAINT` needs. `ADD
      CONSTRAINT` waits for that writer to commit or roll back before it
      can proceed — so by the time it (and therefore the preflight
      `SELECT` immediately after it, in the same transaction and the same
      `READ COMMITTED` snapshot rules) actually runs, that writer's
      outcome — including any row it committed — is already visible.
    - Any writer that attempts to start *after* `ADD CONSTRAINT` has
      already taken its lock is itself blocked, queued behind this
      migration's own transaction, until that transaction commits or rolls
      back. If it goes on to commit successfully (this migration's
      transaction reaches step 4 and 5 and commits), that writer's own
      `INSERT`/`UPDATE` is then evaluated against the now-fully-installed
      `CHECK` the moment it is finally allowed to run — a `NOT VALID`
      constraint still fully enforces itself against every new write from
      the instant `ADD CONSTRAINT` adds it; only *pre-existing* rows are
      exempt from validation until `VALIDATE CONSTRAINT` runs. An invalid
      write queued behind this migration is therefore rejected with an
      ordinary constraint violation the instant it unblocks, never
      silently admitted.
    No invalid `description` can therefore ever reach `VALIDATE
    CONSTRAINT` undetected: every one either commits early enough to be
    caught by the preflight (and blocks the whole migration, deliberately
    and actionably), or attempts to commit late enough to be rejected by
    the constraint itself (and fails on its own, independently of this
    migration). `tests/database/
    test_access_group_description_length_migration.py`'s two-connection
    concurrency tests exercise both halves of this guarantee directly
    against real PostgreSQL locks (via `SET LOCAL lock_timeout`, the same
    deterministic-blocking idiom already established in
    `tests/database/test_membership_role_concurrency.py`), not just the
    single-connection sequential path the rest of that file covers.

Forward migration:
    - `ALTER TABLE security.access_groups ADD CONSTRAINT
      ck_access_groups_description_length CHECK (description IS NULL OR
      char_length(description) BETWEEN 1 AND 2000) NOT VALID` (see policy
      step 1 above — this now runs *first*).
    - Precondition check: any `security.access_groups.description` longer
      than 2000 characters aborts `upgrade()` with `RuntimeError`,
      rolling back the `ADD CONSTRAINT` above along with everything else
      (see policy step 2 and "Concurrency guarantee" above).
    - `UPDATE security.access_groups SET description = NULL WHERE
      description = ''` (see policy step 3 above).
    - `VALIDATE CONSTRAINT ck_access_groups_description_length` (see
      policy step 4 above).
    - Updates the column's own `COMMENT` to document the new bound,
      matching the Core metadata `Column` comment in
      `src/dnd_ai/persistence/tables/security.py` word for word — `alembic
      check` compares comments unconditionally, so the two must agree
      exactly (the same discipline revision 105 already followed for
      `lifecycle_status_id`'s own comment).

Rollback:
    Supported. Drops the constraint and clears the column comment back to
    revision 080's original (none). Does **not** attempt to restore an
    empty string where `upgrade()` backfilled one to `NULL` — that
    backfill is one-way by design: nothing before this revision ever
    distinguished "originally NULL" from "originally empty string" as a
    meaningful difference (the schema enforced no such distinction, and
    the application already treats them identically), so there is nothing
    a downgrade could correctly restore even in principle.

Data implications:
    Normalizes any existing empty-string `description` to `NULL` (policy
    step 3) — see "Production-safety correction" above for why this is
    safe and not a new policy. Blocks (via `RuntimeError`, not a schema
    change) if any row's `description` exceeds 2000 characters, requiring
    manual resolution before this migration can proceed on that database.
    A repository/CI database, and any environment with no `security.
    access_groups` rows yet, is unaffected by either case in practice.

Locking considerations:
    See "Production-safety correction" steps 1 and 4, and "Concurrency
    guarantee", above: `ADD CONSTRAINT ... NOT VALID` is a brief `ACCESS
    EXCLUSIVE` metadata-only change — but it waits for any writer already
    in flight against `security.access_groups` to finish first, and holds
    that lock for the rest of this migration's own transaction, blocking
    any new writer until this migration commits or rolls back. This is a
    real, deliberate difference from revision 105's own "not a concern at
    this data volume" note: that reflected this checkpoint having no
    production deployment yet, and this revision no longer assumes that.
    The separate `VALIDATE CONSTRAINT` afterward takes only `SHARE UPDATE
    EXCLUSIVE`, permitting concurrent reads and writes against `security.
    access_groups` for the scan's duration. The empty-string backfill
    `UPDATE` takes ordinary row locks only, exactly like any other
    application write to this table.

See: src/dnd_ai/commands/access_groups.py (ACCESS_GROUP_DESCRIPTION_MAX_LENGTH,
     AccessGroupDescriptionTooLongError, the matching pre-check)
     src/dnd_ai/api/access_groups.py (the matching Pydantic Field max_length)
     src/dnd_ai/persistence/tables/security.py (the matching declared
     column comment)
     database/migrations/versions/080_security_identity_and_access.py
     (ck_access_groups_name_length's own precedent)
     database/migrations/versions/105_access_group_status.py (this
     revision's parent — lifecycle_status_id, added the same checkpoint)
     database/migrations/versions/103_login_failure_audit_action.py (the
     "Python-side read-only precondition check, raise RuntimeError with an
     actionable message before any destructive statement" precedent this
     revision's own precondition check follows)
     tests/database/test_access_group_description_length_migration.py
     (single-connection upgrade/downgrade/re-upgrade coverage for this
     exact revision, including the blocked-upgrade/resolve/retry path,
     the final constraint's rejection of a new invalid direct write, and
     the two-connection real-lock concurrency tests proving the
     "Concurrency guarantee" above)
     tests/database/test_membership_role_concurrency.py (the `SET LOCAL
     lock_timeout` deterministic-blocking idiom this revision's own
     concurrency tests reuse)
"""

import uuid

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = "106_access_group_desc_length"
down_revision = "105_access_group_status"
branch_labels = None
depends_on = None

# Must match src/dnd_ai/persistence/tables/security.py's access_groups.c.description
# Column comment exactly — alembic check compares comments unconditionally.
_DESCRIPTION_COMMENT = (
    "Optional free-text description; when present, 1-2000 characters "
    "(ck_access_groups_description_length, migration 106). A blank value "
    "normalizes to NULL before storage (dnd_ai.commands.access_groups."
    "create_access_group/update_access_group), never stored as an empty "
    "string."
)

_DESCRIPTION_MAX_LENGTH = 2000

# Never inlined into the f-string at the raise site — a message this long
# is easier to review, and to keep in sync with the module docstring above,
# as one named constant with an explicit {ids}/{count} substitution point.
_OVER_LENGTH_ERROR_TEMPLATE = (
    "Cannot add ck_access_groups_description_length: {count} security.access_groups "
    "row(s) already have a description longer than {max_length} characters, predating "
    "any length bound (revisions 080-105 enforced none). These are not silently "
    "truncated — that would destroy user-authored text with no way to recover it, and "
    "no authoritative design in this repository approves truncation as a data policy. "
    "Affected access_group_id(s): {ids}. For each one, shorten its description to "
    "{max_length} characters or fewer, or clear it (UPDATE security.access_groups SET "
    "description = NULL WHERE access_group_id = '<id>') — a decision for whoever owns "
    "that content, not this migration — then re-run this migration. Nothing in the "
    "database has been changed by this failed attempt."
)

# Caps how many ids the error message spells out directly — the count is
# always exact regardless; this only bounds the id list's own size for an
# unusually large violation set, the identical "count + capped sample"
# shape dnd_ai.api.access_groups._bounded_id_sample uses for the unrelated
# deactivation-audit correction.
_ERROR_ID_SAMPLE_LIMIT = 20


def _over_length_access_group_ids() -> list[uuid.UUID]:
    """Read-only precondition check, run before any statement below that
    could change the database — mirrors `103_login_failure_audit_action.
    _denied_change_action_is_referenced()`'s identical "Python-side
    SELECT via op.get_bind(), not a raw-SQL RAISE EXCEPTION" shape.
    Ordered by `access_group_id` so a re-run against the same unresolved
    data reports the same rows in the same order."""
    bind = op.get_bind()
    return list(
        bind.execute(
            text("""
                SELECT access_group_id FROM security.access_groups
                WHERE description IS NOT NULL AND char_length(description) > :max_length
                ORDER BY access_group_id
            """),
            {"max_length": _DESCRIPTION_MAX_LENGTH},
        )
        .scalars()
        .all()
    )


def _format_id_sample(ids: list[uuid.UUID]) -> str:
    sample = ids[:_ERROR_ID_SAMPLE_LIMIT]
    formatted = ", ".join(str(access_group_id) for access_group_id in sample)
    if len(ids) > len(sample):
        formatted += f", and {len(ids) - len(sample)} more"
    return formatted


def upgrade() -> None:
    """Apply the migration. See this module's own "Production-safety
    correction" docstring section — especially "Concurrency guarantee" —
    for why the steps below run in exactly this order: ADD CONSTRAINT ...
    NOT VALID *first*, so its ACCESS EXCLUSIVE lock forces any in-flight
    writer to finish (and any new writer to wait) before the over-length
    preflight ever runs, then the preflight (never truncating; blocking
    deliberately and actionably instead), then the empty-string-to-NULL
    backfill (the application's own pre-existing, documented
    normalization, applied retroactively), then VALIDATE CONSTRAINT, then
    the column comment. Running the preflight before ADD CONSTRAINT — this
    revision's own first cut — left a window where a concurrent writer
    could commit an invalid description after the preflight passed but
    before the lock was taken, surfacing only a generic CheckViolation
    from VALIDATE CONSTRAINT instead of this migration's actionable error;
    this order closes that window using ordinary PostgreSQL lock
    semantics, no extra code required. If the preflight raises, this
    migration's own transaction rolls back — undoing the NOT VALID
    constraint along with everything else — so a failed attempt always
    leaves the database exactly as it found it."""
    op.execute("""
        ALTER TABLE security.access_groups
        ADD CONSTRAINT ck_access_groups_description_length
        CHECK (description IS NULL OR char_length(description) BETWEEN 1 AND 2000)
        NOT VALID;
    """)

    over_length_ids = _over_length_access_group_ids()
    if over_length_ids:
        raise RuntimeError(
            _OVER_LENGTH_ERROR_TEMPLATE.format(
                count=len(over_length_ids),
                max_length=_DESCRIPTION_MAX_LENGTH,
                ids=_format_id_sample(over_length_ids),
            )
        )

    op.execute("UPDATE security.access_groups SET description = NULL WHERE description = '';")

    op.execute("""
        ALTER TABLE security.access_groups
        VALIDATE CONSTRAINT ck_access_groups_description_length;
    """)
    op.execute(f"""
        COMMENT ON COLUMN security.access_groups.description IS
        '{_DESCRIPTION_COMMENT}';
    """)


def downgrade() -> None:
    """Revert the migration. Does not attempt to restore an empty string
    where upgrade() backfilled one to NULL — see this module's own
    "Rollback" docstring section for why there is nothing to correctly
    restore."""
    op.execute("COMMENT ON COLUMN security.access_groups.description IS NULL;")
    op.execute("""
        ALTER TABLE security.access_groups
        DROP CONSTRAINT IF EXISTS ck_access_groups_description_length;
    """)
