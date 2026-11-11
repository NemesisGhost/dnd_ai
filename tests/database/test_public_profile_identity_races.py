# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""Publication under concurrent definition edits (P03-A A4a, plan section 12.7).

Every competitor is a real command: `release_character_public_profile` against `update_npc` and
`update_player_character` (the two callers of `update_character_identity`, the only writer of
`species_id` and `size_category`), plus `save_character_public_profile_draft` and a second release.
The release holds the character's `core.entities` row `FOR KEY SHARE`; the edit takes it `FOR
UPDATE`. Each wait is observed through `pg_blocking_pids` as blocked by the intended session, both
orders are run, and no scenario deadlocks.

The first group calls the release as the command, as the existing release races do. The last group
(follow-up to A4) runs the real HTTP route through the same orders and asserts the response, the
release rows, the idempotency receipts and the audit rows.
"""

import time
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import Connection, Engine, text

from dnd_ai.commands.character_public_profile import (
    release_character_public_profile,
    save_character_public_profile_draft,
)
from dnd_ai.commands.npcs import update_npc
from dnd_ai.commands.player_characters import update_player_character
from dnd_ai.domain.authoring import StaleWriteError
from tests.database.test_campaign_owner_gate import (  # noqa: F401 - fixtures used by name
    Gate,
    client_factory,
    g,
)
from tests.database.test_character_public_profile_concurrency import CLOCK, SAVE_UPDATE, do_save
from tests.database.test_character_public_profile_copy import (  # noqa: F401 - fixtures
    entity_version,
    pc,
)
from tests.database.test_character_public_profile_restrictions import npc  # noqa: F401 - fixture
from tests.database.test_character_reveal_delegation import (  # noqa: F401 - fixtures used by name
    Members,
    m,
)
from tests.database.test_public_profile_identity_api import identity_release
from tests.lock_race_support import LockRace

pytestmark = pytest.mark.database

KINDS = ["npc", "player_character"]


@pytest.fixture
def subject(request: pytest.FixtureRequest, kind: str) -> uuid.UUID:
    return request.getfixturevalue("npc" if kind == "npc" else "pc")  # type: ignore[no-any-return]


@pytest.fixture(params=KINDS)
def kind(request: pytest.FixtureRequest) -> str:
    return str(request.param)


def seed_flagged_draft(engine: Engine, g: Gate, character: uuid.UUID) -> int:
    with engine.begin() as connection:
        return save_character_public_profile_draft(
            connection,
            campaign_id=g.campaign_id,
            character_id=character,
            actor_user_id=g.o1_user_id,
            expected_row_version=None,
            fields={"public_appearance": "Tall"},
            identity_flags={"publish_species": True, "publish_size": True},
        ).row_version


def do_identity_release(
    g: Gate,
    character: uuid.UUID,
    membership: uuid.UUID,
    version: int,
    character_version: int | None,
) -> Callable[[Connection], Any]:
    return lambda c: release_character_public_profile(
        c,
        campaign_id=g.campaign_id,
        character_id=character,
        actor_membership_id=membership,
        expected_draft_row_version=version,
        release_note=None,
        expected_character_row_version=character_version,
    )


def edit_identity(
    g: Gate, kind: str, character: uuid.UUID, user: uuid.UUID, *, size: str = "large"
) -> Callable[[Connection], Any]:
    """The real `update_npc` / `update_player_character` with the character's current values and a
    new size."""

    def run(connection: Connection) -> Any:
        cur = connection.execute(
            text("""
                SELECT e.canonical_name, e.summary, e.row_version, c.species_id,
                       c.origin_location_id, d.background, d.appearance, d.notes
                FROM core.entities e
                JOIN character.characters c ON c.character_id = e.entity_id
                LEFT JOIN character.character_descriptions d ON d.character_id = e.entity_id
                WHERE e.entity_id = :c
            """),
            {"c": character},
        ).one()
        common: dict[str, Any] = {
            "campaign_id": g.campaign_id,
            "actor_user_id": user,
            "expected_row_version": int(cur.row_version),
            "name": cur.canonical_name,
            "summary": cur.summary,
            "species_id": cur.species_id,
            "size_category": size,
            "origin_location_id": cur.origin_location_id,
            "background": cur.background,
            "appearance": cur.appearance,
            "notes": cur.notes,
        }
        if kind == "npc":
            return update_npc(connection, npc_id=character, **common)
        return update_player_character(connection, player_character_id=character, **common)

    return run


def released(engine: Engine, g: Gate, character: uuid.UUID) -> list[Any]:
    with engine.connect() as connection:
        return list(
            connection.execute(
                text(
                    "SELECT version_number, released_size_category, identity_entity_row_version "
                    "FROM campaign.character_public_profile_releases "
                    "WHERE campaign_id = :c AND character_id = :ch ORDER BY version_number"
                ),
                {"c": g.campaign_id, "ch": character},
            )
        )


def live_size(engine: Engine, character: uuid.UUID) -> str:
    with engine.connect() as connection:
        return str(
            connection.execute(
                text("SELECT size_category FROM character.characters WHERE character_id = :c"),
                {"c": character},
            ).scalar_one()
        )


def test_an_identity_edit_that_commits_first_makes_the_old_token_stale_and_writes_no_release(
    postgres_engine: Engine, g: Gate, m: Members, kind: str, subject: uuid.UUID
) -> None:
    c = subject
    version = seed_flagged_draft(postgres_engine, g, c)
    token = entity_version(postgres_engine, c)
    with LockRace(postgres_engine) as race:
        updating = race.hold(edit_identity(g, kind, c, m.gm_user_id))
        releasing = race.start("release", do_identity_release(g, c, g.o1, version, token))
        race.wait_blocked_by(updating, releasing)  # at the entity row the edit holds FOR UPDATE
        updating.commit()
        race.join_all()
    assert isinstance(releasing.error, StaleWriteError), releasing.describe()
    assert released(postgres_engine, g, c) == []
    assert entity_version(postgres_engine, c) > token
    assert live_size(postgres_engine, c) == "large"


def test_a_release_that_holds_the_entity_first_snapshots_the_old_values_and_the_edit_waits(
    postgres_engine: Engine, g: Gate, m: Members, kind: str, subject: uuid.UUID
) -> None:
    c = subject
    version = seed_flagged_draft(postgres_engine, g, c)
    token = entity_version(postgres_engine, c)
    old_size = live_size(postgres_engine, c)
    assert old_size != "large"
    with LockRace(postgres_engine) as race:
        # Paused after its last lock wait (the draft row), holding the entity row FOR KEY SHARE.
        pause = race.pause(thread_name="release", pattern=CLOCK)
        releasing = race.start("release", do_identity_release(g, c, g.o1, version, token))
        pause.wait_reached(releasing)
        updating = race.start("update", edit_identity(g, kind, c, m.gm_user_id))
        race.wait_blocked_by(pause, updating)  # the edit waits for the release
        pause.release()
        race.join_all()
    assert releasing.error is None and updating.error is None, (
        releasing.describe(),
        updating.describe(),
    )
    [row] = released(postgres_engine, g, c)
    assert row.released_size_category == old_size  # the old value, with the old version
    assert row.identity_entity_row_version == token
    assert live_size(postgres_engine, c) == "large"  # the edit committed after
    assert entity_version(postgres_engine, c) > token


def test_two_flagged_releases_of_one_draft_and_character_version_make_one_release(
    postgres_engine: Engine, g: Gate, m: Members, npc: uuid.UUID
) -> None:
    c = npc
    version = seed_flagged_draft(postgres_engine, g, c)
    token = entity_version(postgres_engine, c)
    with LockRace(postgres_engine) as race:
        pause = race.pause(thread_name="first", pattern=CLOCK)
        first = race.start("first", do_identity_release(g, c, g.o1, version, token))
        pause.wait_reached(first)
        second = race.start("second", do_identity_release(g, c, g.o2, version, token))
        race.wait_blocked_by(pause, second)  # on the draft row the first holds FOR UPDATE
        pause.release()
        race.join_all()
    assert first.error is None and second.error is None, (first.describe(), second.describe())
    assert first.result.created is True
    assert second.result.created is False  # the same release, never a second snapshot
    assert second.result.character_public_profile_release_id == (
        first.result.character_public_profile_release_id
    )
    assert second.result.identity_entity_row_version == token
    assert len(released(postgres_engine, g, c)) == 1


def test_a_flag_toggle_that_commits_first_makes_a_release_of_the_previous_draft_version_stale(
    postgres_engine: Engine, g: Gate, m: Members, npc: uuid.UUID
) -> None:
    c = npc
    version = seed_flagged_draft(postgres_engine, g, c)
    token = entity_version(postgres_engine, c)
    toggling = lambda conn: save_character_public_profile_draft(  # noqa: E731
        conn,
        campaign_id=g.campaign_id,
        character_id=c,
        actor_user_id=g.o1_user_id,
        expected_row_version=version,
        fields={},
        identity_flags={"publish_size": False},
    )
    with LockRace(postgres_engine) as race:
        saving = race.hold(toggling)
        releasing = race.start("release", do_identity_release(g, c, g.o1, version, token))
        race.wait_blocked_by(saving, releasing)  # at the draft row the save holds FOR UPDATE
        saving.commit()
        race.join_all()
    assert isinstance(releasing.error, StaleWriteError), releasing.describe()
    assert released(postgres_engine, g, c) == []


def test_a_draft_save_and_an_identity_edit_never_wait_on_each_other(
    postgres_engine: Engine, g: Gate, m: Members, npc: uuid.UUID
) -> None:
    """A save takes the entity `FOR SHARE`, the edit `FOR UPDATE`: they order at that row, and a
    pending release does not change it (no new lock, no new order)."""
    c = npc
    version = seed_flagged_draft(postgres_engine, g, c)
    with LockRace(postgres_engine) as race:
        pause = race.pause(thread_name="save", pattern=SAVE_UPDATE)
        saving = race.start("save", do_save(g, c, g.o1_user_id, version, public_summary="s"))
        pause.wait_reached(saving)  # holds the entity FOR SHARE and the draft FOR UPDATE
        updating = race.start("update", edit_identity(g, "npc", c, m.gm_user_id))
        race.wait_blocked_by(pause, updating)
        pause.release()
        race.join_all()
    assert saving.error is None and updating.error is None, (saving.describe(), updating.describe())


# --- the HTTP release route under the same races (follow-up to A4) -----------------------------
#
# The command races above prove the lock order; these run the real route, so the response, the
# release rows, the `security.idempotent_requests` receipts and the audit rows are asserted too.
# The route runs on a framework thread, so the HTTP request cannot be paused by name; each order is
# instead built from a held transaction (`LockRace.hold`) and the waits are observed through
# `pg_blocking_pids`, the HTTP session being identified as the one the holder blocks.

_RELEASE_COMMAND = "release_character_public_profile"


def http_release(
    client_factory: Callable[[uuid.UUID], Any],
    g: Gate,
    character: uuid.UUID,
    version: int,
    token: int,
    key: str,
) -> Callable[[Connection], Any]:
    def run(_connection: Connection) -> Any:
        return identity_release(client_factory, g.o1_user_id, g, character, version, token, key=key)

    return run


def lock_draft_row(g: Gate, character: uuid.UUID) -> Callable[[Connection], Any]:
    """Locks the profile draft row `FOR UPDATE` without changing it: a release has by then taken
    the entity `FOR KEY SHARE` (the lock order), and waits here."""
    return lambda c: c.execute(
        text(
            "SELECT 1 FROM campaign.character_public_profiles "
            "WHERE campaign_id = :c AND character_id = :ch FOR UPDATE"
        ),
        {"c": g.campaign_id, "ch": character},
    )


def waiters_of(engine: Engine, holder_pid: int) -> list[int]:
    """The sessions directly blocked by `holder_pid`."""
    with engine.connect() as connection:
        return [
            int(pid)
            for pid in connection.execute(
                text("""
                    SELECT a.pid FROM pg_stat_activity a
                    WHERE a.datname = current_database() AND :h = ANY(pg_blocking_pids(a.pid))
                    ORDER BY a.pid
                """),
                {"h": holder_pid},
            ).scalars()
        ]


def wait_for_session_blocked_by(race: LockRace, pid: int, count: int = 1) -> None:
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        if race.blocked_by(pid) >= count:
            return
        time.sleep(0.02)
    raise AssertionError(f"fewer than {count} session(s) blocked by pid {pid}")


def receipts(engine: Engine, g: Gate, keys: list[str]) -> dict[str, tuple[int | None, Any]]:
    with engine.connect() as connection:
        return {
            str(row.idempotency_key): (row.response_status_code, row.response_body)
            for row in connection.execute(
                text(
                    "SELECT idempotency_key, response_status_code, response_body "
                    "FROM security.idempotent_requests "
                    "WHERE campaign_id = :c AND idempotency_key = ANY(:k)"
                ),
                {"c": g.campaign_id, "k": keys},
            )
        }


def release_audits(engine: Engine, g: Gate, character: uuid.UUID) -> list[dict[str, Any]]:
    with engine.connect() as connection:
        return [
            dict(row)
            for row in connection.execute(
                text(
                    "SELECT changed_fields FROM audit.change_log "
                    "WHERE world_id = :w AND command_name = :n AND entity_id = :ch "
                    "ORDER BY recorded_at"
                ),
                {"w": g.world_id, "n": _RELEASE_COMMAND, "ch": character},
            ).mappings()
        ]


def test_http_identity_edit_first_returns_stale_write_and_leaves_no_release_receipt_or_audit(
    client_factory: Callable[[uuid.UUID], Any],
    postgres_engine: Engine,
    g: Gate,
    m: Members,
    kind: str,
    subject: uuid.UUID,
) -> None:
    c = subject
    version = seed_flagged_draft(postgres_engine, g, c)
    token = entity_version(postgres_engine, c)
    key = f"edit-first-{uuid.uuid4().hex[:8]}"
    with LockRace(postgres_engine) as race:
        updating = race.hold(edit_identity(g, kind, c, m.gm_user_id))
        releasing = race.start("release", http_release(client_factory, g, c, version, token, key))
        race.wait_blocked_by(updating, releasing)  # at the entity row the edit holds FOR UPDATE
        updating.commit()
        race.join_all()
    assert releasing.error is None, releasing.describe()
    response = releasing.result
    assert response.status_code == 409 and response.json()["error"]["code"] == "stale_write", (
        releasing.describe()
    )
    assert released(postgres_engine, g, c) == []
    assert release_audits(postgres_engine, g, c) == []
    # The failed request rolled back with its reservation: nothing is left under the key.
    assert receipts(postgres_engine, g, [key]) == {}
    assert live_size(postgres_engine, c) == "large" and entity_version(postgres_engine, c) > token

    # The key is not poisoned: a retry with the current token succeeds and is then the one receipt.
    fresh = entity_version(postgres_engine, c)
    retry = identity_release(client_factory, g.o1_user_id, g, c, version, fresh, key=key)
    assert retry.status_code == 201 and retry.json()["identity_entity_row_version"] == fresh
    [row] = released(postgres_engine, g, c)
    assert row.released_size_category == "large" and row.identity_entity_row_version == fresh
    [audit] = release_audits(postgres_engine, g, c)
    assert audit["changed_fields"]["identity_entity_row_version"] == fresh
    stored = receipts(postgres_engine, g, [key])
    assert stored[key][0] == 201
    assert stored[key][1]["identity_entity_row_version"] == fresh


def test_http_release_first_snapshots_the_old_values_and_the_edit_waits_for_it(
    client_factory: Callable[[uuid.UUID], Any],
    postgres_engine: Engine,
    g: Gate,
    m: Members,
    kind: str,
    subject: uuid.UUID,
) -> None:
    c = subject
    version = seed_flagged_draft(postgres_engine, g, c)
    token = entity_version(postgres_engine, c)
    old_size = live_size(postgres_engine, c)
    assert old_size != "large"
    key = f"release-first-{uuid.uuid4().hex[:8]}"
    with LockRace(postgres_engine) as race:
        gate = race.hold(lock_draft_row(g, c))
        releasing = race.start("release", http_release(client_factory, g, c, version, token, key))
        race.wait_blocked_by(gate, releasing)  # past the entity lock, waiting for the draft row
        [release_pid] = waiters_of(postgres_engine, gate.pid)
        updating = race.start("update", edit_identity(g, kind, c, m.gm_user_id))
        wait_for_session_blocked_by(race, release_pid)  # the edit waits at the entity row
        assert not updating.done
        gate.commit()
        race.join_all()
    assert releasing.error is None and updating.error is None, (
        releasing.describe(),
        updating.describe(),
    )
    response = releasing.result
    assert response.status_code == 201, releasing.describe()
    [row] = released(postgres_engine, g, c)
    assert row.released_size_category == old_size and row.identity_entity_row_version == token
    assert live_size(postgres_engine, c) == "large" and entity_version(postgres_engine, c) > token
    [audit] = release_audits(postgres_engine, g, c)
    assert audit["changed_fields"]["identity_entity_row_version"] == token
    assert audit["changed_fields"]["species_published"] is True
    assert audit["changed_fields"]["size_published"] is True
    stored = receipts(postgres_engine, g, [key])
    assert stored[key][0] == 201
    assert stored[key][1]["identity_entity_row_version"] == token
    assert "species_code" not in str(stored[key][1]) and old_size not in str(stored[key][1])


def test_http_concurrent_natural_retries_under_separate_keys_make_one_release(
    client_factory: Callable[[uuid.UUID], Any],
    postgres_engine: Engine,
    g: Gate,
    m: Members,
    npc: uuid.UUID,
) -> None:
    c = npc
    version = seed_flagged_draft(postgres_engine, g, c)
    token = entity_version(postgres_engine, c)
    keys = [f"retry-a-{uuid.uuid4().hex[:8]}", f"retry-b-{uuid.uuid4().hex[:8]}"]
    with LockRace(postgres_engine) as race:
        gate = race.hold(lock_draft_row(g, c))
        first = race.start("first", http_release(client_factory, g, c, version, token, keys[0]))
        second = race.start("second", http_release(client_factory, g, c, version, token, keys[1]))
        race.wait_blocked_by(gate, first, second)  # both wait on the same draft row
        gate.commit()
        race.join_all()
    assert first.error is None and second.error is None, (first.describe(), second.describe())
    answers = [first.result, second.result]
    assert sorted(a.status_code for a in answers) == [200, 201], (
        first.describe(),
        second.describe(),
    )
    created = next(a for a in answers if a.status_code == 201).json()
    natural = next(a for a in answers if a.status_code == 200).json()
    assert created["created"] is True and natural["created"] is False
    assert (
        natural["character_public_profile_release_id"]
        == (created["character_public_profile_release_id"])
    )
    assert natural["identity_entity_row_version"] == token == created["identity_entity_row_version"]
    [row] = released(postgres_engine, g, c)  # never a second snapshot
    assert row.identity_entity_row_version == token
    [audit] = release_audits(postgres_engine, g, c)  # only the creating request is audited
    assert audit["changed_fields"]["identity_entity_row_version"] == token
    stored = receipts(postgres_engine, g, keys)
    assert sorted(status for status, _ in stored.values()) == [200, 201]
    for status, stored_body in stored.values():
        expected = created if status == 201 else natural
        assert (
            stored_body["character_public_profile_release_id"]
            == (expected["character_public_profile_release_id"])
        )
        assert stored_body["identity_entity_row_version"] == token
