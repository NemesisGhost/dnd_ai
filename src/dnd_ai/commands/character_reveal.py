"""Granting and revoking `character.reveal` delegations (P03-A A1).

A live built-in `campaign_owner` is the only actor who can delegate `character.reveal`, and only to
a member who currently holds the built-in `gm` role (docs/PHASE14_15_P03A_IMPLEMENTATION_PLAN_2026-
11-06.md section 1, ADR 0021). `access.manage`, `canon.edit`, a custom role or an assistant-GM
status confer neither the authority nor the right to delegate it. The delegation is bound to the
grantee's specific live `gm` assignment (`reveal_delegation_lifecycle` closes it when that
assignment or the membership ends), so a regained GM status needs a fresh grant.

Both commands re-read the caller's owner assignment under lock and again at a fresh database
instant after their last lock wait and before the write (DEF-013), reusing the D3 gate and the
shared live-owner predicate. Lock order (design section 3, never inverted): the caller's owner
assignment (`FOR SHARE`); the grantee's built-in `gm` assignment rows (`FOR UPDATE`); the grantee's
membership (`FOR UPDATE`); the grantee's delegation rows (`FOR UPDATE`); the campaign row (`FOR
UPDATE`). Revoking takes the owner assignment, the delegation rows and the campaign row. This is
the order `revoke_membership_role`, `change_membership_role` and `end_campaign_membership` reach
the same rows in: role rows, then the membership, then the delegation, then the campaign (the
retention trigger takes it at commit).
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, text

from dnd_ai.domain.access import find_live_builtin_gm_assignment
from dnd_ai.domain.authoring import normalize_reason
from dnd_ai.domain.errors import SafeMessageError

from .memberships import (
    MembershipNotInCampaignError,
    _database_clock,
    _recheck_caller_is_live_owner,
    _require_builtin_campaign_owner,
)
from .reveal_delegation_lifecycle import (
    END_REASON_GM_ASSIGNMENT_LAPSED,
    END_REASON_REVOKED_BY_OWNER,
)


class RevealDelegationRecipientNotGmError(SafeMessageError):
    """The grantee does not currently hold the built-in `gm` role as an open, active member:
    reveal authority can be delegated only to a GM (`assistant_gm`, a custom role and a player
    do not qualify). 409. The caller is a live owner of the campaign and chose the member, so this
    discloses nothing about anyone else."""

    safe_status_code = 409
    safe_error_code = "reveal_delegation_recipient_not_gm"
    safe_message = (
        "Reveal authority can be delegated only to a member who currently holds the GM role. "
        "Nothing was changed."
    )


@dataclass(frozen=True)
class GrantCharacterRevealDelegationResult:
    grantee_campaign_membership_id: uuid.UUID
    character_reveal_delegation_id: uuid.UUID
    # False when the grantee already held a delegation bound to their current live gm assignment.
    created: bool
    gm_membership_role_id: uuid.UUID
    # Live delegations this grant closed because the gm assignment they were bound to is gone.
    replaced_stale_delegation_ids: tuple[uuid.UUID, ...] = ()


@dataclass(frozen=True)
class RevokeCharacterRevealDelegationResult:
    grantee_campaign_membership_id: uuid.UUID
    # None when the grantee held no live delegation (a harmless no-op).
    character_reveal_delegation_id: uuid.UUID | None
    revoked: bool


def _require_grantee_in_campaign(
    connection: Connection, *, campaign_id: uuid.UUID, grantee_campaign_membership_id: uuid.UUID
) -> None:
    """The membership's campaign never changes, so this unlocked read is safe ahead of any lock."""
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


def grant_character_reveal_delegation(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_membership_id: uuid.UUID,
    grantee_campaign_membership_id: uuid.UUID,
    reason: str,
) -> GrantCharacterRevealDelegationResult:
    """Delegates `character.reveal` to a member holding the built-in `gm` role.

    The caller must be a live built-in owner (`CampaignOwnerRequiredError`, 403), checked first
    and again at a fresh instant before the write. The grantee must belong to `campaign_id`
    (`MembershipNotInCampaignError`, 404) and hold a live built-in `gm` assignment
    (`RevealDelegationRecipientNotGmError`, 409). Idempotent: a grantee whose live delegation is
    bound to their current `gm` assignment gets no second row. A live delegation bound to an
    assignment that has since expired or been replaced does not block a fresh grant: it is closed
    (`gm_assignment_lapsed`) and a new row is bound to the current assignment."""
    clean_reason = normalize_reason(reason, required=True)
    assert clean_reason is not None
    _require_builtin_campaign_owner(
        connection, campaign_id=campaign_id, actor_membership_id=actor_membership_id
    )
    _require_grantee_in_campaign(
        connection,
        campaign_id=campaign_id,
        grantee_campaign_membership_id=grantee_campaign_membership_id,
    )
    # Only the grantee's built-in gm rows are locked, not every role row: two owners granting to
    # each other would otherwise each hold the other's owner assignment `FOR SHARE` and want it
    # `FOR UPDATE`.
    connection.execute(
        text("""
            SELECT mr.membership_role_id
            FROM security.membership_roles mr
            JOIN security.roles r ON r.role_id = mr.role_id
            WHERE mr.campaign_membership_id = :grantee
              AND r.campaign_id IS NULL AND r.code = 'gm' AND mr.revoked_at IS NULL
            ORDER BY mr.membership_role_id
            FOR UPDATE OF mr
        """),
        {"grantee": grantee_campaign_membership_id},
    ).all()
    connection.execute(
        text(
            "SELECT 1 FROM security.campaign_memberships "
            "WHERE campaign_membership_id = :grantee FOR UPDATE"
        ),
        {"grantee": grantee_campaign_membership_id},
    ).all()
    existing = (
        connection.execute(
            text("""
                SELECT character_reveal_delegation_id, gm_membership_role_id
                FROM security.character_reveal_delegations
                WHERE grantee_campaign_membership_id = :grantee AND revoked_at IS NULL
                ORDER BY character_reveal_delegation_id
                FOR UPDATE
            """),
            {"grantee": grantee_campaign_membership_id},
        )
        .mappings()
        .all()
    )
    connection.execute(
        text("SELECT 1 FROM campaign.campaigns WHERE campaign_id = :campaign FOR UPDATE"),
        {"campaign": campaign_id},
    ).all()

    # Every lock wait is behind us: judge the caller and the grantee at a fresh database instant.
    now = _database_clock(connection)
    _recheck_caller_is_live_owner(
        connection, campaign_id=campaign_id, actor_membership_id=actor_membership_id
    )
    gm_assignment = find_live_builtin_gm_assignment(
        connection,
        campaign_id=campaign_id,
        campaign_membership_id=grantee_campaign_membership_id,
        as_of=now,
    )
    if gm_assignment is None:
        raise RevealDelegationRecipientNotGmError(
            f"membership {grantee_campaign_membership_id} holds no live built-in gm assignment "
            f"in campaign {campaign_id}"
        )

    for row in existing:
        if row["gm_membership_role_id"] == gm_assignment:
            return GrantCharacterRevealDelegationResult(
                grantee_campaign_membership_id=grantee_campaign_membership_id,
                character_reveal_delegation_id=row["character_reveal_delegation_id"],
                created=False,
                gm_membership_role_id=gm_assignment,
            )
    stale = [row["character_reveal_delegation_id"] for row in existing]
    if stale:
        connection.execute(
            text("""
                UPDATE security.character_reveal_delegations
                SET revoked_at = :now, end_reason = :end_reason
                WHERE character_reveal_delegation_id = ANY(:ids)
            """),
            {"now": now, "end_reason": END_REASON_GM_ASSIGNMENT_LAPSED, "ids": stale},
        )
    delegation_id = connection.execute(
        text("""
            INSERT INTO security.character_reveal_delegations
                (campaign_id, grantee_campaign_membership_id, gm_membership_role_id,
                 granted_by_membership_id, reason)
            VALUES (:campaign, :grantee, :gm_role, :actor, :reason)
            RETURNING character_reveal_delegation_id
        """),
        {
            "campaign": campaign_id,
            "grantee": grantee_campaign_membership_id,
            "gm_role": gm_assignment,
            "actor": actor_membership_id,
            "reason": clean_reason,
        },
    ).scalar()
    assert isinstance(delegation_id, uuid.UUID)
    return GrantCharacterRevealDelegationResult(
        grantee_campaign_membership_id=grantee_campaign_membership_id,
        character_reveal_delegation_id=delegation_id,
        created=True,
        gm_membership_role_id=gm_assignment,
        replaced_stale_delegation_ids=tuple(stale),
    )


def revoke_character_reveal_delegation(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_membership_id: uuid.UUID,
    grantee_campaign_membership_id: uuid.UUID,
    reason: str,
) -> RevokeCharacterRevealDelegationResult:
    """Revokes the grantee's live delegation. Only a live built-in owner may (`CampaignOwnerRequiredError`,
    403), whoever granted it: the grantor is provenance, so a new owner can revoke what a former
    owner granted. Idempotent: a grantee with no live delegation is a no-op (`revoked` is False)
    and writes nothing."""
    clean_reason = normalize_reason(reason, required=True)
    assert clean_reason is not None
    _require_builtin_campaign_owner(
        connection, campaign_id=campaign_id, actor_membership_id=actor_membership_id
    )
    _require_grantee_in_campaign(
        connection,
        campaign_id=campaign_id,
        grantee_campaign_membership_id=grantee_campaign_membership_id,
    )
    delegation_id = connection.execute(
        text("""
            SELECT character_reveal_delegation_id
            FROM security.character_reveal_delegations
            WHERE grantee_campaign_membership_id = :grantee AND campaign_id = :campaign
              AND revoked_at IS NULL
            FOR UPDATE
        """),
        {"grantee": grantee_campaign_membership_id, "campaign": campaign_id},
    ).scalar()
    connection.execute(
        text("SELECT 1 FROM campaign.campaigns WHERE campaign_id = :campaign FOR UPDATE"),
        {"campaign": campaign_id},
    ).all()
    _recheck_caller_is_live_owner(
        connection, campaign_id=campaign_id, actor_membership_id=actor_membership_id
    )
    if delegation_id is None:
        return RevokeCharacterRevealDelegationResult(
            grantee_campaign_membership_id=grantee_campaign_membership_id,
            character_reveal_delegation_id=None,
            revoked=False,
        )
    connection.execute(
        text("""
            UPDATE security.character_reveal_delegations
            SET revoked_at = clock_timestamp(), revoked_by_membership_id = :actor,
                revocation_reason = :reason, end_reason = :end_reason
            WHERE character_reveal_delegation_id = :id
        """),
        {
            "actor": actor_membership_id,
            "reason": clean_reason,
            "end_reason": END_REASON_REVOKED_BY_OWNER,
            "id": delegation_id,
        },
    )
    return RevokeCharacterRevealDelegationResult(
        grantee_campaign_membership_id=grantee_campaign_membership_id,
        character_reveal_delegation_id=delegation_id,
        revoked=True,
    )
