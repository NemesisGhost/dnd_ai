"""Single-link campaign-invitation onboarding endpoints (Phase 13E
checkpoint 8b — `PHASE13E_REMAINING_IMPLEMENTATION_PLAN.md` §8.2, the
authoritative contract this module implements exactly).

Five routes under `/campaign-invitations/onboarding`: `start`, `status`,
`register`, `complete`, `cancel`. `dnd_ai.commands.invitation_onboarding`
(checkpoint 8a) does every validation and mutation; this module is the
HTTP-specific plumbing: cookie read/write, the onboarding CSRF double-
submit check, and the `next_action` derivation.

## Never auto-completes (S-1)

`complete` is the only route that binds an *already signed-in* visitor's
account to the invitation, and it is reachable only by an explicit,
client-initiated `POST` carrying the ordinary session CSRF/Origin contract
(`require_human_user_id`, via `get_authenticated_user_id`) — nothing in
this module or in `dnd_ai.commands.invitation_onboarding` ever completes
an onboarding session on a `GET`, or as a side effect of any other call.
`register` similarly requires an explicit form submission; it is the
brand-new registrant's own equivalent of the confirm step, since
submitting that form is itself the one explicit action such a caller
gets to take (see `dnd_ai.commands.local_auth.
_register_invited_local_account_impl`'s own docstring).

## `next_action` (S-4)

Derived on every `start`/`status` call from whether a *currently valid*
local browser session accompanies the request — read directly via
`resolve_local_session_principal`, deliberately bypassing `get_
authenticated_user_id`'s own CSRF/Origin enforcement (which would
otherwise incorrectly demand a session `X-CSRF-Token` header on `start`,
a route with no such requirement). This is a soft, informational read:
a resolution failure here means "not currently signed in," never an
error. The onboarding session itself records nothing about which account
is expected — there is nothing trustworthy to record before
authentication — so the *signed-in principal's own current session* is
always the source of truth for what `confirm`/`complete` will bind to.

## Authorization-header rejection (S-10)

`start` and `register` are unauthenticated by design (no principal to
resolve). Per `PHASE13E_REMAINING_IMPLEMENTATION_PLAN.md` §7.1 S-10, an
`Authorization` header on either must be rejected outright, not silently
ignored — `_reject_authorization_header` below.
"""

import hmac
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import Connection, text

from dnd_ai.commands.invitation_onboarding import (
    OnboardingNotAvailableError,
    begin_invitation_onboarding,
    cancel_invitation_onboarding,
    complete_invitation_onboarding,
    resolve_invitation_onboarding_status,
)
from dnd_ai.commands.local_auth import (
    _register_invited_local_account_impl,
    resolve_local_session_principal,
)
from dnd_ai.domain.rate_limit import RateLimiter

from .audit import record_change_log
from .auth import require_allowed_origin, require_human_user_id
from .client_address import resolve_client_ip
from .cookies import (
    onboarding_cookie_name,
    onboarding_cookie_set_kwargs,
    session_cookie_name,
    session_cookie_set_kwargs,
)
from .correlation import get_request_correlation_id
from .deps import get_connection
from .errors import ForbiddenError, RateLimitedError
from .local_auth import get_token_consumption_rate_limiter

router = APIRouter(tags=["invitation_onboarding"])

_BEGIN_COMMAND_NAME = "invitation_onboarding.begin"
_REGISTER_COMMAND_NAME = "invitation_onboarding.register"
_COMPLETE_COMMAND_NAME = "invitation_onboarding.complete"
_CANCEL_COMMAND_NAME = "invitation_onboarding.cancel"

_SIGN_IN_OR_REGISTER_ACTION = "sign_in_or_register"
_CONFIRM_ACTION = "confirm"

# D-11, mirroring dnd_ai.api.local_auth.CreateAccountRequest's own bound —
# matches the database ck_users_display_name_length CHECK (migration 107)
# exactly, so a caller sees a clear 422 rather than an opaque constraint
# violation.
_DISPLAY_NAME_MAX_LENGTH = 100


def _reject_authorization_header(request: Request) -> None:
    """S-10: `start`/`register` are unauthenticated by design; a present
    `Authorization` header must be rejected, not silently ignored — an
    unauthenticated route that quietly tolerates a credential header could
    otherwise mask a caller's own mistaken assumption about which identity
    this request is acting under."""
    if request.headers.get("authorization") is not None:
        raise ForbiddenError()


def _resolve_signed_in_context(request: Request, connection: Connection) -> tuple[str, str | None]:
    """See this module's own docstring, "`next_action` (S-4)" — a soft,
    informational read of the *current* local session cookie, never an
    error on absence or invalidity."""
    raw_session_token = request.cookies.get(session_cookie_name())
    if raw_session_token is None:
        return _SIGN_IN_OR_REGISTER_ACTION, None
    principal = resolve_local_session_principal(connection, raw_session_token=raw_session_token)
    if principal is None:
        return _SIGN_IN_OR_REGISTER_ACTION, None
    display_name = connection.execute(
        text("SELECT display_name FROM security.users WHERE user_id = :user"),
        {"user": principal.user_id},
    ).scalar()
    if display_name is None:
        return _SIGN_IN_OR_REGISTER_ACTION, None
    return _CONFIRM_ACTION, str(display_name)


def _require_onboarding_csrf_token(
    request: Request, connection: Connection, raw_onboarding_token: str
) -> str:
    """The onboarding session's own double-submit check for `register`/
    `cancel` — mirrors `dnd_ai.api.auth._enforce_csrf_and_origin`'s session-
    CSRF comparison exactly, `hmac.compare_digest` included, over `security.
    invitation_onboarding_sessions.csrf_token` instead of `security.
    browser_sessions.csrf_token`. Resolving the session here first (a plain
    read, no lock) means an already-dead session surfaces as the ordinary
    `OnboardingNotAvailableError` before any CSRF comparison is even
    attempted — there is nothing to protect on a session that is already
    unusable. Returns the campaign display name so callers that already
    need it (register) do not pay for a second lookup."""
    status = resolve_invitation_onboarding_status(connection, onboarding_token=raw_onboarding_token)
    submitted = request.headers.get("x-onboarding-csrf-token")
    if submitted is None or not hmac.compare_digest(submitted, status.onboarding_csrf_token):
        raise ForbiddenError()
    return status.campaign_display_name


class BeginOnboardingRequest(BaseModel):
    token: str = Field(repr=False)


class BeginOnboardingResponse(BaseModel):
    campaign_display_name: str
    invitation_expires_at: str
    onboarding_expires_at: str
    onboarding_csrf_token: str = Field(repr=False)
    next_action: str
    signed_in_display_name: str | None = None


@router.post(
    "/campaign-invitations/onboarding/start",
    response_model=BeginOnboardingResponse,
    status_code=201,
)
def begin_invitation_onboarding_endpoint(
    body: BeginOnboardingRequest,
    request: Request,
    response: Response,
    connection: Annotated[Connection, Depends(get_connection)],
    rate_limiter: Annotated[RateLimiter, Depends(get_token_consumption_rate_limiter)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
    _origin: Annotated[None, Depends(require_allowed_origin)],
) -> BeginOnboardingResponse:
    _reject_authorization_header(request)
    if not rate_limiter.allow(resolve_client_ip(request), now=datetime.now(UTC)):
        raise RateLimitedError()

    existing_onboarding_token = request.cookies.get(onboarding_cookie_name())
    result = begin_invitation_onboarding(
        connection,
        invitation_token=body.token,
        existing_onboarding_token=existing_onboarding_token,
        created_ip=resolve_client_ip(request),
    )
    next_action, signed_in_display_name = _resolve_signed_in_context(request, connection)

    remaining_seconds = max(
        1, int((result.onboarding_expires_at - datetime.now(UTC)).total_seconds())
    )
    response.set_cookie(
        key=onboarding_cookie_name(),
        value=result.raw_onboarding_token,
        **onboarding_cookie_set_kwargs(max_age_seconds=remaining_seconds),  # type: ignore[arg-type]
    )
    # A pure "did a link get opened" event, not itself a state change on
    # any durable domain row (dnd_ai.commands.invitation_onboarding's own
    # docstring: "begin_invitation_onboarding (reads only, no row)" refers
    # to audit.change_log specifically) -- record_change_log is
    # deliberately not called here, mirroring accept_campaign_invitation's
    # own read-side calls receiving no audit row of their own.
    del correlation_id
    return BeginOnboardingResponse(
        campaign_display_name=result.campaign_display_name,
        invitation_expires_at=result.invitation_expires_at.isoformat(),
        onboarding_expires_at=result.onboarding_expires_at.isoformat(),
        onboarding_csrf_token=result.onboarding_csrf_token,
        next_action=next_action,
        signed_in_display_name=signed_in_display_name,
    )


class OnboardingStatusResponse(BaseModel):
    campaign_display_name: str
    invitation_expires_at: str
    onboarding_expires_at: str
    # Additive correction to §8.2's original contract table (found while
    # building the portal page around it): without this, a page refresh
    # loses the only copy of the onboarding CSRF token, permanently
    # blocking register/cancel for the rest of that session -- there is no
    # separate reissue endpoint. `/auth/session` already re-returns a fresh
    # `csrf_token` on every call (that endpoint's own docstring); this
    # mirrors the identical "the current token is always available from a
    # plain read" shape for the onboarding session's own CSRF secret.
    onboarding_csrf_token: str = Field(repr=False)
    next_action: str
    signed_in_display_name: str | None = None


@router.get(
    "/campaign-invitations/onboarding/status",
    response_model=OnboardingStatusResponse,
    status_code=200,
)
def invitation_onboarding_status_endpoint(
    request: Request,
    connection: Annotated[Connection, Depends(get_connection)],
) -> OnboardingStatusResponse:
    raw_onboarding_token = request.cookies.get(onboarding_cookie_name())
    if raw_onboarding_token is None:
        raise OnboardingNotAvailableError("no onboarding cookie present on status request")
    status = resolve_invitation_onboarding_status(connection, onboarding_token=raw_onboarding_token)
    next_action, signed_in_display_name = _resolve_signed_in_context(request, connection)
    return OnboardingStatusResponse(
        campaign_display_name=status.campaign_display_name,
        invitation_expires_at=status.invitation_expires_at.isoformat(),
        onboarding_expires_at=status.onboarding_expires_at.isoformat(),
        onboarding_csrf_token=status.onboarding_csrf_token,
        next_action=next_action,
        signed_in_display_name=signed_in_display_name,
    )


class RegisterInvitedAccountRequest(BaseModel):
    login_name: str
    display_name: str = Field(min_length=1, max_length=_DISPLAY_NAME_MAX_LENGTH)
    password: str = Field(repr=False)


class RegisterInvitedAccountResponse(BaseModel):
    csrf_token: str = Field(repr=False)
    campaign_display_name: str


@router.post(
    "/campaign-invitations/onboarding/register",
    response_model=RegisterInvitedAccountResponse,
    status_code=201,
)
def register_invited_account_endpoint(
    body: RegisterInvitedAccountRequest,
    request: Request,
    response: Response,
    connection: Annotated[Connection, Depends(get_connection)],
    rate_limiter: Annotated[RateLimiter, Depends(get_token_consumption_rate_limiter)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
    _origin: Annotated[None, Depends(require_allowed_origin)],
) -> RegisterInvitedAccountResponse:
    _reject_authorization_header(request)
    if not rate_limiter.allow(resolve_client_ip(request), now=datetime.now(UTC)):
        raise RateLimitedError()

    raw_onboarding_token = request.cookies.get(onboarding_cookie_name())
    if raw_onboarding_token is None:
        raise OnboardingNotAvailableError("no onboarding cookie present on register request")
    _require_onboarding_csrf_token(request, connection, raw_onboarding_token)

    result = _register_invited_local_account_impl(
        connection,
        onboarding_token=raw_onboarding_token,
        login_name=body.login_name,
        display_name=body.display_name,
        raw_password=body.password,
        created_ip=resolve_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    record_change_log(
        connection,
        change_action_code="created",
        schema_name="security",
        table_name="users",
        record_id=result.user_id,
        entity_id=None,
        world_id=None,
        actor_user_id=result.user_id,
        correlation_id=correlation_id,
        command_name=_REGISTER_COMMAND_NAME,
        event_id=None,
    )

    response.set_cookie(
        key=session_cookie_name(),
        value=result.session.raw_session_token,
        **session_cookie_set_kwargs(),  # type: ignore[arg-type]
    )
    response.delete_cookie(key=onboarding_cookie_name(), path="/")
    return RegisterInvitedAccountResponse(
        csrf_token=result.session.csrf_token, campaign_display_name=result.campaign_display_name
    )


class CompleteOnboardingResponse(BaseModel):
    campaign_display_name: str


@router.post(
    "/campaign-invitations/onboarding/complete",
    response_model=CompleteOnboardingResponse,
    status_code=200,
)
def complete_invitation_onboarding_endpoint(
    user_id: Annotated[uuid.UUID, Depends(require_human_user_id)],
    request: Request,
    response: Response,
    connection: Annotated[Connection, Depends(get_connection)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> CompleteOnboardingResponse:
    """`require_human_user_id` (via `get_authenticated_user_id`) already
    enforces the ordinary session `X-CSRF-Token`/Origin contract for this
    `POST` — see this module's docstring, "Never auto-completes (S-1)"."""
    raw_onboarding_token = request.cookies.get(onboarding_cookie_name())
    if raw_onboarding_token is None:
        raise OnboardingNotAvailableError("no onboarding cookie present on complete request")

    result = complete_invitation_onboarding(
        connection, onboarding_token=raw_onboarding_token, user_id=user_id
    )
    record_change_log(
        connection,
        change_action_code="updated",
        schema_name="security",
        table_name="campaign_memberships",
        record_id=result.campaign_membership_id,
        entity_id=None,
        world_id=None,
        actor_user_id=user_id,
        correlation_id=correlation_id,
        command_name=_COMPLETE_COMMAND_NAME,
        event_id=None,
    )
    response.delete_cookie(key=onboarding_cookie_name(), path="/")
    return CompleteOnboardingResponse(campaign_display_name=result.campaign_display_name)


@router.post("/campaign-invitations/onboarding/cancel", status_code=204)
def cancel_invitation_onboarding_endpoint(
    request: Request,
    response: Response,
    connection: Annotated[Connection, Depends(get_connection)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
    _origin: Annotated[None, Depends(require_allowed_origin)],
) -> Response:
    del correlation_id
    raw_onboarding_token = request.cookies.get(onboarding_cookie_name())
    if raw_onboarding_token is None:
        raise OnboardingNotAvailableError("no onboarding cookie present on cancel request")
    _require_onboarding_csrf_token(request, connection, raw_onboarding_token)

    cancel_invitation_onboarding(connection, onboarding_token=raw_onboarding_token)
    response.delete_cookie(key=onboarding_cookie_name(), path="/")
    response.status_code = 204
    return response


__all__ = ["router"]
