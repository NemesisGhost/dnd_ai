"""Regression coverage for the Phase 13D cross-campaign quest-detail
disclosure (`GET /campaigns/{campaign_a}/quests/{campaign_b_quest}` used to
return Campaign B's quest name/stages/objectives while inside Campaign A).

The defect: `dnd_ai.queries.quest.get_quest_view` validated only that the
quest existed and shared the caller's *world* — but quests are world canon
with no `campaign_id`, and one world hosts many campaign timelines, so
"same world" is not "exposed to this campaign." A quest tracked only on
another campaign's timeline (`campaign.quest_state`) leaked through detail
even though it never appeared in the campaign's own quest list.

The fix: `get_quest_endpoint` now calls `get_quest_view(...,
require_campaign_tracking=True, include_all_parties=<baseline canon.edit>)`
— the *same* shared `_QUEST_STATE_MATCHES_AUDIENCE` timeline/party audience
rule `list_quests_endpoint` feeds `list_campaign_quests`. List and detail
can no longer disagree on which quests an audience may see.

Fixture shape (deliberately the exact shape that exposed the defect):
one world, timelines A and B, Campaign A on A / Campaign B on B, plus a
second world for the cross-world case. Every rejection path is asserted to
return the identical fixed non-disclosing 404 body, with no quest, stage,
or objective detail in it.
"""

import uuid
from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, text

from dnd_ai.api.app import create_app
from dnd_ai.api.auth import get_authenticated_user_id
from dnd_ai.api.deps import get_engine
from dnd_ai.queries.quest import QuestNotFoundError, get_quest_view, list_campaign_quests
from tests.factories import (
    lookup_id,
    make_campaign,
    make_campaign_membership,
    make_campaign_party,
    make_character,
    make_character_relationship_type,
    make_membership_character_relationship,
    make_membership_role,
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
        self.timeline_a_id = make_timeline(connection, self.world_id, is_primary=True)
        self.timeline_b_id = make_timeline(connection, self.world_id, name="Timeline B")
        self.world_time_id = make_world_time(connection, self.world_id, 100)

        self.campaign_a_id = make_campaign(
            connection, self.timeline_a_id, lifecycle_status_code="pending"
        )
        self.campaign_b_id = make_campaign(
            connection, self.timeline_b_id, lifecycle_status_code="pending"
        )

        # Parties associated with Campaign A.
        self.party_1_id = make_party(connection, self.world_id, name="Party One")
        self.party_2_id = make_party(connection, self.world_id, name="Party Two")
        make_campaign_party(connection, self.campaign_a_id, self.party_1_id)
        make_campaign_party(connection, self.campaign_a_id, self.party_2_id)

        # A quest tracked campaign-wide on Timeline A — the "normal" quest.
        self.quest_a_id = make_quest(connection, self.world_id, name="Guard the Ford")
        self.stage_a_id = make_quest_stage(connection, self.quest_a_id, name="Hold the line")
        self.visible_objective_id = make_quest_objective(
            connection, self.stage_a_id, name="Post the watch", visibility_policy="visible"
        )
        self.gm_only_objective_id = make_quest_objective(
            connection, self.stage_a_id, name="Bribe the ferryman", visibility_policy="gm_only"
        )
        make_quest_state(connection, self.timeline_a_id, self.quest_a_id, status_code="active")

        # A quest tracked campaign-wide on Timeline B ONLY — Campaign B's
        # quest, same world as Campaign A. This is the disclosure vector.
        self.quest_b_id = make_quest(connection, self.world_id, name="Chart the Marshes")
        self.stage_b_id = make_quest_stage(connection, self.quest_b_id, name="Sound the shallows")
        make_quest_objective(connection, self.stage_b_id, name="Map the causeway")
        make_quest_state(connection, self.timeline_b_id, self.quest_b_id, status_code="active")

        # A world quest with no campaign.quest_state row anywhere.
        self.quest_untracked_id = make_quest(connection, self.world_id, name="Unused Hook")
        untracked_stage = make_quest_stage(connection, self.quest_untracked_id, name="Never begun")
        make_quest_objective(connection, untracked_stage, name="Do the thing")

        # A quest tracked on Timeline A ONLY through Party One's own row
        # (no campaign-wide row).
        self.quest_party_1_id = make_quest(connection, self.world_id, name="Party One's Oath")
        p1_stage = make_quest_stage(connection, self.quest_party_1_id, name="Swear it")
        make_quest_objective(connection, p1_stage, name="Speak the words")
        make_quest_state(
            connection,
            self.timeline_a_id,
            self.quest_party_1_id,
            party_id=self.party_1_id,
            status_code="active",
        )

        # A quest tracked on Timeline A ONLY through Party Two's own row.
        self.quest_party_2_id = make_quest(connection, self.world_id, name="Party Two's Secret")
        p2_stage = make_quest_stage(connection, self.quest_party_2_id, name="Keep it")
        make_quest_objective(connection, p2_stage, name="Tell no one")
        make_quest_state(
            connection,
            self.timeline_a_id,
            self.quest_party_2_id,
            party_id=self.party_2_id,
            status_code="active",
        )

        # A second, unrelated world — its quest proves the cross-world path.
        self.other_world_id = make_world(connection, slug=f"{slug}-other")
        self.other_world_quest_id = make_quest(
            connection, self.other_world_id, name="Foreign Quest"
        )

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

        # Campaign A GM: campaign.view + canon.edit (baseline, no target).
        self.gm_a_user_id = make_user(connection, "Scope GM A")
        gm_a_membership_id = make_campaign_membership(
            connection, self.campaign_a_id, self.gm_a_user_id
        )
        self.gm_a_membership_id = gm_a_membership_id
        gm_a_role_id = make_role(
            connection, campaign_id=self.campaign_a_id, code=f"gm_a_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, gm_a_role_id, view_capability_id)
        make_role_capability(connection, gm_a_role_id, canon_edit_id)
        make_membership_role(connection, gm_a_membership_id, gm_a_role_id)

        # Campaign A player: campaign.view only, plus an authorized
        # character/Party One perspective.
        self.player_a_user_id = make_user(connection, "Scope Player A")
        player_a_membership_id = make_campaign_membership(
            connection, self.campaign_a_id, self.player_a_user_id
        )
        player_a_role_id = make_role(
            connection, campaign_id=self.campaign_a_id, code=f"player_a_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, player_a_role_id, view_capability_id)
        make_membership_role(connection, player_a_membership_id, player_a_role_id)

        self.character_id = make_character(connection, self.world_id, name="Bran")
        make_party_membership(
            connection, self.timeline_a_id, self.party_1_id, self.character_id, self.world_time_id
        )
        self.relationship_type_id = make_character_relationship_type(connection)
        make_relationship_type_capability(
            connection, self.relationship_type_id, view_knowledge_capability_id
        )
        make_membership_character_relationship(
            connection,
            player_a_membership_id,
            self.character_id,
            self.relationship_type_id,
            timeline_id=self.timeline_a_id,
        )

        # Campaign B GM: campaign.view + canon.edit on Campaign B.
        self.gm_b_user_id = make_user(connection, "Scope GM B")
        gm_b_membership_id = make_campaign_membership(
            connection, self.campaign_b_id, self.gm_b_user_id
        )
        gm_b_role_id = make_role(
            connection, campaign_id=self.campaign_b_id, code=f"gm_b_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, gm_b_role_id, view_capability_id)
        make_role_capability(connection, gm_b_role_id, canon_edit_id)
        make_membership_role(connection, gm_b_membership_id, gm_b_role_id)

        # Never a member of anything.
        self.outsider_user_id = make_user(connection, "Scope Outsider")


@pytest.fixture
def f(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as connection:
        fixture = Fixture(connection, f"quest-scope-{uuid.uuid4().hex[:8]}")
    yield fixture
    with postgres_engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
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
            for tbl in (
                "security.membership_roles",
                "security.role_capabilities",
            ):
                cleanup.execute(
                    text(f"""
                        DELETE FROM {tbl} WHERE role_id IN (
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
                    fixture.gm_a_user_id,
                    fixture.player_a_user_id,
                    fixture.gm_b_user_id,
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


def _detail_url(campaign_id: uuid.UUID, quest_id: uuid.UUID) -> str:
    return f"/campaigns/{campaign_id}/quests/{quest_id}"


# ---------------------------------------------------------------------------
# API route — the endpoint the portal actually calls
# ---------------------------------------------------------------------------


def test_a_tracked_quest_returns_normally(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_a_user_id) as client:
        response = client.get(_detail_url(f.campaign_a_id, f.quest_a_id))
    assert response.status_code == 200, response.text
    assert response.json()["quest_id"] == str(f.quest_a_id)
    assert response.json()["name"] == "Guard the Ford"


def test_campaign_b_quest_is_unavailable_through_campaign_a_same_world(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    """The exact defect shape: one world, two timelines, one campaign per
    timeline, Campaign B's quest state only on Timeline B, requested
    through Campaign A."""
    with client_factory(f.gm_a_user_id) as client:
        response = client.get(_detail_url(f.campaign_a_id, f.quest_b_id))
    assert response.status_code == 404


def test_campaign_b_quest_still_returns_normally_under_campaign_b(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_b_user_id) as client:
        response = client.get(_detail_url(f.campaign_b_id, f.quest_b_id))
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "Chart the Marshes"


def test_a_cross_world_quest_is_unavailable(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_a_user_id) as client:
        response = client.get(_detail_url(f.campaign_a_id, f.other_world_quest_id))
    assert response.status_code == 404


def test_an_untracked_world_quest_is_unavailable(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_a_user_id) as client:
        response = client.get(_detail_url(f.campaign_a_id, f.quest_untracked_id))
    assert response.status_code == 404


def test_a_campaign_wide_row_makes_the_quest_visible_to_a_plain_viewer(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.player_a_user_id) as client:
        response = client.get(_detail_url(f.campaign_a_id, f.quest_a_id))
    assert response.status_code == 200, response.text
    assert response.json()["quest_id"] == str(f.quest_a_id)


def test_a_party_scoped_quest_is_visible_to_its_authorized_party_audience(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.player_a_user_id) as client:
        response = client.get(
            _detail_url(f.campaign_a_id, f.quest_party_1_id),
            params={"character_id": str(f.character_id), "party_id": str(f.party_1_id)},
        )
    assert response.status_code == 200, response.text
    assert response.json()["quest_id"] == str(f.quest_party_1_id)


def test_a_quest_tracked_only_for_another_party_is_unavailable_to_a_non_gm(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.player_a_user_id) as client:
        response = client.get(
            _detail_url(f.campaign_a_id, f.quest_party_2_id),
            params={"character_id": str(f.character_id), "party_id": str(f.party_1_id)},
        )
    assert response.status_code == 404


def test_a_gm_sees_a_party_tracked_quest_across_parties_on_the_same_timeline(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_a_user_id) as client:
        response = client.get(_detail_url(f.campaign_a_id, f.quest_party_2_id))
    assert response.status_code == 200, response.text
    assert response.json()["quest_id"] == str(f.quest_party_2_id)


def test_a_quest_specific_campaign_view_deny_remains_unavailable(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with postgres_engine.begin() as setup:
        make_resource_grant(
            setup,
            f.campaign_a_id,
            f.view_capability_id,
            quest_id=f.quest_a_id,
            grantee_campaign_membership_id=f.gm_a_membership_id,
            effect="deny",
        )
    with client_factory(f.gm_a_user_id) as client:
        response = client.get(_detail_url(f.campaign_a_id, f.quest_a_id))
    assert response.status_code == 404


def test_objective_visibility_filtering_is_unchanged_after_the_eligibility_check(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    """The gm_only objective is still returned to a GM and still withheld
    from a plain viewer — the top-level tracking gate does not disturb
    per-objective `visibility_policy` filtering."""
    with client_factory(f.gm_a_user_id) as gm_client:
        gm_body = gm_client.get(_detail_url(f.campaign_a_id, f.quest_a_id)).json()
    with client_factory(f.player_a_user_id) as player_client:
        player_body = player_client.get(_detail_url(f.campaign_a_id, f.quest_a_id)).json()

    def objective_ids(body: dict[str, object]) -> set[str]:
        return {
            o["quest_objective_id"]
            for stage in body["stages"]  # type: ignore[index]
            for o in stage["objectives"]
        }

    assert str(f.gm_only_objective_id) in objective_ids(gm_body)
    assert str(f.gm_only_objective_id) not in objective_ids(player_body)
    assert str(f.visible_objective_id) in objective_ids(player_body)


def test_every_rejected_request_has_the_same_non_disclosing_response(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """Nonexistent, cross-world, same-world/cross-timeline, unauthorized-
    party, and specifically-denied requests must be indistinguishable in
    the response body, and must not carry any quest/stage/objective
    detail."""
    with postgres_engine.begin() as setup:
        make_resource_grant(
            setup,
            f.campaign_a_id,
            f.view_capability_id,
            quest_id=f.quest_a_id,
            grantee_campaign_membership_id=f.gm_a_membership_id,
            effect="deny",
        )

    targets = [
        uuid.uuid4(),  # nonexistent
        f.other_world_quest_id,  # cross-world
        f.quest_b_id,  # same-world, other timeline
        f.quest_untracked_id,  # untracked
        f.quest_a_id,  # quest-specific campaign.view deny
    ]
    errors = []
    for quest_id in targets:
        with client_factory(f.gm_a_user_id) as client:
            response = client.get(_detail_url(f.campaign_a_id, quest_id))
        assert response.status_code == 404
        error = response.json()["error"]
        errors.append({"code": error["code"], "message": error["message"]})

    # Every rejection is the same fixed non-disclosing (code, message) —
    # the caller cannot tell which condition occurred.
    assert all(e == errors[0] for e in errors), errors
    assert errors[0]["code"] == "not_found"

    leaked = {
        "Guard the Ford",
        "Chart the Marshes",
        "Unused Hook",
        "Sound the shallows",
        "Hold the line",
        "Map the causeway",
        "Post the watch",
        "Bribe the ferryman",
        str(f.quest_b_id),
        str(f.timeline_b_id),
    }
    serialized = repr(errors[0])
    for term in leaked:
        assert term not in serialized, serialized


def test_the_list_and_detail_paths_agree_for_a_non_gm(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    """A quest excluded from an audience's list cannot be fetched directly
    by that audience, and every quest in the list is fetchable."""
    with client_factory(f.player_a_user_id) as client:
        listed = client.get(f"/campaigns/{f.campaign_a_id}/quests")
        assert listed.status_code == 200, listed.text
        listed_ids = {item["quest_id"] for item in listed.json()}

        # The non-GM sees the campaign-wide quest, not the party-2 or
        # cross-timeline ones.
        assert str(f.quest_a_id) in listed_ids
        assert str(f.quest_b_id) not in listed_ids
        assert str(f.quest_party_2_id) not in listed_ids

        for quest_id in (f.quest_b_id, f.quest_party_2_id, f.quest_untracked_id):
            assert client.get(_detail_url(f.campaign_a_id, quest_id)).status_code == 404
        for quest_id_str in listed_ids:
            assert (
                client.get(_detail_url(f.campaign_a_id, uuid.UUID(quest_id_str))).status_code == 200
            )


def test_a_non_member_still_gets_not_found(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.outsider_user_id) as client:
        response = client.get(_detail_url(f.campaign_a_id, f.quest_a_id))
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Query layer — get_quest_view directly, real PostgreSQL (no mocks)
# ---------------------------------------------------------------------------


def test_query_rejects_a_quest_tracked_only_on_another_timeline(
    postgres_engine: Engine, f: Fixture
) -> None:
    with postgres_engine.connect() as connection, pytest.raises(QuestNotFoundError):
        get_quest_view(
            connection,
            quest_id=f.quest_b_id,
            timeline_id=f.timeline_a_id,
            expected_world_id=f.world_id,
            party_id=None,
            include_hidden=True,
            require_campaign_tracking=True,
            include_all_parties=True,
        )


def test_query_returns_a_quest_tracked_on_the_requested_timeline(
    postgres_engine: Engine, f: Fixture
) -> None:
    with postgres_engine.connect() as connection:
        view = get_quest_view(
            connection,
            quest_id=f.quest_b_id,
            timeline_id=f.timeline_b_id,
            expected_world_id=f.world_id,
            party_id=None,
            include_hidden=True,
            require_campaign_tracking=True,
            include_all_parties=True,
        )
    assert view.name == "Chart the Marshes"
    assert view.status_code == "active"


def test_query_non_gm_audience_excludes_another_partys_only_tracking(
    postgres_engine: Engine, f: Fixture
) -> None:
    with postgres_engine.connect() as connection:
        # Party One's own perspective cannot reach Party Two's quest.
        with pytest.raises(QuestNotFoundError):
            get_quest_view(
                connection,
                quest_id=f.quest_party_2_id,
                timeline_id=f.timeline_a_id,
                expected_world_id=f.world_id,
                party_id=f.party_1_id,
                include_hidden=False,
                require_campaign_tracking=True,
                include_all_parties=False,
            )
        # Its own party's perspective can.
        view = get_quest_view(
            connection,
            quest_id=f.quest_party_1_id,
            timeline_id=f.timeline_a_id,
            expected_world_id=f.world_id,
            party_id=f.party_1_id,
            include_hidden=False,
            require_campaign_tracking=True,
            include_all_parties=False,
        )
    assert view.quest_id == f.quest_party_1_id


def test_query_list_and_detail_use_the_same_eligibility_rule(
    postgres_engine: Engine, f: Fixture
) -> None:
    """Whatever `list_campaign_quests` includes for an audience,
    `get_quest_view(require_campaign_tracking=True)` accepts for that same
    audience — and vice versa."""
    with postgres_engine.connect() as connection:
        for include_all_parties, party_id in ((True, None), (False, f.party_1_id)):
            listed = {
                item.quest_id
                for item in list_campaign_quests(
                    connection,
                    timeline_id=f.timeline_a_id,
                    party_id=party_id,
                    include_all_parties=include_all_parties,
                )
            }
            for quest_id in (
                f.quest_a_id,
                f.quest_b_id,
                f.quest_untracked_id,
                f.quest_party_1_id,
                f.quest_party_2_id,
            ):
                try:
                    get_quest_view(
                        connection,
                        quest_id=quest_id,
                        timeline_id=f.timeline_a_id,
                        expected_world_id=f.world_id,
                        party_id=party_id,
                        include_hidden=True,
                        require_campaign_tracking=True,
                        include_all_parties=include_all_parties,
                    )
                    fetchable = True
                except QuestNotFoundError:
                    fetchable = False
                assert fetchable == (quest_id in listed), (quest_id, include_all_parties)
