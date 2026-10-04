"""Single-link campaign-invitation onboarding (Phase 13E checkpoint 8a).

`security.invitation_onboarding_sessions` (migration 107) backs a visitor
who opens an invitation link with no account yet: `begin_invitation_
onboarding` validates the raw invitation token and opens a short-lived,
cookie-carried onboarding session; `register_invited_local_account`
(`dnd_ai.commands.local_auth`, not this module — it composes that module's
own account-creation/activation primitives) or `complete_invitation_
onboarding` below then binds that session's invitation to a real account,
in each case behind an explicit, human-initiated POST — this flow never
completes automatically on a `GET` (see `PHASE13E_REMAINING_
IMPLEMENTATION_PLAN.md` §7.1 S-1: "one-click cross-site campaign join /
confused deputy").

## Token handling

`onboarding_token_hash` is the only thing ever persisted for the
onboarding token itself — the same `dnd_ai.domain.credentials.
generate_opaque_secret`/`hash_opaque_secret` shape every other
server-issued opaque credential in this codebase already uses. The raw
*invitation* token is never stored anywhere, including here: this table
only references `campaign_invitation_id`, the row `dnd_ai.commands.
campaign_invitations.create_campaign_invitation` already created and whose
own `invitation_token_hash` already covers that token.

## Lock order

`invitation_onboarding_sessions` -> `campaign_invitations` ->
`campaign_memberships` -> `users`, matching `PHASE13E_REMAINING_
IMPLEMENTATION_PLAN.md` §6.2/§8.1's documented ordering. `begin_invitation_
onboarding` takes no lock on the invitation row at all (P-1): it is a
read-only validation, and holding that lock across a human-paced flow
would block a GM's concurrent revoke. `_lock_and_validate_onboarding_
session` (used by `register`/`complete`/`cancel`) locks both rows `FOR
UPDATE`, in that order, so a concurrent revoke landing between `begin` and
`complete` correctly wins.

## Rejection semantics

Every rejection reason — a token that never existed, one already consumed
or cancelled, one whose window has expired, or one whose underlying
invitation is now revoked, expired, or already accepted by someone else —
collapses into a single `OnboardingNotAvailableError`, mirroring `dnd_ai.
commands.campaign_invitations.InvitationNotAcceptableError`'s identical
reasoning: a caller must never be able to distinguish these causes from
the response alone.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import Connection, RowMapping, text

from dnd_ai.domain.credentials import generate_opaque_secret, hash_opaque_secret
from dnd_ai.domain.errors import DomainAuthorizationError

from .campaign_invitations import (
    AcceptCampaignInvitationResult,
    _accept_locked_invitation,
    _hash_invitation_token,
)

_ONBOARDING_SESSION_TTL = timedelta(minutes=20)


class OnboardingNotAvailableError(DomainAuthorizationError):
    """Raised by every function in this module for an onboarding token (or,
    for `begin_invitation_onboarding`, an invitation token) that does not
    resolve to something currently usable — nonexistent, consumed,
    cancelled, expired, or backed by an invitation that is now revoked,
    expired, or accepted by someone else — all indistinguishably. See this
    module's docstring for why a bearer-token rejection must never vary by
    cause."""


def _hash_onboarding_token(token: str) -> str:
    return hash_opaque_secret(token)


@dataclass(frozen=True)
class BeginInvitationOnboardingResult:
    invitation_onboarding_session_id: uuid.UUID
    raw_onboarding_token: str
    onboarding_csrf_token: str
    campaign_display_name: str
    invitation_expires_at: datetime
    onboarding_expires_at: datetime


def _cancel_existing_onboarding_session(
    connection: Connection, *, raw_onboarding_token: str
) -> None:
    """Best-effort replacement of a pre-existing live onboarding session
    for the same browser (S-2: "start must replace any pre-existing live
    onboarding session for the same browser (delete-then-set, never
    merge)"). Deliberately not locked and not an error if the row is
    missing or already terminal — this is a courtesy cleanup, not a
    validated operation; the caller is about to create a brand-new session
    regardless of this statement's outcome."""
    connection.execute(
        text("""
            UPDATE security.invitation_onboarding_sessions
            SET cancelled_at = now()
            WHERE onboarding_token_hash = :hash
              AND consumed_at IS NULL AND cancelled_at IS NULL
        """),
        {"hash": _hash_onboarding_token(raw_onboarding_token)},
    )


def begin_invitation_onboarding(
    connection: Connection,
    *,
    invitation_token: str,
    existing_onboarding_token: str | None = None,
    created_ip: str | None = None,
) -> BeginInvitationOnboardingResult:
    """Validates `invitation_token` (read-only, no row lock — see this
    module's docstring, "Lock order") and opens a new onboarding session
    for it. `existing_onboarding_token`, when given, is the *previous*
    onboarding cookie's raw value (if any) for the same browser; it is
    replaced, never reused or merged, before the new session is created
    (S-2)."""
    invitation_token_hash = _hash_invitation_token(invitation_token)

    invitation = (
        connection.execute(
            text("""
                SELECT ci.campaign_invitation_id, ci.campaign_id, ci.accepted_by_user_id,
                       ci.revoked_at, (ci.expires_at <= now()) AS expired, ci.expires_at,
                       c.name AS campaign_display_name, cls.code AS campaign_status
                FROM security.campaign_invitations ci
                JOIN campaign.campaigns c ON c.campaign_id = ci.campaign_id
                JOIN core.lifecycle_statuses cls ON cls.lifecycle_status_id = c.lifecycle_status_id
                WHERE ci.invitation_token_hash = :hash
            """),
            {"hash": invitation_token_hash},
        )
        .mappings()
        .one_or_none()
    )
    if (
        invitation is None
        or invitation["accepted_by_user_id"] is not None
        or invitation["revoked_at"] is not None
        or invitation["expired"]
        or invitation["campaign_status"] in ("archived", "deleted")
    ):
        raise OnboardingNotAvailableError(
            f"invitation token hash {invitation_token_hash} is not onboardable "
            f"(row={invitation is not None})"
        )

    if existing_onboarding_token is not None:
        _cancel_existing_onboarding_session(
            connection, raw_onboarding_token=existing_onboarding_token
        )

    now = datetime.now(UTC)
    # P-7: the invitation's own unexpiry is already proven above, before
    # this window is ever computed, so this can only be non-positive from
    # clock skew within a single statement's own now() — the CHECK
    # constraint (ck_ios_expires_after_created) is a defensive backstop,
    # not the expected path.
    onboarding_expires_at = min(now + _ONBOARDING_SESSION_TTL, invitation["expires_at"])
    if onboarding_expires_at <= now:
        raise OnboardingNotAvailableError(
            f"invitation {invitation['campaign_invitation_id']} leaves no positive "
            "onboarding window"
        )

    raw_onboarding_token = generate_opaque_secret()
    onboarding_csrf_token = generate_opaque_secret()
    invitation_onboarding_session_id = connection.execute(
        text("""
            INSERT INTO security.invitation_onboarding_sessions
                (onboarding_token_hash, campaign_invitation_id, csrf_token, expires_at,
                 created_ip)
            VALUES (:hash, :invitation, :csrf, :expires_at, :ip)
            RETURNING invitation_onboarding_session_id
        """),
        {
            "hash": _hash_onboarding_token(raw_onboarding_token),
            "invitation": invitation["campaign_invitation_id"],
            "csrf": onboarding_csrf_token,
            "expires_at": onboarding_expires_at,
            "ip": created_ip,
        },
    ).scalar()
    assert isinstance(invitation_onboarding_session_id, uuid.UUID)

    return BeginInvitationOnboardingResult(
        invitation_onboarding_session_id=invitation_onboarding_session_id,
        raw_onboarding_token=raw_onboarding_token,
        onboarding_csrf_token=onboarding_csrf_token,
        campaign_display_name=str(invitation["campaign_display_name"]),
        invitation_expires_at=invitation["expires_at"],
        onboarding_expires_at=onboarding_expires_at,
    )


@dataclass(frozen=True)
class OnboardingStatusView:
    campaign_display_name: str
    invitation_expires_at: datetime
    onboarding_expires_at: datetime
    onboarding_csrf_token: str


@dataclass(frozen=True)
class _LockedOnboardingSession:
    invitation_onboarding_session_id: uuid.UUID
    campaign_invitation_id: uuid.UUID
    campaign_id: uuid.UUID
    campaign_display_name: str
    invitation_expires_at: datetime
    onboarding_expires_at: datetime
    onboarding_csrf_token: str


def _select_onboarding_session_sql(*, lock: bool) -> str:
    return f"""
        SELECT ios.invitation_onboarding_session_id, ios.campaign_invitation_id,
               ios.consumed_at, ios.cancelled_at, ios.expires_at AS onboarding_expires_at,
               ios.csrf_token AS onboarding_csrf_token,
               ci.campaign_id, ci.accepted_by_user_id, ci.revoked_at,
               (ci.expires_at <= now()) AS invitation_expired, ci.expires_at AS invitation_expires_at,
               c.name AS campaign_display_name, cls.code AS campaign_status
        FROM security.invitation_onboarding_sessions ios
        JOIN security.campaign_invitations ci ON ci.campaign_invitation_id = ios.campaign_invitation_id
        JOIN campaign.campaigns c ON c.campaign_id = ci.campaign_id
        JOIN core.lifecycle_statuses cls ON cls.lifecycle_status_id = c.lifecycle_status_id
        WHERE ios.onboarding_token_hash = :hash
        {"FOR UPDATE OF ios, ci" if lock else ""}
    """


def resolve_invitation_onboarding_status(
    connection: Connection, *, onboarding_token: str
) -> OnboardingStatusView:
    """Read-only status check (no row lock) for `GET .../status`."""
    row = (
        connection.execute(
            text(_select_onboarding_session_sql(lock=False)),
            {"hash": _hash_onboarding_token(onboarding_token)},
        )
        .mappings()
        .one_or_none()
    )
    session = _validate_onboarding_row(
        row, onboarding_token_hash=_hash_onboarding_token(onboarding_token)
    )
    return OnboardingStatusView(
        campaign_display_name=session.campaign_display_name,
        invitation_expires_at=session.invitation_expires_at,
        onboarding_expires_at=session.onboarding_expires_at,
        onboarding_csrf_token=session.onboarding_csrf_token,
    )


def _validate_onboarding_row(
    row: RowMapping | None, *, onboarding_token_hash: str
) -> _LockedOnboardingSession:
    if row is None:
        raise OnboardingNotAvailableError(
            f"onboarding token hash {onboarding_token_hash} does not resolve to any session"
        )
    if (
        row["consumed_at"] is not None
        or row["cancelled_at"] is not None
        or row["onboarding_expires_at"] <= datetime.now(UTC)
        or row["accepted_by_user_id"] is not None
        or row["revoked_at"] is not None
        or row["invitation_expired"]
        or row["campaign_status"] in ("archived", "deleted")
    ):
        raise OnboardingNotAvailableError(
            f"onboarding session {row['invitation_onboarding_session_id']} is not consumable"
        )
    return _LockedOnboardingSession(
        invitation_onboarding_session_id=row["invitation_onboarding_session_id"],
        campaign_invitation_id=row["campaign_invitation_id"],
        campaign_id=row["campaign_id"],
        campaign_display_name=str(row["campaign_display_name"]),
        invitation_expires_at=row["invitation_expires_at"],
        onboarding_expires_at=row["onboarding_expires_at"],
        onboarding_csrf_token=str(row["onboarding_csrf_token"]),
    )


def _lock_and_validate_onboarding_session(
    connection: Connection, *, onboarding_token: str
) -> _LockedOnboardingSession:
    """Locks both the onboarding-session row and its referenced invitation
    row `FOR UPDATE`, in that order (this module's docstring, "Lock
    order"), then validates both. Used by `register`/`complete` — never by
    `begin`/`status`, which must not take these locks (P-1)."""
    onboarding_token_hash = _hash_onboarding_token(onboarding_token)
    row = (
        connection.execute(
            text(_select_onboarding_session_sql(lock=True)),
            {"hash": onboarding_token_hash},
        )
        .mappings()
        .one_or_none()
    )
    return _validate_onboarding_row(row, onboarding_token_hash=onboarding_token_hash)


def _mark_onboarding_session_consumed(
    connection: Connection,
    *,
    invitation_onboarding_session_id: uuid.UUID,
    consumed_by_user_id: uuid.UUID,
) -> None:
    connection.execute(
        text("""
            UPDATE security.invitation_onboarding_sessions
            SET consumed_at = now(), consumed_by_user_id = :user
            WHERE invitation_onboarding_session_id = :session
        """),
        {"user": consumed_by_user_id, "session": invitation_onboarding_session_id},
    )


def accept_locked_onboarding_invitation(
    connection: Connection, *, session: "_LockedOnboardingSession", accepting_user_id: uuid.UUID
) -> AcceptCampaignInvitationResult:
    """Exposed for `dnd_ai.commands.local_auth._register_invited_local_
    account_impl`, which must lock and validate the onboarding session
    itself (before the account it will accept on behalf of even exists),
    then call this to accept the already-locked invitation and mark the
    session consumed, all inside the same registration transaction."""
    result = _accept_locked_invitation(
        connection,
        campaign_invitation_id=session.campaign_invitation_id,
        campaign_id=session.campaign_id,
        accepting_user_id=accepting_user_id,
    )
    _mark_onboarding_session_consumed(
        connection,
        invitation_onboarding_session_id=session.invitation_onboarding_session_id,
        consumed_by_user_id=accepting_user_id,
    )
    return result


@dataclass(frozen=True)
class CompleteInvitationOnboardingResult:
    campaign_id: uuid.UUID
    campaign_membership_id: uuid.UUID
    campaign_display_name: str


def complete_invitation_onboarding(
    connection: Connection, *, onboarding_token: str, user_id: uuid.UUID
) -> CompleteInvitationOnboardingResult:
    """The explicit, human-initiated confirm step for a visitor who is
    already signed in as some account (`PHASE13E_REMAINING_IMPLEMENTATION_
    PLAN.md` §7.1 S-1/S-4): binds the onboarding session's invitation to
    `user_id`, whichever account the caller's own current session names —
    never a caller-supplied identity. Idempotent only in the sense that a
    second call with the *same* onboarding token fails generically (the
    session is already consumed) rather than erroring loudly — see this
    module's docstring."""
    session = _lock_and_validate_onboarding_session(connection, onboarding_token=onboarding_token)
    result = accept_locked_onboarding_invitation(
        connection, session=session, accepting_user_id=user_id
    )
    return CompleteInvitationOnboardingResult(
        campaign_id=result.campaign_id,
        campaign_membership_id=result.campaign_membership_id,
        campaign_display_name=session.campaign_display_name,
    )


@dataclass(frozen=True)
class CancelInvitationOnboardingResult:
    cancelled: bool


def cancel_invitation_onboarding(
    connection: Connection, *, onboarding_token: str
) -> CancelInvitationOnboardingResult:
    """Explicit visitor-initiated cancellation. Locks only the onboarding-
    session row (no invitation lock needed — nothing about the invitation
    itself changes). An already-consumed or already-cancelled session is a
    documented no-op (`cancelled=False`), never an error — matching
    `dnd_ai.commands.campaign_invitations.revoke_campaign_invitation`'s
    identical "already revoked is a success/no-op" shape."""
    onboarding_token_hash = _hash_onboarding_token(onboarding_token)
    row = (
        connection.execute(
            text("""
                SELECT invitation_onboarding_session_id, consumed_at, cancelled_at
                FROM security.invitation_onboarding_sessions
                WHERE onboarding_token_hash = :hash
                FOR UPDATE
            """),
            {"hash": onboarding_token_hash},
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise OnboardingNotAvailableError(
            f"onboarding token hash {onboarding_token_hash} does not resolve to any session"
        )
    if row["consumed_at"] is not None or row["cancelled_at"] is not None:
        return CancelInvitationOnboardingResult(cancelled=False)
    connection.execute(
        text("""
            UPDATE security.invitation_onboarding_sessions
            SET cancelled_at = now()
            WHERE invitation_onboarding_session_id = :session
        """),
        {"session": row["invitation_onboarding_session_id"]},
    )
    return CancelInvitationOnboardingResult(cancelled=True)


__all__ = [
    "OnboardingNotAvailableError",
    "BeginInvitationOnboardingResult",
    "begin_invitation_onboarding",
    "OnboardingStatusView",
    "resolve_invitation_onboarding_status",
    "CompleteInvitationOnboardingResult",
    "complete_invitation_onboarding",
    "CancelInvitationOnboardingResult",
    "cancel_invitation_onboarding",
    "accept_locked_onboarding_invitation",
]
