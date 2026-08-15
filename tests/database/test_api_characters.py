"""Tests for `dnd_ai.api.characters` — Phase 10 workstream 13's query
endpoint over `dnd_ai.queries.character.get_character_view` (docs/PLAN.md
Phase 10 "query services for the effective dungeon, character, ... state
required by the vertical slice"). Mirrors `tests/database/
test_api_dungeon.py`'s shape: `get_authenticated_user_id` is overridden
directly, since these tests exercise campaign-capability enforcement and
character-view-tier resolution, not OIDC token verification.

Covers: access control (non-member 404, capless-member 403), the
character-view-tier split (`character.view_summary` returns name/species/
size only; `character.view_full` and `canon.edit` additionally return
mechanical state, conditions, resources, and current location; a member
holding neither gets the same fixed 404 a nonexistent character would),
and cross-world ownership.
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
    make_character,
    make_character_condition,
    make_character_location_history,
    make_character_relationship_type,
    make_character_resource,
    make_character_state,
    make_condition,
    make_location,
    make_membership_character_relationship,
    make_membership_role,
    make_relationship_type_capability,
    make_resource_definition,
    make_role,
    make_role_capability,
    make_ruleset_version_for_world,
    make_species,
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
        self.world_time_id = make_world_time(connection, self.world_id, 100)
        self.campaign_id = make_campaign(
            connection, self.timeline_id, lifecycle_status_code="pending"
        )

        ruleset_version_id = make_ruleset_version_for_world(connection, self.world_id)
        species_id = make_species(connection, ruleset_version_id, code="elf")
        self.character_id = make_character(
            connection, self.world_id, species_id=species_id, name="Aria", size_category="medium"
        )
        make_character_state(
            connection,
            self.timeline_id,
            self.character_id,
            current_hit_points=7,
            maximum_hit_points=12,
        )
        condition_id = make_condition(connection, ruleset_version_id, code="poisoned")
        make_character_condition(
            connection,
            self.timeline_id,
            self.character_id,
            condition_id,
            source_description="stepped in ooze",
        )
        resource_definition_id = make_resource_definition(
            connection, ruleset_version_id, code="ki_points"
        )
        make_character_resource(
            connection,
            self.timeline_id,
            self.character_id,
            resource_definition_id,
            current_amount=2,
            maximum_amount=4,
        )
        self.location_id = make_location(connection, self.world_id, name="Camp")
        make_character_location_history(
            connection, self.timeline_id, self.character_id, self.location_id, self.world_time_id
        )

        # A second, unrelated world — its character proves the cross-world
        # ownership check (character.characters carries no campaign_id at
        # all, so world agreement stands in for it).
        self.other_world_id = make_world(connection, slug=f"{slug}-other-world")
        other_ruleset_version_id = make_ruleset_version_for_world(connection, self.other_world_id)
        other_species_id = make_species(connection, other_ruleset_version_id, code="dwarf")
        self.other_world_character_id = make_character(
            connection, self.other_world_id, species_id=other_species_id, name="Borin"
        )

        view_capability_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "campaign.view"
        )
        canon_edit_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "canon.edit"
        )
        view_full_capability_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "character.view_full"
        )
        view_summary_capability_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "character.view_summary"
        )

        base_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"viewer_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, base_role_id, view_capability_id)

        self.gm_user_id = make_user(connection, "Character API GM")
        gm_membership_id = make_campaign_membership(connection, self.campaign_id, self.gm_user_id)
        gm_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"gm_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, gm_role_id, view_capability_id)
        make_role_capability(connection, gm_role_id, canon_edit_id)
        make_membership_role(connection, gm_membership_id, gm_role_id)

        # security.character_relationship_types is a global lookup table,
        # not scoped by world — cleanup below deletes both specific rows
        # explicitly by id.
        self.full_view_relationship_type_id = make_character_relationship_type(connection)
        make_relationship_type_capability(
            connection, self.full_view_relationship_type_id, view_full_capability_id
        )
        self.summary_view_relationship_type_id = make_character_relationship_type(connection)
        make_relationship_type_capability(
            connection, self.summary_view_relationship_type_id, view_summary_capability_id
        )

        self.full_view_user_id = make_user(connection, "Character API Full Viewer")
        full_view_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.full_view_user_id
        )
        make_membership_role(connection, full_view_membership_id, base_role_id)
        make_membership_character_relationship(
            connection,
            full_view_membership_id,
            self.character_id,
            self.full_view_relationship_type_id,
            timeline_id=self.timeline_id,
        )

        self.summary_view_user_id = make_user(connection, "Character API Summary Viewer")
        summary_view_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.summary_view_user_id
        )
        make_membership_role(connection, summary_view_membership_id, base_role_id)
        make_membership_character_relationship(
            connection,
            summary_view_membership_id,
            self.character_id,
            self.summary_view_relationship_type_id,
            timeline_id=self.timeline_id,
        )

        # Holds campaign.view (passes the base gate) but no character-
        # specific view capability at all for self.character_id — proves
        # the resource-scoped tier check, not just campaign membership,
        # gates this endpoint.
        self.no_character_capability_user_id = make_user(
            connection, "Character API No Character Capability"
        )
        no_cap_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.no_character_capability_user_id
        )
        make_membership_role(connection, no_cap_membership_id, base_role_id)

        # A member with no role/capability at all — proves ForbiddenError,
        # distinct from a non-member's NotFoundError.
        self.capless_user_id = make_user(connection, "Character API Capless Member")
        make_campaign_membership(connection, self.campaign_id, self.capless_user_id)

        # Never given a membership at all.
        self.outsider_user_id = make_user(connection, "Character API Outsider")


@pytest.fixture
def f(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as connection:
        fixture = Fixture(connection, f"character-api-{uuid.uuid4().hex[:8]}")
    yield fixture
    with postgres_engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        # See tests/database/test_api_dungeon.py's identical cleanup
        # comment: session_replication_role = replica disables the
        # cascades the later DELETE FROM core.entities/core.worlds
        # statements would otherwise apply, and revision 080's DEFERRABLE
        # constraint triggers on several security.* tables can fail a
        # later, unrelated test in the same pytest session if left behind.
        for world_id in (fixture.world_id, fixture.other_world_id):
            cleanup.execute(
                text("""
                    DELETE FROM security.membership_character_relationships
                    WHERE campaign_membership_id IN (
                        SELECT campaign_membership_id FROM security.campaign_memberships
                        WHERE campaign_id IN (
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
                text(
                    "DELETE FROM campaign.character_conditions WHERE timeline_id IN "
                    "(SELECT timeline_id FROM campaign.timelines WHERE world_id = :w)"
                ),
                {"w": world_id},
            )
            cleanup.execute(
                text(
                    "DELETE FROM campaign.character_resources WHERE timeline_id IN "
                    "(SELECT timeline_id FROM campaign.timelines WHERE world_id = :w)"
                ),
                {"w": world_id},
            )
            cleanup.execute(
                text(
                    "DELETE FROM campaign.character_location_history WHERE timeline_id IN "
                    "(SELECT timeline_id FROM campaign.timelines WHERE world_id = :w)"
                ),
                {"w": world_id},
            )
            cleanup.execute(
                text(
                    "DELETE FROM campaign.character_state WHERE timeline_id IN "
                    "(SELECT timeline_id FROM campaign.timelines WHERE world_id = :w)"
                ),
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
        # security.character_relationship_types (and its capability grants)
        # are global lookup tables, not scoped by world — the per-world
        # loop above already removed the membership_character_relationships
        # rows referencing them, so these two specific rows are safe to
        # delete here by id.
        for relationship_type_id in (
            fixture.full_view_relationship_type_id,
            fixture.summary_view_relationship_type_id,
        ):
            cleanup.execute(
                text(
                    "DELETE FROM security.character_relationship_type_capabilities "
                    "WHERE character_relationship_type_id = :rt"
                ),
                {"rt": relationship_type_id},
            )
            cleanup.execute(
                text(
                    "DELETE FROM security.character_relationship_types "
                    "WHERE character_relationship_type_id = :rt"
                ),
                {"rt": relationship_type_id},
            )
        cleanup.execute(
            text("DELETE FROM security.users WHERE user_id = ANY(:users)"),
            {
                "users": [
                    fixture.gm_user_id,
                    fixture.full_view_user_id,
                    fixture.summary_view_user_id,
                    fixture.no_character_capability_user_id,
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
        app.dependency_overrides[get_authenticated_user_id] = lambda: user_id
        return TestClient(app, raise_server_exceptions=False)

    return _make


def _character_url(f: Fixture, character_id: uuid.UUID | None = None) -> str:
    return f"/campaigns/{f.campaign_id}/characters/{character_id or f.character_id}"


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


def test_a_non_member_gets_not_found(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.outsider_user_id) as client:
        response = client.get(_character_url(f))
    assert response.status_code == 404


def test_a_member_without_campaign_view_gets_forbidden(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.capless_user_id) as client:
        response = client.get(_character_url(f))
    assert response.status_code == 403


def test_a_member_with_campaign_view_but_no_character_capability_gets_not_found(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.no_character_capability_user_id) as client:
        response = client.get(_character_url(f))
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# View-tier resolution
# ---------------------------------------------------------------------------


def test_summary_tier_returns_only_name_species_and_size(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.summary_view_user_id) as client:
        response = client.get(_character_url(f))
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["name"] == "Aria"
    assert body["species_code"] == "elf"
    assert body["size_category"] == "medium"
    assert body["current_hit_points"] is None
    assert body["maximum_hit_points"] is None
    assert body["temporary_hit_points"] is None
    assert body["exhaustion_level"] is None
    assert body["death_save_successes"] is None
    assert body["death_save_failures"] is None
    assert body["current_location_id"] is None
    assert body["conditions"] is None
    assert body["resources"] is None


def test_full_tier_returns_mechanical_state_conditions_resources_and_location(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.full_view_user_id) as client:
        response = client.get(_character_url(f))
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["name"] == "Aria"
    assert body["current_hit_points"] == 7
    assert body["maximum_hit_points"] == 12
    assert body["temporary_hit_points"] == 0
    assert body["exhaustion_level"] == 0
    assert body["current_location_id"] == str(f.location_id)
    assert body["conditions"] == [
        {"condition_code": "poisoned", "source_description": "stepped in ooze"}
    ]
    assert body["resources"] == [
        {"resource_code": "ki_points", "current_amount": 2, "maximum_amount": 4}
    ]


def test_a_gm_gets_full_tier_without_any_character_specific_relationship(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.get(_character_url(f))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["current_hit_points"] == 7
    assert body["conditions"] == [
        {"condition_code": "poisoned", "source_description": "stepped in ooze"}
    ]


# ---------------------------------------------------------------------------
# Cross-world ownership and existence
# ---------------------------------------------------------------------------


def test_a_character_in_a_different_world_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.get(_character_url(f, f.other_world_character_id))
    assert response.status_code == 404


def test_a_nonexistent_character_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.get(_character_url(f, uuid.uuid4()))
    assert response.status_code == 404
