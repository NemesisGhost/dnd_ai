"""`dnd_ai.commands.user_preferences` and the preference read path of
`dnd_ai.queries.bootstrap.get_session_bootstrap` against real PostgreSQL
(docs/UI_DESIGN.md §4.2, §4.7).

HTTP-layer behavior (CSRF, Origin, 401/404 bodies) lives in
`tests/database/test_api_user_preferences.py`.
"""

import uuid

import pytest
from sqlalchemy import Connection, text

from dnd_ai.commands.user_preferences import (
    CampaignNotAvailableError,
    record_last_visited_campaign,
    set_campaign_startup_preference,
)
from dnd_ai.queries.bootstrap import (
    get_session_bootstrap,
    is_campaign_bootstrap_authorized,
    list_bootstrap_campaign_ids,
)
from tests.factories import (
    make_campaign,
    make_campaign_membership,
    make_timeline,
    make_user,
    make_world,
)

pytestmark = pytest.mark.database


@pytest.fixture
def timeline_id(db_connection: Connection) -> uuid.UUID:
    world_id = make_world(db_connection, slug=f"prefs-{uuid.uuid4().hex[:8]}")
    return make_timeline(db_connection, world_id, is_primary=True)


@pytest.fixture
def user_id(db_connection: Connection) -> uuid.UUID:
    return make_user(db_connection, "Preference Tester")


def _row(db_connection: Connection, user_id: uuid.UUID) -> dict[str, object] | None:
    row = (
        db_connection.execute(
            text(
                "SELECT preferred_campaign_id, last_visited_campaign_id "
                "FROM security.user_portal_preferences WHERE user_id = :u"
            ),
            {"u": user_id},
        )
        .mappings()
        .one_or_none()
    )
    return dict(row) if row is not None else None


def _member_of(
    db_connection: Connection, timeline_id: uuid.UUID, user_id: uuid.UUID, name: str
) -> uuid.UUID:
    campaign_id = make_campaign(db_connection, timeline_id, name)
    make_campaign_membership(db_connection, campaign_id, user_id)
    return campaign_id


def _change_log_count(db_connection: Connection) -> int:
    return int(db_connection.execute(text("SELECT count(*) FROM audit.change_log")).scalar_one())


# ---------------------------------------------------------------------------
# set_campaign_startup_preference
# ---------------------------------------------------------------------------


def test_startup_preference_stores_authorized_campaign_only_in_its_own_column(
    db_connection: Connection, timeline_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    a = _member_of(db_connection, timeline_id, user_id, "A")
    b = _member_of(db_connection, timeline_id, user_id, "B")
    record_last_visited_campaign(db_connection, user_id=user_id, campaign_id=a)

    set_campaign_startup_preference(db_connection, user_id=user_id, preferred_campaign_id=b)

    assert _row(db_connection, user_id) == {
        "preferred_campaign_id": b,
        "last_visited_campaign_id": a,
    }


def test_startup_preference_none_clears_without_touching_last_visited(
    db_connection: Connection, timeline_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    a = _member_of(db_connection, timeline_id, user_id, "A")
    b = _member_of(db_connection, timeline_id, user_id, "B")
    set_campaign_startup_preference(db_connection, user_id=user_id, preferred_campaign_id=a)
    record_last_visited_campaign(db_connection, user_id=user_id, campaign_id=b)

    set_campaign_startup_preference(db_connection, user_id=user_id, preferred_campaign_id=None)

    assert _row(db_connection, user_id) == {
        "preferred_campaign_id": None,
        "last_visited_campaign_id": b,
    }


def test_clearing_with_no_existing_row_is_harmless(
    db_connection: Connection, user_id: uuid.UUID
) -> None:
    set_campaign_startup_preference(db_connection, user_id=user_id, preferred_campaign_id=None)
    assert _row(db_connection, user_id) == {
        "preferred_campaign_id": None,
        "last_visited_campaign_id": None,
    }


@pytest.mark.parametrize("situation", ["non_member", "ended", "archived", "unknown"])
def test_unavailable_campaigns_are_rejected_identically_and_nothing_is_written(
    db_connection: Connection, timeline_id: uuid.UUID, user_id: uuid.UUID, situation: str
) -> None:
    if situation == "non_member":
        target = make_campaign(db_connection, timeline_id, "Not mine")
    elif situation == "ended":
        target = make_campaign(db_connection, timeline_id, "Departed")
        make_campaign_membership(db_connection, target, user_id, ended=True)
    elif situation == "archived":
        target = make_campaign(db_connection, timeline_id, "Old", lifecycle_status_code="archived")
        make_campaign_membership(db_connection, target, user_id)
    else:
        target = uuid.uuid4()

    with pytest.raises(CampaignNotAvailableError) as startup_error:
        set_campaign_startup_preference(
            db_connection, user_id=user_id, preferred_campaign_id=target
        )
    with pytest.raises(CampaignNotAvailableError) as visited_error:
        record_last_visited_campaign(db_connection, user_id=user_id, campaign_id=target)

    assert startup_error.value.safe_message == visited_error.value.safe_message
    assert str(target) not in startup_error.value.safe_message
    assert _row(db_connection, user_id) is None


# ---------------------------------------------------------------------------
# record_last_visited_campaign
# ---------------------------------------------------------------------------


def test_last_visited_is_stored_idempotently_and_leaves_preferred_alone(
    db_connection: Connection, timeline_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    a = _member_of(db_connection, timeline_id, user_id, "A")
    b = _member_of(db_connection, timeline_id, user_id, "B")
    set_campaign_startup_preference(db_connection, user_id=user_id, preferred_campaign_id=a)

    record_last_visited_campaign(db_connection, user_id=user_id, campaign_id=b)
    record_last_visited_campaign(db_connection, user_id=user_id, campaign_id=b)

    assert _row(db_connection, user_id) == {
        "preferred_campaign_id": a,
        "last_visited_campaign_id": b,
    }
    count = db_connection.execute(
        text("SELECT count(*) FROM security.user_portal_preferences WHERE user_id = :u"),
        {"u": user_id},
    ).scalar_one()
    assert count == 1


def test_preference_writes_record_no_audit_change_log_row(
    db_connection: Connection, timeline_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    a = _member_of(db_connection, timeline_id, user_id, "A")
    before = _change_log_count(db_connection)
    set_campaign_startup_preference(db_connection, user_id=user_id, preferred_campaign_id=a)
    record_last_visited_campaign(db_connection, user_id=user_id, campaign_id=a)
    assert _change_log_count(db_connection) == before


# ---------------------------------------------------------------------------
# Shared authorization scope
# ---------------------------------------------------------------------------


def test_authorization_helper_agrees_with_the_bootstrap_campaign_list(
    db_connection: Connection, timeline_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    listed = _member_of(db_connection, timeline_id, user_id, "Listed")
    ended = make_campaign(db_connection, timeline_id, "Ended")
    make_campaign_membership(db_connection, ended, user_id, ended=True)
    archived = make_campaign(db_connection, timeline_id, "Arch", lifecycle_status_code="archived")
    make_campaign_membership(db_connection, archived, user_id)
    stranger = make_campaign(db_connection, timeline_id, "Stranger")

    bootstrap_ids = [
        c.campaign_id for c in get_session_bootstrap(db_connection, user_id=user_id).campaigns
    ]

    assert bootstrap_ids == list_bootstrap_campaign_ids(db_connection, user_id=user_id) == [listed]
    for campaign_id in (listed, ended, archived, stranger):
        assert is_campaign_bootstrap_authorized(
            db_connection, user_id=user_id, campaign_id=campaign_id
        ) == (campaign_id in bootstrap_ids)


# ---------------------------------------------------------------------------
# Bootstrap read path
# ---------------------------------------------------------------------------


def test_bootstrap_without_a_row_defaults_and_get_does_not_create_one(
    db_connection: Connection, timeline_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    _member_of(db_connection, timeline_id, user_id, "A")
    _member_of(db_connection, timeline_id, user_id, "B")

    bootstrap = get_session_bootstrap(db_connection, user_id=user_id)

    assert bootstrap.startup_campaign_id is None
    assert bootstrap.campaign_preferences.startup_mode == "resume_last_visited"
    assert _row(db_connection, user_id) is None


def test_bootstrap_single_campaign_is_the_startup_campaign(
    db_connection: Connection, timeline_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    only = _member_of(db_connection, timeline_id, user_id, "Only")
    assert get_session_bootstrap(db_connection, user_id=user_id).startup_campaign_id == only


def test_bootstrap_reports_preferred_mode_and_last_visited(
    db_connection: Connection, timeline_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    a = _member_of(db_connection, timeline_id, user_id, "A")
    b = _member_of(db_connection, timeline_id, user_id, "B")
    _member_of(db_connection, timeline_id, user_id, "C")
    set_campaign_startup_preference(db_connection, user_id=user_id, preferred_campaign_id=b)
    record_last_visited_campaign(db_connection, user_id=user_id, campaign_id=a)

    bootstrap = get_session_bootstrap(db_connection, user_id=user_id)

    assert bootstrap.startup_campaign_id == b
    assert bootstrap.campaign_preferences.startup_mode == "preferred_campaign"
    assert bootstrap.campaign_preferences.preferred_campaign_id == b
    assert bootstrap.campaign_preferences.last_visited_campaign_id == a


def test_bootstrap_resumes_last_visited_when_no_preferred(
    db_connection: Connection, timeline_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    _member_of(db_connection, timeline_id, user_id, "A")
    b = _member_of(db_connection, timeline_id, user_id, "B")
    record_last_visited_campaign(db_connection, user_id=user_id, campaign_id=b)

    bootstrap = get_session_bootstrap(db_connection, user_id=user_id)

    assert bootstrap.startup_campaign_id == b
    assert bootstrap.campaign_preferences.startup_mode == "resume_last_visited"


def test_revoked_preferred_membership_is_ignored_and_falls_back(
    db_connection: Connection, timeline_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    a = _member_of(db_connection, timeline_id, user_id, "A")
    b = _member_of(db_connection, timeline_id, user_id, "B")
    _member_of(db_connection, timeline_id, user_id, "C")
    set_campaign_startup_preference(db_connection, user_id=user_id, preferred_campaign_id=b)
    record_last_visited_campaign(db_connection, user_id=user_id, campaign_id=a)

    db_connection.execute(
        text(
            "UPDATE security.campaign_memberships "
            "SET ended_at = joined_at + interval '1 second' "
            "WHERE campaign_id = :c AND user_id = :u"
        ),
        {"c": b, "u": user_id},
    )
    bootstrap = get_session_bootstrap(db_connection, user_id=user_id)

    assert bootstrap.campaign_preferences.preferred_campaign_id is None
    assert bootstrap.campaign_preferences.startup_mode == "resume_last_visited"
    assert bootstrap.startup_campaign_id == a
    assert b not in {c.campaign_id for c in bootstrap.campaigns}


def test_archived_last_visited_is_ignored(
    db_connection: Connection, timeline_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    _member_of(db_connection, timeline_id, user_id, "A")
    b = _member_of(db_connection, timeline_id, user_id, "B")
    _member_of(db_connection, timeline_id, user_id, "C")
    record_last_visited_campaign(db_connection, user_id=user_id, campaign_id=b)
    db_connection.execute(
        text(
            "UPDATE campaign.campaigns SET lifecycle_status_id = "
            "(SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'archived') "
            "WHERE campaign_id = :c"
        ),
        {"c": b},
    )

    bootstrap = get_session_bootstrap(db_connection, user_id=user_id)

    assert bootstrap.campaign_preferences.last_visited_campaign_id is None
    assert bootstrap.startup_campaign_id is None
