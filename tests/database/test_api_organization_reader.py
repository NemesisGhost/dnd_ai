"""The player's view of an organization: the detail's reader-entitled fields and the roster read.

    GET /campaigns/{id}/world/organizations/{organization_id}
    GET /campaigns/{id}/organizations/{organization_id}/members

Covers what a `campaign.view` reader (no `canon.edit`) receives: the founding, dissolution and
`PUBLIC_WORLD` subtype text on the detail; only active, public memberships of discoverable members on
the roster, current and ended, with `period_status` against the caller's own timeline clock (`as_of`)
and a server-decided `can_open`; that a withheld membership leaves no trace in the body (so an office
whose holder is withheld is absent, never reported vacant); that the organization type grants
nothing; the direct-API gates; and that an editor's roster keeps every stint and field.
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
    make_business,
    make_campaign,
    make_campaign_membership,
    make_character,
    make_character_relationship_type,
    make_government,
    make_membership_character_relationship,
    make_membership_role,
    make_organization,
    make_organization_membership,
    make_political_faction,
    make_relationship,
    make_relationship_participant,
    make_relationship_type_capability,
    make_resource_grant,
    make_role,
    make_role_capability,
    make_timeline,
    make_user,
    make_world,
    make_world_role_assignment,
    make_world_time,
    oidc_principal,
)

pytestmark = pytest.mark.database

INTERNAL = "SENTINEL-council-internal-notes"
HIDDEN_OFFICE = "SENTINEL-archivist-office"
PRIVATE_OFFICE = "SENTINEL-spy-office"
DRAFT_OFFICE = "SENTINEL-draft-envoy"
ARCHIVED_OFFICE = "SENTINEL-archived-stint"
BUSINESS_TYPE = "SENTINEL-business-type"


def _set_status(
    connection: Connection, table: str, column: str, row_id: uuid.UUID, code: str
) -> None:
    lookup = "canon_statuses" if column == "canon_status_id" else "lifecycle_statuses"
    connection.execute(
        text(
            f"UPDATE {table} SET {column} = (SELECT {column} FROM core.{lookup} WHERE code = :c) "
            f"WHERE {'relationship_id' if table == 'world.relationships' else 'entity_id'} = :i"
        ),
        {"c": code, "i": row_id},
    )


def _npc(connection: Connection, world_id: uuid.UUID, name: str) -> uuid.UUID:
    npc = make_character(connection, world_id, name=name, entity_type_code="npc")
    connection.execute(text("INSERT INTO character.npcs (npc_id) VALUES (:i)"), {"i": npc})
    return npc


class Fixture:
    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        self.wt = {
            k: make_world_time(connection, self.world_id, k) for k in (100, 500, 600, 700, 900)
        }
        # The primary clock reads 700; a branch cut at 500 inherits 500.
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
        self.bran = _npc(connection, self.world_id, "Ser Bran")
        self.eld = _npc(connection, self.world_id, "Eld Discoverable")
        self.cora = _npc(connection, self.world_id, "Cora Hidden")

        self.council = make_organization(
            connection,
            self.world_id,
            organization_type_code="government",
            name="R Council",
            founded_world_time_id=self.wt[100],
            public_description="Public council",
            internal_description=INTERNAL,
        )
        make_government(connection, self.council, government_form="Elected senate")
        self.faction = make_organization(
            connection, self.world_id, organization_type_code="political_faction", name="Greens"
        )
        make_political_faction(connection, self.faction, ideology="Land for all")
        self.shop = make_organization(
            connection,
            self.world_id,
            organization_type_code="business",
            name="Shop",
            founded_world_time_id=self.wt[100],
            dissolved_world_time_id=self.wt[600],
        )
        make_business(connection, self.shop, business_type=BUSINESS_TYPE, reputation=-77)
        self.guild = make_organization(connection, self.world_id, name="Silver Guild")
        self.draft_org = make_organization(connection, self.world_id, name="Draft Lodge")
        _set_status(connection, "core.entities", "canon_status_id", self.draft_org, "draft")
        self.archived_org = make_organization(connection, self.world_id, name="Old Lodge")
        _set_status(
            connection, "core.entities", "lifecycle_status_id", self.archived_org, "archived"
        )
        self.lapsed_org = make_organization(connection, self.world_id, name="Lapsed Lodge")
        # Same rule whatever the type: a "Public Council" government grants nothing extra.
        self.public_council = make_organization(
            connection, self.world_id, organization_type_code="government", name="Public Council"
        )
        make_government(connection, self.public_council)

        def stint(
            org: uuid.UUID,
            member: uuid.UUID,
            start: int,
            *,
            end: int | None = None,
            archived: bool = False,
            **typed: Any,
        ) -> uuid.UUID:
            r = make_relationship(
                connection,
                self.world_id,
                relationship_type_code="membership",
                started_world_time_id=self.wt[start],
                ended_world_time_id=None if end is None else self.wt[end],
            )
            make_organization_membership(
                connection,
                r,
                org,
                member,
                self.wt[start],
                effective_to_world_time_id=None if end is None else self.wt[end],
                **typed,
            )
            make_relationship_participant(connection, r, member, role_code="member")
            make_relationship_participant(connection, r, org, role_code="organization")
            if archived:
                _set_status(connection, "world.relationships", "lifecycle_status_id", r, "archived")
            return r

        self.speaker = stint(self.council, self.aria, 100, role="Speaker", rank="First seat")
        # Ended on the primary clock (700); still in effect on the branch (500).
        self.treasurer = stint(self.council, self.bran, 100, end=600, role="Treasurer")
        self.spy = stint(self.council, self.bran, 600, role=PRIVATE_OFFICE, is_public=False)
        # Not started on either clock; a discover-only member is a name, not a link.
        self.envoy = stint(self.council, self.eld, 900, role="Envoy")
        self.archivist = stint(self.council, self.cora, 100, role=HIDDEN_OFFICE)
        self.guild_seat = stint(self.council, self.guild, 100)
        self.draft_seat = stint(self.council, self.draft_org, 100, role=DRAFT_OFFICE)
        self.old_seat = stint(self.council, self.archived_org, 100, role="Founder")
        self.lapsed_seat = stint(
            self.council, self.lapsed_org, 100, role=ARCHIVED_OFFICE, archived=True
        )
        self.public_council_seat = stint(self.public_council, self.cora, 100, role=HIDDEN_OFFICE)

        view = lookup_id(connection, "security", "capabilities", "capability_id", "campaign.view")
        canon = lookup_id(connection, "security", "capabilities", "capability_id", "canon.edit")
        cap = {
            c: lookup_id(connection, "security", "capabilities", "capability_id", f"character.{c}")
            for c in ("discover", "view_summary", "view_full")
        }

        def member(campaign: uuid.UUID, user: uuid.UUID, *caps: uuid.UUID) -> uuid.UUID:
            membership = make_campaign_membership(connection, campaign, user)
            role = make_role(connection, campaign_id=campaign, code=f"r_{uuid.uuid4().hex[:8]}")
            for c in caps:
                make_role_capability(connection, role, c)
            make_membership_role(connection, membership, role)
            return membership

        self.player_user_id = make_user(connection, "Org Reader Player")
        self.player_membership_id = member(self.campaign_id, self.player_user_id, view)
        branch_membership = member(self.branch_campaign_id, self.player_user_id, view)
        self.gm_user_id = make_user(connection, "Org Reader GM")
        member(self.campaign_id, self.gm_user_id, view, canon)
        # Unpublished definitions are shared world canon: previewing them takes the world's
        # private-read capability as well as campaign `canon.edit` (ADR 0020). This GM also edits
        # members, so is given the world Editor role.
        make_world_role_assignment(connection, self.world_id, self.gm_user_id, "world_editor")
        self.stranger_user_id = make_user(connection, "Org Reader Stranger")
        member(self.campaign_id, self.stranger_user_id, view)
        self.capless_user_id = make_user(connection, "Org Reader Capless")
        make_campaign_membership(connection, self.campaign_id, self.capless_user_id)
        self.outsider_user_id = make_user(connection, "Org Reader Outsider")

        self.types: list[uuid.UUID] = []

        def kind(*caps: str) -> uuid.UUID:
            t = make_character_relationship_type(connection)
            self.types.append(t)
            for c in caps:
                make_relationship_type_capability(connection, t, cap[c])
            return t

        own, summary, discover_only = (
            kind("discover", "view_summary", "view_full"),
            kind("discover", "view_summary"),
            kind("discover"),
        )
        for membership, timeline in (
            (self.player_membership_id, self.timeline_id),
            (branch_membership, self.branch_timeline_id),
        ):
            for character, rtype in (
                (self.aria, own),
                (self.bran, summary),
                (self.eld, discover_only),
            ):
                make_membership_character_relationship(
                    connection, membership, character, rtype, timeline_id=timeline
                )

    @property
    def users(self) -> list[uuid.UUID]:
        return [
            self.player_user_id,
            self.gm_user_id,
            self.stranger_user_id,
            self.capless_user_id,
            self.outsider_user_id,
        ]


_IN_WORLD_CAMPAIGNS = (
    "SELECT campaign_id FROM campaign.campaigns WHERE timeline_id IN "
    "(SELECT timeline_id FROM campaign.timelines WHERE world_id = :w)"
)
_IN_WORLD_RELATIONSHIPS = "SELECT relationship_id FROM world.relationships WHERE world_id = :w"
_IN_WORLD_ENTITIES = "SELECT entity_id FROM core.entities WHERE world_id = :w"
_CLEANUP = [
    f"DELETE FROM world.organization_memberships WHERE relationship_id IN ({_IN_WORLD_RELATIONSHIPS})",
    f"DELETE FROM world.relationship_participants WHERE relationship_id IN ({_IN_WORLD_RELATIONSHIPS})",
    "DELETE FROM world.relationships WHERE world_id = :w",
    "DELETE FROM campaign.timeline_clocks WHERE timeline_id IN "
    "(SELECT timeline_id FROM campaign.timelines WHERE world_id = :w)",
    "DELETE FROM security.membership_character_relationships WHERE campaign_membership_id IN "
    f"(SELECT campaign_membership_id FROM security.campaign_memberships WHERE campaign_id IN "
    f"({_IN_WORLD_CAMPAIGNS}))",
    "DELETE FROM security.membership_roles WHERE role_id IN "
    f"(SELECT role_id FROM security.roles WHERE campaign_id IN ({_IN_WORLD_CAMPAIGNS}))",
    "DELETE FROM security.role_capabilities WHERE role_id IN "
    f"(SELECT role_id FROM security.roles WHERE campaign_id IN ({_IN_WORLD_CAMPAIGNS}))",
    f"DELETE FROM security.roles WHERE campaign_id IN ({_IN_WORLD_CAMPAIGNS})",
    f"DELETE FROM security.resource_grants WHERE campaign_id IN ({_IN_WORLD_CAMPAIGNS})",
    f"DELETE FROM security.campaign_memberships WHERE campaign_id IN ({_IN_WORLD_CAMPAIGNS})",
    f"DELETE FROM campaign.campaigns WHERE campaign_id IN ({_IN_WORLD_CAMPAIGNS})",
    "DELETE FROM campaign.timelines WHERE parent_timeline_id IS NOT NULL AND world_id = :w",
    "DELETE FROM campaign.timelines WHERE world_id = :w",
    f"DELETE FROM world.governments WHERE government_id IN ({_IN_WORLD_ENTITIES})",
    f"DELETE FROM world.political_factions WHERE political_faction_id IN ({_IN_WORLD_ENTITIES})",
    f"DELETE FROM world.businesses WHERE business_id IN ({_IN_WORLD_ENTITIES})",
    f"DELETE FROM world.organizations WHERE organization_id IN ({_IN_WORLD_ENTITIES})",
    f"DELETE FROM character.npcs WHERE npc_id IN ({_IN_WORLD_ENTITIES})",
    f"DELETE FROM character.player_characters WHERE player_character_id IN ({_IN_WORLD_ENTITIES})",
    f"DELETE FROM character.characters WHERE character_id IN ({_IN_WORLD_ENTITIES})",
    "DELETE FROM core.entities WHERE world_id = :w",
    "DELETE FROM core.world_times WHERE world_id = :w",
    "DELETE FROM core.worlds WHERE world_id = :w",
]


@pytest.fixture
def f(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as connection:
        fixture = Fixture(connection, f"org-reader-{uuid.uuid4().hex[:8]}")
    yield fixture
    with postgres_engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        for stmt in _CLEANUP:
            cleanup.execute(text(stmt), {"w": fixture.world_id})
        for table, column in (
            ("security.character_relationship_type_capabilities", "character_relationship_type_id"),
            ("security.character_relationship_types", "character_relationship_type_id"),
        ):
            cleanup.execute(
                text(f"DELETE FROM {table} WHERE {column} = ANY(:t)"), {"t": fixture.types}
            )
        cleanup.execute(
            text("DELETE FROM security.users WHERE user_id = ANY(:u)"), {"u": fixture.users}
        )


@pytest.fixture
def client_factory(postgres_engine: Engine) -> Callable[[uuid.UUID], TestClient]:
    def _make(user_id: uuid.UUID) -> TestClient:
        app = create_app()
        app.dependency_overrides[get_engine] = lambda: postgres_engine
        app.dependency_overrides[get_authenticated_user_id] = lambda: oidc_principal(user_id)
        return TestClient(app, raise_server_exceptions=False)

    return _make


Client = Callable[[uuid.UUID], TestClient]


def _members_url(campaign_id: uuid.UUID, org: uuid.UUID) -> str:
    return f"/campaigns/{campaign_id}/organizations/{org}/members"


def _detail_url(campaign_id: uuid.UUID, org: uuid.UUID) -> str:
    return f"/campaigns/{campaign_id}/world/organizations/{org}"


def _get(client_factory: Client, user: uuid.UUID, url: str) -> Any:
    with client_factory(user) as client:
        return client.get(url)


def _roster(client_factory: Client, user: uuid.UUID, campaign_id: uuid.UUID, org: uuid.UUID) -> Any:
    response = _get(client_factory, user, _members_url(campaign_id, org))
    assert response.status_code == 200, response.text
    return response


def _by_relationship(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {m["relationship_id"]: m for m in body["members"]}


# ---------------------------------------------------------------------------
# Detail
# ---------------------------------------------------------------------------


def test_a_reader_gets_the_councils_public_details_and_never_its_notes(
    client_factory: Client, f: Fixture
) -> None:
    response = _get(client_factory, f.player_user_id, _detail_url(f.campaign_id, f.council))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["organization_type_code"] == "government"
    assert body["public_description"] == "Public council"
    assert body["government_form"] == "Elected senate"
    assert body["founded"] == "Year 1100" and body["dissolved"] is None
    assert body["ideology"] is None
    assert INTERNAL not in response.text and "internal_description" not in body
    # Times travel as display text only.
    assert str(f.wt[100]) not in response.text


def test_a_faction_carries_its_ideology_and_a_business_none_of_its_structural_fields(
    client_factory: Client, f: Fixture
) -> None:
    faction = _get(client_factory, f.player_user_id, _detail_url(f.campaign_id, f.faction)).json()
    assert faction["ideology"] == "Land for all" and faction["government_form"] is None
    shop = _get(client_factory, f.player_user_id, _detail_url(f.campaign_id, f.shop))
    assert shop.json()["dissolved"] == "Year 1600"
    for withheld in (BUSINESS_TYPE, "business_type", "reputation", "-77", "operating_status"):
        assert withheld not in shop.text


# ---------------------------------------------------------------------------
# Roster: who is listed
# ---------------------------------------------------------------------------


def test_a_reader_sees_public_active_discoverable_members_current_and_ended(
    client_factory: Client, f: Fixture
) -> None:
    body = _roster(client_factory, f.player_user_id, f.campaign_id, f.council).json()
    rows = _by_relationship(body)
    assert set(rows) == {
        str(r) for r in (f.speaker, f.treasurer, f.envoy, f.guild_seat, f.old_seat)
    }
    speaker = rows[str(f.speaker)]
    assert (speaker["member_name"], speaker["role"], speaker["rank"]) == (
        "Aria",
        "Speaker",
        "First seat",
    )
    # An organization member without an office is listed as such; an archived member stays listed.
    assert rows[str(f.guild_seat)]["role"] is None and rows[str(f.guild_seat)]["rank"] is None
    assert rows[str(f.old_seat)]["member_name"] == "Old Lodge"
    assert body["can_edit"] is False and body["status_choices"] == []


def test_withheld_memberships_leave_no_trace_in_the_reader_body(
    client_factory: Client, f: Fixture
) -> None:
    response = _roster(client_factory, f.player_user_id, f.campaign_id, f.council)
    for withheld in (
        # An undiscoverable member: its id, name and office (no "vacant" office is left behind).
        str(f.cora),
        "Cora Hidden",
        HIDDEN_OFFICE,
        str(f.archivist),
        # A private stint, an unpublished member, and an archived membership.
        PRIVATE_OFFICE,
        str(f.spy),
        str(f.draft_org),
        "Draft Lodge",
        DRAFT_OFFICE,
        str(f.lapsed_seat),
        "Lapsed Lodge",
        ARCHIVED_OFFICE,
    ):
        assert withheld not in response.text, withheld
    assert "vacan" not in response.text.lower()
    assert all(
        m["is_public"] and m["lifecycle_status"] == "active" for m in response.json()["members"]
    )


def test_the_organization_type_or_name_grants_no_visibility(
    client_factory: Client, f: Fixture
) -> None:
    # "Public Council" is a government whose only member is a public stint of a hidden NPC.
    reader = _roster(client_factory, f.player_user_id, f.campaign_id, f.public_council)
    assert reader.json()["members"] == [] and "Cora Hidden" not in reader.text
    gm = _roster(client_factory, f.gm_user_id, f.campaign_id, f.public_council).json()
    assert [m["member_name"] for m in gm["members"]] == ["Cora Hidden"]


def test_a_reader_with_no_character_relationships_sees_only_organization_members(
    client_factory: Client, f: Fixture
) -> None:
    body = _roster(client_factory, f.stranger_user_id, f.campaign_id, f.council).json()
    assert {m["member_name"] for m in body["members"]} == {"Silver Guild", "Old Lodge"}


def test_a_discover_grant_lists_a_member_without_making_it_a_link(
    client_factory: Client, f: Fixture, postgres_engine: Engine
) -> None:
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
    rows = _by_relationship(
        _roster(client_factory, f.player_user_id, f.campaign_id, f.council).json()
    )
    archivist = rows[str(f.archivist)]
    assert archivist["role"] == HIDDEN_OFFICE and archivist["can_open"] is False


# ---------------------------------------------------------------------------
# Roster: links and periods
# ---------------------------------------------------------------------------


def test_can_open_follows_the_character_view_tier_and_world_categories(
    client_factory: Client, f: Fixture
) -> None:
    rows = _by_relationship(
        _roster(client_factory, f.player_user_id, f.campaign_id, f.council).json()
    )
    opens = {m["member_name"]: m["can_open"] for m in rows.values()}
    assert opens == {
        "Aria": True,  # the player's own character (view_full)
        "Ser Bran": True,  # view_summary opens the character page
        "Eld Discoverable": False,  # discover only: a name, not a link
        "Silver Guild": True,
        "Old Lodge": True,
    }
    assert rows[str(f.speaker)]["category"] == "character"
    assert rows[str(f.guild_seat)]["category"] == "organization"


def test_period_status_and_as_of_follow_the_callers_timeline(
    client_factory: Client, f: Fixture
) -> None:
    primary = _roster(client_factory, f.player_user_id, f.campaign_id, f.council).json()
    branch = _roster(client_factory, f.player_user_id, f.branch_campaign_id, f.council).json()
    assert primary["as_of"] == "Year 1700" and branch["as_of"] == "Year 1500"

    def statuses(body: dict[str, Any]) -> dict[str, str]:
        rows = _by_relationship(body)
        return {
            name: rows[str(r)]["period_status"]
            for name, r in (("speaker", f.speaker), ("treasurer", f.treasurer), ("envoy", f.envoy))
        }

    assert statuses(primary) == {
        "speaker": "in_effect",
        "treasurer": "ended",
        "envoy": "not_started",
    }
    assert statuses(branch) == {
        "speaker": "in_effect",
        "treasurer": "in_effect",
        "envoy": "not_started",
    }
    # Memberships are world definitions: the branch lists the same rows, with its own clock.
    assert set(_by_relationship(primary)) == set(_by_relationship(branch))
    # The legacy flag stays as it was (no end recorded), independent of the clock.
    assert _by_relationship(primary)[str(f.envoy)]["current"] is True


def test_an_unset_clock_is_reported_rather_than_guessed(
    client_factory: Client, f: Fixture, postgres_engine: Engine
) -> None:
    with postgres_engine.begin() as connection:
        connection.execute(
            text("DELETE FROM campaign.timeline_clocks WHERE timeline_id = :t"),
            {"t": f.timeline_id},
        )
    body = _roster(client_factory, f.player_user_id, f.campaign_id, f.council).json()
    assert body["as_of"] is None
    assert {m["period_status"] for m in body["members"]} == {"clock_unset"}


# ---------------------------------------------------------------------------
# Direct API authorization
# ---------------------------------------------------------------------------


def test_the_reader_routes_are_gated_on_the_server(
    client_factory: Client, f: Fixture, postgres_engine: Engine
) -> None:
    for url in (_members_url(f.campaign_id, f.council), _detail_url(f.campaign_id, f.council)):
        assert _get(client_factory, f.outsider_user_id, url).status_code == 404
        assert _get(client_factory, f.capless_user_id, url).status_code == 403
    # An unpublished organization has no reader detail or roster; the editor still reads it.
    for url in (_members_url(f.campaign_id, f.draft_org), _detail_url(f.campaign_id, f.draft_org)):
        assert _get(client_factory, f.player_user_id, url).status_code == 404
        assert _get(client_factory, f.gm_user_id, url).status_code == 200
    # Party and perspective inputs do not change the reader's roster.
    with client_factory(f.player_user_id) as client:
        plain = client.get(_members_url(f.campaign_id, f.council)).json()
        noisy = client.get(
            _members_url(f.campaign_id, f.council)
            + f"?party_id={uuid.uuid4()}&perspective_character_id={f.cora}",
            headers={"X-Party-Id": str(uuid.uuid4())},
        ).json()
    assert plain == noisy
    # An entity-targeted campaign.view deny removes the organization from both routes.
    with postgres_engine.begin() as connection:
        make_resource_grant(
            connection,
            f.campaign_id,
            lookup_id(connection, "security", "capabilities", "capability_id", "campaign.view"),
            grantee_campaign_membership_id=f.player_membership_id,
            entity_id=f.council,
            effect="deny",
        )
    assert (
        _get(client_factory, f.player_user_id, _members_url(f.campaign_id, f.council)).status_code
        == 404
    )
    assert (
        _get(client_factory, f.player_user_id, _detail_url(f.campaign_id, f.council)).status_code
        == 404
    )


# ---------------------------------------------------------------------------
# Editor
# ---------------------------------------------------------------------------


def test_the_editor_roster_keeps_every_stint_and_field(client_factory: Client, f: Fixture) -> None:
    body = _roster(client_factory, f.gm_user_id, f.campaign_id, f.council).json()
    rows = _by_relationship(body)
    assert set(rows) == {
        str(r)
        for r in (
            f.speaker,
            f.treasurer,
            f.spy,
            f.envoy,
            f.archivist,
            f.guild_seat,
            f.draft_seat,
            f.old_seat,
            f.lapsed_seat,
        )
    }
    assert body["can_edit"] is True and body["status_choices"] != []
    assert rows[str(f.spy)]["is_public"] is False
    assert rows[str(f.lapsed_seat)]["lifecycle_status"] == "archived"
    assert set(rows[str(f.speaker)]) == {
        "relationship_id",
        "member_entity_id",
        "member_name",
        "member_type_code",
        "role",
        "rank",
        "is_public",
        "started",
        "ended",
        "current",
        "lifecycle_status",
        "row_version",
        "period_status",
        "category",
        "can_open",
    }
    gm_detail = _get(client_factory, f.gm_user_id, _detail_url(f.campaign_id, f.council)).json()
    assert gm_detail["government_form"] == "Elected senate"
