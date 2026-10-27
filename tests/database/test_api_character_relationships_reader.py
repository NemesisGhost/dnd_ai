"""Tests for `GET /campaigns/{id}/characters/{character_id}/relationships` — the reader projection
behind the character page's player-facing, read-only Relationships section.

Covers the reader policy (ADR 0017: active, public subtype, every participant discoverable by this
caller), non-disclosure (a hidden edge leaves no trace), the absence of every GM_ONLY value from the
body, orientation from either participant, the period status against the effective (and inherited)
campaign clock, link eligibility, the character-page gate, and agreement with the existing
`/world/relationships` list on the same fixture.
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
    make_character,
    make_character_relationship_type,
    make_employment_relationship,
    make_family_relationship,
    make_location,
    make_membership_character_relationship,
    make_membership_role,
    make_organization,
    make_organization_membership,
    make_ownership_relationship,
    make_political_relationship,
    make_relationship,
    make_relationship_participant,
    make_relationship_perspective,
    make_relationship_state,
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

# Values that must never appear anywhere in a reader response.
DESCRIPTION = "SENTINEL-description-gm-only"
TREATY = "SENTINEL-treaty-terms"
NOTES = "SENTINEL-participant-notes"
TONE = "SENTINEL-shared-tone"
INTERPRETATION = "SENTINEL-shared-interpretation"
PERSPECTIVE_TONE = "SENTINEL-perspective-tone"
PERSPECTIVE_INTERPRETATION = "SENTINEL-perspective-interpretation"
SENTINELS = (
    DESCRIPTION,
    TREATY,
    NOTES,
    TONE,
    INTERPRETATION,
    PERSPECTIVE_TONE,
    PERSPECTIVE_INTERPRETATION,
)


def _insert_npc(connection: Connection, world_id: uuid.UUID, name: str, **kwargs: Any) -> uuid.UUID:
    npc = make_character(connection, world_id, name=name, entity_type_code="npc")
    connection.execute(text("INSERT INTO character.npcs (npc_id) VALUES (:i)"), {"i": npc})
    if kwargs.get("canon") == "draft":
        connection.execute(
            text(
                "UPDATE core.entities SET canon_status_id = (SELECT canon_status_id FROM "
                "core.canon_statuses WHERE code = 'draft') WHERE entity_id = :i"
            ),
            {"i": npc},
        )
    return npc


class Fixture:
    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        self.wt = {
            k: make_world_time(connection, self.world_id, k) for k in (100, 300, 500, 600, 900)
        }
        # The primary clock reads 700; a branch cut at 500 inherits 500.
        self.wt[700] = make_world_time(connection, self.world_id, 700)
        connection.execute(
            text(
                "INSERT INTO campaign.timeline_clocks (timeline_id, current_world_time_id) "
                "VALUES (:t, :w)"
            ),
            {"t": self.timeline_id, "w": self.wt[700]},
        )
        self.branch_timeline_id = make_timeline(
            connection,
            self.world_id,
            "Branch",
            parent_timeline_id=self.timeline_id,
            branch_world_time_id=self.wt[500],
        )
        self.campaign_id = make_campaign(
            connection, self.timeline_id, lifecycle_status_code="pending"
        )
        self.branch_campaign_id = make_campaign(
            connection, self.branch_timeline_id, "Branch campaign", lifecycle_status_code="pending"
        )

        self.aria = make_character(
            connection, self.world_id, name="Aria", entity_type_code="player_character"
        )
        connection.execute(
            text("INSERT INTO character.player_characters (player_character_id) VALUES (:i)"),
            {"i": self.aria},
        )
        self.bran = _insert_npc(connection, self.world_id, "Ser Bran")
        self.cora = _insert_npc(connection, self.world_id, "Cora Hidden")
        self.dax = _insert_npc(connection, self.world_id, "Dax Draft", canon="draft")
        self.eld = _insert_npc(connection, self.world_id, "Eld Discoverable")
        self.guild = make_organization(connection, self.world_id, name="Silver Guild")
        self.order = make_organization(connection, self.world_id, name="Secret Order")
        self.keep = make_location(connection, self.world_id, name="The Keep")
        self.foreign_world_id = make_world(connection, slug=f"{slug}-foreign")
        self.foreign_char = make_character(connection, self.foreign_world_id, name="Stranger")

        def rel(kind_type: str, **kw: Any) -> uuid.UUID:
            return make_relationship(
                connection, self.world_id, relationship_type_code=kind_type, **kw
            )

        def part(r: uuid.UUID, entity: uuid.UUID, role: str, **kw: Any) -> None:
            make_relationship_participant(connection, r, entity, role_code=role, **kw)

        # Aria (child) / Ser Bran (parent): family, dated, with a recorded timeline status.
        self.family = rel("family", description=DESCRIPTION, started_world_time_id=self.wt[100])
        make_family_relationship(connection, self.family, family_unit_name="House Vale")
        part(self.family, self.aria, "child", notes=NOTES)
        part(self.family, self.bran, "parent")
        make_relationship_state(
            connection,
            self.timeline_id,
            self.family,
            status_code="active",
            emotional_tone=TONE,
            private_interpretation=INTERPRETATION,
        )
        make_relationship_perspective(
            connection,
            self.family,
            self.bran,
            emotional_tone=PERSPECTIVE_TONE,
            private_interpretation=PERSPECTIVE_INTERPRETATION,
        )

        # Symmetric alliance with Bran; treaty terms are GM_ONLY.
        self.alliance = rel("alliance", description=DESCRIPTION)
        make_political_relationship(connection, self.alliance, is_active=False, treaty_terms=TREATY)
        part(self.alliance, self.aria, "ally")
        part(self.alliance, self.bran, "ally")

        # Excluded edges.
        self.with_cora = rel("alliance")
        make_political_relationship(connection, self.with_cora)
        part(self.with_cora, self.aria, "ally")
        part(self.with_cora, self.cora, "ally")
        self.with_dax = rel("alliance")
        make_political_relationship(connection, self.with_dax)
        part(self.with_dax, self.aria, "ally")
        part(self.with_dax, self.dax, "ally")
        self.archived = rel("alliance")
        make_political_relationship(connection, self.archived)
        part(self.archived, self.aria, "ally")
        part(self.archived, self.bran, "ally")
        connection.execute(
            text(
                "UPDATE world.relationships SET lifecycle_status_id = (SELECT lifecycle_status_id "
                "FROM core.lifecycle_statuses WHERE code = 'archived') WHERE relationship_id = :r"
            ),
            {"r": self.archived},
        )
        self.private_ownership = rel("ownership")
        make_ownership_relationship(
            connection, self.private_ownership, self.aria, self.keep, is_public=False
        )
        part(self.private_ownership, self.aria, "owner")
        part(self.private_ownership, self.keep, "property")
        self.private_membership = rel("membership")
        make_organization_membership(
            connection,
            self.private_membership,
            self.order,
            self.aria,
            self.wt[100],
            is_public=False,
        )
        part(self.private_membership, self.aria, "member")
        part(self.private_membership, self.order, "organization")
        # A concealed route between two places: only editors see it. A route cannot involve a
        # character, so it is checked against the shared reader predicate on the World list.
        self.hall = make_location(connection, self.world_id, name="The Hall")
        self.hidden_route = rel("route")
        part(self.hidden_route, self.keep, "origin")
        part(self.hidden_route, self.hall, "destination")
        connection.execute(
            text(
                "INSERT INTO world.route_relationships (relationship_id, is_hidden) "
                "VALUES (:r, true)"
            ),
            {"r": self.hidden_route},
        )

        # Included edges.
        self.public_ownership = rel("ownership")
        make_ownership_relationship(
            connection, self.public_ownership, self.aria, self.keep, ownership_share=40
        )
        part(self.public_ownership, self.aria, "owner")
        part(self.public_ownership, self.keep, "property")
        self.membership = rel("membership", started_world_time_id=self.wt[100])
        make_organization_membership(
            connection,
            self.membership,
            self.guild,
            self.aria,
            self.wt[100],
            role="Scout",
            rank="Lieutenant",
        )
        part(self.membership, self.aria, "member")
        part(self.membership, self.guild, "organization")
        # Ended: Eld employed Aria; the discover-only counterpart is a name, not a link.
        self.employment = rel(
            "employment",
            started_world_time_id=self.wt[100],
            ended_world_time_id=self.wt[300],
        )
        make_employment_relationship(
            connection, self.employment, self.eld, self.aria, job_title="Scribe"
        )
        part(self.employment, self.aria, "employee")
        part(self.employment, self.eld, "employer")
        # Not started yet on the primary clock (700): begins at 900.
        self.future = rel("worship", started_world_time_id=self.wt[900])
        part(self.future, self.aria, "subject")
        part(self.future, self.guild, "object")
        # Ends at 600: ended on the primary clock (700), still in effect on the branch (500).
        self.ends_600 = rel(
            "parent_of", started_world_time_id=self.wt[100], ended_world_time_id=self.wt[600]
        )
        part(self.ends_600, self.aria, "object")
        part(self.ends_600, self.bran, "subject")

        view = lookup_id(connection, "security", "capabilities", "capability_id", "campaign.view")
        canon = lookup_id(connection, "security", "capabilities", "capability_id", "canon.edit")
        cap = {
            c: lookup_id(connection, "security", "capabilities", "capability_id", f"character.{c}")
            for c in ("discover", "view_summary", "view_full")
        }

        self.player_user_id = make_user(connection, "Reader Player")
        self.player_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.player_user_id
        )
        self.branch_player_membership_id = make_campaign_membership(
            connection, self.branch_campaign_id, self.player_user_id
        )
        self.gm_user_id = make_user(connection, "Reader GM")
        gm_membership = make_campaign_membership(connection, self.campaign_id, self.gm_user_id)
        for membership, campaign in (
            (self.player_membership_id, self.campaign_id),
            (self.branch_player_membership_id, self.branch_campaign_id),
        ):
            role = make_role(connection, campaign_id=campaign, code=f"p_{uuid.uuid4().hex[:8]}")
            make_role_capability(connection, role, view)
            make_membership_role(connection, membership, role)
        gm_role = make_role(
            connection, campaign_id=self.campaign_id, code=f"gm_{uuid.uuid4().hex[:8]}"
        )
        for capability in (view, canon):
            make_role_capability(connection, gm_role, capability)
        make_membership_role(connection, gm_membership, gm_role)

        self.types: list[uuid.UUID] = []

        def kind(*caps: str) -> uuid.UUID:
            t = make_character_relationship_type(connection)
            self.types.append(t)
            for c in caps:
                make_relationship_type_capability(connection, t, cap[c])
            return t

        own = kind("discover", "view_summary", "view_full")
        summary = kind("discover", "view_summary")
        discover_only = kind("discover")
        for membership, timeline in (
            (self.player_membership_id, self.timeline_id),
            (self.branch_player_membership_id, self.branch_timeline_id),
        ):
            for character, rtype in (
                (self.aria, own),
                (self.bran, summary),
                (self.eld, discover_only),
            ):
                make_membership_character_relationship(
                    connection, membership, character, rtype, timeline_id=timeline
                )
        # A player with no relationship to Aria at all.
        self.stranger_user_id = make_user(connection, "Reader Stranger")
        stranger_membership = make_campaign_membership(
            connection, self.campaign_id, self.stranger_user_id
        )
        stranger_role = make_role(
            connection, campaign_id=self.campaign_id, code=f"s_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, stranger_role, view)
        make_membership_role(connection, stranger_membership, stranger_role)
        self.stranger_membership_id = stranger_membership
        self.capless_user_id = make_user(connection, "Reader Capless")
        make_campaign_membership(connection, self.campaign_id, self.capless_user_id)
        self.outsider_user_id = make_user(connection, "Reader Outsider")


_CLEANUP = [
    "DELETE FROM campaign.relationship_state WHERE timeline_id IN "
    "(SELECT timeline_id FROM campaign.timelines WHERE world_id = :w)",
    "DELETE FROM world.relationship_perspectives WHERE relationship_id IN "
    "(SELECT relationship_id FROM world.relationships WHERE world_id = :w)",
    "DELETE FROM world.family_relationships WHERE relationship_id IN "
    "(SELECT relationship_id FROM world.relationships WHERE world_id = :w)",
    "DELETE FROM world.political_relationships WHERE relationship_id IN "
    "(SELECT relationship_id FROM world.relationships WHERE world_id = :w)",
    "DELETE FROM world.ownership_relationships WHERE relationship_id IN "
    "(SELECT relationship_id FROM world.relationships WHERE world_id = :w)",
    "DELETE FROM world.employment_relationships WHERE relationship_id IN "
    "(SELECT relationship_id FROM world.relationships WHERE world_id = :w)",
    "DELETE FROM world.organization_memberships WHERE relationship_id IN "
    "(SELECT relationship_id FROM world.relationships WHERE world_id = :w)",
    "DELETE FROM world.route_relationships WHERE relationship_id IN "
    "(SELECT relationship_id FROM world.relationships WHERE world_id = :w)",
    "DELETE FROM world.relationship_participants WHERE relationship_id IN "
    "(SELECT relationship_id FROM world.relationships WHERE world_id = :w)",
    "DELETE FROM world.relationships WHERE world_id = :w",
    "DELETE FROM campaign.timeline_clocks WHERE timeline_id IN "
    "(SELECT timeline_id FROM campaign.timelines WHERE world_id = :w)",
    "DELETE FROM security.membership_character_relationships WHERE campaign_membership_id IN "
    "(SELECT campaign_membership_id FROM security.campaign_memberships WHERE campaign_id IN "
    "(SELECT campaign_id FROM campaign.campaigns WHERE timeline_id IN "
    "(SELECT timeline_id FROM campaign.timelines WHERE world_id = :w)))",
    "DELETE FROM security.membership_roles WHERE role_id IN (SELECT role_id FROM security.roles "
    "WHERE campaign_id IN (SELECT campaign_id FROM campaign.campaigns WHERE timeline_id IN "
    "(SELECT timeline_id FROM campaign.timelines WHERE world_id = :w)))",
    "DELETE FROM security.role_capabilities WHERE role_id IN (SELECT role_id FROM security.roles "
    "WHERE campaign_id IN (SELECT campaign_id FROM campaign.campaigns WHERE timeline_id IN "
    "(SELECT timeline_id FROM campaign.timelines WHERE world_id = :w)))",
    "DELETE FROM security.roles WHERE campaign_id IN (SELECT campaign_id FROM campaign.campaigns "
    "WHERE timeline_id IN (SELECT timeline_id FROM campaign.timelines WHERE world_id = :w))",
    "DELETE FROM security.resource_grants WHERE campaign_id IN (SELECT campaign_id FROM "
    "campaign.campaigns WHERE timeline_id IN (SELECT timeline_id FROM campaign.timelines "
    "WHERE world_id = :w))",
    "DELETE FROM security.campaign_memberships WHERE campaign_id IN (SELECT campaign_id FROM "
    "campaign.campaigns WHERE timeline_id IN (SELECT timeline_id FROM campaign.timelines "
    "WHERE world_id = :w))",
    "DELETE FROM campaign.campaigns WHERE timeline_id IN (SELECT timeline_id FROM "
    "campaign.timelines WHERE world_id = :w)",
    "DELETE FROM campaign.timelines WHERE parent_timeline_id IS NOT NULL AND world_id = :w",
    "DELETE FROM campaign.timelines WHERE world_id = :w",
    "DELETE FROM core.entities WHERE world_id = :w",
    "DELETE FROM core.world_times WHERE world_id = :w",
    "DELETE FROM core.worlds WHERE world_id = :w",
]


@pytest.fixture
def f(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as connection:
        fixture = Fixture(connection, f"char-rel-reader-{uuid.uuid4().hex[:8]}")
    yield fixture
    with postgres_engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        for stmt in _CLEANUP:
            cleanup.execute(text(stmt), {"w": fixture.world_id})
        cleanup.execute(
            text("DELETE FROM core.entities WHERE world_id = :w"), {"w": fixture.foreign_world_id}
        )
        cleanup.execute(
            text("DELETE FROM core.worlds WHERE world_id = :w"), {"w": fixture.foreign_world_id}
        )
        cleanup.execute(
            text(
                "DELETE FROM security.character_relationship_type_capabilities WHERE "
                "character_relationship_type_id = ANY(:t)"
            ),
            {"t": fixture.types},
        )
        cleanup.execute(
            text(
                "DELETE FROM security.character_relationship_types WHERE "
                "character_relationship_type_id = ANY(:t)"
            ),
            {"t": fixture.types},
        )
        cleanup.execute(
            text("DELETE FROM security.users WHERE user_id = ANY(:u)"),
            {
                "u": [
                    fixture.player_user_id,
                    fixture.gm_user_id,
                    fixture.stranger_user_id,
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


def _url(f: Fixture, character_id: uuid.UUID, campaign_id: uuid.UUID | None = None) -> str:
    return f"/campaigns/{campaign_id or f.campaign_id}/characters/{character_id}/relationships"


def _ids(body: dict[str, Any]) -> set[str]:
    return {item["relationship_id"] for item in body["items"]}


def _item(body: dict[str, Any], relationship_id: uuid.UUID) -> dict[str, Any]:
    (found,) = [i for i in body["items"] if i["relationship_id"] == str(relationship_id)]
    return found


def _player_body(client_factory: Callable[[uuid.UUID], TestClient], f: Fixture) -> dict[str, Any]:
    with client_factory(f.player_user_id) as client:
        response = client.get(_url(f, f.aria))
    assert response.status_code == 200, response.text
    return response.json()


def test_an_authorized_player_sees_a_qualifying_relationship_with_names_and_roles(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    body = _player_body(client_factory, f)
    family = _item(body, f.family)
    assert family["kind"] == "family"
    assert family["relationship_type_label"]
    assert family["symmetric"] is False
    by_name = {p["name"]: p for p in family["participants"]}
    assert set(by_name) == {"Aria", "Ser Bran"}
    assert by_name["Aria"]["is_self"] is True and by_name["Aria"]["role"] == "child"
    assert by_name["Aria"]["can_open"] is False
    assert by_name["Ser Bran"]["is_self"] is False and by_name["Ser Bran"]["role"] == "parent"
    assert by_name["Ser Bran"]["role_label"] == "Parent"
    # Bran is openable because the player holds a summary-tier path to him.
    assert by_name["Ser Bran"]["can_open"] is True
    assert by_name["Ser Bran"]["category"] == "character"
    assert family["details"]["family_unit_name"] == "House Vale"
    assert family["current_status_label"]
    assert body["character_id"] == str(f.aria)


def test_only_visible_edges_are_listed_and_nothing_hints_at_hidden_ones(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    body = _player_body(client_factory, f)
    assert _ids(body) == {
        str(r)
        for r in (
            f.family,
            f.alliance,
            f.public_ownership,
            f.membership,
            f.employment,
            f.future,
            f.ends_600,
        )
    }
    text_body = str(body)
    for hidden in ("Cora Hidden", "Dax Draft", "Secret Order", str(f.cora), str(f.dax)):
        assert hidden not in text_body
    assert set(body) == {"character_id", "as_of", "truncated", "items"}
    assert body["truncated"] is False


def test_no_qualifying_relationships_is_an_empty_list(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with postgres_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE world.relationships SET lifecycle_status_id = (SELECT lifecycle_status_id "
                "FROM core.lifecycle_statuses WHERE code = 'archived') WHERE world_id = :w"
            ),
            {"w": f.world_id},
        )
    body = _player_body(client_factory, f)
    assert body["items"] == []


def test_an_undiscoverable_or_draft_counterpart_suppresses_the_whole_edge(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    body = _player_body(client_factory, f)
    assert str(f.with_cora) not in _ids(body)
    assert str(f.with_dax) not in _ids(body)
    # The reader view is the same for a caller who can edit canon: drafts stay hidden.
    with client_factory(f.gm_user_id) as client:
        gm = client.get(_url(f, f.aria)).json()
    assert str(f.with_dax) not in _ids(gm)
    assert str(f.archived) not in _ids(gm)
    assert str(f.private_ownership) not in _ids(gm)


def test_archived_private_and_hidden_edges_are_excluded(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    ids = _ids(_player_body(client_factory, f))
    for hidden in (f.archived, f.private_ownership, f.private_membership):
        assert str(hidden) not in ids


def test_ended_and_not_started_edges_are_returned_and_labelled(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    body = _player_body(client_factory, f)
    ended = _item(body, f.employment)
    assert ended["period_status"] == "ended"
    assert ended["ended_at"] is not None and ended["started"] is not None
    assert ended["details"]["job_title"] == "Scribe"
    assert _item(body, f.future)["period_status"] == "not_started"
    assert _item(body, f.family)["period_status"] == "in_effect"
    assert _item(body, f.public_ownership)["period_status"] == "undated"
    assert body["as_of"] is not None


def test_a_discover_only_counterpart_is_a_name_without_a_link(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    employer = next(
        p
        for p in _item(_player_body(client_factory, f), f.employment)["participants"]
        if p["role"] == "employer"
    )
    assert employer["name"] == "Eld Discoverable"
    assert employer["can_open"] is False


def test_typed_fields_are_the_campaign_visible_ones(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    body = _player_body(client_factory, f)
    membership = _item(body, f.membership)
    assert membership["details"]["office"] == "Scout"
    assert membership["details"]["rank"] == "Lieutenant"
    assert _item(body, f.public_ownership)["details"]["ownership_share"] == 40
    guild = next(p for p in membership["participants"] if p["role"] == "organization")
    assert guild["can_open"] is True and guild["category"] == "organization"
    alliance = _item(body, f.alliance)
    assert alliance["details"]["in_force"] is False


def test_symmetric_types_report_symmetry_and_equal_roles(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    alliance = _item(_player_body(client_factory, f), f.alliance)
    assert alliance["symmetric"] is True
    assert {p["role"] for p in alliance["participants"]} == {"ally"}


def test_orientation_is_per_viewed_character(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.player_user_id) as client:
        from_aria = client.get(_url(f, f.aria)).json()
        from_bran = client.get(_url(f, f.bran)).json()
    aria_side = _item(from_aria, f.family)
    bran_side = _item(from_bran, f.family)
    assert {p["name"]: p["is_self"] for p in aria_side["participants"]} == {
        "Aria": True,
        "Ser Bran": False,
    }
    assert {p["name"]: p["is_self"] for p in bran_side["participants"]} == {
        "Aria": False,
        "Ser Bran": True,
    }
    # Roles belong to the participants, not to a side: the same pairing both ways.
    assert {p["name"]: p["role"] for p in bran_side["participants"]} == {
        "Aria": "child",
        "Ser Bran": "parent",
    }


@pytest.mark.parametrize("sentinel", SENTINELS)
def test_no_gm_only_value_appears_anywhere_in_the_response(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, sentinel: str
) -> None:
    with client_factory(f.player_user_id) as client:
        player = client.get(_url(f, f.aria)).text
    with client_factory(f.gm_user_id) as client:
        gm = client.get(_url(f, f.aria)).text
    assert sentinel not in player
    assert sentinel not in gm
    for forbidden in (
        "description",
        "treaty_terms",
        "notes",
        "perspective",
        "private_interpretation",
        "emotional_tone",
        "lifecycle",
        "row_version",
        "is_public",
        "is_hidden",
    ):
        assert forbidden not in player


def test_the_period_follows_the_inherited_clock_on_a_branch_and_status_is_exact_timeline(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.player_user_id) as client:
        primary = client.get(_url(f, f.aria)).json()
        branch = client.get(_url(f, f.aria, f.branch_campaign_id)).json()
    assert _item(primary, f.ends_600)["period_status"] == "ended"
    # The branch was cut at 500, before the relationship ends.
    assert _item(branch, f.ends_600)["period_status"] == "in_effect"
    assert _item(primary, f.family)["current_status_label"]
    assert _item(branch, f.family)["current_status_label"] is None


def test_an_unset_clock_leaves_dated_edges_unplaced(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with postgres_engine.begin() as connection:
        connection.execute(
            text("DELETE FROM campaign.timeline_clocks WHERE timeline_id = :t"),
            {"t": f.timeline_id},
        )
    body = _player_body(client_factory, f)
    assert body["as_of"] is None
    assert _item(body, f.family)["period_status"] == "clock_unset"
    assert _item(body, f.public_ownership)["period_status"] == "undated"


def test_the_gate_is_the_character_pages_gate(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    def status(user: uuid.UUID, character: uuid.UUID, campaign: uuid.UUID | None = None) -> int:
        with client_factory(user) as client:
            return client.get(_url(f, character, campaign)).status_code

    assert status(f.outsider_user_id, f.aria) == 404
    assert status(f.capless_user_id, f.aria) == 403
    # No character-view capability at all: the same 404 as a nonexistent character.
    with client_factory(f.stranger_user_id) as client:
        no_tier = client.get(_url(f, f.aria))
        missing = client.get(_url(f, uuid.uuid4()))
    assert no_tier.status_code == 404
    bodies = [r.json() for r in (no_tier, missing)]
    for body in bodies:
        body["error"].pop("correlation_id")
    assert bodies[0] == bodies[1]
    assert status(f.player_user_id, f.foreign_char) == 404
    assert status(f.player_user_id, f.dax) == 404
    assert status(f.player_user_id, f.cora) == 404
    # An entity-targeted campaign.view deny removes the character entirely.
    with postgres_engine.begin() as connection:
        make_resource_grant(
            connection,
            f.campaign_id,
            lookup_id(connection, "security", "capabilities", "capability_id", "campaign.view"),
            grantee_campaign_membership_id=f.player_membership_id,
            entity_id=f.aria,
            effect="deny",
        )
    assert status(f.player_user_id, f.aria) == 404


def test_the_reader_route_is_independent_of_party_and_perspective_headers(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.player_user_id) as client:
        plain = client.get(_url(f, f.aria)).json()
        noisy = client.get(
            _url(f, f.aria) + f"?party_id={uuid.uuid4()}&perspective_character_id={uuid.uuid4()}",
            headers={"X-Party-Id": str(uuid.uuid4())},
        ).json()
    assert plain == noisy


def test_the_ids_match_the_existing_world_relationship_list_for_the_same_caller(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.player_user_id) as client:
        mine = client.get(_url(f, f.aria)).json()
        world = client.get(
            f"/campaigns/{f.campaign_id}/world/relationships?related_entity_id={f.aria}&limit=100"
        ).json()
    assert _ids(mine) == {item["relationship_id"] for item in world["items"]}


def test_granting_a_summary_path_makes_a_new_counterpart_appear(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    assert str(f.with_cora) not in _ids(_player_body(client_factory, f))
    with postgres_engine.begin() as connection:
        make_resource_grant(
            connection,
            f.campaign_id,
            lookup_id(
                connection, "security", "capabilities", "capability_id", "character.discover"
            ),
            grantee_campaign_membership_id=f.player_membership_id,
            character_id=f.cora,
        )
    body = _player_body(client_factory, f)
    item = _item(body, f.with_cora)
    cora = next(p for p in item["participants"] if p["name"] == "Cora Hidden")
    assert cora["can_open"] is False


def test_a_concealed_route_is_hidden_by_the_shared_reader_predicate(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    def route_ids(user: uuid.UUID) -> set[str]:
        with client_factory(user) as client:
            body = client.get(
                f"/campaigns/{f.campaign_id}/world/relationships?related_entity_id={f.keep}"
                "&limit=100"
            ).json()
        return {item["relationship_id"] for item in body["items"]}

    assert str(f.hidden_route) not in route_ids(f.player_user_id)
    assert str(f.hidden_route) in route_ids(f.gm_user_id)
