"""Foundry hybrid-pairing tables — security schema (Phase 11R workstream D,
docs/PLAN.md §23.5, Workstream 11R item 1).

Part of the src/dnd_ai/persistence/tables package. See
src/dnd_ai/persistence/tables/__init__.py for the metadata-authority note
this module inherits: this is compared against the live database by
`alembic check`, so declared tables/columns/comments must match migrations
exactly.

CHECK constraints and triggers are not declared here — see that same
__init__.py note for why (alembic does not compare them; tests cover them).

Four tables, replacing the single-shared-secret `integration.
external_systems.system_key_hash` credential (Phase 11 workstream 2, twice
security-corrected — see that column's own comment) with individually
paired devices, per §23.5:

- `foundry_connections` — the non-secret binding "D&D AI user X, on
  campaign Y, is Foundry user Z in external system W" (§23.5 step 4).
  Portable metadata only, never a bearer credential.
- `foundry_pairing_codes` — the hashed, single-use, 5-10 minute bootstrap
  code a user generates from the portal and enters into Foundry (§23.5
  steps 2-4).
- `foundry_devices` — one row per paired browser/device, holding the
  hashed 30-90 day device secret a Foundry client presents to obtain
  access tokens (§23.5 step 5-6). Belongs to exactly one connection; a
  connection may have several devices (several browsers for the same
  Foundry user).
- `foundry_access_tokens` — short-lived (10-30 minute), opaque,
  hash-stored tokens a device exchanges its secret for for ordinary
  adapter requests (§23.5's credential table). Never carries its own
  scope snapshot — `dnd_ai.domain.foundry_pairing.resolve_foundry_access_
  principal` always re-resolves the owning connection's *current*
  `granted_scopes`/`revoked_at` at request time, so a token cannot outlive
  a revoked connection or device (§23.5: "every API request again resolves
  current capabilities... so an access token cannot preserve revoked
  campaign authorization").
"""

from sqlalchemy import (
    Column,
    ForeignKey,
    Index,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, TIMESTAMP, UUID

from ._shared import _uuid_pk, metadata

foundry_connections = Table(
    "foundry_connections",
    metadata,
    _uuid_pk("foundry_connection_id"),
    Column(
        "user_id",
        UUID(),
        ForeignKey("security.users.user_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "campaign_id",
        UUID(),
        ForeignKey("campaign.campaigns.campaign_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "external_system_id",
        UUID(),
        ForeignKey("integration.external_systems.external_system_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "foundry_user_id",
        Text(),
        nullable=False,
        comment=(
            "The Foundry-side user id this connection binds to one platform user, one "
            "campaign, and one external system — never authorization by itself, only "
            "identity within a connection already established through a consumed "
            "pairing code (dnd_ai.commands.foundry_pairing.consume_foundry_pairing_code)."
        ),
    ),
    Column(
        "foundry_origin",
        Text(),
        nullable=False,
        comment=(
            "The exact Foundry browser origin recorded at pairing time — portability "
            "metadata for the portal's connection-health display (docs/PLAN.md §23.5), "
            "never consulted by authentication itself."
        ),
    ),
    Column(
        "granted_scopes",
        ARRAY(Text()),
        nullable=False,
        comment=(
            "The closed set of dnd_ai.domain.foundry_pairing.FOUNDRY_SCOPES codes this "
            "connection may use — re-checked on every access-token-authenticated request "
            "(dnd_ai.domain.foundry_pairing.resolve_foundry_access_principal), never "
            "frozen onto an issued device or access token."
        ),
    ),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("revoked_at", TIMESTAMP(timezone=True)),
    Column(
        "revoked_by_user_id",
        UUID(),
        ForeignKey("security.users.user_id", ondelete="SET NULL"),
        comment="The GM (access.manage) or the connection's own user who revoked it.",
    ),
    schema="security",
    comment=(
        "The non-secret Foundry-user binding a pairing code creates or confirms "
        "(docs/PLAN.md §23.5 step 4) — one D&D AI user, one campaign, one external "
        "system/world, one Foundry user id. Several security.foundry_devices rows may "
        "share one connection (several browsers for the same Foundry user); revoking "
        "the connection (dnd_ai.commands.foundry_pairing.revoke_foundry_connection) "
        "revokes every device under it, while revoking one device leaves the "
        "connection and its other devices untouched."
    ),
)

Index("ix_foundry_connections_user_id", foundry_connections.c.user_id)
Index("ix_foundry_connections_campaign_id", foundry_connections.c.campaign_id)
Index("ix_foundry_connections_external_system_id", foundry_connections.c.external_system_id)
Index(
    "ix_foundry_connections_revoked_by_user_id",
    foundry_connections.c.revoked_by_user_id,
    postgresql_where=foundry_connections.c.revoked_by_user_id.isnot(None),
)
Index(
    "ux_foundry_connections_active",
    foundry_connections.c.campaign_id,
    foundry_connections.c.external_system_id,
    foundry_connections.c.foundry_user_id,
    unique=True,
    postgresql_where=foundry_connections.c.revoked_at.is_(None),
)

foundry_pairing_codes = Table(
    "foundry_pairing_codes",
    metadata,
    _uuid_pk("foundry_pairing_code_id"),
    Column(
        "user_id",
        UUID(),
        ForeignKey("security.users.user_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "campaign_id",
        UUID(),
        ForeignKey("campaign.campaigns.campaign_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "external_system_id",
        UUID(),
        ForeignKey("integration.external_systems.external_system_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "code_hash",
        Text(),
        nullable=False,
        comment=(
            "sha256 hex digest of a server-generated pairing code "
            "(dnd_ai.domain.credentials.hash_opaque_secret). The raw code is returned "
            "to the creating browser session exactly once and never stored or logged."
        ),
    ),
    Column(
        "requested_scopes",
        ARRAY(Text()),
        nullable=False,
        comment=(
            "The dnd_ai.domain.foundry_pairing.FOUNDRY_SCOPES this code, once consumed, "
            "grants to the resulting/confirmed security.foundry_connections row."
        ),
    ),
    Column(
        "created_by_browser_session_id",
        UUID(),
        ForeignKey("security.browser_sessions.browser_session_id", ondelete="SET NULL"),
        comment="The portal browser session that created this code, for audit only.",
    ),
    Column("expires_at", TIMESTAMP(timezone=True), nullable=False),
    Column("consumed_at", TIMESTAMP(timezone=True)),
    Column(
        "consumed_by_foundry_device_id",
        UUID(),
        ForeignKey("security.foundry_devices.foundry_device_id", ondelete="SET NULL"),
        comment="The device this code minted, set atomically with consumption.",
    ),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    UniqueConstraint("code_hash", name="ux_foundry_pairing_codes_code_hash"),
    schema="security",
    comment=(
        "A hashed, single-use, 5-10 minute bootstrap code (docs/PLAN.md §23.5 steps "
        "2-4) a local-session-authenticated user creates from the portal and enters "
        "into a FoundryVTT client to pair one browser/device. Consumed atomically by "
        "dnd_ai.commands.foundry_pairing.consume_foundry_pairing_code via a single "
        "UPDATE ... WHERE consumed_at IS NULL ... RETURNING — the identical single-"
        "winner pattern security.user_activation_tokens already established."
    ),
)

Index("ix_foundry_pairing_codes_user_id", foundry_pairing_codes.c.user_id)
Index("ix_foundry_pairing_codes_campaign_id", foundry_pairing_codes.c.campaign_id)
Index("ix_foundry_pairing_codes_external_system_id", foundry_pairing_codes.c.external_system_id)
Index(
    "ix_foundry_pairing_codes_created_by_browser_session_id",
    foundry_pairing_codes.c.created_by_browser_session_id,
    postgresql_where=foundry_pairing_codes.c.created_by_browser_session_id.isnot(None),
)
Index(
    "ix_foundry_pairing_codes_consumed_by_foundry_device_id",
    foundry_pairing_codes.c.consumed_by_foundry_device_id,
    postgresql_where=foundry_pairing_codes.c.consumed_by_foundry_device_id.isnot(None),
)

foundry_devices = Table(
    "foundry_devices",
    metadata,
    _uuid_pk("foundry_device_id"),
    Column(
        "foundry_connection_id",
        UUID(),
        ForeignKey("security.foundry_connections.foundry_connection_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "device_label",
        Text(),
        nullable=False,
        comment=(
            "The Foundry-generated device id plus module/Foundry version this row was "
            "paired with (docs/PLAN.md §23.5 step 3) — descriptive only, shown in the "
            "portal's device list, never used for authentication."
        ),
    ),
    Column("module_version", Text()),
    Column("foundry_version", Text()),
    Column(
        "device_secret_hash",
        Text(),
        nullable=False,
        comment=(
            "sha256 hex digest of a server-generated, 30-90 day device credential "
            "(dnd_ai.domain.credentials.hash_opaque_secret). The raw secret is returned "
            "to the pairing Foundry client exactly once, for storage only in its own "
            "client-scoped game.settings value, and is never stored or logged here."
        ),
    ),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("last_used_at", TIMESTAMP(timezone=True)),
    Column("expires_at", TIMESTAMP(timezone=True), nullable=False),
    Column("revoked_at", TIMESTAMP(timezone=True)),
    Column(
        "revoked_by_user_id",
        UUID(),
        ForeignKey("security.users.user_id", ondelete="SET NULL"),
    ),
    Column(
        "replaced_by_foundry_device_id",
        UUID(),
        ForeignKey("security.foundry_devices.foundry_device_id", ondelete="SET NULL"),
        comment=(
            "Set by dnd_ai.commands.foundry_pairing.rotate_foundry_device when rotation "
            "is requested with a bounded overlap window — this row's own revoked_at is "
            "then set to the end of that window rather than immediately, and this column "
            "records which new device row superseded it. NULL for a device that was "
            "never rotated, and for the new row a rotation produces."
        ),
    ),
    UniqueConstraint("device_secret_hash", name="ux_foundry_devices_device_secret_hash"),
    schema="security",
    comment=(
        "One paired browser/device under a security.foundry_connections row "
        "(docs/PLAN.md §23.5 steps 5-6) — the client-scoped device credential a "
        "FoundryVTT module exchanges for short-lived security.foundry_access_tokens "
        "on startup. Revoking a device leaves its connection and any sibling devices "
        "untouched; revoking the connection cascades to every device under it "
        "(dnd_ai.commands.foundry_pairing.revoke_foundry_connection)."
    ),
)

Index("ix_foundry_devices_foundry_connection_id", foundry_devices.c.foundry_connection_id)
Index(
    "ix_foundry_devices_replaced_by_foundry_device_id",
    foundry_devices.c.replaced_by_foundry_device_id,
    postgresql_where=foundry_devices.c.replaced_by_foundry_device_id.isnot(None),
)
Index(
    "ix_foundry_devices_revoked_by_user_id",
    foundry_devices.c.revoked_by_user_id,
    postgresql_where=foundry_devices.c.revoked_by_user_id.isnot(None),
)

foundry_access_tokens = Table(
    "foundry_access_tokens",
    metadata,
    _uuid_pk("foundry_access_token_id"),
    Column(
        "foundry_device_id",
        UUID(),
        ForeignKey("security.foundry_devices.foundry_device_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "token_hash",
        Text(),
        nullable=False,
        comment=(
            "sha256 hex digest of a server-generated, 10-30 minute opaque access token "
            "(dnd_ai.domain.credentials.hash_opaque_secret) — the Authorization: "
            "FoundryAccess <token> bearer value (docs/PLAN.md §23.5). Held only in "
            "memory by the Foundry client; never stored or logged here or by it."
        ),
    ),
    Column("issued_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("expires_at", TIMESTAMP(timezone=True), nullable=False),
    Column("revoked_at", TIMESTAMP(timezone=True)),
    Column("last_used_at", TIMESTAMP(timezone=True)),
    UniqueConstraint("token_hash", name="ux_foundry_access_tokens_token_hash"),
    schema="security",
    comment=(
        "A short-lived opaque access token exchanged from a security.foundry_devices "
        "credential (docs/PLAN.md §23.5's credential table) for ordinary Foundry-"
        "adapter API requests. Deliberately carries no scope/campaign snapshot of its "
        "own — dnd_ai.domain.foundry_pairing.resolve_foundry_access_principal always "
        "re-resolves its owning device's connection at request time, so revoking the "
        "connection or device takes effect on this token's very next use even though "
        "the token row itself is untouched."
    ),
)

Index("ix_foundry_access_tokens_foundry_device_id", foundry_access_tokens.c.foundry_device_id)
