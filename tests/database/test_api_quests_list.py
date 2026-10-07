"""Tests for `dnd_ai.api.quests`'s new list endpoint — Phase 13D backend-
readiness workstream's `GET /campaigns/{campaign_id}/quests`, added
because the existing detail route (`GET .../quests/{quest_id}`) requires
already knowing a `quest_id`, and nothing else in this codebase could
enumerate a campaign's tracked quests (the portal's Home dashboard "active
quests" section and a Quests screen both need this).

`tests/database/test_api_quests_query.py` already exhaustively covers
`visibility_policy` filtering, resource-grant overrides, and party-scoped-
over-campaign-wide status for the *detail* route; this file proves only
the list's own behavior: which quests are tracked/untracked, ordering,
the party-scoped status preference at list granularity, and access
control. It does not re-prove objective-level visibility, since the list
never returns objectives at all.

A correction pass (post-review) fixed two defects the initial cut had:
the list never resolved per-quest `campaign.view` resource-grant denies at
all (an incorrect module comment had claimed no per-quest resource-grant
target existed, when `quest_id` is in fact a valid target column, exactly
like `session_id` already is for `dnd_ai.api.sessions`), and a quest
tracked *only* through one party's independent `campaign.quest_state` row
(no campaign-wide row) was silently excluded even from a GM's own list.
The corresponding test classes below (`# Per-quest resource-grant deny`,
`# Party-only-tracked quests`) prove both fixes; `dnd_ai.api.quests.
get_quest_endpoint`'s own equivalent detail-route hardening is covered by
`tests/database/test_api_quests_query.py` instead, to keep list- and
detail-route coverage in their existing respective files.
"""

import uuid
from collections.abc import Callable, Iterator
from typing import Any, cast

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

        # Tracked campaign-wide, no party override.
        self.tracked_quest_id = make_quest(connection, self.world_id, name="Restore the Shrine")
        make_quest_state(connection, self.timeline_id, self.tracked_quest_id, status_code="active")

        # Tracked campaign-wide *and* with an independent party-scoped
        # status — proves the party-preferred-over-campaign-wide fallback
        # applies at list granularity too.
        self.party_scoped_quest_id = make_quest(connection, self.world_id, name="Find the Relic")
        make_quest_state(
            connection, self.timeline_id, self.party_scoped_quest_id, status_code="active"
        )
        self.party_id = make_party(connection, self.world_id, name="The Company")
        make_campaign_party(connection, self.campaign_id, self.party_id)
        make_quest_state(
            connection,
            self.timeline_id,
            self.party_scoped_quest_id,
            party_id=self.party_id,
            status_code="completed",
        )

        # Defined but never tracked on this timeline — must not appear.
        self.untracked_quest_id = make_quest(connection, self.world_id, name="Unused Hook")

        # Tracked *only* through self.party_id's own independent row — no
        # campaign-wide campaign.quest_state row at all. Proves the
        # corrected include_all_parties contract: a GM sees it (canonical
        # truth across every party); an authorized member of the owning
        # party sees it too; a caller with no party perspective at all
        # would not (not separately tested here — cross-party privacy for
        # a *different* party's own independent tracking is covered by
        # dnd_ai.queries.quest.list_campaign_quests's own docstring
        # reasoning, not re-derived per campaign role combination here).
        self.party_only_quest_id = make_quest(connection, self.world_id, name="The Company's Oath")
        make_quest_state(
            connection,
            self.timeline_id,
            self.party_only_quest_id,
            party_id=self.party_id,
            status_code="active",
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

        self.gm_user_id = make_user(connection, "Quest List GM")
        gm_membership_id = make_campaign_membership(connection, self.campaign_id, self.gm_user_id)
        self.gm_membership_id = gm_membership_id
        gm_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"gm_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, gm_role_id, view_capability_id)
        make_role_capability(connection, gm_role_id, canon_edit_id)
        make_membership_role(connection, gm_membership_id, gm_role_id)

        # A player with an authorized character/party perspective — proves
        # the party-preferred-over-campaign-wide status fallback (a GM
        # never resolves a perspective at all, matching
        # get_quest_endpoint's own include_hidden branch).
        self.player_user_id = make_user(connection, "Quest List Player")
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

        # A member with no role/capability at all — proves ForbiddenError,
        # distinct from a non-member's NotFoundError.
        self.capless_user_id = make_user(connection, "Quest List Capless Member")
        make_campaign_membership(connection, self.campaign_id, self.capless_user_id)

        # Never given a membership at all.
        self.outsider_user_id = make_user(connection, "Quest List Outsider")


@pytest.fixture
def f(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as connection:
        fixture = Fixture(connection, f"quest-list-{uuid.uuid4().hex[:8]}")
    yield fixture
    with postgres_engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        cleanup.execute(
            text("""
                DELETE FROM security.membership_character_relationships
                WHERE campaign_membership_id IN (
                    SELECT campaign_membership_id FROM security.campaign_memberships
                    WHERE campaign_id = :c
                )
            """),
            {"c": fixture.campaign_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM security.membership_roles WHERE role_id IN (
                    SELECT role_id FROM security.roles WHERE campaign_id = :c
                )
            """),
            {"c": fixture.campaign_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM security.role_capabilities WHERE role_id IN (
                    SELECT role_id FROM security.roles WHERE campaign_id = :c
                )
            """),
            {"c": fixture.campaign_id},
        )
        cleanup.execute(
            text("DELETE FROM security.roles WHERE campaign_id = :c"), {"c": fixture.campaign_id}
        )
        # security.resource_grants is created ad hoc by individual tests
        # below (the per-quest campaign.view deny regression tests), never
        # by the shared Fixture itself — cleaned up here, scoped by
        # campaign_id, before the campaign_memberships row it references is
        # removed.
        cleanup.execute(
            text("DELETE FROM security.resource_grants WHERE campaign_id = :c"),
            {"c": fixture.campaign_id},
        )
        cleanup.execute(
            text("DELETE FROM security.campaign_memberships WHERE campaign_id = :c"),
            {"c": fixture.campaign_id},
        )
        cleanup.execute(
            text("DELETE FROM campaign.party_memberships WHERE timeline_id = :t"),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text("DELETE FROM campaign.campaign_parties WHERE campaign_id = :c"),
            {"c": fixture.campaign_id},
        )
        cleanup.execute(
            text("DELETE FROM campaign.campaigns WHERE campaign_id = :c"),
            {"c": fixture.campaign_id},
        )
        cleanup.execute(
            text("DELETE FROM campaign.parties WHERE world_id = :w"), {"w": fixture.world_id}
        )
        cleanup.execute(
            text("DELETE FROM campaign.timelines WHERE world_id = :w"), {"w": fixture.world_id}
        )
        cleanup.execute(
            text("DELETE FROM core.entities WHERE world_id = :w"), {"w": fixture.world_id}
        )
        cleanup.execute(
            text("DELETE FROM core.worlds WHERE world_id = :w"), {"w": fixture.world_id}
        )
        # security.character_relationship_types is a global lookup table,
        # not scoped by world — deleted here by id, after the
        # membership_character_relationships row referencing it above.
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


def _list_url(f: Fixture) -> str:
    return f"/campaigns/{f.campaign_id}/quests"


def test_a_non_member_gets_not_found(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.outsider_user_id) as client:
        response = client.get(_list_url(f))
    assert response.status_code == 404


def test_a_member_without_campaign_view_gets_forbidden(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.capless_user_id) as client:
        response = client.get(_list_url(f))
    assert response.status_code == 403


def test_only_tracked_quests_are_listed(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.get(_list_url(f))
    assert response.status_code == 200, response.text
    items = {item["quest_id"]: item for item in response.json()}
    # Phase 15.1: an editor also sees authored definitions no party has started,
    # flagged untracked, so a draft quest can be found and edited.
    assert set(items) == {
        str(f.tracked_quest_id),
        str(f.party_scoped_quest_id),
        str(f.party_only_quest_id),
        str(f.untracked_quest_id),
    }
    assert items[str(f.untracked_quest_id)]["tracked"] is False
    assert items[str(f.tracked_quest_id)]["tracked"] is True


def test_without_a_party_perspective_the_campaign_wide_status_applies(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.get(_list_url(f))
    assert response.status_code == 200, response.text
    by_id = {item["quest_id"]: item for item in response.json()}
    assert by_id[str(f.party_scoped_quest_id)]["status_code"] == "active"


def test_with_an_authorized_party_perspective_its_own_status_takes_precedence(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    """f.gm_user_id is deliberately not used here: a caller holding
    baseline canon.edit never resolves a party perspective at all (see
    list_quests_endpoint's own comment), so only a non-GM caller with an
    authorized character/party pair can exercise this branch."""
    with client_factory(f.player_user_id) as client:
        response = client.get(
            _list_url(f),
            params={"character_id": str(f.character_id), "party_id": str(f.party_id)},
        )
    assert response.status_code == 200, response.text
    by_id = {item["quest_id"]: item for item in response.json()}
    assert by_id[str(f.party_scoped_quest_id)]["status_code"] == "completed"
    # The campaign-wide-only quest is unaffected by a party perspective it
    # has no party-scoped row for.
    assert by_id[str(f.tracked_quest_id)]["status_code"] == "active"


# ---------------------------------------------------------------------------
# Party-only-tracked quests (correction pass: a quest tracked exclusively
# through one party's own campaign.quest_state row, with no campaign-wide
# row, used to be silently excluded even from a GM's own list)
# ---------------------------------------------------------------------------


def test_a_party_only_tracked_quest_is_visible_to_a_gm(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.get(_list_url(f))
    assert response.status_code == 200, response.text
    by_id = {item["quest_id"]: item for item in response.json()}
    assert str(f.party_only_quest_id) in by_id
    # The GM never resolves a party perspective (see
    # list_quests_endpoint's own comment), so with no campaign-wide row to
    # fall back to, the status is unresolved rather than fabricated.
    assert by_id[str(f.party_only_quest_id)]["status_code"] is None


def test_a_party_only_tracked_quest_is_visible_to_its_own_partys_perspective(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.player_user_id) as client:
        response = client.get(
            _list_url(f),
            params={"character_id": str(f.character_id), "party_id": str(f.party_id)},
        )
    assert response.status_code == 200, response.text
    by_id = {item["quest_id"]: item for item in response.json()}
    assert by_id[str(f.party_only_quest_id)]["status_code"] == "active"


# ---------------------------------------------------------------------------
# Per-quest campaign.view resource-grant deny (correction pass: the list
# previously never resolved this at all, despite quest_id being a valid
# security.resource_grants/AccessContext target column)
# ---------------------------------------------------------------------------


def test_a_targeted_deny_hides_the_quest_from_the_list_without_removing_others(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with postgres_engine.begin() as setup:
        make_resource_grant(
            setup,
            f.campaign_id,
            f.view_capability_id,
            quest_id=f.tracked_quest_id,
            grantee_campaign_membership_id=f.gm_membership_id,
            effect="deny",
        )

    with client_factory(f.gm_user_id) as client:
        response = client.get(_list_url(f))
    assert response.status_code == 200, response.text
    quest_ids = {item["quest_id"] for item in response.json()}
    assert str(f.tracked_quest_id) not in quest_ids
    # An unrelated denied quest does not remove other, otherwise-visible
    # quests from the response.
    assert quest_ids == {
        str(f.party_scoped_quest_id),
        str(f.party_only_quest_id),
        str(f.untracked_quest_id),
    }


def test_a_targeted_deny_hides_the_quest_from_direct_detail_access(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """A role-derived campaign.view holder (and, here, canon.edit too) is
    still rejected identically to a nonexistent quest — the deny is never
    merely a list-time filter."""
    with postgres_engine.begin() as setup:
        make_resource_grant(
            setup,
            f.campaign_id,
            f.view_capability_id,
            quest_id=f.tracked_quest_id,
            grantee_campaign_membership_id=f.gm_membership_id,
            effect="deny",
        )

    with client_factory(f.gm_user_id) as client:
        response = client.get(f"/campaigns/{f.campaign_id}/quests/{f.tracked_quest_id}")
    assert response.status_code == 404


def test_the_deny_does_not_affect_a_different_campaign_member(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with postgres_engine.begin() as setup:
        make_resource_grant(
            setup,
            f.campaign_id,
            f.view_capability_id,
            quest_id=f.tracked_quest_id,
            grantee_campaign_membership_id=f.gm_membership_id,
            effect="deny",
        )

    with client_factory(f.player_user_id) as client:
        list_response = client.get(_list_url(f))
        detail_response = client.get(f"/campaigns/{f.campaign_id}/quests/{f.tracked_quest_id}")
    assert list_response.status_code == 200, list_response.text
    assert str(f.tracked_quest_id) in {item["quest_id"] for item in list_response.json()}
    assert detail_response.status_code == 200, detail_response.text


# ---------------------------------------------------------------------------
# Party audience end-to-end: the (character_id, party_id) pair the portal
# sends adds the own party's quests and statuses to the campaign-wide ones,
# never another party's, and is re-authorized on every request.
# ---------------------------------------------------------------------------


class _PartyAudience:
    def __init__(self, connection: Connection, f: Fixture) -> None:
        self.rival_party_id = make_party(connection, f.world_id, name="The Rivals")
        make_campaign_party(connection, f.campaign_id, self.rival_party_id)
        # Tracked only for the rival party — never visible to The Company.
        self.rival_only_quest_id = make_quest(connection, f.world_id, name="The Rivals' Pact")
        make_quest_state(
            connection,
            f.timeline_id,
            self.rival_only_quest_id,
            party_id=self.rival_party_id,
            status_code="active",
        )
        # A rival-specific status on a campaign-wide quest.
        make_quest_state(
            connection,
            f.timeline_id,
            f.tracked_quest_id,
            party_id=self.rival_party_id,
            status_code="failed",
        )
        # One objective on the campaign-wide quest with a campaign-wide, an
        # own-party, and a rival-party status.
        stage_id = make_quest_stage(connection, f.tracked_quest_id)
        self.objective_id = make_quest_objective(connection, stage_id, name="Light the beacon")
        make_objective_state(connection, f.timeline_id, self.objective_id, status_code="active")
        make_objective_state(
            connection,
            f.timeline_id,
            self.objective_id,
            party_id=f.party_id,
            status_code="completed",
        )
        make_objective_state(
            connection,
            f.timeline_id,
            self.objective_id,
            party_id=self.rival_party_id,
            status_code="failed",
        )


@pytest.fixture
def audience(f: Fixture, postgres_engine: Engine) -> _PartyAudience:
    with postgres_engine.begin() as connection:
        return _PartyAudience(connection, f)


def _pair(f: Fixture) -> dict[str, str]:
    return {"character_id": str(f.character_id), "party_id": str(f.party_id)}


def _objective_status(detail: dict[str, Any], objective_id: uuid.UUID) -> str | None:
    for stage in detail["stages"]:
        for objective in stage["objectives"]:
            if objective["quest_objective_id"] == str(objective_id):
                return cast("str | None", objective["status_code"])
    raise AssertionError(f"objective {objective_id} not in detail")


def test_a_party_perspective_keeps_campaign_wide_quests_and_adds_its_own(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, audience: _PartyAudience
) -> None:
    with client_factory(f.player_user_id) as client:
        response = client.get(_list_url(f), params=_pair(f))
    assert response.status_code == 200, response.text
    by_id = {item["quest_id"]: item for item in response.json()}
    assert set(by_id) == {
        str(f.tracked_quest_id),
        str(f.party_scoped_quest_id),
        str(f.party_only_quest_id),
    }
    # The rival party's own quest is never listed, and its status on the
    # campaign-wide quest never replaces the campaign-wide one.
    assert str(audience.rival_only_quest_id) not in by_id
    assert by_id[str(f.tracked_quest_id)]["status_code"] == "active"
    assert by_id[str(f.party_scoped_quest_id)]["status_code"] == "completed"


def test_a_character_without_its_party_sees_campaign_wide_quests_only(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, audience: _PartyAudience
) -> None:
    """The request shape the portal used to send (`character_id` alone):
    no party perspective is resolved, so party-only quests and party
    statuses stay out — which is why the portal must send the pair."""
    with client_factory(f.player_user_id) as client:
        response = client.get(_list_url(f), params={"character_id": str(f.character_id)})
    assert response.status_code == 200, response.text
    by_id = {item["quest_id"]: item for item in response.json()}
    assert set(by_id) == {str(f.tracked_quest_id), str(f.party_scoped_quest_id)}
    assert by_id[str(f.party_scoped_quest_id)]["status_code"] == "active"


def test_detail_shows_the_own_partys_objective_status_never_anothers(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, audience: _PartyAudience
) -> None:
    detail_url = f"/campaigns/{f.campaign_id}/quests/{f.tracked_quest_id}"
    with client_factory(f.player_user_id) as client:
        with_party = client.get(detail_url, params=_pair(f))
        without_party = client.get(detail_url, params={"character_id": str(f.character_id)})
        rival_quest = client.get(
            f"/campaigns/{f.campaign_id}/quests/{audience.rival_only_quest_id}",
            params=_pair(f),
        )
    assert with_party.status_code == 200, with_party.text
    assert with_party.json()["status_code"] == "active"
    assert _objective_status(with_party.json(), audience.objective_id) == "completed"
    assert _objective_status(without_party.json(), audience.objective_id) == "active"
    # Another party's private quest is the same non-disclosing 404 as a
    # nonexistent one, even with a valid perspective.
    assert rival_quest.status_code == 404


def test_every_listed_quest_opens_in_detail_under_the_same_perspective(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, audience: _PartyAudience
) -> None:
    with client_factory(f.player_user_id) as client:
        listed = client.get(_list_url(f), params=_pair(f)).json()
        for item in listed:
            detail = client.get(
                f"/campaigns/{f.campaign_id}/quests/{item['quest_id']}", params=_pair(f)
            )
            assert detail.status_code == 200, (item, detail.text)
            assert detail.json()["status_code"] == item["status_code"]


def test_a_party_the_character_does_not_belong_to_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, audience: _PartyAudience
) -> None:
    params = {"character_id": str(f.character_id), "party_id": str(audience.rival_party_id)}
    with client_factory(f.player_user_id) as client:
        listed = client.get(_list_url(f), params=params)
        detail = client.get(
            f"/campaigns/{f.campaign_id}/quests/{audience.rival_only_quest_id}", params=params
        )
    assert listed.status_code == 404
    assert detail.status_code == 404


@pytest.mark.parametrize("revocation", ["party_membership", "character_relationship"])
def test_perspective_revocation_takes_effect_on_the_next_request(
    client_factory: Callable[[uuid.UUID], TestClient],
    f: Fixture,
    audience: _PartyAudience,
    postgres_engine: Engine,
    revocation: str,
) -> None:
    detail_url = f"/campaigns/{f.campaign_id}/quests/{f.party_only_quest_id}"
    with client_factory(f.player_user_id) as client:
        before_list = client.get(_list_url(f), params=_pair(f))
        before_detail = client.get(detail_url, params=_pair(f))
    assert str(f.party_only_quest_id) in {item["quest_id"] for item in before_list.json()}
    assert before_detail.status_code == 200

    with postgres_engine.begin() as revoke:
        if revocation == "party_membership":
            later = make_world_time(revoke, f.world_id, 200)
            revoke.execute(
                text(
                    "UPDATE campaign.party_memberships SET effective_to_world_time_id = :t "
                    "WHERE party_id = :p AND member_entity_id = :c"
                ),
                {"t": later, "p": f.party_id, "c": f.character_id},
            )
        else:
            revoke.execute(
                text(
                    "UPDATE security.membership_character_relationships SET revoked_at = now() "
                    "WHERE character_id = :c"
                ),
                {"c": f.character_id},
            )

    with client_factory(f.player_user_id) as client:
        after_list = client.get(_list_url(f), params=_pair(f))
        after_detail = client.get(detail_url, params=_pair(f))
        campaign_wide = client.get(_list_url(f))
    # The pair can no longer be proven: the same fixed 404 as any
    # unauthorized perspective, never a silent party-scoped answer.
    assert after_list.status_code == 404
    assert after_detail.status_code == 404
    # Campaign-wide quests remain available without the revoked perspective.
    assert {item["quest_id"] for item in campaign_wide.json()} == {
        str(f.tracked_quest_id),
        str(f.party_scoped_quest_id),
    }
