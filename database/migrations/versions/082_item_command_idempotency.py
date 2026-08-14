"""Durable command idempotency store

Revision ID: 082_item_command_idempotency
Revises: 081_encounter_session_scope
Create Date: 2026-08-14 10:00:00.000000

Purpose:
    Phase 10 workstream 6 correction pass. `POST /campaigns/{campaign_id}/
    items/{item_instance_id}/transfer` and `.../identify`
    (`src/dnd_ai/api/items.py`) create another `narrative.events`/
    `.event_effects` pair on a naive client retry of the same logical
    request — unlike `resolve_combat_turn`, neither command has a natural
    unique-constraint-backed idempotency key, so PLAN.md §25's "retries do
    not duplicate effects" vertical-slice criterion did not hold for them.
    `dnd_ai.api.deps.get_idempotency_key` already passed the client's
    `Idempotency-Key` header through; nothing stored or deduplicated
    against it (its own docstring called that out as deferred "to the
    first mutating command endpoint that needs it").

    `security.idempotent_requests` is that store: one row reserves a
    (`actor_user_id`, `campaign_id`, `idempotency_key`) tuple for the
    lifetime of the command's own transaction, and is filled in with the
    command's response before that same transaction commits. See
    `src/dnd_ai/api/idempotency.py` for the reservation/replay logic this
    table supports and why the reserve-then-fill shape, entirely within
    the command's own transaction, is what makes a rolled-back or failed
    command release the key automatically rather than needing an explicit
    cleanup path.

    Placed under `security` rather than `audit`, deliberately: `audit.*`
    tables are append-only to normal application roles (conventions
    §24.2) and their rows deliberately outlive the records they describe
    (`audit.change_log`'s own comment). This table is the opposite on both
    counts — a row is reserved, then updated once with its final response,
    and it is disposable request-dedup cache state, not history, so it
    carries real `ON DELETE CASCADE` foreign keys to `security.users`/
    `campaign.campaigns` rather than the deliberately unconstrained columns
    `audit.change_log` uses. `security` already houses comparable
    request/session-scoped, mutable, per-user-per-campaign state
    (`security.campaign_memberships`), which is the closer fit.

Forward migration:
    - security.idempotent_requests

Rollback:
    Supported. Drops the table.

Data implications:
    None. New, empty table.

Locking considerations:
    None. New table only.

See: docs/DATABASE_CONVENTIONS.md §26.4 (idempotency)
     docs/architecture/DATABASE_MODEL.md §19
     docs/PLAN.md §25 (vertical-slice acceptance criteria)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "082_item_command_idempotency"
down_revision = "081_encounter_session_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    # ==========================================================================
    # 1. security.idempotent_requests
    # ==========================================================================
    # response_status_code/response_body are nullable: begin_idempotent_request()
    # (src/dnd_ai/api/idempotency.py) INSERTs the reservation row with both NULL
    # before the command runs, then complete_idempotent_request() fills them in
    # with an UPDATE later in the *same* transaction, before it commits. No
    # other transaction can ever observe the row in its intermediate NULL
    # state: it either doesn't exist yet (uncommitted) or is already complete
    # (committed) — see idempotency.py's own docstring for the concurrency
    # argument this depends on (INSERT ... ON CONFLICT DO NOTHING blocking on
    # a same-key row from an in-flight, not-yet-committed transaction).
    op.execute("""
        CREATE TABLE security.idempotent_requests (
            idempotent_request_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            actor_user_id             UUID NOT NULL
                                    REFERENCES security.users(user_id) ON DELETE CASCADE,
            campaign_id                  UUID NOT NULL
                                    REFERENCES campaign.campaigns(campaign_id) ON DELETE CASCADE,
            idempotency_key                 TEXT NOT NULL,
            request_fingerprint                TEXT NOT NULL,
            correlation_id                        UUID,
            response_status_code                     SMALLINT,
            response_body                               JSONB,
            created_at                                     TIMESTAMPTZ NOT NULL DEFAULT now(),
            completed_at                                      TIMESTAMPTZ,

            CONSTRAINT ux_idempotent_requests_scope
                UNIQUE (actor_user_id, campaign_id, idempotency_key),
            CONSTRAINT ck_idempotent_requests_key_format
                CHECK (idempotency_key ~ '^[A-Za-z0-9._~-]{1,255}$'),
            CONSTRAINT ck_idempotent_requests_completion_consistent CHECK (
                (response_status_code IS NULL AND response_body IS NULL AND completed_at IS NULL)
                OR
                (response_status_code IS NOT NULL AND response_body IS NOT NULL
                 AND completed_at IS NOT NULL)
            )
        );
    """)
    op.execute("""
        COMMENT ON TABLE security.idempotent_requests IS
        'Durable Idempotency-Key store for command endpoints (docs/PLAN.md §25 '
        '"retries do not duplicate effects"). One row reserves (actor_user_id, '
        'campaign_id, idempotency_key) for the lifetime of the reserving '
        'transaction; a rolled-back or failed command releases the key '
        'automatically because its INSERT is part of the same rolled-back '
        'transaction. See src/dnd_ai/api/idempotency.py.';
    """)
    op.execute("""
        COMMENT ON COLUMN security.idempotent_requests.idempotency_key IS
        'Client-supplied Idempotency-Key header value, bounded and character-'
        'restricted (dnd_ai.api.deps.get_idempotency_key) before it ever reaches '
        'this column or any log line — the same discipline '
        'dnd_ai.api.correlation applies to X-Correlation-Id.';
    """)
    op.execute("""
        COMMENT ON COLUMN security.idempotent_requests.request_fingerprint IS
        'sha256 hex digest of the canonical (command_name, path parameters, '
        'request body) tuple (dnd_ai.api.idempotency.compute_request_fingerprint). '
        'A replay whose fingerprint does not match this value — a different '
        'command or a different payload reusing the same key — is rejected as '
        'a fixed, non-disclosing conflict rather than replayed or silently '
        'applied.';
    """)
    op.execute("""
        COMMENT ON COLUMN security.idempotent_requests.response_body IS
        'The exact response body this command already returned to this same '
        'authenticated caller for this key; replayed verbatim on a matching '
        'retry rather than re-running the command.';
    """)

    op.execute(
        "CREATE INDEX ix_idempotent_requests_campaign_id "
        "ON security.idempotent_requests (campaign_id);"
    )


def downgrade() -> None:
    """Revert the migration."""

    op.execute("DROP TABLE IF EXISTS security.idempotent_requests;")
