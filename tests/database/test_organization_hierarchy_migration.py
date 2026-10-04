"""Organization-hierarchy cycle guard (revision 113, Phase 15.1).

The shared test database is already at head, so most checks run against it and
roll back. The upgrade pre-flight and the downgrade/re-upgrade round trip need a
database paused at revision 112, so they provision a throwaway one (the same
pattern as test_phase8_populated_upgrade.py).
"""

import subprocess
import sys
import threading

import pytest
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.exc import IntegrityError, InternalError, ProgrammingError

from tests.database.test_phase8_populated_upgrade import (
    ALEMBIC_INI,
    REPO_ROOT,
    _alembic_upgrade,
    _connect_args,
    _drop_database,
    _provision_database,
)
from tests.factories import make_location, make_organization, make_user, make_world

pytestmark = pytest.mark.database

REJECTED = (IntegrityError, InternalError, ProgrammingError)


def _set_parent(connection: Connection, child, parent) -> None:  # type: ignore[no-untyped-def]
    connection.execute(
        text(
            "UPDATE world.organizations SET parent_organization_id = :p WHERE organization_id = :c"
        ),
        {"p": parent, "c": child},
    )


def test_a_two_hop_cycle_is_refused(db_connection: Connection) -> None:
    world = make_world(db_connection, "org-cycle-2")
    a = make_organization(db_connection, world, name="A")
    b = make_organization(db_connection, world, name="B", parent_organization_id=a)
    with pytest.raises(REJECTED) as raised, db_connection.begin_nested():
        _set_parent(db_connection, a, b)
    assert "hierarchy cycle" in str(raised.value)


def test_a_three_hop_cycle_is_refused(db_connection: Connection) -> None:
    world = make_world(db_connection, "org-cycle-3")
    a = make_organization(db_connection, world, name="A")
    b = make_organization(db_connection, world, name="B", parent_organization_id=a)
    c = make_organization(db_connection, world, name="C", parent_organization_id=b)
    with pytest.raises(REJECTED) as raised, db_connection.begin_nested():
        _set_parent(db_connection, a, c)
    assert "hierarchy cycle" in str(raised.value)


def test_a_self_parent_is_refused(db_connection: Connection) -> None:
    world = make_world(db_connection, "org-self")
    a = make_organization(db_connection, world, name="A")
    with pytest.raises(IntegrityError) as raised, db_connection.begin_nested():
        _set_parent(db_connection, a, a)
    # The BEFORE trigger fires ahead of the CHECK; either is a refusal.
    assert "hierarchy cycle" in str(raised.value) or "parent_not_self" in str(raised.value)


def test_a_cross_world_parent_is_still_refused(db_connection: Connection) -> None:
    mine = make_organization(db_connection, make_world(db_connection, "org-w1"), name="Mine")
    theirs = make_organization(db_connection, make_world(db_connection, "org-w2"), name="Theirs")
    with pytest.raises(REJECTED), db_connection.begin_nested():
        _set_parent(db_connection, mine, theirs)


def test_legitimate_reparenting_and_deep_chains_are_accepted(db_connection: Connection) -> None:
    world = make_world(db_connection, "org-ok")
    root = make_organization(db_connection, world, name="Root")
    previous = root
    chain = []
    for index in range(25):
        previous = make_organization(
            db_connection, world, name=f"Level {index}", parent_organization_id=previous
        )
        chain.append(previous)
    other = make_organization(db_connection, world, name="Other root")
    _set_parent(db_connection, chain[10], other)
    _set_parent(db_connection, chain[10], None)
    _set_parent(db_connection, root, None)


def test_inserting_with_a_parent_in_another_branch_is_accepted(db_connection: Connection) -> None:
    world = make_world(db_connection, "org-insert")
    parent = make_organization(db_connection, world, name="Parent")
    make_organization(db_connection, world, name="Child", parent_organization_id=parent)
    make_location(db_connection, world)


def test_the_guard_function_is_commented(db_connection: Connection) -> None:
    comment = db_connection.execute(
        text("SELECT obj_description('world.enforce_organization_no_cycle()'::regprocedure)")
    ).scalar()
    assert comment and "advisory lock" in comment


# --- throwaway-database checks: pre-flight and round trip -----------------------------------


def _alembic(database_url: str, *args: str) -> subprocess.CompletedProcess[str]:
    import os

    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_INI), *args],
        cwd=REPO_ROOT,
        env={**os.environ, "DATABASE_URL": database_url},
        capture_output=True,
        text=True,
        timeout=300,
    )


def _trigger_exists(engine: Engine) -> bool:
    with engine.connect() as connection:
        return bool(
            connection.execute(
                text(
                    "SELECT EXISTS (SELECT 1 FROM pg_trigger "
                    "WHERE tgname = 'tr_organizations_enforce_no_cycle' AND NOT tgisinternal)"
                )
            ).scalar()
        )


def test_upgrade_refuses_to_install_over_an_existing_cycle_then_round_trips() -> None:
    admin_url, test_url = _provision_database()
    try:
        _alembic_upgrade(test_url, "112_actor_idempotent_requests")
        setup = create_engine(test_url, connect_args=_connect_args())
        with setup.begin() as connection:
            world = make_world(connection, "org-preflight")
            a = make_organization(connection, world, name="A")
            b = make_organization(connection, world, name="B", parent_organization_id=a)
            c = make_organization(connection, world, name="C", parent_organization_id=b)
            # No guard exists yet at 112, so the corrupt cycle can be written.
            _set_parent(connection, a, c)
            make_user(connection)

        blocked = _alembic(test_url, "upgrade", "113_organization_cycle_guard")
        assert blocked.returncode != 0
        assert "already part of a parent cycle" in blocked.stderr + blocked.stdout
        assert str(a) in blocked.stderr + blocked.stdout
        assert not _trigger_exists(setup)

        with setup.begin() as connection:
            _set_parent(connection, a, None)
        _alembic_upgrade(test_url, "113_organization_cycle_guard")
        assert _trigger_exists(setup)

        downgraded = _alembic(test_url, "downgrade", "112_actor_idempotent_requests")
        assert downgraded.returncode == 0, downgraded.stderr
        assert not _trigger_exists(setup)
        with setup.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT to_regprocedure('world.enforce_organization_no_cycle()')")
                ).scalar()
                is None
            )

        _alembic_upgrade(test_url, "head")
        assert _trigger_exists(setup)
        checked = _alembic(test_url, "check")
        assert checked.returncode == 0, checked.stdout + checked.stderr
        setup.dispose()
    finally:
        _drop_database(admin_url, test_url)


# --- real concurrency ---------------------------------------------------------------------------


def test_two_concurrent_opposing_reparents_commit_exactly_one(postgres_engine: Engine) -> None:
    """Both transactions pass the CHECK and the same-world trigger on their own
    snapshot; the per-world advisory lock makes the second see the first's
    committed parent and refuse the cycle."""
    with postgres_engine.begin() as setup:
        world = make_world(setup, "org-race")
        a = make_organization(setup, world, name="Race A")
        b = make_organization(setup, world, name="Race B")

    first = postgres_engine.connect()
    first_tx = first.begin()
    _set_parent(first, a, b)  # holds the advisory lock until commit

    outcome: dict[str, object] = {}

    def second_reparent() -> None:
        try:
            with postgres_engine.begin() as connection:
                _set_parent(connection, b, a)
            outcome["result"] = "committed"
        except REJECTED:
            outcome["result"] = "refused"

    thread = threading.Thread(target=second_reparent)
    thread.start()
    from tests.database.test_authoring_concurrency import _wait_until_blocked

    try:
        _wait_until_blocked(postgres_engine, "wait_event = 'advisory'")
        first_tx.commit()
    finally:
        first.close()
    thread.join(timeout=20)
    assert not thread.is_alive()
    assert outcome["result"] == "refused"
    with postgres_engine.connect() as verify:
        parents = {
            row.organization_id: row.parent_organization_id
            for row in verify.execute(
                text(
                    "SELECT organization_id, parent_organization_id FROM world.organizations "
                    "WHERE organization_id IN (:a, :b)"
                ),
                {"a": a, "b": b},
            )
        }
    assert parents == {a: b, b: None}
    with postgres_engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        cleanup.execute(
            text("DELETE FROM world.organizations WHERE organization_id IN (:a, :b)"),
            {"a": a, "b": b},
        )
        cleanup.execute(text("DELETE FROM core.entities WHERE world_id = :w"), {"w": world})
        cleanup.execute(text("DELETE FROM core.worlds WHERE world_id = :w"), {"w": world})
