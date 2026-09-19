"""Tests for `dnd_ai.api.access_overview` (Phase 13E-A) — the read-only GM
campaign access overview backing the portal's Access screen. Mirrors
`tests/database/test_api_memberships.py`'s shape: `get_authenticated_user_id`
is overridden directly, since these tests exercise campaign-capability
enforcement and the endpoint's own query wiring, not OIDC token
verification (already covered centrally by `tests/database/
test_api_auth.py` for the same shared `get_authenticated_user_id`
dependency this route uses — not duplicated here).

Covers: access control (non-member 404, capless-member 403, unknown
campaign 404), successful overview content (roles, character
relationships, membership-targeted resource grants with human-readable
labels), current-state filtering (a revoked role, a revoked relationship,
and a revoked grant are all excluded; a departed/ended membership is
excluded entirely), non-disclosure of out-of-scope grant shapes
(access-group-targeted grants never attributed to any member), and
cross-campaign isolation (two campaigns' overviews never leak into each
other).
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
    make_access_group,
    make_access_group_membership,
    make_campaign,
    make_campaign_membership,
    make_capability,
    make_character,
    make_character_relationship_type,
    make_membership_character_relationship,
    make_membership_role,
    make_resource_grant,
    make_role,
    make_role_capability,
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
        self.campaign_id = make_campaign(connection, self.timeline_id, "Overview Campaign")
        self.other_campaign_id = make_campaign(
            connection, self.timeline_id, "Other Overview Campaign"
        )

        access_manage_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "access.manage"
        )
        view_capability_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "campaign.view"
        )
        primary_controller_type_id = lookup_id(
            connection,
            "security",
            "character_relationship_types",
            "character_relationship_type_id",
            "primary_controller",
        )

        admin_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"admin_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, admin_role_id, access_manage_id)
        make_role_capability(connection, admin_role_id, view_capability_id)

        self.admin_user_id = make_user(connection, "Overview Admin")
        self.admin_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.admin_user_id
        )
        make_membership_role(connection, self.admin_membership_id, admin_role_id)

        # A member with no role/capability at all — proves ForbiddenError,
        # distinct from a non-member's NotFoundError.
        self.capless_user_id = make_user(connection, "Overview Capless Member")
        self.capless_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.capless_user_id
        )

        # Never given a membership at all.
        self.outsider_user_id = make_user(connection, "Overview Outsider")

        # A fully populated member: a role, a character relationship, and a
        # membership-targeted resource grant — the success-path content.
        player_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"player_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, player_role_id, view_capability_id)
        self.member_user_id = make_user(connection, "Overview Member")
        self.member_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.member_user_id
        )
        make_membership_role(connection, self.member_membership_id, player_role_id)

        self.character_id = make_character(connection, self.world_id, name="Overview PC")
        self.relationship_id = make_membership_character_relationship(
            connection,
            self.member_membership_id,
            self.character_id,
            primary_controller_type_id,
            granted_by_membership_id=self.admin_membership_id,
        )
        self.grant_id = make_resource_grant(
            connection,
            self.campaign_id,
            view_capability_id,
            grantee_campaign_membership_id=self.member_membership_id,
            character_id=self.character_id,
            granted_by_membership_id=self.admin_membership_id,
        )
        # make_resource_grant does not expose `reason` — set it directly so
        # the overview's reason passthrough has something to assert on.
        connection.execute(
            text("UPDATE security.resource_grants SET reason = :r WHERE resource_grant_id = :id"),
            {"r": "Overview test visibility", "id": self.grant_id},
        )

        # A fresh, non-protected capability used only by one explicit
        # grant — proves grant/capability-active parity with
        # dnd_ai.domain.access.resolve_access_context (a review
        # correction): an otherwise-current grant of a *deactivated*
        # capability confers no effective access there, so it must not
        # appear here as a current grant either. Left active by default;
        # a dedicated test below deactivates it. The fixture's own
        # cleanup deletes this capability row explicitly by id regardless
        # of its active state at teardown, since security.capabilities is
        # a shared lookup table, not scoped by campaign/timeline like the
        # rows the rest of that cleanup deletes by that scope.
        self.deactivatable_capability_id = make_capability(
            connection, code=f"test.access_overview_deactivatable_{uuid.uuid4().hex[:8]}"
        )
        self.deactivatable_capability_grant_id = make_resource_grant(
            connection,
            self.campaign_id,
            self.deactivatable_capability_id,
            grantee_campaign_membership_id=self.member_membership_id,
            character_id=self.character_id,
            granted_by_membership_id=self.admin_membership_id,
        )

        # A member whose role/relationship/grant are all revoked — proves
        # current-state filtering excludes each independently while the
        # membership itself still appears.
        self.revoked_user_id = make_user(connection, "Overview Revoked Grants Member")
        self.revoked_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.revoked_user_id
        )
        self.revoked_role_id = make_membership_role(
            connection, self.revoked_membership_id, player_role_id, revoked=True
        )
        self.revoked_relationship_id = make_membership_character_relationship(
            connection,
            self.revoked_membership_id,
            self.character_id,
            primary_controller_type_id,
            revoked=True,
        )
        self.revoked_grant_id = make_resource_grant(
            connection,
            self.campaign_id,
            view_capability_id,
            grantee_campaign_membership_id=self.revoked_membership_id,
            character_id=self.character_id,
            revoked=True,
        )

        # A departed (closed) membership — excluded from the overview
        # entirely, not merely emptied of roles/relationships/grants.
        self.departed_user_id = make_user(connection, "Overview Departed Member")
        self.departed_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.departed_user_id, status_code="departed", ended=True
        )

        # A fully fictional-time-bounded (closed) relationship — checkpoint-4
        # correction: `effective_from_world_time_id`/`effective_to_world_
        # time_id` both set makes this a closed historical interval, never
        # a currently-active one (see `dnd_ai.domain.access.
        # resolve_access_context`'s own docstring for the "current record"
        # rule this overview now applies identically). On the *same*
        # member/character `member_membership_id` already holds an active
        # `primary_controller` relationship for, proving this exclusion is
        # per-row, not per-member.
        bounded_from_time = make_world_time(connection, self.world_id, 100)
        bounded_to_time = make_world_time(connection, self.world_id, 200)
        self.bounded_relationship_id = make_membership_character_relationship(
            connection,
            self.member_membership_id,
            self.character_id,
            lookup_id(
                connection,
                "security",
                "character_relationship_types",
                "character_relationship_type_id",
                "viewer",
            ),
            effective_from_world_time_id=bounded_from_time,
            effective_to_world_time_id=bounded_to_time,
        )

        # A grant targeting an access group rather than a membership — out
        # of scope for this first increment; must never surface under any
        # member's grants.
        self.access_group_id = make_access_group(connection, self.campaign_id)
        make_access_group_membership(connection, self.access_group_id, self.member_membership_id)
        self.group_grant_id = make_resource_grant(
            connection,
            self.campaign_id,
            view_capability_id,
            grantee_access_group_id=self.access_group_id,
            character_id=self.character_id,
        )

        # --- assignable_characters/assignable_relationship_types metadata
        # (character-relationship-management checkpoint): a same-world
        # character not otherwise related to anyone (must still appear as
        # assignable), a cross-world character (must never appear), an
        # archived same-world character (must never appear), and a
        # deactivated relationship type (must never appear). ---
        self.unrelated_character_id = make_character(
            connection, self.world_id, name="Overview Unrelated Character"
        )
        self.metadata_other_world_id = make_world(connection, slug=f"{slug}-metadata-other-world")
        self.other_world_character_id = make_character(
            connection, self.metadata_other_world_id, name="Overview Other-World Character"
        )
        self.archived_character_id = make_character(
            connection, self.world_id, name="Overview Archived Character"
        )
        connection.execute(
            text("""
                UPDATE core.entities SET lifecycle_status_id = (
                    SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'archived'
                )
                WHERE entity_id = :character
            """),
            {"character": self.archived_character_id},
        )
        self.deactivated_relationship_type_id = make_character_relationship_type(connection)
        connection.execute(
            text(
                "UPDATE security.character_relationship_types SET is_active = false "
                "WHERE character_relationship_type_id = :t"
            ),
            {"t": self.deactivated_relationship_type_id},
        )

        # A second campaign with its own admin/member — cross-campaign
        # isolation.
        other_admin_role_id = make_role(
            connection, campaign_id=self.other_campaign_id, code=f"admin_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, other_admin_role_id, access_manage_id)
        make_role_capability(connection, other_admin_role_id, view_capability_id)
        self.other_admin_user_id = make_user(connection, "Other Overview Admin")
        self.other_admin_membership_id = make_campaign_membership(
            connection, self.other_campaign_id, self.other_admin_user_id
        )
        make_membership_role(connection, self.other_admin_membership_id, other_admin_role_id)
        self.other_member_user_id = make_user(connection, "Other Overview Member")
        self.other_member_membership_id = make_campaign_membership(
            connection, self.other_campaign_id, self.other_member_user_id
        )


@pytest.fixture
def f(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as connection:
        fixture = Fixture(connection, f"access-overview-api-{uuid.uuid4().hex[:8]}")
    yield fixture
    with postgres_engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        # See tests/database/test_api_dungeon.py's identical cleanup comment
        # for why session_replication_role = replica and explicit,
        # dependency-ordered deletes are used here.
        cleanup.execute(
            text("""
                DELETE FROM security.membership_character_relationships
                WHERE campaign_membership_id IN (
                    SELECT campaign_membership_id FROM security.campaign_memberships
                    WHERE campaign_id IN (
                        SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t
                    )
                )
            """),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM security.resource_grants WHERE campaign_id IN (
                    SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t
                )
            """),
            {"t": fixture.timeline_id},
        )
        # security.capabilities is a shared lookup table, not scoped by
        # campaign/timeline like the rows above — the fixture's own
        # deactivatable capability is deleted explicitly by id.
        cleanup.execute(
            text("DELETE FROM security.capabilities WHERE capability_id = :c"),
            {"c": fixture.deactivatable_capability_id},
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
            text("""
                DELETE FROM security.access_groups WHERE campaign_id IN (
                    SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t
                )
            """),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM security.membership_roles WHERE campaign_membership_id IN (
                    SELECT campaign_membership_id FROM security.campaign_memberships
                    WHERE campaign_id IN (
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
            text("""
                DELETE FROM security.roles WHERE campaign_id IN (
                    SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t
                )
            """),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM security.campaign_memberships WHERE campaign_id IN (
                    SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t
                )
            """),
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
            text("DELETE FROM core.entities WHERE world_id = :w"),
            {"w": fixture.metadata_other_world_id},
        )
        cleanup.execute(
            text("DELETE FROM core.worlds WHERE world_id = :w"),
            {"w": fixture.metadata_other_world_id},
        )
        # security.character_relationship_types is a shared lookup table,
        # not scoped by campaign/timeline like the rows above — the
        # fixture's own extra, deactivated type is deleted explicitly by id.
        cleanup.execute(
            text(
                "DELETE FROM security.character_relationship_types "
                "WHERE character_relationship_type_id = :t"
            ),
            {"t": fixture.deactivated_relationship_type_id},
        )
        cleanup.execute(
            text("DELETE FROM security.users WHERE user_id = ANY(:users)"),
            {
                "users": [
                    fixture.admin_user_id,
                    fixture.capless_user_id,
                    fixture.outsider_user_id,
                    fixture.member_user_id,
                    fixture.revoked_user_id,
                    fixture.departed_user_id,
                    fixture.other_admin_user_id,
                    fixture.other_member_user_id,
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


def _overview_url(f: Fixture, campaign_id: uuid.UUID | None = None) -> str:
    return f"/campaigns/{campaign_id or f.campaign_id}/access-overview"


def _member(payload: dict, membership_id: uuid.UUID) -> dict:
    for member in payload["members"]:
        if member["campaign_membership_id"] == str(membership_id):
            return member
    raise AssertionError(f"membership {membership_id} not found in {payload}")


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


def test_a_non_member_gets_not_found(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.outsider_user_id) as client:
        response = client.get(_overview_url(f))
    assert response.status_code == 404


def test_a_member_without_access_manage_gets_forbidden(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.capless_user_id) as client:
        response = client.get(_overview_url(f))
    assert response.status_code == 403


def test_an_unknown_campaign_gets_not_found(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.get(_overview_url(f, campaign_id=uuid.uuid4()))
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Successful overview content
# ---------------------------------------------------------------------------


def test_authorized_gm_sees_the_full_overview(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.get(_overview_url(f))
    assert response.status_code == 200, response.text
    payload = response.json()

    member = _member(payload, f.member_membership_id)
    assert member["display_name"] == "Overview Member"
    assert member["status_display_name"] == "Active"

    assert [role["code"] for role in member["roles"]] != []
    assert any(role["display_name"] for role in member["roles"])

    assert len(member["character_relationships"]) == 1
    relationship = member["character_relationships"][0]
    assert relationship["character_display_name"] == "Overview PC"
    assert relationship["relationship_type_code"] == "primary_controller"
    assert relationship["relationship_type_display_name"] == "Primary Controller"
    assert relationship["character_id"] == str(f.character_id)

    # Two grants: the assertions below exercise `grant_id`'s fields; the
    # deactivatable-capability grant is exercised separately in the
    # current-state filtering tests below.
    assert len(member["grants"]) == 2
    grant = next(g for g in member["grants"] if g["resource_grant_id"] == str(f.grant_id))
    assert grant["capability_code"] == "campaign.view"
    assert grant["capability_display_name"] == "View Campaign"
    assert grant["effect"] == "allow"
    assert grant["target_type"] == "character"
    assert grant["reason"] == "Overview test visibility"

    assignable_character_ids = {c["character_id"] for c in payload["assignable_characters"]}
    assert str(f.character_id) in assignable_character_ids
    assert str(f.unrelated_character_id) in assignable_character_ids

    assignable_type_codes = {t["code"] for t in payload["assignable_relationship_types"]}
    assert "primary_controller" in assignable_type_codes
    assert "viewer" in assignable_type_codes
    assert "portrayer" in assignable_type_codes


def test_a_membership_with_no_roles_or_relationships_or_grants_still_appears(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.get(_overview_url(f))
    assert response.status_code == 200, response.text
    member = _member(response.json(), f.capless_membership_id)
    assert member["roles"] == []
    assert member["character_relationships"] == []
    assert member["grants"] == []


# ---------------------------------------------------------------------------
# Current-state filtering
# ---------------------------------------------------------------------------


def test_a_revoked_role_relationship_and_grant_are_all_excluded(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.get(_overview_url(f))
    assert response.status_code == 200, response.text
    member = _member(response.json(), f.revoked_membership_id)
    assert member["roles"] == []
    assert member["character_relationships"] == []
    assert member["grants"] == []


def test_a_fully_fictional_time_bounded_relationship_is_excluded(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    """Checkpoint-4 correction: `f.bounded_relationship_id` (both fictional-
    time endpoints set) must never appear, even though `f.member_
    membership_id`'s *other*, unbounded relationship (`f.relationship_id`)
    to the same character still does — proving the exclusion is per-row."""
    with client_factory(f.admin_user_id) as client:
        response = client.get(_overview_url(f))
    assert response.status_code == 200, response.text
    member = _member(response.json(), f.member_membership_id)
    relationship_ids = {
        r["membership_character_relationship_id"] for r in member["character_relationships"]
    }
    assert str(f.bounded_relationship_id) not in relationship_ids
    assert str(f.relationship_id) in relationship_ids


def test_a_departed_membership_is_excluded_entirely(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.get(_overview_url(f))
    assert response.status_code == 200, response.text
    membership_ids = {m["campaign_membership_id"] for m in response.json()["members"]}
    assert str(f.departed_membership_id) not in membership_ids


def test_an_access_group_targeted_grant_is_never_attributed_to_a_member(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.get(_overview_url(f))
    assert response.status_code == 200, response.text
    for member in response.json()["members"]:
        for grant in member["grants"]:
            assert grant["resource_grant_id"] != str(f.group_grant_id)


def test_a_grant_of_a_deactivated_capability_is_excluded_while_an_active_one_remains(
    client_factory: Callable[[uuid.UUID], TestClient],
    f: Fixture,
    postgres_engine: Engine,
) -> None:
    """Parity with `dnd_ai.domain.access.resolve_access_context`, which
    requires `cap.is_active` when resolving a caller's own resource-grant
    effects — an explicit grant of a deactivated capability confers no
    effective access there, so it must not appear here as a current grant
    either, even though the grant row itself is otherwise fully current
    (not revoked, not expired, correctly timeline-scoped, and targets an
    open membership)."""
    with postgres_engine.begin() as connection:
        connection.execute(
            text("UPDATE security.capabilities SET is_active = false WHERE capability_id = :c"),
            {"c": f.deactivatable_capability_id},
        )

    with client_factory(f.admin_user_id) as client:
        response = client.get(_overview_url(f))
    assert response.status_code == 200, response.text

    member = _member(response.json(), f.member_membership_id)
    grant_ids = {grant["resource_grant_id"] for grant in member["grants"]}

    # The deactivated capability's otherwise-current grant is gone...
    assert str(f.deactivatable_capability_grant_id) not in grant_ids
    # ...while the equivalent grant to a still-active capability remains.
    assert str(f.grant_id) in grant_ids


# ---------------------------------------------------------------------------
# assignable_characters / assignable_relationship_types metadata
# ---------------------------------------------------------------------------


def test_a_cross_world_character_is_excluded_from_assignable_characters(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.get(_overview_url(f))
    assert response.status_code == 200, response.text
    assignable_character_ids = {c["character_id"] for c in response.json()["assignable_characters"]}
    assert str(f.other_world_character_id) not in assignable_character_ids


def test_an_archived_character_is_excluded_from_assignable_characters(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.get(_overview_url(f))
    assert response.status_code == 200, response.text
    assignable_character_ids = {c["character_id"] for c in response.json()["assignable_characters"]}
    assert str(f.archived_character_id) not in assignable_character_ids


def test_a_deactivated_relationship_type_is_excluded_from_assignable_relationship_types(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.get(_overview_url(f))
    assert response.status_code == 200, response.text
    assignable_type_ids = {
        t["character_relationship_type_id"]
        for t in response.json()["assignable_relationship_types"]
    }
    assert str(f.deactivated_relationship_type_id) not in assignable_type_ids


# ---------------------------------------------------------------------------
# Cross-campaign isolation
# ---------------------------------------------------------------------------


def test_campaigns_do_not_leak_members_into_each_other(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        primary_response = client.get(_overview_url(f))
    assert primary_response.status_code == 200, primary_response.text
    primary_membership_ids = {
        m["campaign_membership_id"] for m in primary_response.json()["members"]
    }
    assert str(f.other_admin_membership_id) not in primary_membership_ids
    assert str(f.other_member_membership_id) not in primary_membership_ids

    with client_factory(f.other_admin_user_id) as client:
        other_response = client.get(_overview_url(f, campaign_id=f.other_campaign_id))
    assert other_response.status_code == 200, other_response.text
    other_membership_ids = {m["campaign_membership_id"] for m in other_response.json()["members"]}
    assert str(f.member_membership_id) not in other_membership_ids
    assert str(f.admin_membership_id) not in other_membership_ids


def test_an_admin_of_one_campaign_cannot_view_another_campaigns_overview(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.get(_overview_url(f, campaign_id=f.other_campaign_id))
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Revocation reflected on the next request
# ---------------------------------------------------------------------------


def test_revoking_a_role_after_the_fact_is_reflected_on_the_next_request(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.admin_user_id) as client:
        before = client.get(_overview_url(f))
    assert before.status_code == 200, before.text
    member_before = _member(before.json(), f.member_membership_id)
    assert member_before["roles"] != []

    with postgres_engine.begin() as connection:
        connection.execute(
            text("""
                UPDATE security.membership_roles SET revoked_at = now()
                WHERE campaign_membership_id = :m
            """),
            {"m": f.member_membership_id},
        )

    with client_factory(f.admin_user_id) as client:
        after = client.get(_overview_url(f))
    assert after.status_code == 200, after.text
    member_after = _member(after.json(), f.member_membership_id)
    assert member_after["roles"] == []
