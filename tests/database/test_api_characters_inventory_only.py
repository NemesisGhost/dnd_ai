"""CP-6 / DR-2: `character.view_inventory` and the restricted `inventory_only` projection.

Runs under the real relationship policy with the seeded built-in relationship types (migration
114 + 139), not the permissive test relaxation. Everything is read from the serialized response
body, never the UI: the restricted rows must not merely hide a field, they must not carry it.
"""

import json
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, text

from dnd_ai.api.app import create_app
from dnd_ai.api.auth import get_authenticated_user_id
from dnd_ai.api.deps import get_connection
from tests.factories import (
    lookup_id,
    make_campaign,
    make_campaign_membership,
    make_character,
    make_inventory_entry,
    make_item_definition,
    make_item_identification,
    make_item_instance,
    make_item_ownership,
    make_item_state,
    make_membership_character_relationship,
    make_membership_role,
    make_resource_grant,
    make_ruleset_version_for_world,
    make_timeline,
    make_user,
    make_world,
    oidc_principal,
    system_role_id,
)

pytestmark = [pytest.mark.database, pytest.mark.real_relationship_policy]

_INVENTORY = "character.view_inventory"
_RESTRICTED_KEYS = {
    "item_instance_id",
    "name",
    "display_name",
    "item_category_code",
    "rarity",
    "quantity",
    "is_equipped",
    "is_destroyed",
    "ownership",
    "identification_level",
    "properties",
}
# Everything the full projection carries that the restricted one must not.
_WITHHELD_KEYS = {
    "condition_percentage",
    "charges_current",
    "charges_maximum",
    "owner_entity_id",
    "last_event_id",
    "origin_notes",
    "is_published",
}
_SECRET = "gm-only-secret-origin"


class World:
    def __init__(self, c: Connection) -> None:
        self.c = c
        self.world_id = make_world(c, slug=f"cp6-{uuid.uuid4().hex[:8]}")
        self.timeline_id = make_timeline(c, self.world_id, is_primary=True)
        self.campaign_id = make_campaign(c, self.timeline_id, lifecycle_status_code="pending")
        self.character_id = make_character(c, self.world_id, name="Aria")
        self.stranger_id = make_character(c, self.world_id, name="Stranger")
        ruleset = make_ruleset_version_for_world(c, self.world_id)

        plain = make_item_definition(
            c, ruleset, display_name="Longsword", rarity="common", item_category_code="weapon"
        )
        self.sword_id = make_item_instance(
            c, self.world_id, plain, name="Dawn", origin_notes=_SECRET
        )
        make_item_state(
            c,
            self.timeline_id,
            self.sword_id,
            quantity=1,
            condition_percentage=80,
            charges_current=2,
            charges_maximum=3,
            is_equipped=True,
        )
        make_item_ownership(c, self.timeline_id, self.sword_id, owner_entity_id=self.character_id)
        make_inventory_entry(c, self.timeline_id, self.sword_id, holder_entity_id=self.character_id)

        # Carried but owned by someone else: custody without ownership.
        self.loan_id = make_item_instance(c, self.world_id, plain, name="Borrowed Blade")
        make_item_state(c, self.timeline_id, self.loan_id, quantity=2, is_destroyed=True)
        make_item_ownership(c, self.timeline_id, self.loan_id, owner_entity_id=self.stranger_id)
        make_inventory_entry(c, self.timeline_id, self.loan_id, holder_entity_id=self.character_id)

        hidden = make_item_definition(
            c,
            ruleset,
            display_name="Ring of Mystery",
            rarity="rare",
            item_category_code="ring",
            properties={"curse": "binds permanently"},
        )
        self.ring_id = make_item_instance(c, self.world_id, hidden, name="A Ring")
        make_item_state(c, self.timeline_id, self.ring_id, quantity=1)
        make_inventory_entry(c, self.timeline_id, self.ring_id, holder_entity_id=self.character_id)

        known = make_item_definition(
            c,
            ruleset,
            display_name="Sunblade",
            rarity="very_rare",
            item_category_code="weapon",
            properties={"damage": "1d8 radiant", "secret": "x"},
        )
        self.known_id = make_item_instance(c, self.world_id, known, name="A Sunblade")
        make_item_state(c, self.timeline_id, self.known_id, quantity=1)
        make_inventory_entry(c, self.timeline_id, self.known_id, holder_entity_id=self.character_id)
        make_item_identification(
            c,
            self.timeline_id,
            self.known_id,
            self.character_id,
            identification_level="partially_identified",
            known_properties={"damage": "1d8 radiant"},
        )

        # Unpublished instances the restricted reader must never see.
        self.draft_id = make_item_instance(c, self.world_id, plain, name="Draft Dagger")
        self.archived_id = make_item_instance(c, self.world_id, plain, name="Archived Axe")
        for item_id, canon, lifecycle in (
            (self.draft_id, "draft", "active"),
            (self.archived_id, "canon", "archived"),
        ):
            make_item_state(c, self.timeline_id, item_id, quantity=1)
            make_inventory_entry(c, self.timeline_id, item_id, holder_entity_id=self.character_id)
            c.execute(
                text("""
                    UPDATE core.entities
                    SET canon_status_id = (SELECT canon_status_id FROM core.canon_statuses
                                           WHERE code = :canon),
                        lifecycle_status_id = (SELECT lifecycle_status_id
                                               FROM core.lifecycle_statuses WHERE code = :life)
                    WHERE entity_id = :id
                """),
                {"canon": canon, "life": lifecycle, "id": item_id},
            )

        # Another timeline of the same world: the same character carries something else there.
        self.branch_timeline_id = make_timeline(c, self.world_id, "Branch")

        self.memberships: dict[uuid.UUID, uuid.UUID] = {}
        self.gm = self.member("GM", "gm")

    def member(self, name: str, role: str = "player") -> uuid.UUID:
        user_id = make_user(self.c, name)
        membership_id = make_campaign_membership(self.c, self.campaign_id, user_id)
        make_membership_role(self.c, membership_id, system_role_id(self.c, role))
        self.memberships[user_id] = membership_id
        return user_id

    def relate(self, user_id: uuid.UUID, type_code: str, *, revoked: bool = False) -> None:
        type_id = lookup_id(
            self.c,
            "security",
            "character_relationship_types",
            "character_relationship_type_id",
            type_code,
        )
        make_membership_character_relationship(
            self.c,
            self.memberships[user_id],
            self.character_id,
            type_id,
            timeline_id=self.timeline_id,
            revoked=revoked,
        )

    def grant(self, user_id: uuid.UUID, capability: str, effect: str) -> None:
        make_resource_grant(
            self.c,
            self.campaign_id,
            lookup_id(self.c, "security", "capabilities", "capability_id", capability),
            character_id=self.character_id,
            grantee_campaign_membership_id=self.memberships[user_id],
            effect=effect,
        )

    def deny_entity_view(self, user_id: uuid.UUID) -> None:
        make_resource_grant(
            self.c,
            self.campaign_id,
            lookup_id(self.c, "security", "capabilities", "capability_id", "campaign.view"),
            entity_id=self.character_id,
            grantee_campaign_membership_id=self.memberships[user_id],
            effect="deny",
        )

    def url(self, suffix: str = "", character_id: uuid.UUID | None = None) -> str:
        return (
            f"/campaigns/{self.campaign_id}/characters/{character_id or self.character_id}{suffix}"
        )


@pytest.fixture
def w(db_connection: Connection) -> World:
    return World(db_connection)


@pytest.fixture
def client_for(db_connection: Connection) -> Iterator[Callable[[uuid.UUID], TestClient]]:
    clients: list[TestClient] = []

    def make(user_id: uuid.UUID) -> TestClient:
        app = create_app()
        app.dependency_overrides[get_connection] = lambda: db_connection
        app.dependency_overrides[get_authenticated_user_id] = lambda: oidc_principal(user_id)
        client = TestClient(app, raise_server_exceptions=False)
        client.__enter__()
        clients.append(client)
        return client

    yield make
    for client in clients:
        client.__exit__(None, None, None)


def _rows(body: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    return {str(row["item_instance_id"]): row for row in body}


# --- the relationship matrix -----------------------------------------------------------------


@pytest.mark.parametrize("type_code", ["viewer", "observer_approved_viewer"])
def test_viewer_types_read_the_restricted_inventory_and_nothing_more(
    w: World, client_for: Callable[[uuid.UUID], TestClient], type_code: str
) -> None:
    user = w.member("Reader")
    w.relate(user, type_code)
    client = client_for(user)

    response = client.get(w.url("/inventory"))
    assert response.status_code == 200, response.text
    body = response.json()
    rows = _rows(body)

    # Published, active items only: the draft and the archived instance are absent.
    assert set(rows) == {str(w.sword_id), str(w.loan_id), str(w.ring_id), str(w.known_id)}
    # Every row carries exactly the allowlist.
    assert all(set(row) == _RESTRICTED_KEYS for row in body)
    # The serialized text holds none of the withheld values, whatever the field is called.
    text_body = response.text
    assert _SECRET not in text_body
    assert "origin_notes" not in text_body
    for forbidden in _WITHHELD_KEYS:
        assert forbidden not in text_body

    sword = rows[str(w.sword_id)]
    assert (sword["name"], sword["display_name"], sword["quantity"]) == ("Dawn", "Longsword", 1)
    assert sword["is_equipped"] is True and sword["is_destroyed"] is False
    assert sword["ownership"] == "holder"
    loan = rows[str(w.loan_id)]
    assert loan["ownership"] == "other" and loan["is_destroyed"] is True and loan["quantity"] == 2
    assert str(w.stranger_id) not in text_body  # the other owner's id is not disclosed
    assert rows[str(w.ring_id)]["ownership"] == "none"

    # Identification filtering is unchanged: nothing for the unidentified ring, the known subset.
    assert rows[str(w.ring_id)]["properties"] is None
    assert rows[str(w.known_id)]["properties"] == {"damage": "1d8 radiant"}
    assert "binds permanently" not in text_body and "secret" not in text_body

    # Not the full sheet, no controlling perspective, no GM-only surfaces.
    assert client.get(w.url("/sheet")).status_code == 404
    detail = client.get(w.url()).json()
    assert detail["sections"] == {
        "details": True,
        "sheet": False,
        "relationships": True,
        "inventory": True,
        "parties": False,
    }
    assert client.get(w.url("/parties")).status_code in (403, 404)


def test_former_controller_and_a_bare_summary_reader_get_no_inventory(
    w: World, client_for: Callable[[uuid.UUID], TestClient]
) -> None:
    former = w.member("Former")
    w.relate(former, "former_controller")
    assert client_for(former).get(w.url("/inventory")).status_code == 404

    revoked = w.member("Revoked")
    w.relate(revoked, "viewer", revoked=True)
    assert client_for(revoked).get(w.url("/inventory")).status_code == 404

    unrelated = w.member("Unrelated")
    assert client_for(unrelated).get(w.url("/inventory")).status_code == 404


@pytest.mark.parametrize("type_code", ["owner", "primary_controller", "co_controller", "portrayer"])
def test_controlling_types_keep_the_full_projection(
    w: World, client_for: Callable[[uuid.UUID], TestClient], type_code: str
) -> None:
    user = w.member("Controller")
    w.relate(user, type_code)
    body = client_for(user).get(w.url("/inventory")).json()
    assert all(_WITHHELD_KEYS - {"origin_notes", "is_published"} <= set(row) for row in body)
    assert {row["item_instance_id"] for row in body} == {
        str(i) for i in (w.sword_id, w.loan_id, w.ring_id, w.known_id)
    }


def test_the_gm_keeps_the_full_projection_with_unpublished_items(
    w: World, client_for: Callable[[uuid.UUID], TestClient]
) -> None:
    body = client_for(w.gm).get(w.url("/inventory")).json()
    assert str(w.draft_id) in _rows(body)
    assert "condition_percentage" in body[0]


# --- explicit grants and denies --------------------------------------------------------------


def test_a_direct_grant_to_a_plain_player_opens_the_restricted_inventory(
    w: World, client_for: Callable[[uuid.UUID], TestClient]
) -> None:
    player = w.member("Plain Player")
    client = client_for(player)
    assert client.get(w.url("/inventory")).status_code == 404
    w.grant(player, _INVENTORY, "allow")
    response = client.get(w.url("/inventory"))
    assert response.status_code == 200
    assert all(set(row) == _RESTRICTED_KEYS for row in response.json())
    assert client.get(w.url("/sheet")).status_code == 404


def test_a_revoked_grant_closes_the_inventory_again(
    w: World, client_for: Callable[[uuid.UUID], TestClient], db_connection: Connection
) -> None:
    player = w.member("Plain Player")
    w.grant(player, _INVENTORY, "allow")
    client = client_for(player)
    assert client.get(w.url("/inventory")).status_code == 200
    db_connection.execute(text("UPDATE security.resource_grants SET revoked_at = now()"))
    assert client.get(w.url("/inventory")).status_code == 404


def test_an_explicit_inventory_deny_beats_both_relationship_and_full_tier(
    w: World, client_for: Callable[[uuid.UUID], TestClient]
) -> None:
    viewer = w.member("Viewer")
    w.relate(viewer, "viewer")
    w.grant(viewer, _INVENTORY, "deny")
    owner = w.member("Owner")
    w.relate(owner, "owner")
    w.grant(owner, _INVENTORY, "deny")
    for user in (viewer, owner):
        client = client_for(user)
        assert client.get(w.url("/inventory")).status_code == 404
        sections = client.get(w.url()).json()["sections"]
        assert sections["inventory"] is False
    # The owner's sheet is a separate section and stays open.
    assert client_for(owner).get(w.url("/sheet")).status_code == 200


def test_an_entity_level_campaign_view_deny_removes_the_inventory_for_everyone_but_the_gm(
    w: World, client_for: Callable[[uuid.UUID], TestClient]
) -> None:
    viewer = w.member("Viewer")
    w.relate(viewer, "viewer")
    w.grant(viewer, _INVENTORY, "allow")
    w.deny_entity_view(viewer)
    client = client_for(viewer)
    assert client.get(w.url("/inventory")).status_code == 404
    assert client.get(w.url()).status_code == 404


def test_a_view_full_deny_leaves_inventory_only_access_in_place(
    w: World, client_for: Callable[[uuid.UUID], TestClient]
) -> None:
    owner = w.member("Owner")
    w.relate(owner, "owner")
    w.grant(owner, "character.view_full", "deny")
    client = client_for(owner)
    body = client.get(w.url("/inventory")).json()
    assert all(set(row) == _RESTRICTED_KEYS for row in body)
    assert client.get(w.url("/sheet")).status_code == 404
    assert client.get(w.url()).json()["sections"]["inventory"] is True


# --- sections agree with the endpoint ----------------------------------------------------------


@pytest.mark.parametrize(
    ("setup", "expected"),
    [
        (lambda w, u: w.relate(u, "viewer"), True),
        (lambda w, u: w.relate(u, "observer_approved_viewer"), True),
        (lambda w, u: w.relate(u, "owner"), True),
        (lambda w, u: w.relate(u, "former_controller"), None),
        (lambda w, u: (w.relate(u, "viewer"), w.grant(u, _INVENTORY, "deny")), False),
        (lambda w, u: w.relate(u, "viewer", revoked=True), None),
    ],
)
def test_sections_inventory_equals_the_endpoint(
    w: World,
    client_for: Callable[[uuid.UUID], TestClient],
    setup: Callable[[World, uuid.UUID], object],
    expected: bool | None,
) -> None:
    user = w.member("Subject")
    setup(w, user)
    client = client_for(user)
    detail = client.get(w.url())
    opens = client.get(w.url("/inventory")).status_code == 200
    if expected is None:
        assert detail.status_code != 200 and not opens
    else:
        assert detail.json()["sections"]["inventory"] is expected is opens


# --- lifecycle, campaign and timeline boundaries ----------------------------------------------


def test_a_character_of_another_world_and_a_foreign_timeline_are_rejected(
    w: World, client_for: Callable[[uuid.UUID], TestClient], db_connection: Connection
) -> None:
    viewer = w.member("Viewer")
    w.relate(viewer, "viewer")
    other_world = make_world(db_connection, slug=f"cp6-other-{uuid.uuid4().hex[:6]}")
    foreign = make_character(db_connection, other_world, name="Foreign")
    client = client_for(viewer)
    assert client.get(w.url("/inventory", foreign)).status_code in (403, 404)

    # Items held on the branch timeline are not visible through the primary-timeline campaign.
    ruleset = make_ruleset_version_for_world(db_connection, w.world_id)
    definition = make_item_definition(db_connection, ruleset, display_name="Branch Item")
    branch_item = make_item_instance(db_connection, w.world_id, definition, name="Branch Only")
    make_item_state(db_connection, w.branch_timeline_id, branch_item, quantity=1)
    make_inventory_entry(
        db_connection, w.branch_timeline_id, branch_item, holder_entity_id=w.character_id
    )
    body = client.get(w.url("/inventory")).json()
    assert str(branch_item) not in {row["item_instance_id"] for row in body}


# --- the capability grants nothing else --------------------------------------------------------


def test_inventory_access_opens_no_mutation_party_or_control_route(
    w: World, client_for: Callable[[uuid.UUID], TestClient]
) -> None:
    user = w.member("Reader")
    w.relate(user, "viewer")
    w.grant(user, _INVENTORY, "allow")
    client = client_for(user)
    item = w.sword_id
    attempts = [
        client.post(f"/campaigns/{w.campaign_id}/items/{item}/transfer", json={}),
        client.post(f"/campaigns/{w.campaign_id}/items/{item}/identify", json={}),
        client.get(f"/campaigns/{w.campaign_id}/parties/{uuid.uuid4()}/inventory"),
        client.get(w.url("/parties")),
        client.get(w.url("/sheet")),
    ]
    assert all(r.status_code in (400, 401, 403, 404, 405, 422) for r in attempts)
    assert all(r.status_code != 200 for r in attempts)
    # The inventory projection carries nothing a mutation would need as an optimistic token.
    assert "last_event_id" not in client.get(w.url("/inventory")).text


def test_the_capability_is_referenced_only_by_the_read_side() -> None:
    """No command, mutation route, perspective or control check names the capability."""
    src = Path(__file__).resolve().parents[2] / "src" / "dnd_ai"
    users = {
        str(path.relative_to(src)).replace("\\", "/")
        for path in src.rglob("*.py")
        if _INVENTORY in path.read_text(encoding="utf-8")
    }
    assert users == {
        "domain/access.py",
        "api/access.py",
        "api/characters.py",
        "queries/inventory.py",
    }


def test_the_openapi_contract_lists_the_restricted_row() -> None:
    schema = json.dumps(create_app().openapi())
    assert "RestrictedInventoryItemResponse" in schema
