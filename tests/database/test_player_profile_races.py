# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""RA1: a GM read of the player profile during a profile edit, over real HTTP (P03-A A5a, design
sections 8.5 and 10.4).

The profile-edit side is the fixture writer (`tests/player_profile_support.py`) running the P03-B
write shape in its own transaction: it stands in for a writer that does not exist yet and is the only
non-HTTP party. The read is `GET .../player-profile` through `TestClient` and the real route, on its
own thread and connection, under `tests/lock_race_support.py`.

The design promises that the current profile is read in one statement joining the head to its
current version, so a reader sees either the previous complete version or the new complete one,
never a mixture, and never waits for the editor. The edit holds the head `FOR UPDATE` (observed
through `pg_locks`, not assumed) and a head update plus a version insert uncommitted.
"""

import threading
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from tests.database.test_campaign_owner_gate import (  # noqa: F401 - fixtures used by name
    Gate,
    client_factory,
    g,
)
from tests.database.test_character_reveal_delegation import (  # noqa: F401 - fixtures used by name
    Members,
    m,
)
from tests.database.test_player_profile_api import Pp, pp, url  # noqa: F401 - fixtures by name
from tests.http_race_support import StatementGate
from tests.lock_race_support import LockRace
from tests.player_profile_support import edit_player_profile, edit_player_profile_in, markers

pytestmark = pytest.mark.database

Factory = Callable[[uuid.UUID], TestClient]


def _read(factory: Factory, user: uuid.UUID, g: Gate, character: uuid.UUID) -> Callable[[Any], Any]:
    def run(_connection: Any) -> Any:
        with factory(user) as client:
            return client.get(url(g.campaign_id, character))

    return run


def _head_is_locked_for_update(engine: Engine, character: uuid.UUID) -> bool:
    """Whether the profile head row is held `FOR UPDATE` by another session right now."""
    with engine.connect() as connection:
        try:
            connection.execute(text("SET LOCAL lock_timeout = '0'"))
            connection.execute(
                text(
                    "SELECT 1 FROM campaign.character_player_profiles "
                    "WHERE character_id = :c FOR UPDATE NOWAIT"
                ),
                {"c": character},
            )
        except DBAPIError:
            return True
        finally:
            connection.rollback()
    return False


def test_ra1_a_read_during_an_uncommitted_edit_gets_the_previous_complete_version_then_the_new(
    postgres_engine: Engine, client_factory: Factory, g: Gate, pp: Pp
) -> None:
    new_markers = markers("A-edit")
    with LockRace(postgres_engine) as race:
        editing = race.hold(
            lambda c: edit_player_profile_in(
                c,
                campaign_id=g.campaign_id,
                character_id=pp.character,
                editor_membership_id=g.o2,
                fields=new_markers,
            )
        )
        # The experiment is meaningful only while the edit really holds the head.
        assert _head_is_locked_for_update(postgres_engine, pp.character)
        reading = race.start("read", _read(client_factory, g.o1_user_id, g, pp.character))
        race.wait_done(reading, why="a profile read waited for the editor; it must not")
        assert reading.error is None
        assert reading.result.status_code == 200, reading.result.text
        body = reading.result.json()
        assert body["profile"]["row_version"] == 1
        assert body["profile"]["fields"] == pp.a_markers  # the previous version, complete
        assert body["profile"]["edited_by"] == "Gate Owner One"
        assert race.blocked_by(editing.pid) == 0  # nothing waited behind the edit
        editing.commit()
        race.join_all()
    after = client_factory(g.o1_user_id)
    with after as client:
        committed = client.get(url(g.campaign_id, pp.character)).json()
    assert committed["profile"]["row_version"] == 2
    assert committed["profile"]["fields"] == new_markers
    assert committed["profile"]["edited_by"] == "Gate Owner Two"


def test_ra1_a_read_stopped_before_its_profile_statement_sees_the_edit_whole_once_it_commits(
    postgres_engine: Engine, client_factory: Factory, g: Gate, pp: Pp
) -> None:
    """The reader is stopped just before its profile statement (it holds no lock there), the edit
    commits in full, and the reader then runs: it sees the new version whole, and the editor never
    waited for the reader."""
    new_markers = markers("A-edit")
    with (
        StatementGate(postgres_engine, r"FROM campaign\.character_player_profiles h") as gate,
        LockRace(postgres_engine) as race,
    ):
        reading = race.start("read", _read(client_factory, g.o1_user_id, g, pp.character))
        assert gate.reached.wait(15), "the read never reached its profile statement"
        assert (
            edit_player_profile(
                postgres_engine,
                campaign_id=g.campaign_id,
                character_id=pp.character,
                editor_membership_id=g.o2,
                fields=new_markers,
            )
            == 2
        )  # committed while the reader was stopped: the reader held nothing the editor needed
        gate.resume.set()
        race.join_all()
    assert reading.error is None and reading.result.status_code == 200, reading.describe()
    profile = reading.result.json()["profile"]
    assert profile["row_version"] == 2 and profile["fields"] == new_markers


def test_ra1_readers_never_see_a_mixture_while_edits_commit(
    postgres_engine: Engine, client_factory: Factory, g: Gate, pp: Pp
) -> None:
    """Every response during a run of committed edits is one whole version: the `row_version`
    and every field marker name the same edit, and nothing is torn, partial or missing."""
    edits = 12
    done = threading.Event()
    failures: list[str] = []
    seen: set[int] = set()

    def versioned(n: int) -> dict[str, str]:
        return {code: f"RA1-V{n}-{code}" for code in pp.a_markers}

    def writer() -> None:
        try:
            for n in range(2, edits + 2):
                version = edit_player_profile(
                    postgres_engine,
                    campaign_id=g.campaign_id,
                    character_id=pp.character,
                    editor_membership_id=g.o1,
                    fields=versioned(n),
                )
                if version != n:
                    failures.append(f"writer expected row_version {n}, got {version}")
        except BaseException as exc:  # noqa: BLE001 - surfaced below
            failures.append(f"writer failed: {exc!r}")
        finally:
            done.set()

    def reader() -> None:
        with client_factory(g.o1_user_id) as client:
            while not done.is_set():
                response = client.get(url(g.campaign_id, pp.character))
                if response.status_code != 200:
                    failures.append(f"reader got {response.status_code}")
                    return
                profile = response.json()["profile"]
                version = profile["row_version"]
                seen.add(version)
                expected = pp.a_markers if version == 1 else versioned(version)
                if profile["fields"] != expected:
                    failures.append(f"torn read at row_version {version}: {profile['fields']}")
                    return

    threads = [threading.Thread(target=reader, name=f"ra1-reader-{i}") for i in range(3)]
    threads.append(threading.Thread(target=writer, name="ra1-writer"))
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
        assert not thread.is_alive(), thread.name
    assert failures == []
    with client_factory(g.o1_user_id) as client:
        final = client.get(url(g.campaign_id, pp.character)).json()["profile"]
    assert final["row_version"] == edits + 1 and final["fields"] == versioned(edits + 1)
    assert seen  # the readers did observe the profile while the edits ran
