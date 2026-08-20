"""Populated-upgrade proof for revision 076_relationships_and_orgs's
narrative.event_effects.target_relationship_id / interaction.consequences.
resulting_relationship_state_id columns and the world/timeline-agreement
guard functions extended to cover them.

Every other test in tests/database runs against the shared session-scoped
database, already migrated straight to head — it can never prove anything
about what happens to a database that had real event_effects/consequences
rows *before* revision 076 added the relationship columns and extended
narrative.enforce_event_effect_target_world()/interaction.
enforce_consequence_world(). This file follows tests/database/
test_phase5_populated_upgrade.py's pattern: provision a throwaway database,
pause mid-upgrade at revision 075_phase7_reparent_guards (the last revision
before 076), insert legacy rows using only the target/result columns that
existed at that point, continue the upgrade to head, and assert on what
actually happened.
"""

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import Connection, Engine, create_engine, make_url, text
from sqlalchemy.exc import IntegrityError, InternalError, ProgrammingError

from tests.factories import (
    make_character,
    make_consequence,
    make_event,
    make_event_effect,
    make_interaction,
    make_objective_state,
    make_quest,
    make_quest_objective,
    make_quest_stage,
    make_relationship,
    make_relationship_state,
    make_timeline,
    make_world,
    make_world_time,
)

pytestmark = pytest.mark.database

CONSTRAINT_ERRORS = (IntegrityError, InternalError, ProgrammingError)

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "database" / "alembic.ini"

# Matches tests/conftest.py's _MIGRATION_SUBPROCESS_TIMEOUT_SECONDS — a
# hung alembic subprocess must fail this test clearly (subprocess.
# TimeoutExpired) rather than freeze the whole test session forever with
# no recovery, which is what an un-bounded subprocess.run() here previously
# allowed.
_ALEMBIC_SUBPROCESS_TIMEOUT_SECONDS = 300

# Matches tests/conftest.py's _DB_CONNECT_TIMEOUT_SECONDS/_connect_args() —
# every create_engine() call below previously had no connect_timeout at
# all, so a stalled TCP handshake (observed in practice: py-spy showed a
# connect() blocked indefinitely in psycopg's own select() wait, with no
# bound to ever fail it) froze the whole test session with no recovery,
# rather than raising a clear, fast connection error.
_CONNECT_TIMEOUT_SECONDS = 10


def _connect_args() -> dict[str, object]:
    return {"connect_timeout": _CONNECT_TIMEOUT_SECONDS}


K0 = 100


def _require_admin_url() -> str:
    admin_url_raw = os.environ.get("DATABASE_URL")
    if not admin_url_raw:
        pytest.skip(
            "DATABASE_URL is not set — these tests provision their own throwaway "
            "database and need an admin/bootstrap connection, same precondition as "
            "tests/conftest.py::postgres_engine."
        )
    return admin_url_raw


def _provision_database() -> tuple[str, str]:
    """Creates a fresh, unmigrated throwaway database. Returns (admin_url, test_url)."""
    admin_url = make_url(_require_admin_url())
    db_name = f"dnd_ai_phase8_upgrade_{uuid.uuid4().hex[:12]}"
    test_url = admin_url.set(database=db_name)

    admin_engine = create_engine(
        admin_url, isolation_level="AUTOCOMMIT", connect_args=_connect_args()
    )
    with admin_engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    admin_engine.dispose()

    return (
        admin_url.render_as_string(hide_password=False),
        test_url.render_as_string(hide_password=False),
    )


def _drop_database(admin_url: str, test_url: str) -> None:
    db_name = make_url(test_url).database
    admin_engine = create_engine(
        make_url(admin_url), isolation_level="AUTOCOMMIT", connect_args=_connect_args()
    )
    with admin_engine.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))
    admin_engine.dispose()


def _alembic_upgrade(database_url: str, target: str) -> None:
    # sys.executable -m alembic, not the "alembic" console-script entry
    # point — see tests/conftest.py's _run_alembic_upgrade for the same
    # choice and why (doesn't depend on a separate PATH-resolved
    # executable, and avoids that shim's own extra process-spawn layer).
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_INI), "upgrade", target],
        check=True,
        cwd=REPO_ROOT,
        env={**os.environ, "DATABASE_URL": database_url},
        timeout=_ALEMBIC_SUBPROCESS_TIMEOUT_SECONDS,
    )


def _insert_legacy_event_effect(
    conn: Connection, event_id: uuid.UUID, quest_objective_id: uuid.UUID
) -> uuid.UUID:
    """A pre-076 event_effects row using target_quest_objective_id — the
    newest target_* column that existed before target_relationship_id."""
    value = conn.execute(
        text("""
            INSERT INTO narrative.event_effects
                (event_id, target_quest_objective_id, target_component,
                 previous_value, new_value)
            VALUES (:event, :objective, 'objective_status_id', '"active"', '"completed"')
            RETURNING event_effect_id
        """),
        {"event": event_id, "objective": quest_objective_id},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def _insert_legacy_consequence(
    conn: Connection, interaction_id: uuid.UUID, objective_state_id: uuid.UUID
) -> uuid.UUID:
    """A pre-076 consequences row using resulting_quest_objective_state_id —
    the newest typed result column that existed before
    resulting_relationship_state_id."""
    value = conn.execute(
        text("""
            INSERT INTO interaction.consequences
                (interaction_id, consequence_type, resulting_quest_objective_state_id)
            VALUES (:interaction, 'quest_change', :objective_state)
            RETURNING consequence_id
        """),
        {"interaction": interaction_id, "objective_state": objective_state_id},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def test_a_populated_revision_075_database_upgrades_cleanly_through_076() -> None:
    admin_url, test_url = _provision_database()
    try:
        _alembic_upgrade(test_url, "075_phase7_reparent_guards")

        setup_engine = create_engine(test_url, connect_args=_connect_args())
        with setup_engine.begin() as conn:
            world = make_world(conn, slug="phase8-populated-upgrade")
            other_world = make_world(conn, slug="phase8-populated-upgrade-other")
            timeline = make_timeline(conn, world, is_primary=True)
            timeline_b = make_timeline(conn, world)
            t0 = make_world_time(conn, world, K0)

            quest = make_quest(conn, world)
            stage = make_quest_stage(conn, quest)
            objective = make_quest_objective(conn, stage)
            objective_state = make_objective_state(conn, timeline, objective)

            event = make_event(conn, world, timeline, t0)
            legacy_event_effect_id = _insert_legacy_event_effect(conn, event, objective)

            interaction = make_interaction(conn, timeline, t0)
            legacy_consequence_id = _insert_legacy_consequence(conn, interaction, objective_state)
        setup_engine.dispose()

        _alembic_upgrade(test_url, "head")

        engine = create_engine(test_url, connect_args=_connect_args())
        try:
            _assert_legacy_rows_survived_unchanged(
                engine, legacy_event_effect_id, objective, legacy_consequence_id, objective_state
            )
            _assert_new_relationship_columns_are_usable(engine, world, timeline)
            _assert_at_most_one_target_still_rejects_conflicts(engine, world, timeline, t0)
            _assert_event_effect_relationship_target_must_share_its_world(
                engine, world, other_world, timeline, t0
            )
            _assert_consequence_relationship_state_must_share_its_timeline(
                engine, world, timeline, timeline_b, t0
            )
        finally:
            engine.dispose()
    finally:
        _drop_database(admin_url, test_url)


def _assert_legacy_rows_survived_unchanged(
    engine: Engine,
    legacy_event_effect_id: uuid.UUID,
    objective: uuid.UUID,
    legacy_consequence_id: uuid.UUID,
    objective_state: uuid.UUID,
) -> None:
    with engine.connect() as conn:
        effect_row = conn.execute(
            text("""
                SELECT target_quest_objective_id, target_component, previous_value, new_value,
                       target_relationship_id
                FROM narrative.event_effects WHERE event_effect_id = :id
            """),
            {"id": legacy_event_effect_id},
        ).one()
        assert effect_row.target_quest_objective_id == objective
        assert effect_row.target_component == "objective_status_id"
        assert effect_row.previous_value == "active"
        assert effect_row.new_value == "completed"
        assert effect_row.target_relationship_id is None

        consequence_row = conn.execute(
            text("""
                SELECT consequence_type, resulting_quest_objective_state_id,
                       resulting_relationship_state_id
                FROM interaction.consequences WHERE consequence_id = :id
            """),
            {"id": legacy_consequence_id},
        ).one()
        assert consequence_row.consequence_type == "quest_change"
        assert consequence_row.resulting_quest_objective_state_id == objective_state
        assert consequence_row.resulting_relationship_state_id is None


def _assert_new_relationship_columns_are_usable(
    engine: Engine, world: uuid.UUID, timeline: uuid.UUID
) -> None:
    with engine.begin() as conn:
        relationship = make_relationship(conn, world)
        relationship_state = make_relationship_state(conn, timeline, relationship)
        t0 = make_world_time(conn, world, K0 + 1)

        event = make_event(conn, world, timeline, t0)
        event_effect_id = make_event_effect(conn, event, target_relationship_id=relationship)

        interaction = make_interaction(conn, timeline, t0)
        consequence_id = make_consequence(
            conn,
            interaction,
            consequence_type="relationship_change",
            resulting_relationship_state_id=relationship_state,
        )

        effect_row = conn.execute(
            text(
                "SELECT target_relationship_id FROM narrative.event_effects "
                "WHERE event_effect_id = :id"
            ),
            {"id": event_effect_id},
        ).one()
        assert effect_row.target_relationship_id == relationship

        consequence_row = conn.execute(
            text(
                "SELECT resulting_relationship_state_id FROM interaction.consequences "
                "WHERE consequence_id = :id"
            ),
            {"id": consequence_id},
        ).one()
        assert consequence_row.resulting_relationship_state_id == relationship_state


def _assert_at_most_one_target_still_rejects_conflicts(
    engine: Engine, world: uuid.UUID, timeline: uuid.UUID, t0: uuid.UUID
) -> None:
    with engine.begin() as conn:
        relationship = make_relationship(conn, world)
        npc = make_character(conn, world, entity_type_code="npc")
        event = make_event(conn, world, timeline, t0)

        with pytest.raises(IntegrityError) as exc:
            make_event_effect(
                conn, event, target_relationship_id=relationship, target_entity_id=npc
            )
        assert "ck_event_effects_at_most_one_target" in str(exc.value)


def _assert_event_effect_relationship_target_must_share_its_world(
    engine: Engine, world: uuid.UUID, other_world: uuid.UUID, timeline: uuid.UUID, t0: uuid.UUID
) -> None:
    with engine.begin() as conn:
        foreign_relationship = make_relationship(conn, other_world)
        event = make_event(conn, world, timeline, t0)

        with pytest.raises(CONSTRAINT_ERRORS) as exc:
            make_event_effect(conn, event, target_relationship_id=foreign_relationship)
        assert "belongs to world" in str(exc.value)


def _assert_consequence_relationship_state_must_share_its_timeline(
    engine: Engine, world: uuid.UUID, timeline: uuid.UUID, timeline_b: uuid.UUID, t0: uuid.UUID
) -> None:
    with engine.begin() as conn:
        relationship = make_relationship(conn, world)
        foreign_relationship_state = make_relationship_state(conn, timeline_b, relationship)
        interaction = make_interaction(conn, timeline, t0)

        with pytest.raises(CONSTRAINT_ERRORS) as exc:
            make_consequence(
                conn,
                interaction,
                consequence_type="relationship_change",
                resulting_relationship_state_id=foreign_relationship_state,
            )
        assert "belongs to timeline" in str(exc.value)
