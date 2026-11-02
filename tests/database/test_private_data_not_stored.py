"""No narrative content in audit or idempotency storage (checkpoint 15.2A-3).

Every typed authoring write (locations, organizations, religions, NPCs,
knowledge claims, quests and their stages/objectives) is exercised through the
real HTTP routes with a sentinel string in every free-text field. Afterwards the
sentinel must appear in no `audit.change_log` row and no
`security.idempotent_requests` row of the world, the stored replay body must be
exactly the minimal receipt, and a replay must return that receipt and write no
second audit row.
"""

import json
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, text

from tests.authoring_support import AuthoringHarness, harness_fixture_factory
from tests.content_support import ContentSetup

pytestmark = pytest.mark.database

SENTINEL = "ZQX-NARRATIVE-SENTINEL-7731"
RECEIPT_KEYS = {"row_version", "created", "changed"}


@pytest.fixture
def harness(db_connection: Connection) -> Iterator[AuthoringHarness]:
    yield from harness_fixture_factory()(db_connection)


@pytest.fixture
def s(harness: AuthoringHarness, db_connection: Connection) -> ContentSetup:
    return ContentSetup(harness, db_connection)


def _audit_and_replay_text(s: ContentSetup) -> str:
    rows = s.connection.execute(
        text(
            "SELECT CAST(changed_fields AS text), reason FROM audit.change_log WHERE world_id = :w"
        ),
        {"w": s.world_id},
    ).all()
    replays = s.connection.execute(
        text(
            "SELECT CAST(response_body AS text) FROM security.idempotent_requests "
            "WHERE actor_user_id = :u"
        ),
        {"u": s.gm.user_id},
    ).all()
    return json.dumps([[str(c) for c in r] for r in rows]) + json.dumps(
        [[str(c) for c in r] for r in replays]
    )


def _post(s: ContentSetup, path: str, body: dict, *, status: int) -> dict:
    key = s.gm.fresh_key()
    raw = s.gm.post_raw(s.url(path), body, key=key)
    assert raw.status_code == status, raw.text
    receipt = raw.json()
    assert set(receipt) >= RECEIPT_KEYS, receipt
    stored = s.connection.execute(
        text(
            "SELECT response_body FROM security.idempotent_requests "
            "WHERE actor_user_id = :u AND idempotency_key = :k"
        ),
        {"u": s.gm.user_id, "k": key},
    ).scalar()
    assert stored == receipt, "the stored replay body is exactly the response receipt"
    audit_before = s.connection.execute(
        text("SELECT count(*) FROM audit.change_log WHERE world_id = :w"), {"w": s.world_id}
    ).scalar()
    replay = s.gm.post_raw(s.url(path), body, key=key)
    assert replay.status_code == status and replay.json() == receipt
    audit_after = s.connection.execute(
        text("SELECT count(*) FROM audit.change_log WHERE world_id = :w"), {"w": s.world_id}
    ).scalar()
    assert audit_before == audit_after, "a replay writes no second audit row"
    return receipt


def _update(s: ContentSetup, path: str, receipt: dict, body: dict) -> dict:
    return _post(s, path, {"expected_row_version": receipt["row_version"], **body}, status=200)


def test_location_writes_store_only_receipts_and_redacted_audit(s: ContentSetup) -> None:
    created = _post(
        s, "locations", {"category": "region", "name": "Ashmark", "summary": SENTINEL}, status=201
    )
    assert set(created) == RECEIPT_KEYS | {"location_id"}
    _update(
        s,
        f"locations/{created['location_id']}/update",
        created,
        {"name": "Ashmark", "summary": SENTINEL + " v2", "change_note": None},
    )
    assert SENTINEL not in _audit_and_replay_text(s)


def test_organization_and_religion_writes_store_only_receipts(s: ContentSetup) -> None:
    org = _post(
        s,
        "organizations",
        {
            "kind": "organization",
            "organization_type": "guild",
            "name": "Guild",
            "summary": SENTINEL,
            "public_description": SENTINEL,
            "internal_description": SENTINEL,
        },
        status=201,
    )
    assert set(org) == RECEIPT_KEYS | {"organization_id"}
    religion = _post(
        s,
        "religions",
        {"name": "Faith", "summary": SENTINEL, "pantheon_structure": SENTINEL},
        status=201,
    )
    assert set(religion) == RECEIPT_KEYS | {"religion_id"}
    _update(
        s,
        f"religions/{religion['religion_id']}/update",
        religion,
        {"name": "Faith", "summary": SENTINEL + "2", "pantheon_structure": SENTINEL + "2"},
    )
    assert SENTINEL not in _audit_and_replay_text(s)


def test_npc_writes_store_only_receipts_and_redacted_audit(s: ContentSetup) -> None:
    options = s.gm.get(s.url("npcs/options")).json()
    species = options["species"][0]["species_id"]
    npc = _post(
        s,
        "npcs",
        {
            "name": "Mira",
            "summary": SENTINEL,
            "species_id": species,
            "size_category": "medium",
            "background": SENTINEL,
            "appearance": SENTINEL,
            "notes": SENTINEL,
        },
        status=201,
    )
    assert set(npc) == RECEIPT_KEYS | {"npc_id"}
    _update(
        s,
        f"npcs/{npc['npc_id']}/update",
        npc,
        {
            "name": "Mira",
            "summary": SENTINEL + "2",
            "species_id": species,
            "size_category": "medium",
            "notes": SENTINEL + "2",
        },
    )
    assert SENTINEL not in _audit_and_replay_text(s)


def test_knowledge_writes_store_only_receipts_and_redacted_audit(s: ContentSetup) -> None:
    claim = _post(
        s,
        "knowledge",
        {
            "statement": SENTINEL,
            "knowledge_type": "secret",
            "truth_status": "true",
            "sensitivity": "secret",
        },
        status=201,
    )
    assert set(claim) == RECEIPT_KEYS | {"knowledge_item_id"}
    _update(
        s,
        f"knowledge/{claim['knowledge_item_id']}/update",
        claim,
        {
            "statement": SENTINEL + " v2",
            "knowledge_type": "secret",
            "truth_status": "false",
            "sensitivity": "secret",
        },
    )
    assert SENTINEL not in _audit_and_replay_text(s)


def test_quest_writes_including_children_store_only_receipts(s: ContentSetup) -> None:
    quest = _post(s, "quests", {"name": "The Manifest", "summary": SENTINEL}, status=201)
    assert set(quest) == RECEIPT_KEYS | {"quest_id"}
    stage = _update(
        s,
        f"quests/{quest['quest_id']}/stages",
        quest,
        {"name": "Stage", "description": SENTINEL, "stage_type": "sequential"},
    )
    assert stage["quest_id"] == quest["quest_id"] and "record_id" in stage
    assert SENTINEL not in _audit_and_replay_text(s)


def test_world_timeline_and_campaign_descriptions_are_redacted_in_audit(s: ContentSetup) -> None:
    world = s.connection.execute(
        text("SELECT row_version FROM core.worlds WHERE world_id = :w"), {"w": s.world_id}
    ).scalar()
    response = s.gm.post_raw(
        f"/worlds/{s.world_id}/update",
        {"expected_row_version": world, "name": "World", "description": SENTINEL},
        key=s.gm.fresh_key(),
    )
    assert response.status_code == 200, response.text
    rows = s.connection.execute(
        text(
            "SELECT CAST(changed_fields AS text) FROM audit.change_log "
            "WHERE world_id = :w AND command_name = 'update_world'"
        ),
        {"w": s.world_id},
    ).scalars()
    texts = list(rows)
    assert texts and all(SENTINEL not in t for t in texts)


def test_a_replay_with_a_different_body_is_still_a_conflict(s: ContentSetup) -> None:
    key = s.gm.fresh_key()
    first = s.gm.post_raw(
        s.url("locations"), {"category": "region", "name": "A", "summary": None}, key=key
    )
    assert first.status_code == 201
    other = s.gm.post_raw(
        s.url("locations"), {"category": "region", "name": "B", "summary": None}, key=key
    )
    assert other.status_code == 409


def test_identifiers_in_the_receipt_are_the_only_ids_returned(s: ContentSetup) -> None:
    created = _post(
        s, "locations", {"category": "region", "name": "Id", "summary": None}, status=201
    )
    uuid.UUID(created["location_id"])
    assert created["created"] is True and created["changed"] is True
