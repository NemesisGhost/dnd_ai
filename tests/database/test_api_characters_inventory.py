"""Tests for `dnd_ai.api.characters`'s inventory sub-resource — Phase 10
workstream 16's query over `dnd_ai.queries.inventory.get_inventory_view`
(docs/PLAN.md Phase 10 "query services for the effective dungeon,
character, quest, relationship, inventory, ... state required by the
vertical slice"). Mirrors `tests/database/test_api_characters.py`'s shape:
`get_authenticated_user_id` is overridden directly, since these tests
exercise campaign-capability enforcement and identification-gated
properties, not OIDC token verification. `resolve_character_view_tier`
itself is already exhaustively covered by `tests/database/
test_api_characters.py`; this file proves only that the inventory route
requires the full tier (never the summary tier) and wires identification
correctly.

Covers: access control (non-member 404, capless-member 403, a
summary-tier-only viewer 404), that definition/state fields are always
returned once authorized, that hidden properties follow the holder's own
`identification_level` (none for unidentified, the known subset for
partial, the full definition for fully identified), and that a GM sees
full properties regardless of identification state.
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
    make_inventory_entry,
    make_item_definition,
    make_item_identification,
    make_item_instance,
    make_item_ownership,
    make_item_state,
    make_membership_character_relationship,
    make_membership_role,
    make_relationship_type_capability,
    make_resource_grant,
    make_role,
    make_role_capability,
    make_ruleset_version_for_world,
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
        self.campaign_id = make_campaign(
            connection, self.timeline_id, lifecycle_status_code="pending"
        )

        ruleset_version_id = make_ruleset_version_for_world(connection, self.world_id)
        self.character_id = make_character(connection, self.world_id, name="Aria")

        mundane_definition_id = make_item_definition(
            connection,
            ruleset_version_id,
            display_name="Longsword",
            rarity="common",
            item_category_code="weapon",
        )
        self.mundane_item_id = make_item_instance(
            connection, self.world_id, mundane_definition_id, name="A Longsword"
        )
        make_item_state(connection, self.timeline_id, self.mundane_item_id, quantity=1)
        make_item_ownership(
            connection, self.timeline_id, self.mundane_item_id, owner_entity_id=self.character_id
        )
        make_inventory_entry(
            connection, self.timeline_id, self.mundane_item_id, holder_entity_id=self.character_id
        )

        self.ring_definition_id = make_item_definition(
            connection,
            ruleset_version_id,
            display_name="Ring of Mystery",
            rarity="rare",
            item_category_code="ring",
            properties={"bonus": "+2 AC", "curse": "binds permanently"},
        )
        self.ring_item_id = make_item_instance(
            connection, self.world_id, self.ring_definition_id, name="A Mysterious Ring"
        )
        make_item_state(connection, self.timeline_id, self.ring_item_id, quantity=1)
        make_inventory_entry(
            connection, self.timeline_id, self.ring_item_id, holder_entity_id=self.character_id
        )
        # No knowledge.item_identification row at all — defaults to
        # 'unidentified', properties hidden.

        self.partial_definition_id = make_item_definition(
            connection,
            ruleset_version_id,
            display_name="Strange Wand",
            rarity="uncommon",
            item_category_code="wand",
            properties={"charges": 7, "school": "evocation"},
        )
        self.partial_item_id = make_item_instance(
            connection, self.world_id, self.partial_definition_id, name="A Strange Wand"
        )
        make_item_state(connection, self.timeline_id, self.partial_item_id, quantity=1)
        make_inventory_entry(
            connection, self.timeline_id, self.partial_item_id, holder_entity_id=self.character_id
        )
        make_item_identification(
            connection,
            self.timeline_id,
            self.partial_item_id,
            self.character_id,
            identification_level="partially_identified",
            known_properties={"school": "evocation"},
        )

        self.full_definition_id = make_item_definition(
            connection,
            ruleset_version_id,
            display_name="Sunblade",
            rarity="very_rare",
            item_category_code="weapon",
            properties={"damage": "1d8 radiant"},
        )
        self.full_item_id = make_item_instance(
            connection, self.world_id, self.full_definition_id, name="A Sunblade"
        )
        make_item_state(connection, self.timeline_id, self.full_item_id, quantity=1)
        make_inventory_entry(
            connection, self.timeline_id, self.full_item_id, holder_entity_id=self.character_id
        )
        make_item_identification(
            connection,
            self.timeline_id,
            self.full_item_id,
            self.character_id,
            identification_level="fully_identified",
        )

        # A second, unrelated world — its character proves the cross-world
        # ownership check.
        self.other_world_id = make_world(connection, slug=f"{slug}-other-world")
        self.other_world_character_id = make_character(connection, self.other_world_id)

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

        self.canon_edit_capability_id = canon_edit_id

        base_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"viewer_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, base_role_id, view_capability_id)

        self.gm_user_id = make_user(connection, "Inventory Query GM")
        gm_membership_id = make_campaign_membership(connection, self.campaign_id, self.gm_user_id)
        self.gm_membership_id = gm_membership_id
        gm_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"gm_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, gm_role_id, view_capability_id)
        make_role_capability(connection, gm_role_id, canon_edit_id)
        make_membership_role(connection, gm_membership_id, gm_role_id)

        self.full_view_user_id = make_user(connection, "Inventory Query Full Viewer")
        full_view_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.full_view_user_id
        )
        make_membership_role(connection, full_view_membership_id, base_role_id)
        self.full_view_relationship_type_id = make_character_relationship_type(connection)
        make_relationship_type_capability(
            connection, self.full_view_relationship_type_id, view_full_capability_id
        )
        make_membership_character_relationship(
            connection,
            full_view_membership_id,
            self.character_id,
            self.full_view_relationship_type_id,
            timeline_id=self.timeline_id,
        )

        # Holds role-derived canon.edit *and* an independent
        # character.view_full relationship for f.character_id, so a
        # targeted canon.edit deny for that character still leaves
        # resolve_character_view_tier satisfied via the relationship —
        # isolating the reveal_all_properties regression from the tier
        # check itself.
        self.privileged_user_id = make_user(connection, "Inventory Query Privileged Member")
        privileged_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.privileged_user_id
        )
        self.privileged_membership_id = privileged_membership_id
        make_membership_role(connection, privileged_membership_id, gm_role_id)
        make_membership_character_relationship(
            connection,
            privileged_membership_id,
            self.character_id,
            self.full_view_relationship_type_id,
            timeline_id=self.timeline_id,
        )

        # Holds campaign.view only — no role-derived canon.edit, no
        # character relationship — proving a targeted canon.edit allow can
        # substitute for both at once.
        self.base_view_user_id = make_user(connection, "Inventory Query Base Viewer")
        base_view_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.base_view_user_id
        )
        self.base_view_membership_id = base_view_membership_id
        make_membership_role(connection, base_view_membership_id, base_role_id)

        self.summary_view_user_id = make_user(connection, "Inventory Query Summary Viewer")
        summary_view_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.summary_view_user_id
        )
        make_membership_role(connection, summary_view_membership_id, base_role_id)
        self.summary_view_relationship_type_id = make_character_relationship_type(connection)
        make_relationship_type_capability(
            connection, self.summary_view_relationship_type_id, view_summary_capability_id
        )
        make_membership_character_relationship(
            connection,
            summary_view_membership_id,
            self.character_id,
            self.summary_view_relationship_type_id,
            timeline_id=self.timeline_id,
        )

        # A member with no role/capability at all — proves ForbiddenError,
        # distinct from a non-member's NotFoundError.
        self.capless_user_id = make_user(connection, "Inventory Query Capless Member")
        make_campaign_membership(connection, self.campaign_id, self.capless_user_id)

        # Never given a membership at all.
        self.outsider_user_id = make_user(connection, "Inventory Query Outsider")


@pytest.fixture
def f(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as connection:
        fixture = Fixture(connection, f"inventory-query-{uuid.uuid4().hex[:8]}")
    yield fixture
    with postgres_engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        # See tests/database/test_api_dungeon.py's identical cleanup
        # comment for why session_replication_role = replica and explicit,
        # dependency-ordered deletes are used here.
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
            # security.resource_grants/access_group_memberships/
            # access_groups are created ad hoc by individual tests below
            # (the untargeted canon.edit correction pass's deny/allow-grant
            # regression tests), never by the shared Fixture itself —
            # cleaned up here, scoped by campaign_id, before the
            # campaign_memberships/access_groups rows they reference are
            # removed. See tests/database/test_api_characters.py's
            # identical cleanup for the same pattern.
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
                    DELETE FROM knowledge.item_identification WHERE timeline_id IN (
                        SELECT timeline_id FROM campaign.timelines WHERE world_id = :w
                    )
                """),
                {"w": world_id},
            )
            cleanup.execute(
                text("""
                    DELETE FROM campaign.inventory_entries WHERE timeline_id IN (
                        SELECT timeline_id FROM campaign.timelines WHERE world_id = :w
                    )
                """),
                {"w": world_id},
            )
            cleanup.execute(
                text("""
                    DELETE FROM campaign.item_ownership WHERE timeline_id IN (
                        SELECT timeline_id FROM campaign.timelines WHERE world_id = :w
                    )
                """),
                {"w": world_id},
            )
            cleanup.execute(
                text("""
                    DELETE FROM campaign.item_state WHERE timeline_id IN (
                        SELECT timeline_id FROM campaign.timelines WHERE world_id = :w
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
                    fixture.privileged_user_id,
                    fixture.base_view_user_id,
                    fixture.full_view_user_id,
                    fixture.summary_view_user_id,
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


def _inventory_url(f: Fixture, character_id: uuid.UUID | None = None) -> str:
    return f"/campaigns/{f.campaign_id}/characters/{character_id or f.character_id}/inventory"


def _by_item_id(body: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    return {item["item_instance_id"]: item for item in body}  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


def test_a_non_member_gets_not_found(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.outsider_user_id) as client:
        response = client.get(_inventory_url(f))
    assert response.status_code == 404


def test_a_member_without_campaign_view_gets_forbidden(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.capless_user_id) as client:
        response = client.get(_inventory_url(f))
    assert response.status_code == 403


def test_a_summary_tier_viewer_gets_not_found(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.summary_view_user_id) as client:
        response = client.get(_inventory_url(f))
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Identification-gated properties
# ---------------------------------------------------------------------------


def test_a_full_tier_viewer_sees_items_gated_by_the_holders_own_identification(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.full_view_user_id) as client:
        response = client.get(_inventory_url(f))
    assert response.status_code == 200, response.text
    body = response.json()
    items = _by_item_id(body)

    mundane = items[str(f.mundane_item_id)]
    assert mundane["display_name"] == "Longsword"
    assert mundane["item_category_code"] == "weapon"
    assert mundane["quantity"] == 1
    assert mundane["identification_level"] == "unidentified"
    assert mundane["properties"] is None

    unidentified_ring = items[str(f.ring_item_id)]
    assert unidentified_ring["identification_level"] == "unidentified"
    assert unidentified_ring["properties"] is None

    partial = items[str(f.partial_item_id)]
    assert partial["identification_level"] == "partially_identified"
    assert partial["properties"] == {"school": "evocation"}

    full = items[str(f.full_item_id)]
    assert full["identification_level"] == "fully_identified"
    assert full["properties"] == {"damage": "1d8 radiant"}


def test_a_gm_sees_full_properties_regardless_of_identification_state(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.get(_inventory_url(f))
    assert response.status_code == 200, response.text
    items = _by_item_id(response.json())

    unidentified_ring = items[str(f.ring_item_id)]
    assert unidentified_ring["identification_level"] == "unidentified"
    assert unidentified_ring["properties"] == {"bonus": "+2 AC", "curse": "binds permanently"}


# ---------------------------------------------------------------------------
# Resource-grant overrides for the reveal_all_properties (canon.edit) check
#
# dnd_ai.api.characters.get_character_inventory_endpoint used to check
# canon.edit with no character_id target, so a character-scoped
# security.resource_grants deny never reached it and a role-derived GM
# always saw every item's hidden properties. These tests prove the fixed,
# character_id-scoped check honors a targeted deny/allow, while inventory
# access itself (governed by resolve_character_view_tier, already
# character_id-scoped from an earlier correction pass) is unaffected.
# ---------------------------------------------------------------------------


def test_a_targeted_deny_for_canon_edit_hides_properties_but_leaves_inventory_accessible(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """f.privileged_user_id holds role-derived canon.edit *and* an
    independent character.view_full relationship for f.character_id — the
    pre-correction-pass bug ignored a deny targeting this exact character
    and always revealed every item's hidden properties anyway. The
    character.view_full relationship keeps resolve_character_view_tier
    satisfied on its own merits, isolating this regression to
    reveal_all_properties specifically."""
    with postgres_engine.begin() as setup:
        make_resource_grant(
            setup,
            f.campaign_id,
            f.canon_edit_capability_id,
            character_id=f.character_id,
            grantee_campaign_membership_id=f.privileged_membership_id,
            effect="deny",
        )

    with client_factory(f.privileged_user_id) as client:
        response = client.get(_inventory_url(f))
    assert response.status_code == 200, response.text
    items = _by_item_id(response.json())

    unidentified_ring = items[str(f.ring_item_id)]
    assert unidentified_ring["identification_level"] == "unidentified"
    assert unidentified_ring["properties"] is None

    full = items[str(f.full_item_id)]
    assert full["identification_level"] == "fully_identified"
    assert full["properties"] == {"damage": "1d8 radiant"}


def test_a_targeted_deny_via_access_group_hides_properties_but_leaves_inventory_accessible(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """Identical to the direct-membership deny above, but inherited through
    security.access_group_memberships rather than granted straight to
    f.privileged_membership_id — proving the fix applies uniformly
    regardless of how the grant reaches the caller."""
    with postgres_engine.begin() as setup:
        access_group_id = make_access_group(setup, f.campaign_id)
        make_access_group_membership(setup, access_group_id, f.privileged_membership_id)
        make_resource_grant(
            setup,
            f.campaign_id,
            f.canon_edit_capability_id,
            character_id=f.character_id,
            grantee_access_group_id=access_group_id,
            effect="deny",
        )

    with client_factory(f.privileged_user_id) as client:
        response = client.get(_inventory_url(f))
    assert response.status_code == 200, response.text
    items = _by_item_id(response.json())

    unidentified_ring = items[str(f.ring_item_id)]
    assert unidentified_ring["identification_level"] == "unidentified"
    assert unidentified_ring["properties"] is None


def test_a_targeted_canon_edit_allow_reveals_properties_without_a_role(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """f.base_view_user_id holds campaign.view only — no role-derived
    canon.edit, no character.view_full/view_summary relationship. A
    canon.edit allow targeted at f.character_id both unlocks inventory
    access at all (via resolve_character_view_tier's own identical,
    already-fixed character_id-scoped check) and reveals every item's
    hidden properties — proving the targeted-allow path this correction
    pass preserves."""
    with postgres_engine.begin() as setup:
        make_resource_grant(
            setup,
            f.campaign_id,
            f.canon_edit_capability_id,
            character_id=f.character_id,
            grantee_campaign_membership_id=f.base_view_membership_id,
            effect="allow",
        )

    with client_factory(f.base_view_user_id) as client:
        response = client.get(_inventory_url(f))
    assert response.status_code == 200, response.text
    items = _by_item_id(response.json())

    unidentified_ring = items[str(f.ring_item_id)]
    assert unidentified_ring["identification_level"] == "unidentified"
    assert unidentified_ring["properties"] == {"bonus": "+2 AC", "curse": "binds permanently"}


# ---------------------------------------------------------------------------
# Cross-world ownership
# ---------------------------------------------------------------------------


def test_a_holder_in_a_different_world_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.get(_inventory_url(f, f.other_world_character_id))
    assert response.status_code == 404
