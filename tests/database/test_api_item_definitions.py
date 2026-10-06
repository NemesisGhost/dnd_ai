"""Item definition authoring (checkpoint 15.3B-1a, decision D-22, migration 132)."""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError

from dnd_ai.domain.data_classification import replay_body
from tests.authoring_support import AuthoringHarness, harness_fixture_factory
from tests.content_support import ContentSetup
from tests.factories import make_item_instance

pytestmark = pytest.mark.database


@pytest.fixture
def harness(db_connection: Connection) -> Iterator[AuthoringHarness]:
    yield from harness_fixture_factory()(db_connection)


@pytest.fixture
def s(harness: AuthoringHarness, db_connection: Connection) -> ContentSetup:
    return ContentSetup(harness, db_connection)


def code(response) -> str:  # type: ignore[no-untyped-def]
    return str(response.json()["error"]["code"])


def create(s: ContentSetup, name: str = "Moonblade", *, actor=None, cid=None, **fields):  # type: ignore[no-untyped-def]
    who = actor or s.gm
    return who.post(
        s.url("item-definitions", cid),
        {"name": name, "category": "weapon", **fields},
        key=who.fresh_key(),
    )


def update(s: ContentSetup, definition_id: str, version: int, **fields):  # type: ignore[no-untyped-def]
    body = {"expected_row_version": version, "name": "Moonblade", "category": "weapon", **fields}
    return s.gm.post(s.url(f"item-definitions/{definition_id}/update"), body, key=s.gm.fresh_key())


def test_a_clean_install_has_generic_definitions_and_options(s: ContentSetup) -> None:
    listed = s.gm.get(s.url("item-definitions")).json()["items"]
    codes = {item["code"] for item in listed}
    assert {"longsword", "healing_potion", "backpack"} <= codes
    assert all(item["is_homebrew"] is False and item["can_edit"] is False for item in listed)
    assert all(item["canon_status"] == "canon" for item in listed)
    options = s.gm.get(s.url("item-definitions/options")).json()
    assert {c["value"] for c in options["categories"]} >= {"weapon", "armor", "potion"}
    assert [r["value"] for r in options["rarities"]][0] == "common"
    assert [c["value"] for c in options["canon_states"]] == ["draft", "canon"]
    only_weapons = s.gm.get(s.url("item-definitions"), category="weapon").json()["items"]
    assert only_weapons and {i["category"] for i in only_weapons} == {"weapon"}


def test_creating_homebrew_derives_a_unique_code_and_starts_as_draft(s: ContentSetup) -> None:
    first = create(
        s,
        "Moon-Blade!",
        description="  Glows softly  ",
        rarity="rare",
        requires_attunement=True,
        weight=3,
        base_cost_gp="1200.50",
    )
    assert first.status_code == 201, first.text
    body = first.json()
    assert body["code"] == "moon_blade" and body["canon_status"] == "draft"
    assert body["description"] == "Glows softly" and body["rarity"] == "rare"
    assert body["requires_attunement"] is True and body["weight"] == 3.0
    assert body["base_cost_gp"] == 1200.5 and body["is_homebrew"] and body["can_edit"]
    again = create(s, "Moon Blade")
    assert again.status_code == 201 and again.json()["code"] == "moon_blade_2"
    # A name that matches a seeded definition gets a different code, not an error.
    clash = create(s, "Longsword")
    assert clash.status_code == 201 and clash.json()["code"] == "longsword_2"
    homebrew = s.gm.get(s.url("item-definitions"), homebrew="true").json()["items"]
    assert {i["code"] for i in homebrew} == {"moon_blade", "moon_blade_2", "longsword_2"}


def test_invalid_input_is_refused(s: ContentSetup) -> None:
    bad = [
        {"name": "   "},
        {"category": "nonsense"},
        {"rarity": "mythic"},
        {"canon_status": "approved"},
        {"weight": "1.234"},
        {"weight": -1},
        {"base_cost_gp": "abc"},
    ]
    for fields in bad:
        response = create(s, **{"name": "Thing", **fields})
        assert response.status_code in (400, 422), (fields, response.text)
    assert s.gm.get(s.url("item-definitions"), homebrew="true").json()["items"] == []


def test_update_is_against_the_row_version_and_world_owned_only(s: ContentSetup) -> None:
    made = create(s, "Moonblade").json()
    changed = update(
        s,
        made["item_definition_id"],
        made["row_version"],
        rarity="legendary",
        canon_status="canon",
        description="Now canon",
    )
    assert changed.status_code == 200, changed.text
    body = changed.json()
    assert body["changed"] is True and body["row_version"] == made["row_version"] + 1
    assert body["canon_status"] == "canon" and body["rarity"] == "legendary"
    assert body["code"] == "moonblade"  # the code never changes
    stale = update(s, made["item_definition_id"], made["row_version"], rarity="rare")
    assert stale.status_code == 409 and code(stale) == "stale_write"
    same = update(
        s,
        made["item_definition_id"],
        body["row_version"],
        rarity="legendary",
        canon_status="canon",
        description="Now canon",
    )
    assert same.status_code == 200 and same.json()["changed"] is False
    assert same.json()["row_version"] == body["row_version"]
    seeded = next(
        i for i in s.gm.get(s.url("item-definitions")).json()["items"] if i["code"] == "longsword"
    )
    refused = update(s, seeded["item_definition_id"], seeded["row_version"], name="Longsword")
    assert refused.status_code == 404


def test_homebrew_is_invisible_and_untouchable_from_another_world(s: ContentSetup) -> None:
    made = create(s, "Moonblade").json()
    theirs = s.stranger.get(s.url("item-definitions", s.other_cid)).json()["items"]
    assert "moonblade" not in {i["code"] for i in theirs}
    assert (
        s.stranger.get(
            s.url(f"item-definitions/{made['item_definition_id']}", s.other_cid)
        ).status_code
        == 404
    )
    foreign_update = s.stranger.post(
        s.url(f"item-definitions/{made['item_definition_id']}/update", s.other_cid),
        {"expected_row_version": 1, "name": "Mine now", "category": "weapon"},
        key=s.stranger.fresh_key(),
    )
    assert foreign_update.status_code == 404
    # The same name in the other world is allowed and independent.
    other = create(s, "Moonblade", actor=s.stranger, cid=s.other_cid)
    assert other.status_code == 201 and other.json()["code"] == "moonblade"
    assert other.json()["item_definition_id"] != made["item_definition_id"]


def test_players_and_outsiders_cannot_author_or_list(s: ContentSetup) -> None:
    assert s.player.get(s.url("item-definitions")).status_code == 403
    assert create(s, "Nope", actor=s.player).status_code == 403
    assert s.stranger.get(s.url("item-definitions")).status_code in (403, 404)


def test_the_database_refuses_an_instance_of_another_worlds_homebrew(
    s: ContentSetup, db_connection: Connection
) -> None:
    made = create(s, "Moonblade").json()
    definition = uuid.UUID(made["item_definition_id"])
    own = make_item_instance(db_connection, s.world_id, definition, name="Mine")
    assert own is not None
    with pytest.raises(DBAPIError) as exc, db_connection.begin_nested():
        make_item_instance(db_connection, s.other_world_id, definition, name="Stolen")
    assert "homebrew owned by another world" in str(exc.value)
    seeded = db_connection.execute(
        text(
            "SELECT item_definition_id FROM rules.item_definitions "
            "WHERE code = 'longsword' AND owning_world_id IS NULL"
        )
    ).scalar()
    assert make_item_instance(db_connection, s.other_world_id, seeded, name="Fine")


def test_ownership_and_ruleset_cannot_be_changed(
    s: ContentSetup, db_connection: Connection
) -> None:
    made = create(s, "Moonblade").json()
    for column, value in (("owning_world_id", s.other_world_id), ("owning_world_id", None)):
        with pytest.raises(DBAPIError), db_connection.begin_nested():
            db_connection.execute(
                text(
                    f"UPDATE rules.item_definitions SET {column} = :v WHERE item_definition_id = :d"
                ),
                {"v": value, "d": made["item_definition_id"]},
            )


def test_replay_and_audit_are_redacted(s: ContentSetup) -> None:
    key = s.gm.fresh_key()
    body = {"name": "Moonblade", "category": "weapon", "description": "Secret lore"}
    first = s.gm.post(s.url("item-definitions"), body, key=key)
    replay = s.gm.post(s.url("item-definitions"), body, key=key)
    assert first.status_code == replay.status_code == 201 and replay.json() == replay_body(
        first.json()
    )
    assert len(s.gm.get(s.url("item-definitions"), homebrew="true").json()["items"]) == 1
    rows = s.audit("create_item_definition")
    assert len(rows) == 1 and rows[0].action == "created"
    assert "Secret lore" not in str(rows[0].changed_fields)
