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

    1. **Empty-string descriptions are backfilled to `NULL`.** This is not
       a new, invented normalization — it is the exact rule `dnd_ai.
       commands.access_groups.create_access_group()`/`update_access_group()`
       have already applied to every description passing through the
       application since checkpoint 6 first shipped ("a blank result
       [is] stored as NULL rather than an empty string"). Retroactively
       applying that same, already-documented, already-accepted rule to
       pre-existing rows destroys no textual content — an empty string
       carries none — and makes every row consistent with the invariant
       the application already guarantees going forward. This is the one
       and only data-mutating step this revision performs.
    2. **An over-2000-character description blocks the upgrade outright,
       deliberately and actionably, before any schema change.** Silently
       truncating a legacy description to fit would destroy real,
       user-authored text with no way to recover it, and no authoritative
       document in this repository (`docs/DATABASE_CONVENTIONS.md`,
       `docs/ENTITY_LIFECYCLE.md`, `docs/PHASE13E_ACCESS_CONTRACT.md`)
       approves silent truncation as a data policy anywhere — so this
       migration never does it. Instead, `upgrade()` runs a read-only
       precondition check (mirroring `103_login_failure_audit_action`'s
       own conditional-downgrade precedent: a Python-side `SELECT` via
       `op.get_bind()`, not a raw-SQL `RAISE EXCEPTION`) for any `security.
       access_groups` row whose `description` exceeds 2000 characters
       *before* the empty-string backfill or the `ADD CONSTRAINT` ever
       run. If any exist, it raises `RuntimeError` naming the exact
       `access_group_id`s affected (a stable, non-sensitive identifier —
       never the description text itself, arbitrary free-form content
       that may be sensitive) and instructing the operator to shorten or
       clear each one, then re-run the migration. Nothing in the database
       changes when this happens — not even the harmless empty-string
       backfill — so a failed attempt is always safe to retry after the
       data is fixed.
    3. **The constraint is added `NOT VALID`, then validated separately**
       (`VALIDATE CONSTRAINT`), not as one direct, validating `ADD
       CONSTRAINT ... CHECK (...)`. `ADD CONSTRAINT` (even `NOT VALID`)
       takes a brief `ACCESS EXCLUSIVE` lock only for the metadata change;
       `VALIDATE CONSTRAINT`'s own scan takes only `SHARE UPDATE
       EXCLUSIVE`, which blocks other DDL but not ordinary reads or
       writes against `security.access_groups` — unlike a plain `ADD
       CONSTRAINT ... CHECK (...)`, which holds `ACCESS EXCLUSIVE` (blocking
       every read and write) for the entire scan. Revision 105's own
       "Locking considerations" note ("not a concern at this data volume")
       reflected this checkpoint having no production deployment yet; this
       correction no longer assumes that, since the very defect it fixes
       is that assumption failing to hold. The `VALIDATE CONSTRAINT` scan
       is guaranteed to find nothing by the time it runs — step 2's
       precondition check already proved no violating row exists, in the
       same transaction — so this sequence is chosen for lock behavior,
       not because validation might still fail here.

Forward migration:
    - Precondition check: any `security.access_groups.description` longer
      than 2000 characters aborts `upgrade()` with `RuntimeError` before
      any statement below runs.
    - `UPDATE security.access_groups SET description = NULL WHERE
      description = ''` (see policy step 1 above).
    - `ALTER TABLE security.access_groups ADD CONSTRAINT
      ck_access_groups_description_length CHECK (description IS NULL OR
      char_length(description) BETWEEN 1 AND 2000) NOT VALID`, then
      `VALIDATE CONSTRAINT ck_access_groups_description_length` (see
      policy step 3 above).
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
    step 1) — see "Production-safety correction" above for why this is
    safe and not a new policy. Blocks (via `RuntimeError`, not a schema
    change) if any row's `description` exceeds 2000 characters, requiring
    manual resolution before this migration can proceed on that database.
    A repository/CI database, and any environment with no `security.
    access_groups` rows yet, is unaffected by either case in practice.

Locking considerations:
    See "Production-safety correction" step 3 above: `ADD CONSTRAINT ...
    NOT VALID` is a brief `ACCESS EXCLUSIVE` metadata-only change; the
    separate `VALIDATE CONSTRAINT` takes only `SHARE UPDATE EXCLUSIVE`,
    permitting concurrent reads and writes against `security.
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
     (single-step upgrade/downgrade/re-upgrade coverage for this exact
     revision, including the blocked-upgrade/resolve/retry path and the
     final constraint's rejection of a new invalid direct write)
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
    correction" docstring section for the full legacy-data policy this
    implements — in short: block deliberately and actionably on an
    over-length description (never truncate it), backfill an empty-string
    description to NULL (the application's own pre-existing, documented
    normalization, applied retroactively), then add the constraint via
    NOT VALID/VALIDATE CONSTRAINT rather than one direct, validating ADD
    CONSTRAINT, for lock behavior on a database that may already carry
    real rows."""
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
        ADD CONSTRAINT ck_access_groups_description_length
        CHECK (description IS NULL OR char_length(description) BETWEEN 1 AND 2000)
        NOT VALID;
    """)
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
