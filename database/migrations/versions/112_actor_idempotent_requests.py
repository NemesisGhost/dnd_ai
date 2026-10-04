"""Add security.actor_idempotent_requests

Revision ID: 112_actor_idempotent_requests
Revises: 111_authoring_row_versions
Create Date: 2026-10-03 13:00:00.000000

Purpose:
    Phase 14 (docs/DATABASE_CONVENTIONS.md §26.4). World and timeline commands
    have no campaign to scope a `security.idempotent_requests` reservation to
    (its `campaign_id` is NOT NULL), and `security.campaign_creation_
    reservations` is specific to POST /campaigns. This is the third, actor-scoped
    store: one row reserves `(actor_user_id, idempotency_key)` for the lifetime
    of the reserving transaction, is completed with the response before that
    transaction commits, and is released automatically if the command fails
    (its INSERT rolls back with it).

Forward migration:
    `security.actor_idempotent_requests` with the same shape and the same
    completion-consistency CHECK as revision 082's table, minus `campaign_id`.

Rollback:
    Supported. Drops the table; in-flight replay data is lost, which only means
    a retry after the downgrade re-executes instead of replaying.

Data implications:
    New, empty table.

Locking considerations:
    New table; briefly SHARE ROW EXCLUSIVE on `security.users` for the FK.

See: src/dnd_ai/api/idempotency.py (begin/complete_actor_idempotent_request)
     docs/DATABASE_CONVENTIONS.md §26.4
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "112_actor_idempotent_requests"
down_revision = "111_authoring_row_versions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""
    op.execute("""
        CREATE TABLE security.actor_idempotent_requests (
            actor_idempotent_request_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            actor_user_id                UUID NOT NULL
                                          REFERENCES security.users(user_id)
                                          ON DELETE CASCADE,
            idempotency_key              TEXT NOT NULL,
            request_fingerprint          TEXT NOT NULL,
            correlation_id               UUID,
            response_status_code         SMALLINT,
            response_body                JSONB,
            created_at                   TIMESTAMPTZ NOT NULL DEFAULT now(),
            completed_at                 TIMESTAMPTZ,
            CONSTRAINT ux_actor_idempotent_requests_scope
                UNIQUE (actor_user_id, idempotency_key),
            CONSTRAINT ck_actor_idempotent_requests_key_format
                CHECK (idempotency_key ~ '^[A-Za-z0-9._~-]{1,255}$'),
            CONSTRAINT ck_actor_idempotent_requests_completion_consistent CHECK (
                (response_status_code IS NULL AND response_body IS NULL AND completed_at IS NULL)
                OR
                (response_status_code IS NOT NULL AND response_body IS NOT NULL
                 AND completed_at IS NOT NULL)
            )
        );
    """)
    op.execute("""
        COMMENT ON TABLE security.actor_idempotent_requests IS
        'Durable actor-scoped Idempotency-Key store for commands with no campaign to '
        'scope to (world and timeline authoring). One row reserves (actor_user_id, '
        'idempotency_key) for the lifetime of the reserving transaction and is filled in '
        'with the response before that transaction commits; a rolled-back or failed '
        'command releases the key automatically. See src/dnd_ai/api/idempotency.py.';
    """)
    op.execute("""
        COMMENT ON COLUMN security.actor_idempotent_requests.idempotency_key IS
        'Client-supplied Idempotency-Key header value, bounded and character-restricted '
        '(dnd_ai.api.deps.get_idempotency_key) before it reaches this column or any log '
        'line.';
    """)
    op.execute("""
        COMMENT ON COLUMN security.actor_idempotent_requests.request_fingerprint IS
        'sha256 hex digest of the canonical (command_name, path parameters, request body) '
        'tuple (dnd_ai.api.idempotency.compute_request_fingerprint). A replay whose '
        'fingerprint does not match -- a different command or payload reusing the key -- '
        'is rejected as a fixed, non-disclosing conflict rather than replayed.';
    """)
    op.execute("""
        COMMENT ON COLUMN security.actor_idempotent_requests.response_body IS
        'The exact response body the command already returned to this same '
        'authenticated caller for this key; replayed verbatim on a matching retry.';
    """)


def downgrade() -> None:
    """Revert the migration."""
    op.execute("DROP TABLE IF EXISTS security.actor_idempotent_requests;")
