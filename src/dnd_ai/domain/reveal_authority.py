"""Who may reveal a character in a campaign (P03-A A1, `character.reveal`).

`character.reveal` has exactly two sources and is never carried by a custom role, a relationship
type, a resource grant, `access.manage`, `canon.edit` or assistant-GM status:

- `owner`: a live built-in `campaign_owner` assignment
  (`find_live_builtin_owner_assignment`, the same predicate the D3 ownership gate uses);
- `delegation`: a live delegation (`security.character_reveal_delegations`) from an owner to a
  member who holds the built-in `gm` role. It is bound to one specific `gm` assignment and counts
  only while that exact row is live, so losing GM status and regaining it later never revives it.

Commands re-read authority under lock at their protected write and never trust a cached
`AccessContext` (docs/PHASE14_15_P03A_IMPLEMENTATION_PLAN_2026-11-06.md section 1).
"""

import uuid
from datetime import datetime
from typing import Literal

from sqlalchemy import Connection, text

from .access import (
    OwnerAssignmentLock,
    find_live_builtin_gm_assignment,
    find_live_builtin_owner_assignment,
)

RevealAuthority = Literal["owner", "delegation", "none"]

REVEAL_CAPABILITY_CODE = "character.reveal"


def resolve_reveal_authority(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    campaign_membership_id: uuid.UUID,
    lock: OwnerAssignmentLock = "none",
    as_of: datetime | None = None,
) -> RevealAuthority:
    """The source of this membership's reveal authority in `campaign_id`, or `none`.

    `lock` takes a row lock on every row the answer depends on, in the order a release or reveal
    command locks them: the owner assignment; failing that, the `gm` assignment, then the
    delegation row. `share` keeps them live until commit. `as_of` is the instant expiry is judged
    at; a caller that has waited on locks passes a fresh `clock_timestamp()` (see
    `find_live_builtin_owner_assignment`)."""
    if (
        find_live_builtin_owner_assignment(
            connection,
            campaign_id=campaign_id,
            campaign_membership_id=campaign_membership_id,
            lock=lock,
            as_of=as_of,
        )
        is not None
    ):
        return "owner"
    gm_assignment = find_live_builtin_gm_assignment(
        connection,
        campaign_id=campaign_id,
        campaign_membership_id=campaign_membership_id,
        lock=lock,
        as_of=as_of,
    )
    if gm_assignment is None:
        return "none"
    bound = connection.execute(
        text(f"""
            SELECT gm_membership_role_id
            FROM security.character_reveal_delegations
            WHERE campaign_id = :campaign
              AND grantee_campaign_membership_id = :membership
              AND revoked_at IS NULL
            {"FOR SHARE" if lock != "none" else ""}
        """),  # noqa: S608 - the lock clause is one of two literals
        {"campaign": campaign_id, "membership": campaign_membership_id},
    ).scalar()
    return "delegation" if bound == gm_assignment else "none"
