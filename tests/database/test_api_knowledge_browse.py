"""Tests for `dnd_ai.api.knowledge`'s new Phase 13D list endpoint
(`GET /campaigns/{id}/knowledge`) — the audience-filtered discovery/list
side of the Knowledge screen (docs/UI_DESIGN.md §5.6).

Covers, per docs/PHASE13D_BACKEND_READINESS.md §9: known fact; false party
belief (interpretation, not canonical truth); recently-discovered ordering
and pagination; character-private knowledge and its exclusion from another
character's perspective; party-shared and its exclusion of another party's
knowledge; public lore; provenance on visible records; GM truth vs player
belief; targeted deny; no / valid / mismatched perspective; empty list;
search and type/view filters; list/detail agreement; revocation reflected
on the next request; no leaked truth-status/sensitivity/ids.

The existing `test_api_knowledge.py` covers the single-item detail route's
own GM/party split exhaustively; this file adds only the list behavior and
the character-private detail extension.
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
    make_campaign_party,
    make_character,
    make_character_relationship_type,
    make_entity_knowledge,
    make_event,
    make_interaction,
    make_knowledge_item,
    make_location,
    make_membership_character_relationship,
    make_membership_role,
    make_organization,
    make_party,
    make_party_discovery,
    make_party_knowledge,
    make_party_membership,
    make_public_knowledge,
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
        self.wt_early = make_world_time(connection, self.world_id, 100)
        self.wt_late = make_world_time(connection, self.world_id, 900)
        self.campaign_id = make_campaign(
            connection, self.timeline_id, lifecycle_status_code="pending"
        )

        self.party_id = make_party(connection, self.world_id, name="The Company")
        make_campaign_party(connection, self.campaign_id, self.party_id)
        self.other_party_id = make_party(connection, self.world_id, name="The Rivals")
        make_campaign_party(connection, self.campaign_id, self.other_party_id)

        self.character_id = make_character(connection, self.world_id, name="Aria")
        make_party_membership(
            connection, self.timeline_id, self.party_id, self.character_id, self.wt_early
        )
        self.other_character_id = make_character(connection, self.world_id, name="Borin")

        # --- knowledge items --------------------------------------------
        self.fact_id = make_knowledge_item(
            connection,
            self.world_id,
            knowledge_type_code="fact",
            truth_status_code="true",
            statement="The bridge at Elmford is sound.",
        )
        self.rumor_id = make_knowledge_item(
            connection,
            self.world_id,
            knowledge_type_code="rumor",
            truth_status_code="false",
            statement="The mayor is secretly a doppelganger.",
        )
        self.private_id = make_knowledge_item(
            connection,
            self.world_id,
            knowledge_type_code="secret",
            truth_status_code="true",
            statement="Aria saw the seneschal take a bribe.",
        )
        self.public_id = make_knowledge_item(
            connection,
            self.world_id,
            knowledge_type_code="fact",
            truth_status_code="true",
            statement="The harvest festival is on the first of Highsun.",
        )
        self.other_party_only_id = make_knowledge_item(
            connection,
            self.world_id,
            knowledge_type_code="fact",
            truth_status_code="true",
            statement="The Rivals found the northern cache.",
        )

        # The Company's party knowledge: a true fact, and a false belief
        # (interpretation differs from canonical truth).
        make_party_knowledge(
            connection, self.timeline_id, self.party_id, self.fact_id, awareness_level="aware"
        )
        make_party_knowledge(
            connection,
            self.timeline_id,
            self.party_id,
            self.rumor_id,
            awareness_level="rumored",
            confidence=30,
            interpretation="Some say the mayor was replaced last winter.",
        )
        # Another party's knowledge — must never appear in The Company's view.
        make_party_knowledge(
            connection, self.timeline_id, self.other_party_id, self.other_party_only_id
        )

        # Aria's individual (character-private) belief.
        make_entity_knowledge(
            connection,
            self.timeline_id,
            self.private_id,
            self.character_id,
            interpretation="I am certain it was the seneschal.",
            learned_at_world_time_id=self.wt_late,
        )
        # Borin's individual belief — must not appear in Aria's perspective.
        make_entity_knowledge(
            connection,
            self.timeline_id,
            self.rumor_id,
            self.other_character_id,
            interpretation="Borin's private notes.",
        )

        # Discoveries for the recently-discovered stream (early then late).
        self.discovery_early_id = make_party_discovery(
            connection,
            self.timeline_id,
            self.fact_id,
            party_id=self.party_id,
            discovered_at_world_time_id=self.wt_early,
        )
        self.discovery_late_id = make_party_discovery(
            connection,
            self.timeline_id,
            self.rumor_id,
            party_id=self.party_id,
            discovered_at_world_time_id=self.wt_late,
        )

        # Public lore at a location.
        self.location_id = make_location(connection, self.world_id, name="Elmford")
        make_public_knowledge(connection, self.timeline_id, self.public_id, self.location_id)

        # --- users / roles ---------------------------------------------
        self.view_capability_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "campaign.view"
        )
        canon_edit_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "canon.edit"
        )
        self.canon_edit_capability_id = canon_edit_id
        view_knowledge_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "character.view_knowledge"
        )

        self.gm_user_id = make_user(connection, "Knowledge GM")
        gm_membership_id = make_campaign_membership(connection, self.campaign_id, self.gm_user_id)
        self.gm_membership_id = gm_membership_id
        gm_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"gm_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, gm_role_id, self.view_capability_id)
        make_role_capability(connection, gm_role_id, canon_edit_id)
        make_membership_role(connection, gm_membership_id, gm_role_id)

        self.player_user_id = make_user(connection, "Knowledge Player")
        player_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.player_user_id
        )
        self.player_membership_id = player_membership_id
        player_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"player_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, player_role_id, self.view_capability_id)
        make_membership_role(connection, player_membership_id, player_role_id)

        self.relationship_type_id = make_character_relationship_type(connection)
        make_relationship_type_capability(connection, self.relationship_type_id, view_knowledge_id)
        make_membership_character_relationship(
            connection,
            player_membership_id,
            self.character_id,
            self.relationship_type_id,
            timeline_id=self.timeline_id,
        )

        self.outsider_user_id = make_user(connection, "Knowledge Outsider")


@pytest.fixture
def f(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as connection:
        fixture = Fixture(connection, f"knowledge-browse-{uuid.uuid4().hex[:8]}")
    yield fixture
    with postgres_engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        for stmt, param in [
            (
                "DELETE FROM security.membership_character_relationships "
                "WHERE campaign_membership_id IN (SELECT campaign_membership_id "
                "FROM security.campaign_memberships WHERE campaign_id = :c)",
                {"c": fixture.campaign_id},
            ),
            (
                "DELETE FROM security.membership_roles WHERE role_id IN "
                "(SELECT role_id FROM security.roles WHERE campaign_id = :c)",
                {"c": fixture.campaign_id},
            ),
            (
                "DELETE FROM security.role_capabilities WHERE role_id IN "
                "(SELECT role_id FROM security.roles WHERE campaign_id = :c)",
                {"c": fixture.campaign_id},
            ),
            ("DELETE FROM security.roles WHERE campaign_id = :c", {"c": fixture.campaign_id}),
            (
                "DELETE FROM security.resource_grants WHERE campaign_id = :c",
                {"c": fixture.campaign_id},
            ),
            (
                "DELETE FROM security.campaign_memberships WHERE campaign_id = :c",
                {"c": fixture.campaign_id},
            ),
            (
                "DELETE FROM campaign.party_knowledge WHERE timeline_id = :t",
                {"t": fixture.timeline_id},
            ),
            (
                "DELETE FROM knowledge.party_discoveries WHERE timeline_id = :t",
                {"t": fixture.timeline_id},
            ),
            (
                "DELETE FROM knowledge.entity_knowledge WHERE timeline_id = :t",
                {"t": fixture.timeline_id},
            ),
            (
                "DELETE FROM knowledge.public_knowledge WHERE timeline_id = :t",
                {"t": fixture.timeline_id},
            ),
            (
                "DELETE FROM campaign.party_memberships WHERE timeline_id = :t",
                {"t": fixture.timeline_id},
            ),
            (
                "DELETE FROM campaign.campaign_parties WHERE campaign_id = :c",
                {"c": fixture.campaign_id},
            ),
            ("DELETE FROM campaign.campaigns WHERE campaign_id = :c", {"c": fixture.campaign_id}),
            ("DELETE FROM campaign.parties WHERE world_id = :w", {"w": fixture.world_id}),
            ("DELETE FROM campaign.timelines WHERE world_id = :w", {"w": fixture.world_id}),
            ("DELETE FROM core.entities WHERE world_id = :w", {"w": fixture.world_id}),
            ("DELETE FROM core.worlds WHERE world_id = :w", {"w": fixture.world_id}),
            (
                "DELETE FROM security.character_relationship_type_capabilities "
                "WHERE character_relationship_type_id = :rt",
                {"rt": fixture.relationship_type_id},
            ),
            (
                "DELETE FROM security.character_relationship_types "
                "WHERE character_relationship_type_id = :rt",
                {"rt": fixture.relationship_type_id},
            ),
            (
                "DELETE FROM security.users WHERE user_id = ANY(:u)",
                {"u": [fixture.gm_user_id, fixture.player_user_id, fixture.outsider_user_id]},
            ),
        ]:
            cleanup.execute(text(stmt), param)


@pytest.fixture
def client_factory(postgres_engine: Engine) -> Callable[[uuid.UUID], TestClient]:
    def _make(user_id: uuid.UUID) -> TestClient:
        from tests.factories import oidc_principal

        app = create_app()
        app.dependency_overrides[get_engine] = lambda: postgres_engine
        app.dependency_overrides[get_authenticated_user_id] = lambda: oidc_principal(user_id)
        return TestClient(app, raise_server_exceptions=False)

    return _make


def _url(f: Fixture) -> str:
    return f"/campaigns/{f.campaign_id}/knowledge"


def _perspective(f: Fixture) -> dict[str, str]:
    return {"character_id": str(f.character_id), "party_id": str(f.party_id)}


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


def test_non_member_gets_not_found(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.outsider_user_id) as client:
        assert client.get(_url(f)).status_code == 404


# ---------------------------------------------------------------------------
# Player perspective views
# ---------------------------------------------------------------------------


def test_known_view_returns_the_partys_settled_facts_not_rumors(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.player_user_id) as client:
        body = client.get(_url(f), params={"view": "known", **_perspective(f), "limit": 100}).json()
    ids = {item["knowledge_item_id"] for item in body["items"]}
    assert str(f.fact_id) in ids
    assert str(f.rumor_id) not in ids
    # No ground-truth metadata leaks to a player.
    for item in body["items"]:
        assert item["truth_status_code"] is None
        assert item["sensitivity"] is None


def test_rumors_view_shows_the_partys_interpretation_not_canonical_truth(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.player_user_id) as client:
        body = client.get(
            _url(f), params={"view": "rumors", **_perspective(f), "limit": 100}
        ).json()
    by_id = {item["knowledge_item_id"]: item for item in body["items"]}
    assert str(f.rumor_id) in by_id
    item = by_id[str(f.rumor_id)]
    assert item["statement"] == "Some say the mayor was replaced last winter."
    assert item["statement"] != "The mayor is secretly a doppelganger."
    assert item["truth_status_code"] is None  # never told it's "false"
    assert item["confidence"] == 30


def test_party_shared_is_the_union_of_known_and_rumors(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.player_user_id) as client:
        body = client.get(
            _url(f), params={"view": "party_shared", **_perspective(f), "limit": 100}
        ).json()
    ids = {item["knowledge_item_id"] for item in body["items"]}
    assert {str(f.fact_id), str(f.rumor_id)} <= ids
    assert str(f.other_party_only_id) not in ids  # another party's knowledge excluded


def test_character_private_shows_only_the_selected_characters_beliefs(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.player_user_id) as client:
        body = client.get(
            _url(f),
            params={"view": "character_private", "character_id": str(f.character_id), "limit": 100},
        ).json()
    ids = {item["knowledge_item_id"] for item in body["items"]}
    assert str(f.private_id) in ids
    # Borin's private belief about the rumor is not in Aria's perspective.
    by_id = {item["knowledge_item_id"]: item for item in body["items"]}
    assert (
        by_id.get(str(f.rumor_id)) is None
        or by_id[str(f.rumor_id)]["statement"] != "Borin's private notes."
    )


def test_public_view_needs_no_perspective(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.player_user_id) as client:
        body = client.get(_url(f), params={"view": "public", "limit": 100}).json()
    ids = {item["knowledge_item_id"] for item in body["items"]}
    assert str(f.public_id) in ids
    for item in body["items"]:
        assert item["truth_status_code"] is None  # non-public canonical fields withheld


def test_recent_view_is_newest_discovery_first_and_paginates(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.player_user_id) as client:
        page1 = client.get(_url(f), params={"view": "recent", **_perspective(f), "limit": 1}).json()
        assert [i["knowledge_item_id"] for i in page1["items"]] == [str(f.rumor_id)]
        assert page1["next_cursor"] is not None
        page2 = client.get(
            _url(f),
            params={
                "view": "recent",
                **_perspective(f),
                "limit": 1,
                "cursor": page1["next_cursor"],
            },
        ).json()
    assert [i["knowledge_item_id"] for i in page2["items"]] == [str(f.fact_id)]
    # Provenance is surfaced on the record.
    assert "discovery_world_time_id" in page1["items"][0]


# ---------------------------------------------------------------------------
# GM
# ---------------------------------------------------------------------------


def test_gm_known_view_is_canonical_with_ground_truth(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        body = client.get(_url(f), params={"view": "known", "limit": 100}).json()
    by_id = {item["knowledge_item_id"]: item for item in body["items"]}
    assert str(f.fact_id) in by_id
    assert by_id[str(f.fact_id)]["truth_status_code"] == "true"
    assert by_id[str(f.fact_id)]["statement"] == "The bridge at Elmford is sound."
    # The rumor-typed item is not in the GM's "known" (settled) canonical view.
    assert str(f.rumor_id) not in by_id


def test_gm_rumors_view_shows_canonical_statement_and_false_status(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        body = client.get(_url(f), params={"view": "rumors", "limit": 100}).json()
    by_id = {item["knowledge_item_id"]: item for item in body["items"]}
    assert by_id[str(f.rumor_id)]["statement"] == "The mayor is secretly a doppelganger."
    assert by_id[str(f.rumor_id)]["truth_status_code"] == "false"


# ---------------------------------------------------------------------------
# Perspective / empty / filters
# ---------------------------------------------------------------------------


def test_no_perspective_yields_an_empty_page_not_an_error(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.player_user_id) as client:
        body = client.get(_url(f), params={"view": "party_shared"}).json()
    assert body == {"items": [], "next_cursor": None}


def test_a_mismatched_perspective_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.player_user_id) as client:
        response = client.get(
            _url(f),
            params={
                "view": "party_shared",
                "character_id": str(f.character_id),
                "party_id": str(f.other_party_id),  # Aria is not in The Rivals
            },
        )
    assert response.status_code == 404


def test_search_and_type_filters(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.player_user_id) as client:
        by_q = client.get(
            _url(f), params={"view": "party_shared", **_perspective(f), "q": "bridge"}
        ).json()
        by_type = client.get(
            _url(f), params={"view": "party_shared", **_perspective(f), "type": "rumor"}
        ).json()
    assert {i["knowledge_item_id"] for i in by_q["items"]} == {str(f.fact_id)}
    assert {i["knowledge_item_id"] for i in by_type["items"]} == {str(f.rumor_id)}


def test_an_invalid_cursor_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.player_user_id) as client:
        response = client.get(_url(f), params={"view": "known", "cursor": "garbage"})
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Targeted deny + revocation
# ---------------------------------------------------------------------------


def test_a_targeted_deny_hides_an_item_from_the_list_and_detail(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with postgres_engine.begin() as setup:
        make_resource_grant(
            setup,
            f.campaign_id,
            f.view_capability_id,
            knowledge_item_id=f.fact_id,
            grantee_campaign_membership_id=f.player_membership_id,
            effect="deny",
        )
    with client_factory(f.player_user_id) as client:
        body = client.get(
            _url(f), params={"view": "party_shared", **_perspective(f), "limit": 100}
        ).json()
        detail = client.get(
            f"/campaigns/{f.campaign_id}/knowledge/{f.fact_id}", params=_perspective(f)
        )
    assert str(f.fact_id) not in {i["knowledge_item_id"] for i in body["items"]}
    assert detail.status_code == 404


def test_revoking_the_character_relationship_takes_effect_on_the_next_request(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.player_user_id) as client:
        before = client.get(
            _url(f), params={"view": "party_shared", **_perspective(f), "limit": 100}
        ).json()
        assert before["items"]
    with postgres_engine.begin() as revoke:
        revoke.execute(
            text(
                "UPDATE security.membership_character_relationships SET revoked_at = now() "
                "WHERE character_id = :c"
            ),
            {"c": f.character_id},
        )
    with client_factory(f.player_user_id) as client:
        after = client.get(_url(f), params={"view": "party_shared", **_perspective(f)})
    # The perspective can no longer be proven -> 404 (resolve_party_perspective).
    assert after.status_code == 404


# ---------------------------------------------------------------------------
# list/detail agreement
# ---------------------------------------------------------------------------


def test_every_listed_item_is_fetchable_via_detail_under_the_same_perspective(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.player_user_id) as client:
        for view, params in [
            ("party_shared", _perspective(f)),
            ("character_private", {"character_id": str(f.character_id)}),
            ("public", {}),
        ]:
            listed = client.get(_url(f), params={"view": view, **params, "limit": 100}).json()[
                "items"
            ]
            assert listed, view
            for item in listed:
                detail = client.get(
                    f"/campaigns/{f.campaign_id}/knowledge/{item['knowledge_item_id']}",
                    params=params,
                )
                assert detail.status_code == 200, (view, item, detail.text)


# ---------------------------------------------------------------------------
# `recent` belief-vs-canonical confidentiality (review High finding #1)
# ---------------------------------------------------------------------------


def test_recent_with_a_character_perspective_shows_the_private_interpretation(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """A player asking for `view=recent&character_id=...` (no party) must
    see each discovery's statement resolved through that character's own
    `entity_knowledge` belief — never the canonical statement the
    character-private views deliberately replace."""
    with postgres_engine.begin() as connection:
        make_party_discovery(
            connection,
            f.timeline_id,
            f.private_id,
            knower_entity_id=f.character_id,
            discovered_at_world_time_id=f.wt_late,
        )
    params = {"character_id": str(f.character_id)}
    with client_factory(f.player_user_id) as client:
        recent = client.get(_url(f), params={**params, "view": "recent", "limit": 100})
        detail = client.get(f"/campaigns/{f.campaign_id}/knowledge/{f.private_id}", params=params)
    assert recent.status_code == detail.status_code == 200
    item = next(i for i in recent.json()["items"] if i["knowledge_item_id"] == str(f.private_id))
    assert item["statement"] == "I am certain it was the seneschal."
    assert item["statement"] == detail.json()["statement"]
    assert item["truth_status_code"] is None
    assert item["sensitivity"] is None
    assert item["scope"] == "character"


def test_recent_canonical_only_search_term_does_not_surface_a_distorted_belief(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with postgres_engine.begin() as connection:
        make_party_discovery(
            connection,
            f.timeline_id,
            f.private_id,
            knower_entity_id=f.character_id,
            discovered_at_world_time_id=f.wt_late,
        )
    params = {"character_id": str(f.character_id), "view": "recent"}
    with client_factory(f.player_user_id) as client:
        # "bribe" appears only in the canonical statement.
        canonical_only = client.get(_url(f), params={**params, "q": "bribe"}).json()
        # "certain" appears only in the character's interpretation.
        belief_term = client.get(_url(f), params={**params, "q": "certain"}).json()
    assert str(f.private_id) not in {i["knowledge_item_id"] for i in canonical_only["items"]}
    assert str(f.private_id) in {i["knowledge_item_id"] for i in belief_term["items"]}


def test_recent_mixed_party_and_character_perspective_each_resolve_their_own_belief(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with postgres_engine.begin() as connection:
        make_party_discovery(
            connection,
            f.timeline_id,
            f.private_id,
            knower_entity_id=f.character_id,
            discovered_at_world_time_id=f.wt_late,
        )
    with client_factory(f.player_user_id) as client:
        body = client.get(
            _url(f), params={**_perspective(f), "view": "recent", "limit": 100}
        ).json()
    by_id = {i["knowledge_item_id"]: i for i in body["items"]}
    # party discovery -> party interpretation
    assert by_id[str(f.rumor_id)]["statement"] == "Some say the mayor was replaced last winter."
    assert by_id[str(f.rumor_id)]["scope"] == "party"
    # character discovery -> that character's own interpretation
    assert by_id[str(f.private_id)]["statement"] == "I am certain it was the seneschal."
    assert by_id[str(f.private_id)]["scope"] == "character"


def test_recent_omits_a_discovery_with_no_matching_belief_row(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """A discovery whose party has no belief record is not shown — `recent`
    stays in agreement with the detail route (which 404s) rather than
    falling back to the canonical statement."""
    with postgres_engine.begin() as connection:
        orphan_id = make_knowledge_item(
            connection,
            f.world_id,
            knowledge_type_code="secret",
            statement="The vault code is nine-one-seven.",
        )
        make_party_discovery(
            connection,
            f.timeline_id,
            orphan_id,
            party_id=f.party_id,
            discovered_at_world_time_id=f.wt_late,
        )
    with client_factory(f.player_user_id) as client:
        body = client.get(
            _url(f), params={**_perspective(f), "view": "recent", "limit": 100}
        ).json()
        detail = client.get(
            f"/campaigns/{f.campaign_id}/knowledge/{orphan_id}", params=_perspective(f)
        )
    assert str(orphan_id) not in {i["knowledge_item_id"] for i in body["items"]}
    assert detail.status_code == 404


def test_gm_recent_is_canonical_with_ground_truth(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        body = client.get(_url(f), params={"view": "recent", "limit": 100}).json()
    by_id = {i["knowledge_item_id"]: i for i in body["items"]}
    assert by_id[str(f.rumor_id)]["statement"] == "The mayor is secretly a doppelganger."
    assert by_id[str(f.rumor_id)]["truth_status_code"] == "false"
    assert by_id[str(f.rumor_id)]["scope"] == "canonical"


# ---------------------------------------------------------------------------
# Long-statement cursor (review Medium finding)
# ---------------------------------------------------------------------------


def test_a_generated_cursor_for_a_long_statement_is_accepted_on_the_next_page(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """Regression: a valid long canonical statement (well within the
    5000-char column limit) must not produce a `next_cursor` the decoder
    then rejects."""
    with postgres_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE knowledge.knowledge_items SET canonical_statement = :s "
                "WHERE knowledge_item_id = :id"
            ),
            {"s": "A" * 4000, "id": f.fact_id},
        )
    params: dict[str, object] = {"view": "party_shared", **_perspective(f), "limit": 1}
    with client_factory(f.player_user_id) as client:
        first = client.get(_url(f), params=params)
        assert first.status_code == 200
        cursor = first.json()["next_cursor"]
        assert cursor
        second = client.get(_url(f), params={**params, "cursor": cursor})
    assert second.status_code == 200
    # The two pages together cover both party-known items without overlap.
    first_ids = [i["knowledge_item_id"] for i in first.json()["items"]]
    second_ids = [i["knowledge_item_id"] for i in second.json()["items"]]
    assert set(first_ids).isdisjoint(second_ids)
    assert {str(f.fact_id), str(f.rumor_id)} <= set(first_ids) | set(second_ids)


def test_a_generated_cursor_for_a_non_bmp_statement_is_accepted_on_the_next_page(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """Regression (review f66441f, Medium #1): a statement whose 200-char
    sort prefix is supplementary-plane Unicode must still produce a
    `next_cursor` the decoder accepts — `ensure_ascii` escaping previously
    inflated an emoji prefix past the 2048-char decode bound."""
    with postgres_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE knowledge.knowledge_items SET canonical_statement = :s "
                "WHERE knowledge_item_id IN (:a, :b)"
            ),
            {"s": "\U0001f409" * 200, "a": f.fact_id, "b": f.rumor_id},
        )
        # Null the interpretations so the sort key is the (emoji) canonical
        # statement itself, not a short belief string.
        connection.execute(
            text(
                "UPDATE campaign.party_knowledge SET interpretation = NULL WHERE timeline_id = :t"
            ),
            {"t": f.timeline_id},
        )
    params: dict[str, object] = {"view": "party_shared", **_perspective(f), "limit": 1}
    with client_factory(f.player_user_id) as client:
        first = client.get(_url(f), params=params)
        assert first.status_code == 200
        cursor = first.json()["next_cursor"]
        assert cursor
        second = client.get(_url(f), params={**params, "cursor": cursor})
    assert second.status_code == 200, f"cursor len={len(cursor)}"
    first_ids = [i["knowledge_item_id"] for i in first.json()["items"]]
    second_ids = [i["knowledge_item_id"] for i in second.json()["items"]]
    assert set(first_ids).isdisjoint(second_ids)


def test_paginating_items_that_share_a_long_prefix_visits_each_exactly_once(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """When several statements share the full 200-char sort prefix, the
    unique `knowledge_item_id` tie-breaker must still walk every row once
    with no repeat or omission across `limit=1` pages."""
    shared = "Z" * 260
    ids = set()
    with postgres_engine.begin() as connection:
        for suffix in ("alpha", "bravo", "charlie", "delta"):
            item_id = make_knowledge_item(
                connection, f.world_id, knowledge_type_code="fact", statement=f"{shared}{suffix}"
            )
            make_party_knowledge(
                connection, f.timeline_id, f.party_id, item_id, awareness_level="aware"
            )
            ids.add(str(item_id))
    seen: list[str] = []
    cursor: str | None = None
    with client_factory(f.player_user_id) as client:
        for _ in range(20):  # generous upper bound; the loop breaks itself
            params: dict[str, object] = {"view": "known", **_perspective(f), "limit": 1}
            if cursor:
                params["cursor"] = cursor
            body = client.get(_url(f), params=params).json()
            seen.extend(i["knowledge_item_id"] for i in body["items"])
            cursor = body["next_cursor"]
            if cursor is None:
                break
    assert len(seen) == len(set(seen)), "a row was returned on more than one page"
    assert ids <= set(seen), "a shared-prefix row was skipped"


# ---------------------------------------------------------------------------
# recent-view belief metadata (review f66441f, Medium #2)
# ---------------------------------------------------------------------------


def test_recent_character_discovery_metadata_comes_from_the_characters_own_belief(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """A character-owned discovery of an item the party *also* believes must
    report the character's own awareness/confidence/willing_to_share, not
    the party's — consistent with its (character) statement and scope."""
    with postgres_engine.begin() as connection:
        make_entity_knowledge(
            connection,
            f.timeline_id,
            f.rumor_id,  # The Company already has a `rumored`/conf 30/share true belief here
            f.character_id,
            interpretation="My own private read on this.",
            awareness_level="aware",
            confidence=99,
            willing_to_share=False,
        )
        make_party_discovery(
            connection,
            f.timeline_id,
            f.rumor_id,
            knower_entity_id=f.character_id,
            discovered_at_world_time_id=f.wt_late,
        )
    with client_factory(f.player_user_id) as client:
        with_party = client.get(
            _url(f), params={"view": "recent", **_perspective(f), "limit": 100}
        ).json()
        without_party = client.get(
            _url(f),
            params={"view": "recent", "character_id": str(f.character_id), "limit": 100},
        ).json()

    def character_row(body: dict) -> dict:
        return next(
            i
            for i in body["items"]
            if i["knowledge_item_id"] == str(f.rumor_id) and i["scope"] == "character"
        )

    row = character_row(with_party)
    assert row["statement"] == "My own private read on this."
    assert (row["awareness_level"], row["confidence"], row["willing_to_share"]) == (
        "aware",
        99,
        False,
    )
    # Adding/removing the (authorized) party context does not change the
    # character discovery's own card.
    assert character_row(without_party) == row


def test_recent_party_discovery_null_confidence_is_not_borrowed_from_a_character_belief(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """The fixture's party belief about `fact_id` has `confidence = NULL`;
    a character belief with a non-null confidence must not fill it in on
    the party-owned discovery."""
    with postgres_engine.begin() as connection:
        make_entity_knowledge(
            connection,
            f.timeline_id,
            f.fact_id,
            f.character_id,
            confidence=77,
            awareness_level="suspected",
        )
    with client_factory(f.player_user_id) as client:
        body = client.get(
            _url(f), params={"view": "recent", **_perspective(f), "limit": 100}
        ).json()
    party_row = next(
        i
        for i in body["items"]
        if i["knowledge_item_id"] == str(f.fact_id) and i["scope"] == "party"
    )
    assert party_row["confidence"] is None
    assert party_row["awareness_level"] == "aware"  # the party's value, not "suspected"


def test_gm_recent_carries_no_party_belief_metadata(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        body = client.get(_url(f), params={"view": "recent", "limit": 100}).json()
    for item in body["items"]:
        assert item["scope"] == "canonical"
        assert item["awareness_level"] is None
        assert item["confidence"] is None
        assert item["willing_to_share"] is None


# ---------------------------------------------------------------------------
# Issue 3: malformed typed cursor values return 422, never 500
# ---------------------------------------------------------------------------


def _forged_knowledge_cursor(keyset: str, values: list[object]) -> str:
    import base64
    import json

    raw = json.dumps([1, keyset, values], separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


@pytest.mark.parametrize(
    ("view", "keyset", "values"),
    [
        ("known", "knowledge_by_statement", ["a bridge", "not-a-uuid"]),  # bad UUID
        (
            "known",
            "knowledge_by_statement",
            [123, "11111111-1111-1111-1111-111111111111"],
        ),  # int for str
        (
            "known",
            "knowledge_by_statement",
            [None, "11111111-1111-1111-1111-111111111111"],
        ),  # null name
        ("known", "knowledge_by_statement", ["a bridge"]),  # missing id
        ("known", "knowledge_by_statement", ["a bridge", "1111...", "extra"]),  # wrong shape
        (
            "recent",
            "knowledge_recent",
            ["not-an-int", "11111111-1111-1111-1111-111111111111"],
        ),  # str for int
        (
            "recent",
            "knowledge_recent",
            [True, "11111111-1111-1111-1111-111111111111"],
        ),  # bool for int
        # A cursor shaped for the *other* view/keyset:
        ("recent", "knowledge_by_statement", ["a bridge", "11111111-1111-1111-1111-111111111111"]),
        ("known", "knowledge_recent", [5, "11111111-1111-1111-1111-111111111111"]),
    ],
)
def test_a_wellformed_cursor_with_bad_values_is_422_not_500(
    client_factory: Callable[[uuid.UUID], TestClient],
    f: Fixture,
    view: str,
    keyset: str,
    values: list[object],
) -> None:
    with client_factory(f.player_user_id) as client:
        response = client.get(
            _url(f),
            params={
                "view": view,
                **_perspective(f),
                "cursor": _forged_knowledge_cursor(keyset, values),
            },
        )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "invalid_cursor"


def test_a_valid_recent_cursor_still_paginates(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.player_user_id) as client:
        page1 = client.get(_url(f), params={"view": "recent", **_perspective(f), "limit": 1}).json()
        assert page1["next_cursor"] is not None
        page2 = client.get(
            _url(f),
            params={
                "view": "recent",
                **_perspective(f),
                "limit": 1,
                "cursor": page1["next_cursor"],
            },
        )
    assert page2.status_code == 200
    assert page1["items"][0]["knowledge_item_id"] not in {
        i["knowledge_item_id"] for i in page2.json()["items"]
    }


# ---------------------------------------------------------------------------
# Issue 4: campaign.view vs canon.edit — a canon.edit deny never hides an
# otherwise-visible item; it only strips that item's ground-truth fields.
# ---------------------------------------------------------------------------


def test_a_targeted_canon_edit_deny_does_not_hide_an_item_the_party_believes(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """The player has no `canon.edit` at all, so a `canon.edit` deny
    targeting `rumor_id` changes nothing about that item's capability — yet
    before Issue 4 it vanished from the player's list too (the deny set
    conflated `campaign.view` and `canon.edit`). Now the player still sees
    their party's belief (interpretation, no truth_status/sensitivity), and
    list and detail agree."""
    with postgres_engine.begin() as setup:
        make_resource_grant(
            setup,
            f.campaign_id,
            f.canon_edit_capability_id,
            knowledge_item_id=f.rumor_id,
            grantee_campaign_membership_id=f.player_membership_id,
            effect="deny",
        )
    with client_factory(f.player_user_id) as player:
        listed = player.get(
            _url(f), params={"view": "party_shared", **_perspective(f), "limit": 100}
        ).json()["items"]
        detail = player.get(
            f"/campaigns/{f.campaign_id}/knowledge/{f.rumor_id}", params=_perspective(f)
        )
    row = next(i for i in listed if i["knowledge_item_id"] == str(f.rumor_id))
    assert row["statement"] == "Some say the mayor was replaced last winter."
    assert row["truth_status_code"] is None
    assert row["sensitivity"] is None
    assert detail.status_code == 200
    assert detail.json()["statement"] == row["statement"]


def test_the_canonical_rumors_list_drops_an_item_a_gm_is_denied_ground_truth_for(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with postgres_engine.begin() as setup:
        make_resource_grant(
            setup,
            f.campaign_id,
            f.canon_edit_capability_id,
            knowledge_item_id=f.rumor_id,
            grantee_campaign_membership_id=f.gm_membership_id,
            effect="deny",
        )
    with client_factory(f.gm_user_id) as gm:
        listed = {
            i["knowledge_item_id"]
            for i in gm.get(_url(f), params={"view": "rumors", "limit": 100}).json()["items"]
        }
        detail = gm.get(f"/campaigns/{f.campaign_id}/knowledge/{f.rumor_id}")
    # No perspective, no ground truth for this item -> the canonical view
    # has nothing to show, and detail 404s. They agree.
    assert str(f.rumor_id) not in listed
    assert detail.status_code == 404
    # A different, undenied item is unaffected.
    with client_factory(f.gm_user_id) as gm:
        others = {
            i["knowledge_item_id"]
            for i in gm.get(_url(f), params={"view": "known", "limit": 100}).json()["items"]
        }
    assert str(f.fact_id) in others


def test_a_non_gm_with_a_targeted_canon_edit_allow_sees_that_items_ground_truth_only(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """A targeted `canon.edit` allow reveals one item's canonical view to a
    caller with no baseline `canon.edit` — and *only* that item (no
    campaign-wide GM authority)."""
    with postgres_engine.begin() as setup:
        make_resource_grant(
            setup,
            f.campaign_id,
            f.canon_edit_capability_id,
            knowledge_item_id=f.fact_id,
            grantee_campaign_membership_id=f.player_membership_id,
            effect="allow",
        )
    with client_factory(f.player_user_id) as player:
        known = player.get(_url(f), params={"view": "known", "limit": 100}).json()["items"]
        detail = player.get(f"/campaigns/{f.campaign_id}/knowledge/{f.fact_id}")
    ids = {i["knowledge_item_id"] for i in known}
    assert ids == {str(f.fact_id)}, "only the targeted item, canonical view"
    row = next(i for i in known if i["knowledge_item_id"] == str(f.fact_id))
    assert row["scope"] == "canonical"
    assert row["truth_status_code"] == "true"
    assert detail.status_code == 200
    assert detail.json()["truth_status_code"] == "true"


# ---------------------------------------------------------------------------
# Issue 1: a knowledge item never discloses an unauthorized related id
# ---------------------------------------------------------------------------


def test_a_visible_subject_and_source_event_id_are_returned(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with postgres_engine.begin() as setup:
        org_id = make_organization(setup, f.world_id, name="The Cartographers Guild")
        setup.execute(
            text(
                "UPDATE knowledge.knowledge_items SET subject_entity_id = :s "
                "WHERE knowledge_item_id = :k"
            ),
            {"s": org_id, "k": f.fact_id},
        )
        event_id = make_event(
            setup,
            f.world_id,
            f.timeline_id,
            f.wt_early,
            campaign_id=f.campaign_id,
            name="The Guild Charter Signed",
        )
        setup.execute(
            text(
                "UPDATE knowledge.party_discoveries SET discovered_via_event_id = :e "
                "WHERE party_discovery_id = :d"
            ),
            {"e": event_id, "d": f.discovery_early_id},
        )
    with client_factory(f.player_user_id) as player:
        recent = player.get(
            _url(f), params={"view": "recent", **_perspective(f), "limit": 100}
        ).json()["items"]
    row = next(i for i in recent if i["knowledge_item_id"] == str(f.fact_id))
    assert row["subject_entity_id"] == str(org_id)
    assert row["source_event_id"] == str(event_id)


def test_a_denied_subject_and_a_draft_source_event_id_are_redacted(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """The knowledge item stays visible; only the related ids the player
    cannot independently discover are nulled — and never appear anywhere in
    the serialized response."""
    with postgres_engine.begin() as setup:
        org_id = make_organization(setup, f.world_id, name="The Hidden Circle")
        setup.execute(
            text(
                "UPDATE knowledge.knowledge_items SET subject_entity_id = :s "
                "WHERE knowledge_item_id = :k"
            ),
            {"s": org_id, "k": f.fact_id},
        )
        make_resource_grant(
            setup,
            f.campaign_id,
            f.view_capability_id,
            entity_id=org_id,
            grantee_campaign_membership_id=f.player_membership_id,
            effect="deny",
        )
        draft_event_id = make_event(
            setup,
            f.world_id,
            f.timeline_id,
            f.wt_early,
            campaign_id=f.campaign_id,
            event_status_code="draft",
            name="An Unrecorded Meeting",
        )
        setup.execute(
            text(
                "UPDATE knowledge.party_discoveries SET discovered_via_event_id = :e "
                "WHERE party_discovery_id = :d"
            ),
            {"e": draft_event_id, "d": f.discovery_early_id},
        )
    with client_factory(f.player_user_id) as player:
        response = player.get(_url(f), params={"view": "recent", **_perspective(f), "limit": 100})
    row = next(i for i in response.json()["items"] if i["knowledge_item_id"] == str(f.fact_id))
    assert row["subject_entity_id"] is None
    assert row["source_event_id"] is None
    assert str(org_id) not in response.text
    assert str(draft_event_id) not in response.text
    # The GM (discovers the org, sees the draft event) gets both ids.
    with client_factory(f.gm_user_id) as gm:
        gm_recent = gm.get(_url(f), params={"view": "recent", "limit": 100}).json()["items"]
    gm_row = next(i for i in gm_recent if i["knowledge_item_id"] == str(f.fact_id))
    assert gm_row["subject_entity_id"] == str(org_id)
    assert gm_row["source_event_id"] == str(draft_event_id)


def test_a_same_timeline_source_interaction_id_is_returned(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """`interaction.interactions` has no browse/detail endpoint; the only
    "may I see this" signal the redaction check permits is that it happened
    on the caller's own campaign timeline — which the schema's own
    `enforce_party_discovery_source_world` trigger already guarantees for
    any interaction a discovery references, so a cross-timeline reference
    cannot be constructed on these tables and there is no negative case to
    assert. This confirms the permitted (positive) case."""
    with postgres_engine.begin() as setup:
        interaction_id = make_interaction(
            setup, f.timeline_id, f.wt_early, campaign_id=f.campaign_id
        )
        setup.execute(
            text(
                "UPDATE knowledge.party_discoveries SET discovered_via_interaction_id = :i "
                "WHERE party_discovery_id = :d"
            ),
            {"i": interaction_id, "d": f.discovery_early_id},
        )
    with client_factory(f.player_user_id) as player:
        recent = player.get(
            _url(f), params={"view": "recent", **_perspective(f), "limit": 100}
        ).json()["items"]
    row = next(i for i in recent if i["knowledge_item_id"] == str(f.fact_id))
    assert row["source_interaction_id"] == str(interaction_id)
    with postgres_engine.begin() as teardown:
        teardown.execute(text("SET LOCAL session_replication_role = replica"))
        teardown.execute(
            text("DELETE FROM interaction.interactions WHERE interaction_id = :i"),
            {"i": interaction_id},
        )
