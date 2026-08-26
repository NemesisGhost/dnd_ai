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
`get_login_ip_rate_limiter`/`get_login_account_rate_limiter`/
`get_token_consumption_rate_limiter` mirror `dnd_ai.api.auth.
get_jwks_client`'s singleton-plus-override shape exactly — each a
process-wide `dnd_ai.domain.rate_limit.RateLimiter`, resolved through a
FastAPI dependency so tests can substitute a fresh instance via
`app.dependency_overrides` instead of sharing rate-limit state across
unrelated test cases in the same process. `login_endpoint` checks the IP-
and account-wide ceilings as two *independent* limiters, not one composite
"ip:login_name" key — that composite shape let a caller reset its own
bucket on every request merely by varying `login_name`, which neither
independent ceiling permits (see `get_login_ip_rate_limiter`'s own
module-level comment for the full reasoning).

Client-address resolution (Phase 13B correction): `resolve_client_ip`
(`dnd_ai.api.client_address`, shared with `dnd_ai.api.foundry_pairing` —
see that module's own docstring for the full trust algorithm) reads
`request.client.host` unless that immediate peer is a configured trusted
proxy (`dnd_ai.config.settings.trusted_proxies`), in which case it trusts
the last `X-Forwarded-For` entry instead. With no trusted proxy configured
— the safe default, and this repository's current `compose.yaml` topology,
which has no reverse proxy in front of `api` yet (PLAN.md §32, Phase 14) —
this behaves identically to the plain `request.client.host` read this
module used before the correction. A real deployment that places a reverse
proxy in front of `api` must set `DND_AI_TRUSTED_PROXIES` to that proxy's
address before enabling public login, or the IP-wide ceiling below still
degrades to one shared bucket across every client behind it (the proxy's
own address) — see `dnd_ai.config`'s own docstring and `compose.yaml`'s
`api` service comment.

Account-wide rate limiting does not gate authentication itself (Phase 13B
correction): `get_login_account_rate_limiter`'s ceiling is checked only
*after* `authenticate_local_user` has already run and reported a failure —
never before it — so a caller who has filled one login name's failure
bucket (by distributing wrong-password attempts across many source
addresses, each individually under the IP-wide ceiling) can never turn
that into a hard lock against the *correct* password for that same
account; every IP-admitted request is always fully authenticated. The
account-wide ceiling instead bounds what happens after a failed attempt —
audit-log admission and how long invalid attempts against one login name
keep receiving a plain `401` before degrading to `429` — so distributed
brute-forcing of one account remains bounded and observable without ever
becoming a denial-of-service primitive against that account's legitimate
owner. See `login_endpoint`'s own docstring for the exact flow.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import Connection

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
from dnd_ai.domain.passwords import MAX_PASSWORD_LENGTH
from dnd_ai.domain.rate_limit import RateLimiter
from dnd_ai.queries.bootstrap import get_session_bootstrap

from .audit import record_change_log
from .auth import get_authenticated_user_id, require_human_user_id
from .client_address import resolve_client_ip
from .cookies import session_cookie_name, session_cookie_set_kwargs
from .correlation import get_request_correlation_id
from .deps import get_connection
from .errors import RateLimitedError, UnauthorizedError

router = APIRouter(tags=["local_auth"])

# Login-name field size limit for /auth/login specifically, mirroring
# dnd_ai.commands.local_auth._LOGIN_NAME_MAX_LENGTH (64) — that module's
# own `_validate_login_name_format` already enforces this for every login
# name a *command* ever persists or compares, but /auth/login never calls
# it (there is nothing to "create" on a login attempt), so an oversized
# login_name would otherwise reach the database lookup, the rate-limiter
# key, and (on a genuine mismatch) the audit write unbounded. Duplicated
# here, not imported, since that constant is private to the commands
# module and this is the one API-layer field that needs its own copy of
# the same limit.
_LOGIN_REQUEST_LOGIN_NAME_MAX_LENGTH = 64

# Independent rate-limit ceilings for /auth/login (Phase 13B correction):
# a single limiter keyed on "ip:login_name" let an attacker reset their own
# bucket every request merely by varying login_name, defeating the limit
# entirely. Two independent limiters close that gap without depending on
# each other: an IP-wide ceiling (any login_name from one source address),
# checked *before* authenticate_local_user runs, and an account-wide
# ceiling (one login_name from any source address), checked only *after* a
# failed attempt (see login_endpoint below) — never before, so it can never
# reject a correct password without verifying it first. The IP ceiling is
# deliberately more generous than the account one — it exists to bound
# abuse volume from one address, not to police how many distinct users a
# shared address (e.g. NAT/office gateway) legitimately serves. A composite
# per-(ip, login_name) limiter was deliberately dropped: with both
# independent ceilings in place it added no coverage neither already
# provides, only a third bucket to maintain.
_LOGIN_IP_RATE_LIMIT_MAX_ATTEMPTS = 30
_LOGIN_IP_RATE_LIMIT_WINDOW = timedelta(minutes=15)
_LOGIN_ACCOUNT_RATE_LIMIT_MAX_ATTEMPTS = 10
_LOGIN_ACCOUNT_RATE_LIMIT_WINDOW = timedelta(minutes=15)
_TOKEN_CONSUMPTION_RATE_LIMIT_MAX_ATTEMPTS = 20
_TOKEN_CONSUMPTION_RATE_LIMIT_WINDOW = timedelta(minutes=15)

_login_ip_rate_limiter: RateLimiter | None = None
_login_account_rate_limiter: RateLimiter | None = None
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


def get_login_ip_rate_limiter() -> RateLimiter:
    global _login_ip_rate_limiter
    if _login_ip_rate_limiter is None:
        _login_ip_rate_limiter = RateLimiter(
            max_attempts=_LOGIN_IP_RATE_LIMIT_MAX_ATTEMPTS, window=_LOGIN_IP_RATE_LIMIT_WINDOW
        )
    return _login_ip_rate_limiter


def get_login_account_rate_limiter() -> RateLimiter:
    """Bounds *failed* attempts against one login name (Phase 13B
    correction) — `login_endpoint` never consults this before calling
    `authenticate_local_user`, only after it reports a failure, precisely
    so a full account bucket can never itself reject a correct password.
    See `login_endpoint`'s own docstring for the exact flow this and
    `get_login_ip_rate_limiter` together implement."""
    global _login_account_rate_limiter
    if _login_account_rate_limiter is None:
        _login_account_rate_limiter = RateLimiter(
            max_attempts=_LOGIN_ACCOUNT_RATE_LIMIT_MAX_ATTEMPTS,
            window=_LOGIN_ACCOUNT_RATE_LIMIT_WINDOW,
        )
    return _login_account_rate_limiter


def get_token_consumption_rate_limiter() -> RateLimiter:
    global _token_consumption_rate_limiter
    if _token_consumption_rate_limiter is None:
        _token_consumption_rate_limiter = RateLimiter(
            max_attempts=_TOKEN_CONSUMPTION_RATE_LIMIT_MAX_ATTEMPTS,
            window=_TOKEN_CONSUMPTION_RATE_LIMIT_WINDOW,
        )
    return _token_consumption_rate_limiter


def _record_login_failure_audit(
    connection: Connection, *, login_name: str, correlation_id: str | None
) -> None:
    """A failed login attempt (`login_endpoint`, below) produces no other
    data change on this request's connection — `get_connection` rolls that
    connection's transaction back the moment `login_endpoint` raises
    `UnauthorizedError` right after this call, which would silently
    discard an audit row written normally. Committing this write
    immediately, on the connection `login_endpoint` already holds, durably
    persists it despite that rollback.

    Deliberately reuses the *request's own* connection rather than opening
    a second one (an `engine.begin()`-backed independent transaction, this
    function's original Phase 13B shape) — a failed request that held its
    request-scoped connection open *and* a second audit connection
    simultaneously could starve or, on a pool sized to 1, deadlock a small
    connection pool under concurrent failed-login load, since neither
    connection could be released until the other's work finished. Calling
    `Connection.commit()` mid-request like this ends the transaction
    `get_connection`'s own `with connection.begin():` started early and is
    officially supported "commit as you go" usage — per `Connection.
    begin()`'s own docstring, doing so "is not fundamentally any different"
    from ending that `with` block here; when the generator resumes and
    that block's `__exit__` eventually runs, it observes the transaction
    already completed and simply closes without attempting a second
    commit. Nothing else touches `connection` after this call on the
    failure path (the endpoint raises immediately), so no further
    statement can autobegin a new, orphaned transaction on it.

    Never distinguishes "unknown login name" from "wrong password" (no
    `reason` is recorded) — the same non-disclosing contract `dnd_ai.
    commands.local_auth.authenticate_local_user` already applies to the API
    response itself, extended to the audit trail so it cannot become a
    second, quieter account-enumeration channel. `login_name`, normalized
    the same way `authenticate_local_user` normalizes it before comparison,
    is recorded in `changed_fields` — not a secret (unlike a password or
    any token), and its presence here is exactly what makes this record
    useful for spotting a brute-force pattern against one account.

    Reached only once a real credential check has already failed *and*
    `get_login_account_rate_limiter` still admits this login name (Phase
    13B correction — the account ceiling is checked after, never before,
    authentication itself; see `login_endpoint`'s own docstring) — the
    IP-wide ceiling bounds how many *attempts* one source address can ever
    make per window regardless of how many distinct login names it
    presents, and the account-wide ceiling separately bounds how many of
    *these audit rows* one login name can accumulate per window regardless
    of how many distinct source addresses present it, closing both the
    "vary the name every request" and the "vary the source address every
    request" versions of the same unbounded-audit-growth gap. No
    `actor_user_id` — a failed login authenticates no one — so
    `actor_service` names this module instead, the same "actor is not a
    person" case that column exists for."""
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
    connection.commit()


# ---------------------------------------------------------------------------
# Login / logout / session bootstrap
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    # Explicit upper bounds, checked by Pydantic before this model even
    # reaches login_endpoint — before any database lookup, Argon2 call,
    # rate-limiter key, or audit write (Phase 13B correction). An oversized
    # login_name would otherwise become an unbounded rate-limiter/audit key;
    # an oversized password would otherwise be handed straight to Argon2id
    # verification (authenticate_local_user calls dnd_ai.domain.passwords.
    # verify_password directly, never dnd_ai.domain.passwords.
    # validate_password_policy — that check only applies when *setting* a
    # password, not verifying one), making hashing cost attacker-controlled.
    login_name: str = Field(max_length=_LOGIN_REQUEST_LOGIN_NAME_MAX_LENGTH)
    password: str = Field(repr=False, max_length=MAX_PASSWORD_LENGTH)


class LoginResponse(BaseModel):
    user_id: uuid.UUID
    csrf_token: str


@router.post("/auth/login", response_model=LoginResponse, status_code=200)
def login_endpoint(
    body: LoginRequest,
    request: Request,
    response: Response,
    connection: Annotated[Connection, Depends(get_connection)],
    ip_rate_limiter: Annotated[RateLimiter, Depends(get_login_ip_rate_limiter)],
    account_rate_limiter: Annotated[RateLimiter, Depends(get_login_account_rate_limiter)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> LoginResponse:
    """docs/PLAN.md §23.4 steps 1-4: rate limit, constant-work credential
    check, session creation with a rotated identifier, and the `Set-Cookie`
    response. Every failure — rate-limited or a genuine credential mismatch
    — raises the identical `UnauthorizedError`/`RateLimitedError` shape
    (distinct status codes, 429 vs. 401, but neither discloses which of
    "unknown login name," "inactive account," or "wrong password" applies,
    matching `dnd_ai.commands.local_auth.authenticate_local_user`'s own
    non-disclosing contract one layer down).

    Only `ip_rate_limiter` gates admission *before* `authenticate_local_
    user` runs (Phase 13B correction, replacing an earlier shape that also
    consulted `account_rate_limiter` up front): once a request is IP-
    admitted, its credential is *always* verified — there is no
    attacker-reachable state, including a login name's own failure bucket
    being completely full, that can turn into a 429 for a caller who
    presents the *correct* password. `account_rate_limiter` is instead
    consulted only in the failure branch below, where it decides two
    things bounded independently of the IP ceiling: whether this failure
    is durably audited, and whether the caller sees `401` (credential
    genuinely rejected, this login name's own bucket still has room) or
    `429` (this login name has already accumulated
    `_LOGIN_ACCOUNT_RATE_LIMIT_MAX_ATTEMPTS` recent failures, from however
    many distinct source addresses). Both outcomes are reachable for both
    a real and a nonexistent login name — the bucket is keyed on the
    normalized name text, not on whether an account actually exists behind
    it — so neither response shape discloses account existence any more
    than the pre-existing `401`-vs-`401` non-disclosure already didn't.
    A successful login on an IP-admitted request always succeeds
    regardless of the account bucket's state, and forgives only that
    bucket (see the comment at `account_rate_limiter.reset` below)."""
    client_ip = resolve_client_ip(request)
    normalized_login_name = normalize_login_name(body.login_name)
    now = datetime.now(UTC)
    if not ip_rate_limiter.allow(client_ip, now=now):
        raise RateLimitedError()

    user_id = authenticate_local_user(
        connection, login_name=body.login_name, raw_password=body.password
    )
    if user_id is None:
        # Checked here, never before authenticate_local_user runs (Phase
        # 13B correction) — a full bucket for this login name must never
        # reject a correct password without verifying it, only throttle
        # how the *invalid*-credential path behaves. allow() itself
        # already declines to extend the window when the bucket is full
        # (dnd_ai.domain.rate_limit.RateLimiter.allow's own docstring), so
        # a sustained attack against one name, from any number of distinct
        # source addresses, cannot grow this bucket's own memory or the
        # audit rows it admits below past that ceiling.
        if account_rate_limiter.allow(normalized_login_name, now=now):
            _record_login_failure_audit(
                connection, login_name=body.login_name, correlation_id=correlation_id
            )
            raise UnauthorizedError()
        raise RateLimitedError()
    # Only the account-wide bucket is cleared on success — never the
    # IP-wide one. Resetting the IP bucket too would let one throwaway
    # successful login (e.g. the attacker's own account, or any account
    # sharing that address) wipe the IP-wide abuse counter clean and let a
    # sustained attack against *other* accounts from the same address
    # continue unthrottled; the account-wide bucket, in contrast, tracks
    # exactly the identity that just proved it knows the current password,
    # so it alone is safe to forgive.
    account_rate_limiter.reset(normalized_login_name)

    # "Successful login rotates the session" (docs/PLAN.md §23.4): a fresh
    # session is always created here, never reused — there is no pre-
    # authentication session identifier in this design to rotate away from
    # (no anonymous session exists before login), so a new, distinct
    # session/CSRF-secret pair on every successful login already satisfies
    # the rotation requirement.
    session = create_browser_session(
        connection,
        user_id=user_id,
        created_ip=client_ip,
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
    if not rate_limiter.allow(resolve_client_ip(request), now=datetime.now(UTC)):
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
    if not rate_limiter.allow(resolve_client_ip(request), now=datetime.now(UTC)):
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


__all__ = [
    "router",
    "get_login_account_rate_limiter",
    "get_login_ip_rate_limiter",
    "get_token_consumption_rate_limiter",
]
