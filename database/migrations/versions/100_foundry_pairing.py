"""Foundry hybrid pairing: connections, pairing codes, devices, access tokens

Revision ID: 100_foundry_pairing
Revises: 099_local_authentication
Create Date: 2026-08-21 12:00:00.000000

Purpose:
    Phase 11R workstream D (docs/PLAN.md §23.5, Workstream 11R item 1): the
    schema for individually paired Foundry devices and short-lived access
    tokens, replacing nothing yet (`integration.external_systems.
    system_key_hash`, the shared `FoundrySystem` credential, is untouched by
    this revision — Workstream 11R item 7's forward-only transition removes
    it only once every device has repaired, in a later workstream). Four new
    tables, all in the `security` schema alongside the other credential
    tables workstream A/B added:

    - `security.foundry_connections` — the non-secret binding "D&D AI user
      X, on campaign Y, is Foundry user Z in external system W" (§23.5 step
      4). Portable metadata only.
    - `security.foundry_pairing_codes` — hashed, single-use, short-lived
      bootstrap codes (§23.5 steps 2-3).
    - `security.foundry_devices` — one row per paired browser/device, the
      hashed 30-90 day device credential (§23.5 steps 5-6).
    - `security.foundry_access_tokens` — short-lived (10-30 minute), opaque,
      hash-stored tokens a device exchanges its secret for (§23.5's
      credential table).

    Every hashed-secret column follows the identical "server generates 256
    bits of CSPRNG entropy, returns it exactly once, stores only
    sha256(raw).hexdigest()" shape 089/099 already established
    (dnd_ai.domain.credentials.generate_opaque_secret/.hash_opaque_secret).

    granted_scopes/requested_scopes are `TEXT[]`, per docs/DATABASE_
    CONVENTIONS.md §5.8 ("PostgreSQL arrays may be used for simple ordered
    scalar values when no metadata is needed") — a scope code carries no
    identity, provenance, or per-element metadata of its own, so a junction
    table would add real machinery a fixed, narrow set (docs/PLAN.md §23.5:
    "Initial Foundry scopes remain closed and narrow") does not need yet.
    The CHECK constraints below enforce the exact same closed set
    dnd_ai.domain.foundry_pairing.FOUNDRY_SCOPES defines in Python — the two
    must be kept in sync by hand, the same relationship every other
    Python-closed-set-mirrored-by-a-SQL-CHECK in this codebase already has
    (e.g. ai.proposed_changes.proposal_kind).

    Ordering matters: foundry_connections must exist before foundry_devices
    (FK), foundry_devices before foundry_pairing_codes (consumed_by_
    foundry_device_id FK) and before foundry_access_tokens (FK).

Forward migration:
    - `security.foundry_connections`
    - `security.foundry_devices`
    - `security.foundry_pairing_codes`
    - `security.foundry_access_tokens`

Rollback:
    Supported. Drops the four new tables in reverse dependency order.

Data implications:
    None — every table is new; no existing row is touched.

Locking considerations:
    Four `CREATE TABLE`s only; no existing table is altered.

See: docs/PLAN.md §23.5 (Foundry hybrid pairing and device authentication)
     docs/architecture/DATABASE_MODEL.md §19
     database/migrations/versions/099_local_authentication.py (the
     identical hash-only credential pattern this revision reuses)
     src/dnd_ai/persistence/tables/foundry_pairing.py
     src/dnd_ai/commands/foundry_pairing.py
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "100_foundry_pairing"
down_revision = "099_local_authentication"
branch_labels = None
depends_on = None

# Must match dnd_ai.domain.foundry_pairing.FOUNDRY_SCOPES exactly.
_FOUNDRY_SCOPES_SQL_ARRAY = (
    "ARRAY['encounter_read','sync_status_read','combat_sync',"
    "'character_state_sync','location_read']::TEXT[]"
)


def upgrade() -> None:
    """Apply the migration."""

    # ==========================================================================
    # 1. security.foundry_connections
    # ==========================================================================
    op.execute(f"""
        CREATE TABLE security.foundry_connections (
            foundry_connection_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id                    UUID NOT NULL
                                    REFERENCES security.users(user_id) ON DELETE CASCADE,
            campaign_id                    UUID NOT NULL
                                    REFERENCES campaign.campaigns(campaign_id) ON DELETE CASCADE,
            external_system_id                 UUID NOT NULL
                                    REFERENCES integration.external_systems(external_system_id)
                                    ON DELETE CASCADE,
            foundry_user_id                        TEXT NOT NULL,
            foundry_origin                             TEXT NOT NULL,
            granted_scopes                                 TEXT[] NOT NULL,
            created_at                                         TIMESTAMPTZ NOT NULL
                                                                DEFAULT now(),
            revoked_at                                             TIMESTAMPTZ,
            revoked_by_user_id                                         UUID
                                    REFERENCES security.users(user_id) ON DELETE SET NULL,

            CONSTRAINT ck_foundry_connections_granted_scopes_closed
                CHECK (granted_scopes <@ {_FOUNDRY_SCOPES_SQL_ARRAY}),
            CONSTRAINT ck_foundry_connections_granted_scopes_nonempty
                CHECK (array_length(granted_scopes, 1) >= 1)
        );
    """)
    op.execute("""
        COMMENT ON TABLE security.foundry_connections IS
        'The non-secret Foundry-user binding a pairing code creates or confirms '
        '(docs/PLAN.md §23.5 step 4) — one D&D AI user, one campaign, one external '
        'system/world, one Foundry user id. Several security.foundry_devices rows may '
        'share one connection (several browsers for the same Foundry user); revoking '
        'the connection (dnd_ai.commands.foundry_pairing.revoke_foundry_connection) '
        'revokes every device under it, while revoking one device leaves the '
        'connection and its other devices untouched.';
    """)
    op.execute("""
        COMMENT ON COLUMN security.foundry_connections.foundry_user_id IS
        'The Foundry-side user id this connection binds to one platform user, one '
        'campaign, and one external system — never authorization by itself, only '
        'identity within a connection already established through a consumed pairing '
        'code (dnd_ai.commands.foundry_pairing.consume_foundry_pairing_code).';
    """)
    op.execute("""
        COMMENT ON COLUMN security.foundry_connections.foundry_origin IS
        'The exact Foundry browser origin recorded at pairing time — portability '
        'metadata for the portal''s connection-health display (docs/PLAN.md §23.5), '
        'never consulted by authentication itself.';
    """)
    op.execute("""
        COMMENT ON COLUMN security.foundry_connections.granted_scopes IS
        'The closed set of dnd_ai.domain.foundry_pairing.FOUNDRY_SCOPES codes this '
        'connection may use — re-checked on every access-token-authenticated request '
        '(dnd_ai.domain.foundry_pairing.resolve_foundry_access_principal), never frozen '
        'onto an issued device or access token.';
    """)
    op.execute("""
        COMMENT ON COLUMN security.foundry_connections.revoked_by_user_id IS
        'The GM (access.manage) or the connection''s own user who revoked it.';
    """)
    op.execute(
        "CREATE INDEX ix_foundry_connections_user_id ON security.foundry_connections (user_id);"
    )
    op.execute(
        "CREATE INDEX ix_foundry_connections_campaign_id "
        "ON security.foundry_connections (campaign_id);"
    )
    op.execute(
        "CREATE INDEX ix_foundry_connections_external_system_id "
        "ON security.foundry_connections (external_system_id);"
    )
    op.execute(
        "CREATE UNIQUE INDEX ux_foundry_connections_active ON security.foundry_connections "
        "(campaign_id, external_system_id, foundry_user_id) WHERE revoked_at IS NULL;"
    )

    # ==========================================================================
    # 2. security.foundry_devices
    # ==========================================================================
    op.execute("""
        CREATE TABLE security.foundry_devices (
            foundry_device_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            foundry_connection_id  UUID NOT NULL
                                    REFERENCES security.foundry_connections(foundry_connection_id)
                                    ON DELETE CASCADE,
            device_label                TEXT NOT NULL,
            module_version                  TEXT,
            foundry_version                     TEXT,
            device_secret_hash                      TEXT NOT NULL,
            created_at                                  TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_used_at                                    TIMESTAMPTZ,
            expires_at                                          TIMESTAMPTZ NOT NULL,
            revoked_at                                              TIMESTAMPTZ,
            revoked_by_user_id                                          UUID
                                    REFERENCES security.users(user_id) ON DELETE SET NULL,
            replaced_by_foundry_device_id                                   UUID
                                    REFERENCES security.foundry_devices(foundry_device_id)
                                    ON DELETE SET NULL,

            CONSTRAINT ux_foundry_devices_device_secret_hash UNIQUE (device_secret_hash),
            CONSTRAINT ck_foundry_devices_device_secret_hash_length
                CHECK (char_length(device_secret_hash) = 64)
        );
    """)
    op.execute("""
        COMMENT ON TABLE security.foundry_devices IS
        'One paired browser/device under a security.foundry_connections row '
        '(docs/PLAN.md §23.5 steps 5-6) — the client-scoped device credential a '
        'FoundryVTT module exchanges for short-lived security.foundry_access_tokens on '
        'startup. Revoking a device leaves its connection and any sibling devices '
        'untouched; revoking the connection cascades to every device under it '
        '(dnd_ai.commands.foundry_pairing.revoke_foundry_connection).';
    """)
    op.execute("""
        COMMENT ON COLUMN security.foundry_devices.device_label IS
        'The Foundry-generated device id plus module/Foundry version this row was '
        'paired with (docs/PLAN.md §23.5 step 3) — descriptive only, shown in the '
        'portal''s device list, never used for authentication.';
    """)
    op.execute("""
        COMMENT ON COLUMN security.foundry_devices.device_secret_hash IS
        'sha256 hex digest of a server-generated, 30-90 day device credential '
        '(dnd_ai.domain.credentials.hash_opaque_secret). The raw secret is returned to '
        'the pairing Foundry client exactly once, for storage only in its own '
        'client-scoped game.settings value, and is never stored or logged here.';
    """)
    op.execute("""
        COMMENT ON COLUMN security.foundry_devices.replaced_by_foundry_device_id IS
        'Set by dnd_ai.commands.foundry_pairing.rotate_foundry_device when rotation is '
        'requested with a bounded overlap window — this row''s own revoked_at is then '
        'set to the end of that window rather than immediately, and this column records '
        'which new device row superseded it. NULL for a device that was never rotated, '
        'and for the new row a rotation produces.';
    """)
    op.execute(
        "CREATE INDEX ix_foundry_devices_foundry_connection_id "
        "ON security.foundry_devices (foundry_connection_id);"
    )
    op.execute(
        "CREATE INDEX ix_foundry_devices_replaced_by_foundry_device_id "
        "ON security.foundry_devices (replaced_by_foundry_device_id) "
        "WHERE replaced_by_foundry_device_id IS NOT NULL;"
    )

    # ==========================================================================
    # 3. security.foundry_pairing_codes
    # ==========================================================================
    op.execute(f"""
        CREATE TABLE security.foundry_pairing_codes (
            foundry_pairing_code_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id                      UUID NOT NULL
                                    REFERENCES security.users(user_id) ON DELETE CASCADE,
            campaign_id                       UUID NOT NULL
                                    REFERENCES campaign.campaigns(campaign_id) ON DELETE CASCADE,
            external_system_id                    UUID NOT NULL
                                    REFERENCES integration.external_systems(external_system_id)
                                    ON DELETE CASCADE,
            code_hash                                 TEXT NOT NULL,
            requested_scopes                              TEXT[] NOT NULL,
            created_by_browser_session_id                     UUID
                                    REFERENCES security.browser_sessions(browser_session_id)
                                    ON DELETE SET NULL,
            expires_at                                            TIMESTAMPTZ NOT NULL,
            consumed_at                                               TIMESTAMPTZ,
            consumed_by_foundry_device_id                                 UUID
                                    REFERENCES security.foundry_devices(foundry_device_id)
                                    ON DELETE SET NULL,
            created_at                                                        TIMESTAMPTZ
                                                                        NOT NULL DEFAULT now(),

            CONSTRAINT ux_foundry_pairing_codes_code_hash UNIQUE (code_hash),
            CONSTRAINT ck_foundry_pairing_codes_code_hash_length
                CHECK (char_length(code_hash) = 64),
            CONSTRAINT ck_foundry_pairing_codes_requested_scopes_closed
                CHECK (requested_scopes <@ {_FOUNDRY_SCOPES_SQL_ARRAY}),
            CONSTRAINT ck_foundry_pairing_codes_requested_scopes_nonempty
                CHECK (array_length(requested_scopes, 1) >= 1)
        );
    """)
    op.execute("""
        COMMENT ON TABLE security.foundry_pairing_codes IS
        'A hashed, single-use, 5-10 minute bootstrap code (docs/PLAN.md §23.5 steps '
        '2-4) a local-session-authenticated user creates from the portal and enters '
        'into a FoundryVTT client to pair one browser/device. Consumed atomically by '
        'dnd_ai.commands.foundry_pairing.consume_foundry_pairing_code via a single '
        'UPDATE ... WHERE consumed_at IS NULL ... RETURNING — the identical single-'
        'winner pattern security.user_activation_tokens already established.';
    """)
    op.execute("""
        COMMENT ON COLUMN security.foundry_pairing_codes.code_hash IS
        'sha256 hex digest of a server-generated pairing code '
        '(dnd_ai.domain.credentials.hash_opaque_secret). The raw code is returned to '
        'the creating browser session exactly once and never stored or logged.';
    """)
    op.execute("""
        COMMENT ON COLUMN security.foundry_pairing_codes.requested_scopes IS
        'The dnd_ai.domain.foundry_pairing.FOUNDRY_SCOPES this code, once consumed, '
        'grants to the resulting/confirmed security.foundry_connections row.';
    """)
    op.execute("""
        COMMENT ON COLUMN security.foundry_pairing_codes.created_by_browser_session_id IS
        'The portal browser session that created this code, for audit only.';
    """)
    op.execute("""
        COMMENT ON COLUMN security.foundry_pairing_codes.consumed_by_foundry_device_id IS
        'The device this code minted, set atomically with consumption.';
    """)
    op.execute(
        "CREATE INDEX ix_foundry_pairing_codes_user_id "
        "ON security.foundry_pairing_codes (user_id);"
    )
    op.execute(
        "CREATE INDEX ix_foundry_pairing_codes_campaign_id "
        "ON security.foundry_pairing_codes (campaign_id);"
    )
    op.execute(
        "CREATE INDEX ix_foundry_pairing_codes_external_system_id "
        "ON security.foundry_pairing_codes (external_system_id);"
    )
    op.execute(
        "CREATE INDEX ix_foundry_pairing_codes_created_by_browser_session_id "
        "ON security.foundry_pairing_codes (created_by_browser_session_id) "
        "WHERE created_by_browser_session_id IS NOT NULL;"
    )

    # ==========================================================================
    # 4. security.foundry_access_tokens
    # ==========================================================================
    op.execute("""
        CREATE TABLE security.foundry_access_tokens (
            foundry_access_token_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            foundry_device_id            UUID NOT NULL
                                    REFERENCES security.foundry_devices(foundry_device_id)
                                    ON DELETE CASCADE,
            token_hash                       TEXT NOT NULL,
            issued_at                            TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at                               TIMESTAMPTZ NOT NULL,
            revoked_at                                   TIMESTAMPTZ,
            last_used_at                                     TIMESTAMPTZ,

            CONSTRAINT ux_foundry_access_tokens_token_hash UNIQUE (token_hash),
            CONSTRAINT ck_foundry_access_tokens_token_hash_length
                CHECK (char_length(token_hash) = 64)
        );
    """)
    op.execute("""
        COMMENT ON TABLE security.foundry_access_tokens IS
        'A short-lived opaque access token exchanged from a security.foundry_devices '
        'credential (docs/PLAN.md §23.5''s credential table) for ordinary Foundry-'
        'adapter API requests. Deliberately carries no scope/campaign snapshot of its '
        'own — dnd_ai.domain.foundry_pairing.resolve_foundry_access_principal always '
        're-resolves its owning device''s connection at request time, so revoking the '
        'connection or device takes effect on this token''s very next use even though '
        'the token row itself is untouched.';
    """)
    op.execute("""
        COMMENT ON COLUMN security.foundry_access_tokens.token_hash IS
        'sha256 hex digest of a server-generated, 10-30 minute opaque access token '
        '(dnd_ai.domain.credentials.hash_opaque_secret) — the Authorization: '
        'FoundryAccess <token> bearer value (docs/PLAN.md §23.5). Held only in memory '
        'by the Foundry client; never stored or logged here or by it.';
    """)
    op.execute(
        "CREATE INDEX ix_foundry_access_tokens_foundry_device_id "
        "ON security.foundry_access_tokens (foundry_device_id);"
    )


def downgrade() -> None:
    """Revert the migration."""

    op.execute("DROP TABLE IF EXISTS security.foundry_access_tokens;")
    op.execute("DROP TABLE IF EXISTS security.foundry_pairing_codes;")
    op.execute("DROP TABLE IF EXISTS security.foundry_devices;")
    op.execute("DROP TABLE IF EXISTS security.foundry_connections;")
