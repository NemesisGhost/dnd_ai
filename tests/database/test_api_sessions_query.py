"""Tests for `dnd_ai.api.sessions`'s read side — Phase 13D backend-
readiness workstream's `GET /campaigns/{campaign_id}/sessions` (list) and
`GET /campaigns/{campaign_id}/sessions/{session_id}` (detail), added
because the portal's Session detail screen (docs/UI_DESIGN.md §5.8) had no
endpoint to call at all before this (only the GM-only `POST .../end`
write existed).

Covers: access control (non-member 404, capless-member 403), the list's
ordering and shape, the detail's own fields plus its session-scoped
events, the draft/voided event-visibility split (mirroring `dnd_ai.api.
summary`'s already-tested rule), a per-session `campaign.view`
resource-grant deny hiding a session from both the list and the direct
detail route (a previously untested security-sensitive contract — no route
existed to exercise `security.resource_grants.session_id` before this),
and cross-campaign/nonexistent-session rejection.
"""

import uuid
from collections.abc import Callable, Iterator

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
    make_resource_grant,
    make_role,
    make_role_capability,
    make_session,
    make_timeline,
    make_user,
    make_world,
    make_world_time,
    oidc_principal,
)

pytestmark = pytest.mark.database


class Fixture:
    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        self.world_time_id = make_world_time(connection, self.world_id, 100)
        self.campaign_id = make_campaign(
            connection, self.timeline_id, lifecycle_status_code="pending"
        )

        self.session_1_id = make_session(
            connection, self.campaign_id, 1, title="The Beginning", summary="They met."
        )
        self.session_2_id = make_session(
            connection, self.campaign_id, 2, title="Deeper In", summary="They descended."
        )

        # A recorded and a draft event on session 1 — proves the draft
        # split; a voided one proves it is excluded for every caller.
        self.recorded_event_id = make_event(
            connection,
            self.world_id,
            self.timeline_id,
            self.world_time_id,
            campaign_id=self.campaign_id,
            session_id=self.session_1_id,
            event_status_code="recorded",
            name="A recorded event",
        )
        self.draft_event_id = make_event(
            connection,
            self.world_id,
            self.timeline_id,
            self.world_time_id,
            campaign_id=self.campaign_id,
            session_id=self.session_1_id,
            event_status_code="draft",
            name="A draft event",
        )
        self.voided_event_id = make_event(
            connection,
            self.world_id,
            self.timeline_id,
            self.world_time_id,
            campaign_id=self.campaign_id,
            session_id=self.session_1_id,
            event_status_code="voided",
            name="A voided event",
        )

        # A second, unrelated campaign — its session proves the
        # cross-campaign ownership check.
        self.other_world_id = make_world(connection, slug=f"{slug}-other-world")
        other_timeline_id = make_timeline(connection, self.other_world_id, is_primary=True)
        self.other_campaign_id = make_campaign(
            connection, other_timeline_id, lifecycle_status_code="pending"
        )
        self.other_campaign_session_id = make_session(connection, self.other_campaign_id, 1)

        view_capability_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "campaign.view"
        )
        canon_edit_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "canon.edit"
        )
        self.view_capability_id = view_capability_id
        self.canon_edit_capability_id = canon_edit_id

        self.gm_user_id = make_user(connection, "Session Query GM")
        gm_membership_id = make_campaign_membership(connection, self.campaign_id, self.gm_user_id)
        self.gm_membership_id = gm_membership_id
        gm_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"gm_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, gm_role_id, view_capability_id)
        make_role_capability(connection, gm_role_id, canon_edit_id)
        make_membership_role(connection, gm_membership_id, gm_role_id)

        self.player_user_id = make_user(connection, "Session Query Player")
        player_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.player_user_id
        )
        self.player_membership_id = player_membership_id
        player_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"player_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, player_role_id, view_capability_id)
        make_membership_role(connection, player_membership_id, player_role_id)

        # A member with no role/capability at all — proves ForbiddenError,
        # distinct from a non-member's NotFoundError.
        self.capless_user_id = make_user(connection, "Session Query Capless Member")
        make_campaign_membership(connection, self.campaign_id, self.capless_user_id)

        # Never given a membership at all.
        self.outsider_user_id = make_user(connection, "Session Query Outsider")


@pytest.fixture
def f(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as connection:
        fixture = Fixture(connection, f"session-query-{uuid.uuid4().hex[:8]}")
    yield fixture
    with postgres_engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        for world_id in (fixture.world_id, fixture.other_world_id):
            cleanup.execute(
                text("""
                    DELETE FROM security.resource_grants WHERE campaign_id IN (
                        SELECT campaign_id FROM campaign.campaigns WHERE timeline_id IN (
                            SELECT timeline_id FROM campaign.timelines WHERE world_id = :w
                        )
                    )
                """),
                {"w": world_id},
            )
            cleanup.execute(
                text("""
                    DELETE FROM security.membership_roles WHERE role_id IN (
                        SELECT role_id FROM security.roles WHERE campaign_id IN (
                            SELECT campaign_id FROM campaign.campaigns WHERE timeline_id IN (
                                SELECT timeline_id FROM campaign.timelines WHERE world_id = :w
                            )
                        )
                    )
                """),
                {"w": world_id},
            )
            cleanup.execute(
                text("""
                    DELETE FROM security.role_capabilities WHERE role_id IN (
                        SELECT role_id FROM security.roles WHERE campaign_id IN (
                            SELECT campaign_id FROM campaign.campaigns WHERE timeline_id IN (
                                SELECT timeline_id FROM campaign.timelines WHERE world_id = :w
                            )
                        )
                    )
                """),
                {"w": world_id},
            )
            cleanup.execute(
                text("""
                    DELETE FROM security.roles WHERE campaign_id IN (
                        SELECT campaign_id FROM campaign.campaigns WHERE timeline_id IN (
                            SELECT timeline_id FROM campaign.timelines WHERE world_id = :w
                        )
                    )
                """),
                {"w": world_id},
            )
            cleanup.execute(
                text("""
                    DELETE FROM security.campaign_memberships WHERE campaign_id IN (
                        SELECT campaign_id FROM campaign.campaigns WHERE timeline_id IN (
                            SELECT timeline_id FROM campaign.timelines WHERE world_id = :w
                        )
                    )
                """),
                {"w": world_id},
            )
            cleanup.execute(
                text("""
                    DELETE FROM campaign.sessions WHERE campaign_id IN (
                        SELECT campaign_id FROM campaign.campaigns WHERE timeline_id IN (
                            SELECT timeline_id FROM campaign.timelines WHERE world_id = :w
                        )
                    )
                """),
                {"w": world_id},
            )
            cleanup.execute(
                text("""
                    DELETE FROM campaign.campaigns WHERE timeline_id IN (
                        SELECT timeline_id FROM campaign.timelines WHERE world_id = :w
                    )
                """),
                {"w": world_id},
            )
            cleanup.execute(
                text("DELETE FROM campaign.timelines WHERE world_id = :w"), {"w": world_id}
            )
            cleanup.execute(text("DELETE FROM core.entities WHERE world_id = :w"), {"w": world_id})
            cleanup.execute(text("DELETE FROM core.worlds WHERE world_id = :w"), {"w": world_id})
        cleanup.execute(
            text("DELETE FROM security.users WHERE user_id = ANY(:users)"),
            {
                "users": [
                    fixture.gm_user_id,
                    fixture.player_user_id,
                    fixture.capless_user_id,
                    fixture.outsider_user_id,
                ]
            },
        )


@pytest.fixture
def client_factory(postgres_engine: Engine) -> Callable[[uuid.UUID], TestClient]:
    def _make(user_id: uuid.UUID) -> TestClient:
        app = create_app()
        app.dependency_overrides[get_engine] = lambda: postgres_engine
        app.dependency_overrides[get_authenticated_user_id] = lambda: oidc_principal(user_id)
        return TestClient(app, raise_server_exceptions=False)

    return _make


def _list_url(f: Fixture) -> str:
    return f"/campaigns/{f.campaign_id}/sessions"


def _detail_url(f: Fixture, session_id: uuid.UUID | None = None) -> str:
    return f"/campaigns/{f.campaign_id}/sessions/{session_id or f.session_1_id}"


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


def test_list_a_non_member_gets_not_found(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.outsider_user_id) as client:
        response = client.get(_list_url(f))
    assert response.status_code == 404


def test_list_a_member_without_campaign_view_gets_forbidden(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.capless_user_id) as client:
        response = client.get(_list_url(f))
    assert response.status_code == 403


def test_detail_a_non_member_gets_not_found(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.outsider_user_id) as client:
        response = client.get(_detail_url(f))
    assert response.status_code == 404


def test_detail_a_member_without_campaign_view_gets_forbidden(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.capless_user_id) as client:
        response = client.get(_detail_url(f))
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# List shape and ordering
# ---------------------------------------------------------------------------


def test_list_returns_every_session_most_recent_first(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.player_user_id) as client:
        response = client.get(_list_url(f))
    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["session_id"] for item in body] == [str(f.session_2_id), str(f.session_1_id)]
    assert body[1]["title"] == "The Beginning"
    assert body[1]["session_number"] == 1


# ---------------------------------------------------------------------------
# Detail fields and session-scoped events
# ---------------------------------------------------------------------------


def test_detail_returns_session_fields(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.player_user_id) as client:
        response = client.get(_detail_url(f))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["session_id"] == str(f.session_1_id)
    assert body["session_number"] == 1
    assert body["title"] == "The Beginning"
    assert body["summary"] == "They met."


def test_a_player_never_sees_a_draft_event_in_the_session(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.player_user_id) as client:
        response = client.get(_detail_url(f))
    assert response.status_code == 200, response.text
    event_ids = {e["event_id"] for e in response.json()["events"]}
    assert event_ids == {str(f.recorded_event_id)}


def test_a_gm_sees_the_draft_event_but_never_the_voided_one(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.get(_detail_url(f))
    assert response.status_code == 200, response.text
    event_ids = {e["event_id"] for e in response.json()["events"]}
    assert event_ids == {str(f.recorded_event_id), str(f.draft_event_id)}


# ---------------------------------------------------------------------------
# Per-session resource-grant deny (previously untested — no route existed
# to exercise security.resource_grants.session_id before this workstream)
# ---------------------------------------------------------------------------


def test_a_targeted_deny_hides_the_session_from_the_list(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with postgres_engine.begin() as setup:
        make_resource_grant(
            setup,
            f.campaign_id,
            f.view_capability_id,
            session_id=f.session_1_id,
            grantee_campaign_membership_id=f.player_membership_id,
            effect="deny",
        )

    with client_factory(f.player_user_id) as client:
        response = client.get(_list_url(f))
    assert response.status_code == 200, response.text
    session_ids = {item["session_id"] for item in response.json()}
    assert session_ids == {str(f.session_2_id)}


def test_a_targeted_deny_hides_the_session_from_direct_detail_access(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """A role-derived campaign.view holder is still rejected identically to
    a nonexistent session — the deny is never merely a list-time filter."""
    with postgres_engine.begin() as setup:
        make_resource_grant(
            setup,
            f.campaign_id,
            f.view_capability_id,
            session_id=f.session_1_id,
            grantee_campaign_membership_id=f.player_membership_id,
            effect="deny",
        )

    with client_factory(f.player_user_id) as client:
        response = client.get(_detail_url(f))
    assert response.status_code == 404


def test_the_deny_does_not_affect_a_different_member(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with postgres_engine.begin() as setup:
        make_resource_grant(
            setup,
            f.campaign_id,
            f.view_capability_id,
            session_id=f.session_1_id,
            grantee_campaign_membership_id=f.player_membership_id,
            effect="deny",
        )

    with client_factory(f.gm_user_id) as client:
        response = client.get(_detail_url(f))
    assert response.status_code == 200, response.text
    assert response.json()["session_id"] == str(f.session_1_id)


# ---------------------------------------------------------------------------
# Cross-campaign ownership and existence
# ---------------------------------------------------------------------------


def test_a_session_in_a_different_campaign_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.get(_detail_url(f, f.other_campaign_session_id))
    assert response.status_code == 404


def test_a_nonexistent_session_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.get(_detail_url(f, uuid.uuid4()))
    assert response.status_code == 404
