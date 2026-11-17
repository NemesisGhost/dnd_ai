"""R01 E1: shared test support for the proposal-review command.

`dnd_ai.commands.ai_proposals.review_proposed_change` no longer opens its own transaction: it runs on the caller's
connection under an `AuthorizationPlan` and locks the reviewer's operation scope first. The two review test
modules (`test_ai_npc.py`, `test_ai_advance_objective_proposal.py`) keep every assertion; they call
`review_proposed_change(engine, ...)` here, which wraps the command in `authorized_transaction` (finalize, then
commit or abandon by T0's rule) and gives each reviewer a GM role in the campaign they review in (the
operation-scope check every operation route makes; the campaign must be `active`).
"""

import uuid
from typing import Any

from sqlalchemy import Connection, Engine, text

from dnd_ai.commands.ai_proposals import ReviewProposedChangeResult
from dnd_ai.commands.ai_proposals import review_proposed_change as _review_in_transaction
from dnd_ai.commands.authorized_transaction import authorized_transaction
from tests.factories import (
    make_campaign,
    make_campaign_membership,
    make_membership_role,
    make_user,
    status_id,
)


def make_active_campaign(
    connection: Connection, timeline_id: uuid.UUID, name: str = "The Campaign"
) -> uuid.UUID:
    """An `active` campaign. Since revision 080 an active campaign must retain an access manager, so it is
    created `pending`, given an owner, and then activated (the operation-scope check the review now makes
    requires `active`; design D-5)."""
    campaign_id = make_campaign(connection, timeline_id, name, lifecycle_status_code="pending")
    owner = make_user(connection, "Campaign Owner")
    membership_id = make_campaign_membership(connection, campaign_id, owner)
    template = connection.execute(
        text(
            "SELECT role_id FROM security.roles WHERE code = 'campaign_owner' AND campaign_id IS NULL"
        )
    ).scalar_one()
    make_membership_role(connection, membership_id, template)
    connection.execute(
        text("UPDATE campaign.campaigns SET lifecycle_status_id = :s WHERE campaign_id = :c"),
        {"s": status_id(connection, "lifecycle_statuses", "active"), "c": campaign_id},
    )
    return campaign_id


def make_gm_reviewer(
    connection: Connection, campaign_id: uuid.UUID, name: str = "Reviewer"
) -> uuid.UUID:
    """A user holding the template `gm` role (`canon.edit`) in `campaign_id`."""
    user_id = make_user(connection, name)
    membership_id = make_campaign_membership(connection, campaign_id, user_id)
    template = connection.execute(
        text("SELECT role_id FROM security.roles WHERE code = 'gm' AND campaign_id IS NULL")
    ).scalar_one()
    make_membership_role(connection, membership_id, template)
    return user_id


def delete_reviewer(connection: Connection, user_id: uuid.UUID) -> None:
    """Remove a reviewer made by `make_gm_reviewer`: its membership first (the foreign key is RESTRICT)."""
    connection.execute(
        text("DELETE FROM security.campaign_memberships WHERE user_id = :u"), {"u": user_id}
    )
    connection.execute(text("DELETE FROM security.users WHERE user_id = :u"), {"u": user_id})


def review_proposed_change(engine: Engine, **kwargs: Any) -> ReviewProposedChangeResult:
    """`review_proposed_change(engine, ai_proposed_change_id=..., campaign_id=..., reviewer_user_id=...,
    decision=..., comments=...)` as one authorized transaction on `engine`."""
    with authorized_transaction(engine, kwargs["reviewer_user_id"], kwargs["campaign_id"]) as (
        connection,
        plan,
    ):
        return _review_in_transaction(connection, plan=plan, **kwargs)
