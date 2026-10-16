"""Canonical definition revision history (migration 117, checkpoint 15.2R).

Every real change to a typed definition stores a full snapshot in
`core.entity_revisions`, built from the authored record itself -- never from
`audit.change_log`.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.exc import IntegrityError

from tests.authoring_support import AuthoringHarness, harness_fixture_factory
from tests.content_support import ContentSetup
from tests.database.test_organization_hierarchy_migration import _alembic
from tests.database.test_phase8_populated_upgrade import (
    _alembic_upgrade,
    _connect_args,
    _drop_database,
    _provision_database,
)

pytestmark = pytest.mark.database

NOTE = "GM-ONLY-REVISION-NOTE-4421"


@pytest.fixture
def harness(db_connection: Connection) -> Iterator[AuthoringHarness]:
    yield from harness_fixture_factory()(db_connection)


@pytest.fixture
def s(harness: AuthoringHarness, db_connection: Connection) -> ContentSetup:
    return ContentSetup(harness, db_connection)


def _revisions(s: ContentSetup, entity_id: str) -> list:
    return list(
        s.connection.execute(
            text(
                "SELECT row_version, revision_kind, snapshot, created_by_user_id, world_id "
                "FROM core.entity_revisions WHERE entity_id = :e ORDER BY row_version"
            ),
            {"e": entity_id},
        ).all()
    )


def _npc_body(s: ContentSetup, **extra: object) -> dict:
    species = s.gm.get(s.url("npcs/options")).json()["species"][0]["species_id"]
    return {
        "name": "Mira",
        "summary": None,
        "species_id": species,
        "size_category": "medium",
        "notes": NOTE,
        **extra,
    }


def _create_npc(s: ContentSetup) -> dict:
    created = s.gm.post(s.url("npcs"), _npc_body(s), key=s.gm.fresh_key())
    assert created.status_code == 201, created.text
    return created.json()


def test_a_create_stores_a_full_gm_only_snapshot_at_the_entity_version(s: ContentSetup) -> None:
    view = _create_npc(s)
    (revision,) = _revisions(s, view["npc_id"])
    assert revision.row_version == view["row_version"]
    assert revision.revision_kind == "created"
    assert revision.snapshot["name"] == "Mira"
    assert revision.snapshot["notes"] == NOTE  # GM-only content lives here, not in audit
    assert revision.created_by_user_id == s.gm.user_id and revision.world_id == s.world_id
    for presentation_only in ("available_actions", "blocked_actions", "field_locks", "row_version"):
        assert presentation_only not in revision.snapshot


def test_an_update_adds_a_revision_but_a_no_op_a_replay_and_a_stale_write_do_not(
    s: ContentSetup,
) -> None:
    created = _create_npc(s)
    npc_id = created["npc_id"]
    body = {
        **_npc_body(s, notes=NOTE + " v2"),
        "expected_row_version": created["row_version"],
        "change_note": None,
    }
    key = s.gm.fresh_key()
    first = s.gm.post(s.url(f"npcs/{npc_id}/update"), body, key=key)
    assert first.status_code == 200 and first.json()["changed"] is True
    revisions = _revisions(s, npc_id)
    assert [r.revision_kind for r in revisions] == ["created", "updated"]
    assert revisions[1].snapshot["notes"] == NOTE + " v2"
    assert revisions[0].snapshot["notes"] == NOTE  # the prior version is preserved

    # Replay: same key and body -> no second revision.
    s.gm.post_raw(s.url(f"npcs/{npc_id}/update"), body, key=key)
    assert len(_revisions(s, npc_id)) == 2
    # Stale write -> refused, no revision.
    stale = s.gm.post_raw(s.url(f"npcs/{npc_id}/update"), body, key=s.gm.fresh_key())
    assert stale.status_code == 409
    assert len(_revisions(s, npc_id)) == 2
    # Identical resubmission at the current version -> no-op, no revision.
    current = s.gm.get(s.url(f"npcs/{npc_id}")).json()
    same = {**body, "expected_row_version": current["row_version"]}
    again = s.gm.post(s.url(f"npcs/{npc_id}/update"), same, key=s.gm.fresh_key())
    assert again.json()["changed"] is False
    assert len(_revisions(s, npc_id)) == 2


def test_lifecycle_transitions_record_status_revisions(s: ContentSetup) -> None:
    created = _create_npc(s)
    s.publish(created["npc_id"], created["row_version"])
    revisions = _revisions(s, created["npc_id"])
    assert [r.revision_kind for r in revisions] == [
        "created",
        "lifecycle",
        "lifecycle",
        "lifecycle",
    ]
    assert revisions[-1].snapshot == {"canon_status": "canon", "lifecycle_status": "active"}


def test_a_quest_child_command_snapshots_the_whole_quest(s: ContentSetup) -> None:
    quest = s.gm.post(
        s.url("quests"), {"name": "The Manifest", "summary": None}, key=s.gm.fresh_key()
    ).json()
    stage = s.gm.post(
        s.url(f"quests/{quest['quest_id']}/stages"),
        {
            "expected_row_version": quest["row_version"],
            "name": "Stage",
            "description": NOTE,
            "stage_type": "sequential",
        },
        key=s.gm.fresh_key(),
    )
    assert stage.status_code == 200, stage.text
    revisions = _revisions(s, quest["quest_id"])
    assert [r.revision_kind for r in revisions] == ["created", "updated"]
    assert revisions[0].snapshot["stages"] == []
    assert [st["name"] for st in revisions[1].snapshot["stages"]] == ["Stage"]


def test_a_revision_cannot_be_updated(s: ContentSetup) -> None:
    created = _create_npc(s)
    with pytest.raises(IntegrityError, match="append-only"), s.connection.begin_nested():
        s.connection.execute(
            text("UPDATE core.entity_revisions SET snapshot = '{}' WHERE entity_id = :e"),
            {"e": created["npc_id"]},
        )


def test_a_revision_must_belong_to_its_entitys_world(s: ContentSetup) -> None:
    created = _create_npc(s)
    with pytest.raises(IntegrityError, match="does not match"), s.connection.begin_nested():
        s.connection.execute(
            text("""
                INSERT INTO core.entity_revisions
                    (entity_id, world_id, row_version, revision_kind, snapshot)
                VALUES (:e, :w, 999, 'updated', '{}')
            """),
            {"e": created["npc_id"], "w": s.other_world_id},
        )


def test_application_roles_cannot_alter_revisions_and_the_reporting_role_cannot_read(
    s: ContentSetup,
) -> None:
    expected = {"SELECT": True, "INSERT": True, "UPDATE": False, "DELETE": False}
    for privilege, allowed in expected.items():
        granted = s.connection.execute(
            text("SELECT has_table_privilege('app_read_write', 'core.entity_revisions', :p)"),
            {"p": privilege},
        ).scalar()
        assert granted is allowed, privilege
    reporting = s.connection.execute(
        text("SELECT has_table_privilege('app_read_only', 'core.entity_revisions', 'SELECT')")
    ).scalar()
    assert reporting is False


def test_deleting_a_draft_removes_its_revisions_through_the_cascade(s: ContentSetup) -> None:
    created = _create_npc(s)
    npc_id = created["npc_id"]
    assert _revisions(s, npc_id)
    deleted = s.gm.post(
        s.lifecycle(npc_id, "/delete-draft"),
        {"expected_row_version": created["row_version"], "reason": "typo"},
        key=s.gm.fresh_key(),
    )
    assert deleted.status_code == 200, deleted.text
    assert _revisions(s, npc_id) == []


def test_revision_capture_never_reads_audit() -> None:
    """Snapshots come from the authored record (the typed views), not from
    `audit.change_log`: the capture module has no audit dependency at all."""
    source = (
        Path(__file__).resolve().parents[2] / "src" / "dnd_ai" / "commands" / "_revisions.py"
    ).read_text(encoding="utf-8")
    for forbidden in ("FROM audit", "JOIN audit", "record_change_log", "INSERT INTO audit"):
        assert forbidden not in source, forbidden


def _regclass(connection: Connection) -> object:
    return connection.execute(text("SELECT to_regclass('core.entity_revisions')")).scalar()


def test_the_migration_round_trips() -> None:
    admin_url, test_url = _provision_database()
    try:
        _alembic_upgrade(test_url, "116_sensitive_read_action")
        engine = create_engine(test_url, connect_args=_connect_args())
        with engine.connect() as connection:
            assert _regclass(connection) is None
        _alembic_upgrade(test_url, "117_entity_revisions")
        with engine.connect() as connection:
            assert _regclass(connection) is not None
        downgraded = _alembic(test_url, "downgrade", "116_sensitive_read_action")
        assert downgraded.returncode == 0, downgraded.stderr
        with engine.connect() as connection:
            assert _regclass(connection) is None
        _alembic_upgrade(test_url, "head")
        checked = _alembic(test_url, "check")
        assert checked.returncode == 0, checked.stdout + checked.stderr
        engine.dispose()
    finally:
        _drop_database(admin_url, test_url)
