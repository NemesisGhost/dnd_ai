"""Item events and event corrections (checkpoint 15.3B-1b, E-1 reversals for items)."""

from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, text

from tests.authoring_support import AuthoringHarness, harness_fixture_factory
from tests.content_support import ContentSetup
from tests.database.test_api_event_corrections import events_url, status_of, void
from tests.database.test_api_item_runtime import (
    award,
    homebrew_definition,
    item,
    op,
    transfer,
    view,
)
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


def rows(s: ContentSetup, table: str, item_id: str) -> int:
    return int(
        s.connection.execute(
            text(f"SELECT count(*) FROM campaign.{table} WHERE item_instance_id = :i"),  # noqa: S608
            {"i": item_id},
        ).scalar()
        or 0
    )


def test_voiding_an_award_unplaces_the_item_and_drops_ownership(s: ContentSetup) -> None:
    holder = pc(s, "Aldric")
    made = item(s)
    item_id = made["item_instance_id"]
    awarded = award(s, item_id, holder, None, quantity=4).json()
    preview = s.gm.get(events_url(s, awarded["event_id"], "/correction-preview")).json()
    assert preview["can_correct"] is True
    assert {e["component"] for e in preview["effects"]} == {
        "inventory_entries.location",
        "item_ownership",
        "item_state",
    }
    response = void(s, awarded["event_id"])
    assert response.status_code == 200, response.text
    after = view(s, item_id)
    assert after["holder"] is None and after["owner"] is None and after["quantity"] == 1
    # The token goes back to the item's previous event, here none.
    assert after["last_event_id"] is None
    assert rows(s, "item_ownership", item_id) == 0
    assert status_of(s, awarded["event_id"]) == "voided"
    # The item can be awarded again, against the new token.
    again = award(s, item_id, holder, after["last_event_id"])
    assert again.status_code == 200, again.text


def test_voiding_a_transfer_restores_the_holder_and_owner(s: ContentSetup) -> None:
    aldric, bryn, town = pc(s, "Aldric"), pc(s, "Bryn"), place(s, "Stonebridge")
    item_id = item(s)["item_instance_id"]
    first = award(s, item_id, aldric).json()
    moved = transfer(
        s, item_id, first["last_event_id"], holder_entity_id=bryn, transfer_ownership=True
    ).json()
    assert view(s, item_id)["owner"]["entity_id"] == bryn
    assert void(s, moved["event_id"]).status_code == 200
    after = view(s, item_id)
    assert after["holder"]["entity_id"] == aldric and after["owner"]["entity_id"] == aldric
    dropped = transfer(s, item_id, after["last_event_id"], location_id=town).json()
    assert void(s, dropped["event_id"]).status_code == 200
    assert view(s, item_id)["holder"]["entity_id"] == aldric


def test_a_correction_is_refused_once_the_item_has_moved_on(s: ContentSetup) -> None:
    holder = pc(s, "Aldric")
    item_id = item(s)["item_instance_id"]
    first = award(s, item_id, holder).json()
    later = op(s, item_id, "equip", first["last_event_id"]).json()
    preview = s.gm.get(events_url(s, first["event_id"], "/correction-preview")).json()
    assert preview["can_correct"] is False
    assert {e["reason"] for e in preview["effects"]} == {"state_changed"}
    refused = void(s, first["event_id"])
    assert (
        refused.status_code == 409
        and refused.json()["error"]["code"] == "correction_not_reversible"
    )
    assert status_of(s, first["event_id"]) == "recorded"
    # The latest event can be undone, and then the earlier one.
    assert void(s, later["event_id"]).status_code == 200
    assert view(s, item_id)["is_equipped"] is False
    assert void(s, first["event_id"]).status_code == 200


def test_voiding_damage_and_consumption_restores_the_state(s: ContentSetup) -> None:
    holder = pc(s, "Aldric")
    item_id = item(s)["item_instance_id"]
    token = award(s, item_id, holder, None, quantity=3).json()["last_event_id"]
    damaged = op(s, item_id, "damage", token, amount=40).json()
    used = op(s, item_id, "consume", damaged["last_event_id"], amount=2).json()
    assert (view(s, item_id)["condition_percentage"], view(s, item_id)["quantity"]) == (60, 1)
    assert void(s, used["event_id"]).status_code == 200
    assert view(s, item_id)["quantity"] == 3
    assert void(s, damaged["event_id"]).status_code == 200
    assert view(s, item_id)["condition_percentage"] is None


def test_voiding_an_attunement_and_its_end(s: ContentSetup) -> None:
    holder = pc(s, "Aldric")
    ring = item(
        s, "Ring", definition=homebrew_definition(s, "Ring of Foo", requires_attunement=True)
    )
    item_id = ring["item_instance_id"]
    token = award(s, item_id, holder).json()["last_event_id"]
    attuned = op(s, item_id, "attune", token, character_id=holder).json()
    clock_at(s, 6)
    ended = op(s, item_id, "end-attunement", attuned["last_event_id"]).json()
    assert view(s, item_id)["attuned_to"] is None
    assert void(s, ended["event_id"]).status_code == 200
    assert view(s, item_id)["attuned_to"]["entity_id"] == holder
    assert void(s, attuned["event_id"]).status_code == 200
    assert view(s, item_id)["attuned_to"] is None and rows(s, "item_attunements", item_id) == 0


def test_a_destroy_can_be_voided_while_it_is_the_latest_event(s: ContentSetup) -> None:
    holder = pc(s, "Aldric")
    item_id = item(s)["item_instance_id"]
    token = award(s, item_id, holder).json()["last_event_id"]
    destroyed = op(s, item_id, "destroy", token).json()
    assert view(s, item_id)["is_destroyed"] is True
    assert void(s, destroyed["event_id"]).status_code == 200
    assert view(s, item_id)["is_destroyed"] is False
