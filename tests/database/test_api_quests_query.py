"""Tests for `dnd_ai.api.quests`'s read endpoint — Phase 10 workstream 14's
query over `dnd_ai.queries.quest.get_quest_view` (docs/PLAN.md Phase 10
"query services for the effective dungeon, character, quest, ... state
required by the vertical slice"). Mirrors `tests/database/
test_api_dungeon.py`'s shape: `get_authenticated_user_id` is overridden
directly, since these tests exercise campaign-capability enforcement and
`visibility_policy` filtering, not OIDC token verification. Party-
perspective authorization itself (`dnd_ai.api.access.
resolve_party_perspective`) is already exhaustively covered by
`tests/database/test_api_dungeon.py`; this file proves only that the quest
route wires it correctly, not every edge case again.

Covers: access control (non-member 404, capless-member 403),
`visibility_policy` filtering ('visible' always shown, 'gm_only' only to a
GM, 'hidden_until_active'/'hidden_until_discovered' shown to a non-GM only
once a `campaign.objective_state` row exists), the party-scoped-over-
campaign-wide status fallback for both quest- and objective-level state,
and cross-world/nonexistent-quest rejection.
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
    make_campaign_party,
    make_character,
    make_character_relationship_type,
    make_membership_character_relationship,
    make_membership_role,
    make_objective_state,
    make_party,
    make_party_membership,
    make_quest,
    make_quest_objective,
    make_quest_stage,
    make_quest_state,
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
        self.campaign_id = make_campaign(
            connection, self.timeline_id, lifecycle_status_code="pending"
        )

        self.quest_id = make_quest(connection, self.world_id, name="Restore the Shrine")
        self.stage_id = make_quest_stage(connection, self.quest_id, name="Stage One")

        self.visible_objective_id = make_quest_objective(
            connection, self.stage_id, name="Talk to the elder", visibility_policy="visible"
        )
        self.gm_only_objective_id = make_quest_objective(
            connection, self.stage_id, name="Secret GM note", visibility_policy="gm_only"
        )
        self.hidden_until_active_objective_id = make_quest_objective(
            connection, self.stage_id, name="Ambush point", visibility_policy="hidden_until_active"
        )
        self.hidden_until_discovered_objective_id = make_quest_objective(
            connection,
            self.stage_id,
            name="Hidden lore",
            visibility_policy="hidden_until_discovered",
        )

        # A campaign-wide state row unlocks hidden_until_active for a
        # non-GM; hidden_until_discovered gets no state row at all, so it
        # stays hidden — together proving both values share the same
        # "has any state at all" signal this first cut collapses them to.
        make_objective_state(
            connection,
            self.timeline_id,
            self.hidden_until_active_objective_id,
            status_code="active",
        )

        self.party_id = make_party(connection, self.world_id, name="The Company")
        make_campaign_party(connection, self.campaign_id, self.party_id)

        make_quest_state(connection, self.timeline_id, self.quest_id, status_code="active")
        make_quest_state(
            connection,
            self.timeline_id,
            self.quest_id,
            party_id=self.party_id,
            status_code="completed",
        )
        make_objective_state(
            connection, self.timeline_id, self.visible_objective_id, status_code="active"
        )
        make_objective_state(
            connection,
            self.timeline_id,
            self.visible_objective_id,
            party_id=self.party_id,
            status_code="completed",
        )

        # A second, unrelated world — its quest proves the cross-world
        # ownership check (narrative.quests carries no campaign_id at all,
        # so world agreement stands in for it).
        self.other_world_id = make_world(connection, slug=f"{slug}-other-world")
        self.other_world_quest_id = make_quest(connection, self.other_world_id)

        view_capability_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "campaign.view"
        )
        canon_edit_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "canon.edit"
        )
        view_knowledge_capability_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "character.view_knowledge"
        )
        self.view_capability_id = view_capability_id

        self.gm_user_id = make_user(connection, "Quest Query GM")
        gm_membership_id = make_campaign_membership(connection, self.campaign_id, self.gm_user_id)
        self.gm_membership_id = gm_membership_id
        gm_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"gm_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, gm_role_id, view_capability_id)
        make_role_capability(connection, gm_role_id, canon_edit_id)
        make_membership_role(connection, gm_membership_id, gm_role_id)

        self.player_user_id = make_user(connection, "Quest Query Player")
        player_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.player_user_id
        )
        player_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"player_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, player_role_id, view_capability_id)
        make_membership_role(connection, player_membership_id, player_role_id)

        self.character_id = make_character(connection, self.world_id, name="Aria")
        make_party_membership(
            connection, self.timeline_id, self.party_id, self.character_id, self.world_time_id
        )
        # security.character_relationship_types is a global lookup table,
        # not scoped by world — cleanup below deletes this specific row
        # explicitly by id.
        self.relationship_type_id = make_character_relationship_type(connection)
        make_relationship_type_capability(
            connection, self.relationship_type_id, view_knowledge_capability_id
        )
        make_membership_character_relationship(
            connection,
            player_membership_id,
            self.character_id,
            self.relationship_type_id,
            timeline_id=self.timeline_id,
        )

        self.canon_edit_capability_id = canon_edit_id

        # Holds role-derived canon.edit *and* an independent
        # character.view_knowledge relationship for f.character_id, so a
        # targeted canon.edit deny for a specific quest still leaves an
        # authorized party perspective available — isolating the
        # include_hidden regression from party-perspective authorization
        # itself.
        self.privileged_user_id = make_user(connection, "Quest Query Privileged Member")
        privileged_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.privileged_user_id
        )
        self.privileged_membership_id = privileged_membership_id
        make_membership_role(connection, privileged_membership_id, gm_role_id)
        make_membership_character_relationship(
            connection,
            privileged_membership_id,
            self.character_id,
            self.relationship_type_id,
            timeline_id=self.timeline_id,
        )

        # Holds campaign.view only — no role-derived canon.edit, no
        # character relationship — proving a targeted canon.edit allow can
        # unlock every objective without either.
        self.base_view_user_id = make_user(connection, "Quest Query Base Viewer")
        base_view_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.base_view_user_id
        )
        self.base_view_membership_id = base_view_membership_id
        make_membership_role(connection, base_view_membership_id, player_role_id)

        # A member with no role/capability at all — proves ForbiddenError,
        # distinct from a non-member's NotFoundError.
        self.capless_user_id = make_user(connection, "Quest Query Capless Member")
        make_campaign_membership(connection, self.campaign_id, self.capless_user_id)

        # Never given a membership at all.
        self.outsider_user_id = make_user(connection, "Quest Query Outsider")


@pytest.fixture
def f(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as connection:
        fixture = Fixture(connection, f"quest-query-{uuid.uuid4().hex[:8]}")
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
        # by id.
        cleanup.execute(
            text(
                "DELETE FROM security.character_relationship_type_capabilities "
                "WHERE character_relationship_type_id = :rt"
            ),
            {"rt": fixture.relationship_type_id},
        )
        cleanup.execute(
            text(
                "DELETE FROM security.character_relationship_types "
                "WHERE character_relationship_type_id = :rt"
            ),
            {"rt": fixture.relationship_type_id},
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


def _quest_url(f: Fixture, quest_id: uuid.UUID | None = None) -> str:
    return f"/campaigns/{f.campaign_id}/quests/{quest_id or f.quest_id}"


def _objective_ids(body: dict[str, object]) -> set[str]:
    ids: set[str] = set()
    for stage in body["stages"]:  # type: ignore[index]
        for objective in stage["objectives"]:
            ids.add(objective["quest_objective_id"])
    return ids


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


def test_a_non_member_gets_not_found(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.outsider_user_id) as client:
        response = client.get(_quest_url(f))
    assert response.status_code == 404


def test_a_member_without_campaign_view_gets_forbidden(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.capless_user_id) as client:
        response = client.get(_quest_url(f))
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# visibility_policy filtering
# ---------------------------------------------------------------------------


def test_a_gm_sees_every_objective_regardless_of_visibility_policy(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.get(_quest_url(f))
    assert response.status_code == 200, response.text
    body = response.json()
    assert _objective_ids(body) == {
        str(f.visible_objective_id),
        str(f.gm_only_objective_id),
        str(f.hidden_until_active_objective_id),
        str(f.hidden_until_discovered_objective_id),
    }


def test_a_player_sees_visible_and_activated_but_not_gm_only_or_undiscovered(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.player_user_id) as client:
        response = client.get(_quest_url(f))
    assert response.status_code == 200, response.text
    body = response.json()
    assert _objective_ids(body) == {
        str(f.visible_objective_id),
        str(f.hidden_until_active_objective_id),
    }


# ---------------------------------------------------------------------------
# Resource-grant overrides for the include_hidden (canon.edit) check
#
# dnd_ai.api.quests.get_quest_endpoint used to check canon.edit with no
# quest_id target, so a quest-scoped security.resource_grants deny never
# reached it and a role-derived GM always saw every objective. These tests
# prove the fixed, quest_id-scoped check honors a targeted deny/allow, and
# that a caller denied full visibility for one quest still falls through
# cleanly to an authorized party perspective.
# ---------------------------------------------------------------------------


def test_a_targeted_deny_for_canon_edit_falls_through_to_party_perspective(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """f.privileged_user_id holds role-derived canon.edit *and* an
    independent character.view_knowledge relationship for f.character_id —
    the pre-correction-pass bug ignored a deny targeting this exact quest
    and always returned every objective regardless of visibility_policy
    anyway. The view_knowledge relationship keeps resolve_party_perspective
    satisfied on its own merits, isolating this regression to
    include_hidden specifically."""
    with postgres_engine.begin() as setup:
        make_resource_grant(
            setup,
            f.campaign_id,
            f.canon_edit_capability_id,
            quest_id=f.quest_id,
            grantee_campaign_membership_id=f.privileged_membership_id,
            effect="deny",
        )

    with client_factory(f.privileged_user_id) as client:
        response = client.get(
            _quest_url(f),
            params={"character_id": str(f.character_id), "party_id": str(f.party_id)},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert _objective_ids(body) == {
        str(f.visible_objective_id),
        str(f.hidden_until_active_objective_id),
    }


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
            quest_id=f.quest_id,
            grantee_access_group_id=access_group_id,
            effect="deny",
        )

    with client_factory(f.privileged_user_id) as client:
        response = client.get(
            _quest_url(f),
            params={"character_id": str(f.character_id), "party_id": str(f.party_id)},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert _objective_ids(body) == {
        str(f.visible_objective_id),
        str(f.hidden_until_active_objective_id),
    }


def test_a_targeted_canon_edit_allow_reveals_every_objective_without_a_role(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """f.base_view_user_id holds campaign.view only — no role-derived
    canon.edit, no character.view_knowledge relationship. A canon.edit
    allow targeted at f.quest_id unlocks every objective regardless of
    visibility_policy without supplying (or being authorized for) any party
    perspective at all — proving the targeted-allow path this correction
    pass preserves."""
    with postgres_engine.begin() as setup:
        make_resource_grant(
            setup,
            f.campaign_id,
            f.canon_edit_capability_id,
            quest_id=f.quest_id,
            grantee_campaign_membership_id=f.base_view_membership_id,
            effect="allow",
        )

    with client_factory(f.base_view_user_id) as client:
        response = client.get(_quest_url(f))
    assert response.status_code == 200, response.text
    body = response.json()
    assert _objective_ids(body) == {
        str(f.visible_objective_id),
        str(f.gm_only_objective_id),
        str(f.hidden_until_active_objective_id),
        str(f.hidden_until_discovered_objective_id),
    }


# ---------------------------------------------------------------------------
# Targeted campaign.view deny (correction pass: get_quest_endpoint only
# ever checked quest-scoped canon.edit — which decides include_hidden, not
# overall visibility — so a quest-targeted campaign.view deny was never
# consulted at all and had no effect on this route, distinct from every
# canon.edit-targeted test above.
# ---------------------------------------------------------------------------


def test_a_targeted_campaign_view_deny_returns_not_found(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """f.gm_user_id holds role-derived campaign.view *and* canon.edit — the
    pre-correction-pass bug never checked campaign.view against a
    quest_id target at all, so this deny had no effect and the GM saw the
    quest (with every objective, via the separate canon.edit check) exactly
    as if no grant existed."""
    with postgres_engine.begin() as setup:
        make_resource_grant(
            setup,
            f.campaign_id,
            f.view_capability_id,
            quest_id=f.quest_id,
            grantee_campaign_membership_id=f.gm_membership_id,
            effect="deny",
        )

    with client_factory(f.gm_user_id) as client:
        response = client.get(_quest_url(f))
    assert response.status_code == 404


def test_the_campaign_view_deny_does_not_affect_a_different_member(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with postgres_engine.begin() as setup:
        make_resource_grant(
            setup,
            f.campaign_id,
            f.view_capability_id,
            quest_id=f.quest_id,
            grantee_campaign_membership_id=f.gm_membership_id,
            effect="deny",
        )

    with client_factory(f.player_user_id) as client:
        response = client.get(_quest_url(f))
    assert response.status_code == 200, response.text
    assert response.json()["quest_id"] == str(f.quest_id)


def test_an_unrelated_campaign_view_deny_does_not_hide_a_different_quest(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """The deny's own database-enforced same-world scope
    (`security.enforce_resource_grant_scope()`) requires a second, real
    same-world quest here rather than reusing f.other_world_quest_id."""
    with postgres_engine.begin() as setup:
        unrelated_quest_id = make_quest(setup, f.world_id, name="An Unrelated Quest")
        make_resource_grant(
            setup,
            f.campaign_id,
            f.view_capability_id,
            quest_id=unrelated_quest_id,
            grantee_campaign_membership_id=f.gm_membership_id,
            effect="deny",
        )

    with client_factory(f.gm_user_id) as client:
        response = client.get(_quest_url(f))
    assert response.status_code == 200, response.text
    assert response.json()["quest_id"] == str(f.quest_id)


# ---------------------------------------------------------------------------
# Party-scoped-over-campaign-wide status fallback
# ---------------------------------------------------------------------------


def test_without_a_party_perspective_the_campaign_wide_status_applies(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.get(_quest_url(f))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status_code"] == "active"
    visible = next(
        o
        for stage in body["stages"]
        for o in stage["objectives"]
        if o["quest_objective_id"] == str(f.visible_objective_id)
    )
    assert visible["status_code"] == "active"


def test_with_an_authorized_party_perspective_its_own_status_takes_precedence(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.player_user_id) as client:
        response = client.get(
            _quest_url(f),
            params={"character_id": str(f.character_id), "party_id": str(f.party_id)},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status_code"] == "completed"
    visible = next(
        o
        for stage in body["stages"]
        for o in stage["objectives"]
        if o["quest_objective_id"] == str(f.visible_objective_id)
    )
    assert visible["status_code"] == "completed"


# ---------------------------------------------------------------------------
# Cross-world ownership and existence
# ---------------------------------------------------------------------------


def test_a_quest_in_a_different_world_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.get(_quest_url(f, f.other_world_quest_id))
    assert response.status_code == 404


def test_a_nonexistent_quest_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.get(_quest_url(f, uuid.uuid4()))
    assert response.status_code == 404
