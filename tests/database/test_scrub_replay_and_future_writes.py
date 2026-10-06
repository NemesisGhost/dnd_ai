"""Replay after the scrub, and the future-write guarantee (checkpoint 15.2A-4).

A replay of a key whose stored body was scrubbed returns the receipt and writes nothing new.
Every authoring route stores only a minimal receipt for replay, whatever it returns first.
"""

import importlib.util
import json
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Connection, text

from dnd_ai.domain.data_classification import replay_body
from tests.authoring_support import AuthoringHarness, harness_fixture_factory
from tests.content_support import ContentSetup

pytestmark = pytest.mark.database

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "migrations"
    / "versions"
    / "135_scrub_narrative_text.py"
)


def load_migration():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("scrub_migration", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def harness(db_connection: Connection) -> Iterator[AuthoringHarness]:
    yield from harness_fixture_factory()(db_connection)


@pytest.fixture
def s(harness: AuthoringHarness, db_connection: Connection) -> ContentSetup:
    return ContentSetup(harness, db_connection)


def test_replaying_a_scrubbed_key_returns_the_receipt_and_writes_nothing(
    s: ContentSetup, db_connection: Connection
) -> None:
    migration = load_migration()
    key = s.gm.fresh_key()
    body = {"category": "settlement", "name": "Stonebridge", "summary": "A secret smuggler town"}
    first = s.gm.post_raw(s.url("locations"), body, key=key)
    assert first.status_code == 201, first.text
    location_id = first.json()["location_id"]
    # Put the stored body back to the full authoring view the old routes kept.
    old_view = {
        "location_id": location_id,
        "name": "Stonebridge",
        "summary": "A secret smuggler town",
        "row_version": 1,
        "canon_status": "draft",
        "available_actions": ["update"],
        "blocked_actions": [],
    }
    db_connection.execute(
        text(
            "UPDATE security.idempotent_requests SET response_body = CAST(:b AS jsonb) "
            "WHERE idempotency_key = :k"
        ),
        {"b": json.dumps(old_view), "k": key},
    )
    stored = db_connection.execute(
        text(
            "SELECT idempotent_request_id, response_body FROM security.idempotent_requests "
            "WHERE idempotency_key = :k"
        ),
        {"k": key},
    ).one()
    receipt = migration.plan_replay_row(201, stored.response_body)
    assert receipt is not None and "summary" not in receipt and "name" not in receipt
    db_connection.execute(
        text(
            "UPDATE security.idempotent_requests SET response_body = CAST(:b AS jsonb) "
            "WHERE idempotent_request_id = :i"
        ),
        {"b": json.dumps(receipt), "i": stored.idempotent_request_id},
    )
    audit_before = s.count("audit.change_log")
    entities_before = s.count("core.entities")
    replay = s.gm.post_raw(s.url("locations"), body, key=key)
    assert replay.status_code == 201
    assert replay.json()["location_id"] == location_id
    assert replay.json()["created"] is True and "summary" not in replay.json()
    assert replay.json()["_redacted_by"] == migration.revision
    assert s.count("audit.change_log") == audit_before
    assert s.count("core.entities") == entities_before


def test_every_authoring_route_stores_only_a_minimal_replay_body(s: ContentSetup) -> None:
    """The route answers with the full view, but what is kept for replay is a receipt."""
    key = s.gm.fresh_key()
    first = s.gm.post(
        s.url("locations"),
        {"category": "settlement", "name": "Quiet Town", "summary": "SENTINEL-SECRET-SUMMARY"},
        key=key,
    )
    assert first.status_code == 201
    stored = s.connection.execute(
        text("SELECT response_body FROM security.idempotent_requests WHERE idempotency_key = :k"),
        {"k": key},
    ).scalar()
    assert "SENTINEL-SECRET-SUMMARY" not in json.dumps(stored)
    assert stored == replay_body(stored)

    # A route that returns a full view (an item) also keeps only the receipt.
    item_key = s.gm.fresh_key()
    definitions = s.gm.get(s.url("item-definitions")).json()["items"]
    sword = next(d["item_definition_id"] for d in definitions if d["code"] == "longsword")
    made = s.gm.post(
        s.url("items"),
        {
            "name": "Quiet Sword",
            "summary": "SENTINEL-ITEM-SUMMARY",
            "item_definition_id": sword,
            "origin_notes": "SENTINEL-ORIGIN-NOTES",
        },
        key=item_key,
    )
    assert made.status_code == 201 and made.json()["summary"] == "SENTINEL-ITEM-SUMMARY"
    stored_item = s.connection.execute(
        text("SELECT response_body FROM security.idempotent_requests WHERE idempotency_key = :k"),
        {"k": item_key},
    ).scalar()
    assert "SENTINEL" not in json.dumps(stored_item)
    assert str(stored_item["item_instance_id"]) == made.json()["item_instance_id"]
    assert uuid.UUID(str(stored_item["item_instance_id"]))


def test_audit_rows_of_every_authoring_write_carry_no_prose(s: ContentSetup) -> None:
    s.gm.post(
        s.url("locations"),
        {"category": "settlement", "name": "Audit Town", "summary": "SENTINEL-AUDIT-SUMMARY"},
        key=s.gm.fresh_key(),
    )
    rows = s.connection.execute(
        text("SELECT changed_fields FROM audit.change_log WHERE command_name = 'create_location'")
    ).all()
    assert rows and "SENTINEL-AUDIT-SUMMARY" not in json.dumps([r.changed_fields for r in rows])
