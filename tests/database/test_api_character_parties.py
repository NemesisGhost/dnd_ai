"""Tests for `GET /campaigns/{id}/characters/{character_id}/parties` — the informational party
affiliations list in the campaign Info Box (docs/UI_DESIGN.md §4).

Covers: the complete, stably ordered current membership; the temporal rule (an ended membership
and a membership on another timeline do not count); campaign attachment (a party of another
campaign never appears); archived parties (editor-only); authorization (the identical fixed 404
for a non-member, a character the caller has no perspective on, a character of another world, a
nonexistent character and a revoked relationship); the empty list; `can_open`; and that nothing
here is a knowledge perspective.
"""

import uuid
from collections.abc import Callable, Iterator
from typing import Any

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
    make_party,
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
        self.other_timeline_id = make_timeline(connection, self.world_id)
        self.wt_early = make_world_time(connection, self.world_id, 100)
        self.wt_late = make_world_time(connection, self.world_id, 900)
        self.campaign_id = make_campaign(
            connection, self.timeline_id, lifecycle_status_code="pending"
        )
        self.other_campaign_id = make_campaign(
            connection, self.timeline_id, "Other campaign", lifecycle_status_code="pending"
        )

        self.character_id = make_character(connection, self.world_id, name="Aria")
        self.loner_id = make_character(connection, self.world_id, name="Loner")
        self.other_character_id = make_character(connection, self.world_id, name="Borin")
        foreign_world = make_world(connection, slug=f"{slug}-foreign")
        self.foreign_world_id = foreign_world
        self.foreign_character_id = make_character(connection, foreign_world, name="Stranger")

        # Aria's parties, deliberately not created in name order.
        self.zeta = self._party(connection, "Zeta Company", attach=True, member=True)
        self.alpha = self._party(connection, "alpha Wardens", attach=True, member=True)
        self.mid = self._party(connection, "Midnight Court", attach=True, member=True)
        # Not counted: an ended membership, a membership on another timeline, a party of another
        # campaign, a party she never joined, and (for a player) an archived one.
        self.ended = self._party(connection, "Former Band", attach=True, member=False)
        make_party_membership(
            connection,
            self.timeline_id,
            self.ended,
            self.character_id,
            self.wt_early,
            effective_to_world_time_id=self.wt_late,
        )
        self.branch_only = self._party(connection, "Branch Band", attach=True, member=False)
        make_party_membership(
            connection, self.other_timeline_id, self.branch_only, self.character_id, self.wt_early
        )
        self.elsewhere = make_party(connection, self.world_id, name="Elsewhere Company")
        make_campaign_party(connection, self.other_campaign_id, self.elsewhere)
        make_party_membership(
            connection, self.timeline_id, self.elsewhere, self.character_id, self.wt_early
        )
        self.never_joined = self._party(connection, "Rivals", attach=True, member=False)
        self.archived = self._party(connection, "Disbanded Guild", attach=True, member=True)
        connection.execute(
            text(
                "UPDATE campaign.parties SET archived_at = now(), lifecycle_status_id = "
                "(SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'archived') "
                "WHERE party_id = :p"
            ),
            {"p": self.archived},
        )

        view = lookup_id(connection, "security", "capabilities", "capability_id", "campaign.view")
        canon = lookup_id(connection, "security", "capabilities", "capability_id", "canon.edit")
        view_knowledge = lookup_id(
            connection, "security", "capabilities", "capability_id", "character.view_knowledge"
        )

        self.gm_user_id = make_user(connection, "Parties GM")
        gm_membership = make_campaign_membership(connection, self.campaign_id, self.gm_user_id)
        gm_role = make_role(
            connection, campaign_id=self.campaign_id, code=f"gm_{uuid.uuid4().hex[:8]}"
        )
        for capability in (view, canon, view_knowledge):
            make_role_capability(connection, gm_role, capability)
        make_membership_role(connection, gm_membership, gm_role)

        self.player_user_id = make_user(connection, "Parties Player")
        self.player_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.player_user_id
        )
        player_role = make_role(
            connection, campaign_id=self.campaign_id, code=f"player_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, player_role, view)
        make_membership_role(connection, self.player_membership_id, player_role)
        self.relationship_type_id = make_character_relationship_type(connection)
        make_relationship_type_capability(connection, self.relationship_type_id, view_knowledge)
        for character in (self.character_id, self.loner_id):
            make_membership_character_relationship(
                connection,
                self.player_membership_id,
                character,
                self.relationship_type_id,
                timeline_id=self.timeline_id,
            )
        self.outsider_user_id = make_user(connection, "Parties Outsider")

    def _party(self, connection: Connection, name: str, *, attach: bool, member: bool) -> uuid.UUID:
        party = make_party(connection, self.world_id, name=name)
        if attach:
            make_campaign_party(connection, self.campaign_id, party)
        if member:
            make_party_membership(
                connection, self.timeline_id, party, self.character_id, self.wt_early
            )
        return party


@pytest.fixture
def f(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as connection:
        fixture = Fixture(connection, f"character-parties-{uuid.uuid4().hex[:8]}")
    yield fixture
    with postgres_engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        c = {"c": fixture.campaign_id, "t": fixture.timeline_id}
        for stmt, param in [
            (
                "DELETE FROM security.membership_character_relationships WHERE "
                "campaign_membership_id IN (SELECT campaign_membership_id "
                "FROM security.campaign_memberships WHERE campaign_id = :c)",
                c,
            ),
            (
                "DELETE FROM security.membership_roles WHERE role_id IN "
                "(SELECT role_id FROM security.roles WHERE campaign_id = :c)",
                c,
            ),
            (
                "DELETE FROM security.role_capabilities WHERE role_id IN "
                "(SELECT role_id FROM security.roles WHERE campaign_id = :c)",
                c,
            ),
            ("DELETE FROM security.roles WHERE campaign_id = :c", c),
            ("DELETE FROM security.resource_grants WHERE campaign_id = :c", c),
            ("DELETE FROM security.campaign_memberships WHERE campaign_id = :c", c),
            (
                "DELETE FROM campaign.party_memberships WHERE timeline_id IN "
                "(SELECT timeline_id FROM campaign.timelines WHERE world_id = :w)",
                {"w": fixture.world_id},
            ),
            (
                "DELETE FROM campaign.campaign_parties WHERE campaign_id = ANY(:cs)",
                {"cs": [fixture.campaign_id, fixture.other_campaign_id]},
            ),
            (
                "DELETE FROM campaign.campaigns WHERE campaign_id = ANY(:cs)",
                {"cs": [fixture.campaign_id, fixture.other_campaign_id]},
            ),
            ("DELETE FROM campaign.parties WHERE world_id = :w", {"w": fixture.world_id}),
            ("DELETE FROM campaign.timelines WHERE world_id = :w", {"w": fixture.world_id}),
            (
                "DELETE FROM core.entities WHERE world_id = ANY(:ws)",
                {"ws": [fixture.world_id, fixture.foreign_world_id]},
            ),
            (
                "DELETE FROM core.worlds WHERE world_id = ANY(:ws)",
                {"ws": [fixture.world_id, fixture.foreign_world_id]},
            ),
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
        app = create_app()
        app.dependency_overrides[get_engine] = lambda: postgres_engine
        app.dependency_overrides[get_authenticated_user_id] = lambda: oidc_principal(user_id)
        return TestClient(app, raise_server_exceptions=False)

    return _make


def _url(f: Fixture, character_id: uuid.UUID, campaign_id: uuid.UUID | None = None) -> str:
    return f"/campaigns/{campaign_id or f.campaign_id}/characters/{character_id}/parties"


def _names(body: dict[str, Any]) -> list[str]:
    return [item["name"] for item in body["items"]]


def test_a_player_sees_the_complete_current_membership_in_a_stable_name_order(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.player_user_id) as client:
        first = client.get(_url(f, f.character_id))
        second = client.get(_url(f, f.character_id))
    assert first.status_code == 200
    body = first.json()
    assert body == second.json()
    # Case-insensitive name order; ended, other-timeline, other-campaign, un-joined and (for a
    # player) archived parties are all absent.
    assert _names(body) == ["alpha Wardens", "Midnight Court", "Zeta Company"]
    assert [i["party_id"] for i in body["items"]] == [str(f.alpha), str(f.mid), str(f.zeta)]
    assert body["character_id"] == str(f.character_id)
    assert body["can_open"] is False
    # Only the affiliation: no description, version or lifecycle detail.
    assert all(set(i) == {"party_id", "name"} for i in body["items"])


def test_the_list_is_never_truncated_to_a_page(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with postgres_engine.begin() as setup:
        for number in range(60):
            party = make_party(setup, f.world_id, name=f"Band {number:02d}")
            make_campaign_party(setup, f.campaign_id, party)
            make_party_membership(setup, f.timeline_id, party, f.character_id, f.wt_early)
    with client_factory(f.player_user_id) as client:
        body = client.get(_url(f, f.character_id)).json()
    assert len(body["items"]) == 63
    assert _names(body) == sorted(_names(body), key=lambda name: (name.lower(), name))


def test_a_gm_may_open_parties_and_also_sees_an_archived_one(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        body = client.get(_url(f, f.character_id)).json()
    assert body["can_open"] is True
    assert _names(body) == ["alpha Wardens", "Disbanded Guild", "Midnight Court", "Zeta Company"]


def test_a_character_with_no_memberships_is_an_empty_list_not_an_error(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.player_user_id) as client:
        response = client.get(_url(f, f.loner_id))
    assert response.status_code == 200
    assert response.json()["items"] == []


def test_membership_changes_show_on_the_next_request(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.player_user_id) as client:
        before = _names(client.get(_url(f, f.character_id)).json())
        with postgres_engine.begin() as change:
            change.execute(
                text(
                    "UPDATE campaign.party_memberships SET effective_to_world_time_id = :wt "
                    "WHERE party_id = :p AND member_entity_id = :c"
                ),
                {"wt": f.wt_late, "p": f.mid, "c": f.character_id},
            )
        after = _names(client.get(_url(f, f.character_id)).json())
    assert "Midnight Court" in before
    assert after == ["alpha Wardens", "Zeta Company"]


def test_each_character_gets_only_its_own_memberships(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with postgres_engine.begin() as setup:
        party = make_party(setup, f.world_id, name="Loner's Circle")
        make_campaign_party(setup, f.campaign_id, party)
        make_party_membership(setup, f.timeline_id, party, f.loner_id, f.wt_early)
    with client_factory(f.player_user_id) as client:
        loner = _names(client.get(_url(f, f.loner_id)).json())
        aria = _names(client.get(_url(f, f.character_id)).json())
    assert loner == ["Loner's Circle"]
    assert "Loner's Circle" not in aria


def test_unauthorized_characters_and_campaigns_get_one_identical_not_found(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """A character the player has no perspective on (even one in a party), a character of another
    world, a nonexistent one, a campaign the caller is not in and a revoked relationship are all
    the same fixed 404 — no party name, id or count leaks through any of them."""
    with postgres_engine.begin() as setup:
        shared = make_party(setup, f.world_id, name="Borin's Secret Order")
        make_campaign_party(setup, f.campaign_id, shared)
        make_party_membership(setup, f.timeline_id, shared, f.other_character_id, f.wt_early)
    with client_factory(f.player_user_id) as client:
        responses = [
            client.get(_url(f, f.other_character_id)),
            client.get(_url(f, f.foreign_character_id)),
            client.get(_url(f, uuid.uuid4())),
            client.get(_url(f, f.character_id, f.other_campaign_id)),
        ]
    with client_factory(f.outsider_user_id) as client:
        responses.append(client.get(_url(f, f.character_id)))
    with postgres_engine.begin() as revoke:
        revoke.execute(
            text(
                "UPDATE security.membership_character_relationships SET revoked_at = now() "
                "WHERE character_id = :c"
            ),
            {"c": f.character_id},
        )
    with client_factory(f.player_user_id) as client:
        responses.append(client.get(_url(f, f.character_id)))
    assert [r.status_code for r in responses] == [404] * 6
    shapes = {
        tuple(sorted((k, v) for k, v in r.json()["error"].items() if k != "correlation_id"))
        for r in responses
    }
    assert len(shapes) == 1
    assert all("Borin" not in r.text and "Secret" not in r.text for r in responses)


def test_a_character_targeted_view_deny_hides_the_list(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with postgres_engine.begin() as setup:
        view = lookup_id(setup, "security", "capabilities", "capability_id", "campaign.view")
        make_resource_grant(
            setup,
            f.campaign_id,
            view,
            entity_id=f.character_id,
            grantee_campaign_membership_id=f.player_membership_id,
            effect="deny",
        )
    with client_factory(f.player_user_id) as client:
        assert client.get(_url(f, f.character_id)).status_code == 404


def test_reading_the_list_changes_no_knowledge_state(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """It is an affiliation list: a read writes nothing, and a party named here is not thereby a
    knowledge perspective (that still needs the explicit, authorized pair)."""
    tables = (
        "campaign.party_knowledge",
        "knowledge.entity_knowledge",
        "knowledge.party_discoveries",
    )
    counts_before = _counts(postgres_engine, tables)
    with client_factory(f.player_user_id) as client:
        assert client.get(_url(f, f.character_id)).status_code == 200
    assert _counts(postgres_engine, tables) == counts_before


def _counts(engine: Engine, tables: tuple[str, ...]) -> list[int]:
    with engine.connect() as connection:
        return [
            int(connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one())
            for table in tables
        ]
