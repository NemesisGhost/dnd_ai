"""campaign.sessions (revision 011).

Sessions carry both real-world time (started_at/ended_at) and fictional time
(start/end_world_time_id) at once — deliberately, per DATABASE_CONVENTIONS.md
§12. Unlike party_memberships, there is no derived range and no exclusion
constraint: nothing requires sessions not to overlap in fictional time, so
only ordering and world agreement are enforced.
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

K0, K1, K2 = 100, 200, 300


@pytest.fixture
def world_id(db_connection: Connection) -> uuid.UUID:
    return make_world(db_connection, slug="session-world")


@pytest.fixture
def campaign_id(db_connection: Connection, world_id: uuid.UUID) -> uuid.UUID:
    timeline_id = make_timeline(db_connection, world_id, is_primary=True)
    return make_campaign(db_connection, timeline_id)


def test_sessions_are_numbered_within_a_campaign(
    db_connection: Connection, campaign_id: uuid.UUID
) -> None:
    make_session(db_connection, campaign_id, 1)
    make_session(db_connection, campaign_id, 2)

    count = db_connection.execute(
        text("SELECT count(*) FROM campaign.sessions WHERE campaign_id = :c"),
        {"c": campaign_id},
    ).scalar()
    assert count == 2


def test_duplicate_session_number_in_the_same_campaign_is_rejected(
    db_connection: Connection, campaign_id: uuid.UUID
) -> None:
    make_session(db_connection, campaign_id, 1)
    with pytest.raises(IntegrityError) as exc:
        make_session(db_connection, campaign_id, 1)
    assert "ux_sessions_campaign_number" in str(exc.value)


def test_the_same_session_number_is_fine_in_a_different_campaign(
    db_connection: Connection, world_id: uuid.UUID, campaign_id: uuid.UUID
) -> None:
    timeline_id = make_timeline(db_connection, world_id, name="Alt")
    other_campaign = make_campaign(db_connection, timeline_id, name="Other")

    make_session(db_connection, campaign_id, 1)
    make_session(db_connection, other_campaign, 1)


def test_session_number_must_be_positive(db_connection: Connection, campaign_id: uuid.UUID) -> None:
    with pytest.raises(IntegrityError) as exc:
        make_session(db_connection, campaign_id, 0)
    assert "ck_sessions_session_number_positive" in str(exc.value)


def test_an_end_without_a_start_is_rejected(
    db_connection: Connection, campaign_id: uuid.UUID
) -> None:
    with pytest.raises(IntegrityError) as exc:
        db_connection.execute(
            text("""
                INSERT INTO campaign.sessions
                    (campaign_id, session_number, lifecycle_status_id, ended_at)
                VALUES (:c, 1, (SELECT lifecycle_status_id FROM core.lifecycle_statuses
                                WHERE code = 'active'), now())
            """),
            {"c": campaign_id},
        )
    assert "ck_sessions_ended_requires_started" in str(exc.value)


def test_ended_before_started_is_rejected(
    db_connection: Connection, campaign_id: uuid.UUID
) -> None:
    with pytest.raises(IntegrityError) as exc:
        db_connection.execute(
            text("""
                INSERT INTO campaign.sessions
                    (campaign_id, session_number, lifecycle_status_id, started_at, ended_at)
                VALUES (:c, 1, (SELECT lifecycle_status_id FROM core.lifecycle_statuses
                                WHERE code = 'active'), now(), now() - interval '1 hour')
            """),
            {"c": campaign_id},
        )
    assert "ck_sessions_ended_after_started" in str(exc.value)


# ---------------------------------------------------------------------------
# World times: validation only — no overlap prevention
# ---------------------------------------------------------------------------


def test_start_and_end_world_times_are_accepted_in_order(
    db_connection: Connection, world_id: uuid.UUID, campaign_id: uuid.UUID
) -> None:
    start = make_world_time(db_connection, world_id, K0)
    end = make_world_time(db_connection, world_id, K1)
    make_session(db_connection, campaign_id, 1, start_world_time_id=start, end_world_time_id=end)


def test_an_end_world_time_without_a_start_is_rejected(
    db_connection: Connection, world_id: uuid.UUID, campaign_id: uuid.UUID
) -> None:
    end = make_world_time(db_connection, world_id, K1)
    with pytest.raises(IntegrityError) as exc:
        make_session(db_connection, campaign_id, 1, end_world_time_id=end)
    assert "ck_sessions_end_world_time_requires_start" in str(exc.value)


def test_end_world_time_before_start_is_rejected(
    db_connection: Connection, world_id: uuid.UUID, campaign_id: uuid.UUID
) -> None:
    start = make_world_time(db_connection, world_id, K1)
    end = make_world_time(db_connection, world_id, K0)
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_session(
            db_connection, campaign_id, 1, start_world_time_id=start, end_world_time_id=end
        )
    assert "must be later than its start" in str(exc.value)


def test_overlapping_sessions_are_not_rejected(
    db_connection: Connection, world_id: uuid.UUID, campaign_id: uuid.UUID
) -> None:
    """Deliberately not enforced: a flashback session, or two sessions each
    covering an overlapping stretch of story time, are legitimate."""
    start = make_world_time(db_connection, world_id, K0)
    end = make_world_time(db_connection, world_id, K2)
    make_session(db_connection, campaign_id, 1, start_world_time_id=start, end_world_time_id=end)
    make_session(db_connection, campaign_id, 2, start_world_time_id=start, end_world_time_id=end)


def test_a_world_time_from_another_world_is_rejected(
    db_connection: Connection, campaign_id: uuid.UUID
) -> None:
    other_world = make_world(db_connection, slug="session-other-world")
    foreign_time = make_world_time(db_connection, other_world, K0)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_session(db_connection, campaign_id, 1, start_world_time_id=foreign_time)
    assert "belongs to world" in str(exc.value)
