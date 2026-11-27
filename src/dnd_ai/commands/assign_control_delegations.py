"""The vocabulary of assign-control delegations (P15-C11-S02-T02, ADR 0021 OD-4a).

A live built-in `campaign_owner` or `gm` assignment may delegate `character.assign_control` to a member who holds the
built-in `assistant_gm` role in the same campaign. The delegation is bound to that member's specific `assistant_gm`
assignment, so it authorizes only while that assignment is live; there are no lifecycle hooks (a lapsed role simply
ends the authority, a regained role needs a fresh grant). A delegated holder uses the three control writers and the
read of [control assignments](control_assignment_plans.py) and cannot delegate further.

This module holds the error vocabulary, the command and end-reason names and the one unlocked campaign check. The
writers are the plan phases in `assign_control_delegation_plans` (there is no unguarded direct command: the plan phases
are the only writers, and the tests compare the routes with the stored rows, as for the control writers).

It is deliberately separate from the reveal delegations of `character.reveal`: no shared table, function, error or
route, and neither delegation confers anything the other does.
"""

import uuid

from sqlalchemy import Connection, text

from dnd_ai.domain.errors import SafeMessageError

from .access_grants import MembershipNotInCampaignError

GRANT_COMMAND_NAME = "delegate_character_assign_control"
REVOKE_COMMAND_NAME = "revoke_character_assign_control_delegation"

#: An explicit revocation by an owner or GM (`revoked_by_membership_id` and `revocation_reason` set).
END_REASON_REVOKED = "revoked"
#: A later grant found the bound `assistant_gm` assignment no longer live and closed the row.
END_REASON_ASSISTANT_GM_LAPSED = "assistant_gm_assignment_lapsed"


class AssignControlRecipientNotAssistantGmError(SafeMessageError):
    """The grantee does not currently hold the built-in `assistant_gm` role as an open, active member of this campaign.
    409. The caller is a live owner or GM who chose the member, so this discloses nothing about anyone else."""

    safe_status_code = 409
    safe_error_code = "assign_control_recipient_not_assistant_gm"
    safe_message = (
        "Assigning character control can be delegated only to a member who currently holds the "
        "assistant GM role. Nothing was changed."
    )


class AssignControlRecipientChangedError(SafeMessageError):
    """The grantee's live built-in `assistant_gm` assignment, or its live delegations, changed after the grant had
    chosen the rows to lock: the delegation would have bound to a row the grant never held. Nothing was written; a retry
    locks the new rows first. 409."""

    safe_status_code = 409
    safe_error_code = "assign_control_recipient_changed"
    safe_message = (
        "The member's assistant GM assignment changed while the delegation was being made. "
        "Nothing was changed; try again."
    )


def require_grantee_in_campaign(
    connection: Connection, *, campaign_id: uuid.UUID, grantee_campaign_membership_id: uuid.UUID
) -> None:
    """404 for a membership of another campaign (or none). The membership's campaign never changes, so this unlocked
    read is safe ahead of any lock."""
    belongs = connection.execute(
        text(
            "SELECT 1 FROM security.campaign_memberships "
            "WHERE campaign_membership_id = :membership AND campaign_id = :campaign"
        ),
        {"membership": grantee_campaign_membership_id, "campaign": campaign_id},
    ).first()
    if belongs is None:
        raise MembershipNotInCampaignError(
            f"membership {grantee_campaign_membership_id} does not belong to campaign {campaign_id}"
        )


__all__ = [
    "END_REASON_ASSISTANT_GM_LAPSED",
    "END_REASON_REVOKED",
    "GRANT_COMMAND_NAME",
    "REVOKE_COMMAND_NAME",
    "AssignControlRecipientChangedError",
    "AssignControlRecipientNotAssistantGmError",
    "require_grantee_in_campaign",
]
