"""Granting and revoking `character.reveal` delegations (P03-A A1).

A live built-in `campaign_owner` is the only actor who can delegate `character.reveal`, and only to
a member who currently holds the built-in `gm` role (docs/PHASE14_15_P03A_IMPLEMENTATION_PLAN_2026-
11-06.md section 1, ADR 0021). `access.manage`, `canon.edit`, a custom role or an assistant-GM
status confer neither the authority nor the right to delegate it. The delegation is bound to the
grantee's specific live `gm` assignment (`reveal_delegation_lifecycle` closes it when that
assignment or the membership ends), so a regained GM status needs a fresh grant.

Both commands re-read the caller's owner assignment under lock and again at a fresh database
instant after their last lock wait and before the write (DEF-013), reusing the D3 gate and the
shared live-owner predicate.

Lock order of a grant (R01 S5-E2 lock-order correction C1, docs/R01_S5E2_LOCK_ORDER_CORRECTION_DESIGN_
2026-11-15.md): **each lock class in one ascending-id pass, every row at the mode it needs.** The rows are
discovered first by one unlocked read (the caller's live owner row and the grantee's unrevoked built-in `gm`
rows of this campaign, ordered by `membership_role_id`) and then locked one statement per row, each bound to a
discovered id, so a row that appears later is never picked up by a locking statement: the role class (the owner
row `FOR SHARE`, a `gm` row `FOR UPDATE`, in id order, so the grant and the S5-E2 change/revoke/transfer routes,
which lock role rows in id order too, never wait in a cycle); the membership class (the grantee `FOR NO KEY
UPDATE` and the caller `FOR KEY SHARE`, in id order; one membership is locked once, at `FOR NO KEY UPDATE`); the
grantee's delegation rows (`FOR UPDATE`); the campaign (`FOR KEY SHARE`). After the last wait the caller is
re-judged and the live `gm` row must be one of the rows locked in the role pass, otherwise the grant is refused
409 `reveal_delegation_recipient_changed` (a `gm` row inserted after discovery would be a delegation target nobody
holds). Refusal precedence is unchanged: 403 (no live owner row, at discovery or at the lock), 404 (grantee of
another campaign), 403 (the caller's row lapsed during the waits), 409 (no live `gm` row). Revoking takes the
owner assignment, the delegation row and the caller's membership (`FOR KEY SHARE`). The order is the one
`revoke_membership_role`, `change_membership_role` and `end_campaign_membership` reach the same rows in: role rows,
then the membership, then the delegation, then the campaign (the retention trigger takes it at commit).

Why these modes (the two deadlocks found in review):

- The grantee's membership is locked `FOR NO KEY UPDATE`, never `FOR UPDATE`. The delegation
  insert's foreign key takes `FOR KEY SHARE` on the *granting* membership. Two owners granting each
  other each held `FOR UPDATE` on the membership the other request's foreign key needed, and
  deadlocked. `FOR NO KEY UPDATE` still excludes every command that locks the membership `FOR
  UPDATE` (ending it, assigning it a role) and does not conflict with a key share.
- The campaign row is taken only `FOR KEY SHARE`, the mode the insert needs anyway, and taken here
  so that any wait for it is behind the caller re-check (DEF-013). It conflicts only with `FOR
  UPDATE` takers (a relinquishing transfer, adding a member, the retention trigger at commit), none
  of which waits for what a grant holds. It must not be `FOR UPDATE`: administrative recovery holds
  the campaign row `FOR NO KEY UPDATE` while it waits for the membership it promotes, and a grant
  holding that membership and wanting the campaign row `FOR UPDATE` made the two wait on each other.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, text

from dnd_ai.domain.access import (
    BUILTIN_CAMPAIGN_GM_ROLE_CODE,
    BUILTIN_CAMPAIGN_OWNER_ROLE_CODE,
    find_live_builtin_gm_assignment,
)
from dnd_ai.domain.authoring import normalize_reason
from dnd_ai.domain.errors import SafeMessageError

from .memberships import (
    CampaignOwnerRequiredError,
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


class RevealDelegationRecipientChangedError(SafeMessageError):
    """The grantee's live built-in `gm` assignment appeared after the grant had chosen the rows to lock (C1,
    docs/R01_S5E2_LOCK_ORDER_CORRECTION_DESIGN_2026-11-15.md BA-1): the delegation would have bound to a row the
    grant never held. Nothing was written; a retry locks the new row first. 409."""

    safe_status_code = 409
    safe_error_code = "reveal_delegation_recipient_changed"
    safe_message = (
        "The member's GM assignment changed while the delegation was being made. "
        "Nothing was changed; try again."
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


def _lock_foreign_key_targets(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_membership_id: uuid.UUID,
    include_campaign: bool,
) -> None:
    """Takes `FOR KEY SHARE` on the rows the write's foreign keys will touch (the caller's
    membership, and the campaign for an insert) before the caller re-check, so that a wait for
    them cannot fall between the re-check and the write (DEF-013). The mode is the weakest there
    is and is what the foreign-key check takes itself; see the module docstring for why it must
    not be stronger."""
    connection.execute(
        text(
            "SELECT 1 FROM security.campaign_memberships "
            "WHERE campaign_membership_id = :actor FOR KEY SHARE"
        ),
        {"actor": actor_membership_id},
    ).all()
    if include_campaign:
        connection.execute(
            text("SELECT 1 FROM campaign.campaigns WHERE campaign_id = :campaign FOR KEY SHARE"),
            {"campaign": campaign_id},
        ).all()


_OWNER_KIND = "owner"
_GM_KIND = "gm"

# The caller's live built-in owner row: exactly `find_live_builtin_owner_assignment`'s predicate at `now()` (the
# transaction's start), repeated here so that a *locking* statement can be bound to a discovered row id.
_LIVE_OWNER_FROM = """
    FROM security.membership_roles mr
    JOIN security.roles r ON r.role_id = mr.role_id
    JOIN security.campaign_memberships cm ON cm.campaign_membership_id = mr.campaign_membership_id
    JOIN security.membership_statuses ms ON ms.membership_status_id = cm.membership_status_id
    JOIN security.users u ON u.user_id = cm.user_id
    JOIN core.lifecycle_statuses uls ON uls.lifecycle_status_id = u.lifecycle_status_id
    WHERE mr.campaign_membership_id = :caller
      AND cm.campaign_id = :campaign
      AND r.campaign_id IS NULL
      AND r.code = :owner
      AND r.is_active
      AND mr.revoked_at IS NULL
      AND (mr.expires_at IS NULL OR mr.expires_at > now())
      AND cm.ended_at IS NULL
      AND ms.code = 'active'
      AND ms.is_active
      AND uls.code = 'active'
"""
_LIVE_OWNER_ROW_SQL = "SELECT mr.membership_role_id " + _LIVE_OWNER_FROM
# The grantee's unrevoked built-in gm rows (the rows the delegation binds to and the lifecycle closes).
_GM_ROW_SQL = """
    SELECT mr.membership_role_id
    FROM security.membership_roles mr
    JOIN security.roles r ON r.role_id = mr.role_id
    WHERE mr.campaign_membership_id = :grantee
      AND r.campaign_id IS NULL AND r.code = :gm AND mr.revoked_at IS NULL
"""
_DISCOVERY_SQL = f"""
    SELECT d.membership_role_id, d.kind FROM (
        SELECT mr.membership_role_id, '{_OWNER_KIND}' AS kind {_LIVE_OWNER_FROM}
        UNION ALL
        SELECT mr.membership_role_id, '{_GM_KIND}' AS kind
        FROM security.membership_roles mr
        JOIN security.roles r ON r.role_id = mr.role_id
        JOIN security.campaign_memberships cm ON cm.campaign_membership_id = mr.campaign_membership_id
        WHERE mr.campaign_membership_id = :grantee
          AND cm.campaign_id = :campaign
          AND r.campaign_id IS NULL AND r.code = :gm AND mr.revoked_at IS NULL
    ) d
    ORDER BY d.membership_role_id
"""  # noqa: S608 - the interpolated names are module constants


def _owner_binds(
    campaign_id: uuid.UUID, caller_membership_id: uuid.UUID, *, row: uuid.UUID
) -> dict[str, object]:
    return {
        "caller": caller_membership_id,
        "campaign": campaign_id,
        "owner": BUILTIN_CAMPAIGN_OWNER_ROLE_CODE,
        "row": row,
    }


def _owner_required(
    campaign_id: uuid.UUID, caller_membership_id: uuid.UUID
) -> CampaignOwnerRequiredError:
    return CampaignOwnerRequiredError(
        f"membership {caller_membership_id} holds no live campaign_owner assignment in "
        f"campaign {campaign_id}"
    )


def _discover_role_rows(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    caller_membership_id: uuid.UUID,
    grantee_membership_id: uuid.UUID,
) -> list[tuple[uuid.UUID, str]]:
    """The caller's live owner row and the grantee's unrevoked gm rows of this campaign, **unlocked**, ascending by
    id: the order the role class is then locked in. A grantee of another campaign matches no gm row."""
    found = connection.execute(
        text(_DISCOVERY_SQL),
        {
            "caller": caller_membership_id,
            "grantee": grantee_membership_id,
            "campaign": campaign_id,
            "owner": BUILTIN_CAMPAIGN_OWNER_ROLE_CODE,
            "gm": BUILTIN_CAMPAIGN_GM_ROLE_CODE,
        },
    ).all()
    return [(row.membership_role_id, row.kind) for row in found]


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
    # 1. Discovery (unlocked, one statement, ascending by id): the caller's live owner row and the grantee's
    #    unrevoked built-in gm rows. A caller with no live owner row is refused before anything is locked.
    discovered = _discover_role_rows(
        connection,
        campaign_id=campaign_id,
        caller_membership_id=actor_membership_id,
        grantee_membership_id=grantee_campaign_membership_id,
    )
    if not any(kind == _OWNER_KIND for _, kind in discovered):
        raise _owner_required(campaign_id, actor_membership_id)
    # 2. Role class, one ascending pass, each row once at the mode it needs, each statement bound to a
    #    discovered id (a row inserted after discovery is never picked up by a locking statement):
    #    the owner row FOR SHARE (a revocation, an end or a relinquishment waits for this transaction),
    #    the gm rows FOR UPDATE (they are the delegation's foreign key and its lifecycle).
    locked_gm_rows: set[uuid.UUID] = set()
    for row_id, kind in discovered:
        if kind == _OWNER_KIND:
            if (
                connection.execute(
                    text(_LIVE_OWNER_ROW_SQL + " AND mr.membership_role_id = :row FOR SHARE OF mr"),
                    _owner_binds(campaign_id, actor_membership_id, row=row_id),
                ).first()
                is None
            ):
                raise _owner_required(campaign_id, actor_membership_id)
        elif (
            connection.execute(
                text(_GM_ROW_SQL + " AND mr.membership_role_id = :row FOR UPDATE OF mr"),
                {
                    "grantee": grantee_campaign_membership_id,
                    "row": row_id,
                    "gm": BUILTIN_CAMPAIGN_GM_ROLE_CODE,
                },
            ).first()
            is not None
        ):
            locked_gm_rows.add(row_id)
    # 3. Unlocked, as before (the membership's campaign never changes): the 404 keeps its place after the
    #    owner refusal.
    _require_grantee_in_campaign(
        connection,
        campaign_id=campaign_id,
        grantee_campaign_membership_id=grantee_campaign_membership_id,
    )
    # 4. Membership class, one ascending pass: the grantee `FOR NO KEY UPDATE`, the caller `FOR KEY SHARE`
    #    (the delegation insert's foreign keys need nothing stronger); one membership, one lock.
    memberships: dict[uuid.UUID, str] = {actor_membership_id: "FOR KEY SHARE"}
    memberships[grantee_campaign_membership_id] = "FOR NO KEY UPDATE"
    for membership_id in sorted(memberships):
        connection.execute(
            text(
                "SELECT 1 FROM security.campaign_memberships "
                f"WHERE campaign_membership_id = :membership {memberships[membership_id]}"  # noqa: S608
            ),
            {"membership": membership_id},
        ).all()
    # 5. The grantee's delegation rows, then the campaign (`FOR KEY SHARE`, the mode the insert needs).
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
        text("SELECT 1 FROM campaign.campaigns WHERE campaign_id = :campaign FOR KEY SHARE"),
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
    if gm_assignment not in locked_gm_rows:
        # The live gm row was not among the rows locked in step 2 (it appeared after discovery): the
        # delegation would bind to a row nobody holds. Retryable; nothing has been written.
        raise RevealDelegationRecipientChangedError(
            f"membership {grantee_campaign_membership_id}'s live gm assignment {gm_assignment} "
            "appeared while the grant waited"
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
    _lock_foreign_key_targets(
        connection,
        campaign_id=campaign_id,
        actor_membership_id=actor_membership_id,
        include_campaign=False,
    )
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
