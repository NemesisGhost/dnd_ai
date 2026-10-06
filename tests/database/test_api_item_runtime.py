"""Item instances, runtime operations, custody and party inventory (checkpoint 15.3B-1b, migration 133)."""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, text

from dnd_ai.domain.data_classification import replay_body
from tests.authoring_support import AuthoringHarness, harness_fixture_factory
from tests.content_support import ContentSetup
from tests.database.test_api_campaign_clock import Times
from tests.database.test_api_party_members import add, new_party
from tests.database.test_api_routes_travel import clock_at, pc, place

pytestmark = pytest.mark.database


@pytest.fixture
def harness(db_connection: Connection) -> Iterator[AuthoringHarness]:
    yield from harness_fixture_factory()(db_connection)


@pytest.fixture
def s(harness: AuthoringHarness, db_connection: Connection) -> ContentSetup:
    setup = ContentSetup(harness, db_connection)
    clock_at(setup, 5)
    return setup


def code(response) -> str:  # type: ignore[no-untyped-def]
    return str(response.json()["error"]["code"])


def definition_id(s: ContentSetup, item_code: str = "longsword") -> str:
    items = s.gm.get(s.url("item-definitions")).json()["items"]
    return str(next(i["item_definition_id"] for i in items if i["code"] == item_code))


def homebrew_definition(s: ContentSetup, name: str = "Moonblade", **fields: object) -> str:
    created = s.gm.post(
        s.url("item-definitions"),
        {"name": name, "category": "weapon", "canon_status": "canon", **fields},
        key=s.gm.fresh_key(),
    )
    assert created.status_code == 201, created.text
    return str(created.json()["item_definition_id"])


def item(
    s: ContentSetup,
    name: str = "Rusty Sword",
    *,
    definition: str | None = None,
    publish: bool = True,
) -> dict:
    created = s.gm.post(
        s.url("items"),
        {"name": name, "item_definition_id": definition or definition_id(s)},
        key=s.gm.fresh_key(),
    )
    assert created.status_code == 201, created.text
    body = created.json()
    if publish:
        s.publish(body["item_instance_id"], body["row_version"])
        body = view(s, body["item_instance_id"])
    return dict(body)


def view(s: ContentSetup, item_id: str) -> dict:
    response = s.gm.get(s.url(f"items/{item_id}"))
    assert response.status_code == 200, response.text
    return dict(response.json())


def op(s: ContentSetup, item_id: str, name: str, token: str | None, **extra: object):  # type: ignore[no-untyped-def]
    return s.gm.post_raw(
        f"/campaigns/{s.cid}/items/{item_id}/{name}",
        {"expected_last_event_id": token, **extra},
        key=s.gm.fresh_key(),
    )


def award(s: ContentSetup, item_id: str, holder: str, token: str | None = None, **extra: object):  # type: ignore[no-untyped-def]
    return op(s, item_id, "award", token, holder_entity_id=holder, **extra)


def transfer(s: ContentSetup, item_id: str, token: str | None, **extra: object):  # type: ignore[no-untyped-def]
    return s.gm.post_raw(
        f"/campaigns/{s.cid}/items/{item_id}/transfer",
        {"expected_last_event_id": token, **extra},
        key=s.gm.fresh_key(),
    )


def event_types(s: ContentSetup, item_id: str) -> list[str]:
    """The event types of the item's events, sorted (events of one test share a timestamp)."""
    return sorted(
        str(r[0])
        for r in s.connection.execute(
            text("""
                SELECT et.code FROM narrative.event_effects f
                JOIN narrative.events e ON e.event_id = f.event_id
                JOIN narrative.event_types et ON et.event_type_id = e.event_type_id
                WHERE f.target_entity_id = :i
                GROUP BY e.event_id, et.code
            """),
            {"i": item_id},
        )
    )


def make_container(s: ContentSetup, item_id: str) -> None:
    s.connection.execute(
        text("INSERT INTO world.item_containers (container_id) VALUES (:i)"), {"i": item_id}
    )


# --- instance authoring ----------------------------------------------------------------------------


def test_an_instance_is_a_draft_with_a_fixed_published_definition(s: ContentSetup) -> None:
    created = s.gm.post(
        s.url("items"),
        {
            "name": "  Rusty Sword  ",
            "summary": "Pitted",
            "item_definition_id": definition_id(s),
            "origin_notes": "Found in a ditch",
        },
        key=s.gm.fresh_key(),
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["name"] == "Rusty Sword" and body["canon_status"] == "draft"
    assert body["definition_name"] == "Longsword" and body["can_operate"] is False
    assert body["holder"] is None and body["last_event_id"] is None and body["quantity"] == 1
    updated = s.gm.post(
        s.url(f"items/{body['item_instance_id']}/update"),
        {
            "expected_row_version": body["row_version"],
            "name": "Rusty Sword",
            "summary": "Pitted and bent",
            "origin_notes": "Found in a ditch",
        },
        key=s.gm.fresh_key(),
    )
    assert updated.status_code == 200 and updated.json()["summary"] == "Pitted and bent"
    stale = s.gm.post(
        s.url(f"items/{body['item_instance_id']}/update"),
        {"expected_row_version": body["row_version"], "name": "Late"},
        key=s.gm.fresh_key(),
    )
    assert stale.status_code == 409 and code(stale) == "stale_write"
    listed = s.gm.get(s.url("items")).json()["items"]
    assert [i["name"] for i in listed] == ["Rusty Sword"]


def test_the_definition_must_be_published_and_visible_to_the_world(s: ContentSetup) -> None:
    draft = s.gm.post(
        s.url("item-definitions"),
        {"name": "Draft Blade", "category": "weapon"},
        key=s.gm.fresh_key(),
    ).json()["item_definition_id"]
    foreign = s.stranger.post(
        s.url("item-definitions", s.other_cid),
        {"name": "Theirs", "category": "weapon", "canon_status": "canon"},
        key=s.stranger.fresh_key(),
    ).json()["item_definition_id"]
    for bad in (draft, foreign, str(uuid.uuid4())):
        response = s.gm.post(
            s.url("items"), {"name": "X", "item_definition_id": bad}, key=s.gm.fresh_key()
        )
        assert response.status_code == 400 and code(response) == "item_definition_invalid"
    options = s.gm.get(s.url("items/options")).json()["definitions"]
    assert "Longsword (Weapon)" in {o["label"] for o in options}
    assert draft not in {o["value"] for o in options}


def test_players_and_other_worlds_cannot_author_or_read_items(s: ContentSetup) -> None:
    made = item(s)
    assert s.player.get(s.url("items")).status_code == 403
    assert (
        s.player.post(
            s.url("items"),
            {"name": "X", "item_definition_id": definition_id(s)},
            key=s.player.fresh_key(),
        ).status_code
        == 403
    )
    assert (
        s.stranger.get(s.url(f"items/{made['item_instance_id']}", s.other_cid)).status_code == 404
    )
    assert op(s, made["item_instance_id"], "equip", None).status_code in (400, 404, 409)


# --- award, transfer, custody ------------------------------------------------------------------------


def test_award_places_an_unplaced_published_item_with_one_event(s: ContentSetup) -> None:
    holder = pc(s, "Aldric")
    made = item(s)
    response = award(s, made["item_instance_id"], holder, None, quantity=3)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["holder"]["entity_id"] == holder and body["owner"]["entity_id"] == holder
    assert body["quantity"] == 3 and body["operation"] == "award"
    assert body["last_event_id"] == body["event_id"]
    assert event_types(s, made["item_instance_id"]) == ["item_acquired"]
    again = award(s, made["item_instance_id"], holder, body["last_event_id"])
    assert again.status_code == 409 and code(again) == "item_already_placed"
    audit = s.audit("award_item")
    assert len(audit) == 1 and audit[0].action == "updated"


def test_a_draft_item_or_holder_is_not_targetable(s: ContentSetup) -> None:
    holder, draft_holder = pc(s, "Aldric"), pc(s, "Draft", publish=False)
    draft_item = item(s, "Draft Item", publish=False)
    refused = award(s, draft_item["item_instance_id"], holder)
    assert refused.status_code in (404, 409) and refused.status_code != 200
    published = item(s)
    assert award(s, published["item_instance_id"], draft_holder).status_code != 200
    assert view(s, published["item_instance_id"])["holder"] is None


def test_transfer_is_against_the_last_event_seen(s: ContentSetup) -> None:
    aldric, bryn = pc(s, "Aldric"), pc(s, "Bryn")
    made = item(s)
    first = award(s, made["item_instance_id"], aldric).json()
    moved = transfer(
        s,
        made["item_instance_id"],
        first["last_event_id"],
        holder_entity_id=bryn,
        transfer_ownership=True,
    )
    assert moved.status_code == 200, moved.text
    after = view(s, made["item_instance_id"])
    assert after["holder"]["entity_id"] == bryn and after["owner"]["entity_id"] == bryn
    assert after["last_event_id"] == moved.json()["event_id"]
    stale = transfer(s, made["item_instance_id"], first["last_event_id"], holder_entity_id=aldric)
    assert stale.status_code == 409 and code(stale) == "stale_write"
    same = transfer(s, made["item_instance_id"], after["last_event_id"], holder_entity_id=bryn)
    assert same.status_code == 409 and code(same) == "item_operation_invalid"
    assert event_types(s, made["item_instance_id"]) == ["item_acquired", "item_transferred"]


def test_transfer_to_a_place_and_back_and_without_a_token_for_adapters(s: ContentSetup) -> None:
    aldric, town = pc(s, "Aldric"), place(s, "Stonebridge")
    made = item(s)
    first = award(s, made["item_instance_id"], aldric).json()
    dropped = transfer(s, made["item_instance_id"], first["last_event_id"], location_id=town)
    assert dropped.status_code == 200, dropped.text
    assert view(s, made["item_instance_id"])["location"]["entity_id"] == town
    # An adapter that predates the token omits the key and is not checked.
    picked = s.gm.post_raw(
        f"/campaigns/{s.cid}/items/{made['item_instance_id']}/transfer",
        {"holder_entity_id": aldric},
        key=s.gm.fresh_key(),
    )
    assert picked.status_code == 200, picked.text
    assert view(s, made["item_instance_id"])["holder"]["entity_id"] == aldric
    bad = transfer(
        s,
        made["item_instance_id"],
        view(s, made["item_instance_id"])["last_event_id"],
        holder_entity_id=aldric,
        location_id=town,
    )
    assert bad.status_code == 400


def test_containers_refuse_loops_and_non_containers(s: ContentSetup) -> None:
    chest, bag, sword = item(s, "Chest"), item(s, "Bag"), item(s, "Sword")
    make_container(s, chest["item_instance_id"])
    make_container(s, bag["item_instance_id"])
    town = place(s, "Stonebridge")
    for made in (chest, bag):
        assert transfer(s, made["item_instance_id"], None, location_id=town).status_code == 200
    inside = transfer(
        s,
        bag["item_instance_id"],
        view(s, bag["item_instance_id"])["last_event_id"],
        container_id=chest["item_instance_id"],
    )
    assert inside.status_code == 200, inside.text
    loop = transfer(
        s,
        chest["item_instance_id"],
        view(s, chest["item_instance_id"])["last_event_id"],
        container_id=bag["item_instance_id"],
    )
    assert loop.status_code == 400 and code(loop) == "item_container_invalid"
    not_container = transfer(
        s,
        sword["item_instance_id"],
        None,
        container_id=view(s, sword["item_instance_id"])["item_instance_id"],
    )
    assert not_container.status_code == 400
    plain = transfer(s, sword["item_instance_id"], None, container_id=chest["item_instance_id"])
    assert plain.status_code == 200
    assert view(s, sword["item_instance_id"])["container"]["entity_id"] == chest["item_instance_id"]


# --- condition, equipment and destruction ----------------------------------------------------------


def test_equip_damage_repair_consume_and_destroy(s: ContentSetup) -> None:
    holder = pc(s, "Aldric")
    made = item(s)
    token = award(s, made["item_instance_id"], holder, quantity=3).json()["last_event_id"]
    unheld = item(s, "Loose")
    assert op(s, unheld["item_instance_id"], "equip", None).status_code == 409

    equipped = op(s, made["item_instance_id"], "equip", token)
    assert equipped.status_code == 200 and equipped.json()["is_equipped"] is True
    token = equipped.json()["last_event_id"]
    twice = op(s, made["item_instance_id"], "equip", token)
    assert twice.status_code == 409 and code(twice) == "item_operation_invalid"
    blocked = transfer(s, made["item_instance_id"], token, holder_entity_id=pc(s, "Bryn"))
    assert blocked.status_code == 409 and code(blocked) == "item_equipped"

    damaged = op(s, made["item_instance_id"], "damage", token, amount=30)
    assert damaged.json()["condition_percentage"] == 70
    token = damaged.json()["last_event_id"]
    repaired = op(s, made["item_instance_id"], "repair", token, amount=50)
    assert repaired.json()["condition_percentage"] == 100
    token = repaired.json()["last_event_id"]
    assert op(s, made["item_instance_id"], "repair", token, amount=5).status_code == 409

    used = op(s, made["item_instance_id"], "consume", token, amount=2)
    assert used.json()["quantity"] == 1
    token = used.json()["last_event_id"]
    over = op(s, made["item_instance_id"], "consume", token, amount=2)
    assert over.status_code == 409
    last = op(s, made["item_instance_id"], "consume", token)
    assert last.json()["quantity"] == 0 and last.json()["is_destroyed"] is True
    assert last.json()["is_equipped"] is False
    token = last.json()["last_event_id"]
    gone = op(s, made["item_instance_id"], "equip", token)
    assert gone.status_code == 409 and code(gone) == "item_destroyed"
    assert event_types(s, made["item_instance_id"]) == sorted(
        [
            "item_acquired",
            "item_equipped",
            "item_damaged",
            "item_repaired",
            "item_consumed",
            "item_consumed",
        ]
    )


def test_destroy_is_final_and_every_operation_checks_the_token(s: ContentSetup) -> None:
    holder = pc(s, "Aldric")
    made = item(s)
    first = award(s, made["item_instance_id"], holder).json()["last_event_id"]
    stale = op(s, made["item_instance_id"], "damage", None, amount=10)
    assert stale.status_code == 409 and code(stale) == "stale_write"
    destroyed = op(s, made["item_instance_id"], "destroy", first)
    assert destroyed.status_code == 200 and destroyed.json()["is_destroyed"] is True
    after = op(s, made["item_instance_id"], "repair", destroyed.json()["last_event_id"], amount=10)
    assert after.status_code == 409 and code(after) == "item_destroyed"
    assert transfer(s, made["item_instance_id"], None, holder_entity_id=holder).status_code == 409
    assert "item_destroyed" in event_types(s, made["item_instance_id"])


# --- attunement -------------------------------------------------------------------------------------


def test_attunement_needs_the_holder_a_requiring_item_and_stops_at_three(s: ContentSetup) -> None:
    holder, other = pc(s, "Aldric"), pc(s, "Bryn")
    plain = item(s, "Plain")
    award(s, plain["item_instance_id"], holder)
    refused = op(
        s,
        plain["item_instance_id"],
        "attune",
        view(s, plain["item_instance_id"])["last_event_id"],
        character_id=holder,
    )
    assert refused.status_code == 409 and code(refused) == "attunement_not_allowed"

    required = homebrew_definition(s, "Ring of Foo", requires_attunement=True)
    rings = [item(s, f"Ring {n}", definition=required) for n in range(4)]
    for ring in rings:
        award(s, ring["item_instance_id"], holder)
    not_holder = op(
        s,
        rings[0]["item_instance_id"],
        "attune",
        view(s, rings[0]["item_instance_id"])["last_event_id"],
        character_id=other,
    )
    assert not_holder.status_code == 409 and code(not_holder) == "item_not_held"
    for ring in rings[:3]:
        done = op(
            s,
            ring["item_instance_id"],
            "attune",
            view(s, ring["item_instance_id"])["last_event_id"],
            character_id=holder,
        )
        assert done.status_code == 200, done.text
        assert done.json()["attuned_to"]["entity_id"] == holder
    fourth = op(
        s,
        rings[3]["item_instance_id"],
        "attune",
        view(s, rings[3]["item_instance_id"])["last_event_id"],
        character_id=holder,
    )
    assert fourth.status_code == 409 and code(fourth) == "attunement_not_allowed"

    first = rings[0]["item_instance_id"]
    token = view(s, first)["last_event_id"]
    moved = transfer(s, first, token, holder_entity_id=other)
    assert moved.status_code == 409 and code(moved) == "item_attuned"
    destroy = op(s, first, "destroy", token)
    assert destroy.status_code == 409 and code(destroy) == "item_attuned"
    same_time = op(s, first, "end-attunement", token)
    assert same_time.status_code == 409 and code(same_time) == "item_operation_invalid"
    clock_at(s, 6)
    ended = op(s, first, "end-attunement", token)
    assert ended.status_code == 200 and ended.json()["attuned_to"] is None
    again = op(s, first, "end-attunement", ended.json()["last_event_id"])
    assert again.status_code == 409
    fourth_now = op(
        s,
        rings[3]["item_instance_id"],
        "attune",
        view(s, rings[3]["item_instance_id"])["last_event_id"],
        character_id=holder,
    )
    assert fourth_now.status_code == 200


# --- inventories --------------------------------------------------------------------------------------


def test_party_inventory_lists_current_members_items_for_editors_only(s: ContentSetup) -> None:
    times = Times(s)
    aldric, bryn = pc(s, "Aldric"), pc(s, "Bryn")
    party = new_party(s)
    assert add(s, party["party_id"], aldric, times.at(1)).status_code == 201
    made = item(s, "Aldric's Sword")
    award(s, made["item_instance_id"], aldric)
    award(s, item(s, "Bryn's Bow")["item_instance_id"], bryn)
    inventory = s.gm.get(f"/campaigns/{s.cid}/parties/{party['party_id']}/inventory")
    assert inventory.status_code == 200, inventory.text
    members = inventory.json()["members"]
    assert [m["character_name"] for m in members] == ["Aldric"]
    assert [i["name"] for i in members[0]["items"]] == ["Aldric's Sword"]
    assert (
        s.player.get(f"/campaigns/{s.cid}/parties/{party['party_id']}/inventory").status_code == 403
    )
    assert (
        s.stranger.get(
            f"/campaigns/{s.other_cid}/parties/{party['party_id']}/inventory"
        ).status_code
        == 404
    )


def test_a_character_inventory_names_the_instance_and_carries_the_token(s: ContentSetup) -> None:
    holder = pc(s, "Aldric")
    made = item(s, "Moonblade")
    award(s, made["item_instance_id"], holder)
    inventory = s.gm.get(f"/campaigns/{s.cid}/characters/{holder}/inventory")
    assert inventory.status_code == 200, inventory.text
    row = inventory.json()[0]
    assert row["name"] == "Moonblade" and row["display_name"] == "Longsword"
    assert row["last_event_id"] == view(s, made["item_instance_id"])["last_event_id"]


# --- replay and audit ------------------------------------------------------------------------------------


def test_replay_returns_the_same_response_with_one_event(s: ContentSetup) -> None:
    holder = pc(s, "Aldric")
    made = item(s)
    key = s.gm.fresh_key()
    body = {"expected_last_event_id": None, "holder_entity_id": holder}
    url = f"/campaigns/{s.cid}/items/{made['item_instance_id']}/award"
    first = s.gm.post_raw(url, body, key=key)
    replay = s.gm.post_raw(url, body, key=key)
    assert first.status_code == replay.status_code == 200 and replay.json() == replay_body(
        first.json()
    )
    assert event_types(s, made["item_instance_id"]) == ["item_acquired"]
    assert len(s.audit("award_item")) == 1


# --- the world explorer ------------------------------------------------------------------------------------


def test_players_see_only_published_items_in_the_world_explorer(s: ContentSetup) -> None:
    draft = item(s, "Secret Draft", publish=False)
    published = item(s, "Open Sword")
    names = [
        i["name"]
        for i in s.player.get(f"/campaigns/{s.cid}/world/search", category="item").json()["items"]
    ]
    assert "Open Sword" in names and "Secret Draft" not in names
    detail = s.player.get(f"/campaigns/{s.cid}/world/items/{draft['item_instance_id']}")
    assert detail.status_code == 404
    shown = s.player.get(f"/campaigns/{s.cid}/world/items/{published['item_instance_id']}")
    assert shown.status_code == 200 and shown.json()["name"] == "Open Sword"
