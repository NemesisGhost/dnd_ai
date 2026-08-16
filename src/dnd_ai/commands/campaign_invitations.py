"""Campaign-invitation token acceptance flow (docs/PLAN.md Phase 10 "Still
to come": "the invitation-token acceptance flow deferred at workstream
20"). `security.campaign_invitations` (migration 080) "tracks an
invitation without pre-creating a durable membership for an unknown
recipient" (that table's own comment) — only a token hash is retained, and
acceptance is documented there as idempotent.

Sibling to `dnd_ai.commands.memberships` (campaign_memberships/roles) and
`dnd_ai.commands.campaigns` (campaign creation) rather than folded into
either: `create_campaign_invitation` is an ordinary `access.manage`-gated
write over an already-existing, already-authorized campaign (like every
`dnd_ai.commands.memberships` command); `accept_campaign_invitation` is not
campaign-scoped at all — the caller has only a bearer token, the same
shape `dnd_ai.commands.campaigns.create_campaign` already established for
"the one write with no `campaign_id` to authorize against yet."

## Token handling

`invitation_token_hash` is the only thing ever persisted. `create_campaign_
invitation` generates a `secrets.token_urlsafe()` value (256 bits of
entropy from `secrets`, the stdlib's CSPRNG — never `random`) and returns
the raw token to its one caller (`dnd_ai.api.campaign_invitations`)
exactly once; only its sha256 hex digest is ever written to the database
or logged. There is deliberately no email-delivery step — mirroring
`dnd_ai.commands.memberships`'s own "needs an email-delivery mechanism
this application has no other use for yet" reasoning for why `security.
campaign_invitations` itself was left out of that workstream — so the API
layer returns the raw token directly in the response body for an
out-of-band operator to deliver, applying that same scoping decision to
the one remaining piece of that deliverable.

A plain sha256 digest (not a salted/slow hash like bcrypt/argon2) is
appropriate here, unlike a user password: the input is 256 bits of
CSPRNG-generated entropy, not attacker-guessable low-entropy text, so a
fast hash's usual weakness (brute-forcing weak inputs) does not apply —
this mirrors how `dnd_ai.api.idempotency`/`dnd_ai.api.correlation` already
treat other server-generated random values in this codebase.

## Acceptance semantics

`accept_campaign_invitation` folds every rejection reason — a token that
never existed, one already revoked, one past `expires_at`, and one already
accepted by a *different* user — into a single `InvitationNotAcceptableError`
(a `DomainAuthorizationError`, fixed non-disclosing 404), mirroring `dnd_ai.
domain.errors.AuthenticationError`'s own explicit reasoning for never
varying a token-rejection message by cause: telling a caller *which* of
those is true would help an attacker iterate over guessed or stolen
tokens. Re-accepting the *same* token as the user who already accepted it
is the one case that is not rejected — the table's own comment documents
acceptance as idempotent — and returns the same membership id without
writing anything a second time.

Accepting activates (or creates) exactly one `security.campaign_
memberships` row for `(campaign_id, accepting_user_id)`: an existing
*open* membership for that pair is reused as-is; an existing *closed* one
(a member who departed and is being re-invited) is reactivated (`ended_at`/
`ended_by_membership_id` cleared, status reset to active) rather than
creating a second row, which `ux_campaign_memberships_open` would reject
anyway; only when neither exists is a fresh row created. No
idempotency-key store is needed for this command: unlike `dnd_ai.commands.
campaigns.create_campaign` (which has no natural dedup key and is
genuinely non-idempotent on retry, by that module's own documented
limitation), accepting the *same* token twice is already a defined no-op
by construction.
"""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import Connection, text

from dnd_ai.domain.errors import DomainAuthorizationError

from ._shared import lookup_id

_INVITATION_TOKEN_ENTROPY_BYTES = 32
_DEFAULT_INVITATION_TTL = timedelta(days=7)
_ACTIVE_MEMBERSHIP_STATUS_CODE = "active"


class InvitationNotAcceptableError(DomainAuthorizationError):
    """Raised by `accept_campaign_invitation()` for a token that does not
    resolve to an acceptable invitation — nonexistent, revoked, expired, or
    already accepted by a different user — all indistinguishably. See this
    module's docstring for why: a bearer token's rejection reason must
    never vary by cause, the same principle `dnd_ai.domain.errors.
    AuthenticationError` already applies to OIDC bearer tokens. The
    constructor's `detail` argument (`str(self)`) is for local debugging
    only, never `safe_message`."""


def _hash_invitation_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CreateCampaignInvitationResult:
    campaign_invitation_id: uuid.UUID
    token: str


def create_campaign_invitation(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    invited_by_membership_id: uuid.UUID,
    invited_email: str | None = None,
    ttl: timedelta = _DEFAULT_INVITATION_TTL,
) -> CreateCampaignInvitationResult:
    """Creates a `security.campaign_invitations` row and returns its raw,
    single-use token (never stored). `invited_by_membership_id` is trusted
    as already belonging to `campaign_id` — like `dnd_ai.commands.
    memberships.assign_membership_role`'s identical `granted_by_
    membership_id` argument, callers always pass the caller's own resolved
    `AccessContext.campaign_membership_id`, so it is same-campaign by
    construction and `security.enforce_campaign_invitation_actor_scope()`
    (migration 080) is never reached with a mismatch."""
    token = secrets.token_urlsafe(_INVITATION_TOKEN_ENTROPY_BYTES)
    token_hash = _hash_invitation_token(token)
    campaign_invitation_id = connection.execute(
        text("""
            INSERT INTO security.campaign_invitations
                (campaign_id, invited_email, invitation_token_hash, invited_by_membership_id,
                 expires_at)
            VALUES (:campaign, :email, :hash, :invited_by, now() + :ttl)
            RETURNING campaign_invitation_id
        """),
        {
            "campaign": campaign_id,
            "email": invited_email,
            "hash": token_hash,
            "invited_by": invited_by_membership_id,
            "ttl": ttl,
        },
    ).scalar()
    assert isinstance(campaign_invitation_id, uuid.UUID)
    return CreateCampaignInvitationResult(
        campaign_invitation_id=campaign_invitation_id, token=token
    )


@dataclass(frozen=True)
class AcceptCampaignInvitationResult:
    campaign_id: uuid.UUID
    campaign_membership_id: uuid.UUID


def _activate_or_create_membership(
    connection: Connection, *, campaign_id: uuid.UUID, user_id: uuid.UUID
) -> uuid.UUID:
    existing = (
        connection.execute(
            text("""
                SELECT campaign_membership_id, ended_at
                FROM security.campaign_memberships
                WHERE campaign_id = :campaign AND user_id = :user
                ORDER BY created_at DESC
                LIMIT 1
                FOR UPDATE
            """),
            {"campaign": campaign_id, "user": user_id},
        )
        .mappings()
        .one_or_none()
    )

    if existing is not None and existing["ended_at"] is None:
        # Already an open member — accepting is a no-op on the membership
        # itself.
        membership_id = existing["campaign_membership_id"]
        assert isinstance(membership_id, uuid.UUID)
        return membership_id

    active_membership_status_id = lookup_id(
        connection,
        "security",
        "membership_statuses",
        "membership_status_id",
        _ACTIVE_MEMBERSHIP_STATUS_CODE,
    )

    if existing is None:
        membership_id = connection.execute(
            text("""
                INSERT INTO security.campaign_memberships
                    (campaign_id, user_id, membership_status_id, joined_at)
                VALUES (:campaign, :user, :status, now())
                RETURNING campaign_membership_id
            """),
            {"campaign": campaign_id, "user": user_id, "status": active_membership_status_id},
        ).scalar()
        assert isinstance(membership_id, uuid.UUID)
        return membership_id

    # A closed (departed/revoked) membership already exists — reactivate it
    # rather than insert a second row, which ux_campaign_memberships_open
    # would reject anyway.
    connection.execute(
        text("""
            UPDATE security.campaign_memberships
            SET ended_at = NULL, ended_by_membership_id = NULL,
                membership_status_id = :status, updated_at = now()
            WHERE campaign_membership_id = :membership
        """),
        {
            "status": active_membership_status_id,
            "membership": existing["campaign_membership_id"],
        },
    )
    membership_id = existing["campaign_membership_id"]
    assert isinstance(membership_id, uuid.UUID)
    return membership_id


def accept_campaign_invitation(
    connection: Connection, *, token: str, accepting_user_id: uuid.UUID
) -> AcceptCampaignInvitationResult:
    """Redeems `token`, activating or creating a `security.campaign_
    memberships` row for `accepting_user_id`. See this module's docstring
    for the full rejection/idempotency reasoning."""
    token_hash = _hash_invitation_token(token)
    invitation = (
        connection.execute(
            text("""
                SELECT campaign_invitation_id, campaign_id, accepted_by_user_id, revoked_at,
                       (expires_at <= now()) AS expired
                FROM security.campaign_invitations
                WHERE invitation_token_hash = :hash
                FOR UPDATE
            """),
            {"hash": token_hash},
        )
        .mappings()
        .one_or_none()
    )
    if invitation is None:
        raise InvitationNotAcceptableError(
            f"invitation token hash {token_hash} does not resolve to any invitation"
        )

    if invitation["accepted_by_user_id"] is not None:
        # Already accepted — a replay by the same user is idempotent
        # regardless of subsequent revocation/expiry (see this module's
        # docstring); revoked_at/expired only gate a *first* acceptance,
        # checked below.
        if invitation["accepted_by_user_id"] != accepting_user_id:
            raise InvitationNotAcceptableError(
                f"invitation {invitation['campaign_invitation_id']} was already accepted by a "
                "different user"
            )
        membership_id = connection.execute(
            text("""
                SELECT campaign_membership_id FROM security.campaign_memberships
                WHERE campaign_id = :campaign AND user_id = :user AND ended_at IS NULL
            """),
            {"campaign": invitation["campaign_id"], "user": accepting_user_id},
        ).scalar()
        if membership_id is None:
            raise InvitationNotAcceptableError(
                f"invitation {invitation['campaign_invitation_id']}'s previously accepted "
                "membership is no longer open"
            )
        return AcceptCampaignInvitationResult(
            campaign_id=invitation["campaign_id"], campaign_membership_id=membership_id
        )

    if invitation["revoked_at"] is not None or invitation["expired"]:
        raise InvitationNotAcceptableError(
            f"invitation {invitation['campaign_invitation_id']} is revoked or expired"
        )

    membership_id = _activate_or_create_membership(
        connection, campaign_id=invitation["campaign_id"], user_id=accepting_user_id
    )

    connection.execute(
        text("""
            UPDATE security.campaign_invitations
            SET accepted_by_user_id = :user, accepted_at = now()
            WHERE campaign_invitation_id = :invitation
        """),
        {"user": accepting_user_id, "invitation": invitation["campaign_invitation_id"]},
    )

    return AcceptCampaignInvitationResult(
        campaign_id=invitation["campaign_id"], campaign_membership_id=membership_id
    )
