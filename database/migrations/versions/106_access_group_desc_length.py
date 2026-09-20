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
    blank result to `NULL`, but nothing stopped an unbounded string from
    ever reaching this column — through the application (closed together
    with this revision by the matching Pydantic `Field(max_length=...)` at
    the API layer, `dnd_ai.api.access_groups`, and by `dnd_ai.commands.
    access_groups`' own pre-check, `AccessGroupDescriptionTooLongError`) or
    a direct database write bypassing both.

    This revision adds `ck_access_groups_description_length`, mirroring
    `ck_access_groups_name_length`'s own shape: `description IS NULL OR
    char_length(description) BETWEEN 1 AND 2000` — a `NULL` description
    remains legal (the normalized "no description" case), but a non-`NULL`
    one must be 1-2000 characters, matching `dnd_ai.commands.access_groups.
    ACCESS_GROUP_DESCRIPTION_MAX_LENGTH` exactly, so the API-layer
    rejection, the command-layer pre-check, and this database constraint
    all agree on the same bound.

Forward migration:
    - `security.access_groups`: `ADD CONSTRAINT
      ck_access_groups_description_length CHECK (description IS NULL OR
      char_length(description) BETWEEN 1 AND 2000)` — a plain, immediately
      validated `CHECK` addition, not `NOT VALID`/`VALIDATE CONSTRAINT`,
      matching this codebase's own established convention for a new
      constraint on a table with no meaningful row volume at this project
      stage (`051_conditional_route_semantics`'s identical reasoning; see
      "Locking considerations" below).
    - Updates the column's own `COMMENT` to document the new bound,
      matching the Core metadata `Column` comment in
      `src/dnd_ai/persistence/tables/security.py` word for word — `alembic
      check` compares comments unconditionally, so the two must agree
      exactly (the same discipline revision 105 already followed for
      `lifecycle_status_id`'s own comment).

Rollback:
    Supported. Drops the constraint and clears the column comment back to
    revision 080's original (none).

Data implications:
    No `security.access_groups` rows exist outside test fixtures today
    (the same starting point revision 105 documented) — the validating
    scan this `CHECK` addition performs has nothing to actually check in
    practice, included for correctness against a future real deployment
    that has since created groups with long descriptions.

Locking considerations:
    `ADD CONSTRAINT ... CHECK` on this table takes a validating scan (a
    new constraint is never skipped), but the table is not large enough at
    this project stage for that to matter — the identical reasoning
    `051_conditional_route_semantics`/`105_access_group_status` already
    documented for their own additions.

See: src/dnd_ai/commands/access_groups.py (ACCESS_GROUP_DESCRIPTION_MAX_LENGTH,
     AccessGroupDescriptionTooLongError, the matching pre-check)
     src/dnd_ai/api/access_groups.py (the matching Pydantic Field max_length)
     src/dnd_ai/persistence/tables/security.py (the matching declared
     column comment)
     database/migrations/versions/080_security_identity_and_access.py
     (ck_access_groups_name_length's own precedent)
     database/migrations/versions/105_access_group_status.py (this
     revision's parent — lifecycle_status_id, added the same checkpoint)
     database/migrations/versions/051_conditional_route_semantics.py (the
     "plain CHECK, not NOT VALID, at this data volume" precedent)
"""

from alembic import op

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


def upgrade() -> None:
    """Apply the migration."""
    op.execute("""
        ALTER TABLE security.access_groups
        ADD CONSTRAINT ck_access_groups_description_length
        CHECK (description IS NULL OR char_length(description) BETWEEN 1 AND 2000);
    """)
    op.execute(f"""
        COMMENT ON COLUMN security.access_groups.description IS
        '{_DESCRIPTION_COMMENT}';
    """)


def downgrade() -> None:
    """Revert the migration."""
    op.execute("COMMENT ON COLUMN security.access_groups.description IS NULL;")
    op.execute("""
        ALTER TABLE security.access_groups
        DROP CONSTRAINT IF EXISTS ck_access_groups_description_length;
    """)
