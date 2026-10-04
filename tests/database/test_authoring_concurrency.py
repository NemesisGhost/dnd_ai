"""Real-PostgreSQL concurrency races for the Phase 14 authoring commands.

Each test uses separate committed connections and a genuine lock wait (a
second transaction blocks on the first's row lock until it commits), then
verifies the final state from a third connection. Committed fixtures are
removed explicitly afterward.
"""

import threading
import time
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from dnd_ai.api.app import create_app
from dnd_ai.api.auth import get_authenticated_user_id
from dnd_ai.api.deps import get_engine
from dnd_ai.commands.worlds import update_world
from dnd_ai.domain.authoring import StaleWriteError
from tests.builders import dnd5e_ids, make_authored_world
from tests.factories import make_user, oidc_principal

pytestmark = pytest.mark.database


def _purge_user_worlds(engine: Engine, user_id: uuid.UUID) -> None:
    with engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        world_ids = (
            cleanup.execute(
                text("SELECT world_id FROM security.world_memberships WHERE user_id = :u"),
                {"u": user_id},
            )
            .scalars()
            .all()
        )
        for world_id in world_ids:
            cleanup.execute(
                text("DELETE FROM audit.change_log WHERE world_id = :w"), {"w": world_id}
            )
            cleanup.execute(
                text(
                    "DELETE FROM campaign.campaigns WHERE timeline_id IN "
                    "(SELECT timeline_id FROM campaign.timelines WHERE world_id = :w)"
                ),
                {"w": world_id},
            )
            cleanup.execute(
                text("DELETE FROM security.world_memberships WHERE world_id = :w"), {"w": world_id}
            )
            cleanup.execute(
                text("DELETE FROM campaign.timelines WHERE world_id = :w"), {"w": world_id}
            )
            cleanup.execute(
                text("DELETE FROM core.world_times WHERE world_id = :w"), {"w": world_id}
            )
            cleanup.execute(
                text("DELETE FROM rules.world_rulesets WHERE world_id = :w"), {"w": world_id}
            )
            cleanup.execute(text("DELETE FROM core.worlds WHERE world_id = :w"), {"w": world_id})
        cleanup.execute(
            text("DELETE FROM security.actor_idempotent_requests WHERE actor_user_id = :u"),
            {"u": user_id},
        )
        cleanup.execute(
            text("DELETE FROM audit.change_log WHERE actor_user_id = :u"), {"u": user_id}
        )
        cleanup.execute(text("DELETE FROM security.users WHERE user_id = :u"), {"u": user_id})


@pytest.fixture
def committed_owner(postgres_engine: Engine) -> Iterator[uuid.UUID]:
    with postgres_engine.begin() as setup:
        user_id = make_user(setup, "Race Owner")
    yield user_id
    _purge_user_worlds(postgres_engine, user_id)


def _wait_until_blocked(engine: Engine, predicate_sql: str, timeout: float = 10.0) -> None:
    """Poll pg_stat_activity (from a third connection) until a backend is
    waiting on a lock matching `predicate_sql`."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with engine.connect() as probe:
            waiting = probe.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE wait_event_type = 'Lock' AND " + predicate_sql
                )
            ).scalar()
        if waiting:
            return
        time.sleep(0.05)
    raise AssertionError("no backend ever blocked on the expected lock")


def test_two_updates_with_the_same_expected_version_one_wins_one_is_stale(
    postgres_engine: Engine, committed_owner: uuid.UUID
) -> None:
    """Race 4: both read version V; the loser blocks on the world row lock
    until the winner commits, then sees V+1 and is rejected."""
    with postgres_engine.begin() as setup:
        world = make_authored_world(setup, owner_user_id=committed_owner, name="Race World")

    winner = postgres_engine.connect()
    winner_tx = winner.begin()
    update_world(
        winner,
        world_id=world.world_id,
        actor_user_id=committed_owner,
        expected_row_version=world.row_version,
        name="Winner",
        description=None,
    )

    outcome: dict[str, object] = {}

    def loser() -> None:
        with postgres_engine.begin() as connection:
            try:
                update_world(
                    connection,
                    world_id=world.world_id,
                    actor_user_id=committed_owner,
                    expected_row_version=world.row_version,
                    name="Loser",
                    description=None,
                )
                outcome["result"] = "ok"
            except StaleWriteError:
                outcome["result"] = "stale"

    thread = threading.Thread(target=loser)
    thread.start()
    _wait_until_blocked(postgres_engine, "query LIKE '%FROM core.worlds w%'")
    winner_tx.commit()
    winner.close()
    thread.join(timeout=15)
    assert not thread.is_alive()

    assert outcome["result"] == "stale"
    with postgres_engine.connect() as verify:
        row = verify.execute(
            text("SELECT name, row_version FROM core.worlds WHERE world_id = :w"),
            {"w": world.world_id},
        ).one()
    assert (row.name, row.row_version) == ("Winner", world.row_version + 1)


def _client_for(engine: Engine, user_id: uuid.UUID) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: engine
    app.dependency_overrides[get_authenticated_user_id] = lambda: oidc_principal(user_id)
    client = TestClient(app, raise_server_exceptions=False)
    client.__enter__()
    return client


def test_two_concurrent_create_world_requests_with_one_key_create_one_world(
    postgres_engine: Engine, committed_owner: uuid.UUID
) -> None:
    """Race 5: the reservation INSERT serializes the two requests on the
    unique index; the second replays the first's stored response."""
    with postgres_engine.connect() as probe:
        ruleset_id, _ = dnd5e_ids(probe)
    body = {
        "name": "Concurrent World",
        "description": None,
        "ruleset_ids": [str(ruleset_id)],
        "default_ruleset_id": str(ruleset_id),
        "primary_timeline": {"name": "T", "description": None},
    }
    clients = [_client_for(postgres_engine, committed_owner) for _ in range(2)]
    barrier = threading.Barrier(2)

    def fire(client: TestClient):  # type: ignore[no-untyped-def]
        barrier.wait()
        return client.post("/worlds", json=body, headers={"Idempotency-Key": "race-create"})

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(fire, clients))
    finally:
        for client in clients:
            client.__exit__(None, None, None)

    assert [r.status_code for r in responses] == [201, 201]
    assert responses[0].json() == responses[1].json()
    with postgres_engine.connect() as verify:
        worlds = verify.execute(
            text("SELECT count(*) FROM core.worlds WHERE name = 'Concurrent World'")
        ).scalar()
        audits = verify.execute(
            text(
                "SELECT count(*) FROM audit.change_log WHERE command_name = 'create_world' "
                "AND actor_user_id = :u"
            ),
            {"u": committed_owner},
        ).scalar()
    assert worlds == 1
    assert audits == 3
