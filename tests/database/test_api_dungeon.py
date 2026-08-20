"""Tests for `dnd_ai.api.dungeon` — Phase 10 workstream 12's query endpoint
over `dnd_ai.queries.dungeon.get_dungeon_area_view` (docs/PLAN.md Phase 10
"query services for the effective dungeon, ... state required by the
vertical slice"). Mirrors `tests/database/test_api_quests.py`'s shape:
`get_authenticated_user_id` is overridden directly, since these tests
exercise campaign-capability enforcement, party-scoped audience filtering,
and cross-world ownership — not OIDC token verification, already covered
by `tests/database/test_api_auth.py`.

Covers: access control (non-member/capless-member), GM vs. player audience
filtering (a GM sees every structural child regardless of `is_hidden`; a
player sees a hidden child only once their party has discovered it, and
otherwise not at all — not merely flagged, per docs/PLAN.md §25 step 15's
"cannot be inferred through counts... or errors"), and — the workstream 12
correction pass's central concern — that a `party_id` is never trusted for
hidden-content filtering merely because it is associated with the caller's
own campaign (`dnd_ai.api.access.resolve_party_perspective`). A `party_id`
is authorized only paired with a `character_id` the caller holds
`character.view_knowledge` for, and only when that character is currently
a member of exactly that party (`campaign.party_memberships`). The fixture
sets up two same-campaign parties, each with its own current member, so
these tests can prove player A's authorized character unlocks party A's
discoveries but never party B's — regardless of whether player A merely
guesses party B's UUID or names a real member of party B that player A
itself has no relationship to.
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
    make_area_connection,
    make_area_feature,
    make_area_hazard,
    make_area_interactable,
    make_campaign,
    make_campaign_membership,
    make_campaign_party,
    make_character,
    make_character_relationship_type,
    make_dungeon,
    make_dungeon_area,
    make_knowledge_item,
    make_membership_character_relationship,
    make_membership_role,
    make_party,
    make_party_discovery,
    make_party_membership,
    make_relationship_type_capability,
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
        self.world_time_id = make_world_time(connection, self.world_id, 100)
        # "pending" sidesteps the active-campaign access-manager retention
        # invariant (revision 080) — these tests grant campaign.view/
        # canon.edit, not access.manage, and don't otherwise care about
        # campaign lifecycle (same reasoning test_api_quests.py's Fixture
        # documents).
        self.campaign_id = make_campaign(
            connection, self.timeline_id, lifecycle_status_code="pending"
        )
        self.other_campaign_id = make_campaign(
            connection, self.timeline_id, "Other Campaign", lifecycle_status_code="pending"
        )

        self.dungeon_id = make_dungeon(connection, self.world_id)
        self.area_a_id = make_dungeon_area(connection, self.dungeon_id, name="Area A")
        self.area_b_id = make_dungeon_area(connection, self.dungeon_id, name="Area B")

        self.visible_feature_id = make_area_feature(connection, self.area_a_id, is_hidden=False)
        self.hidden_feature_id = make_area_feature(connection, self.area_a_id, is_hidden=True)
        self.hidden_feature_knowledge_id = make_knowledge_item(
            connection,
            self.world_id,
            statement="A statue hides a switch.",
            subject_area_feature_id=self.hidden_feature_id,
        )

        self.visible_hazard_id = make_area_hazard(connection, self.area_a_id, is_hidden=False)
        self.hidden_hazard_id = make_area_hazard(connection, self.area_a_id, is_hidden=True)
        make_knowledge_item(
            connection,
            self.world_id,
            statement="A pressure plate trap is set here.",
            subject_area_hazard_id=self.hidden_hazard_id,
        )

        self.visible_interactable_id = make_area_interactable(
            connection, self.area_a_id, is_hidden=False
        )
        self.hidden_interactable_id = make_area_interactable(
            connection, self.area_a_id, is_hidden=True
        )
        make_knowledge_item(
            connection,
            self.world_id,
            statement="A hidden lever is set into the wall.",
            subject_area_interactable_id=self.hidden_interactable_id,
        )

        self.visible_connection_id = make_area_connection(
            connection, self.area_a_id, self.area_b_id, is_hidden=False
        )
        self.hidden_connection_id = make_area_connection(
            connection, self.area_a_id, self.area_b_id, is_hidden=True
        )
        make_knowledge_item(
            connection,
            self.world_id,
            statement="A secret door connects these rooms.",
            subject_area_connection_id=self.hidden_connection_id,
        )

        # Party A — the party player_user is actually entitled to see
        # through (its character_a is a current member, and player_user
        # holds character.view_knowledge for character_a).
        self.party_id = make_party(connection, self.world_id, name="The Company")
        make_campaign_party(connection, self.campaign_id, self.party_id)
        # Discovers only the hidden feature — proves filtering is per
        # structural child, not an all-or-nothing party flag.
        make_party_discovery(
            connection,
            self.timeline_id,
            self.hidden_feature_knowledge_id,
            party_id=self.party_id,
        )

        # Party B — a second, real party in the *same* campaign. Nothing
        # about player_user relates to it; used to prove that campaign
        # association alone (or knowing/guessing its UUID) never unlocks
        # its discoveries.
        self.party_b_id = make_party(connection, self.world_id, name="The Rivals")
        make_campaign_party(connection, self.campaign_id, self.party_b_id)

        # Associated only with the *other* campaign — same world/timeline,
        # so campaign.enforce_campaign_party_world() alone lets it through.
        # Proves party_id is checked against campaign_id specifically.
        self.foreign_party_id = make_party(connection, self.world_id, name="Foreign Party")
        make_campaign_party(connection, self.other_campaign_id, self.foreign_party_id)

        # A second, unrelated world — its dungeon area proves the
        # cross-world ownership check (no campaign_id column exists on any
        # dungeon-domain table, so world agreement stands in for it).
        self.other_world_id = make_world(connection, slug=f"{slug}-other-world")
        other_dungeon_id = make_dungeon(connection, self.other_world_id)
        self.other_world_area_id = make_dungeon_area(connection, other_dungeon_id)

        view_capability_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "campaign.view"
        )
        canon_edit_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "canon.edit"
        )
        view_knowledge_capability_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "character.view_knowledge"
        )

        self.gm_user_id = make_user(connection, "Dungeon API GM")
        gm_membership_id = make_campaign_membership(connection, self.campaign_id, self.gm_user_id)
        gm_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"gm_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, gm_role_id, view_capability_id)
        make_role_capability(connection, gm_role_id, canon_edit_id)
        make_membership_role(connection, gm_membership_id, gm_role_id)

        self.player_user_id = make_user(connection, "Dungeon API Player")
        player_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.player_user_id
        )
        player_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"player_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, player_role_id, view_capability_id)
        make_membership_role(connection, player_membership_id, player_role_id)

        # character_a: player_user's own character — currently a member of
        # Party A, and player_user holds character.view_knowledge for it
        # via a real membership_character_relationship (not a blanket role
        # capability), the same resource-scoped shape resolve_party_
        # perspective() requires.
        self.character_a_id = make_character(connection, self.world_id, name="Aria")
        make_party_membership(
            connection, self.timeline_id, self.party_id, self.character_a_id, self.world_time_id
        )
        # security.character_relationship_types is a global lookup table,
        # not scoped by world — cleanup below deletes this specific row
        # explicitly by id, the same way it must for any shared lookup row
        # a test creates.
        self.controller_relationship_type_id = make_character_relationship_type(connection)
        make_relationship_type_capability(
            connection, self.controller_relationship_type_id, view_knowledge_capability_id
        )
        make_membership_character_relationship(
            connection,
            player_membership_id,
            self.character_a_id,
            self.controller_relationship_type_id,
            timeline_id=self.timeline_id,
        )

        # character_b: a real, current member of Party B — but player_user
        # has *no* relationship to it at all. Proves a character the
        # caller cannot view/control can't be used to unlock a party it
        # does genuinely belong to.
        self.character_b_id = make_character(connection, self.world_id, name="Borin")
        make_party_membership(
            connection, self.timeline_id, self.party_b_id, self.character_b_id, self.world_time_id
        )

        self.canon_edit_capability_id = canon_edit_id

        # Holds role-derived canon.edit *and* an independent
        # character.view_knowledge relationship for character_a (the same
        # relationship player_user holds), so a targeted canon.edit deny
        # for area_a_id still leaves an authorized party perspective
        # available — isolating the include_hidden regression from
        # party-perspective authorization itself.
        self.privileged_user_id = make_user(connection, "Dungeon API Privileged Member")
        privileged_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.privileged_user_id
        )
        self.privileged_membership_id = privileged_membership_id
        make_membership_role(connection, privileged_membership_id, gm_role_id)
        make_membership_character_relationship(
            connection,
            privileged_membership_id,
            self.character_a_id,
            self.controller_relationship_type_id,
            timeline_id=self.timeline_id,
        )

        # Holds campaign.view only — no role-derived canon.edit, no
        # character relationship — proving a targeted canon.edit allow can
        # unlock every structural child, hidden included, without either.
        self.base_view_user_id = make_user(connection, "Dungeon API Base Viewer")
        base_view_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.base_view_user_id
        )
        self.base_view_membership_id = base_view_membership_id
        make_membership_role(connection, base_view_membership_id, player_role_id)

        # A member with no role/capability at all — proves ForbiddenError,
        # distinct from a non-member's NotFoundError.
        self.capless_user_id = make_user(connection, "Dungeon API Capless Member")
        make_campaign_membership(connection, self.campaign_id, self.capless_user_id)

        # Never given a membership at all.
        self.outsider_user_id = make_user(connection, "Dungeon API Outsider")


@pytest.fixture
def f(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as connection:
        fixture = Fixture(connection, f"dungeon-api-{uuid.uuid4().hex[:8]}")
    yield fixture
    with postgres_engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        # See tests/database/test_api_quests.py's identical cleanup comment:
        # session_replication_role = replica disables the cascades the
        # later DELETE FROM core.entities/core.worlds statements would
        # otherwise apply, and revision 080's DEFERRABLE constraint
        # triggers on several security.* tables can fail a later, unrelated
        # test in the same pytest session if left behind. Deleted
        # explicitly here, in dependency order, scoped to this fixture's
        # two worlds.
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
                    DELETE FROM knowledge.party_discoveries WHERE knowledge_item_id IN (
                        SELECT knowledge_item_id FROM knowledge.knowledge_items ki
                        JOIN core.entities e ON e.entity_id = ki.knowledge_item_id
                        WHERE e.world_id = :w
                    )
                """),
                {"w": world_id},
            )
            cleanup.execute(
                text("""
                    DELETE FROM campaign.party_memberships WHERE timeline_id IN (
                        SELECT timeline_id FROM campaign.timelines WHERE world_id = :w
                    )
                """),
                {"w": world_id},
            )
            cleanup.execute(
                text("""
                    DELETE FROM campaign.campaign_parties WHERE campaign_id IN (
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
                text("DELETE FROM campaign.parties WHERE world_id = :w"), {"w": world_id}
            )
            cleanup.execute(
                text("DELETE FROM campaign.timelines WHERE world_id = :w"), {"w": world_id}
            )
            cleanup.execute(text("DELETE FROM core.entities WHERE world_id = :w"), {"w": world_id})
            cleanup.execute(text("DELETE FROM core.worlds WHERE world_id = :w"), {"w": world_id})
        # security.character_relationship_types (and its capability grant)
        # is a global lookup table, not scoped by world — the per-world
        # loop above already removed the membership_character_relationships
        # row referencing it, so this specific row is safe to delete here
        # by id, the same explicit-by-id discipline every other shared
        # lookup table in this codebase's tests already follows.
        cleanup.execute(
            text(
                "DELETE FROM security.character_relationship_type_capabilities "
                "WHERE character_relationship_type_id = :rt"
            ),
            {"rt": fixture.controller_relationship_type_id},
        )
        cleanup.execute(
            text(
                "DELETE FROM security.character_relationship_types WHERE character_relationship_type_id = :rt"
            ),
            {"rt": fixture.controller_relationship_type_id},
        )
        cleanup.execute(
            text("DELETE FROM security.users WHERE user_id = ANY(:users)"),
            {
                "users": [
                    fixture.gm_user_id,
                    fixture.player_user_id,
                    fixture.privileged_user_id,
                    fixture.base_view_user_id,
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


def _area_url(f: Fixture, area_id: uuid.UUID | None = None) -> str:
    return f"/campaigns/{f.campaign_id}/dungeon-areas/{area_id or f.area_a_id}"


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


def test_a_non_member_gets_not_found(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.outsider_user_id) as client:
        response = client.get(_area_url(f))
    assert response.status_code == 404


def test_a_member_without_campaign_view_gets_forbidden(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.capless_user_id) as client:
        response = client.get(_area_url(f))
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Audience filtering
# ---------------------------------------------------------------------------


def test_a_gm_sees_every_structural_child_including_hidden_ones(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.get(_area_url(f))
    assert response.status_code == 200, response.text
    body = response.json()

    assert {feat["area_feature_id"] for feat in body["features"]} == {
        str(f.visible_feature_id),
        str(f.hidden_feature_id),
    }
    assert {haz["area_hazard_id"] for haz in body["hazards"]} == {
        str(f.visible_hazard_id),
        str(f.hidden_hazard_id),
    }
    assert {ia["area_interactable_id"] for ia in body["interactables"]} == {
        str(f.visible_interactable_id),
        str(f.hidden_interactable_id),
    }
    assert {c["area_connection_id"] for c in body["connections"]} == {
        str(f.visible_connection_id),
        str(f.hidden_connection_id),
    }


def test_a_player_with_no_perspective_sees_only_non_hidden_content(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.player_user_id) as client:
        response = client.get(_area_url(f))
    assert response.status_code == 200, response.text
    body = response.json()

    assert {feat["area_feature_id"] for feat in body["features"]} == {str(f.visible_feature_id)}
    assert {haz["area_hazard_id"] for haz in body["hazards"]} == {str(f.visible_hazard_id)}
    assert {ia["area_interactable_id"] for ia in body["interactables"]} == {
        str(f.visible_interactable_id)
    }
    assert {c["area_connection_id"] for c in body["connections"]} == {str(f.visible_connection_id)}


def test_supplying_only_party_id_without_a_character_is_treated_as_no_perspective(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    """The pre-correction-pass shape of this request (bare party_id, no
    character_id) must never grant hidden access on its own — it is
    silently treated as no perspective at all, not an error and not a
    shortcut to authorization."""
    with client_factory(f.player_user_id) as client:
        response = client.get(_area_url(f), params={"party_id": str(f.party_id)})
    assert response.status_code == 200, response.text
    body = response.json()
    assert {feat["area_feature_id"] for feat in body["features"]} == {str(f.visible_feature_id)}


def test_a_player_with_an_authorized_character_sees_their_partys_discoveries(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.player_user_id) as client:
        response = client.get(
            _area_url(f),
            params={"character_id": str(f.character_a_id), "party_id": str(f.party_id)},
        )
    assert response.status_code == 200, response.text
    body = response.json()

    # The party discovered only the hidden feature — the hidden hazard,
    # interactable, and connection remain excluded entirely, not merely
    # flagged (docs/PLAN.md §25 step 15's non-disclosure rule).
    assert {feat["area_feature_id"] for feat in body["features"]} == {
        str(f.visible_feature_id),
        str(f.hidden_feature_id),
    }
    discovered_feature = next(
        feat for feat in body["features"] if feat["area_feature_id"] == str(f.hidden_feature_id)
    )
    assert discovered_feature["is_hidden"] is True

    assert {haz["area_hazard_id"] for haz in body["hazards"]} == {str(f.visible_hazard_id)}
    assert {ia["area_interactable_id"] for ia in body["interactables"]} == {
        str(f.visible_interactable_id)
    }
    assert {c["area_connection_id"] for c in body["connections"]} == {str(f.visible_connection_id)}


def test_connection_direction_is_reported_relative_to_the_queried_area(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.get(_area_url(f))
    assert response.status_code == 200, response.text
    body = response.json()

    visible = next(
        c for c in body["connections"] if c["area_connection_id"] == str(f.visible_connection_id)
    )
    assert visible["direction"] == "outgoing"
    assert visible["other_dungeon_area_id"] == str(f.area_b_id)


def test_location_state_defaults_when_no_state_row_exists(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.get(_area_url(f))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["is_searched"] is False
    assert body["is_destroyed"] is False
    assert body["alarm_level"] == 0
    assert body["condition_notes"] is None


# ---------------------------------------------------------------------------
# Resource-grant overrides for the include_hidden (canon.edit) check
#
# dnd_ai.api.dungeon.get_dungeon_area_endpoint used to check canon.edit
# with no entity_id target, so an entity-scoped security.resource_grants
# deny never reached it and a role-derived GM always saw every structural
# child. These tests prove the fixed, entity_id-scoped check (targeting
# area_a_id, which doubles as its own core.entities.entity_id) honors a
# targeted deny/allow, and that a caller denied full visibility for one
# area still falls through cleanly to an authorized party perspective.
# ---------------------------------------------------------------------------


def test_a_targeted_deny_for_canon_edit_falls_through_to_party_perspective(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """f.privileged_user_id holds role-derived canon.edit *and* an
    independent character.view_knowledge relationship for character_a (the
    same relationship player_user holds) — the pre-correction-pass bug
    ignored a deny targeting this exact area and always returned every
    structural child regardless of is_hidden anyway. The view_knowledge
    relationship keeps resolve_party_perspective satisfied on its own
    merits, isolating this regression to include_hidden specifically."""
    with postgres_engine.begin() as setup:
        make_resource_grant(
            setup,
            f.campaign_id,
            f.canon_edit_capability_id,
            entity_id=f.area_a_id,
            grantee_campaign_membership_id=f.privileged_membership_id,
            effect="deny",
        )

    with client_factory(f.privileged_user_id) as client:
        response = client.get(
            _area_url(f),
            params={"character_id": str(f.character_a_id), "party_id": str(f.party_id)},
        )
    assert response.status_code == 200, response.text
    body = response.json()

    assert {feat["area_feature_id"] for feat in body["features"]} == {
        str(f.visible_feature_id),
        str(f.hidden_feature_id),
    }
    assert {haz["area_hazard_id"] for haz in body["hazards"]} == {str(f.visible_hazard_id)}
    assert {ia["area_interactable_id"] for ia in body["interactables"]} == {
        str(f.visible_interactable_id)
    }
    assert {c["area_connection_id"] for c in body["connections"]} == {str(f.visible_connection_id)}


def test_a_targeted_deny_via_access_group_falls_through_to_party_perspective(
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
            entity_id=f.area_a_id,
            grantee_access_group_id=access_group_id,
            effect="deny",
        )

    with client_factory(f.privileged_user_id) as client:
        response = client.get(
            _area_url(f),
            params={"character_id": str(f.character_a_id), "party_id": str(f.party_id)},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert {feat["area_feature_id"] for feat in body["features"]} == {
        str(f.visible_feature_id),
        str(f.hidden_feature_id),
    }
    assert {haz["area_hazard_id"] for haz in body["hazards"]} == {str(f.visible_hazard_id)}


def test_a_targeted_canon_edit_allow_reveals_every_structural_child_without_a_role(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """f.base_view_user_id holds campaign.view only — no role-derived
    canon.edit, no character.view_knowledge relationship. A canon.edit
    allow targeted at f.area_a_id unlocks every structural child regardless
    of is_hidden without supplying (or being authorized for) any party
    perspective at all — proving the targeted-allow path this correction
    pass preserves."""
    with postgres_engine.begin() as setup:
        make_resource_grant(
            setup,
            f.campaign_id,
            f.canon_edit_capability_id,
            entity_id=f.area_a_id,
            grantee_campaign_membership_id=f.base_view_membership_id,
            effect="allow",
        )

    with client_factory(f.base_view_user_id) as client:
        response = client.get(_area_url(f))
    assert response.status_code == 200, response.text
    body = response.json()

    assert {feat["area_feature_id"] for feat in body["features"]} == {
        str(f.visible_feature_id),
        str(f.hidden_feature_id),
    }
    assert {haz["area_hazard_id"] for haz in body["hazards"]} == {
        str(f.visible_hazard_id),
        str(f.hidden_hazard_id),
    }
    assert {ia["area_interactable_id"] for ia in body["interactables"]} == {
        str(f.visible_interactable_id),
        str(f.hidden_interactable_id),
    }
    assert {c["area_connection_id"] for c in body["connections"]} == {
        str(f.visible_connection_id),
        str(f.hidden_connection_id),
    }


# ---------------------------------------------------------------------------
# Party-perspective authorization
# (dnd_ai.api.access.resolve_party_perspective, workstream 12 correction pass)
# ---------------------------------------------------------------------------


def test_a_players_own_character_cannot_be_used_to_view_a_different_party(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    """character_a genuinely exists, is genuinely a party member, and
    player_user genuinely holds character.view_knowledge for it — just not
    for party_b. Proves the party/character pairing itself is checked, not
    merely "does the caller have some authorized character.\""""
    with client_factory(f.player_user_id) as client:
        response = client.get(
            _area_url(f),
            params={"character_id": str(f.character_a_id), "party_id": str(f.party_b_id)},
        )
    assert response.status_code == 404


def test_an_unauthorized_character_cannot_be_used_to_unlock_a_party_it_belongs_to(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    """character_b is a genuine, current member of party_b — but
    player_user has no character.view_knowledge relationship to character_b
    at all. Proves the capability check on the character itself is
    enforced, not bypassable by naming a character that happens to be a
    real party member."""
    with client_factory(f.player_user_id) as client:
        response = client.get(
            _area_url(f),
            params={"character_id": str(f.character_b_id), "party_id": str(f.party_b_id)},
        )
    assert response.status_code == 404


def test_guessing_a_different_partys_uuid_does_not_change_the_response(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    """A real, same-campaign party's UUID and a nonexistent one must be
    rejected identically — otherwise the response itself would disclose
    which UUIDs name real parties."""
    with client_factory(f.player_user_id) as client:
        real_party = client.get(
            _area_url(f),
            params={"character_id": str(f.character_a_id), "party_id": str(f.party_b_id)},
        )
        nonexistent_party = client.get(
            _area_url(f),
            params={"character_id": str(f.character_a_id), "party_id": str(uuid.uuid4())},
        )
    assert real_party.status_code == 404
    assert nonexistent_party.status_code == 404
    # correlation_id is a fresh per-request identifier, never a disclosure
    # channel on its own — everything else in the error body (the part
    # that could actually leak which UUID was real) must match exactly.
    assert real_party.json()["error"]["code"] == nonexistent_party.json()["error"]["code"]
    assert real_party.json()["error"]["message"] == nonexistent_party.json()["error"]["message"]


def test_a_party_from_a_different_campaign_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.player_user_id) as client:
        response = client.get(
            _area_url(f),
            params={"character_id": str(f.character_a_id), "party_id": str(f.foreign_party_id)},
        )
    assert response.status_code == 404


def test_an_area_in_a_different_world_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.get(_area_url(f, f.other_world_area_id))
    assert response.status_code == 404


def test_a_nonexistent_area_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.get(_area_url(f, uuid.uuid4()))
    assert response.status_code == 404
