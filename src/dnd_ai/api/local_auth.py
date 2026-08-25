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
from sqlalchemy import Connection, Engine

from dnd_ai.commands.local_auth import (
    _activate_local_account_impl,
    _admin_revoke_all_browser_sessions_impl,
    _create_local_account_impl,
    _disable_local_account_impl,
    _issue_password_reset_token_impl,
    _reactivate_local_account_impl,
    _reset_password_with_token_impl,
    authenticate_local_user,
    change_password,
    create_browser_session,
    list_browser_sessions,
    normalize_login_name,
    resolve_browser_session_csrf_token,
    revoke_browser_session,
    revoke_browser_session_by_token,
)
from dnd_ai.domain.access import AuthenticatedPrincipal
from dnd_ai.domain.rate_limit import RateLimiter
from dnd_ai.queries.bootstrap import get_session_bootstrap

from .audit import record_change_log
from .auth import get_authenticated_user_id, require_human_user_id
from .cookies import session_cookie_name, session_cookie_set_kwargs
from .correlation import get_request_correlation_id
from .deps import get_connection, get_engine
from .errors import RateLimitedError, UnauthorizedError

router = APIRouter(tags=["local_auth"])

_LOGIN_RATE_LIMIT_MAX_ATTEMPTS = 10
_LOGIN_RATE_LIMIT_WINDOW = timedelta(minutes=15)
_TOKEN_CONSUMPTION_RATE_LIMIT_MAX_ATTEMPTS = 20
_TOKEN_CONSUMPTION_RATE_LIMIT_WINDOW = timedelta(minutes=15)

_login_rate_limiter: RateLimiter | None = None
_token_consumption_rate_limiter: RateLimiter | None = None

# Fixed command_name literals for audit.change_log rows (dnd_ai.api.audit.
# record_change_log) — one per distinct security-relevant operation this
# module performs, never derived from request data (dnd_ai.api.audit's own
# docstring: "always literal strings a call site supplies").
_LOGIN_SUCCESS_COMMAND_NAME = "local_auth.login_success"
_LOGIN_FAILURE_COMMAND_NAME = "local_auth.login_failure"
_LOGOUT_COMMAND_NAME = "local_auth.logout"
_CREATE_ACCOUNT_COMMAND_NAME = "local_auth.create_account"
_ACTIVATE_ACCOUNT_COMMAND_NAME = "local_auth.activate_account"
_ISSUE_PASSWORD_RESET_COMMAND_NAME = "local_auth.issue_password_reset"
_CONSUME_PASSWORD_RESET_COMMAND_NAME = "local_auth.consume_password_reset"
_CHANGE_PASSWORD_COMMAND_NAME = "local_auth.change_password"
_REVOKE_SESSION_COMMAND_NAME = "local_auth.revoke_session"
_DISABLE_ACCOUNT_COMMAND_NAME = "local_auth.disable_account"
_REACTIVATE_ACCOUNT_COMMAND_NAME = "local_auth.reactivate_account"
_ADMIN_REVOKE_ALL_SESSIONS_COMMAND_NAME = "local_auth.admin_revoke_all_sessions"


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


def _record_login_failure_audit(
    engine: Engine, *, login_name: str, correlation_id: str | None
) -> None:
    """A failed login attempt (`login_endpoint`, below) produces no data
    change to attach an audit row to on the request's own connection —
    `get_connection` rolls that connection's transaction back the moment
    `login_endpoint` raises `UnauthorizedError`, which would silently
    discard an audit row written on it too. This function instead opens
    and commits its own, independent transaction on `engine` — the one
    place in this module (or, so far, this codebase) a security-audit
    write deliberately does not share the request's own transaction —
    specifically so the audit record survives the very failure it
    describes.

    Never distinguishes "unknown login name" from "wrong password" (no
    `reason` is recorded) — the same non-disclosing contract `dnd_ai.
    commands.local_auth.authenticate_local_user` already applies to the API
    response itself, extended to the audit trail so it cannot become a
    second, quieter account-enumeration channel. `login_name`, normalized
    the same way `authenticate_local_user` normalizes it before comparison,
    is recorded in `changed_fields` — not a secret (unlike a password or
    any token), and its presence here is exactly what makes this record
    useful for spotting a brute-force pattern against one account; rate
    limiting (`get_login_rate_limiter`) is the mechanism that actually
    bounds the abuse this could otherwise invite, not this audit write
    itself. No `actor_user_id` — a failed login authenticates no one — so
    `actor_service` names this module instead, the same "actor is not a
    person" case that column exists for."""
    with engine.begin() as connection:
        record_change_log(
            connection,
            change_action_code="denied",
            schema_name="security",
            table_name="browser_sessions",
            record_id=None,
            entity_id=None,
            world_id=None,
            actor_service="local_auth",
            correlation_id=correlation_id,
            command_name=_LOGIN_FAILURE_COMMAND_NAME,
            event_id=None,
            changed_fields={"login_name": normalize_login_name(login_name)},
        )


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
    engine: Annotated[Engine, Depends(get_engine)],
    rate_limiter: Annotated[RateLimiter, Depends(get_login_rate_limiter)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> LoginResponse:
    """docs/PLAN.md §23.4 steps 1-4: rate limit, constant-work credential
    check, session creation with a rotated identifier, and the `Set-Cookie`
    response. Every failure — rate-limited or a genuine credential mismatch
    — raises the identical `UnauthorizedError`/`RateLimitedError` shape
    (distinct status codes, 429 vs. 401, but neither discloses which of
    "unknown login name," "inactive account," or "wrong password" applies,
    matching `dnd_ai.commands.local_auth.authenticate_local_user`'s own
    non-disclosing contract one layer down). A rate-limited attempt is not
    itself audited — `get_login_rate_limiter` already bounds the volume of
    both real attempts and the audit rows a sustained attack could
    otherwise generate; a genuine credential mismatch is, via `engine`'s
    own independent transaction (see `_record_login_failure_audit`)."""
    rate_limit_key = f"{_client_ip(request)}:{body.login_name.strip().lower()}"
    if not rate_limiter.allow(rate_limit_key, now=datetime.now(UTC)):
        raise RateLimitedError()

    user_id = authenticate_local_user(
        connection, login_name=body.login_name, raw_password=body.password
    )
    if user_id is None:
        _record_login_failure_audit(
            engine, login_name=body.login_name, correlation_id=correlation_id
        )
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
    record_change_log(
        connection,
        change_action_code="created",
        schema_name="security",
        table_name="browser_sessions",
        record_id=session.browser_session_id,
        entity_id=None,
        world_id=None,
        actor_user_id=user_id,
        correlation_id=correlation_id,
        command_name=_LOGIN_SUCCESS_COMMAND_NAME,
        event_id=None,
    )
    response.set_cookie(
        key=session_cookie_name(),
        value=session.raw_session_token,
        **session_cookie_set_kwargs(),  # type: ignore[arg-type]
    )
    return LoginResponse(user_id=user_id, csrf_token=session.csrf_token)


@router.post("/auth/logout", status_code=204)
def logout_endpoint(
    user_id: Annotated[uuid.UUID, Depends(require_human_user_id)],
    request: Request,
    response: Response,
    connection: Annotated[Connection, Depends(get_connection)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> Response:
    """docs/PLAN.md §23.4: revokes the session server-side and clears the
    cookie. `user_id` is depended on (via `require_human_user_id`) both to
    force CSRF/Origin enforcement through `get_authenticated_user_id` (an
    already-expired or invalid cookie fails there with 401 before this body
    ever runs — logging out an already-dead session needs no further
    server-side action, so that is an acceptable outcome, not a gap) and to
    attribute the logout audit row below; the actual revocation reads the
    raw cookie value directly rather than the resolved principal, since
    `AuthenticatedPrincipal` deliberately carries no raw secret."""
    raw_session_token = request.cookies.get(session_cookie_name())
    if raw_session_token is not None:
        revoked_session_id = revoke_browser_session_by_token(
            connection, raw_session_token=raw_session_token
        )
        if revoked_session_id is not None:
            record_change_log(
                connection,
                change_action_code="updated",
                schema_name="security",
                table_name="browser_sessions",
                record_id=revoked_session_id,
                entity_id=None,
                world_id=None,
                actor_user_id=user_id,
                correlation_id=correlation_id,
                command_name=_LOGOUT_COMMAND_NAME,
                event_id=None,
            )
    response.delete_cookie(key=session_cookie_name(), path="/")
    return Response(status_code=204)


class SessionUserResponse(BaseModel):
    user_id: uuid.UUID
    display_name: str


class CharacterPerspectiveResponse(BaseModel):
    character_id: uuid.UUID
    character_name: str


class CampaignBootstrapResponse(BaseModel):
    campaign_id: uuid.UUID
    campaign_name: str
    timeline_id: uuid.UUID | None
    timeline_name: str | None
    roles: list[str]
    character_perspectives: list[CharacterPerspectiveResponse]
    selected_character_id: uuid.UUID | None
    capabilities: list[str]


class SessionFeaturesResponse(BaseModel):
    ask: bool
    ai_summaries: bool
    gm_briefs: bool
    cited_rules: bool


# Phase 12's Ask/AI-summaries/GM-briefs/cited-rules surfaces are
# unfinished and unverified (docs/PLAN.md §23.7, Increment 13G) — no
# server feature manifest exists yet to gate them (a search of this
# codebase for one found none). Until that manifest is built, this
# endpoint reports every one of the four as unconditionally disabled,
# never derived from AuthenticatedPrincipal/AccessContext — a fixed,
# audience-independent constant is the smallest correct answer that
# satisfies "keep unfinished Phase 12 features disabled" without
# fabricating gating logic this workstream does not own.
_PHASE_12_FEATURES_ALL_DISABLED = SessionFeaturesResponse(
    ask=False, ai_summaries=False, gm_briefs=False, cited_rules=False
)


class SessionBootstrapResponse(BaseModel):
    user: SessionUserResponse
    csrf_token: str
    browser_session_id: uuid.UUID | None
    selected_campaign_id: uuid.UUID | None
    campaigns: list[CampaignBootstrapResponse]
    features: SessionFeaturesResponse


@router.get("/auth/session", response_model=SessionBootstrapResponse, status_code=200)
def session_bootstrap_endpoint(
    principal: Annotated[AuthenticatedPrincipal, Depends(get_authenticated_user_id)],
    connection: Annotated[Connection, Depends(get_connection)],
) -> SessionBootstrapResponse:
    """The authoritative portal-bootstrap contract (docs/PLAN.md §23.4,
    §23.7 — Phase 13B blocker 2): current user, a fresh CSRF token read,
    the authenticating session id, and every active campaign membership
    with its roles, selectable character perspectives, and effective
    capabilities, plus the (currently all-disabled) Phase 12 feature
    manifest. Never a password hash, reset/activation token, or durable API
    credential.

    Every authorization-sensitive field is recomputed from current database
    state on every call — `dnd_ai.queries.bootstrap.get_session_bootstrap`
    resolves campaigns/roles/perspectives/capabilities through the same
    `dnd_ai.domain.access.resolve_access_context` every other endpoint
    authorizes through, never a second, portal-specific authorization path
    — and this handler performs no write of its own, so a membership,
    relationship, grant, or account-lifecycle change already committed by
    the time of the *next* request is reflected there, with no caching
    layer to invalidate.

    Reachable by any human auth method (`require_human_user_id`'s accepted
    set), not only a browser session — an OIDC caller hitting this (a
    non-browser bearer-token client checking who it's authenticated as)
    gets an empty `csrf_token` and a `null` `browser_session_id`, exactly
    as the prior minimal contract did, since neither concept exists for a
    bearer-token caller; the campaign/capability/feature portion of the
    response is unaffected by auth method either way."""
    csrf_token = (
        resolve_browser_session_csrf_token(
            connection, browser_session_id=principal.local_session_id
        )
        if principal.local_session_id is not None
        else None
    )
    bootstrap = get_session_bootstrap(connection, user_id=principal.user_id)
    return SessionBootstrapResponse(
        user=SessionUserResponse(user_id=bootstrap.user_id, display_name=bootstrap.display_name),
        csrf_token=csrf_token or "",
        browser_session_id=principal.local_session_id,
        selected_campaign_id=bootstrap.selected_campaign_id,
        campaigns=[
            CampaignBootstrapResponse(
                campaign_id=campaign.campaign_id,
                campaign_name=campaign.campaign_name,
                timeline_id=campaign.timeline_id,
                timeline_name=campaign.timeline_name,
                roles=list(campaign.roles),
                character_perspectives=[
                    CharacterPerspectiveResponse(
                        character_id=perspective.character_id,
                        character_name=perspective.character_name,
                    )
                    for perspective in campaign.character_perspectives
                ],
                selected_character_id=campaign.selected_character_id,
                capabilities=list(campaign.capabilities),
            )
            for campaign in bootstrap.campaigns
        ],
        features=_PHASE_12_FEATURES_ALL_DISABLED,
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
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> Response:
    change_password(
        connection,
        user_id=user_id,
        current_raw_password=body.current_password,
        new_raw_password=body.new_password,
    )
    record_change_log(
        connection,
        change_action_code="updated",
        schema_name="security",
        table_name="local_credentials",
        record_id=user_id,
        entity_id=None,
        world_id=None,
        actor_user_id=user_id,
        correlation_id=correlation_id,
        command_name=_CHANGE_PASSWORD_COMMAND_NAME,
        event_id=None,
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
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> Response:
    revoke_browser_session(connection, user_id=user_id, browser_session_id=browser_session_id)
    record_change_log(
        connection,
        change_action_code="updated",
        schema_name="security",
        table_name="browser_sessions",
        record_id=browser_session_id,
        entity_id=None,
        world_id=None,
        actor_user_id=user_id,
        correlation_id=correlation_id,
        command_name=_REVOKE_SESSION_COMMAND_NAME,
        event_id=None,
    )
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
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
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
    record_change_log(
        connection,
        change_action_code="created",
        schema_name="security",
        table_name="users",
        record_id=result.user_id,
        entity_id=None,
        world_id=None,
        actor_user_id=admin_user_id,
        correlation_id=correlation_id,
        command_name=_CREATE_ACCOUNT_COMMAND_NAME,
        event_id=None,
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
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> IssuePasswordResetResponse:
    result = _issue_password_reset_token_impl(
        connection,
        requested_by_user_id=admin_user_id,
        target_user_id=target_user_id,
        revoke_sessions=body.revoke_sessions,
    )
    record_change_log(
        connection,
        change_action_code="created",
        schema_name="security",
        table_name="password_reset_tokens",
        record_id=result.user_id,
        entity_id=None,
        world_id=None,
        actor_user_id=admin_user_id,
        correlation_id=correlation_id,
        command_name=_ISSUE_PASSWORD_RESET_COMMAND_NAME,
        event_id=None,
    )
    return IssuePasswordResetResponse(
        user_id=result.user_id,
        raw_reset_token=result.raw_token,
        expires_at=result.expires_at.isoformat(),
    )


class AccountLifecycleResponse(BaseModel):
    user_id: uuid.UUID
    previous_lifecycle_status: str
    new_lifecycle_status: str


@router.post(
    "/admin/accounts/{target_user_id}/disable",
    response_model=AccountLifecycleResponse,
    status_code=200,
)
def disable_account_endpoint(
    target_user_id: uuid.UUID,
    admin_user_id: Annotated[uuid.UUID, Depends(require_human_user_id)],
    connection: Annotated[Connection, Depends(get_connection)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> AccountLifecycleResponse:
    """Marks `target_user_id` inactive and revokes every one of its active
    browser sessions (`dnd_ai.commands.local_auth._disable_local_account_
    impl`, in the same transaction) — it can no longer authenticate,
    starting with its very next request. Idempotent: disabling an
    already-disabled account succeeds again rather than erroring. Does not
    alter Foundry pairing/device access — see that command's own
    docstring."""
    result = _disable_local_account_impl(
        connection, admin_user_id=admin_user_id, target_user_id=target_user_id
    )
    record_change_log(
        connection,
        change_action_code="status_changed",
        schema_name="security",
        table_name="users",
        record_id=result.user_id,
        entity_id=None,
        world_id=None,
        actor_user_id=admin_user_id,
        correlation_id=correlation_id,
        command_name=_DISABLE_ACCOUNT_COMMAND_NAME,
        event_id=None,
        previous_status=result.previous_lifecycle_status_code,
        new_status=result.new_lifecycle_status_code,
    )
    return AccountLifecycleResponse(
        user_id=result.user_id,
        previous_lifecycle_status=result.previous_lifecycle_status_code,
        new_lifecycle_status=result.new_lifecycle_status_code,
    )


@router.post(
    "/admin/accounts/{target_user_id}/reactivate",
    response_model=AccountLifecycleResponse,
    status_code=200,
)
def reactivate_account_endpoint(
    target_user_id: uuid.UUID,
    admin_user_id: Annotated[uuid.UUID, Depends(require_human_user_id)],
    connection: Annotated[Connection, Depends(get_connection)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> AccountLifecycleResponse:
    """Restores `target_user_id`'s ability to authenticate — does not
    restore any browser session `disable_account_endpoint` (or any other
    revocation path) already revoked, so the account still requires a
    fresh `POST /auth/login` (`dnd_ai.commands.local_auth.
    _reactivate_local_account_impl`'s own docstring). Idempotent:
    reactivating an already-active account succeeds again rather than
    erroring."""
    result = _reactivate_local_account_impl(
        connection, admin_user_id=admin_user_id, target_user_id=target_user_id
    )
    record_change_log(
        connection,
        change_action_code="status_changed",
        schema_name="security",
        table_name="users",
        record_id=result.user_id,
        entity_id=None,
        world_id=None,
        actor_user_id=admin_user_id,
        correlation_id=correlation_id,
        command_name=_REACTIVATE_ACCOUNT_COMMAND_NAME,
        event_id=None,
        previous_status=result.previous_lifecycle_status_code,
        new_status=result.new_lifecycle_status_code,
    )
    return AccountLifecycleResponse(
        user_id=result.user_id,
        previous_lifecycle_status=result.previous_lifecycle_status_code,
        new_lifecycle_status=result.new_lifecycle_status_code,
    )


class AdminRevokeAllSessionsResponse(BaseModel):
    user_id: uuid.UUID
    revoked_count: int


@router.post(
    "/admin/accounts/{target_user_id}/revoke-sessions",
    response_model=AdminRevokeAllSessionsResponse,
    status_code=200,
)
def admin_revoke_all_sessions_endpoint(
    target_user_id: uuid.UUID,
    admin_user_id: Annotated[uuid.UUID, Depends(require_human_user_id)],
    connection: Annotated[Connection, Depends(get_connection)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> AdminRevokeAllSessionsResponse:
    """Revokes every active browser session belonging to `target_user_id`
    only — every other user's sessions are untouched
    (`dnd_ai.commands.local_auth._admin_revoke_all_browser_sessions_impl`).
    Independent of account disablement: the target account remains active
    and may sign in again immediately with a fresh login, exactly as a
    self-service revoke-all-devices action would leave it. Idempotent: with
    no active sessions left, this still succeeds and reports
    `revoked_count=0`."""
    result = _admin_revoke_all_browser_sessions_impl(
        connection, admin_user_id=admin_user_id, target_user_id=target_user_id
    )
    record_change_log(
        connection,
        change_action_code="updated",
        schema_name="security",
        table_name="users",
        record_id=result.user_id,
        entity_id=None,
        world_id=None,
        actor_user_id=admin_user_id,
        correlation_id=correlation_id,
        command_name=_ADMIN_REVOKE_ALL_SESSIONS_COMMAND_NAME,
        event_id=None,
        changed_fields={"revoked_session_count": result.revoked_count},
    )
    return AdminRevokeAllSessionsResponse(
        user_id=result.user_id, revoked_count=result.revoked_count
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
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> ActivateAccountResponse:
    if not rate_limiter.allow(_client_ip(request), now=datetime.now(UTC)):
        raise RateLimitedError()
    result = _activate_local_account_impl(
        connection, raw_activation_token=body.token, raw_password=body.password
    )
    record_change_log(
        connection,
        change_action_code="created",
        schema_name="security",
        table_name="local_credentials",
        record_id=result.user_id,
        entity_id=None,
        world_id=None,
        actor_user_id=result.user_id,
        correlation_id=correlation_id,
        command_name=_ACTIVATE_ACCOUNT_COMMAND_NAME,
        event_id=None,
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
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> ResetPasswordResponse:
    if not rate_limiter.allow(_client_ip(request), now=datetime.now(UTC)):
        raise RateLimitedError()
    result = _reset_password_with_token_impl(
        connection, raw_reset_token=body.token, new_raw_password=body.new_password
    )
    record_change_log(
        connection,
        change_action_code="updated",
        schema_name="security",
        table_name="local_credentials",
        record_id=result.user_id,
        entity_id=None,
        world_id=None,
        actor_user_id=result.user_id,
        correlation_id=correlation_id,
        command_name=_CONSUME_PASSWORD_RESET_COMMAND_NAME,
        event_id=None,
    )
    return ResetPasswordResponse(user_id=result.user_id, sessions_revoked=result.sessions_revoked)


__all__ = ["router", "get_login_rate_limiter", "get_token_consumption_rate_limiter"]
