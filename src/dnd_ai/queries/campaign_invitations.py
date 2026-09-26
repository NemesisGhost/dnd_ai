"""Campaign-scoped pending invitation read query.

Returns only currently outstanding `security.campaign_invitations` rows
for one already-authorized campaign: never accepted, never revoked, and
not yet expired. This is a pure read with no idempotency reservation or
audit row, mirroring the rest of the query layer.

The response is a reviewed presentation projection only: no raw token,
token hash, accepted-user identity, login identity, session, or
credential data leaves this module. `invited_email` remains optional
operator metadata only; it is returned verbatim when present but is not an
authorization binding.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Connection, text


@dataclass(frozen=True)
class PendingCampaignInvitationView:
    campaign_invitation_id: uuid.UUID
    invited_email: str | None
    invited_by_display_name: str
    created_at: datetime
    expires_at: datetime


def list_pending_campaign_invitations(
    connection: Connection, *, campaign_id: uuid.UUID
) -> tuple[PendingCampaignInvitationView, ...]:
    """Outstanding invitations for `campaign_id`, oldest first.

    Ordering is deterministic: `created_at`, then `campaign_invitation_id`.
    Returns an empty tuple when none are pending.
    """
    rows = connection.execute(
        text("""
            SELECT
                ci.campaign_invitation_id,
                ci.invited_email,
                inviter.display_name AS invited_by_display_name,
                ci.created_at,
                ci.expires_at
            FROM security.campaign_invitations ci
            JOIN security.campaign_memberships inviter_membership
                ON inviter_membership.campaign_membership_id = ci.invited_by_membership_id
            JOIN security.users inviter
                ON inviter.user_id = inviter_membership.user_id
            WHERE ci.campaign_id = :campaign
              AND ci.accepted_by_user_id IS NULL
              AND ci.accepted_at IS NULL
              AND ci.revoked_at IS NULL
              AND ci.expires_at > now()
            ORDER BY ci.created_at ASC, ci.campaign_invitation_id ASC
        """),
        {"campaign": campaign_id},
    ).mappings()

    invitations: list[PendingCampaignInvitationView] = []
    for row in rows:
        campaign_invitation_id = row["campaign_invitation_id"]
        created_at = row["created_at"]
        expires_at = row["expires_at"]
        assert isinstance(campaign_invitation_id, uuid.UUID)
        assert isinstance(created_at, datetime)
        assert isinstance(expires_at, datetime)
        invitations.append(
            PendingCampaignInvitationView(
                campaign_invitation_id=campaign_invitation_id,
                invited_email=row["invited_email"],
                invited_by_display_name=str(row["invited_by_display_name"]),
                created_at=created_at,
                expires_at=expires_at,
            )
        )
    return tuple(invitations)
