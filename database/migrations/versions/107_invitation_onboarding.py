"""Add security.invitation_onboarding_sessions and bound security.users.display_name

Revision ID: 107_invitation_onboarding
Revises: 106_access_group_desc_length
Create Date: 2026-09-25 09:00:00.000000

Purpose:
    Phase 13E checkpoint 8a. Backs the single-link campaign-invitation
    onboarding flow (docs/PHASE13E_ACCESS_CONTRACT.md §3n;
    PHASE13E_REMAINING_IMPLEMENTATION_PLAN.md §6.2/§8.2): a visitor who
    opens an invitation link with no account yet must be able to register
    one and have the invitation bound to it, across the redirect a
    sign-in/registration step requires, without the raw invitation token
    ever leaving the URL fragment or being persisted anywhere.

    `security.campaign_invitations` (migration 080) already tracks only a
    token hash and cannot itself carry the extra pre-authentication state
    this flow needs (a CSRF secret for the double-submit contract on
    unauthenticated mutations, and a short absolute lifetime independent
    of the invitation's own). `security.campaign_creation_reservations`
    (migration 088) is the closest precedent for a purpose-specific,
    non-`security.idempotent_requests` scratch table backing one narrow
    flow that has no natural fit in an existing table.

    `dnd_ai.commands.invitation_onboarding` is this table's only writer.
    The raw invitation token is never stored here (only the FK to
    `security.campaign_invitations`, whose own row already carries the
    hash) and the onboarding token is stored only as a sha256 hash
    (`dnd_ai.domain.credentials.hash_opaque_secret`), mirroring every
    other opaque-credential table in this schema.

Forward migration:
    `security.invitation_onboarding_sessions`:
      - `invitation_onboarding_session_id UUID PK`
      - `onboarding_token_hash TEXT NOT NULL UNIQUE` — sha256 hex digest of
        the value the onboarding cookie carries; the raw value never
        reaches this column.
      - `campaign_invitation_id UUID NOT NULL REFERENCES security.
        campaign_invitations(campaign_invitation_id) ON DELETE CASCADE` —
        the only reference to the invitation this session is onboarding
        for; deliberately no raw or hashed invitation token duplicated
        here.
      - `csrf_token TEXT NOT NULL` — a server-generated double-submit
        secret for `register`/`cancel`, mirroring `security.
        browser_sessions.csrf_token`'s identical "stored in the clear;
        alone grants nothing" shape (that column's own comment).
      - `created_at`/`expires_at TIMESTAMPTZ NOT NULL` — `expires_at` is
        `min(now() + 20 minutes, invitation.expires_at)`, computed by the
        command layer, never extended once set.
      - `consumed_at TIMESTAMPTZ` / `consumed_by_user_id UUID REFERENCES
        security.users(user_id) ON DELETE RESTRICT` — set together by
        `complete_invitation_onboarding`; `RESTRICT` because no command in
        this codebase ever deletes a `security.users` row (mirroring
        `security.campaign_creation_reservations.created_campaign_id`'s
        identical reasoning for its own completion column), so this only
        turns a schema-level contradiction into an explicit failure if
        that assumption is ever violated.
      - `cancelled_at TIMESTAMPTZ` — set by `cancel_invitation_onboarding`
        or by a fresh `start` replacing a pre-existing live session for
        the same browser (never merged, never reused).
      - `created_ip TEXT` — operator/abuse-investigation metadata only,
        mirroring `security.browser_sessions.created_ip`.
      - `ck_ios_expires_after_created CHECK (expires_at > created_at)` —
        guards against a non-positive onboarding window (P-7); the command
        layer validates the invitation is unexpired *before* computing
        `expires_at` so this can never legitimately fire in production,
        only guard a latent command-layer bug.
      - `ck_ios_consumption_consistent CHECK` — `consumed_at`/
        `consumed_by_user_id` are `NULL` or non-`NULL` together, the
        identical "never half-finished" shape `security.
        campaign_creation_reservations.ck_..._completion_consistent`
        already established.
      - `ck_ios_not_both_terminal CHECK (consumed_at IS NULL OR
        cancelled_at IS NULL)` — a session is consumed *or* cancelled,
        never both; there is exactly one terminal outcome per row.
      - `ux_ios_token_hash UNIQUE (onboarding_token_hash)`.
      - `ix_ios_campaign_invitation_id` — the FK's own supporting index.
      - `ix_ios_live`, partial on `(expires_at) WHERE consumed_at IS NULL
        AND cancelled_at IS NULL` — supports the "does this browser already
        have a live session" lookup `begin_invitation_onboarding` performs
        before replacing one.

    `security.users` gains `ck_users_display_name_length CHECK
    (char_length(display_name) BETWEEN 1 AND 100)` (D-11): until this
    revision, `display_name` has been unrestricted `TEXT NOT NULL` since
    revision 003 with no length or format bound at all, and the only
    writer has been a platform administrator. Checkpoint 8b's invited
    self-registration (`dnd_ai.commands.local_auth.
    _register_invited_local_account_impl`) hands this field to an
    untrusted invitee for the first time, and it renders in the access-
    overview member list, audit-history actor labels, and the session
    bootstrap — so an unbounded value is no longer a purely internal
    concern. 100 matches the bound the dropped `username` column already
    used (migration 080 removed `username`/`is_active`; nothing since
    replaced `username`'s own length bound), so this is the schema's own
    established figure, not a new one. This revision follows migration
    106's production-safe ordering (`NOT VALID` first, so its brief
    `ACCESS EXCLUSIVE` lock closes the rolling-deployment race — see that
    revision's own "Concurrency guarantee" section for the full argument,
    which applies here unchanged — then a read-only over-length preflight
    that names offending `user_id`s and aborts with `RuntimeError` rather
    than truncating any name, then `VALIDATE CONSTRAINT` last, taking only
    `SHARE UPDATE EXCLUSIVE`). Unlike migration 106's `description` column,
    `display_name` is `NOT NULL` with no blank-is-legal case, so there is
    no backfill step here — a whitespace-only value is rejected by the
    application layer (`dnd_ai.commands.local_auth`), never normalized to
    empty, so no legacy row is expected to violate the lower bound; the
    preflight checks both bounds regardless, since nothing before this
    revision enforced either.

Rollback:
    Supported. Drops `security.invitation_onboarding_sessions` and
    `ck_users_display_name_length`. Does not restore any `display_name`
    value — the constraint's own validation never modifies data, only
    rejects a new out-of-bounds write going forward.

Data implications:
    `security.invitation_onboarding_sessions` is new and empty. The
    `display_name` preflight blocks (via `RuntimeError`, not a schema
    change) if any existing row is empty or longer than 100 characters;
    a repository/CI database, and any environment whose only `display_name`
    values were written by an administrator following existing practice,
    is unaffected in practice.

Locking considerations:
    Creates one new table (no lock on any existing table). The
    `ck_users_display_name_length` constraint follows migration 106's own
    "Locking considerations" section exactly: `ADD CONSTRAINT ... NOT
    VALID` briefly takes `ACCESS EXCLUSIVE` on `security.users` (metadata
    only, no scan) and waits for in-flight writers, then blocks new ones
    until this migration's transaction ends; `VALIDATE CONSTRAINT` takes
    only `SHARE UPDATE EXCLUSIVE` for its scan.

See: PHASE13E_REMAINING_IMPLEMENTATION_PLAN.md §6.2, §8.1 (D-11), §8.2
     database/migrations/versions/088_precampaign_idempotency.py (the
     purpose-specific pre-authentication reservation-table precedent)
     database/migrations/versions/106_access_group_desc_length.py (the
     NOT VALID -> preflight -> VALIDATE production-safe pattern this
     revision's display_name constraint follows verbatim)
     src/dnd_ai/commands/invitation_onboarding.py (this table's only
     writer/reader)
     src/dnd_ai/commands/local_auth.py (_register_invited_local_account_impl,
     the display_name CHECK's actual new caller)
     src/dnd_ai/persistence/tables/security.py (the matching declared table
     and column comment)
"""

import uuid

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = "107_invitation_onboarding"
down_revision = "106_access_group_desc_length"
branch_labels = None
depends_on = None

# Must match src/dnd_ai/persistence/tables/security.py's
# users.c.display_name column comment exactly -- alembic check compares
# comments unconditionally.
# Doubled apostrophe ('') is the raw-SQL escape for a literal apostrophe
# inside this single-quoted string, matching migration 106's own
# "created_campaign_id''s" precedent -- this value is interpolated
# directly into a COMMENT ON COLUMN ... IS '...' statement below.
_DISPLAY_NAME_COMMENT = (
    "1-100 characters (ck_users_display_name_length, migration 107). "
    "Untrusted input as of that revision: dnd_ai.commands.local_auth."
    "_register_invited_local_account_impl lets an invited registrant "
    "choose this value directly, so it is a free-text label, not a "
    "verified identity -- see that command''s own docstring."
)

_DISPLAY_NAME_MIN_LENGTH = 1
_DISPLAY_NAME_MAX_LENGTH = 100

_OUT_OF_BOUNDS_ERROR_TEMPLATE = (
    "Cannot add ck_users_display_name_length: {count} security.users row(s) already "
    "have a display_name outside the 1-{max_length} character bound (revisions "
    "003-106 enforced none). These are not silently truncated or backfilled -- that "
    "would destroy or fabricate user-authored text, and no authoritative design in "
    "this repository approves either as a data policy. Affected user_id(s): {ids}. "
    "For each one, set display_name to a value between {min_length} and {max_length} "
    "characters -- a decision for whoever owns that account, not this migration -- "
    "then re-run this migration. Nothing in the database has been changed by this "
    "failed attempt."
)

_ERROR_ID_SAMPLE_LIMIT = 20


def _out_of_bounds_user_ids() -> list[uuid.UUID]:
    """Read-only precondition check, run immediately after the NOT VALID
    ADD CONSTRAINT above takes its lock -- mirrors 106's own
    _over_length_access_group_ids() ordering and reasoning exactly."""
    bind = op.get_bind()
    return list(
        bind.execute(
            text("""
                SELECT user_id FROM security.users
                WHERE char_length(display_name) < :min_length
                   OR char_length(display_name) > :max_length
                ORDER BY user_id
            """),
            {"min_length": _DISPLAY_NAME_MIN_LENGTH, "max_length": _DISPLAY_NAME_MAX_LENGTH},
        )
        .scalars()
        .all()
    )


def _format_id_sample(ids: list[uuid.UUID]) -> str:
    sample = ids[:_ERROR_ID_SAMPLE_LIMIT]
    formatted = ", ".join(str(user_id) for user_id in sample)
    if len(ids) > len(sample):
        formatted += f", and {len(ids) - len(sample)} more"
    return formatted


def upgrade() -> None:
    """Apply the migration. See this module's own "Forward migration"
    section for why display_name's constraint runs NOT VALID -> preflight
    -> VALIDATE, in that order (migration 106's "Concurrency guarantee"
    reasoning, unchanged)."""
    op.execute("""
        CREATE TABLE security.invitation_onboarding_sessions (
            invitation_onboarding_session_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            onboarding_token_hash             TEXT NOT NULL,
            campaign_invitation_id            UUID NOT NULL
                                               REFERENCES security.campaign_invitations(
                                                   campaign_invitation_id)
                                               ON DELETE CASCADE,
            csrf_token                        TEXT NOT NULL,
            created_at                        TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at                        TIMESTAMPTZ NOT NULL,
            consumed_at                       TIMESTAMPTZ,
            consumed_by_user_id               UUID
                                               REFERENCES security.users(user_id)
                                               ON DELETE RESTRICT,
            cancelled_at                      TIMESTAMPTZ,
            created_ip                        TEXT,
            CONSTRAINT ux_ios_token_hash UNIQUE (onboarding_token_hash),
            CONSTRAINT ck_ios_expires_after_created CHECK (expires_at > created_at),
            CONSTRAINT ck_ios_consumption_consistent CHECK (
                (consumed_at IS NULL AND consumed_by_user_id IS NULL)
                OR
                (consumed_at IS NOT NULL AND consumed_by_user_id IS NOT NULL)
            ),
            CONSTRAINT ck_ios_not_both_terminal CHECK (
                consumed_at IS NULL OR cancelled_at IS NULL
            )
        );
    """)
    op.execute("""
        COMMENT ON TABLE security.invitation_onboarding_sessions IS
        'Pre-authentication scratch state for the single-link campaign-invitation '
        'onboarding flow (PHASE13E_REMAINING_IMPLEMENTATION_PLAN.md §6.2/§8.2). Only '
        'a hash of the onboarding token is stored, and only a reference to the '
        'invitation being onboarded for -- never the raw invitation token itself. '
        'See dnd_ai.commands.invitation_onboarding, this table''s only writer.';
    """)
    op.execute("""
        COMMENT ON COLUMN security.invitation_onboarding_sessions.onboarding_token_hash IS
        'sha256 hex digest of the value the onboarding cookie carries '
        '(dnd_ai.domain.credentials.hash_opaque_secret). The raw value never reaches '
        'this column, this table, or any log line.';
    """)
    op.execute("""
        COMMENT ON COLUMN security.invitation_onboarding_sessions.csrf_token IS
        'Server-generated double-submit secret for register/cancel, stored in the '
        'clear -- alone grants nothing, mirroring security.browser_sessions.csrf_token.';
    """)
    op.execute("""
        COMMENT ON COLUMN security.invitation_onboarding_sessions.expires_at IS
        'min(now() + 20 minutes, the referenced invitation''s own expires_at) at the '
        'time this row was created; never extended afterward.';
    """)
    op.execute("""
        COMMENT ON COLUMN security.invitation_onboarding_sessions.consumed_by_user_id IS
        'The account complete_invitation_onboarding bound this session to, set '
        'atomically with consumed_at. ON DELETE RESTRICT: no command in this codebase '
        'ever deletes a security.users row, mirroring security.'
        'campaign_creation_reservations.created_campaign_id''s identical reasoning.';
    """)

    op.execute(
        "CREATE INDEX ix_ios_campaign_invitation_id "
        "ON security.invitation_onboarding_sessions (campaign_invitation_id);"
    )
    op.execute(
        "CREATE INDEX ix_ios_live "
        "ON security.invitation_onboarding_sessions (expires_at) "
        "WHERE consumed_at IS NULL AND cancelled_at IS NULL;"
    )

    op.execute("""
        ALTER TABLE security.users
        ADD CONSTRAINT ck_users_display_name_length
        CHECK (char_length(display_name) BETWEEN 1 AND 100)
        NOT VALID;
    """)

    out_of_bounds_ids = _out_of_bounds_user_ids()
    if out_of_bounds_ids:
        raise RuntimeError(
            _OUT_OF_BOUNDS_ERROR_TEMPLATE.format(
                count=len(out_of_bounds_ids),
                min_length=_DISPLAY_NAME_MIN_LENGTH,
                max_length=_DISPLAY_NAME_MAX_LENGTH,
                ids=_format_id_sample(out_of_bounds_ids),
            )
        )

    op.execute("""
        ALTER TABLE security.users
        VALIDATE CONSTRAINT ck_users_display_name_length;
    """)
    op.execute(f"""
        COMMENT ON COLUMN security.users.display_name IS
        '{_DISPLAY_NAME_COMMENT}';
    """)


def downgrade() -> None:
    """Revert the migration."""
    op.execute("COMMENT ON COLUMN security.users.display_name IS NULL;")
    op.execute("ALTER TABLE security.users DROP CONSTRAINT IF EXISTS ck_users_display_name_length;")
    op.execute("DROP TABLE IF EXISTS security.invitation_onboarding_sessions;")
