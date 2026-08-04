"""Session world_time_period derivation (revision 023).

Split from test_phase4_corrections.py (DEVELOPMENT.md §2.1): sessions'
derived half-open world-time range, tracked separately from the other
rule-content correction topics that used to share a file with it.
"""

import uuid

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError, InternalError, ProgrammingError

from tests.factories import (
    make_campaign,
    make_session,
    make_timeline,
    make_world,
    make_world_time,
)

pytestmark = pytest.mark.database

CONSTRAINT_ERRORS = (IntegrityError, InternalError, ProgrammingError)


@pytest.fixture
def world_id(db_connection: Connection) -> uuid.UUID:
    return make_world(db_connection, slug="corrections-world")


@pytest.fixture
def campaign_id(db_connection: Connection, world_id: uuid.UUID) -> uuid.UUID:
    timeline_id = make_timeline(db_connection, world_id, is_primary=True)
    return make_campaign(db_connection, timeline_id)


def test_an_unscheduled_session_has_no_world_time_period(
    db_connection: Connection, campaign_id: uuid.UUID
) -> None:
    session_id = make_session(db_connection, campaign_id, 1)
    period = db_connection.execute(
        text("SELECT world_time_period FROM campaign.sessions WHERE session_id = :s"),
        {"s": session_id},
    ).scalar()
    assert period is None


def test_an_open_ended_session_has_an_unbounded_upper_range(
    db_connection: Connection, world_id: uuid.UUID, campaign_id: uuid.UUID
) -> None:
    start = make_world_time(db_connection, world_id, 100)
    session_id = make_session(db_connection, campaign_id, 1, start_world_time_id=start)

    row = db_connection.execute(
        text(
            "SELECT lower(world_time_period), upper_inf(world_time_period) "
            "FROM campaign.sessions WHERE session_id = :s"
        ),
        {"s": session_id},
    ).one()
    assert row[0] == 100
    assert row[1] is True


def test_a_bounded_session_derives_a_half_open_range(
    db_connection: Connection, world_id: uuid.UUID, campaign_id: uuid.UUID
) -> None:
    start = make_world_time(db_connection, world_id, 100)
    end = make_world_time(db_connection, world_id, 200)
    session_id = make_session(
        db_connection, campaign_id, 1, start_world_time_id=start, end_world_time_id=end
    )

    row = db_connection.execute(
        text(
            "SELECT lower(world_time_period), upper(world_time_period) "
            "FROM campaign.sessions WHERE session_id = :s"
        ),
        {"s": session_id},
    ).one()
    assert (row[0], row[1]) == (100, 200)


def test_sessions_may_still_overlap_with_a_derived_range(
    db_connection: Connection, world_id: uuid.UUID, campaign_id: uuid.UUID
) -> None:
    """The derived range is queryable but not exclusion-constrained —
    DATABASE_MODEL.md §6.4's overlap decision is unchanged by revision 023."""
    start = make_world_time(db_connection, world_id, 100)
    end = make_world_time(db_connection, world_id, 300)
    make_session(db_connection, campaign_id, 1, start_world_time_id=start, end_world_time_id=end)
    make_session(db_connection, campaign_id, 2, start_world_time_id=start, end_world_time_id=end)
