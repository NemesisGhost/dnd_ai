"""Local account lifecycle and browser-session commands (docs/PLAN.md
§23.1, §23.4 — Phase 11R workstream A/B).

The one production command path that ever creates a `security.users` row
today (no other command in this codebase inserts one — OIDC/Foundry
principals are resolved against rows this module, or a future JIT-
provisioning command, must have already created). Reuses `security.
external_identities` for the login-name identity mapping, exactly the way
`dnd_ai.commands.integration.link_foundry_identity` already reuses it for
Foundry — see `dnd_ai.domain.access.LOCAL_AUTH_ISSUER`'s own docstring.

Every hashed-secret token here (activation, password reset, browser
session) follows the identical "SELECT ... FOR UPDATE, check, UPDATE"
single-use consumption shape `dnd_ai.commands.campaign_invitations.
accept_campaign_invitation` already established, and the identical
"generate with `dnd_ai.domain.credentials.generate_opaque_secret`, return
the raw value exactly once, persist only `hash_opaque_secret(raw)`" shape
`issue_foundry_system_key` already established for its own credential.

Constant-work login (`authenticate_local_user`): every rejection path
(unknown login name, no local credential row, inactive account, wrong
password) still calls `dnd_ai.domain.passwords.verify_password` against
some Argon2id hash — `dnd_ai.domain.passwords.DUMMY_PASSWORD_HASH` when no
real one exists — before returning, so the observable cost of "no such
account" and "wrong password for a real account" are the same order of
magnitude. This does not, and cannot, equalize database round-trip timing
or query-plan differences; it only removes the one component (Argon2id's
own deliberately-expensive computation, which dominates total request time
by design) that would otherwise make "the hash check never ran at all" the
single largest, cheapest-to-observe timing signal.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import Connection, Engine, text

from dnd_ai.domain.access import (
    LOCAL_AUTH_ISSUER,
    LOCAL_SESSION_AUTH_METHOD,
    AuthenticatedPrincipal,
    is_platform_administrator,
)
from dnd_ai.domain.credentials import generate_opaque_secret, hash_opaque_secret
from dnd_ai.domain.errors import AuthenticationError, DomainAuthorizationError, SafeMessageError
from dnd_ai.domain.passwords import (
    DUMMY_PASSWORD_HASH,
    hash_password,
    password_needs_rehash,
    validate_password_policy,
    verify_password,
)

from ._shared import lookup_id
from .foundry_pairing import revoke_all_foundry_connections

_ACTIVATION_TOKEN_TTL = timedelta(hours=48)
_PASSWORD_RESET_TOKEN_TTL = timedelta(hours=2)
_BROWSER_SESSION_IDLE_TIMEOUT = timedelta(minutes=30)
_BROWSER_SESSION_ABSOLUTE_TIMEOUT = timedelta(hours=12)
_ACTIVE_LIFECYCLE_STATUS_CODE = "active"


def _active_lifecycle_status_id(connection: Connection) -> uuid.UUID:
    return lookup_id(
        connection,
        "core",
        "lifecycle_statuses",
        "lifecycle_status_id",
        _ACTIVE_LIFECYCLE_STATUS_CODE,
    )


def normalize_login_name(raw_login_name: str) -> str:
    """The one place a login name is lowercased/trimmed before it is ever
    compared, stored, or checked against `ck_user_activation_tokens_login_
    name_format` (`^[a-z0-9._-]{3,64}$`, migration 099) — callers pass the
    normalized value everywhere else in this module rather than each
    re-deriving it, so a login name can never be reserved or matched in
    two different cases."""
    return raw_login_name.strip().lower()


class LoginNameFormatError(SafeMessageError):
    """`raw_login_name`, once normalized, does not satisfy the login-name
    format every `security.user_activation_tokens.login_name`/`security.
    external_identities(issuer='local').subject` row must (migration 099's
    `ck_user_activation_tokens_login_name_format`) — 3-64 characters,
    lowercase ASCII letters/digits/`.`/`_`/`-` only. Raised before any
    database round-trip, not left to surface as an opaque constraint
    violation."""

    safe_error_code = "invalid_login_name"
    safe_message = (
        "Login names must be 3-64 characters: lowercase letters, digits, '.', '_', or '-' only."
    )


_LOGIN_NAME_MIN_LENGTH = 3
_LOGIN_NAME_MAX_LENGTH = 64
_LOGIN_NAME_ALLOWED_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789._-")


def _validate_login_name_format(login_name: str) -> None:
    if not (_LOGIN_NAME_MIN_LENGTH <= len(login_name) <= _LOGIN_NAME_MAX_LENGTH):
        raise LoginNameFormatError()
    if any(ch not in _LOGIN_NAME_ALLOWED_CHARS for ch in login_name):
        raise LoginNameFormatError()


class NotPlatformAdministratorError(DomainAuthorizationError):
    """Raised when a caller who is not `security.users.is_platform_
    administrator` attempts an account-management operation
    (`create_local_account`, `issue_password_reset_token`). A fixed,
    non-disclosing 404 via `DomainAuthorizationError`, matching every other
    "you are not authorized to know this exists" case in this codebase —
    an ordinary authenticated user should learn nothing about whether
    account-management operations exist at all, let alone why theirs was
    refused."""


class AlreadyBootstrappedError(SafeMessageError):
    """`bootstrap_initial_admin` refuses to run once any `security.users`
    row already exists — "fails closed after use" (docs/PLAN.md §23.1). A
    disclosing message is safe here: this command is never reachable over
    HTTP (deployment-time only, invoked directly against the database by
    an operator who already has that access), so there is no unauthorized
    caller for this message to leak information to."""

    safe_status_code = 409
    safe_error_code = "already_bootstrapped"
    safe_message = (
        "The platform already has at least one user; the initial-admin bootstrap "
        "operation only runs once, against a completely empty security.users table."
    )


@dataclass(frozen=True)
class IssuedActivationToken:
    user_id: uuid.UUID
    user_activation_token_id: uuid.UUID
    raw_token: str
    login_name: str
    expires_at: datetime


def _create_user_with_activation_token(
    connection: Connection,
    *,
    login_name: str,
    display_name: str,
    email: str | None,
    created_by_user_id: uuid.UUID | None,
    is_platform_administrator_flag: bool,
) -> IssuedActivationToken:
    """Shared by `bootstrap_initial_admin` and `create_local_account`:
    creates the `security.users` row and its first (and, until consumed,
    only) `security.user_activation_tokens` row in one transaction. The
    login name is *not* reserved anywhere durable yet — see this module's
    docstring and `security.user_activation_tokens.login_name`'s own
    column comment — so this never conflicts with an existing active
    identity merely because a name is already in use by a different
    outstanding, unconsumed token."""
    normalized_login_name = normalize_login_name(login_name)
    _validate_login_name_format(normalized_login_name)

    active_status_id = _active_lifecycle_status_id(connection)
    user_id = connection.execute(
        text("""
            INSERT INTO security.users
                (display_name, email, lifecycle_status_id, is_platform_administrator)
            VALUES (:display_name, :email, :status, :is_admin)
            RETURNING user_id
        """),
        {
            "display_name": display_name,
            "email": email,
            "status": active_status_id,
            "is_admin": is_platform_administrator_flag,
        },
    ).scalar()
    assert isinstance(user_id, uuid.UUID)

    raw_token = generate_opaque_secret()
    token_hash = hash_opaque_secret(raw_token)
    expires_at = datetime.now(UTC) + _ACTIVATION_TOKEN_TTL
    activation_token_id = connection.execute(
        text("""
            INSERT INTO security.user_activation_tokens
                (user_id, login_name, token_hash, created_by_user_id, expires_at)
            VALUES (:user_id, :login_name, :hash, :created_by, :expires_at)
            RETURNING user_activation_token_id
        """),
        {
            "user_id": user_id,
            "login_name": normalized_login_name,
            "hash": token_hash,
            "created_by": created_by_user_id,
            "expires_at": expires_at,
        },
    ).scalar()
    assert isinstance(activation_token_id, uuid.UUID)

    return IssuedActivationToken(
        user_id=user_id,
        user_activation_token_id=activation_token_id,
        raw_token=raw_token,
        login_name=normalized_login_name,
        expires_at=expires_at,
    )


def bootstrap_initial_admin(
    engine: Engine, *, login_name: str, display_name: str, email: str | None = None
) -> IssuedActivationToken:
    """The one-time initial-administrator bootstrap (docs/PLAN.md §23.1):
    creates the very first `security.users` row, with `is_platform_
    administrator = true`, and its activation token. Deployment-time only
    — deliberately never exposed over HTTP (there is no `dnd_ai.api.
    local_auth` route for it); the intended caller is an operator running
    `scripts/bootstrap_admin.py` with direct database access, the same
    "trusted infrastructure, never over HTTP" posture `security.timeline_
    bootstrap_grants`' own migration comment already establishes for that
    table's analogous first-campaign entitlement.

    Fails closed (`AlreadyBootstrappedError`) unless `security.users` is
    completely empty — serialized against a concurrent call via a session-
    scoped advisory lock held for the whole transaction, so two operators
    racing to bootstrap at the same moment cannot both observe zero rows
    and both succeed."""
    with engine.begin() as connection:
        connection.execute(
            text("SELECT pg_advisory_xact_lock(hashtext('bootstrap_initial_admin'))")
        )
        existing = connection.execute(text("SELECT count(*) FROM security.users")).scalar()
        if existing:
            raise AlreadyBootstrappedError()
        return _create_user_with_activation_token(
            connection,
            login_name=login_name,
            display_name=display_name,
            email=email,
            created_by_user_id=None,
            is_platform_administrator_flag=True,
        )


def _create_local_account_impl(
    connection: Connection,
    *,
    created_by_user_id: uuid.UUID,
    login_name: str,
    display_name: str,
    email: str | None = None,
) -> IssuedActivationToken:
    """The composable form of `create_local_account`, on a connection the
    caller already has open — the same `_..._impl`/public-wrapper split
    `dnd_ai.commands.integration._issue_foundry_system_key_impl` already
    establishes, so an API route with its own request-scoped transaction
    (`dnd_ai.api.local_auth.create_account_endpoint`) calls this directly
    instead of opening a second, independent transaction via the public
    wrapper below. `created_by_user_id` must already be a platform
    administrator (`NotPlatformAdministratorError` otherwise) — checked
    here, inside the caller's own transaction, not merely at the API
    layer, so this remains safe to call directly (tests, scripts) without
    re-deriving that check."""
    if not is_platform_administrator(connection, user_id=created_by_user_id):
        raise NotPlatformAdministratorError(
            f"user {created_by_user_id} is not a platform administrator"
        )
    return _create_user_with_activation_token(
        connection,
        login_name=login_name,
        display_name=display_name,
        email=email,
        created_by_user_id=created_by_user_id,
        is_platform_administrator_flag=False,
    )


def create_local_account(
    engine: Engine,
    *,
    created_by_user_id: uuid.UUID,
    login_name: str,
    display_name: str,
    email: str | None = None,
) -> IssuedActivationToken:
    """Public convenience API: opens and commits its own transaction. See
    `_create_local_account_impl` for the composable form a caller with its
    own transaction (an API command endpoint) uses instead."""
    with engine.begin() as connection:
        return _create_local_account_impl(
            connection,
            created_by_user_id=created_by_user_id,
            login_name=login_name,
            display_name=display_name,
            email=email,
        )


class ActivationNotAcceptableError(DomainAuthorizationError):
    """Raised by `activate_local_account` for a token that does not resolve
    to a consumable activation — nonexistent, already consumed, or expired
    — all indistinguishably, mirroring `dnd_ai.commands.
    campaign_invitations.InvitationNotAcceptableError`'s identical
    reasoning for why a bearer token's rejection must never vary by
    cause."""


class LoginNameAlreadyTakenError(SafeMessageError):
    """Raised by `activate_local_account` when the token's own `login_name`
    was claimed by a *different* now-activated account between this
    token's issuance and its consumption (two administrators independently
    issued activation tokens naming the same login name; the second to
    consume loses to the first). Disclosing "this name is taken" here is
    safe: the caller already possesses a valid, unexpired, single-use
    token proving an administrator specifically issued *them* an account —
    this is not a caller probing for arbitrary account existence, and the
    fix (choose a different login name and ask the administrator to
    re-issue) requires knowing the reason."""

    safe_status_code = 409
    safe_error_code = "login_name_taken"
    safe_message = "That login name was claimed by another account. Ask an administrator to reissue your activation with a different login name."


@dataclass(frozen=True)
class ActivateLocalAccountResult:
    user_id: uuid.UUID
    login_name: str


def _activate_local_account_impl(
    connection: Connection, *, raw_activation_token: str, raw_password: str
) -> ActivateLocalAccountResult:
    """The composable form of `activate_local_account` — see
    `_create_local_account_impl`'s docstring for the pattern. Consumes
    `raw_activation_token`, setting the account's first password and
    claiming its `login_name` (docs/PLAN.md §23.1). Atomic, single-use,
    race-free under concurrency: `SELECT ... FOR UPDATE` locks the token
    row for the duration of this transaction, so a second concurrent
    consumption attempt for the *same* token blocks until this one commits
    or rolls back, then observes `consumed_at` already set and raises
    `ActivationNotAcceptableError` — exactly one caller ever succeeds,
    mirroring `accept_campaign_invitation`'s identical concurrency shape."""
    validate_password_policy(raw_password)
    token_hash = hash_opaque_secret(raw_activation_token)

    token_row = (
        connection.execute(
            text("""
                SELECT user_activation_token_id, user_id, login_name, consumed_at,
                       (expires_at <= now()) AS expired
                FROM security.user_activation_tokens
                WHERE token_hash = :hash
                FOR UPDATE
            """),
            {"hash": token_hash},
        )
        .mappings()
        .one_or_none()
    )
    if token_row is None or token_row["consumed_at"] is not None or token_row["expired"]:
        raise ActivationNotAcceptableError(
            f"activation token hash {token_hash} is not consumable (row={token_row is not None})"
        )

    user_id = token_row["user_id"]
    login_name = token_row["login_name"]

    already_claimed = connection.execute(
        text("""
            SELECT 1 FROM security.external_identities
            WHERE issuer = :issuer AND subject = :subject AND revoked_at IS NULL
        """),
        {"issuer": LOCAL_AUTH_ISSUER, "subject": login_name},
    ).scalar()
    if already_claimed is not None:
        raise LoginNameAlreadyTakenError()

    connection.execute(
        text("""
            UPDATE security.user_activation_tokens
            SET consumed_at = now()
            WHERE user_activation_token_id = :token
        """),
        {"token": token_row["user_activation_token_id"]},
    )
    connection.execute(
        text("""
            INSERT INTO security.external_identities
                (user_id, issuer, subject, linked_at, last_authenticated_at)
            VALUES (:user_id, :issuer, :subject, now(), now())
        """),
        {"user_id": user_id, "issuer": LOCAL_AUTH_ISSUER, "subject": login_name},
    )
    password_hash = hash_password(raw_password)
    connection.execute(
        text("""
            INSERT INTO security.local_credentials (user_id, password_hash)
            VALUES (:user_id, :hash)
        """),
        {"user_id": user_id, "hash": password_hash},
    )

    return ActivateLocalAccountResult(user_id=user_id, login_name=login_name)


def activate_local_account(
    engine: Engine, *, raw_activation_token: str, raw_password: str
) -> ActivateLocalAccountResult:
    """Public convenience API: opens and commits its own transaction. See
    `_activate_local_account_impl` for the composable form a caller with
    its own transaction uses instead."""
    with engine.begin() as connection:
        return _activate_local_account_impl(
            connection, raw_activation_token=raw_activation_token, raw_password=raw_password
        )


def authenticate_local_user(
    connection: Connection, *, login_name: str, raw_password: str
) -> uuid.UUID | None:
    """Constant-work credential check (docs/PLAN.md §23.1/§23.4): returns
    the authenticated `user_id`, or `None` for *any* failure reason
    (unknown login name, inactive account, no password set, wrong
    password) without distinguishing which. Every path — including
    "no such login name at all" — calls `dnd_ai.domain.passwords.
    verify_password` against a real Argon2id hash before returning, so the
    dominant cost (Argon2id's own deliberate expense) is paid identically
    whether or not the account exists. See this module's docstring for
    what this does and does not equalize.

    Does not open its own transaction — the caller (`dnd_ai.api.
    local_auth.login_endpoint`, via `get_connection`) already has one; a
    failed login still commits its own rate-limit bookkeeping same as a
    successful one, so a failed-attempt counter (owned by the API layer's
    `RateLimiter`, not this function) is never rolled back by the
    surrounding request transaction."""
    normalized_login_name = normalize_login_name(login_name)
    row = (
        connection.execute(
            text("""
            SELECT lc.user_id, lc.password_hash
            FROM security.external_identities ei
            JOIN security.users u ON u.user_id = ei.user_id
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = u.lifecycle_status_id
            LEFT JOIN security.local_credentials lc ON lc.user_id = ei.user_id
            WHERE ei.issuer = :issuer AND ei.subject = :subject
              AND ei.revoked_at IS NULL AND ls.code = 'active'
        """),
            {"issuer": LOCAL_AUTH_ISSUER, "subject": normalized_login_name},
        )
        .mappings()
        .one_or_none()
    )

    encoded_hash = (
        row["password_hash"] if row is not None and row["password_hash"] else DUMMY_PASSWORD_HASH
    )
    verified = verify_password(raw_password, encoded_hash)

    if row is None or row["password_hash"] is None or not verified:
        return None

    user_id = row["user_id"]
    assert isinstance(user_id, uuid.UUID)

    if password_needs_rehash(encoded_hash):
        connection.execute(
            text("""
                UPDATE security.local_credentials
                SET password_hash = :hash, password_updated_at = now(), updated_at = now()
                WHERE user_id = :user_id
            """),
            {"hash": hash_password(raw_password), "user_id": user_id},
        )
    connection.execute(
        text("""
            UPDATE security.external_identities
            SET last_authenticated_at = now()
            WHERE issuer = :issuer AND subject = :subject
        """),
        {"issuer": LOCAL_AUTH_ISSUER, "subject": normalized_login_name},
    )
    connection.execute(
        text("UPDATE security.users SET last_login_at = now() WHERE user_id = :user_id"),
        {"user_id": user_id},
    )
    return user_id


@dataclass(frozen=True)
class CreatedBrowserSession:
    browser_session_id: uuid.UUID
    raw_session_token: str
    csrf_token: str
    idle_expires_at: datetime
    absolute_expires_at: datetime


def create_browser_session(
    connection: Connection,
    *,
    user_id: uuid.UUID,
    created_ip: str | None = None,
    user_agent: str | None = None,
) -> CreatedBrowserSession:
    """Creates a new opaque browser session for `user_id` (docs/PLAN.md
    §23.4). Does not itself revoke any prior session for the same user —
    a user may hold multiple concurrent browser sessions (different
    browsers/devices), matching the Foundry-pairing model's own "each
    device pairs independently" design; `login_endpoint`
    (`dnd_ai.api.local_auth`) is what decides whether a fresh login
    replaces or adds to the caller's existing sessions, by calling this
    after any pre-authentication session rotation it performs."""
    raw_session_token = generate_opaque_secret()
    csrf_token = generate_opaque_secret()
    now = datetime.now(UTC)
    idle_expires_at = now + _BROWSER_SESSION_IDLE_TIMEOUT
    absolute_expires_at = now + _BROWSER_SESSION_ABSOLUTE_TIMEOUT
    browser_session_id = connection.execute(
        text("""
            INSERT INTO security.browser_sessions
                (user_id, session_token_hash, csrf_token, idle_expires_at, absolute_expires_at,
                 created_ip, last_used_ip, user_agent)
            VALUES (:user_id, :hash, :csrf, :idle, :absolute, :ip, :ip, :agent)
            RETURNING browser_session_id
        """),
        {
            "user_id": user_id,
            "hash": hash_opaque_secret(raw_session_token),
            "csrf": csrf_token,
            "idle": idle_expires_at,
            "absolute": absolute_expires_at,
            "ip": created_ip,
            "agent": user_agent,
        },
    ).scalar()
    assert isinstance(browser_session_id, uuid.UUID)
    return CreatedBrowserSession(
        browser_session_id=browser_session_id,
        raw_session_token=raw_session_token,
        csrf_token=csrf_token,
        idle_expires_at=idle_expires_at,
        absolute_expires_at=absolute_expires_at,
    )


def resolve_local_session_principal(
    connection: Connection, *, raw_session_token: str
) -> AuthenticatedPrincipal | None:
    """Resolves a raw `__Host-dnd_ai_session` cookie value to an
    `AuthenticatedPrincipal`, or `None` for any invalid/expired/revoked
    session or inactive user — uniformly, mirroring `resolve_foundry_
    system_principal`'s identical non-disclosing contract. Revalidates on
    every call (docs/PLAN.md §23.4: "every request re-resolves... so
    revocation takes effect without waiting for the browser session to
    expire") rather than trusting a cached decision from login time.

    On success, extends the sliding idle-expiry window (never past
    `absolute_expires_at`) and bumps `last_used_at`/`last_used_ip` in the
    same statement — this is a write coupled to the read, committed as
    part of whatever transaction the caller (`dnd_ai.api.auth.
    get_authenticated_user_id`, via the request's own `get_connection`)
    is already running, exactly like `authenticate_local_user`'s own
    `last_login_at` bump above."""
    token_hash = hash_opaque_secret(raw_session_token)
    row = (
        connection.execute(
            text("""
                SELECT bs.browser_session_id, bs.user_id, bs.idle_expires_at,
                       bs.absolute_expires_at, bs.revoked_at
                FROM security.browser_sessions bs
                JOIN security.users u ON u.user_id = bs.user_id
                JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = u.lifecycle_status_id
                WHERE bs.session_token_hash = :hash AND ls.code = 'active'
            """),
            {"hash": token_hash},
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    now = datetime.now(UTC)
    if row["revoked_at"] is not None:
        return None
    if row["idle_expires_at"] <= now or row["absolute_expires_at"] <= now:
        return None

    new_idle_expires_at = min(now + _BROWSER_SESSION_IDLE_TIMEOUT, row["absolute_expires_at"])
    connection.execute(
        text("""
            UPDATE security.browser_sessions
            SET last_used_at = now(), idle_expires_at = :idle
            WHERE browser_session_id = :session
        """),
        {"idle": new_idle_expires_at, "session": row["browser_session_id"]},
    )
    return AuthenticatedPrincipal(
        user_id=row["user_id"],
        auth_method=LOCAL_SESSION_AUTH_METHOD,
        local_session_id=row["browser_session_id"],
    )


def resolve_browser_session_csrf_token(
    connection: Connection, *, browser_session_id: uuid.UUID
) -> str | None:
    """The stored `csrf_token` for one session, for `dnd_ai.api.auth`'s
    CSRF double-submit check on a cookie-authenticated state-changing
    request — `None` only if the session row has since been deleted out
    from under an in-flight request (it is never physically deleted by any
    command in this module), which the caller treats as a hard CSRF
    failure like any other mismatch."""
    value = connection.execute(
        text(
            "SELECT csrf_token FROM security.browser_sessions WHERE browser_session_id = :session"
        ),
        {"session": browser_session_id},
    ).scalar()
    return str(value) if value is not None else None


def revoke_browser_session_by_token(connection: Connection, *, raw_session_token: str) -> None:
    """Logout (docs/PLAN.md §23.4): revokes the session `raw_session_token`
    names, if any — silently a no-op for an unknown/already-revoked token,
    since "log out a session that no longer exists" is already the
    caller's desired end state, not an error."""
    connection.execute(
        text("""
            UPDATE security.browser_sessions
            SET revoked_at = now()
            WHERE session_token_hash = :hash AND revoked_at IS NULL
        """),
        {"hash": hash_opaque_secret(raw_session_token)},
    )


class ForeignBrowserSessionError(DomainAuthorizationError):
    """Raised by `revoke_browser_session` when `browser_session_id` does
    not belong to the caller's own `user_id` — a fixed, non-disclosing 404
    (never confirming whether the session belongs to someone else or
    doesn't exist at all)."""


def revoke_browser_session(
    connection: Connection, *, user_id: uuid.UUID, browser_session_id: uuid.UUID
) -> None:
    """A user revoking one of their own listed sessions (docs/PLAN.md
    §23.5's "users can revoke their own devices," applied to browser
    sessions). `ForeignBrowserSessionError` if `browser_session_id` does
    not belong to `user_id` — checked and enforced in the same statement
    via the `WHERE user_id = :user_id` clause, not a separate ownership
    pre-check, so there is no window between checking and revoking."""
    result = connection.execute(
        text("""
            UPDATE security.browser_sessions
            SET revoked_at = now()
            WHERE browser_session_id = :session AND user_id = :user_id AND revoked_at IS NULL
        """),
        {"session": browser_session_id, "user_id": user_id},
    )
    if result.rowcount == 0:
        exists_for_other_user = connection.execute(
            text("SELECT 1 FROM security.browser_sessions WHERE browser_session_id = :session"),
            {"session": browser_session_id},
        ).scalar()
        if exists_for_other_user is None:
            return  # Already revoked, or never existed — both a no-op.
        raise ForeignBrowserSessionError(
            f"browser session {browser_session_id} does not belong to user {user_id}"
        )


def revoke_all_browser_sessions(connection: Connection, *, user_id: uuid.UUID) -> None:
    """Revokes every active browser session for `user_id` — used by
    `reset_password_with_token` when the reset token's own
    `revoke_sessions` flag is set (docs/PLAN.md §23.1's "full sign-out"
    reset policy) and by administrator-initiated account deactivation."""
    connection.execute(
        text("""
            UPDATE security.browser_sessions
            SET revoked_at = now()
            WHERE user_id = :user_id AND revoked_at IS NULL
        """),
        {"user_id": user_id},
    )


@dataclass(frozen=True)
class BrowserSessionSummary:
    browser_session_id: uuid.UUID
    created_at: datetime
    last_used_at: datetime
    idle_expires_at: datetime
    absolute_expires_at: datetime
    created_ip: str | None
    last_used_ip: str | None
    user_agent: str | None
    is_current: bool


def list_browser_sessions(
    connection: Connection,
    *,
    user_id: uuid.UUID,
    current_browser_session_id: uuid.UUID | None = None,
) -> list[BrowserSessionSummary]:
    """Every active (unrevoked, unexpired) browser session for `user_id`,
    most-recently-used first — never a password hash or any other
    credential-bearing field, matching docs/PLAN.md §23.1's "password
    hashes/credential state must never appear in general user-profile
    responses.\""""
    rows = connection.execute(
        text("""
            SELECT browser_session_id, created_at, last_used_at, idle_expires_at,
                   absolute_expires_at, created_ip, last_used_ip, user_agent
            FROM security.browser_sessions
            WHERE user_id = :user_id AND revoked_at IS NULL
              AND idle_expires_at > now() AND absolute_expires_at > now()
            ORDER BY last_used_at DESC
        """),
        {"user_id": user_id},
    ).mappings()
    return [
        BrowserSessionSummary(
            browser_session_id=row["browser_session_id"],
            created_at=row["created_at"],
            last_used_at=row["last_used_at"],
            idle_expires_at=row["idle_expires_at"],
            absolute_expires_at=row["absolute_expires_at"],
            created_ip=row["created_ip"],
            last_used_ip=row["last_used_ip"],
            user_agent=row["user_agent"],
            is_current=row["browser_session_id"] == current_browser_session_id,
        )
        for row in rows
    ]


def change_password(
    connection: Connection, *, user_id: uuid.UUID, current_raw_password: str, new_raw_password: str
) -> None:
    """Self-service password change (docs/PLAN.md §23.1) — requires the
    caller's *current* password, verified with the same `dnd_ai.domain.
    passwords.verify_password` check `authenticate_local_user` uses
    (though not constant-work against a nonexistent account, since the
    caller is already an authenticated session naming a real `user_id`;
    there is no username-enumeration surface to protect against here).
    Does not itself revoke other sessions — an ordinary password change is
    not documented as a forced sign-out event the way an administrator-
    initiated reset is (docs/PLAN.md §23.1 draws that distinction
    explicitly)."""
    row = (
        connection.execute(
            text("SELECT password_hash FROM security.local_credentials WHERE user_id = :user_id"),
            {"user_id": user_id},
        )
        .mappings()
        .one_or_none()
    )
    if row is None or not verify_password(current_raw_password, row["password_hash"]):
        raise AuthenticationError("current password did not verify")
    validate_password_policy(new_raw_password)
    connection.execute(
        text("""
            UPDATE security.local_credentials
            SET password_hash = :hash, password_updated_at = now(), updated_at = now()
            WHERE user_id = :user_id
        """),
        {"hash": hash_password(new_raw_password), "user_id": user_id},
    )


@dataclass(frozen=True)
class IssuedPasswordResetToken:
    password_reset_token_id: uuid.UUID
    user_id: uuid.UUID
    raw_token: str
    expires_at: datetime


def _issue_password_reset_token_impl(
    connection: Connection,
    *,
    requested_by_user_id: uuid.UUID,
    target_user_id: uuid.UUID,
    revoke_sessions: bool = True,
) -> IssuedPasswordResetToken:
    """The composable form of `issue_password_reset_token` — see
    `_create_local_account_impl`'s docstring for the pattern. An
    administrator issues a password-reset token for `target_user_id`
    (docs/PLAN.md §23.1). `requested_by_user_id` must be a platform
    administrator — checked here, inside the caller's own transaction,
    same as `_create_local_account_impl`."""
    if not is_platform_administrator(connection, user_id=requested_by_user_id):
        raise NotPlatformAdministratorError(
            f"user {requested_by_user_id} is not a platform administrator"
        )
    raw_token = generate_opaque_secret()
    expires_at = datetime.now(UTC) + _PASSWORD_RESET_TOKEN_TTL
    password_reset_token_id = connection.execute(
        text("""
            INSERT INTO security.password_reset_tokens
                (user_id, token_hash, requested_by_user_id, revoke_sessions, expires_at)
            VALUES (:user_id, :hash, :requested_by, :revoke_sessions, :expires_at)
            RETURNING password_reset_token_id
        """),
        {
            "user_id": target_user_id,
            "hash": hash_opaque_secret(raw_token),
            "requested_by": requested_by_user_id,
            "revoke_sessions": revoke_sessions,
            "expires_at": expires_at,
        },
    ).scalar()
    assert isinstance(password_reset_token_id, uuid.UUID)
    return IssuedPasswordResetToken(
        password_reset_token_id=password_reset_token_id,
        user_id=target_user_id,
        raw_token=raw_token,
        expires_at=expires_at,
    )


def issue_password_reset_token(
    engine: Engine,
    *,
    requested_by_user_id: uuid.UUID,
    target_user_id: uuid.UUID,
    revoke_sessions: bool = True,
) -> IssuedPasswordResetToken:
    """Public convenience API: opens and commits its own transaction. See
    `_issue_password_reset_token_impl` for the composable form a caller
    with its own transaction uses instead."""
    with engine.begin() as connection:
        return _issue_password_reset_token_impl(
            connection,
            requested_by_user_id=requested_by_user_id,
            target_user_id=target_user_id,
            revoke_sessions=revoke_sessions,
        )


class PasswordResetNotAcceptableError(DomainAuthorizationError):
    """Mirrors `ActivationNotAcceptableError` exactly, for
    `reset_password_with_token`: nonexistent, already-consumed, and
    expired tokens are all indistinguishable to the caller."""


@dataclass(frozen=True)
class ResetPasswordResult:
    user_id: uuid.UUID
    sessions_revoked: bool


def _reset_password_with_token_impl(
    connection: Connection, *, raw_reset_token: str, new_raw_password: str
) -> ResetPasswordResult:
    """The composable form of `reset_password_with_token` — see
    `_create_local_account_impl`'s docstring for the pattern. Consumes
    `raw_reset_token`, setting a new password for the user it names, and —
    when the token's own `revoke_sessions` flag is set — revoking every one
    of that user's active browser sessions *and* Foundry connections
    (`dnd_ai.commands.foundry_pairing.revoke_all_foundry_connections`,
    Phase 11R workstream D) in the same transaction (docs/PLAN.md §23.1's
    "full sign-out" policy)."""
    validate_password_policy(new_raw_password)
    token_hash = hash_opaque_secret(raw_reset_token)
    token_row = (
        connection.execute(
            text("""
                SELECT password_reset_token_id, user_id, revoke_sessions, consumed_at,
                       (expires_at <= now()) AS expired
                FROM security.password_reset_tokens
                WHERE token_hash = :hash
                FOR UPDATE
            """),
            {"hash": token_hash},
        )
        .mappings()
        .one_or_none()
    )
    if token_row is None or token_row["consumed_at"] is not None or token_row["expired"]:
        raise PasswordResetNotAcceptableError(
            f"password reset token hash {token_hash} is not consumable "
            f"(row={token_row is not None})"
        )
    connection.execute(
        text("""
            UPDATE security.password_reset_tokens
            SET consumed_at = now()
            WHERE password_reset_token_id = :token
        """),
        {"token": token_row["password_reset_token_id"]},
    )
    user_id = token_row["user_id"]
    connection.execute(
        text("""
            UPDATE security.local_credentials
            SET password_hash = :hash, password_updated_at = now(), updated_at = now()
            WHERE user_id = :user_id
        """),
        {"hash": hash_password(new_raw_password), "user_id": user_id},
    )
    if token_row["revoke_sessions"]:
        revoke_all_browser_sessions(connection, user_id=user_id)
        revoke_all_foundry_connections(connection, user_id=user_id)
    return ResetPasswordResult(user_id=user_id, sessions_revoked=token_row["revoke_sessions"])


def reset_password_with_token(
    engine: Engine, *, raw_reset_token: str, new_raw_password: str
) -> ResetPasswordResult:
    """Public convenience API: opens and commits its own transaction. See
    `_reset_password_with_token_impl` for the composable form a caller
    with its own transaction uses instead."""
    with engine.begin() as connection:
        return _reset_password_with_token_impl(
            connection, raw_reset_token=raw_reset_token, new_raw_password=new_raw_password
        )


__all__ = [
    "ActivateLocalAccountResult",
    "ActivationNotAcceptableError",
    "AlreadyBootstrappedError",
    "BrowserSessionSummary",
    "CreatedBrowserSession",
    "ForeignBrowserSessionError",
    "IssuedActivationToken",
    "IssuedPasswordResetToken",
    "LoginNameAlreadyTakenError",
    "LoginNameFormatError",
    "NotPlatformAdministratorError",
    "PasswordResetNotAcceptableError",
    "ResetPasswordResult",
    "_activate_local_account_impl",
    "_create_local_account_impl",
    "_issue_password_reset_token_impl",
    "_reset_password_with_token_impl",
    "activate_local_account",
    "authenticate_local_user",
    "bootstrap_initial_admin",
    "change_password",
    "create_browser_session",
    "create_local_account",
    "issue_password_reset_token",
    "list_browser_sessions",
    "normalize_login_name",
    "reset_password_with_token",
    "resolve_browser_session_csrf_token",
    "resolve_local_session_principal",
    "revoke_all_browser_sessions",
    "revoke_browser_session",
    "revoke_browser_session_by_token",
]
