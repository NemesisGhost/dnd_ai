"""Tests for `dnd_ai.api.summary` — Phase 10 workstream 22's query
endpoint over `dnd_ai.queries.summary.get_campaign_summary_view` (docs/
PLAN.md Phase 10 "deterministic, audience-filtered summary and detail
query services for current campaign/session state, ... recent events, ...
and the prior-session recap"). Mirrors `tests/database/
test_api_dungeon.py`'s shape: `get_authenticated_user_id` is overridden
directly, since these tests exercise campaign-capability enforcement and
the draft-event audience split, not OIDC token verification.

Covers: access control (non-member 404, capless-member 403), current-
session/prior-session-recap resolution, recent-event ordering by fictional
world time (most recent first), that `voided` events are excluded for
every caller, that `draft` events are additionally excluded for a non-GM
caller, cross-campaign event exclusion, and the empty-campaign default
(no sessions/events at all).
"""

import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, text

from dnd_ai.api.app import create_app
from dnd_ai.api.auth import get_authenticated_user_id
from dnd_ai.api.deps import get_engine
from tests.factories import (
    lookup_id,
    make_campaign,
    make_campaign_membership,
    make_event,
    make_membership_role,
    make_role,
    make_role_capability,
    make_session,
    make_timeline,
    make_user,
    make_world,
    make_world_time,
)

pytestmark = pytest.mark.database


class Fixture:
    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        self.campaign_id = make_campaign(
            connection, self.timeline_id, lifecycle_status_code="pending"
        )
        self.other_campaign_id = make_campaign(
            connection, self.timeline_id, "Other Campaign", lifecycle_status_code="pending"
        )
        self.empty_campaign_id = make_campaign(
            connection, self.timeline_id, "Empty Campaign", lifecycle_status_code="pending"
        )

        now = datetime.now(UTC)
        self.session_1_id = make_session(
            connection,
            self.campaign_id,
            1,
            title="Prologue",
            summary="The party met in a tavern.",
            started_at=now - timedelta(days=7),
            ended_at=now - timedelta(days=7) + timedelta(hours=3),
        )
        self.session_2_id = make_session(
            connection,
            self.campaign_id,
            2,
            title="The Ruins",
            summary=None,
            started_at=now,
        )

        old_time_id = make_world_time(connection, self.world_id, 100)
        new_time_id = make_world_time(connection, self.world_id, 200)
        draft_time_id = make_world_time(connection, self.world_id, 300)
        voided_time_id = make_world_time(connection, self.world_id, 400)

        self.recorded_old_event_id = make_event(
            connection,
            self.world_id,
            self.timeline_id,
            old_time_id,
            campaign_id=self.campaign_id,
            event_status_code="recorded",
            name="Old Recorded Event",
        )
        self.recorded_new_event_id = make_event(
            connection,
            self.world_id,
            self.timeline_id,
            new_time_id,
            campaign_id=self.campaign_id,
            event_status_code="recorded",
            name="New Recorded Event",
        )
        self.draft_event_id = make_event(
            connection,
            self.world_id,
            self.timeline_id,
            draft_time_id,
            campaign_id=self.campaign_id,
            event_status_code="draft",
            name="Draft Event",
        )
        self.voided_event_id = make_event(
            connection,
            self.world_id,
            self.timeline_id,
            voided_time_id,
            campaign_id=self.campaign_id,
            event_status_code="voided",
            name="Voided Event",
        )
        # Tied to a different campaign — proves campaign filtering.
        make_event(
            connection,
            self.world_id,
            self.timeline_id,
            new_time_id,
            campaign_id=self.other_campaign_id,
            event_status_code="recorded",
            name="Other Campaign Event",
        )

        view_capability_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "campaign.view"
        )
        canon_edit_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "canon.edit"
        )

        self.gm_user_id = make_user(connection, "Summary Query GM")
        gm_membership_id = make_campaign_membership(connection, self.campaign_id, self.gm_user_id)
        gm_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"gm_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, gm_role_id, view_capability_id)
        make_role_capability(connection, gm_role_id, canon_edit_id)
        make_membership_role(connection, gm_membership_id, gm_role_id)

        self.player_user_id = make_user(connection, "Summary Query Player")
        player_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.player_user_id
        )
        player_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"player_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, player_role_id, view_capability_id)
        make_membership_role(connection, player_membership_id, player_role_id)

        # A member with no role/capability at all — proves ForbiddenError,
        # distinct from a non-member's NotFoundError.
        self.capless_user_id = make_user(connection, "Summary Query Capless Member")
        make_campaign_membership(connection, self.campaign_id, self.capless_user_id)

        # Never given a membership at all.
        self.outsider_user_id = make_user(connection, "Summary Query Outsider")

        # A member of the empty campaign, to exercise the no-sessions/no-
        # events default.
        self.empty_campaign_user_id = make_user(connection, "Summary Query Empty Campaign Member")
        empty_membership_id = make_campaign_membership(
            connection, self.empty_campaign_id, self.empty_campaign_user_id
        )
        empty_role_id = make_role(
            connection, campaign_id=self.empty_campaign_id, code=f"viewer_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, empty_role_id, view_capability_id)
        make_membership_role(connection, empty_membership_id, empty_role_id)


@pytest.fixture
def f(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as connection:
        fixture = Fixture(connection, f"summary-query-{uuid.uuid4().hex[:8]}")
    yield fixture
    with postgres_engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        # See tests/database/test_api_dungeon.py's identical cleanup
        # comment for why session_replication_role = replica and explicit,
        # dependency-ordered deletes are used here.
        cleanup.execute(
            text("""
                DELETE FROM security.membership_roles WHERE role_id IN (
                    SELECT role_id FROM security.roles WHERE campaign_id IN (
                        SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t
                    )
                )
            """),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM security.role_capabilities WHERE role_id IN (
                    SELECT role_id FROM security.roles WHERE campaign_id IN (
                        SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t
                    )
                )
            """),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text(
                "DELETE FROM security.roles WHERE campaign_id IN "
                "(SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t)"
            ),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text(
                "DELETE FROM security.campaign_memberships WHERE campaign_id IN "
                "(SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t)"
            ),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text(
                "DELETE FROM campaign.sessions WHERE campaign_id IN "
                "(SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t)"
            ),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text("DELETE FROM campaign.campaigns WHERE timeline_id = :t"),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text("DELETE FROM core.entities WHERE world_id = :w"), {"w": fixture.world_id}
        )
        cleanup.execute(
            text("DELETE FROM core.worlds WHERE world_id = :w"), {"w": fixture.world_id}
        )
        cleanup.execute(
            text("DELETE FROM security.users WHERE user_id = ANY(:users)"),
            {
                "users": [
                    fixture.gm_user_id,
                    fixture.player_user_id,
                    fixture.capless_user_id,
                    fixture.outsider_user_id,
                    fixture.empty_campaign_user_id,
                ]
            },
        )


@pytest.fixture
def client_factory(postgres_engine: Engine) -> Callable[[uuid.UUID], TestClient]:
    def _make(user_id: uuid.UUID) -> TestClient:
        app = create_app()
        app.dependency_overrides[get_engine] = lambda: postgres_engine
        app.dependency_overrides[get_authenticated_user_id] = lambda: user_id
        return TestClient(app, raise_server_exceptions=False)

    return _make


def _summary_url(f: Fixture, campaign_id: uuid.UUID | None = None) -> str:
    return f"/campaigns/{campaign_id or f.campaign_id}/summary"


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


def test_a_non_member_gets_not_found(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.outsider_user_id) as client:
        response = client.get(_summary_url(f))
    assert response.status_code == 404


def test_a_member_without_campaign_view_gets_forbidden(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.capless_user_id) as client:
        response = client.get(_summary_url(f))
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Session state and recap
# ---------------------------------------------------------------------------


def test_current_session_is_the_highest_numbered_session(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.get(_summary_url(f))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["current_session"]["session_id"] == str(f.session_2_id)
    assert body["current_session"]["title"] == "The Ruins"
    assert body["current_session"]["ended_at"] is None


def test_previous_session_recap_is_the_most_recently_ended_sessions_summary(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.get(_summary_url(f))
    assert response.status_code == 200, response.text
    assert response.json()["previous_session_recap"] == "The party met in a tavern."


def test_an_empty_campaign_has_no_session_or_recap(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.empty_campaign_user_id) as client:
        response = client.get(_summary_url(f, campaign_id=f.empty_campaign_id))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["current_session"] is None
    assert body["previous_session_recap"] is None
    assert body["recent_events"] == []


# ---------------------------------------------------------------------------
# Recent events: ordering, voided exclusion, draft audience split
# ---------------------------------------------------------------------------


def test_a_gm_sees_recorded_and_draft_events_ordered_most_recent_first(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.get(_summary_url(f))
    assert response.status_code == 200, response.text
    event_ids = [e["event_id"] for e in response.json()["recent_events"]]
    assert event_ids == [
        str(f.draft_event_id),
        str(f.recorded_new_event_id),
        str(f.recorded_old_event_id),
    ]


def test_a_player_never_sees_draft_or_voided_events(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.player_user_id) as client:
        response = client.get(_summary_url(f))
    assert response.status_code == 200, response.text
    event_ids = {e["event_id"] for e in response.json()["recent_events"]}
    assert event_ids == {str(f.recorded_new_event_id), str(f.recorded_old_event_id)}


def test_voided_events_are_excluded_even_for_a_gm(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.get(_summary_url(f))
    assert response.status_code == 200, response.text
    event_ids = {e["event_id"] for e in response.json()["recent_events"]}
    assert str(f.voided_event_id) not in event_ids


def test_events_from_a_different_campaign_are_excluded(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.get(_summary_url(f))
    assert response.status_code == 200, response.text
    names = {e["name"] for e in response.json()["recent_events"]}
    assert "Other Campaign Event" not in names
