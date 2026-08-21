"""Add the eleven missing foreign-key indexes in the Phase 12 AI domain.

Revision ID: 098_ai_domain_fk_indexes
Revises: 097_advance_objective_kind
Create Date: 2026-08-20 15:00:00.000000

Purpose:
    tests/database/test_schema_documentation.py::test_every_foreign_key_is_indexed
    enforces docs/DATABASE_CONVENTIONS.md §19.1 ("PostgreSQL does not
    automatically index foreign-key columns. Add indexes for foreign keys
    used in joins, filtering, or deletes.") directly against
    pg_constraint/pg_index — independent of the src/dnd_ai/persistence/
    tables/ metadata mirror, so this gap was never caught by `alembic
    check`. 093_ai_domain and 094_reference_corpus (Phase 12's first two
    migrations) each indexed most, but not all, of their own foreign keys;
    this is a same-phase correction pass, the same posture 096_campaign_
    scoped_agents and earlier phases' own correction-pass migrations
    already take for gaps caught after the fact.

    Nullable foreign keys get a partial index (WHERE <col> IS NOT NULL),
    matching every other nullable-FK index already in these two
    migrations (ix_context_requests_requesting_character_id,
    ix_proposed_changes_applied_event_id,
    ix_reference_retrievals_context_request_id,
    ix_source_documents_supersedes,
    ix_resource_grants_source_document_id/.ai_proposed_change_id) — a row
    with the FK unset contributes nothing to a lookup keyed on it, and
    the eight fixed here are all ON DELETE SET NULL columns. The three
    NOT NULL foreign keys fixed here get a plain index, matching this
    same pair of migrations' own NOT NULL FK indexes.

Forward migration:
    - ai.agent_assignments.assigned_by_user_id (nullable, partial)
    - ai.agent_assignments.entity_id (NOT NULL, plain)
    - ai.change_reviews.reviewer_user_id (nullable, partial)
    - ai.context_requests.requesting_user_id (nullable, partial)
    - ai.proposed_changes.decided_by_user_id (nullable, partial)
    - ai.reference_retrievals.requested_by_user_id (nullable, partial)
    - ai.reference_retrievals.ruleset_version_id (NOT NULL, plain)
    - ai.reference_source_campaigns.granted_by_user_id (nullable, partial)
    - core.source_documents.ingested_by_user_id (nullable, partial)
    - core.source_documents.removed_by_user_id (nullable, partial)
    - core.source_documents.source_type_id (NOT NULL, plain)

Rollback:
    Supported. Drops the eleven indexes.

Data implications:
    None — every statement is CREATE INDEX (CONCURRENTLY is not used
    since this is a fresh Phase 12 table set with no production data
    yet; a normal CREATE INDEX takes the standard ACCESS EXCLUSIVE lock
    matching the existing 093/094 index-creation statements).

Locking considerations:
    Ten of the eleven tables are Phase 12-only and empty in every
    deployed environment so far; the locks are momentary regardless.

See: docs/DATABASE_CONVENTIONS.md §19.1 (foreign-key indexes)
     docs/PLAN.md Phase 12 (Narrow AI/NPC MVP)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "098_ai_domain_fk_indexes"
down_revision = "097_advance_objective_kind"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    op.execute(
        "CREATE INDEX ix_agent_assignments_assigned_by_user_id "
        "ON ai.agent_assignments (assigned_by_user_id) "
        "WHERE assigned_by_user_id IS NOT NULL;"
    )
    op.execute("CREATE INDEX ix_agent_assignments_entity_id ON ai.agent_assignments (entity_id);")
    op.execute(
        "CREATE INDEX ix_change_reviews_reviewer_user_id "
        "ON ai.change_reviews (reviewer_user_id) "
        "WHERE reviewer_user_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_context_requests_requesting_user_id "
        "ON ai.context_requests (requesting_user_id) "
        "WHERE requesting_user_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_proposed_changes_decided_by_user_id "
        "ON ai.proposed_changes (decided_by_user_id) "
        "WHERE decided_by_user_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_reference_retrievals_requested_by_user_id "
        "ON ai.reference_retrievals (requested_by_user_id) "
        "WHERE requested_by_user_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_reference_retrievals_ruleset_version_id "
        "ON ai.reference_retrievals (ruleset_version_id);"
    )
    op.execute(
        "CREATE INDEX ix_reference_source_campaigns_granted_by_user_id "
        "ON ai.reference_source_campaigns (granted_by_user_id) "
        "WHERE granted_by_user_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_source_documents_ingested_by_user_id "
        "ON core.source_documents (ingested_by_user_id) "
        "WHERE ingested_by_user_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_source_documents_removed_by_user_id "
        "ON core.source_documents (removed_by_user_id) "
        "WHERE removed_by_user_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_source_documents_source_type_id ON core.source_documents (source_type_id);"
    )


def downgrade() -> None:
    """Revert the migration."""

    op.execute("DROP INDEX IF EXISTS core.ix_source_documents_source_type_id;")
    op.execute("DROP INDEX IF EXISTS core.ix_source_documents_removed_by_user_id;")
    op.execute("DROP INDEX IF EXISTS core.ix_source_documents_ingested_by_user_id;")
    op.execute("DROP INDEX IF EXISTS ai.ix_reference_source_campaigns_granted_by_user_id;")
    op.execute("DROP INDEX IF EXISTS ai.ix_reference_retrievals_ruleset_version_id;")
    op.execute("DROP INDEX IF EXISTS ai.ix_reference_retrievals_requested_by_user_id;")
    op.execute("DROP INDEX IF EXISTS ai.ix_proposed_changes_decided_by_user_id;")
    op.execute("DROP INDEX IF EXISTS ai.ix_context_requests_requesting_user_id;")
    op.execute("DROP INDEX IF EXISTS ai.ix_change_reviews_reviewer_user_id;")
    op.execute("DROP INDEX IF EXISTS ai.ix_agent_assignments_entity_id;")
    op.execute("DROP INDEX IF EXISTS ai.ix_agent_assignments_assigned_by_user_id;")
