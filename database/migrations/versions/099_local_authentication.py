"""Local accounts, browser sessions, and platform-administrator authority

Revision ID: 099_local_authentication
Revises: 098_ai_domain_fk_indexes
Create Date: 2026-08-21 09:00:00.000000

Purpose:
    Phase 11R workstream A/B (docs/PLAN.md §23.1, §23.4): the backend
    substrate for local username/password accounts and opaque server-side
    browser sessions, replacing nothing (OIDC bearer verification and the
    Foundry `FoundrySystem` credential remain exactly as they are — this is
    additive, per docs/PLAN.md's own Phase 10/11 "additive, not a
    reopening" framing) but adding the one authentication path this
    codebase has never had: a human logging in with a password this
    application itself verifies, with no external identity provider
    required.

    Four new tables plus one new column on `security.users`:

    - `security.users.is_platform_administrator` — a minimal, campaign-
      independent authorization primitive for account-management
      operations (creating a local account, issuing a password-reset
      token, the one-time initial-admin bootstrap) that have no
      `campaign_id` to scope a `security.roles`/`.resource_grants` check
      against at all. Deliberately not a new role/capability, and
      deliberately not layered onto the existing (inherently campaign-
      scoped) `security.roles`/`.role_capabilities`/`.membership_roles`
      machinery — see `src/dnd_ai/persistence/tables/security.py`'s own
      column comment and `dnd_ai.domain.access.is_platform_administrator`'s
      docstring for the full reasoning. This is a deliberate, documented
      extension beyond docs/PLAN.md §23.1's own text, which describes "an
      administrator" creating accounts without specifying how that
      administrator is themselves authorized — flagged explicitly here per
      CLAUDE.md §5's instruction to surface (not quietly invent) an
      apparent gap in the domain model, and reported as a deviation-with-
      justification in this workstream's own completion report.

    - `security.local_credentials` — the password credential itself
      (Argon2id-encoded hash, one row per user with a chosen password),
      separated from `security.users` per docs/PLAN.md §23.1's explicit
      "local password credentials and credential-history/security metadata
      separated from the user profile."

    - `security.user_activation_tokens` — a hashed, expiring, single-use
      token an administrator issues when creating an account; consuming it
      is how a user chooses their own password and claims their login
      name. The login name itself is *not* a new column anywhere durable
      until consumption: `dnd_ai.commands.local_auth.activate_local_account`
      reuses the already-generic `security.external_identities` table with
      `issuer='local'` (`dnd_ai.domain.access.LOCAL_AUTH_ISSUER`),
      `subject=<normalized login name>` — the identical synthetic-issuer
      pattern Phase 11 workstream 1's `link_foundry_identity` already
      established for Foundry identity mapping. That table's existing
      `ux_external_identities_issuer_subject` unique-while-active index
      already gives a login name the same single-owner-while-active
      guarantee a dedicated `security.users.login_name` column would
      otherwise have to duplicate — no schema change to
      `security.external_identities` is needed at all.

    - `security.password_reset_tokens` — the administrator-initiated
      counterpart to activation tokens, with its own `revoke_sessions` flag
      recording whether consumption should sign the user out everywhere
      (docs/PLAN.md §23.1's "full sign-out" reset policy).

    - `security.browser_sessions` — the opaque, server-side session record
      behind the `__Host-dnd_ai_session` cookie (docs/PLAN.md §23.4): a
      hashed session token, a plaintext CSRF secret (see that table's own
      comment for why this one column is deliberately not hashed, unlike
      every other credential in this migration), idle/absolute expiry, and
      revocation. Named `browser_sessions`, not `sessions`, specifically to
      avoid colliding with the pre-existing, unrelated `campaign.sessions`
      (game-session) concept — `docs/DATABASE_CONVENTIONS.md`'s own
      `<entity>_id` primary-key convention means a bare `sessions.session_id`
      here would collide with `campaign.sessions.session_id`'s already-
      established FK name.

    Every hashed-secret column in this revision (`local_credentials.
    password_hash` excepted — Argon2id is a hash, not a hash-of-a-hash)
    follows the identical "server generates 256 bits of CSPRNG entropy via
    `secrets.token_urlsafe`, returns it exactly once, stores only
    `sha256(raw).hexdigest()`" shape `089_foundry_system_credentials.py`
    and `security.campaign_invitations.invitation_token_hash` already
    established — `dnd_ai.domain.credentials.generate_opaque_secret`/
    `.hash_opaque_secret` are the shared implementation, factored out of
    that established pattern rather than each new token type reinventing
    it. `local_credentials.password_hash` is the deliberate exception:
    Argon2id, not sha256, because a human password is low-entropy and
    attacker-guessable in a way a server-generated opaque secret never is
    — see `dnd_ai.domain.passwords`'s own module docstring.

    No pruning/archival job for expired or revoked rows is added by this
    revision. Per docs/ENTITY_LIFECYCLE.md §12-§14 (which governs
    `core.entities`-rooted canonical world state, not operational security
    state) and following `security.idempotent_requests`' own precedent
    (docs/architecture/DATABASE_MODEL.md §19.8 — "reserved, updated once,
    and disposable cache state, not history"), these rows are disposable
    operational state with real `ON DELETE CASCADE` foreign keys, not
    audit history; a periodic cleanup job is left to a future operational
    workstream (docs/DEVELOPMENT.md's deployment/operations sections),
    documented here as a deliberate scope boundary, not an oversight.

Forward migration:
    - `security.users.is_platform_administrator BOOLEAN NOT NULL DEFAULT false`
    - `security.local_credentials`
    - `security.user_activation_tokens`
    - `security.password_reset_tokens`
    - `security.browser_sessions`

Rollback:
    Supported. Drops the four new tables and the new column, in FK-safe
    order (children before `security.users`' own column, though nothing
    here actually references `is_platform_administrator` by FK — order
    matters only among the four new tables themselves, none of which
    reference each other, so any order is safe there too).

Data implications:
    Every existing `security.users` row gets `is_platform_administrator =
    false` — no existing account gains platform-administrator authority
    merely because this migration ran. The very first such grant happens
    through `dnd_ai.commands.local_auth.bootstrap_initial_admin`, a
    deployment-time-only command (never exposed over HTTP) that itself
    fails closed once any `security.users` row already exists.

Locking considerations:
    `ALTER TABLE security.users ADD COLUMN ... DEFAULT false` is a
    metadata-only change on PostgreSQL 11+ (a fixed, non-volatile default
    does not force a table rewrite). The four `CREATE TABLE`s are new
    objects only. `security.users` is a small table (one row per platform
    user), so even a rewrite would not be materially disruptive, but none
    is expected here regardless.

See: docs/PLAN.md §23.1 (Identity and campaign membership),
     §23.4 (Browser-session boundary)
     docs/architecture/DATABASE_MODEL.md §19.1, §19.7, §19.8
     database/migrations/versions/080_security_identity_and_access.py
     (security.campaign_invitations.invitation_token_hash — the
     established "store only a hash" precedent)
     database/migrations/versions/089_foundry_system_credentials.py
     (the identical hash-only pattern applied to a different credential)
     src/dnd_ai/domain/passwords.py, src/dnd_ai/domain/credentials.py
     src/dnd_ai/commands/local_auth.py
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "099_local_authentication"
down_revision = "098_ai_domain_fk_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    # ==========================================================================
    # 1. security.users.is_platform_administrator
    # ==========================================================================
    op.execute("""
        ALTER TABLE security.users
            ADD COLUMN is_platform_administrator BOOLEAN NOT NULL DEFAULT false;
    """)
    op.execute("""
        COMMENT ON COLUMN security.users.is_platform_administrator IS
        'A minimal, campaign-independent authorization primitive (revision '
        '099_local_authentication, Phase 11R workstream A) for account-management '
        'operations that have no campaign_id to scope a security.resource_grants/'
        'security.roles check against — creating a local account, issuing a '
        'password-reset token, and the one-time initial-admin bootstrap. Deliberately '
        'not a security.roles row: campaign roles grant capabilities within one '
        'campaign membership (docs/architecture/DATABASE_MODEL.md §19.3), and this is '
        'the opposite scope entirely (docs/architecture/DATABASE_MODEL.md §19.7''s '
        'authentication-identity/campaign-responsibility separation, principle 13).';
    """)

    # ==========================================================================
    # 2. security.local_credentials
    # ==========================================================================
    op.execute("""
        CREATE TABLE security.local_credentials (
            local_credential_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id                  UUID NOT NULL UNIQUE
                                    REFERENCES security.users(user_id) ON DELETE CASCADE,
            password_hash                TEXT NOT NULL,
            password_updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_at                           TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at                               TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT ux_local_credentials_user_id UNIQUE (user_id),
            CONSTRAINT ck_local_credentials_password_hash_algorithm
                CHECK (password_hash ~ '^\\$argon2id\\$')
        );
    """)
    op.execute("""
        COMMENT ON TABLE security.local_credentials IS
        'A user''s local password credential, separated from security.users itself '
        '(docs/PLAN.md §23.1: ''local password credentials and credential-history/'
        'security metadata separated from the user profile''). Row created only when '
        'dnd_ai.commands.local_auth.activate_local_account consumes a security.'
        'user_activation_tokens row — before that, the user exists but cannot log in '
        'locally at all (e.g. an OIDC-only or not-yet-activated account).';
    """)
    op.execute("""
        COMMENT ON COLUMN security.local_credentials.password_hash IS
        'An Argon2id-encoded hash string (dnd_ai.domain.passwords.hash_password) — '
        'algorithm, version, and every hashing parameter are embedded in the encoded '
        'string itself, so there is no separate parameters column to keep in sync; '
        'dnd_ai.domain.passwords.password_needs_rehash detects a stale parameter set '
        'at verification time. Never the raw password.';
    """)
    op.execute("CREATE INDEX ix_local_credentials_user_id ON security.local_credentials (user_id);")

    # ==========================================================================
    # 3. security.user_activation_tokens
    # ==========================================================================
    op.execute("""
        CREATE TABLE security.user_activation_tokens (
            user_activation_token_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id                       UUID NOT NULL
                                    REFERENCES security.users(user_id) ON DELETE CASCADE,
            login_name                        TEXT NOT NULL,
            token_hash                            TEXT NOT NULL,
            created_by_user_id                        UUID
                                    REFERENCES security.users(user_id) ON DELETE SET NULL,
            expires_at                                    TIMESTAMPTZ NOT NULL,
            consumed_at                                       TIMESTAMPTZ,
            created_at                                            TIMESTAMPTZ NOT NULL
                                                                DEFAULT now(),

            CONSTRAINT ux_user_activation_tokens_token_hash UNIQUE (token_hash),
            CONSTRAINT ck_user_activation_tokens_token_hash_length
                CHECK (char_length(token_hash) = 64),
            CONSTRAINT ck_user_activation_tokens_login_name_format
                CHECK (login_name ~ '^[a-z0-9._-]{3,64}$')
        );
    """)
    op.execute("""
        COMMENT ON TABLE security.user_activation_tokens IS
        'A hashed, expiring, single-use token authorizing one user to choose their '
        'local password and claim login_name (docs/PLAN.md §23.1). Consumed atomically '
        'by dnd_ai.commands.local_auth.activate_local_account via a single '
        'UPDATE ... WHERE consumed_at IS NULL ... RETURNING — concurrent consumption '
        'attempts race on that row''s own lock, so exactly one ever succeeds.';
    """)
    op.execute("""
        COMMENT ON COLUMN security.user_activation_tokens.login_name IS
        'The normalized local login name this token, once consumed, binds to the user '
        'as security.external_identities(issuer=''local'', subject=login_name) — '
        'chosen by the administrator at account-creation time (dnd_ai.commands.'
        'local_auth.create_local_account), not secret. Reserved only at consumption, '
        'not at issuance, so two outstanding tokens may name the same login_name; the '
        'first to activate wins and the second fails with a clear, non-disclosing '
        'conflict.';
    """)
    op.execute("""
        COMMENT ON COLUMN security.user_activation_tokens.token_hash IS
        'sha256 hex digest of a server-generated activation token '
        '(dnd_ai.domain.credentials.hash_opaque_secret). The raw token is returned to '
        'the issuing administrator exactly once and never stored or logged.';
    """)
    op.execute("""
        COMMENT ON COLUMN security.user_activation_tokens.created_by_user_id IS
        'NULL only for the one-time initial-admin bootstrap token, which has no issuer.';
    """)
    op.execute(
        "CREATE INDEX ix_user_activation_tokens_user_id "
        "ON security.user_activation_tokens (user_id);"
    )
    op.execute(
        "CREATE INDEX ix_user_activation_tokens_created_by_user_id "
        "ON security.user_activation_tokens (created_by_user_id) "
        "WHERE created_by_user_id IS NOT NULL;"
    )
    op.execute(
        "CREATE UNIQUE INDEX ux_user_activation_tokens_unconsumed "
        "ON security.user_activation_tokens (user_id) WHERE consumed_at IS NULL;"
    )

    # ==========================================================================
    # 4. security.password_reset_tokens
    # ==========================================================================
    op.execute("""
        CREATE TABLE security.password_reset_tokens (
            password_reset_token_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id                      UUID NOT NULL
                                    REFERENCES security.users(user_id) ON DELETE CASCADE,
            token_hash                       TEXT NOT NULL,
            requested_by_user_id                 UUID NOT NULL
                                    REFERENCES security.users(user_id) ON DELETE SET NULL,
            revoke_sessions                          BOOLEAN NOT NULL DEFAULT true,
            expires_at                                   TIMESTAMPTZ NOT NULL,
            consumed_at                                      TIMESTAMPTZ,
            created_at                                           TIMESTAMPTZ NOT NULL
                                                               DEFAULT now(),

            CONSTRAINT ux_password_reset_tokens_token_hash UNIQUE (token_hash),
            CONSTRAINT ck_password_reset_tokens_token_hash_length
                CHECK (char_length(token_hash) = 64)
        );
    """)
    op.execute("""
        COMMENT ON TABLE security.password_reset_tokens IS
        'A hashed, expiring, single-use, administrator-issued password-reset token '
        '(docs/PLAN.md §23.1). Consumed atomically the same '
        'UPDATE ... WHERE consumed_at IS NULL ... RETURNING way '
        'security.user_activation_tokens is.';
    """)
    op.execute("""
        COMMENT ON COLUMN security.password_reset_tokens.token_hash IS
        'sha256 hex digest of a server-generated reset token '
        '(dnd_ai.domain.credentials.hash_opaque_secret). The raw token is returned to '
        'the issuing administrator exactly once and never stored or logged.';
    """)
    op.execute("""
        COMMENT ON COLUMN security.password_reset_tokens.requested_by_user_id IS
        'The administrator (is_platform_administrator) who issued this reset token.';
    """)
    op.execute("""
        COMMENT ON COLUMN security.password_reset_tokens.revoke_sessions IS
        'Whether consuming this token revokes the user''s existing browser sessions and '
        'Foundry device credentials (docs/PLAN.md §23.1''s ''full sign-out'' reset '
        'policy) — dnd_ai.commands.local_auth.reset_password_with_token reads this at '
        'consumption time, never re-derives it.';
    """)
    op.execute(
        "CREATE INDEX ix_password_reset_tokens_user_id ON security.password_reset_tokens (user_id);"
    )
    op.execute(
        "CREATE INDEX ix_password_reset_tokens_requested_by_user_id "
        "ON security.password_reset_tokens (requested_by_user_id);"
    )

    # ==========================================================================
    # 5. security.browser_sessions
    # ==========================================================================
    op.execute("""
        CREATE TABLE security.browser_sessions (
            browser_session_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id                  UUID NOT NULL
                                    REFERENCES security.users(user_id) ON DELETE CASCADE,
            session_token_hash            TEXT NOT NULL,
            csrf_token                        TEXT NOT NULL,
            created_at                            TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_used_at                              TIMESTAMPTZ NOT NULL DEFAULT now(),
            idle_expires_at                               TIMESTAMPTZ NOT NULL,
            absolute_expires_at                               TIMESTAMPTZ NOT NULL,
            revoked_at                                            TIMESTAMPTZ,
            created_ip                                                TEXT,
            last_used_ip                                                  TEXT,
            user_agent                                                        TEXT,

            CONSTRAINT ux_browser_sessions_token_hash UNIQUE (session_token_hash),
            CONSTRAINT ck_browser_sessions_token_hash_length
                CHECK (char_length(session_token_hash) = 64),
            CONSTRAINT ck_browser_sessions_expiry_order
                CHECK (idle_expires_at <= absolute_expires_at)
        );
    """)
    op.execute("""
        COMMENT ON TABLE security.browser_sessions IS
        'An opaque, server-side browser session (docs/PLAN.md §23.4) — named '
        'browser_sessions, not sessions, to avoid colliding with the unrelated '
        'campaign.sessions (game-session) concept docs/architecture/DATABASE_MODEL.md '
        '§6.4 already owns that name for. Revoked or expired rows are never physically '
        'deleted by ordinary application commands — only by an administrative pruning '
        'job, which this revision does not itself add (see this table''s own '
        'migration docstring).';
    """)
    op.execute("""
        COMMENT ON COLUMN security.browser_sessions.session_token_hash IS
        'sha256 hex digest of the opaque value the __Host-dnd_ai_session cookie '
        'carries (docs/PLAN.md §23.4). The raw value never leaves dnd_ai.commands.'
        'local_auth and the Set-Cookie response header that carries it once, at login '
        '— never stored, logged, or returned in a JSON body.';
    """)
    op.execute("""
        COMMENT ON COLUMN security.browser_sessions.csrf_token IS
        'A server-generated CSRF secret, stored in the clear (unlike every other '
        'credential in this table/module): unlike session_token_hash, this value alone '
        'grants nothing — the double-submit contract (docs/PLAN.md §23.4) requires the '
        'matching HttpOnly cookie too, and the session-bootstrap endpoint already '
        'returns this same value to the browser in its JSON body on every call, so '
        'hashing it server-side would not reduce what an attacker with database access '
        'already learns from a live response.';
    """)
    op.execute("""
        COMMENT ON COLUMN security.browser_sessions.idle_expires_at IS
        'Sliding window, extended on each authenticated request up to absolute_expires_at.';
    """)
    op.execute("""
        COMMENT ON COLUMN security.browser_sessions.absolute_expires_at IS
        'A hard ceiling idle_expires_at can never be extended past.';
    """)
    op.execute("CREATE INDEX ix_browser_sessions_user_id ON security.browser_sessions (user_id);")
    op.execute(
        "CREATE INDEX ix_browser_sessions_active ON security.browser_sessions "
        "(user_id, idle_expires_at) WHERE revoked_at IS NULL;"
    )


def downgrade() -> None:
    """Revert the migration."""

    op.execute("DROP TABLE IF EXISTS security.browser_sessions;")
    op.execute("DROP TABLE IF EXISTS security.password_reset_tokens;")
    op.execute("DROP TABLE IF EXISTS security.user_activation_tokens;")
    op.execute("DROP TABLE IF EXISTS security.local_credentials;")
    op.execute("ALTER TABLE security.users DROP COLUMN IF EXISTS is_platform_administrator;")
