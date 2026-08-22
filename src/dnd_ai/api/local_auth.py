"""Local account and browser-session HTTP endpoints (docs/PLAN.md §23.1,
§23.4 — Phase 11R workstream A/B).

Every route here is either public (rate-limited, token- or credential-
authenticated: login, activation, password-reset consumption) or requires
an already-authenticated human (`require_human_user_id` — accepts both
`OIDC_AUTH_METHOD` and `LOCAL_SESSION_AUTH_METHOD`, see that dependency's
own docstring). CSRF/Origin enforcement for cookie-authenticated state-changing
requests happens centrally inside `dnd_ai.api.auth.get_authenticated_user_id`
itself — nothing route-specific is needed here beyond depending on that
dependency (directly or via `require_human_user_id`), matching this
router's login/logout/session-cookie plumbing to the same "centralize,
don't rely on every route remembering" shape `require_campaign_capability`'s
`allow_foundry_access` gate already established.

Every write here calls a command's `_..._impl(connection, ...)` composable
form directly on the request's own `get_connection`-provided transaction —
never the `Engine`-based public wrapper, which would open a second,
independent transaction per request (docs/architecture/SYSTEM_ARCHITECTURE.md
§7's "one transaction per request"). See `dnd_ai.commands.local_auth.
_create_local_account_impl`'s docstring for why both forms exist.

Rate limiting (docs/PLAN.md §23.4/§23.5's "account/IP-aware rate-limit
abstractions for login/activation/reset/pairing/token-exchange"):
`get_login_rate_limiter`/`get_token_consumption_rate_limiter` mirror
`dnd_ai.api.auth.get_jwks_client`'s singleton-plus-override shape exactly
— a process-wide `dnd_ai.domain.rate_limit.RateLimiter`, resolved through
a FastAPI dependency so tests can substitute a fresh instance via
`app.dependency_overrides` instead of sharing rate-limit state across
unrelated test cases in the same process.

Known deployment-topology deviation: `_client_ip` reads `request.client.host`
only, never `X-Forwarded-For` — trusting that header requires knowing which
hops are the deployment's own reverse proxy, a topology decision this
module does not own. Behind a reverse proxy that terminates TLS/forwards
client IPs, every request's `request.client.host` is the proxy's own
address, so IP-scoped rate limiting degrades to a single shared bucket
across every real client — login-name scoping in `login_endpoint`'s own
key still bounds the blast radius per account. Documented here, and in
this workstream's completion report, as a deliberate scope boundary for a
future reverse-proxy-aware deployment workstream to close, not an
oversight.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import Connection

from dnd_ai.commands.local_auth import (
    _activate_local_account_impl,
    _create_local_account_impl,
    _issue_password_reset_token_impl,
    _reset_password_with_token_impl,
    authenticate_local_user,
    change_password,
    create_browser_session,
    list_browser_sessions,
    resolve_browser_session_csrf_token,
    revoke_browser_session,
    revoke_browser_session_by_token,
)
from dnd_ai.domain.access import AuthenticatedPrincipal
from dnd_ai.domain.rate_limit import RateLimiter

from .auth import get_authenticated_user_id, require_human_user_id
from .cookies import session_cookie_name, session_cookie_set_kwargs
from .deps import get_connection
from .errors import RateLimitedError, UnauthorizedError

router = APIRouter(tags=["local_auth"])

_LOGIN_RATE_LIMIT_MAX_ATTEMPTS = 10
_LOGIN_RATE_LIMIT_WINDOW = timedelta(minutes=15)
_TOKEN_CONSUMPTION_RATE_LIMIT_MAX_ATTEMPTS = 20
_TOKEN_CONSUMPTION_RATE_LIMIT_WINDOW = timedelta(minutes=15)

_login_rate_limiter: RateLimiter | None = None
_token_consumption_rate_limiter: RateLimiter | None = None


def get_login_rate_limiter() -> RateLimiter:
    global _login_rate_limiter
    if _login_rate_limiter is None:
        _login_rate_limiter = RateLimiter(
            max_attempts=_LOGIN_RATE_LIMIT_MAX_ATTEMPTS, window=_LOGIN_RATE_LIMIT_WINDOW
        )
    return _login_rate_limiter


def get_token_consumption_rate_limiter() -> RateLimiter:
    global _token_consumption_rate_limiter
    if _token_consumption_rate_limiter is None:
        _token_consumption_rate_limiter = RateLimiter(
            max_attempts=_TOKEN_CONSUMPTION_RATE_LIMIT_MAX_ATTEMPTS,
            window=_TOKEN_CONSUMPTION_RATE_LIMIT_WINDOW,
        )
    return _token_consumption_rate_limiter


def _client_ip(request: Request) -> str:
    """`request.client.host`, or a fixed placeholder if the ASGI server
    didn't supply one (e.g. some test transports) — never `None` passed to
    a rate-limiter key. See this module's own docstring for the reverse-
    proxy deviation this leaves open."""
    return request.client.host if request.client is not None else "unknown"


# ---------------------------------------------------------------------------
# Login / logout / session bootstrap
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    login_name: str
    password: str = Field(repr=False)


class LoginResponse(BaseModel):
    user_id: uuid.UUID
    csrf_token: str


@router.post("/auth/login", response_model=LoginResponse, status_code=200)
def login_endpoint(
    body: LoginRequest,
    request: Request,
    response: Response,
    connection: Annotated[Connection, Depends(get_connection)],
    rate_limiter: Annotated[RateLimiter, Depends(get_login_rate_limiter)],
) -> LoginResponse:
    """docs/PLAN.md §23.4 steps 1-4: rate limit, constant-work credential
    check, session creation with a rotated identifier, and the `Set-Cookie`
    response. Every failure — rate-limited or a genuine credential mismatch
    — raises the identical `UnauthorizedError`/`RateLimitedError` shape
    (distinct status codes, 429 vs. 401, but neither discloses which of
    "unknown login name," "inactive account," or "wrong password" applies,
    matching `dnd_ai.commands.local_auth.authenticate_local_user`'s own
    non-disclosing contract one layer down)."""
    rate_limit_key = f"{_client_ip(request)}:{body.login_name.strip().lower()}"
    if not rate_limiter.allow(rate_limit_key, now=datetime.now(UTC)):
        raise RateLimitedError()

    user_id = authenticate_local_user(
        connection, login_name=body.login_name, raw_password=body.password
    )
    if user_id is None:
        raise UnauthorizedError()
    rate_limiter.reset(rate_limit_key)

    # "Successful login rotates the session" (docs/PLAN.md §23.4): a fresh
    # session is always created here, never reused — there is no pre-
    # authentication session identifier in this design to rotate away from
    # (no anonymous session exists before login), so a new, distinct
    # session/CSRF-secret pair on every successful login already satisfies
    # the rotation requirement.
    session = create_browser_session(
        connection,
        user_id=user_id,
        created_ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    response.set_cookie(
        key=session_cookie_name(),
        value=session.raw_session_token,
        **session_cookie_set_kwargs(),  # type: ignore[arg-type]
    )
    return LoginResponse(user_id=user_id, csrf_token=session.csrf_token)


@router.post("/auth/logout", status_code=204)
def logout_endpoint(
    _principal: Annotated[uuid.UUID, Depends(require_human_user_id)],
    request: Request,
    response: Response,
    connection: Annotated[Connection, Depends(get_connection)],
) -> Response:
    """docs/PLAN.md §23.4: revokes the session server-side and clears the
    cookie. `_principal` is only depended on to force CSRF/Origin
    enforcement through `get_authenticated_user_id` (an already-expired or
    invalid cookie fails there with 401 before this body ever runs — logging
    out an already-dead session needs no further server-side action, so
    that is an acceptable outcome, not a gap); the actual revocation reads
    the raw cookie value directly rather than the resolved principal, since
    `AuthenticatedPrincipal` deliberately carries no raw secret."""
    raw_session_token = request.cookies.get(session_cookie_name())
    if raw_session_token is not None:
        revoke_browser_session_by_token(connection, raw_session_token=raw_session_token)
    response.delete_cookie(key=session_cookie_name(), path="/")
    return Response(status_code=204)


class SessionBootstrapResponse(BaseModel):
    user_id: uuid.UUID
    csrf_token: str
    browser_session_id: uuid.UUID | None


@router.get("/auth/session", response_model=SessionBootstrapResponse, status_code=200)
def session_bootstrap_endpoint(
    principal: Annotated[AuthenticatedPrincipal, Depends(get_authenticated_user_id)],
    connection: Annotated[Connection, Depends(get_connection)],
) -> SessionBootstrapResponse:
    """The minimal session-bootstrap contract this workstream owns: current
    user id, a fresh CSRF token read, and the authenticating session id.
    Never a password hash, reset/activation token, or durable API
    credential (docs/PLAN.md §23.4). Campaign/capability/feature-manifest
    listing — the fuller bootstrap payload §23.4/§23.7 describe — is
    deliberately deferred to whichever Phase 13 query surface actually
    needs it; building that listing here would be new query-layer work
    beyond this workstream's authentication/session scope, and the portal
    itself is explicitly out of scope for this change. Reachable by any
    human auth method (`require_human_user_id`'s accepted set), not only a
    browser session — an OIDC caller hitting this (a non-browser bearer-
    token client checking who it's authenticated as) gets an empty
    `csrf_token` and a `null` `browser_session_id` instead of an error."""
    csrf_token = (
        resolve_browser_session_csrf_token(
            connection, browser_session_id=principal.local_session_id
        )
        if principal.local_session_id is not None
        else None
    )
    return SessionBootstrapResponse(
        user_id=principal.user_id,
        csrf_token=csrf_token or "",
        browser_session_id=principal.local_session_id,
    )


# ---------------------------------------------------------------------------
# Self-service: change password, list/revoke own sessions
# ---------------------------------------------------------------------------


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(repr=False)
    new_password: str = Field(repr=False)


@router.post("/auth/change-password", status_code=204)
def change_password_endpoint(
    body: ChangePasswordRequest,
    user_id: Annotated[uuid.UUID, Depends(require_human_user_id)],
    connection: Annotated[Connection, Depends(get_connection)],
) -> Response:
    change_password(
        connection,
        user_id=user_id,
        current_raw_password=body.current_password,
        new_raw_password=body.new_password,
    )
    return Response(status_code=204)


class BrowserSessionSummaryResponse(BaseModel):
    browser_session_id: uuid.UUID
    created_at: str
    last_used_at: str
    idle_expires_at: str
    absolute_expires_at: str
    created_ip: str | None
    last_used_ip: str | None
    user_agent: str | None
    is_current: bool


@router.get("/auth/sessions", response_model=list[BrowserSessionSummaryResponse], status_code=200)
def list_sessions_endpoint(
    principal: Annotated[AuthenticatedPrincipal, Depends(get_authenticated_user_id)],
    user_id: Annotated[uuid.UUID, Depends(require_human_user_id)],
    connection: Annotated[Connection, Depends(get_connection)],
) -> list[BrowserSessionSummaryResponse]:
    summaries = list_browser_sessions(
        connection, user_id=user_id, current_browser_session_id=principal.local_session_id
    )
    return [
        BrowserSessionSummaryResponse(
            browser_session_id=summary.browser_session_id,
            created_at=summary.created_at.isoformat(),
            last_used_at=summary.last_used_at.isoformat(),
            idle_expires_at=summary.idle_expires_at.isoformat(),
            absolute_expires_at=summary.absolute_expires_at.isoformat(),
            created_ip=summary.created_ip,
            last_used_ip=summary.last_used_ip,
            user_agent=summary.user_agent,
            is_current=summary.is_current,
        )
        for summary in summaries
    ]


@router.delete("/auth/sessions/{browser_session_id}", status_code=204)
def revoke_session_endpoint(
    browser_session_id: uuid.UUID,
    user_id: Annotated[uuid.UUID, Depends(require_human_user_id)],
    connection: Annotated[Connection, Depends(get_connection)],
) -> Response:
    revoke_browser_session(connection, user_id=user_id, browser_session_id=browser_session_id)
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Administrator account/reset issuance (security.users.is_platform_administrator)
# ---------------------------------------------------------------------------


class CreateAccountRequest(BaseModel):
    login_name: str
    display_name: str
    email: str | None = None


class CreateAccountResponse(BaseModel):
    user_id: uuid.UUID
    login_name: str
    raw_activation_token: str
    expires_at: str


@router.post("/admin/accounts", response_model=CreateAccountResponse, status_code=201)
def create_account_endpoint(
    body: CreateAccountRequest,
    admin_user_id: Annotated[uuid.UUID, Depends(require_human_user_id)],
    connection: Annotated[Connection, Depends(get_connection)],
) -> CreateAccountResponse:
    """`_create_local_account_impl` itself checks `admin_user_id` is a
    platform administrator (`NotPlatformAdministratorError`, a
    `DomainAuthorizationError` — fixed non-disclosing 404) inside the same
    transaction — see that command's own docstring for why the check lives
    there rather than a duplicate API-layer dependency."""
    result = _create_local_account_impl(
        connection,
        created_by_user_id=admin_user_id,
        login_name=body.login_name,
        display_name=body.display_name,
        email=body.email,
    )
    return CreateAccountResponse(
        user_id=result.user_id,
        login_name=result.login_name,
        raw_activation_token=result.raw_token,
        expires_at=result.expires_at.isoformat(),
    )


class IssuePasswordResetRequest(BaseModel):
    revoke_sessions: bool = True


class IssuePasswordResetResponse(BaseModel):
    user_id: uuid.UUID
    raw_reset_token: str
    expires_at: str


@router.post(
    "/admin/accounts/{target_user_id}/password-reset",
    response_model=IssuePasswordResetResponse,
    status_code=201,
)
def issue_password_reset_endpoint(
    target_user_id: uuid.UUID,
    body: IssuePasswordResetRequest,
    admin_user_id: Annotated[uuid.UUID, Depends(require_human_user_id)],
    connection: Annotated[Connection, Depends(get_connection)],
) -> IssuePasswordResetResponse:
    result = _issue_password_reset_token_impl(
        connection,
        requested_by_user_id=admin_user_id,
        target_user_id=target_user_id,
        revoke_sessions=body.revoke_sessions,
    )
    return IssuePasswordResetResponse(
        user_id=result.user_id,
        raw_reset_token=result.raw_token,
        expires_at=result.expires_at.isoformat(),
    )


# ---------------------------------------------------------------------------
# Public, token-authenticated: activation and password-reset consumption
# ---------------------------------------------------------------------------


class ActivateAccountRequest(BaseModel):
    token: str = Field(repr=False)
    password: str = Field(repr=False)


class ActivateAccountResponse(BaseModel):
    user_id: uuid.UUID
    login_name: str


@router.post("/auth/activate", response_model=ActivateAccountResponse, status_code=200)
def activate_account_endpoint(
    body: ActivateAccountRequest,
    request: Request,
    connection: Annotated[Connection, Depends(get_connection)],
    rate_limiter: Annotated[RateLimiter, Depends(get_token_consumption_rate_limiter)],
) -> ActivateAccountResponse:
    if not rate_limiter.allow(_client_ip(request), now=datetime.now(UTC)):
        raise RateLimitedError()
    result = _activate_local_account_impl(
        connection, raw_activation_token=body.token, raw_password=body.password
    )
    return ActivateAccountResponse(user_id=result.user_id, login_name=result.login_name)


class ResetPasswordRequest(BaseModel):
    token: str = Field(repr=False)
    new_password: str = Field(repr=False)


class ResetPasswordResponse(BaseModel):
    user_id: uuid.UUID
    sessions_revoked: bool


@router.post("/auth/password-reset", response_model=ResetPasswordResponse, status_code=200)
def reset_password_endpoint(
    body: ResetPasswordRequest,
    request: Request,
    connection: Annotated[Connection, Depends(get_connection)],
    rate_limiter: Annotated[RateLimiter, Depends(get_token_consumption_rate_limiter)],
) -> ResetPasswordResponse:
    if not rate_limiter.allow(_client_ip(request), now=datetime.now(UTC)):
        raise RateLimitedError()
    result = _reset_password_with_token_impl(
        connection, raw_reset_token=body.token, new_raw_password=body.new_password
    )
    return ResetPasswordResponse(user_id=result.user_id, sessions_revoked=result.sessions_revoked)


__all__ = ["router", "get_login_rate_limiter", "get_token_consumption_rate_limiter"]
