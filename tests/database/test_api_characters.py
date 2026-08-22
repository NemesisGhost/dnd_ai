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
from dnd_ai.domain.access import FOUNDRY_ACCESS_AUTH_METHOD, AuthenticatedPrincipal
from tests.factories import (
    lookup_id,
    make_access_group,
    make_access_group_membership,
    make_campaign,
    make_campaign_membership,
    make_character,
    make_character_condition,
    make_character_location_history,
    make_character_relationship_type,
    make_character_resource,
    make_character_state,
    make_condition,
    make_encounter,
    make_encounter_participant,
    make_location,
    make_membership_character_relationship,
    make_membership_role,
    make_relationship_type_capability,
    make_resource_definition,
    make_resource_grant,
    make_role,
    make_role_capability,
    make_ruleset_version_for_world,
    make_species,
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

        self.view_capability_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "campaign.view"
        )
        self.canon_edit_capability_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "canon.edit"
        )
        self.view_full_capability_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "character.view_full"
        )
        self.view_summary_capability_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "character.view_summary"
        )

        base_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"viewer_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, base_role_id, self.view_capability_id)

        self.gm_user_id = make_user(connection, "Character API GM")
        self.gm_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.gm_user_id
        )
        gm_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"gm_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, gm_role_id, self.view_capability_id)
        make_role_capability(connection, gm_role_id, self.canon_edit_capability_id)
        make_membership_role(connection, self.gm_membership_id, gm_role_id)

        # security.character_relationship_types is a global lookup table,
        # not scoped by world — cleanup below deletes both specific rows
        # explicitly by id.
        self.full_view_relationship_type_id = make_character_relationship_type(connection)
        make_relationship_type_capability(
            connection, self.full_view_relationship_type_id, self.view_full_capability_id
        )
        self.summary_view_relationship_type_id = make_character_relationship_type(connection)
        make_relationship_type_capability(
            connection, self.summary_view_relationship_type_id, self.view_summary_capability_id
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
        self.no_character_capability_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.no_character_capability_user_id
        )
        make_membership_role(connection, self.no_character_capability_membership_id, base_role_id)

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
            # security.resource_grants/access_group_memberships/
            # access_groups are created ad hoc by individual tests below
            # (the workstream 13 correction pass's deny/allow-grant
            # regression tests), never by the shared Fixture itself —
            # cleaned up here, scoped by campaign_id, before the
            # campaign_memberships/access_groups rows they reference are
            # removed.
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
                    DELETE FROM security.access_group_memberships WHERE access_group_id IN (
                        SELECT access_group_id FROM security.access_groups WHERE campaign_id IN (
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
                    DELETE FROM security.access_groups WHERE campaign_id IN (
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
        app.dependency_overrides[get_authenticated_user_id] = lambda: oidc_principal(user_id)
        return TestClient(app, raise_server_exceptions=False)

    return _make


@pytest.fixture
def foundry_client_factory(
    postgres_engine: Engine,
) -> Callable[[AuthenticatedPrincipal], TestClient]:
    def _make(principal: AuthenticatedPrincipal) -> TestClient:
        app = create_app()
        app.dependency_overrides[get_engine] = lambda: postgres_engine
        app.dependency_overrides[get_authenticated_user_id] = lambda: principal
        return TestClient(app, raise_server_exceptions=False)

    return _make


def _character_url(f: Fixture, character_id: uuid.UUID | None = None) -> str:
    return f"/campaigns/{f.campaign_id}/characters/{character_id or f.character_id}"


def _inventory_url(f: Fixture, character_id: uuid.UUID | None = None) -> str:
    return f"/campaigns/{f.campaign_id}/characters/{character_id or f.character_id}/inventory"


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
    assert body["active_encounter_id"] is None
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
    assert body["active_encounter_id"] is None
    assert body["conditions"] == [
        {"condition_code": "poisoned", "source_description": "stepped in ooze"}
    ]
    assert body["resources"] == [
        {"resource_code": "ki_points", "current_amount": 2, "maximum_amount": 4}
    ]


def test_full_tier_returns_the_active_encounter_id(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with postgres_engine.begin() as connection:
        encounter_id = make_encounter(connection, f.timeline_id, f.world_time_id, status="active")
        make_encounter_participant(connection, encounter_id, f.character_id)

    with client_factory(f.full_view_user_id) as client:
        response = client.get(_character_url(f))
    assert response.status_code == 200, response.text
    assert response.json()["active_encounter_id"] == str(encounter_id)


def test_full_tier_ignores_a_non_active_encounter(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with postgres_engine.begin() as connection:
        encounter_id = make_encounter(
            connection, f.timeline_id, f.world_time_id, status="completed"
        )
        make_encounter_participant(connection, encounter_id, f.character_id)

    with client_factory(f.full_view_user_id) as client:
        response = client.get(_character_url(f))
    assert response.status_code == 200, response.text
    assert response.json()["active_encounter_id"] is None


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
# Resource-grant overrides on canon.edit (workstream 13 correction pass —
# dnd_ai.api.access.resolve_character_view_tier previously checked
# access.has_capability("canon.edit") with no character_id, which skips
# AccessContext.has_capability's resource-grant lookup entirely: a
# character-targeted deny could never override a role-derived GM, and a
# character-targeted allow could never substitute for one. Every check
# below now passes character_id=character_id, matching the
# character.view_full/character.view_summary checks either side of it.
# ---------------------------------------------------------------------------


def test_a_character_targeted_deny_for_canon_edit_overrides_role_derived_canon_edit(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """f.gm_user_id holds role-derived canon.edit — the pre-correction-pass
    bug ignored a deny targeting this exact character and always granted
    full access anyway. A parallel character.view_summary allow grant
    (rather than granting nothing at all) proves the tier resolution falls
    through to summary specifically, not merely "some check happened to
    fail" — the deny is honored for canon.edit alone, view_summary still
    applies on its own merits."""
    with postgres_engine.begin() as setup:
        make_resource_grant(
            setup,
            f.campaign_id,
            f.canon_edit_capability_id,
            character_id=f.character_id,
            grantee_campaign_membership_id=f.gm_membership_id,
            effect="deny",
        )
        make_resource_grant(
            setup,
            f.campaign_id,
            f.view_summary_capability_id,
            character_id=f.character_id,
            grantee_campaign_membership_id=f.gm_membership_id,
            effect="allow",
        )

    with client_factory(f.gm_user_id) as client:
        response = client.get(_character_url(f))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["name"] == "Aria"
    assert body["current_hit_points"] is None
    assert body["conditions"] is None


def test_a_character_targeted_deny_via_access_group_overrides_role_derived_canon_edit(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """Identical to the direct-membership deny above, but inherited through
    security.access_group_memberships rather than granted straight to
    f.gm_membership_id — proving the character_id fix applies uniformly
    regardless of how the grant reaches the caller. No compensating allow
    grant here, so the GM is left with no applicable capability at all for
    this character and the fixed 404 contract applies."""
    with postgres_engine.begin() as setup:
        access_group_id = make_access_group(setup, f.campaign_id)
        make_access_group_membership(setup, access_group_id, f.gm_membership_id)
        make_resource_grant(
            setup,
            f.campaign_id,
            f.canon_edit_capability_id,
            character_id=f.character_id,
            grantee_access_group_id=access_group_id,
            effect="deny",
        )

    with client_factory(f.gm_user_id) as client:
        response = client.get(_character_url(f))
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_a_character_targeted_canon_edit_allow_grants_full_access_without_a_role(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """f.no_character_capability_user_id holds campaign.view only — no
    canon.edit role, no character.view_full/view_summary relationship for
    this character. AccessContext.has_capability's own allow-grant
    semantics ("an allow... at the same or broader path" — §19.6) already
    support this once character_id reaches the canon.edit check; this
    proves the fix actually wires that through end to end at the API
    layer."""
    with postgres_engine.begin() as setup:
        make_resource_grant(
            setup,
            f.campaign_id,
            f.canon_edit_capability_id,
            character_id=f.character_id,
            grantee_campaign_membership_id=f.no_character_capability_membership_id,
            effect="allow",
        )

    with client_factory(f.no_character_capability_user_id) as client:
        response = client.get(_character_url(f))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["current_hit_points"] == 7
    assert body["conditions"] == [
        {"condition_code": "poisoned", "source_description": "stepped in ooze"}
    ]
    assert body["resources"] == [
        {"resource_code": "ki_points", "current_amount": 2, "maximum_amount": 4}
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


# ---------------------------------------------------------------------------
# FoundryAccess credential scope (Phase 11R workstream F, scope-enforced by
# the Workstream 11R High-severity correction) — the paired-device
# credential, exact-campaign- and exact-scope-scoped. The legacy
# FoundrySystem credential is retired (dnd_ai.api.auth) and rejected before
# it can ever reach a real HTTP request at all — see tests/database/
# test_api_auth.py's own "FoundrySystem credential is retired" section for
# that end-to-end proof; there is no principal shape left for this module
# to exercise via a directly-injected dependency override.
# ---------------------------------------------------------------------------


def _foundry_access_principal(
    *,
    user_id: uuid.UUID,
    world_id: uuid.UUID,
    campaign_id: uuid.UUID,
    foundry_scopes: frozenset[str] = frozenset({"encounter_read"}),
) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=user_id,
        auth_method=FOUNDRY_ACCESS_AUTH_METHOD,
        foundry_external_system_id=uuid.uuid4(),
        foundry_world_id=world_id,
        campaign_id=campaign_id,
        foundry_connection_id=uuid.uuid4(),
        foundry_device_id=uuid.uuid4(),
        foundry_scopes=foundry_scopes,
    )


def test_a_foundryaccess_credential_for_its_own_paired_campaign_can_read_the_character(
    foundry_client_factory: Callable[[AuthenticatedPrincipal], TestClient], f: Fixture
) -> None:
    principal = _foundry_access_principal(
        user_id=f.gm_user_id, world_id=f.world_id, campaign_id=f.campaign_id
    )
    with foundry_client_factory(principal) as client:
        response = client.get(_character_url(f))
    assert response.status_code == 200, response.text
    assert response.json()["character_id"] == str(f.character_id)


def test_a_foundryaccess_credential_for_a_different_campaign_cannot_read_the_character(
    foundry_client_factory: Callable[[AuthenticatedPrincipal], TestClient], f: Fixture
) -> None:
    # Exact-campaign scoping: a credential paired for any other campaign —
    # even a nonexistent one, since the comparison never needs to resolve
    # it — must not reach f.campaign_id.
    principal = _foundry_access_principal(
        user_id=f.gm_user_id, world_id=f.other_world_id, campaign_id=uuid.uuid4()
    )
    with foundry_client_factory(principal) as client:
        response = client.get(_character_url(f))
    assert response.status_code == 404


def test_a_foundryaccess_credential_cannot_read_inventory(
    foundry_client_factory: Callable[[AuthenticatedPrincipal], TestClient], f: Fixture
) -> None:
    principal = _foundry_access_principal(
        user_id=f.gm_user_id, world_id=f.world_id, campaign_id=f.campaign_id
    )
    with foundry_client_factory(principal) as client:
        response = client.get(_inventory_url(f))
    assert response.status_code == 403


def test_a_foundryaccess_credential_missing_encounter_read_scope_cannot_read_the_character(
    foundry_client_factory: Callable[[AuthenticatedPrincipal], TestClient], f: Fixture
) -> None:
    # Workstream 11R High-severity finding 1: get_character_endpoint
    # requires encounter_read specifically — a connection paired only with
    # a different scope (combat_sync here) must not reach it, even though
    # the bound user genuinely holds full character-view access and the
    # connection is paired for exactly this campaign.
    principal = _foundry_access_principal(
        user_id=f.gm_user_id,
        world_id=f.world_id,
        campaign_id=f.campaign_id,
        foundry_scopes=frozenset({"combat_sync"}),
    )
    with foundry_client_factory(principal) as client:
        response = client.get(_character_url(f))
    assert response.status_code == 403
