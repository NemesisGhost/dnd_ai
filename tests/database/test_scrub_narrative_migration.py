"""Migration 135 (the one-time scrub of narrative in audit and replay rows), checkpoint 15.2A-4.

Decisions D-2 and D-28, decided by the owner in the working session: scrub audit `changed_fields` prose
(keep `reason`), rewrite replay bodies to receipts, mark every modified row, and record one
maintenance row. These tests run the real migration on a throwaway database populated at the
revision before it.
"""

import json
import uuid
from typing import Any

import pytest
from sqlalchemy import Connection, create_engine, text

from tests.database.test_organization_hierarchy_migration import _alembic
from tests.database.test_phase8_populated_upgrade import (
    _alembic_upgrade,
    _connect_args,
    _drop_database,
    _provision_database,
)

pytestmark = pytest.mark.database

BEFORE = "134_entity_source_links"
REVISION = "135_scrub_narrative_text"
REDACTED = {"redacted": True}


def insert_audit(
    conn: Connection, command: str, changed_fields: object, *, reason: str | None = None
) -> int:
    value = conn.execute(
        text("""
            INSERT INTO audit.change_log
                (change_action_id, schema_name, table_name, record_id, entity_id, world_id,
                 actor_service, command_name, correlation_id, reason, changed_fields,
                 previous_status, new_status)
            VALUES ((SELECT change_action_id FROM audit.change_actions WHERE code = 'updated'),
                    'core', 'entities', :r, :e, :w, 'test', :c, :corr, :reason,
                    CAST(:f AS jsonb), 'draft', 'proposed')
            RETURNING change_log_id
        """),
        {
            "r": uuid.uuid4(),
            "e": uuid.uuid4(),
            "w": uuid.uuid4(),
            "c": command,
            "corr": uuid.uuid4(),
            "reason": reason,
            "f": json.dumps(changed_fields),
        },
    ).scalar()
    return int(value)


def insert_replay(conn: Connection, status: int, body: object) -> uuid.UUID:
    value = conn.execute(
        text("""
            INSERT INTO security.idempotent_requests
                (actor_user_id, campaign_id, idempotency_key, request_fingerprint,
                 response_status_code, response_body, completed_at)
            VALUES (:u, :c, :k, :fp, :s, CAST(:b AS jsonb), now())
            RETURNING idempotent_request_id
        """),
        {
            "u": uuid.uuid4(),
            "c": uuid.uuid4(),
            "k": f"key-{uuid.uuid4().hex[:12]}",
            "fp": "fingerprint-" + uuid.uuid4().hex,
            "s": status,
            "b": json.dumps(body),
        },
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def audit_row(conn: Connection, row_id: int) -> dict[str, Any]:
    row = conn.execute(
        text("SELECT to_jsonb(c) AS row FROM audit.change_log c WHERE change_log_id = :i"),
        {"i": row_id},
    ).scalar()
    assert isinstance(row, dict)
    return row


def replay_row(conn: Connection, row_id: uuid.UUID) -> dict[str, Any]:
    row = conn.execute(
        text(
            "SELECT to_jsonb(r) AS row FROM security.idempotent_requests r "
            "WHERE idempotent_request_id = :i"
        ),
        {"i": row_id},
    ).scalar()
    assert isinstance(row, dict)
    return row


def without(row: dict[str, Any], *keys: str) -> dict[str, Any]:
    return {k: v for k, v in row.items() if k not in keys}


def populated(conn: Connection) -> dict[str, Any]:
    """Legacy-shaped rows, a post-15.2A-3 row, and rows the scrub must leave alone."""
    conn.execute(text("SET session_replication_role = replica"))
    ids: dict[str, Any] = {}
    ids["create_location"] = insert_audit(
        conn,
        "create_location",
        {
            "category": "settlement",
            "name": "Stonebridge",
            "summary": "A river town where the secret smuggler ring meets",
            "building_use": {"value": "x" * 1000, "truncated": True},
            "population": 900,
        },
        reason="GM note: why I made this",
    )
    ids["update_npc"] = insert_audit(
        conn,
        "update_npc",
        {
            "name": {"from": "Mira", "to": "Mira the Quiet"},
            "background": {"from": "Raised by smugglers", "to": "Raised by a priest"},
            "notes": {"from": None, "to": "Is secretly the duke's child"},
            "species_id": {"from": str(uuid.uuid4()), "to": str(uuid.uuid4())},
        },
    )
    ids["update_organization"] = insert_audit(
        conn,
        "update_organization",
        {"ideology": "Burn it all down", "kind": "political_faction", "reputation": 3},
    )
    ids["update_quest_post"] = insert_audit(
        conn,
        "update_quest",
        {
            "summary": {"from": None, "to": REDACTED},
            "gm_notes": {"from": None, "to": REDACTED},
            "name": "Redacted already",
        },
    )
    ids["create_knowledge_item"] = insert_audit(
        conn, "create_knowledge_item", {"statement": "The duke is dead", "truth_status": "true"}
    )
    ids["update_world"] = insert_audit(
        conn, "update_world", {"description": {"from": "Old lore", "to": "New lore"}}
    )
    ids["other_command"] = insert_audit(
        conn, "update_session", {"summary": "This command is not in the frozen list"}
    )
    ids["no_fields"] = insert_audit(conn, "update_location", None)
    ids["view"] = insert_replay(
        conn,
        201,
        {
            "npc_id": str(uuid.uuid4()),
            "name": "Mira",
            "background": "Secret backstory",
            "row_version": 4,
            "available_actions": ["update"],
            "blocked_actions": [],
            "canon_status": "draft",
            "changed": True,
        },
    )
    ids["view_update"] = insert_replay(
        conn,
        200,
        {
            "location_id": str(uuid.uuid4()),
            "summary": "Secret",
            "row_version": 2,
            "available_actions": [],
            "changed": False,
        },
    )
    ids["receipt"] = insert_replay(
        conn,
        201,
        {"npc_id": str(uuid.uuid4()), "row_version": 1, "created": True, "changed": True},
    )
    ids["access"] = insert_replay(
        conn,
        201,
        {
            "access_group_id": str(uuid.uuid4()),
            "name": "Tank players",
            "description": "Frontliners",
        },
    )
    ids["portrayal"] = insert_replay(
        conn,
        200,
        {
            "npc_id": str(uuid.uuid4()),
            "fields": {"voice": "Low and gravelly"},
            "field_labels": [{"name": "voice", "label": "Voice"}],
            "row_version": 3,
            "current_version": 2,
            "changed": True,
        },
    )
    return ids


@pytest.fixture
def database():  # type: ignore[no-untyped-def]
    admin_url, test_url = _provision_database()
    engine = create_engine(test_url, connect_args=_connect_args())
    try:
        _alembic_upgrade(test_url, BEFORE)
        yield test_url, engine
    finally:
        engine.dispose()
        _drop_database(admin_url, test_url)


def test_the_scrub_redacts_prose_marks_rows_and_preserves_everything_else(database) -> None:  # type: ignore[no-untyped-def]
    url, engine = database
    with engine.begin() as conn:
        ids = populated(conn)
    with engine.connect() as conn:
        before = {k: audit_row(conn, v) for k, v in ids.items() if isinstance(v, int)}
        replay_before = {k: replay_row(conn, v) for k, v in ids.items() if isinstance(v, uuid.UUID)}
    _alembic_upgrade(url, REVISION)
    with engine.connect() as conn:
        after = {k: audit_row(conn, v) for k, v in ids.items() if isinstance(v, int)}
        replay_after = {k: replay_row(conn, v) for k, v in ids.items() if isinstance(v, uuid.UUID)}

        # Prose becomes redacted; names, ids, numbers and enumerations are byte-identical.
        loc = after["create_location"]["changed_fields"]
        assert loc["summary"] == REDACTED and loc["building_use"] == REDACTED
        assert (loc["category"], loc["name"], loc["population"]) == (
            "settlement",
            "Stonebridge",
            900,
        )
        assert loc["_redacted_by"] == REVISION
        npc = after["update_npc"]["changed_fields"]
        assert npc["background"] == {"from": REDACTED, "to": REDACTED}
        assert npc["notes"] == {"from": None, "to": REDACTED}
        assert npc["name"] == before["update_npc"]["changed_fields"]["name"]
        assert npc["species_id"] == before["update_npc"]["changed_fields"]["species_id"]
        org = after["update_organization"]["changed_fields"]
        assert org["ideology"] == REDACTED and org["kind"] == "political_faction"
        assert org["reputation"] == 3
        assert after["create_knowledge_item"]["changed_fields"]["statement"] == REDACTED
        assert after["create_knowledge_item"]["changed_fields"]["truth_status"] == "true"
        assert after["update_world"]["changed_fields"]["description"] == {
            "from": REDACTED,
            "to": REDACTED,
        }

        # Every other column of a modified row is untouched, `reason` included.
        for key in ("create_location", "update_npc", "update_organization", "update_world"):
            assert without(after[key], "changed_fields") == without(before[key], "changed_fields")
        assert after["create_location"]["reason"] == "GM note: why I made this"

        # Rows with nothing to scrub are not changed and not marked.
        assert after["update_quest_post"] == before["update_quest_post"]
        assert after["other_command"] == before["other_command"]
        assert after["no_fields"] == before["no_fields"]

        # Replay bodies: views become receipts (created from the status code); the rest is intact.
        view = replay_after["view"]["response_body"]
        # An empty list holds no content and is kept; every name and nested view is dropped.
        assert set(view) == {
            "npc_id",
            "row_version",
            "canon_status",
            "changed",
            "created",
            "blocked_actions",
            "_redacted_by",
        }
        assert view["created"] is True and view["canon_status"] == "draft"
        assert replay_after["view_update"]["response_body"]["created"] is False
        assert "summary" not in replay_after["view_update"]["response_body"]
        portrayal = replay_after["portrayal"]["response_body"]
        assert "fields" not in portrayal and portrayal["current_version"] == 2
        for key in ("view", "view_update", "portrayal"):
            assert without(replay_after[key], "response_body") == without(
                replay_before[key], "response_body"
            )
        assert replay_after["receipt"] == replay_before["receipt"]
        assert replay_after["access"] == replay_before["access"]

        # One bounded maintenance row records what was done.
        maintenance = conn.execute(
            text(
                "SELECT actor_service, changed_fields FROM audit.change_log "
                "WHERE command_name = 'scrub_pre_15_2a_3_narrative'"
            )
        ).all()
        assert len(maintenance) == 1 and maintenance[0].actor_service == "migration"
        fields = maintenance[0].changed_fields
        assert fields["revision"] == REVISION
        assert fields["audit_rows_modified"] == {
            "create_knowledge_item": 1,
            "create_location": 1,
            "update_npc": 1,
            "update_organization": 1,
            "update_world": 1,
        }
        assert fields["audit_rows_modified_total"] == 5 and fields["replay_rows_rewritten"] == 3
        assert "Raised by" not in json.dumps(fields)


def test_downgrade_restores_nothing_and_a_second_run_finds_nothing_to_scrub(database) -> None:  # type: ignore[no-untyped-def]
    url, engine = database
    with engine.begin() as conn:
        ids = populated(conn)
    _alembic_upgrade(url, REVISION)
    downgraded = _alembic(url, "downgrade", BEFORE)
    assert downgraded.returncode == 0, downgraded.stderr
    with engine.connect() as conn:
        scrubbed = audit_row(conn, ids["update_npc"])["changed_fields"]
        assert scrubbed["background"] == {"from": REDACTED, "to": REDACTED}
    _alembic_upgrade(url, REVISION)
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT changed_fields FROM audit.change_log "
                "WHERE command_name = 'scrub_pre_15_2a_3_narrative' ORDER BY change_log_id"
            )
        ).all()
        assert len(rows) == 2
        assert rows[1].changed_fields["audit_rows_modified_total"] == 0
        assert rows[1].changed_fields["replay_rows_rewritten"] == 0


@pytest.mark.parametrize(
    "bad",
    [
        ("audit", "update_npc", {"background": 12345}),
        ("audit", "update_location", {"summary": ["a list is not prose"]}),
        ("audit", "update_location", {"summary": {"from": "x", "to": "y", "extra": 1}}),
        ("audit", "update_quest", {"surprise_key": "a sentence of narrative"}),
        ("audit", "create_npc", ["not", "an", "object"]),
        ("replay", 201, {"available_actions": [], "name": "No id to build a receipt from"}),
    ],
)
def test_an_unexpected_shape_aborts_and_changes_nothing(database, bad) -> None:  # type: ignore[no-untyped-def]
    url, engine = database
    with engine.begin() as conn:
        ids = populated(conn)
        if bad[0] == "audit":
            insert_audit(conn, bad[1], bad[2])
        else:
            insert_replay(conn, bad[1], bad[2])
    with engine.connect() as conn:
        before = {k: audit_row(conn, v) for k, v in ids.items() if isinstance(v, int)}
        replay_before = {k: replay_row(conn, v) for k, v in ids.items() if isinstance(v, uuid.UUID)}
    result = _alembic(url, "upgrade", REVISION)
    assert result.returncode != 0 and "unexpected shape" in (result.stderr + result.stdout)
    with engine.connect() as conn:
        assert {k: audit_row(conn, v) for k, v in ids.items() if isinstance(v, int)} == before
        assert {
            k: replay_row(conn, v) for k, v in ids.items() if isinstance(v, uuid.UUID)
        } == replay_before
        assert conn.execute(text("SELECT version_num FROM core.alembic_version")).scalar() == BEFORE
        assert (
            conn.execute(
                text(
                    "SELECT count(*) FROM audit.change_log "
                    "WHERE command_name = 'scrub_pre_15_2a_3_narrative'"
                )
            ).scalar()
            == 0
        )


def test_an_empty_database_migrates_cleanly_and_records_zero_counts(database) -> None:  # type: ignore[no-untyped-def]
    url, engine = database
    _alembic_upgrade(url, "head")
    with engine.connect() as conn:
        (row,) = conn.execute(
            text(
                "SELECT changed_fields FROM audit.change_log "
                "WHERE command_name = 'scrub_pre_15_2a_3_narrative'"
            )
        ).all()
        assert row.changed_fields["audit_rows_modified"] == {}
    checked = _alembic(url, "check")
    assert checked.returncode == 0, checked.stdout + checked.stderr
