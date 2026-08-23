"""Foundry hybrid-pairing commands (docs/PLAN.md §23.5 — Phase 11R
workstream D): hashed single-use pairing codes, portable Foundry-user
connections, per-device hash-stored credentials, and short-lived opaque
access tokens.

`integration.external_systems.system_key_hash` (the shared legacy
`FoundrySystem` credential) is untouched by this module — Workstream 11R
item 7's forward-only transition removes it only once every client has
repaired. `dnd_ai.domain.access.AuthenticatedPrincipal`'s `FOUNDRY_ACCESS_
AUTH_METHOD` type and `dnd_ai.api.auth.get_authenticated_user_id`'s
`Authorization: FoundryAccess <token>` scheme (Phase 11R workstream C) sit
on top of this module's `exchange_foundry_device_credential` — see `dnd_ai.
domain.foundry_pairing.resolve_foundry_access_principal` for the read-only
authentication resolver built on this schema. No HTTP endpoint in this
codebase calls any command in this module yet, nor has any existing
bounded adapter route (`dnd_ai.api.integration`, `.character_state`,
`.characters`) opted into the sibling `allow_foundry_access` authorization
gate — the management/pairing API surface and the route conversion are
later Phase 11R workstreams (E and F respectively), kept separate so this
workstream's own schema and command-layer invariants could be reviewed and
tested independently first.

Every command here follows the same `_impl(connection, ...)` composable
+ `Engine`-based public-wrapper split `dnd_ai.commands.local_auth` and
`dnd_ai.commands.integration` already establish (see either module's own
docstring for the pattern), and every hashed-secret column follows the
identical "generate with `dnd_ai.domain.credentials.generate_opaque_
secret`, return the raw value exactly once, persist only `hash_opaque_
secret(raw)`" shape those modules already use.

Revalidation, not caching (docs/PLAN.md §23.5: "Every API request again
resolves current capabilities... so an access token cannot preserve
revoked campaign authorization"): `exchange_foundry_device_credential`
re-checks the device, its connection, the bound user's lifecycle status,
and that user's active campaign membership *every time it is called* —
none of that is frozen onto the access token it issues, and the token
itself carries no scope/campaign snapshot of its own (`security.
foundry_access_tokens` has no such column — see that table's own
comment). `dnd_ai.domain.foundry_pairing.resolve_foundry_access_principal`
(Phase 11R workstream C) is deliberately *not* the place that repeats the
active-campaign-membership check this function performs at issuance —
`dnd_ai.api.access.require_campaign_capability`'s own `resolve_access_
context` call already performs the identical live-membership check for
every principal type uniformly (OIDC, local-session, and Foundry alike),
once a route actually opts into `allow_foundry_access` (Workstream F).

Ownership vs. capability-gated calls: `revoke_foundry_device`/
`revoke_foundry_connection` accept an `expected_owner_user_id` parameter —
when supplied (the "a user manages their own device" case), the row must
belong to that user or the call raises `ForeignFoundryDeviceError`/
`ForeignFoundryConnectionError`, mirroring `dnd_ai.commands.local_auth.
revoke_browser_session`'s identical `ForeignBrowserSessionError` shape.
`expected_owner_user_id=None` is the "already authorized some other way"
case (a GM revoking a campaign device/connection via `access.manage`,
checked by the future API layer's `require_campaign_capability`, not by
this module) — the same `expected_world_id=None`/`expected_campaign_id=
None` "unscoped mode" every other command module in this codebase already
uses for the identical "caller already proved authorization upstream"
situation.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Connection, Engine, text

from dnd_ai.commands.integration import ExternalSystemNotFoundError
from dnd_ai.domain.credentials import generate_opaque_secret, hash_opaque_secret
from dnd_ai.domain.errors import DomainAuthorizationError
from dnd_ai.domain.foundry_pairing import validate_foundry_scopes

_PAIRING_CODE_TTL = timedelta(minutes=10)
_DEVICE_TTL = timedelta(days=60)
_ACCESS_TOKEN_TTL = timedelta(minutes=20)


def _external_system_world(connection: Connection, external_system_id: uuid.UUID) -> uuid.UUID:
    """Local copy of `dnd_ai.commands.integration._external_system_world` —
    that function is underscore-prefixed (module-private) by convention, so
    this module keeps its own rather than importing across a private
    boundary; both raise the identical, public `ExternalSystemNotFoundError`
    so a caller sees one consistent error type regardless of which module
    performed the check."""
    value = connection.execute(
        text("SELECT world_id FROM integration.external_systems WHERE external_system_id = :s"),
        {"s": external_system_id},
    ).scalar()
    if value is None:
        raise ExternalSystemNotFoundError(f"external system {external_system_id} does not exist")
    assert isinstance(value, uuid.UUID)
    return value


def _active_campaign_membership_exists(
    connection: Connection, *, user_id: uuid.UUID, campaign_id: uuid.UUID
) -> bool:
    """The same active-membership predicate `dnd_ai.domain.access.
    resolve_access_context` uses, as a plain boolean — this module needs
    only "does an authorizing membership still exist," not a full
    `AccessContext`."""
    value = connection.execute(
        text("""
            SELECT 1
            FROM security.campaign_memberships cm
            JOIN security.membership_statuses ms
              ON ms.membership_status_id = cm.membership_status_id
            WHERE cm.campaign_id = :campaign_id
              AND cm.user_id = :user_id
              AND cm.ended_at IS NULL
              AND ms.code = 'active'
              AND ms.is_active
        """),
        {"campaign_id": campaign_id, "user_id": user_id},
    ).scalar()
    return value is not None


# ==========================================================================
# Pairing codes
# ==========================================================================


@dataclass(frozen=True)
class IssuedFoundryPairingCode:
    foundry_pairing_code_id: uuid.UUID
    raw_code: str
    campaign_id: uuid.UUID
    external_system_id: uuid.UUID
    requested_scopes: tuple[str, ...]
    expires_at: datetime


def _create_foundry_pairing_code_impl(
    connection: Connection,
    *,
    requesting_user_id: uuid.UUID,
    campaign_id: uuid.UUID,
    external_system_id: uuid.UUID,
    requested_scopes: frozenset[str] | set[str] | list[str],
    created_by_browser_session_id: uuid.UUID | None = None,
    expected_world_id: uuid.UUID | None = None,
    ttl: timedelta = _PAIRING_CODE_TTL,
) -> IssuedFoundryPairingCode:
    """The actual work of `create_foundry_pairing_code()`, on a connection
    the caller already has open. A local-session-authenticated portal user
    creates a code for themselves (docs/PLAN.md §23.5 steps 1-2); this
    function does not itself check campaign membership — the future API
    endpoint (workstream E) authorizes `requesting_user_id` for
    `campaign_id` via `require_campaign_capability` before ever calling
    this, the same "authorization happens one layer up, commands trust
    it" split `dnd_ai.commands.integration.issue_foundry_system_key`
    already establishes for its own `access.manage` check.

    `expected_world_id`, when supplied, asserts `external_system_id`
    belongs to that world before writing anything — identical in shape to
    every sibling `expected_world_id` argument in `dnd_ai.commands.
    integration`."""
    scopes = validate_foundry_scopes(requested_scopes)
    if expected_world_id is not None:
        world_id = _external_system_world(connection, external_system_id)
        if world_id != expected_world_id:
            raise ExternalSystemNotFoundError(
                f"external system {external_system_id} belongs to world {world_id!r}, "
                f"not {expected_world_id!r}"
            )

    raw_code = generate_opaque_secret()
    expires_at = datetime.now(UTC) + ttl
    foundry_pairing_code_id = connection.execute(
        text("""
            INSERT INTO security.foundry_pairing_codes
                (user_id, campaign_id, external_system_id, code_hash, requested_scopes,
                 created_by_browser_session_id, expires_at)
            VALUES (:user_id, :campaign_id, :system, :hash, :scopes, :session, :expires_at)
            RETURNING foundry_pairing_code_id
        """),
        {
            "user_id": requesting_user_id,
            "campaign_id": campaign_id,
            "system": external_system_id,
            "hash": hash_opaque_secret(raw_code),
            "scopes": list(scopes),
            "session": created_by_browser_session_id,
            "expires_at": expires_at,
        },
    ).scalar()
    assert isinstance(foundry_pairing_code_id, uuid.UUID)
    return IssuedFoundryPairingCode(
        foundry_pairing_code_id=foundry_pairing_code_id,
        raw_code=raw_code,
        campaign_id=campaign_id,
        external_system_id=external_system_id,
        requested_scopes=scopes,
        expires_at=expires_at,
    )


def create_foundry_pairing_code(
    engine: Engine,
    *,
    requesting_user_id: uuid.UUID,
    campaign_id: uuid.UUID,
    external_system_id: uuid.UUID,
    requested_scopes: frozenset[str] | set[str] | list[str],
    created_by_browser_session_id: uuid.UUID | None = None,
    expected_world_id: uuid.UUID | None = None,
    ttl: timedelta = _PAIRING_CODE_TTL,
) -> IssuedFoundryPairingCode:
    """Public convenience API: opens and commits its own transaction. See
    `_create_foundry_pairing_code_impl()` for the composable form a caller
    with its own transaction (e.g. an API command endpoint) uses instead."""
    with engine.begin() as connection:
        return _create_foundry_pairing_code_impl(
            connection,
            requesting_user_id=requesting_user_id,
            campaign_id=campaign_id,
            external_system_id=external_system_id,
            requested_scopes=requested_scopes,
            created_by_browser_session_id=created_by_browser_session_id,
            expected_world_id=expected_world_id,
            ttl=ttl,
        )


class PairingCodeNotAcceptableError(DomainAuthorizationError):
    """Raised by `consume_foundry_pairing_code()` for a nonexistent,
    already-consumed, expired code, or one whose creating user no longer
    holds an active campaign membership — all deliberately indistinguishable
    to the caller (mirrors `dnd_ai.commands.local_auth.
    ActivationNotAcceptableError`'s identical reasoning: a Foundry client
    presenting a bad code learns nothing about *why* it failed)."""


@dataclass(frozen=True)
class ConsumedFoundryPairingCode:
    foundry_connection_id: uuid.UUID
    foundry_device_id: uuid.UUID
    raw_device_secret: str
    raw_access_token: str
    user_id: uuid.UUID
    campaign_id: uuid.UUID
    external_system_id: uuid.UUID
    granted_scopes: tuple[str, ...]
    device_expires_at: datetime
    access_token_expires_at: datetime


def _consume_foundry_pairing_code_impl(
    connection: Connection,
    *,
    raw_code: str,
    foundry_user_id: str,
    foundry_origin: str,
    device_label: str,
    module_version: str | None = None,
    foundry_version: str | None = None,
    device_ttl: timedelta = _DEVICE_TTL,
    access_token_ttl: timedelta = _ACCESS_TOKEN_TTL,
) -> ConsumedFoundryPairingCode:
    """The actual work of `consume_foundry_pairing_code()`, on a connection
    the caller already has open.

    Single-use consumption follows the identical `UPDATE ... WHERE
    consumed_at IS NULL AND expires_at > now() ... RETURNING` pattern
    `dnd_ai.commands.local_auth._activate_local_account_impl` already
    established for activation tokens — exactly one concurrent caller for
    the same code ever observes a non-empty result; every other racing
    caller sees `rowcount == 0` and raises `PairingCodeNotAcceptableError`
    the same as a genuinely expired/unknown code (see
    `tests/database/test_foundry_pairing_commands.py`'s concurrency test).

    After consumption, re-validates the code's own `user_id` still holds an
    active `campaign_id` membership (docs/PLAN.md §23.5 step 4: "D&D AI
    atomically consumes the code, validates campaign membership... creates
    or confirms the non-secret Foundry-user binding") — a membership that
    was active when the code was *created* may have been revoked in the
    minutes before a Foundry client actually enters it.

    Upserts `security.foundry_connections` on `ux_foundry_connections_
    active` (docs/PLAN.md §23.5 step 4's "creates or confirms") — a second
    pairing for the same (campaign, external system, Foundry user) reuses
    the existing connection row (refreshing `foundry_origin`/`granted_
    scopes` to the newly consumed code's own values) rather than creating a
    duplicate, then always inserts a *new* `security.foundry_devices` row
    under it — one connection may have several devices (several browsers
    for the same Foundry user), never the reverse."""
    now = datetime.now(UTC)
    code_hash = hash_opaque_secret(raw_code)
    code_row = (
        connection.execute(
            text("""
                UPDATE security.foundry_pairing_codes
                SET consumed_at = now()
                WHERE code_hash = :hash AND consumed_at IS NULL AND expires_at > now()
                RETURNING foundry_pairing_code_id, user_id, campaign_id, external_system_id,
                          requested_scopes
            """),
            {"hash": code_hash},
        )
        .mappings()
        .one_or_none()
    )
    if code_row is None:
        raise PairingCodeNotAcceptableError("pairing code is unknown, already consumed, or expired")

    if not _active_campaign_membership_exists(
        connection, user_id=code_row["user_id"], campaign_id=code_row["campaign_id"]
    ):
        raise PairingCodeNotAcceptableError(
            f"user {code_row['user_id']} no longer holds an active membership in campaign "
            f"{code_row['campaign_id']}"
        )

    granted_scopes = tuple(code_row["requested_scopes"])
    foundry_connection_id = connection.execute(
        text("""
            INSERT INTO security.foundry_connections
                (user_id, campaign_id, external_system_id, foundry_user_id, foundry_origin,
                 granted_scopes)
            VALUES (:user_id, :campaign_id, :system, :foundry_user, :origin, :scopes)
            ON CONFLICT (campaign_id, external_system_id, foundry_user_id)
                WHERE revoked_at IS NULL
            DO UPDATE SET foundry_origin = EXCLUDED.foundry_origin,
                          granted_scopes = EXCLUDED.granted_scopes
            RETURNING foundry_connection_id
        """),
        {
            "user_id": code_row["user_id"],
            "campaign_id": code_row["campaign_id"],
            "system": code_row["external_system_id"],
            "foundry_user": foundry_user_id,
            "origin": foundry_origin,
            "scopes": list(granted_scopes),
        },
    ).scalar()
    assert isinstance(foundry_connection_id, uuid.UUID)

    raw_device_secret = generate_opaque_secret()
    device_expires_at = now + device_ttl
    foundry_device_id = connection.execute(
        text("""
            INSERT INTO security.foundry_devices
                (foundry_connection_id, device_label, module_version, foundry_version,
                 device_secret_hash, expires_at)
            VALUES (:connection, :label, :module_version, :foundry_version, :hash, :expires_at)
            RETURNING foundry_device_id
        """),
        {
            "connection": foundry_connection_id,
            "label": device_label,
            "module_version": module_version,
            "foundry_version": foundry_version,
            "hash": hash_opaque_secret(raw_device_secret),
            "expires_at": device_expires_at,
        },
    ).scalar()
    assert isinstance(foundry_device_id, uuid.UUID)

    connection.execute(
        text("""
            UPDATE security.foundry_pairing_codes
            SET consumed_by_foundry_device_id = :device
            WHERE foundry_pairing_code_id = :code
        """),
        {"device": foundry_device_id, "code": code_row["foundry_pairing_code_id"]},
    )

    raw_access_token = generate_opaque_secret()
    access_token_expires_at = now + access_token_ttl
    connection.execute(
        text("""
            INSERT INTO security.foundry_access_tokens (foundry_device_id, token_hash, expires_at)
            VALUES (:device, :hash, :expires_at)
        """),
        {
            "device": foundry_device_id,
            "hash": hash_opaque_secret(raw_access_token),
            "expires_at": access_token_expires_at,
        },
    )

    return ConsumedFoundryPairingCode(
        foundry_connection_id=foundry_connection_id,
        foundry_device_id=foundry_device_id,
        raw_device_secret=raw_device_secret,
        raw_access_token=raw_access_token,
        user_id=code_row["user_id"],
        campaign_id=code_row["campaign_id"],
        external_system_id=code_row["external_system_id"],
        granted_scopes=granted_scopes,
        device_expires_at=device_expires_at,
        access_token_expires_at=access_token_expires_at,
    )


def consume_foundry_pairing_code(
    engine: Engine,
    *,
    raw_code: str,
    foundry_user_id: str,
    foundry_origin: str,
    device_label: str,
    module_version: str | None = None,
    foundry_version: str | None = None,
    device_ttl: timedelta = _DEVICE_TTL,
    access_token_ttl: timedelta = _ACCESS_TOKEN_TTL,
) -> ConsumedFoundryPairingCode:
    """Public convenience API: opens and commits its own transaction. See
    `_consume_foundry_pairing_code_impl()` for the composable form a caller
    with its own transaction uses instead."""
    with engine.begin() as connection:
        return _consume_foundry_pairing_code_impl(
            connection,
            raw_code=raw_code,
            foundry_user_id=foundry_user_id,
            foundry_origin=foundry_origin,
            device_label=device_label,
            module_version=module_version,
            foundry_version=foundry_version,
            device_ttl=device_ttl,
            access_token_ttl=access_token_ttl,
        )


# ==========================================================================
# Access-token exchange
# ==========================================================================


@dataclass(frozen=True)
class ExchangedFoundryAccessToken:
    raw_access_token: str
    expires_at: datetime
    foundry_device_id: uuid.UUID
    foundry_connection_id: uuid.UUID
    user_id: uuid.UUID
    campaign_id: uuid.UUID
    external_system_id: uuid.UUID
    granted_scopes: tuple[str, ...]


def exchange_foundry_device_credential(
    connection: Connection,
    *,
    foundry_device_id: uuid.UUID,
    raw_device_secret: str,
    access_token_ttl: timedelta = _ACCESS_TOKEN_TTL,
) -> ExchangedFoundryAccessToken | None:
    """A Foundry client's device credential exchange (docs/PLAN.md §23.5
    step 6: "the module exchanges the stored device credential for a new
    access token") — the on-startup/on-expiry counterpart to
    `consume_foundry_pairing_code`'s initial issuance. Composable only (no
    `Engine`-based public wrapper): this is an authentication check, the
    same "always takes the caller's own connection" shape `dnd_ai.domain.
    access.resolve_foundry_system_principal` uses, not a caller-facing
    management command — the Phase 11R workstream E `POST /foundry/token`
    endpoint calls this directly on its own per-request connection, parsing
    the `Authorization: FoundryDevice <device_id>.<raw_secret>` header
    itself rather than going through `get_authenticated_user_id`/
    `AuthenticatedPrincipal` — see this module's own docstring for why no
    Foundry-device principal type exists at all.

    Returns `None`, uniformly, for every failure mode — unknown device id,
    wrong secret, revoked or expired device, revoked connection, an
    inactive bound user, or a bound user with no more active campaign
    membership in the connection's campaign — deliberately without
    distinguishing which, the same fail-closed, non-disclosing contract
    `resolve_foundry_system_principal` already establishes. Every one of
    those conditions is checked *fresh* on this call, never cached from
    when the device or connection was created (this module's own docstring
    — "revalidation, not caching").

    A device's own `revoked_at` is an *effective revocation time*, not a
    boolean flag: `rotate_foundry_device`'s bounded-overlap mode can set it
    to a point in the *future*, and this check (`revoked_at IS NULL OR
    revoked_at > now()`) treats such a device as still valid until that
    moment arrives — a still-serviceable old secret during its overlap
    window must keep exchanging, not be rejected the instant rotation
    happens. `security.foundry_connections.revoked_at` has no such overlap
    concept (`revoke_foundry_connection` always revokes immediately), so
    that half of the check stays a plain `IS NULL`.

    On success, bumps the device's own `last_used_at` and mints a brand
    new `security.foundry_access_tokens` row — this never returns or
    extends a *previous* token; each call is a fresh issuance, exactly like
    `dnd_ai.commands.integration.issue_foundry_system_key`'s own "rotation,
    not addition" shape, except scoped to access tokens rather than the
    device credential itself (a device secret is deliberately long-lived
    and is never rotated by this function — see `rotate_foundry_device`
    for that separate, explicit operation)."""
    device_secret_hash = hash_opaque_secret(raw_device_secret)
    row = (
        connection.execute(
            text("""
                SELECT fd.foundry_device_id, fc.foundry_connection_id, fc.user_id,
                       fc.campaign_id, fc.external_system_id, fc.granted_scopes
                FROM security.foundry_devices fd
                JOIN security.foundry_connections fc
                  ON fc.foundry_connection_id = fd.foundry_connection_id
                JOIN security.users u ON u.user_id = fc.user_id
                JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = u.lifecycle_status_id
                WHERE fd.foundry_device_id = :device
                  AND fd.device_secret_hash = :hash
                  AND (fd.revoked_at IS NULL OR fd.revoked_at > now())
                  AND fd.expires_at > now()
                  AND fc.revoked_at IS NULL
                  AND ls.code = 'active'
            """),
            {"device": foundry_device_id, "hash": device_secret_hash},
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    if not _active_campaign_membership_exists(
        connection, user_id=row["user_id"], campaign_id=row["campaign_id"]
    ):
        return None

    connection.execute(
        text(
            "UPDATE security.foundry_devices SET last_used_at = now() WHERE foundry_device_id = :d"
        ),
        {"d": foundry_device_id},
    )
    raw_access_token = generate_opaque_secret()
    expires_at = datetime.now(UTC) + access_token_ttl
    connection.execute(
        text("""
            INSERT INTO security.foundry_access_tokens (foundry_device_id, token_hash, expires_at)
            VALUES (:device, :hash, :expires_at)
        """),
        {
            "device": foundry_device_id,
            "hash": hash_opaque_secret(raw_access_token),
            "expires_at": expires_at,
        },
    )
    return ExchangedFoundryAccessToken(
        raw_access_token=raw_access_token,
        expires_at=expires_at,
        foundry_device_id=row["foundry_device_id"],
        foundry_connection_id=row["foundry_connection_id"],
        user_id=row["user_id"],
        campaign_id=row["campaign_id"],
        external_system_id=row["external_system_id"],
        granted_scopes=tuple(row["granted_scopes"]),
    )


# ==========================================================================
# Device/connection management
# ==========================================================================


class ForeignFoundryDeviceError(DomainAuthorizationError):
    """Raised by `revoke_foundry_device()`/`rotate_foundry_device()` when
    `foundry_device_id` does not belong (via its connection) to the caller's
    own `expected_owner_user_id`, or is not part of the caller's own
    `expected_campaign_id` — mirrors `dnd_ai.commands.local_auth.
    ForeignBrowserSessionError` exactly."""


class ForeignFoundryConnectionError(DomainAuthorizationError):
    """Raised by `revoke_foundry_connection()` when `foundry_connection_id`
    does not belong to the caller's own `expected_owner_user_id`, or is not
    part of the caller's own `expected_campaign_id`."""


def revoke_foundry_device(
    connection: Connection,
    *,
    foundry_device_id: uuid.UUID,
    revoked_by_user_id: uuid.UUID,
    expected_owner_user_id: uuid.UUID | None = None,
    expected_campaign_id: uuid.UUID | None = None,
) -> None:
    """Revoke one device (docs/PLAN.md §23.5: "Users can revoke their own
    devices; authorized GMs can revoke campaign devices"). Leaves the
    device's connection and any sibling devices under it untouched — see
    `revoke_foundry_connection` for the broader operation. A no-op for an
    already-revoked or nonexistent device, matching `revoke_browser_
    session`'s identical "already the caller's desired end state" reasoning
    — except when `expected_owner_user_id`/`expected_campaign_id` is
    supplied and the device belongs to a *different* user/campaign, which
    raises `ForeignFoundryDeviceError` rather than silently doing nothing.

    `expected_owner_user_id` is the self-service case (a user revoking
    their own device); `expected_campaign_id` is the GM case (`access.
    manage`-authorized revocation of *any* device in one campaign,
    regardless of which user it belongs to). The two are never combined by
    any caller in this codebase, but nothing here forbids supplying both —
    a device must then satisfy both to be revoked. Without `expected_
    campaign_id`, a GM authorized only for campaign A could otherwise
    revoke an arbitrary device belonging to campaign B merely by guessing
    or observing its id — the identical cross-campaign leak class `dnd_ai.
    commands._shared.SessionNotInCampaignError`'s own docstring documents
    for an unrelated resource."""
    params: dict[str, object] = {"device": foundry_device_id, "revoked_by": revoked_by_user_id}
    scope_clause = ""
    if expected_owner_user_id is not None:
        scope_clause += (
            " AND foundry_connection_id IN ("
            "SELECT foundry_connection_id FROM security.foundry_connections WHERE user_id = :owner"
            ")"
        )
        params["owner"] = expected_owner_user_id
    if expected_campaign_id is not None:
        scope_clause += (
            " AND foundry_connection_id IN ("
            "SELECT foundry_connection_id FROM security.foundry_connections "
            "WHERE campaign_id = :campaign)"
        )
        params["campaign"] = expected_campaign_id

    result = connection.execute(
        text(f"""
            UPDATE security.foundry_devices
            SET revoked_at = now(), revoked_by_user_id = :revoked_by
            WHERE foundry_device_id = :device AND revoked_at IS NULL{scope_clause}
        """),
        params,
    )
    if result.rowcount == 0 and (
        expected_owner_user_id is not None or expected_campaign_id is not None
    ):
        # rowcount == 0 here means either the device doesn't exist, it's
        # already revoked (both a no-op), or it fails the owner/campaign
        # scope (an error) — this second query distinguishes the last case
        # from the first two by checking scope alone, without the earlier
        # UPDATE's own "AND revoked_at IS NULL" narrowing it away: an
        # already-revoked, still-in-scope device must stay a no-op, not be
        # misreported as foreign merely because it no longer matched the
        # UPDATE's row-selection predicate.
        exists_out_of_scope_clauses = []
        exists_params: dict[str, object] = {"device": foundry_device_id}
        if expected_owner_user_id is not None:
            exists_out_of_scope_clauses.append("fc.user_id != :owner")
            exists_params["owner"] = expected_owner_user_id
        if expected_campaign_id is not None:
            exists_out_of_scope_clauses.append("fc.campaign_id != :campaign")
            exists_params["campaign"] = expected_campaign_id
        exists_for_other_scope = connection.execute(
            text(
                "SELECT 1 FROM security.foundry_devices fd "
                "JOIN security.foundry_connections fc "
                "  ON fc.foundry_connection_id = fd.foundry_connection_id "
                "WHERE fd.foundry_device_id = :device AND ("
                + " OR ".join(exists_out_of_scope_clauses)
                + ")"
            ),
            exists_params,
        ).scalar()
        if exists_for_other_scope is not None:
            raise ForeignFoundryDeviceError(
                f"foundry device {foundry_device_id} does not match the expected "
                f"owner/campaign scope"
            )


@dataclass(frozen=True)
class RotatedFoundryDevice:
    old_foundry_device_id: uuid.UUID
    new_foundry_device_id: uuid.UUID
    raw_device_secret: str
    expires_at: datetime
    old_device_revoked_at: datetime


def _rotate_foundry_device_impl(
    connection: Connection,
    *,
    foundry_device_id: uuid.UUID,
    requesting_user_id: uuid.UUID,
    overlap: timedelta | None = None,
    new_device_ttl: timedelta = _DEVICE_TTL,
) -> RotatedFoundryDevice:
    """The actual work of `rotate_foundry_device()`, on a connection the
    caller already has open. Always ownership-checked — unlike `revoke_
    foundry_device`, rotation is self-service only (docs/PLAN.md §23.5:
    "list/revoke/rotate the caller's devices" — a GM's own device-
    management authority extends only to revocation, not to minting a new
    secret on a user's behalf).

    `overlap=None` (the default) revokes the old device immediately, the
    instant the new one is created — "rotation issues a new secret once...
    and does not change the portable binding" (docs/PLAN.md §23.5) with no
    grace period. `overlap=<timedelta>` instead sets the old device's
    `revoked_at` to `now() + overlap` — "invalidates the prior secret after
    a bounded overlap only when explicitly requested" (same passage) — so a
    client that already has the old secret in flight keeps working for that
    window while a newly paired client can start using the new one
    immediately. Either way, `replaced_by_foundry_device_id` links the old
    row to the new one so the portal's device list can show the rotation
    history rather than an unexplained new device appearing."""
    row = (
        connection.execute(
            text("""
                SELECT fd.foundry_connection_id, fd.revoked_at, fc.user_id
                FROM security.foundry_devices fd
                JOIN security.foundry_connections fc
                  ON fc.foundry_connection_id = fd.foundry_connection_id
                WHERE fd.foundry_device_id = :device
                FOR UPDATE OF fd
            """),
            {"device": foundry_device_id},
        )
        .mappings()
        .one_or_none()
    )
    if row is None or row["user_id"] != requesting_user_id:
        raise ForeignFoundryDeviceError(
            f"foundry device {foundry_device_id} does not belong to user {requesting_user_id}"
        )
    if row["revoked_at"] is not None:
        raise ForeignFoundryDeviceError(f"foundry device {foundry_device_id} is already revoked")

    raw_device_secret = generate_opaque_secret()
    expires_at = datetime.now(UTC) + new_device_ttl
    new_foundry_device_id = connection.execute(
        text("""
            INSERT INTO security.foundry_devices
                (foundry_connection_id, device_label, device_secret_hash, expires_at)
            SELECT foundry_connection_id, device_label, :hash, :expires_at
            FROM security.foundry_devices WHERE foundry_device_id = :old_device
            RETURNING foundry_device_id
        """),
        {
            "hash": hash_opaque_secret(raw_device_secret),
            "expires_at": expires_at,
            "old_device": foundry_device_id,
        },
    ).scalar()
    assert isinstance(new_foundry_device_id, uuid.UUID)

    # revoked_at is computed by PostgreSQL's own now(), never Python's
    # datetime.now() — both this UPDATE and exchange_foundry_device_
    # credential's later "revoked_at > now()" comparison must agree on the
    # same clock, and a value stamped by a different process's wall clock
    # (even off by a few milliseconds) could make an immediate revocation
    # (overlap=None, intended as "revoked_at == now()") spuriously compare
    # as still in the future.
    overlap_seconds = overlap.total_seconds() if overlap is not None else 0
    old_device_revoked_at = connection.execute(
        text("""
            UPDATE security.foundry_devices
            SET revoked_at = now() + (:overlap_seconds * INTERVAL '1 second'),
                replaced_by_foundry_device_id = :new_device
            WHERE foundry_device_id = :old_device
            RETURNING revoked_at
        """),
        {
            "overlap_seconds": overlap_seconds,
            "new_device": new_foundry_device_id,
            "old_device": foundry_device_id,
        },
    ).scalar()
    assert isinstance(old_device_revoked_at, datetime)

    return RotatedFoundryDevice(
        old_foundry_device_id=foundry_device_id,
        new_foundry_device_id=new_foundry_device_id,
        raw_device_secret=raw_device_secret,
        expires_at=expires_at,
        old_device_revoked_at=old_device_revoked_at,
    )


def rotate_foundry_device(
    engine: Engine,
    *,
    foundry_device_id: uuid.UUID,
    requesting_user_id: uuid.UUID,
    overlap: timedelta | None = None,
    new_device_ttl: timedelta = _DEVICE_TTL,
) -> RotatedFoundryDevice:
    """Public convenience API: opens and commits its own transaction. See
    `_rotate_foundry_device_impl()` for the composable form a caller with
    its own transaction uses instead."""
    with engine.begin() as connection:
        return _rotate_foundry_device_impl(
            connection,
            foundry_device_id=foundry_device_id,
            requesting_user_id=requesting_user_id,
            overlap=overlap,
            new_device_ttl=new_device_ttl,
        )


def revoke_foundry_connection(
    connection: Connection,
    *,
    foundry_connection_id: uuid.UUID,
    revoked_by_user_id: uuid.UUID,
    expected_owner_user_id: uuid.UUID | None = None,
    expected_campaign_id: uuid.UUID | None = None,
) -> None:
    """Revoke an entire connection and cascade to every device under it
    (docs/PLAN.md §23.5: "authorized GMs can revoke campaign devices or the
    connection"). Devices are also marked `revoked_at` here, not left to be
    implied only by their connection's own `revoked_at` — `exchange_
    foundry_device_credential`'s join already checks both independently, so
    this cascade is defense in depth plus giving the portal's device list an
    accurate per-device revoked state to display, not a correctness
    requirement by itself. A no-op for an already-revoked or nonexistent
    connection; `ForeignFoundryConnectionError` if `expected_owner_user_id`/
    `expected_campaign_id` is supplied and does not match — same shape (and
    same GM-cross-campaign-leak rationale) as `revoke_foundry_device`."""
    params: dict[str, object] = {
        "connection": foundry_connection_id,
        "revoked_by": revoked_by_user_id,
    }
    scope_clause = ""
    if expected_owner_user_id is not None:
        scope_clause += " AND user_id = :owner"
        params["owner"] = expected_owner_user_id
    if expected_campaign_id is not None:
        scope_clause += " AND campaign_id = :campaign"
        params["campaign"] = expected_campaign_id

    result = connection.execute(
        text(f"""
            UPDATE security.foundry_connections
            SET revoked_at = now(), revoked_by_user_id = :revoked_by
            WHERE foundry_connection_id = :connection AND revoked_at IS NULL{scope_clause}
        """),
        params,
    )
    if result.rowcount == 0:
        if expected_owner_user_id is not None or expected_campaign_id is not None:
            # See revoke_foundry_device's identical comment: this must check
            # scope alone, not "does the row exist at all" — an already-
            # revoked, still-in-scope connection is still a no-op, not a
            # foreign-scope error.
            exists_out_of_scope_clauses = []
            exists_params: dict[str, object] = {"connection": foundry_connection_id}
            if expected_owner_user_id is not None:
                exists_out_of_scope_clauses.append("user_id != :owner")
                exists_params["owner"] = expected_owner_user_id
            if expected_campaign_id is not None:
                exists_out_of_scope_clauses.append("campaign_id != :campaign")
                exists_params["campaign"] = expected_campaign_id
            exists_for_other_scope = connection.execute(
                text(
                    "SELECT 1 FROM security.foundry_connections "
                    "WHERE foundry_connection_id = :connection AND ("
                    + " OR ".join(exists_out_of_scope_clauses)
                    + ")"
                ),
                exists_params,
            ).scalar()
            if exists_for_other_scope is not None:
                raise ForeignFoundryConnectionError(
                    f"foundry connection {foundry_connection_id} does not match the expected "
                    f"owner/campaign scope"
                )
        return

    connection.execute(
        text("""
            UPDATE security.foundry_devices
            SET revoked_at = now(), revoked_by_user_id = :revoked_by
            WHERE foundry_connection_id = :connection AND revoked_at IS NULL
        """),
        {"connection": foundry_connection_id, "revoked_by": revoked_by_user_id},
    )


def revoke_all_foundry_connections(connection: Connection, *, user_id: uuid.UUID) -> None:
    """Revokes every active Foundry connection (and, by cascade, every
    device under each) for `user_id` — the Foundry-credential counterpart
    to `dnd_ai.commands.local_auth.revoke_all_browser_sessions`, called by
    that module's `reset_password_with_token` when the reset token's own
    `revoke_sessions` flag is set (docs/PLAN.md §23.1's "full sign-out"
    reset policy now also reaching Foundry device credentials, closing the
    gap that function's own docstring flagged as this workstream's
    responsibility once this schema existed)."""
    connection_ids = [
        row[0]
        for row in connection.execute(
            text(
                "SELECT foundry_connection_id FROM security.foundry_connections "
                "WHERE user_id = :user_id AND revoked_at IS NULL"
            ),
            {"user_id": user_id},
        )
    ]
    for foundry_connection_id in connection_ids:
        revoke_foundry_connection(
            connection, foundry_connection_id=foundry_connection_id, revoked_by_user_id=user_id
        )


@dataclass(frozen=True)
class FoundryDeviceSummary:
    foundry_device_id: uuid.UUID
    foundry_connection_id: uuid.UUID
    user_id: uuid.UUID
    campaign_id: uuid.UUID
    external_system_id: uuid.UUID
    foundry_user_id: str
    device_label: str
    granted_scopes: tuple[str, ...]
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime
    is_revoked: bool


_FOUNDRY_DEVICE_SUMMARY_SELECT = """
    SELECT fd.foundry_device_id, fd.foundry_connection_id, fc.user_id, fc.campaign_id,
           fc.external_system_id, fc.foundry_user_id, fd.device_label,
           fc.granted_scopes, fd.created_at, fd.last_used_at, fd.expires_at,
           (fd.revoked_at IS NOT NULL OR fc.revoked_at IS NOT NULL) AS is_revoked
    FROM security.foundry_devices fd
    JOIN security.foundry_connections fc
      ON fc.foundry_connection_id = fd.foundry_connection_id
"""


def _foundry_device_summary(row: Any) -> FoundryDeviceSummary:
    return FoundryDeviceSummary(
        foundry_device_id=row["foundry_device_id"],
        foundry_connection_id=row["foundry_connection_id"],
        user_id=row["user_id"],
        campaign_id=row["campaign_id"],
        external_system_id=row["external_system_id"],
        foundry_user_id=row["foundry_user_id"],
        device_label=row["device_label"],
        granted_scopes=tuple(row["granted_scopes"]),
        created_at=row["created_at"],
        last_used_at=row["last_used_at"],
        expires_at=row["expires_at"],
        is_revoked=row["is_revoked"],
    )


def list_foundry_devices(
    connection: Connection, *, user_id: uuid.UUID
) -> list[FoundryDeviceSummary]:
    """Every device across every connection owned by `user_id`, most-
    recently-created first — `is_revoked` is `True` if either the device
    itself or its owning connection has been revoked, since a portal
    listing should show a device revoked-by-connection-cascade the same way
    it shows one revoked directly (`revoke_foundry_connection`'s own device
    cascade already keeps these in sync going forward, but this listing
    does not rely on that alone)."""
    rows = connection.execute(
        text(
            f"{_FOUNDRY_DEVICE_SUMMARY_SELECT} WHERE fc.user_id = :user_id ORDER BY fd.created_at DESC"
        ),
        {"user_id": user_id},
    ).mappings()
    return [_foundry_device_summary(row) for row in rows]


def list_foundry_devices_for_campaign(
    connection: Connection, *, campaign_id: uuid.UUID
) -> list[FoundryDeviceSummary]:
    """Every device across every connection paired for `campaign_id`,
    most-recently-created first — the GM-facing counterpart to `list_
    foundry_devices` (docs/PLAN.md §23.5: "Portal connection management
    shows... for authorized GMs, campaign connection health"), scoped by
    campaign rather than by the caller's own `user_id`. The caller
    authorizing this as a GM action (`access.manage`) is the future API
    endpoint's responsibility, not this function's — it returns every
    device in the campaign unconditionally, the same "authorization
    happens one layer up" split every other command in this module
    follows."""
    rows = connection.execute(
        text(
            f"{_FOUNDRY_DEVICE_SUMMARY_SELECT} WHERE fc.campaign_id = :campaign_id "
            "ORDER BY fd.created_at DESC"
        ),
        {"campaign_id": campaign_id},
    ).mappings()
    return [_foundry_device_summary(row) for row in rows]
