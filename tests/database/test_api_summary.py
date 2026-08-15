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
caller, cross-campaign event exclusion, the empty-campaign default (no
sessions/events at all), and — the untargeted-`canon.edit` correction
pass's central concern — that a `security.resource_grants` `event_id`
target is honored per event even though this endpoint returns a *list*:
a direct or access-group-inherited deny hides one specific draft from an
otherwise-role-derived GM, a targeted allow exposes one specific draft to
an otherwise non-GM caller (and only that one), mixed grants across
several events in the same response resolve independently per event, a
denied draft never consumes one of the response's `_RECENT_EVENTS_LIMIT`
slots (an older, genuinely visible event backfills it instead), ordering
stays deterministic regardless of grant status, and `recorded`/`corrected`
visibility and universal `voided` exclusion are both unaffected by any
event-targeted `canon.edit` grant.
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
    make_access_group,
    make_access_group_membership,
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
        self.canon_edit_capability_id = canon_edit_id

        self.gm_user_id = make_user(connection, "Summary Query GM")
        gm_membership_id = make_campaign_membership(connection, self.campaign_id, self.gm_user_id)
        self.gm_membership_id = gm_membership_id
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
        self.player_membership_id = player_membership_id
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
        # security.resource_grants/access_group_memberships/access_groups
        # are created ad hoc by individual tests below (the untargeted
        # canon.edit correction pass's event-targeted deny/allow regression
        # tests), never by the shared Fixture itself — cleaned up here,
        # scoped by timeline_id (covers any campaign a test creates under
        # fixture.timeline_id too, including the dedicated "limit" campaign
        # some tests use), before the campaign_memberships/access_groups
        # rows they reference are removed. See tests/database/
        # test_api_characters.py's identical cleanup for the same pattern.
        cleanup.execute(
            text(
                "DELETE FROM security.resource_grants WHERE campaign_id IN "
                "(SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t)"
            ),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM security.access_group_memberships WHERE access_group_id IN (
                    SELECT access_group_id FROM security.access_groups WHERE campaign_id IN (
                        SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t
                    )
                )
            """),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text(
                "DELETE FROM security.access_groups WHERE campaign_id IN "
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


# ---------------------------------------------------------------------------
# Resource-grant overrides for per-event draft visibility
# (canon.edit, event_id target)
#
# get_campaign_summary_endpoint used to compute one untargeted
# access.has_capability("canon.edit") boolean for the whole recent_events
# list, so an event-targeted security.resource_grants deny/allow was never
# consulted at all. These tests prove the fixed, per-event resolution
# (AccessContext.resource_grant_targets, applied inside
# dnd_ai.queries.summary.get_campaign_summary_view's own query) honors a
# targeted deny/allow per row, that a denied draft never consumes a
# response slot, that ordering stays deterministic, and that
# recorded/corrected visibility and universal voided exclusion are
# unaffected by any event-targeted canon.edit grant.
# ---------------------------------------------------------------------------


def test_a_direct_event_targeted_deny_hides_that_draft_from_a_role_derived_gm(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with postgres_engine.begin() as setup:
        make_resource_grant(
            setup,
            f.campaign_id,
            f.canon_edit_capability_id,
            event_id=f.draft_event_id,
            grantee_campaign_membership_id=f.gm_membership_id,
            effect="deny",
        )

    with client_factory(f.gm_user_id) as client:
        response = client.get(_summary_url(f))
    assert response.status_code == 200, response.text
    event_ids = [e["event_id"] for e in response.json()["recent_events"]]
    assert str(f.draft_event_id) not in event_ids
    assert event_ids == [str(f.recorded_new_event_id), str(f.recorded_old_event_id)]


def test_an_event_targeted_deny_via_access_group_also_hides_the_draft(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """Identical to the direct-membership deny above, but inherited through
    security.access_group_memberships rather than granted straight to
    f.gm_membership_id — proving the fix applies uniformly regardless of
    how the grant reaches the caller."""
    with postgres_engine.begin() as setup:
        access_group_id = make_access_group(setup, f.campaign_id)
        make_access_group_membership(setup, access_group_id, f.gm_membership_id)
        make_resource_grant(
            setup,
            f.campaign_id,
            f.canon_edit_capability_id,
            event_id=f.draft_event_id,
            grantee_access_group_id=access_group_id,
            effect="deny",
        )

    with client_factory(f.gm_user_id) as client:
        response = client.get(_summary_url(f))
    assert response.status_code == 200, response.text
    event_ids = {e["event_id"] for e in response.json()["recent_events"]}
    assert str(f.draft_event_id) not in event_ids


def test_a_targeted_allow_exposes_only_that_draft_to_a_non_gm_caller(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """f.player_user_id holds campaign.view only — no role-derived
    canon.edit. A second, ungranted draft event proves the allow exposes
    exactly the one targeted draft, not every draft — an allow is not a
    backdoor into include_draft_events entirely."""
    with postgres_engine.begin() as setup:
        other_draft_time_id = make_world_time(setup, f.world_id, 250)
        other_draft_event_id = make_event(
            setup,
            f.world_id,
            f.timeline_id,
            other_draft_time_id,
            campaign_id=f.campaign_id,
            event_status_code="draft",
            name="Other Draft Event",
        )
        make_resource_grant(
            setup,
            f.campaign_id,
            f.canon_edit_capability_id,
            event_id=f.draft_event_id,
            grantee_campaign_membership_id=f.player_membership_id,
            effect="allow",
        )

    with client_factory(f.player_user_id) as client:
        response = client.get(_summary_url(f))
    assert response.status_code == 200, response.text
    event_ids = {e["event_id"] for e in response.json()["recent_events"]}
    assert event_ids == {
        str(f.draft_event_id),
        str(f.recorded_new_event_id),
        str(f.recorded_old_event_id),
    }
    assert str(other_draft_event_id) not in event_ids


def test_mixed_allow_and_deny_grants_are_evaluated_independently_per_event(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """A role-derived GM with three drafts in play at once: one explicitly
    denied (hidden despite the role-derived baseline), one explicitly
    allowed (redundant with the baseline but must not be disturbed by the
    other grant), and one with no grant at all (visible on the baseline
    alone) — proving each event's visibility is resolved from its own
    grant, never contaminated by another event's, and that ordering by
    fictional world time still holds regardless of grant status."""
    with postgres_engine.begin() as setup:
        denied_time_id = make_world_time(setup, f.world_id, 350)
        denied_draft_event_id = make_event(
            setup,
            f.world_id,
            f.timeline_id,
            denied_time_id,
            campaign_id=f.campaign_id,
            event_status_code="draft",
            name="Denied Draft",
        )
        allowed_time_id = make_world_time(setup, f.world_id, 250)
        allowed_draft_event_id = make_event(
            setup,
            f.world_id,
            f.timeline_id,
            allowed_time_id,
            campaign_id=f.campaign_id,
            event_status_code="draft",
            name="Allowed Draft",
        )
        make_resource_grant(
            setup,
            f.campaign_id,
            f.canon_edit_capability_id,
            event_id=denied_draft_event_id,
            grantee_campaign_membership_id=f.gm_membership_id,
            effect="deny",
        )
        make_resource_grant(
            setup,
            f.campaign_id,
            f.canon_edit_capability_id,
            event_id=allowed_draft_event_id,
            grantee_campaign_membership_id=f.gm_membership_id,
            effect="allow",
        )

    with client_factory(f.gm_user_id) as client:
        response = client.get(_summary_url(f))
    assert response.status_code == 200, response.text
    event_ids = [e["event_id"] for e in response.json()["recent_events"]]
    assert str(denied_draft_event_id) not in event_ids
    # World-time sort keys: denied_draft=350 (excluded), f.draft_event_id=300,
    # allowed_draft=250, recorded_new=200, recorded_old=100 — most-recent-
    # first ordering must hold across this mix of baseline-only, denied,
    # and allowed rows exactly as it would with no grants at all.
    assert event_ids == [
        str(f.draft_event_id),
        str(allowed_draft_event_id),
        str(f.recorded_new_event_id),
        str(f.recorded_old_event_id),
    ]


def test_a_denied_recent_draft_does_not_consume_the_limit_slot(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """A dedicated campaign with exactly 20 recorded events plus one more
    recent draft denied to the GM. Filtering the draft out only after a
    LIMIT 20 fetch would let it consume a slot and push the oldest of the
    20 recorded events out of the response; filtering it out inside the
    query itself (this fix) must return all 20 recorded events instead."""
    with postgres_engine.begin() as setup:
        limit_campaign_id = make_campaign(
            setup, f.timeline_id, "Limit Campaign", lifecycle_status_code="pending"
        )
        limit_gm_membership_id = make_campaign_membership(setup, limit_campaign_id, f.gm_user_id)
        limit_gm_role_id = make_role(
            setup, campaign_id=limit_campaign_id, code=f"gm_{uuid.uuid4().hex[:8]}"
        )
        view_capability_id = lookup_id(
            setup, "security", "capabilities", "capability_id", "campaign.view"
        )
        make_role_capability(setup, limit_gm_role_id, view_capability_id)
        make_role_capability(setup, limit_gm_role_id, f.canon_edit_capability_id)
        make_membership_role(setup, limit_gm_membership_id, limit_gm_role_id)

        recorded_event_ids = []
        for sort_key in range(20):
            world_time_id = make_world_time(setup, f.world_id, sort_key)
            recorded_event_ids.append(
                make_event(
                    setup,
                    f.world_id,
                    f.timeline_id,
                    world_time_id,
                    campaign_id=limit_campaign_id,
                    event_status_code="recorded",
                    name=f"Recorded {sort_key}",
                )
            )
        newest_draft_time_id = make_world_time(setup, f.world_id, 999)
        newest_draft_event_id = make_event(
            setup,
            f.world_id,
            f.timeline_id,
            newest_draft_time_id,
            campaign_id=limit_campaign_id,
            event_status_code="draft",
            name="Newest Draft",
        )
        make_resource_grant(
            setup,
            limit_campaign_id,
            f.canon_edit_capability_id,
            event_id=newest_draft_event_id,
            grantee_campaign_membership_id=limit_gm_membership_id,
            effect="deny",
        )

    with client_factory(f.gm_user_id) as client:
        response = client.get(_summary_url(f, campaign_id=limit_campaign_id))
    assert response.status_code == 200, response.text
    event_ids = [e["event_id"] for e in response.json()["recent_events"]]
    assert len(event_ids) == 20
    assert str(newest_draft_event_id) not in event_ids
    assert set(event_ids) == {str(event_id) for event_id in recorded_event_ids}


def test_a_canon_edit_grant_does_not_affect_recorded_or_corrected_event_visibility(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """A deny targeted at a recorded event, and one targeted at a corrected
    event, both for a caller with no role-derived canon.edit at all — the
    draft/non-draft split in dnd_ai.queries.summary bypasses grant
    resolution entirely for non-draft rows, so neither grant has any effect
    and both remain visible exactly as an ungranted caller would see
    them."""
    with postgres_engine.begin() as setup:
        corrected_time_id = make_world_time(setup, f.world_id, 150)
        corrected_event_id = make_event(
            setup,
            f.world_id,
            f.timeline_id,
            corrected_time_id,
            campaign_id=f.campaign_id,
            event_status_code="corrected",
            name="Corrected Event",
        )
        make_resource_grant(
            setup,
            f.campaign_id,
            f.canon_edit_capability_id,
            event_id=f.recorded_new_event_id,
            grantee_campaign_membership_id=f.player_membership_id,
            effect="deny",
        )
        make_resource_grant(
            setup,
            f.campaign_id,
            f.canon_edit_capability_id,
            event_id=corrected_event_id,
            grantee_campaign_membership_id=f.player_membership_id,
            effect="deny",
        )

    with client_factory(f.player_user_id) as client:
        response = client.get(_summary_url(f))
    assert response.status_code == 200, response.text
    event_ids = {e["event_id"] for e in response.json()["recent_events"]}
    assert str(f.recorded_new_event_id) in event_ids
    assert str(corrected_event_id) in event_ids


def test_a_voided_event_stays_excluded_even_with_a_targeted_allow(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with postgres_engine.begin() as setup:
        make_resource_grant(
            setup,
            f.campaign_id,
            f.canon_edit_capability_id,
            event_id=f.voided_event_id,
            grantee_campaign_membership_id=f.gm_membership_id,
            effect="allow",
        )

    with client_factory(f.gm_user_id) as client:
        response = client.get(_summary_url(f))
    assert response.status_code == 200, response.text
    event_ids = {e["event_id"] for e in response.json()["recent_events"]}
    assert str(f.voided_event_id) not in event_ids
