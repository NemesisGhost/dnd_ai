"""Who may create a campaign (docs/adr/0020-scoped-system-world-and-campaign-roles.md).

Creating a campaign needs, all at once: the system `campaign.host` capability (the
system `gm` role), the world capability `campaign.create` on the timeline's world,
and, when the timeline already hosts a campaign, `timeline.manage`. Authority is
never borrowed from another campaign on the same timeline (finding F3), and the
creator receives both `campaign_owner` and `gm`.
"""

import uuid

import pytest
from sqlalchemy import Connection, text

from dnd_ai.commands.campaigns import (
    SystemGmRequiredError,
    TimelineNotAuthorizedError,
    create_campaign,
    grant_timeline_bootstrap,
)
from tests.builders import make_authored_campaign, make_authored_world
from tests.factories import (
    make_campaign_membership,
    make_membership_role,
    make_system_role_assignment,
    make_user,
)

pytestmark = pytest.mark.database


def _roles_in(connection: Connection, campaign_id: uuid.UUID, user_id: uuid.UUID) -> set[str]:
    rows = connection.execute(
        text("""
            SELECT r.code
            FROM security.campaign_memberships cm
            JOIN security.membership_roles mr
              ON mr.campaign_membership_id = cm.campaign_membership_id
            JOIN security.roles r ON r.role_id = mr.role_id
            WHERE cm.campaign_id = :c AND cm.user_id = :u AND mr.revoked_at IS NULL
        """),
        {"c": campaign_id, "u": user_id},
    )
    return {row.code for row in rows}


def _campaign_count(connection: Connection) -> int:
    return int(connection.execute(text("SELECT count(*) FROM campaign.campaigns")).scalar_one())


def _create(connection: Connection, world, user_id: uuid.UUID, name: str = "Another"):  # type: ignore[no-untyped-def]
    return create_campaign(
        connection,
        timeline_id=world.primary_timeline_id,
        ruleset_version_id=world.ruleset_version_id,
        name=name,
        creator_user_id=user_id,
    )


def test_an_owner_who_is_a_system_gm_creates_a_campaign_and_holds_both_roles(
    db_connection: Connection,
) -> None:
    owner = make_user(db_connection, "Owner GM")
    world = make_authored_world(db_connection, owner_user_id=owner)
    result = _create(db_connection, world, owner, "First")
    assert _roles_in(db_connection, result.campaign_id, owner) == {"campaign_owner", "gm"}


def test_an_owner_without_system_gm_is_refused_before_anything_is_written(
    db_connection: Connection,
) -> None:
    owner = make_user(db_connection, "Lapsed GM")
    world = make_authored_world(db_connection, owner_user_id=owner)
    db_connection.execute(
        text("UPDATE security.user_system_roles SET revoked_at = now() WHERE user_id = :u"),
        {"u": owner},
    )
    before = _campaign_count(db_connection)
    with pytest.raises(SystemGmRequiredError):
        _create(db_connection, world, owner)
    assert _campaign_count(db_connection) == before


def test_a_user_who_manages_another_campaign_on_the_timeline_cannot_borrow_that_authority(
    db_connection: Connection,
) -> None:
    owner = make_user(db_connection, "World Owner")
    world = make_authored_world(db_connection, owner_user_id=owner)
    existing = make_authored_campaign(db_connection, world)

    # A second GM, system GM and `campaign_owner` of the existing campaign, but
    # with no authority over the world itself (the former "Path B" caller).
    other = make_user(db_connection, "Other GM")
    make_system_role_assignment(db_connection, other, "gm")
    membership = make_campaign_membership(db_connection, existing, other)
    make_membership_role(
        db_connection, membership, system_role_id_for_campaign_owner(db_connection)
    )

    before = _campaign_count(db_connection)
    with pytest.raises(TimelineNotAuthorizedError):
        _create(db_connection, world, other)
    assert _campaign_count(db_connection) == before


def system_role_id_for_campaign_owner(connection: Connection) -> uuid.UUID:
    value = connection.execute(
        text(
            "SELECT role_id FROM security.roles WHERE code = 'campaign_owner' AND campaign_id IS NULL"
        )
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def test_a_system_gm_with_no_world_authority_and_no_grant_is_refused(
    db_connection: Connection,
) -> None:
    owner = make_user(db_connection, "Private Owner")
    world = make_authored_world(db_connection, owner_user_id=owner)
    stranger = make_user(db_connection, "Stranger GM")
    make_system_role_assignment(db_connection, stranger, "gm")
    with pytest.raises(TimelineNotAuthorizedError):
        _create(db_connection, world, stranger)


def test_a_bootstrap_grant_holder_still_needs_system_gm(db_connection: Connection) -> None:
    owner = make_user(db_connection, "Granting Owner")
    world = make_authored_world(db_connection, owner_user_id=owner)
    grantee = make_user(db_connection, "Grantee")
    grant_timeline_bootstrap(
        db_connection, timeline_id=world.primary_timeline_id, granted_to_user_id=grantee
    )
    with pytest.raises(SystemGmRequiredError):
        _create(db_connection, world, grantee)

    make_system_role_assignment(db_connection, grantee, "gm")
    result = _create(db_connection, world, grantee)
    assert _roles_in(db_connection, result.campaign_id, grantee) == {"campaign_owner", "gm"}


def test_the_owner_of_a_second_campaign_on_a_used_timeline_needs_timeline_manage(
    db_connection: Connection,
) -> None:
    owner = make_user(db_connection, "Repeat Owner")
    world = make_authored_world(db_connection, owner_user_id=owner)
    make_authored_campaign(db_connection, world)
    second = _create(db_connection, world, owner, "Second")
    assert _roles_in(db_connection, second.campaign_id, owner) == {"campaign_owner", "gm"}


def test_system_gm_alone_confers_no_membership_in_the_created_campaign_of_others(
    db_connection: Connection,
) -> None:
    owner = make_user(db_connection, "Host")
    world = make_authored_world(db_connection, owner_user_id=owner)
    created = _create(db_connection, world, owner)
    bystander = make_user(db_connection, "Bystander GM")
    make_system_role_assignment(db_connection, bystander, "gm")
    assert _roles_in(db_connection, created.campaign_id, bystander) == set()
