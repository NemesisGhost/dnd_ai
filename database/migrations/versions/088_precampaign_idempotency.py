"""Add security.campaign_creation_reservations

Revision ID: 088_precampaign_idempotency
Revises: 087_timeline_bootstrap_grants
Create Date: 2026-08-16 09:00:00.000000

Purpose:
    Fixes a High-severity idempotency defect: `POST /campaigns`
    (`dnd_ai.commands.campaigns.create_campaign`, `dnd_ai.api.campaigns`)
    has never supported `Idempotency-Key` at all — deliberately, per that
    module's own former docstring note, since `security.idempotent_requests`
    (migration 082) has a `NOT NULL` `campaign_id` foreign key and
    `create_campaign` is the one write in this codebase with no existing
    campaign to key a reservation against yet.

    Migration 087 (the immediately prior revision) made this a live
    exploit surface, not just a lost-response inconvenience: it added
    `security.timeline_bootstrap_grants`, a *single-use* first-campaign
    entitlement consumed atomically by `create_campaign`. Without a
    reservation of its own, a dropped response and a naive client retry
    replay a genuinely new request rather than the original one — the
    first call creates the campaign and consumes the grant; a retry, now
    seeing an already-used timeline, falls through to the *reuse* branch,
    which the same caller passes via the `access.manage` they just
    received as the campaign's own owner. The single-use grant therefore
    still stops a *different* user from claiming the first campaign, but
    does nothing to stop the successful creator's own retry from minting a
    second active campaign, membership, owner role assignment, and audit
    row for what the caller believes is one logical request.

    `security.campaign_creation_reservations` is the pre-campaign
    reservation table `dnd_ai.commands.campaigns`'s former docstring
    flagged as the missing piece: the same reserve-then-complete shape as
    `security.idempotent_requests`, minus the `campaign_id` scoping column
    that table structurally requires and this one command structurally
    cannot supply at reservation time. Scope is `(actor_user_id,
    idempotency_key)` alone — there is no existing campaign to add to the
    tuple, and no second command shares this table, so no `campaign_id`
    (nullable or not) and no `command_name` column are needed the way a
    general-purpose store would need them; `command_name` is still baked
    into the stored fingerprint (`dnd_ai.api.idempotency.
    compute_request_fingerprint`, called with the literal
    `"create_campaign"`) for parity with that module's own fingerprint
    shape, not because more than one command will ever reserve a row here.

Forward migration:
    `security.campaign_creation_reservations`:
      - `campaign_creation_reservation_id UUID PK`
      - `actor_user_id UUID NOT NULL REFERENCES security.users(user_id)
        ON DELETE CASCADE` — the authenticated creator; the reservation
        scope's other half alongside `idempotency_key`
      - `idempotency_key TEXT NOT NULL`, `ck_..._key_format` — identical
        bounded character set to `security.idempotent_requests.
        idempotency_key` (`dnd_ai.api.deps.get_idempotency_key` validates
        both before either ever reaches a database column)
      - `request_fingerprint TEXT NOT NULL` — sha256 of the canonical
        (`"create_campaign"`, request body) tuple; a replay whose
        fingerprint disagrees is rejected as a fixed, non-disclosing
        conflict rather than replayed or silently applied, mirroring
        `security.idempotent_requests.request_fingerprint` exactly
      - `correlation_id UUID` — nullable, passthrough only
      - `response_status_code SMALLINT` / `response_body JSONB` — NULL
        until the reserving request's own command actually succeeds;
        `ck_..._completion_consistent` requires `response_status_code`,
        `response_body`, `completed_at`, and `created_campaign_id` to be
        NULL or non-NULL together, so a row is never observably
        "half-finished" to any other transaction — it is either not yet
        committed at all, or fully complete, the identical guarantee
        `security.idempotent_requests` gives (see that table's own
        migration 082 comment)
      - `created_campaign_id UUID REFERENCES campaign.campaigns
        (campaign_id) ON DELETE RESTRICT` — the campaign this reservation
        actually produced, set together with the response; kept as a real
        column (not left buried inside `response_body` alone) so a
        reservation's resulting campaign can be queried directly.
        `ck_campaign_creation_reservations_completion_consistent` (below)
        requires `response_status_code`, `response_body`, `completed_at`,
        and `created_campaign_id` to be `NULL` or non-`NULL` *together* —
        `ON DELETE SET NULL` would let a deleted `campaign.campaigns` row
        null out `created_campaign_id` alone, leaving the other three
        still set and violating that very constraint the instant the
        cascade ran, mirroring `security.timeline_bootstrap_grants.
        consumed_by_campaign_id`'s identical fix in migration 087 (see
        that revision's own "Forward migration" section for the full
        reasoning). `RESTRICT`, not `CASCADE`: no command in this
        codebase deletes a `campaign.campaigns` row at all (campaigns are
        permanent once created, CLAUDE.md rule 9), so this only turns a
        schema-level contradiction that would otherwise silently corrupt
        this table's own invariant into an explicit failure if that
        assumption is ever violated, rather than quietly discarding a
        completed reservation's own record of what it produced
      - `ux_campaign_creation_reservations_scope`: `UNIQUE (actor_user_id,
        idempotency_key)` — this table's whole concurrency argument, and
        also the `actor_user_id` foreign key's own supporting index (a
        leading-column match, conventions §19.1)
      - `ix_campaign_creation_reservations_created_campaign_id`: partial,
        `WHERE created_campaign_id IS NOT NULL` — that column's own
        foreign key's supporting index

    `dnd_ai.api.idempotency` gains `begin_campaign_creation_request()` /
    `complete_campaign_creation_request()`, the reserve/replay and
    completion functions for this table, built the same way
    `begin_idempotent_request()`/`complete_idempotent_request()` already
    are: one atomic `INSERT ... ON CONFLICT (...) DO NOTHING RETURNING`
    resolves "do I own this key" without a separate check-then-insert
    race, run inside the same request transaction `create_campaign()`
    itself runs in, so a command that fails or is rolled back for any
    reason never durably reserves the key at all — see that module's own
    docstring for the full concurrency argument, which applies here
    unchanged.

Rollback:
    Supported. Drops the table.

Data implications:
    A new, empty table. No existing row is altered.

Locking considerations:
    Creates one new table; no lock on any existing table.

See: database/migrations/versions/082_item_command_idempotency.py
     (security.idempotent_requests — this table's closest sibling design,
     and the reason its own `campaign_id` column could not simply be made
     nullable and reused: a nullable column in a `UNIQUE` constraint does
     not enforce uniqueness across multiple NULLs, so two concurrent
     pre-campaign reservations under the same key/user would not have
     conflicted at all against that table's existing index shape)
     database/migrations/versions/087_timeline_bootstrap_grants.py (the
     single-use first-campaign entitlement whose own consumption this
     migration's reservation must durably wrap so a lost response can
     never leave an unreplayable committed campaign)
     src/dnd_ai/api/idempotency.py (this table's only writer/reader)
     src/dnd_ai/api/campaigns.py (the one route that uses it)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "088_precampaign_idempotency"
down_revision = "087_timeline_bootstrap_grants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    op.execute("""
        CREATE TABLE security.campaign_creation_reservations (
            campaign_creation_reservation_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            actor_user_id                     UUID NOT NULL
                                               REFERENCES security.users(user_id)
                                               ON DELETE CASCADE,
            idempotency_key                   TEXT NOT NULL,
            request_fingerprint                TEXT NOT NULL,
            correlation_id                        UUID,
            response_status_code                     SMALLINT,
            response_body                               JSONB,
            created_campaign_id                            UUID
                                                            REFERENCES campaign.campaigns(campaign_id)
                                                            ON DELETE RESTRICT,
            created_at                                            TIMESTAMPTZ NOT NULL
                                                                   DEFAULT now(),
            completed_at                                                 TIMESTAMPTZ,
            CONSTRAINT ux_campaign_creation_reservations_scope
                UNIQUE (actor_user_id, idempotency_key),
            CONSTRAINT ck_campaign_creation_reservations_key_format
                CHECK (idempotency_key ~ '^[A-Za-z0-9._~-]{1,255}$'),
            CONSTRAINT ck_campaign_creation_reservations_completion_consistent CHECK (
                (response_status_code IS NULL AND response_body IS NULL
                 AND completed_at IS NULL AND created_campaign_id IS NULL)
                OR
                (response_status_code IS NOT NULL AND response_body IS NOT NULL
                 AND completed_at IS NOT NULL AND created_campaign_id IS NOT NULL)
            )
        );
    """)
    op.execute("""
        COMMENT ON TABLE security.campaign_creation_reservations IS
        'Durable pre-campaign Idempotency-Key store for POST /campaigns '
        '(dnd_ai.commands.campaigns.create_campaign), the one write in this '
        'codebase with no existing campaign_id to key a security.'
        'idempotent_requests reservation against. One row reserves '
        '(actor_user_id, idempotency_key) for the lifetime of the reserving '
        'transaction and is filled in with the resulting campaign and response '
        'before that transaction commits; a rolled-back or failed attempt '
        'releases the key automatically. See src/dnd_ai/api/idempotency.py.';
    """)
    op.execute("""
        COMMENT ON COLUMN security.campaign_creation_reservations.idempotency_key IS
        'Client-supplied Idempotency-Key header value, bounded and character-'
        'restricted (dnd_ai.api.deps.get_idempotency_key) before it ever reaches '
        'this column or any log line — the same discipline '
        'dnd_ai.api.correlation applies to X-Correlation-Id.';
    """)
    op.execute("""
        COMMENT ON COLUMN security.campaign_creation_reservations.request_fingerprint IS
        'sha256 hex digest of the canonical ("create_campaign", request body) '
        'tuple (dnd_ai.api.idempotency.compute_request_fingerprint). A replay '
        'whose fingerprint does not match this value — a different payload '
        'reusing the same key — is rejected as a fixed, non-disclosing conflict '
        'rather than replayed or silently applied.';
    """)
    op.execute("""
        COMMENT ON COLUMN security.campaign_creation_reservations.response_body IS
        'The exact response body this command already returned to this same '
        'authenticated caller for this key, including the resulting campaign_id '
        'and campaign_membership_id; replayed verbatim on a matching retry '
        'rather than re-running create_campaign.';
    """)
    op.execute("""
        COMMENT ON COLUMN security.campaign_creation_reservations.created_campaign_id IS
        'The campaign.campaigns row this reservation produced, set atomically '
        'with response_body once create_campaign succeeds. ON DELETE RESTRICT, '
        'compatible with ck_campaign_creation_reservations_completion_consistent: '
        'campaigns are never physically deleted by any command in this codebase, '
        'so this only turns a schema-level contradiction into an explicit failure '
        'if that assumption is ever violated, rather than a SET NULL cascade '
        'silently orphaning a completed reservation''s own completion columns.';
    """)

    op.execute(
        "CREATE INDEX ix_campaign_creation_reservations_created_campaign_id "
        "ON security.campaign_creation_reservations (created_campaign_id) "
        "WHERE created_campaign_id IS NOT NULL;"
    )


def downgrade() -> None:
    """Revert the migration."""

    op.execute("DROP TABLE IF EXISTS security.campaign_creation_reservations;")
