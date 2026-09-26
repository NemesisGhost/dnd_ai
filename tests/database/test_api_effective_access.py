"""Tests for `dnd_ai.api.access_overview.get_member_effective_access_endpoint`
(Phase 13E-B checkpoint 13) — the GM-facing "why can this person see this?"
explanation. Mirrors `tests/database/test_api_access_overview.py`'s shape:
`get_authenticated_user_id` is overridden directly.

Covers: access control (non-member 404, capless-member 403, unknown campaign
404, a membership from another campaign is a non-disclosing 404, a departed
membership is a non-disclosing 404), capability sources resolved for a
role, a character relationship, a direct allow grant, and a group allow
grant, the denials list for a direct deny grant and a group deny grant, and
that no field outside the audience-safe set (no non-character
target_display_name) ever appears.
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
    make_character,
    make_character_relationship_type,
    make_membership_character_relationship,
    make_membership_role,
    make_relationship_type_capability,
    make_resource_grant,
    make_role,
    make_role_capability,
    make_timeline,
    make_user,
    make_world,
    oidc_principal,
)

pytestmark = pytest.mark.database


class Fixture:
    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        self.campaign_id = make_campaign(connection, self.timeline_id, "Effective Access Campaign")
        self.other_campaign_id = make_campaign(
            connection, self.timeline_id, "Other Effective Access Campaign"
        )

        access_manage_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "access.manage"
        )
        view_capability_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "campaign.view"
        )
        character_view_full_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "character.view_full"
        )
        # A campaign-local relationship type carrying its own capability
        # grant, rather than the seeded `primary_controller` type — that
        # type carries no `character_relationship_type_capabilities` row by
        # default, so a fixture relying on it would grant nothing to
        # resolve a source from. Cleaned up explicitly by id below, matching
        # `tests/database/test_api_access_overview.py`'s identical
        # `deactivated_relationship_type_id` cleanup for a shared lookup row.
        self.relationship_type_id = make_character_relationship_type(connection)
        make_relationship_type_capability(
            connection, self.relationship_type_id, character_view_full_id
        )

        admin_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"admin_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, admin_role_id, access_manage_id)
        self.admin_user_id = make_user(connection, "Effective Access Admin")
        self.admin_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.admin_user_id
        )
        make_membership_role(connection, self.admin_membership_id, admin_role_id)

        # A member with no role/capability at all — proves ForbiddenError,
        # distinct from a non-member's NotFoundError.
        self.capless_user_id = make_user(connection, "Effective Access Capless Member")
        self.capless_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.capless_user_id
        )

        # Never given a membership at all.
        self.outsider_user_id = make_user(connection, "Effective Access Outsider")

        # A departed (closed) membership — must resolve identically to a
        # non-member, never a distinguishable "exists but closed" result.
        self.departed_user_id = make_user(connection, "Effective Access Departed")
        self.departed_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.departed_user_id, status_code="departed", ended=True
        )

        # The fully-populated member: a role, a character relationship, a
        # direct allow grant, a direct deny grant, a group allow grant, and
        # a group deny grant — the success-path content.
        player_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"player_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, player_role_id, view_capability_id)
        self.member_user_id = make_user(connection, "Effective Access Member")
        self.member_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.member_user_id
        )
        make_membership_role(connection, self.member_membership_id, player_role_id)

        self.character_id = make_character(connection, self.world_id, name="Effective Access PC")
        self.relationship_id = make_membership_character_relationship(
            connection,
            self.member_membership_id,
            self.character_id,
            self.relationship_type_id,
            granted_by_membership_id=self.admin_membership_id,
        )

        self.direct_allow_grant_id = make_resource_grant(
            connection,
            self.campaign_id,
            view_capability_id,
            grantee_campaign_membership_id=self.member_membership_id,
            character_id=self.character_id,
            granted_by_membership_id=self.admin_membership_id,
        )
        connection.execute(
            text("UPDATE security.resource_grants SET reason = :r WHERE resource_grant_id = :id"),
            {"r": "Effective access test reason", "id": self.direct_allow_grant_id},
        )

        self.other_character_id = make_character(
            connection, self.world_id, name="Effective Access Denied-Target PC"
        )
        self.direct_deny_grant_id = make_resource_grant(
            connection,
            self.campaign_id,
            view_capability_id,
            grantee_campaign_membership_id=self.member_membership_id,
            character_id=self.other_character_id,
            effect="deny",
            granted_by_membership_id=self.admin_membership_id,
        )

        self.access_group_id = make_access_group(connection, self.campaign_id, name="Lore Circle")
        make_access_group_membership(connection, self.access_group_id, self.member_membership_id)
        self.group_allow_capability_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "canon.edit"
        )
        self.group_allow_grant_id = make_resource_grant(
            connection,
            self.campaign_id,
            self.group_allow_capability_id,
            grantee_access_group_id=self.access_group_id,
            character_id=self.character_id,
            granted_by_membership_id=self.admin_membership_id,
        )
        self.group_deny_grant_id = make_resource_grant(
            connection,
            self.campaign_id,
            view_capability_id,
            grantee_access_group_id=self.access_group_id,
            character_id=self.other_character_id,
            effect="deny",
            granted_by_membership_id=self.admin_membership_id,
        )

        other_admin_role_id = make_role(
            connection,
            campaign_id=self.other_campaign_id,
            code=f"other_admin_{uuid.uuid4().hex[:8]}",
        )
        make_role_capability(connection, other_admin_role_id, access_manage_id)
        self.other_admin_user_id = make_user(connection, "Other Effective Access Admin")
        self.other_admin_membership_id = make_campaign_membership(
            connection, self.other_campaign_id, self.other_admin_user_id
        )
        make_membership_role(connection, self.other_admin_membership_id, other_admin_role_id)
        self.other_member_user_id = make_user(connection, "Other Effective Access Member")
        self.other_member_membership_id = make_campaign_membership(
            connection, self.other_campaign_id, self.other_member_user_id
        )


@pytest.fixture
def f(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as connection:
        fixture = Fixture(connection, f"effective-access-api-{uuid.uuid4().hex[:8]}")
    yield fixture
    with postgres_engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
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
        # security.character_relationship_types is a shared lookup table,
        # not scoped by campaign/timeline like the rows above — the
        # fixture's own extra type is deleted explicitly by id, matching
        # `tests/database/test_api_access_overview.py`'s identical cleanup.
        cleanup.execute(
            text(
                "DELETE FROM security.character_relationship_type_capabilities "
                "WHERE character_relationship_type_id = :t"
            ),
            {"t": fixture.relationship_type_id},
        )
        cleanup.execute(
            text(
                "DELETE FROM security.character_relationship_types "
                "WHERE character_relationship_type_id = :t"
            ),
            {"t": fixture.relationship_type_id},
        )
        cleanup.execute(
            text("DELETE FROM security.users WHERE user_id = ANY(:users)"),
            {
                "users": [
                    fixture.admin_user_id,
                    fixture.capless_user_id,
                    fixture.outsider_user_id,
                    fixture.departed_user_id,
                    fixture.member_user_id,
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


def _url(f: Fixture, membership_id: uuid.UUID, *, campaign_id: uuid.UUID | None = None) -> str:
    return f"/campaigns/{campaign_id or f.campaign_id}/members/{membership_id}/effective-access"


def _capability(payload: dict, code: str) -> dict:
    for capability in payload["capabilities"]:
        if capability["code"] == code:
            return capability
    raise AssertionError(f"capability {code!r} not found in {payload}")


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


def test_a_non_member_gets_not_found(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.outsider_user_id) as client:
        response = client.get(_url(f, f.member_membership_id))
    assert response.status_code == 404


def test_a_member_without_access_manage_gets_forbidden(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.capless_user_id) as client:
        response = client.get(_url(f, f.member_membership_id))
    assert response.status_code == 403


def test_an_unknown_campaign_gets_not_found(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.get(_url(f, f.member_membership_id, campaign_id=uuid.uuid4()))
    assert response.status_code == 404


def test_a_membership_from_another_campaign_is_a_non_disclosing_not_found(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.get(_url(f, f.other_member_membership_id))
    assert response.status_code == 404


def test_a_departed_membership_is_a_non_disclosing_not_found(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.get(_url(f, f.departed_membership_id))
    assert response.status_code == 404


def test_an_admin_of_one_campaign_cannot_explain_another_campaigns_member(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.other_admin_user_id) as client:
        response = client.get(_url(f, f.member_membership_id))
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Success-path content
# ---------------------------------------------------------------------------


def test_the_explanation_includes_the_members_display_name(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.get(_url(f, f.member_membership_id))
    assert response.status_code == 200
    assert response.json()["display_name"] == "Effective Access Member"


def test_a_role_derived_capability_has_a_role_source(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.get(_url(f, f.member_membership_id))
    capability = _capability(response.json(), "campaign.view")
    role_sources = [source for source in capability["sources"] if source["kind"] == "role"]
    assert len(role_sources) == 1
    assert role_sources[0]["target_display_name"] is None


def test_a_character_relationship_derived_capability_has_its_own_source(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.get(_url(f, f.member_membership_id))
    capability = _capability(response.json(), "character.view_full")
    relationship_sources = [
        source for source in capability["sources"] if source["kind"] == "character_relationship"
    ]
    assert len(relationship_sources) == 1
    assert relationship_sources[0]["target_display_name"] == "Effective Access PC"


def test_a_direct_allow_grant_has_a_resource_grant_source_carrying_the_reason(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.get(_url(f, f.member_membership_id))
    capability = _capability(response.json(), "campaign.view")
    grant_sources = [
        source for source in capability["sources"] if source["kind"] == "resource_grant"
    ]
    assert len(grant_sources) == 1
    assert grant_sources[0]["label"] == "Effective access test reason"
    assert grant_sources[0]["target_display_name"] == "Effective Access PC"


def test_a_group_allow_grant_has_an_access_group_source_labeled_with_the_group_name(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.get(_url(f, f.member_membership_id))
    capability = _capability(response.json(), "canon.edit")
    group_sources = [source for source in capability["sources"] if source["kind"] == "access_group"]
    assert len(group_sources) == 1
    assert group_sources[0]["label"] == "Lore Circle"
    assert group_sources[0]["target_display_name"] == "Effective Access PC"


def test_a_direct_deny_grant_appears_in_denials_with_its_target(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.get(_url(f, f.member_membership_id))
    denials = response.json()["denials"]
    matching = [
        denial
        for denial in denials
        if denial["capability_code"] == "campaign.view"
        and denial["target_display_name"] == "Effective Access Denied-Target PC"
    ]
    assert len(matching) == 2  # direct + group deny grants, both targeting the same character
    for denial in matching:
        assert denial["target_type"] == "character"


def test_a_non_character_grant_target_never_carries_a_display_name(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.get(_url(f, f.member_membership_id))
    payload = response.json()
    for capability in payload["capabilities"]:
        for source in capability["sources"]:
            if source["kind"] in ("role", "resource_grant") and source["target_display_name"]:
                assert source["kind"] != "role"
    for denial in payload["denials"]:
        if denial["target_type"] != "character":
            assert denial["target_display_name"] is None


def test_a_member_with_nothing_still_gets_an_empty_but_valid_explanation(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.get(_url(f, f.capless_membership_id))
    assert response.status_code == 200
    payload = response.json()
    assert payload["capabilities"] == []
    assert payload["denials"] == []
