"""Tests for `dnd_ai.api.knowledge` — Phase 10 workstream 18's query
endpoint over `dnd_ai.queries.knowledge.get_knowledge_view` (docs/PLAN.md
Phase 10 "query services for the effective dungeon, character, quest,
relationship, inventory, encounter, and knowledge state required by the
vertical slice"). Mirrors `tests/database/test_api_dungeon.py`'s shape:
`get_authenticated_user_id` is overridden directly, since these tests
exercise campaign-capability enforcement and the ground-truth/party-belief
split, not OIDC token verification. Party-perspective authorization itself
(`dnd_ai.api.access.resolve_party_perspective`) is already exhaustively
covered by `tests/database/test_api_dungeon.py`; this file proves only
that the knowledge route wires it correctly, not every edge case again.

Covers: access control (non-member 404, capless-member 403), that a GM
sees ground truth (`canonical_statement`/`truth_status_code`/`sensitivity`)
regardless of any party's belief, that an authorized party sees its own
belief (falling back to the canonical statement when no distortion is
recorded, and its own recorded interpretation when one is), that an
omitted perspective and a party with no belief record about the item both
resolve to the same fixed 404 a nonexistent item would, and cross-world/
nonexistent-item rejection.
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
    make_knowledge_item,
    make_membership_character_relationship,
    make_membership_role,
    make_party,
    make_party_knowledge,
    make_party_membership,
    make_relationship_type_capability,
    make_resource_grant,
    make_role,
    make_role_capability,
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
        self.other_campaign_id = make_campaign(
            connection, self.timeline_id, "Other Campaign", lifecycle_status_code="pending"
        )

        # An accurately-believed item: no interpretation recorded, so the
        # party's own belief statement falls back to the canonical text.
        self.accurate_item_id = make_knowledge_item(
            connection,
            self.world_id,
            statement="The idol is cursed.",
            truth_status_code="true",
        )
        # A falsely-believed item: ground truth is false, but the party's
        # own recorded interpretation is what a non-GM should see instead.
        self.distorted_item_id = make_knowledge_item(
            connection,
            self.world_id,
            statement="The idol grants wishes.",
            truth_status_code="false",
        )
        # A real item the party has no belief record for at all.
        self.undiscovered_item_id = make_knowledge_item(
            connection, self.world_id, statement="A hidden third truth."
        )

        self.party_id = make_party(connection, self.world_id, name="The Company")
        make_campaign_party(connection, self.campaign_id, self.party_id)
        make_party_knowledge(
            connection,
            self.timeline_id,
            self.party_id,
            self.accurate_item_id,
            awareness_level="aware",
            confidence=80,
        )
        make_party_knowledge(
            connection,
            self.timeline_id,
            self.party_id,
            self.distorted_item_id,
            awareness_level="aware",
            confidence=60,
            interpretation="Everyone says it's cursed, but I've heard it grants wishes.",
        )

        # Associated only with the *other* campaign — same world/timeline,
        # so campaign.enforce_campaign_party_world() alone lets it through.
        self.foreign_party_id = make_party(connection, self.world_id, name="Foreign Party")
        make_campaign_party(connection, self.other_campaign_id, self.foreign_party_id)

        # A second, unrelated world — its knowledge item proves the
        # cross-world ownership check.
        self.other_world_id = make_world(connection, slug=f"{slug}-other-world")
        self.other_world_item_id = make_knowledge_item(connection, self.other_world_id)

        view_capability_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "campaign.view"
        )
        canon_edit_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "canon.edit"
        )
        view_knowledge_capability_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "character.view_knowledge"
        )

        self.gm_user_id = make_user(connection, "Knowledge Query GM")
        gm_membership_id = make_campaign_membership(connection, self.campaign_id, self.gm_user_id)
        gm_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"gm_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, gm_role_id, view_capability_id)
        make_role_capability(connection, gm_role_id, canon_edit_id)
        make_membership_role(connection, gm_membership_id, gm_role_id)

        self.player_user_id = make_user(connection, "Knowledge Query Player")
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
        # targeted canon.edit deny for a specific knowledge item still
        # leaves an authorized party perspective available — isolating the
        # include_ground_truth regression from party-perspective
        # authorization itself.
        self.privileged_user_id = make_user(connection, "Knowledge Query Privileged Member")
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
        # unlock ground truth without either.
        self.base_view_user_id = make_user(connection, "Knowledge Query Base Viewer")
        base_view_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.base_view_user_id
        )
        self.base_view_membership_id = base_view_membership_id
        make_membership_role(connection, base_view_membership_id, player_role_id)

        # A member with no role/capability at all — proves ForbiddenError,
        # distinct from a non-member's NotFoundError.
        self.capless_user_id = make_user(connection, "Knowledge Query Capless Member")
        make_campaign_membership(connection, self.campaign_id, self.capless_user_id)

        # Never given a membership at all.
        self.outsider_user_id = make_user(connection, "Knowledge Query Outsider")


@pytest.fixture
def f(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as connection:
        fixture = Fixture(connection, f"knowledge-query-{uuid.uuid4().hex[:8]}")
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
                    DELETE FROM campaign.party_knowledge WHERE timeline_id IN (
                        SELECT timeline_id FROM campaign.timelines WHERE world_id = :w
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
        app.dependency_overrides[get_authenticated_user_id] = lambda: user_id
        return TestClient(app, raise_server_exceptions=False)

    return _make


def _knowledge_url(f: Fixture, knowledge_item_id: uuid.UUID | None = None) -> str:
    return f"/campaigns/{f.campaign_id}/knowledge/{knowledge_item_id or f.accurate_item_id}"


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


def test_a_non_member_gets_not_found(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.outsider_user_id) as client:
        response = client.get(_knowledge_url(f))
    assert response.status_code == 404


def test_a_member_without_campaign_view_gets_forbidden(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.capless_user_id) as client:
        response = client.get(_knowledge_url(f))
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Ground truth vs. party belief
# ---------------------------------------------------------------------------


def test_a_gm_sees_ground_truth_for_an_accurately_believed_item(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.get(_knowledge_url(f))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["statement"] == "The idol is cursed."
    assert body["truth_status_code"] == "true"
    assert body["sensitivity"] is not None
    assert body["awareness_level"] is None
    assert body["confidence"] is None


def test_a_gm_sees_ground_truth_for_a_falsely_believed_item(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.get(_knowledge_url(f, f.distorted_item_id))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["statement"] == "The idol grants wishes."
    assert body["truth_status_code"] == "false"


def test_an_authorized_party_sees_its_own_belief_falling_back_to_canonical_text(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.player_user_id) as client:
        response = client.get(
            _knowledge_url(f),
            params={"character_id": str(f.character_id), "party_id": str(f.party_id)},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["statement"] == "The idol is cursed."
    assert body["awareness_level"] == "aware"
    assert body["confidence"] == 80
    assert body["truth_status_code"] is None
    assert body["sensitivity"] is None


def test_an_authorized_party_sees_its_own_distorted_interpretation_not_ground_truth(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.player_user_id) as client:
        response = client.get(
            _knowledge_url(f, f.distorted_item_id),
            params={"character_id": str(f.character_id), "party_id": str(f.party_id)},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["statement"] == ("Everyone says it's cursed, but I've heard it grants wishes.")
    assert body["statement"] != "The idol grants wishes."


# ---------------------------------------------------------------------------
# Resource-grant overrides for the include_ground_truth (canon.edit) check
#
# dnd_ai.api.knowledge.get_knowledge_endpoint used to check canon.edit with
# no knowledge_item_id target, so an item-scoped security.resource_grants
# deny never reached it and a role-derived GM always saw ground truth.
# These tests prove the fixed, knowledge_item_id-scoped check honors a
# targeted deny/allow, and that a caller denied ground truth for one item
# still falls through cleanly to an authorized party perspective.
# ---------------------------------------------------------------------------


def test_a_targeted_deny_for_canon_edit_falls_through_to_party_belief(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """f.privileged_user_id holds role-derived canon.edit *and* an
    independent character.view_knowledge relationship for f.character_id —
    the pre-correction-pass bug ignored a deny targeting this exact
    knowledge item and always returned ground truth anyway. The
    view_knowledge relationship keeps resolve_party_perspective satisfied
    on its own merits, isolating this regression to include_ground_truth
    specifically: with ground truth denied, the caller sees the party's own
    distorted interpretation instead."""
    with postgres_engine.begin() as setup:
        make_resource_grant(
            setup,
            f.campaign_id,
            f.canon_edit_capability_id,
            knowledge_item_id=f.distorted_item_id,
            grantee_campaign_membership_id=f.privileged_membership_id,
            effect="deny",
        )

    with client_factory(f.privileged_user_id) as client:
        response = client.get(
            _knowledge_url(f, f.distorted_item_id),
            params={"character_id": str(f.character_id), "party_id": str(f.party_id)},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["statement"] == ("Everyone says it's cursed, but I've heard it grants wishes.")
    assert body["statement"] != "The idol grants wishes."
    assert body["truth_status_code"] is None
    assert body["sensitivity"] is None


def test_a_targeted_deny_via_access_group_falls_through_to_party_belief(
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
            knowledge_item_id=f.distorted_item_id,
            grantee_access_group_id=access_group_id,
            effect="deny",
        )

    with client_factory(f.privileged_user_id) as client:
        response = client.get(
            _knowledge_url(f, f.distorted_item_id),
            params={"character_id": str(f.character_id), "party_id": str(f.party_id)},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["statement"] == ("Everyone says it's cursed, but I've heard it grants wishes.")
    assert body["truth_status_code"] is None


def test_a_targeted_canon_edit_allow_reveals_ground_truth_without_a_role(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """f.base_view_user_id holds campaign.view only — no role-derived
    canon.edit, no character.view_knowledge relationship. A canon.edit
    allow targeted at f.accurate_item_id unlocks ground truth without
    supplying (or being authorized for) any party perspective at all —
    proving the targeted-allow path this correction pass preserves."""
    with postgres_engine.begin() as setup:
        make_resource_grant(
            setup,
            f.campaign_id,
            f.canon_edit_capability_id,
            knowledge_item_id=f.accurate_item_id,
            grantee_campaign_membership_id=f.base_view_membership_id,
            effect="allow",
        )

    with client_factory(f.base_view_user_id) as client:
        response = client.get(_knowledge_url(f, f.accurate_item_id))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["statement"] == "The idol is cursed."
    assert body["truth_status_code"] == "true"
    assert body["sensitivity"] is not None


# ---------------------------------------------------------------------------
# Non-disclosure: omitted perspective and no-belief-record cases
# ---------------------------------------------------------------------------


def test_an_omitted_perspective_is_rejected_not_downgraded(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.player_user_id) as client:
        response = client.get(_knowledge_url(f))
    assert response.status_code == 404


def test_an_authorized_party_with_no_belief_record_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.player_user_id) as client:
        response = client.get(
            _knowledge_url(f, f.undiscovered_item_id),
            params={"character_id": str(f.character_id), "party_id": str(f.party_id)},
        )
    assert response.status_code == 404


def test_an_unauthorized_party_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.player_user_id) as client:
        response = client.get(
            _knowledge_url(f),
            params={"character_id": str(f.character_id), "party_id": str(f.foreign_party_id)},
        )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Cross-world ownership and existence
# ---------------------------------------------------------------------------


def test_a_knowledge_item_in_a_different_world_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.get(_knowledge_url(f, f.other_world_item_id))
    assert response.status_code == 404


def test_a_nonexistent_knowledge_item_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.get(_knowledge_url(f, uuid.uuid4()))
    assert response.status_code == 404
