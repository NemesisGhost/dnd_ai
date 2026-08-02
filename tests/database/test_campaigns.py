"""campaign.campaigns and campaign.campaign_parties (revision 010).

campaign.campaigns proves the "two campaigns can share one timeline" Phase 3
exit criterion. campaign.campaign_parties proves that a world-level party
(revision 009) can be associated with a campaign, and that the association is
rejected when the party and the campaign disagree about which world they
belong to.
"""

import uuid

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError, InternalError, ProgrammingError

from tests.factories import make_campaign, make_party, make_timeline, make_world

pytestmark = pytest.mark.database

CONSTRAINT_ERRORS = (IntegrityError, InternalError, ProgrammingError)


@pytest.fixture
def world_id(db_connection: Connection) -> uuid.UUID:
    return make_world(db_connection, slug="campaign-world")


@pytest.fixture
def timeline_id(db_connection: Connection, world_id: uuid.UUID) -> uuid.UUID:
    return make_timeline(db_connection, world_id, is_primary=True)


# ---------------------------------------------------------------------------
# campaign.campaigns
# ---------------------------------------------------------------------------


def test_two_campaigns_can_share_one_timeline(
    db_connection: Connection, timeline_id: uuid.UUID
) -> None:
    """The exit criterion this table exists to satisfy."""
    make_campaign(db_connection, timeline_id, name="Campaign A")
    make_campaign(db_connection, timeline_id, name="Campaign B")

    count = db_connection.execute(
        text("SELECT count(*) FROM campaign.campaigns WHERE timeline_id = :t"),
        {"t": timeline_id},
    ).scalar()
    assert count == 2


def test_an_end_without_a_start_is_rejected(
    db_connection: Connection, timeline_id: uuid.UUID
) -> None:
    with pytest.raises(IntegrityError) as exc:
        db_connection.execute(
            text("""
                INSERT INTO campaign.campaigns
                    (timeline_id, name, lifecycle_status_id, ended_at)
                VALUES (:tl, 'Broken', (SELECT lifecycle_status_id FROM core.lifecycle_statuses
                                        WHERE code = 'active'), now())
            """),
            {"tl": timeline_id},
        )
    assert "ck_campaigns_ended_requires_started" in str(exc.value)


def test_ended_before_started_is_rejected(
    db_connection: Connection, timeline_id: uuid.UUID
) -> None:
    with pytest.raises(IntegrityError) as exc:
        db_connection.execute(
            text("""
                INSERT INTO campaign.campaigns
                    (timeline_id, name, lifecycle_status_id, started_at, ended_at)
                VALUES (:tl, 'Broken', (SELECT lifecycle_status_id FROM core.lifecycle_statuses
                                        WHERE code = 'active'), now(), now() - interval '1 day')
            """),
            {"tl": timeline_id},
        )
    assert "ck_campaigns_ended_after_started" in str(exc.value)


# ---------------------------------------------------------------------------
# campaign.campaign_parties
# ---------------------------------------------------------------------------


def test_a_party_can_be_associated_with_a_campaign(
    db_connection: Connection, world_id: uuid.UUID, timeline_id: uuid.UUID
) -> None:
    campaign_id = make_campaign(db_connection, timeline_id)
    party_id = make_party(db_connection, world_id)

    db_connection.execute(
        text("INSERT INTO campaign.campaign_parties (campaign_id, party_id) VALUES (:c, :p)"),
        {"c": campaign_id, "p": party_id},
    )

    count = db_connection.execute(
        text("SELECT count(*) FROM campaign.campaign_parties WHERE campaign_id = :c"),
        {"c": campaign_id},
    ).scalar()
    assert count == 1


def test_a_party_can_be_used_by_more_than_one_campaign(
    db_connection: Connection, world_id: uuid.UUID, timeline_id: uuid.UUID
) -> None:
    party_id = make_party(db_connection, world_id)
    first = make_campaign(db_connection, timeline_id, name="First")
    second = make_campaign(db_connection, timeline_id, name="Second")

    for campaign_id in (first, second):
        db_connection.execute(
            text("INSERT INTO campaign.campaign_parties (campaign_id, party_id) VALUES (:c, :p)"),
            {"c": campaign_id, "p": party_id},
        )


def test_a_party_from_another_world_cannot_join_a_campaign(
    db_connection: Connection, timeline_id: uuid.UUID
) -> None:
    other_world = make_world(db_connection, slug="campaign-other-world")
    foreign_party = make_party(db_connection, other_world)
    campaign_id = make_campaign(db_connection, timeline_id)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("INSERT INTO campaign.campaign_parties (campaign_id, party_id) VALUES (:c, :p)"),
            {"c": campaign_id, "p": foreign_party},
        )
    assert "belongs to world" in str(exc.value)
