"""The minimal replay body (checkpoint 15.2A-4): no database."""

import uuid

from dnd_ai.domain.data_classification import replay_body

ID = str(uuid.uuid4())
OTHER = str(uuid.uuid4())


def test_ids_flags_numbers_and_closed_codes_are_kept() -> None:
    body = {
        "item_instance_id": ID,
        "row_version": 3,
        "created": True,
        "changed": False,
        "event_id": OTHER,
        "canon_status": "draft",
        "status": "active",
        "quantity": 2,
        "weight": 1.5,
        "world_time_id": None,
        "moved": [ID, OTHER],
    }
    assert replay_body(body) == body


def test_names_summaries_references_and_nested_views_are_dropped() -> None:
    body = {
        "location_id": ID,
        "name": "Stonebridge",
        "summary": "A secret",
        "reference": "p. 12",
        "description": "Lore",
        "origin_notes": "found in a ditch",
        "parent": {"location_id": ID, "name": "Realm"},
        "participants": [{"name": "Mira"}],
        "fields": {"voice": "gravelly"},
        "changed": True,
    }
    assert replay_body(body) == {"location_id": ID, "changed": True}


def test_a_string_that_is_not_an_id_or_a_code_is_dropped_even_under_an_id_or_code_key() -> None:
    body = {
        "npc_id": "A sentence pretending to be an id",
        "status": "A sentence pretending to be a status code",
        "kind": "x" * 80,
        "side": "enemy",
        "list_of_mixed": [ID, "not an id"],
    }
    assert replay_body(body) == {"side": "enemy"}


def test_a_minimal_body_is_unchanged() -> None:
    receipt = {"npc_id": ID, "row_version": 1, "created": True, "changed": True, "record_id": OTHER}
    assert replay_body(receipt) == receipt
    assert replay_body(replay_body(receipt)) == receipt
