"""scripts/setup_phase15_world_content.py: authored through the production
commands, idempotent, and bounded to the Phase 13C development world."""

import uuid

import pytest
import setup_phase13c_dev_data
import setup_phase15_world_content as p15
from sqlalchemy import Connection, text

from tests.database.test_setup_phase13c_dev_data import _TEST_DEV_PASSWORD, _make_local_account

pytestmark = pytest.mark.database

_COMMANDS = (
    "create_location",
    "create_organization",
    "create_religion",
    "create_npc",
    "create_quest",
    "add_quest_stage",
    "add_quest_objective",
    "create_knowledge_item",
    "submit_entity_for_review",
    "approve_entity",
    "publish_entity_as_canon",
    "archive_entity",
    "supersede_entity",
)


@pytest.fixture
def owner(db_connection: Connection) -> uuid.UUID:
    user_id = _make_local_account(db_connection)
    setup_phase13c_dev_data._run(db_connection, user_id=user_id, dev_password=_TEST_DEV_PASSWORD)
    return user_id


def _audit_rows(connection: Connection) -> int:
    value = connection.execute(
        text("SELECT count(*) FROM audit.change_log WHERE command_name = ANY(:names)"),
        {"names": list(_COMMANDS)},
    ).scalar()
    assert isinstance(value, int)
    return value


def _statuses(connection: Connection) -> dict[str, tuple[str, str]]:
    rows = connection.execute(
        text("""
            SELECT e.canonical_name, cs.code AS canon, ls.code AS lifecycle
            FROM core.entities e
            JOIN core.canon_statuses cs ON cs.canon_status_id = e.canon_status_id
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = e.lifecycle_status_id
            WHERE e.canonical_name LIKE '[P15 dev]%'
        """)
    ).all()
    return {str(r.canonical_name).removeprefix("[P15 dev] "): (r.canon, r.lifecycle) for r in rows}


def test_first_run_creates_the_content_and_a_rerun_changes_nothing(
    db_connection: Connection, owner: uuid.UUID
) -> None:
    first = p15._run(db_connection, user_id=owner)
    assert any("[created]" in line for line in first.lines)
    rows_after_first = _audit_rows(db_connection)
    entities_after_first = _statuses(db_connection)
    assert rows_after_first > 0

    second = p15._run(db_connection, user_id=owner)
    assert all("[created]" not in line for line in second.lines), second.lines
    assert len(second.lines) == len(first.lines)
    assert _audit_rows(db_connection) == rows_after_first
    assert _statuses(db_connection) == entities_after_first


def test_the_content_has_the_planned_lifecycle_states(
    db_connection: Connection, owner: uuid.UUID
) -> None:
    p15._run(db_connection, user_id=owner)
    states = _statuses(db_connection)
    assert states["Ashmark"] == ("canon", "active")
    assert states["Brindlehaven"] == ("canon", "active")
    assert states["Customs House"] == ("canon", "active")
    assert states["Harbor District"] == ("draft", "active")
    assert states["Sunken Reef"][1] == "archived"
    assert states["Old Keep"][0] == "superseded" and states["New Keep"] == ("canon", "active")
    assert states["Brindlehaven Council"] == ("canon", "active")
    assert states["Dockhands Guild"] == ("draft", "active")
    assert states["The Tidewardens"] == ("canon", "active")
    assert states["Tidewarden Chapter"] == ("canon", "active")
    assert states["Harbormaster Lysa"] == ("canon", "active")
    assert states["Stowaway Pell"] == ("draft", "active")
    assert states["The Missing Manifest"] == ("canon", "active")
    assert states["Whispers on the Quay"] == ("draft", "active")
    assert states["The harbormaster takes bribes."] == ("canon", "active")
    assert states["The customs ledger was burned."] == ("draft", "active")


def test_every_authored_record_has_provenance_and_the_quest_is_complete(
    db_connection: Connection, owner: uuid.UUID
) -> None:
    p15._run(db_connection, user_id=owner)
    bad = db_connection.execute(
        text("""
            SELECT count(*) FROM core.entities e
            LEFT JOIN core.sources s ON s.source_id = e.source_id
            LEFT JOIN core.source_types st ON st.source_type_id = s.source_type_id
            WHERE e.canonical_name LIKE '[P15 dev]%' AND st.code IS DISTINCT FROM 'gm_entry'
        """)
    ).scalar()
    assert bad == 0
    shape = db_connection.execute(
        text("""
            SELECT count(DISTINCT qs.quest_stage_id), count(qo.quest_objective_id)
            FROM core.entities e
            JOIN narrative.quest_stages qs ON qs.quest_id = e.entity_id
            LEFT JOIN narrative.quest_objectives qo ON qo.quest_stage_id = qs.quest_stage_id
            WHERE e.canonical_name = '[P15 dev] The Missing Manifest'
        """)
    ).one()
    assert tuple(shape) == (2, 3)


def test_it_creates_no_world_campaign_or_membership(
    db_connection: Connection, owner: uuid.UUID
) -> None:
    tables = (
        "core.worlds",
        "campaign.timelines",
        "campaign.campaigns",
        "security.world_memberships",
        "security.campaign_memberships",
        "security.membership_roles",
    )

    def counts() -> list[object]:
        return [db_connection.execute(text(f"SELECT count(*) FROM {t}")).scalar() for t in tables]

    before = counts()
    p15._run(db_connection, user_id=owner)
    assert counts() == before


def test_it_requires_the_phase_13c_world(db_connection: Connection) -> None:
    user_id = _make_local_account(db_connection)
    with pytest.raises(SystemExit, match="setup_phase13c_dev_data"):
        p15._run(db_connection, user_id=user_id)


def test_an_account_without_canon_edit_is_refused_and_nothing_is_written(
    db_connection: Connection, owner: uuid.UUID
) -> None:
    # `_make_local_account` uses one fixed login name; free it for a second account.
    db_connection.execute(
        text("UPDATE security.external_identities SET subject = 'dev-owner' WHERE user_id = :u"),
        {"u": owner},
    )
    other = _make_local_account(
        db_connection, display_name="Not a member", is_platform_administrator=False
    )
    before = _audit_rows(db_connection)
    with pytest.raises(SystemExit, match="canon.edit"):
        p15._run(db_connection, user_id=other)
    assert _audit_rows(db_connection) == before
    assert _statuses(db_connection) == {}


def test_a_remote_target_is_refused_before_any_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(setup_phase13c_dev_data.settings, "environment", "local")
    monkeypatch.delenv("DND_AI_ALLOW_NONLOCAL_DEV_DATA", raising=False)
    monkeypatch.setattr(
        setup_phase13c_dev_data,
        "_database_url",
        lambda: "postgresql+psycopg://app:secret@db.example.com:5432/dnd_ai",
    )

    def no_connection(*args: object, **kwargs: object) -> None:
        raise AssertionError("connected before the safety guard refused")

    monkeypatch.setattr(p15, "create_engine", no_connection)
    with pytest.raises(SystemExit):
        p15.main(["--user-id", str(uuid.uuid4())])
