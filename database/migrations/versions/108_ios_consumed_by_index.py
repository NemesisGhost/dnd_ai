"""Add security.invitation_onboarding_sessions(consumed_by_user_id) index

Revision ID: 108_ios_consumed_by_index
Revises: 107_invitation_onboarding
Create Date: 2026-09-26 00:00:00.000000

Purpose:
    `107_invitation_onboarding` added `security.invitation_onboarding_
    sessions.consumed_by_user_id` (a foreign key to `security.users.
    user_id`) with no supporting index — a gap `tests/database/
    test_schema_documentation.py::test_every_foreign_key_is_indexed`
    exists specifically to catch (docs/DATABASE_CONVENTIONS.md §19.1: "Add
    indexes for foreign keys used in joins, filtering, or deletes"), missed
    when that migration landed since this table's own checkpoint didn't
    run the full cross-cutting schema-convention suite until later.

Forward migration:
    `CREATE INDEX ix_ios_consumed_by_user_id ON security.
    invitation_onboarding_sessions (consumed_by_user_id) WHERE
    consumed_by_user_id IS NOT NULL` — a partial index, matching
    `ix_change_log_record_id`'s identical precedent for a nullable foreign
    key column (most rows never reach `complete_invitation_onboarding` and
    so never populate this column at all).

Rollback:
    Supported. Drops the index.

Data implications:
    None — index-only change.

Locking considerations:
    A plain (non-`CONCURRENTLY`) `CREATE INDEX`, matching this codebase's
    own established convention for an index added after its table already
    exists (e.g. `098_ai_domain_fk_indexes`, `104_audit_history_indexes`) —
    this is a pre-production schema with no live deployment yet.

See: src/dnd_ai/persistence/tables/security.py (the matching declared Index)
     database/migrations/versions/107_invitation_onboarding.py (the table)
     database/migrations/versions/104_audit_history_indexes.py (the
     identical plain-CREATE-INDEX, partial-WHERE-NOT-NULL precedent this
     migration follows)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "108_ios_consumed_by_index"
down_revision = "107_invitation_onboarding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""
    op.execute(
        "CREATE INDEX ix_ios_consumed_by_user_id ON security.invitation_onboarding_sessions "
        "(consumed_by_user_id) WHERE consumed_by_user_id IS NOT NULL;"
    )


def downgrade() -> None:
    """Revert the migration."""
    op.execute("DROP INDEX security.ix_ios_consumed_by_user_id;")
