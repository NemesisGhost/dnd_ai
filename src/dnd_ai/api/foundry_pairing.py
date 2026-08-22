"""Foundry pairing management HTTP endpoints (docs/PLAN.md §23.5 — Phase
11R workstream E): local-session-authenticated pairing-code creation and
self-service device management, the device-credential-authenticated token
endpoint, and access.manage-gated campaign device/connection
administration.

Route summary:

- `POST /campaigns/{campaign_id}/foundry/pairing-codes` — any active
  campaign member (`campaign.view`) creates a pairing code for themselves.
- `POST /foundry/pair` — a FoundryVTT client consumes a raw pairing code to
  create/confirm its connection and mint its first device credential plus
  access token (docs/PLAN.md §23.5 steps 3-4). Public, no browser cookie or
  `get_authenticated_user_id` principal — the code itself is the
  credential, the same "no session on this side" shape `/auth/activate`
  already establishes for activation tokens.
- `POST /foundry/token` — a paired device exchanges its own credential for
  a fresh access token. Not authenticated via `get_authenticated_user_id`
  at all: this parses `Authorization: FoundryDevice <device_id>.<raw_
  secret>` directly and calls `dnd_ai.commands.foundry_pairing.exchange_
  foundry_device_credential`, the same "no Foundry-device principal type
  exists" design that command's own docstring explains — a device
  credential's only valid action is this exact exchange, so there is no
  second caller a general-purpose principal type would serve.
- `GET /foundry/devices`, `DELETE /foundry/devices/{id}`, `POST /foundry/
  devices/{id}/rotate` — self-service, `require_human_user_id`-gated,
  ownership-checked by the commands layer (`expected_owner_user_id`).
- `GET /campaigns/{campaign_id}/foundry/devices`, `DELETE /campaigns/
  {campaign_id}/foundry/devices/{id}`, `DELETE /campaigns/{campaign_id}/
  foundry/connections/{id}` — `access.manage`-gated GM administration,
  campaign-checked by the commands layer (`expected_campaign_id`) so a GM
  authorized only for one campaign cannot revoke a device/connection
  belonging to a different one merely by guessing its id.

Every write here calls a command's composable `_..._impl(connection, ...)`
form (or, for `exchange_foundry_device_credential`/`revoke_foundry_device`/
`revoke_foundry_connection`, their only form — see `dnd_ai.commands.
foundry_pairing`'s own docstring) directly on the request's own `get_
connection`-provided transaction, never an `Engine`-based public wrapper
that would open a second, independent transaction per request
(docs/architecture/SYSTEM_ARCHITECTURE.md §7's "one transaction per
request").

No idempotency-key wiring: mirrors `dnd_ai.api.local_auth`'s identical
scope decision for its own account/session-management surface (as opposed
to `dnd_ai.api.campaign_invitations`'s resource-creation surface, which
does use it) — a duplicate pairing-code request creates a second,
harmless, independently-expiring code rather than corrupting state, and
revoke/rotate are already idempotent or low-risk-to-retry by construction.

Rate limiting: `POST /foundry/pair` and `POST /foundry/token` each use
their own `RateLimiter` (mirroring `dnd_ai.api.local_auth.get_token_
consumption_rate_limiter`'s singleton-plus-override shape) — the pairing
limiter keyed on client IP alone (no device id exists yet at that point),
the token limiter keyed on client IP plus device id. Defense in depth,
since both credentials are 256 bits of CSPRNG entropy and not realistically
guessable, but brute-force *attempts* against either endpoint should still
be bounded and observable the same way every other credential endpoint in
this codebase already is.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel
from sqlalchemy import Connection

from dnd_ai.commands.foundry_pairing import (
    FoundryDeviceSummary,
    _consume_foundry_pairing_code_impl,
    _create_foundry_pairing_code_impl,
    _rotate_foundry_device_impl,
    exchange_foundry_device_credential,
    list_foundry_devices,
    list_foundry_devices_for_campaign,
    revoke_foundry_connection,
    revoke_foundry_device,
)
from dnd_ai.domain.access import AccessContext
from dnd_ai.domain.rate_limit import RateLimiter

from ._shared import timeline_world_id
from .access import require_campaign_capability
from .auth import require_human_user_id
from .deps import get_connection
from .errors import RateLimitedError, UnauthorizedError

router = APIRouter(tags=["foundry_pairing"])

_CAMPAIGN_VIEW_CAPABILITY = "campaign.view"
_ACCESS_MANAGE_CAPABILITY = "access.manage"

_FOUNDRY_DEVICE_AUTH_SCHEME = "foundrydevice"
_FOUNDRY_TOKEN_RATE_LIMIT_MAX_ATTEMPTS = 20
_FOUNDRY_TOKEN_RATE_LIMIT_WINDOW = timedelta(minutes=15)
_FOUNDRY_PAIRING_RATE_LIMIT_MAX_ATTEMPTS = 20
_FOUNDRY_PAIRING_RATE_LIMIT_WINDOW = timedelta(minutes=15)

_foundry_token_rate_limiter: RateLimiter | None = None
_foundry_pairing_rate_limiter: RateLimiter | None = None


def get_foundry_token_rate_limiter() -> RateLimiter:
    global _foundry_token_rate_limiter
    if _foundry_token_rate_limiter is None:
        _foundry_token_rate_limiter = RateLimiter(
            max_attempts=_FOUNDRY_TOKEN_RATE_LIMIT_MAX_ATTEMPTS,
            window=_FOUNDRY_TOKEN_RATE_LIMIT_WINDOW,
        )
    return _foundry_token_rate_limiter


def get_foundry_pairing_rate_limiter() -> RateLimiter:
    global _foundry_pairing_rate_limiter
    if _foundry_pairing_rate_limiter is None:
        _foundry_pairing_rate_limiter = RateLimiter(
            max_attempts=_FOUNDRY_PAIRING_RATE_LIMIT_MAX_ATTEMPTS,
            window=_FOUNDRY_PAIRING_RATE_LIMIT_WINDOW,
        )
    return _foundry_pairing_rate_limiter


def _client_ip(request: Request) -> str:
    """Same `request.client.host`-only shape, and the same known reverse-
    proxy-topology deviation, as `dnd_ai.api.local_auth._client_ip`."""
    return request.client.host if request.client is not None else "unknown"


def _device_summary_response(summary: FoundryDeviceSummary) -> "FoundryDeviceResponse":
    return FoundryDeviceResponse(
        foundry_device_id=summary.foundry_device_id,
        foundry_connection_id=summary.foundry_connection_id,
        user_id=summary.user_id,
        campaign_id=summary.campaign_id,
        external_system_id=summary.external_system_id,
        foundry_user_id=summary.foundry_user_id,
        device_label=summary.device_label,
        granted_scopes=list(summary.granted_scopes),
        created_at=summary.created_at.isoformat(),
        last_used_at=summary.last_used_at.isoformat() if summary.last_used_at is not None else None,
        expires_at=summary.expires_at.isoformat(),
        is_revoked=summary.is_revoked,
    )


# ---------------------------------------------------------------------------
# Pairing-code creation (any active campaign member)
# ---------------------------------------------------------------------------


class CreatePairingCodeRequest(BaseModel):
    external_system_id: uuid.UUID
    requested_scopes: list[str]


class CreatePairingCodeResponse(BaseModel):
    foundry_pairing_code_id: uuid.UUID
    raw_code: str
    requested_scopes: list[str]
    expires_at: str


@router.post(
    "/campaigns/{campaign_id}/foundry/pairing-codes",
    response_model=CreatePairingCodeResponse,
    status_code=201,
)
def create_foundry_pairing_code_endpoint(
    campaign_id: uuid.UUID,
    body: CreatePairingCodeRequest,
    access: Annotated[
        AccessContext, Depends(require_campaign_capability(_CAMPAIGN_VIEW_CAPABILITY))
    ],
    connection: Annotated[Connection, Depends(get_connection)],
) -> CreatePairingCodeResponse:
    """docs/PLAN.md §23.5 steps 1-2: any active campaign member — not only
    a GM — creates a pairing code for their own use, scoped to `campaign_
    id`'s own world via `expected_world_id`."""
    result = _create_foundry_pairing_code_impl(
        connection,
        requesting_user_id=access.user_id,
        campaign_id=campaign_id,
        external_system_id=body.external_system_id,
        requested_scopes=set(body.requested_scopes),
        expected_world_id=timeline_world_id(connection, access.timeline_id),
    )
    return CreatePairingCodeResponse(
        foundry_pairing_code_id=result.foundry_pairing_code_id,
        raw_code=result.raw_code,
        requested_scopes=list(result.requested_scopes),
        expires_at=result.expires_at.isoformat(),
    )


# ---------------------------------------------------------------------------
# Pairing-code consumption (docs/PLAN.md §23.5 steps 3-4) — public, no
# get_authenticated_user_id principal; the raw code is the credential.
# ---------------------------------------------------------------------------


class ConsumeFoundryPairingCodeRequest(BaseModel):
    raw_code: str
    foundry_user_id: str
    foundry_origin: str
    device_label: str
    module_version: str | None = None
    foundry_version: str | None = None


class ConsumeFoundryPairingCodeResponse(BaseModel):
    foundry_connection_id: uuid.UUID
    foundry_device_id: uuid.UUID
    raw_device_secret: str
    raw_access_token: str
    campaign_id: uuid.UUID
    external_system_id: uuid.UUID
    granted_scopes: list[str]
    device_expires_at: str
    access_token_expires_at: str


@router.post("/foundry/pair", response_model=ConsumeFoundryPairingCodeResponse, status_code=201)
def consume_foundry_pairing_code_endpoint(
    body: ConsumeFoundryPairingCodeRequest,
    request: Request,
    connection: Annotated[Connection, Depends(get_connection)],
    rate_limiter: Annotated[RateLimiter, Depends(get_foundry_pairing_rate_limiter)],
) -> ConsumeFoundryPairingCodeResponse:
    """The FoundryVTT module's own "enter the pairing code" step
    (docs/PLAN.md §23.5 steps 3-4): consumes `body.raw_code`, creates or
    confirms the connection, and mints the first device credential plus
    access token — all three returned exactly once, never persisted or
    logged raw anywhere past this response. Rate-limited by client IP alone
    (no device id exists yet at this point, unlike `/foundry/token`)."""
    if not rate_limiter.allow(_client_ip(request), now=datetime.now(UTC)):
        raise RateLimitedError()
    result = _consume_foundry_pairing_code_impl(
        connection,
        raw_code=body.raw_code,
        foundry_user_id=body.foundry_user_id,
        foundry_origin=body.foundry_origin,
        device_label=body.device_label,
        module_version=body.module_version,
        foundry_version=body.foundry_version,
    )
    rate_limiter.reset(_client_ip(request))
    return ConsumeFoundryPairingCodeResponse(
        foundry_connection_id=result.foundry_connection_id,
        foundry_device_id=result.foundry_device_id,
        raw_device_secret=result.raw_device_secret,
        raw_access_token=result.raw_access_token,
        campaign_id=result.campaign_id,
        external_system_id=result.external_system_id,
        granted_scopes=list(result.granted_scopes),
        device_expires_at=result.device_expires_at.isoformat(),
        access_token_expires_at=result.access_token_expires_at.isoformat(),
    )


# ---------------------------------------------------------------------------
# Device-credential token exchange (docs/PLAN.md §23.5 step 6)
# ---------------------------------------------------------------------------


class FoundryTokenResponse(BaseModel):
    raw_access_token: str
    expires_at: str
    campaign_id: uuid.UUID
    foundry_connection_id: uuid.UUID
    foundry_device_id: uuid.UUID
    granted_scopes: list[str]


@router.post("/foundry/token", response_model=FoundryTokenResponse, status_code=200)
def foundry_token_endpoint(
    request: Request,
    connection: Annotated[Connection, Depends(get_connection)],
    rate_limiter: Annotated[RateLimiter, Depends(get_foundry_token_rate_limiter)],
    authorization: Annotated[str | None, Header()] = None,
) -> FoundryTokenResponse:
    """`Authorization: FoundryDevice <device_id>.<raw_secret>` only —
    never a browser cookie, matching docs/PLAN.md §23.5's "Pairing/token
    endpoints accept no browser cookie as authorization except where
    explicitly creating/managing the pairing from the same-origin portal."
    Every failure mode raises the identical `UnauthorizedError`, mirroring
    `exchange_foundry_device_credential`'s own uniform, non-disclosing
    `None` contract one layer down."""
    scheme, _, credential = (authorization or "").partition(" ")
    if scheme.lower() != _FOUNDRY_DEVICE_AUTH_SCHEME:
        raise UnauthorizedError()
    device_id_text, separator, raw_secret = credential.partition(".")
    if not separator or not raw_secret:
        raise UnauthorizedError()
    try:
        foundry_device_id = uuid.UUID(device_id_text)
    except ValueError as exc:
        raise UnauthorizedError() from exc

    rate_limit_key = f"{_client_ip(request)}:{foundry_device_id}"
    if not rate_limiter.allow(rate_limit_key, now=datetime.now(UTC)):
        raise RateLimitedError()

    exchanged = exchange_foundry_device_credential(
        connection, foundry_device_id=foundry_device_id, raw_device_secret=raw_secret
    )
    if exchanged is None:
        raise UnauthorizedError()
    rate_limiter.reset(rate_limit_key)

    return FoundryTokenResponse(
        raw_access_token=exchanged.raw_access_token,
        expires_at=exchanged.expires_at.isoformat(),
        campaign_id=exchanged.campaign_id,
        foundry_connection_id=exchanged.foundry_connection_id,
        foundry_device_id=exchanged.foundry_device_id,
        granted_scopes=list(exchanged.granted_scopes),
    )


# ---------------------------------------------------------------------------
# Self-service device management
# ---------------------------------------------------------------------------


class FoundryDeviceResponse(BaseModel):
    foundry_device_id: uuid.UUID
    foundry_connection_id: uuid.UUID
    user_id: uuid.UUID
    campaign_id: uuid.UUID
    external_system_id: uuid.UUID
    foundry_user_id: str
    device_label: str
    granted_scopes: list[str]
    created_at: str
    last_used_at: str | None
    expires_at: str
    is_revoked: bool


@router.get("/foundry/devices", response_model=list[FoundryDeviceResponse], status_code=200)
def list_own_foundry_devices_endpoint(
    user_id: Annotated[uuid.UUID, Depends(require_human_user_id)],
    connection: Annotated[Connection, Depends(get_connection)],
) -> list[FoundryDeviceResponse]:
    return [_device_summary_response(s) for s in list_foundry_devices(connection, user_id=user_id)]


@router.delete("/foundry/devices/{foundry_device_id}", status_code=204)
def revoke_own_foundry_device_endpoint(
    foundry_device_id: uuid.UUID,
    user_id: Annotated[uuid.UUID, Depends(require_human_user_id)],
    connection: Annotated[Connection, Depends(get_connection)],
) -> None:
    revoke_foundry_device(
        connection,
        foundry_device_id=foundry_device_id,
        revoked_by_user_id=user_id,
        expected_owner_user_id=user_id,
    )


class RotateFoundryDeviceRequest(BaseModel):
    overlap_seconds: int | None = None


class RotateFoundryDeviceResponse(BaseModel):
    old_foundry_device_id: uuid.UUID
    new_foundry_device_id: uuid.UUID
    raw_device_secret: str
    expires_at: str
    old_device_revoked_at: str


@router.post(
    "/foundry/devices/{foundry_device_id}/rotate",
    response_model=RotateFoundryDeviceResponse,
    status_code=200,
)
def rotate_own_foundry_device_endpoint(
    foundry_device_id: uuid.UUID,
    body: RotateFoundryDeviceRequest,
    user_id: Annotated[uuid.UUID, Depends(require_human_user_id)],
    connection: Annotated[Connection, Depends(get_connection)],
) -> RotateFoundryDeviceResponse:
    overlap = timedelta(seconds=body.overlap_seconds) if body.overlap_seconds is not None else None
    result = _rotate_foundry_device_impl(
        connection, foundry_device_id=foundry_device_id, requesting_user_id=user_id, overlap=overlap
    )
    return RotateFoundryDeviceResponse(
        old_foundry_device_id=result.old_foundry_device_id,
        new_foundry_device_id=result.new_foundry_device_id,
        raw_device_secret=result.raw_device_secret,
        expires_at=result.expires_at.isoformat(),
        old_device_revoked_at=result.old_device_revoked_at.isoformat(),
    )


# ---------------------------------------------------------------------------
# GM campaign administration (access.manage)
# ---------------------------------------------------------------------------


@router.get(
    "/campaigns/{campaign_id}/foundry/devices",
    response_model=list[FoundryDeviceResponse],
    status_code=200,
)
def list_campaign_foundry_devices_endpoint(
    # campaign_id is required in the signature to bind the URL's own path
    # parameter (require_campaign_capability's own dependency already
    # consumes it for authorization); this route uses access.campaign_id
    # instead of this one directly, since the two are always equal once
    # require_campaign_capability has already succeeded.
    campaign_id: uuid.UUID,  # noqa: ARG001
    access: Annotated[
        AccessContext, Depends(require_campaign_capability(_ACCESS_MANAGE_CAPABILITY))
    ],
    connection: Annotated[Connection, Depends(get_connection)],
) -> list[FoundryDeviceResponse]:
    return [
        _device_summary_response(s)
        for s in list_foundry_devices_for_campaign(connection, campaign_id=access.campaign_id)
    ]


@router.delete("/campaigns/{campaign_id}/foundry/devices/{foundry_device_id}", status_code=204)
def revoke_campaign_foundry_device_endpoint(
    campaign_id: uuid.UUID,  # noqa: ARG001 — binds the URL path; see list_campaign_foundry_devices_endpoint's comment
    foundry_device_id: uuid.UUID,
    access: Annotated[
        AccessContext, Depends(require_campaign_capability(_ACCESS_MANAGE_CAPABILITY))
    ],
    connection: Annotated[Connection, Depends(get_connection)],
) -> None:
    revoke_foundry_device(
        connection,
        foundry_device_id=foundry_device_id,
        revoked_by_user_id=access.user_id,
        expected_campaign_id=access.campaign_id,
    )


@router.delete(
    "/campaigns/{campaign_id}/foundry/connections/{foundry_connection_id}", status_code=204
)
def revoke_campaign_foundry_connection_endpoint(
    campaign_id: uuid.UUID,  # noqa: ARG001 — binds the URL path; see list_campaign_foundry_devices_endpoint's comment
    foundry_connection_id: uuid.UUID,
    access: Annotated[
        AccessContext, Depends(require_campaign_capability(_ACCESS_MANAGE_CAPABILITY))
    ],
    connection: Annotated[Connection, Depends(get_connection)],
) -> None:
    revoke_foundry_connection(
        connection,
        foundry_connection_id=foundry_connection_id,
        revoked_by_user_id=access.user_id,
        expected_campaign_id=access.campaign_id,
    )
