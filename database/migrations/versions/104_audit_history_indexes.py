"""Add audit.change_log(record_id) index for the campaign audit-history query

Revision ID: 104_audit_history_indexes
Revises: 103_login_failure_audit_action
Create Date: 2026-09-19 09:00:00.000000

Purpose:
    Phase 13E-B audit-history workstream (`dnd_ai.queries.audit_history`,
    `dnd_ai.api.audit_history`). That query resolves an exact campaign
    scope for a curated `audit.change_log` slice by joining each row back
    to the real table its own `schema_name`/`table_name` name, via
    `record_id = <that table>.<primary key>` — six such joins (one per
    branch of a `UNION ALL`), against `security.campaign_memberships`,
    `.membership_roles`, `.membership_character_relationships`,
    `.resource_grants`, `.campaign_invitations`, and `campaign.campaigns`.
    `audit.change_log` had no index on `record_id` at all before this
    migration (docs/DATABASE_CONVENTIONS.md §19.1: "Add indexes for
    foreign keys used in joins, filtering, or deletes" — `record_id` is
    not a foreign key by design, per that column's own comment in
    `007_audit_change_log` ("Rows outlive the records they describe, so
    the columns identifying those records carry no foreign keys"), but the
    same indexing rationale applies to a column this heavily joined on).
    Every campaign scoped by the query above already has cheap access to
    its own `campaign_id` via one of these six tables' existing indexes
    (e.g. `ix_campaign_memberships_campaign_id`,
    `ix_resource_grants_campaign_id`) — PostgreSQL's planner can push the
    audit-history query's `resolved_campaign_id = :campaign_id` predicate
    down into each branch and drive the join from the small, already-
    indexed campaign-scoped side; without an index on `change_log.
    record_id` the other side of that join falls back to a full scan of
    `audit.change_log`, an append-only table with no natural upper bound
    on size.

Forward migration:
    `CREATE INDEX ix_change_log_record_id ON audit.change_log (record_id)
    WHERE record_id IS NOT NULL` — a partial index, matching every other
    nullable-column index in this codebase (`record_id` is nullable per
    its own migration 007 comment: "Unconstrained by design").

Rollback:
    Supported. Drops the index.

Data implications:
    None — index-only change.

Locking considerations:
    A plain (non-`CONCURRENTLY`) `CREATE INDEX`, matching this codebase's
    own established convention for an index added after its table already
    exists (e.g. `098_ai_domain_fk_indexes`) — this is a pre-production
    schema with no live deployment yet, so a brief `ACCESS SHARE`-blocking
    `CREATE INDEX` (which still permits concurrent reads) costs nothing in
    practice.

See: src/dnd_ai/persistence/tables/audit.py (the matching declared Index)
     src/dnd_ai/queries/audit_history.py (the query this index backs)
     docs/AUDIT_HISTORY_API.md (the endpoint contract)
     database/migrations/versions/007_audit_change_log.py (the table)
     database/migrations/versions/098_ai_domain_fk_indexes.py (the identical
     plain-CREATE-INDEX precedent this migration follows)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "104_audit_history_indexes"
down_revision = "103_login_failure_audit_action"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""
    op.execute(
        "CREATE INDEX ix_change_log_record_id ON audit.change_log (record_id) "
        "WHERE record_id IS NOT NULL;"
    )


def downgrade() -> None:
    """Revert the migration."""
    op.execute("DROP INDEX audit.ix_change_log_record_id;")
