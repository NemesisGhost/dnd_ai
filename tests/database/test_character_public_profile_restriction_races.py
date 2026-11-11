# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""Lock-order races for the restriction (P03-A A2b-1, plan sections 9.6 and 9.8).

World roles are changed with the real world-membership command (`end_world_membership`, which takes
the world row `FOR UPDATE` first). The save and the release both hold the world row `FOR SHARE`
before they judge the caller's world capability, so a role end and either command serialize at the
world row, and the command that waited judges the capability afresh: the text and the draft version
it observes are recorded for each winner. Every wait is observed through `pg_blocking_pids` as
blocked by the intended session (`LockRace.wait_blocked_by`), a command that finishes before it
blocks is reported as it ended, and the pauses, holds and workers are cleaned up before teardown.

Coverage not claimed here: the copy command does not exist yet (A2b-2), so its races (a copy against
`update_npc`, against a save and a release, and the copier's world role) are not executed. The
paths they share with these tests, the world-row `FOR SHARE` before the capability and the draft
`FOR UPDATE`, are the ones exercised below.
"""

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import Connection, Engine

from dnd_ai.commands.world_memberships import end_world_membership
from dnd_ai.domain.authoring import StaleWriteError
from dnd_ai.domain.public_profiles import PublicProfileFieldWithheldError
from tests.database.test_campaign_owner_gate import (  # noqa: F401 - fixtures used by name
    Gate,
    client_factory,
    g,
)
from tests.database.test_character_public_profile_api import (  # noqa: F401 - fixtures by name
    counts,
    release_rows,
)
from tests.database.test_character_public_profile_concurrency import (
    CLOCK,
    SAVE_UPDATE,
    do_release,
    do_save,
)
from tests.database.test_character_public_profile_restrictions import (  # noqa: F401 - fixtures
    EXCERPT,
    FULL,
    npc,
    row,
    started,
)
from tests.database.test_character_reveal_delegation import (  # noqa: F401 - fixtures used by name
    Members,
    m,
)
from tests.lock_race_support import LockRace

pytestmark = pytest.mark.database


def _end_world_role(g: Gate, user: uuid.UUID) -> Callable[[Connection], Any]:
    return lambda c: end_world_membership(c, world_id=g.world_id, user_id=user)


def _world_roles(engine: Engine, g: Gate, user: uuid.UUID) -> int:
    from sqlalchemy import text

    with engine.connect() as connection:
        return int(
            connection.execute(
                text(
                    "SELECT count(*) FROM security.world_memberships "
                    "WHERE world_id = :w AND user_id = :u AND ended_at IS NULL"
                ),
                {"w": g.world_id, "u": user},
            ).scalar_one()
        )


# --- the releaser's world role against a release of uncovered copied content -----------------------------


def test_a_release_in_flight_finishes_before_the_releasers_world_role_ends(
    client_factory: Callable[[uuid.UUID], Any], postgres_engine: Engine, g: Gate, npc: uuid.UUID
) -> None:
    version = started(client_factory, postgres_engine, g, npc)
    with LockRace(postgres_engine) as race:
        pause = race.pause(thread_name="release", pattern=CLOCK)
        releasing = race.start("release", do_release(g, npc, g.o2, version))
        pause.wait_reached(releasing)  # holds the world FOR SHARE and the draft FOR UPDATE
        ending = race.start("end", _end_world_role(g, g.o2_user_id))
        race.wait_blocked_by(pause, ending)
        pause.release()
        race.join_all()
    assert releasing.error is None and releasing.result.created is True
    assert ending.error is None
    rows = release_rows(postgres_engine, g, npc)
    assert [r["public_background"] for r in rows] == [FULL]  # the text the releaser could read
    assert _world_roles(postgres_engine, g, g.o2_user_id) == 0


def test_a_release_that_waited_for_the_end_of_the_releasers_world_role_is_refused(
    client_factory: Callable[[uuid.UUID], Any], postgres_engine: Engine, g: Gate, npc: uuid.UUID
) -> None:
    version = started(client_factory, postgres_engine, g, npc)
    before = counts(postgres_engine, g)
    snapshot = row(postgres_engine, g, npc)
    with LockRace(postgres_engine) as race:
        ending = race.hold(_end_world_role(g, g.o2_user_id))
        releasing = race.start("release", do_release(g, npc, g.o2, version))
        race.wait_blocked_by(ending, releasing)
        ending.commit()
        race.join_all()
    # It judged the capability afresh after the wait: the field is withheld, so nothing is written.
    assert isinstance(releasing.error, PublicProfileFieldWithheldError)
    assert counts(postgres_engine, g) == before
    assert release_rows(postgres_engine, g, npc) == []
    assert row(postgres_engine, g, npc) == snapshot  # the draft version and text it observed


# --- the saver's world role against a save that writes text into the copied field -----------------------------


def test_a_save_in_flight_finishes_before_the_savers_world_role_ends(
    client_factory: Callable[[uuid.UUID], Any],
    postgres_engine: Engine,
    g: Gate,
    m: Members,
    npc: uuid.UUID,
) -> None:
    version = started(client_factory, postgres_engine, g, npc)
    with LockRace(postgres_engine) as race:
        pause = race.pause(thread_name="save", pattern=SAVE_UPDATE)
        saving = race.start(
            "save", do_save(g, npc, m.gm_user_id, version, public_background=EXCERPT)
        )
        pause.wait_reached(saving)
        ending = race.start("end", _end_world_role(g, m.gm_user_id))
        race.wait_blocked_by(pause, ending)
        pause.release()
        race.join_all()
    assert saving.error is None and saving.result.row_version == version + 1
    assert ending.error is None
    after = row(postgres_engine, g, npc)
    assert after["public_background"] == EXCERPT and after["background_watermark"] == version + 1
    assert _world_roles(postgres_engine, g, m.gm_user_id) == 0


def test_a_save_that_waited_for_the_end_of_the_savers_world_role_is_refused_and_writes_nothing(
    client_factory: Callable[[uuid.UUID], Any],
    postgres_engine: Engine,
    g: Gate,
    m: Members,
    npc: uuid.UUID,
) -> None:
    version = started(client_factory, postgres_engine, g, npc)
    snapshot, before = row(postgres_engine, g, npc), counts(postgres_engine, g)
    with LockRace(postgres_engine) as race:
        ending = race.hold(_end_world_role(g, m.gm_user_id))
        saving = race.start(
            "save", do_save(g, npc, m.gm_user_id, version, public_background=EXCERPT)
        )
        race.wait_blocked_by(ending, saving)
        ending.commit()
        race.join_all()
    assert isinstance(saving.error, PublicProfileFieldWithheldError)
    assert row(postgres_engine, g, npc) == snapshot
    assert counts(postgres_engine, g) == before


# --- a permitted edit of a released field against a restricted releaser's release -------------------------------


def _released_copy_at_version_three(
    client_factory: Callable[[uuid.UUID], Any],
    postgres_engine: Engine,
    g: Gate,
    m: Members,
    npc: uuid.UUID,
) -> int:
    """Version 2 released by a permitted owner (it covers the copied background); a permitted GM
    then edits the appearance (version 3). The restricted owner `o1` may therefore release 3."""
    from tests.database.test_character_public_profile_api import code, release, save

    version = started(client_factory, postgres_engine, g, npc)
    assert code(release(client_factory, g.o2_user_id, g, npc, version)) == 201
    assert code(save(client_factory, m.gm_user_id, g, npc, {"expected_row_version": version, "public_appearance": "edited"})) == 200  # fmt: skip
    return version + 1


def test_a_permitted_edit_of_the_released_field_that_commits_first_makes_the_release_stale(
    client_factory: Callable[[uuid.UUID], Any],
    postgres_engine: Engine,
    g: Gate,
    m: Members,
    npc: uuid.UUID,
) -> None:
    version = _released_copy_at_version_three(client_factory, postgres_engine, g, m, npc)
    with LockRace(postgres_engine) as race:
        pause = race.pause(thread_name="edit", pattern=SAVE_UPDATE)
        editing = race.start(
            "edit", do_save(g, npc, m.gm_user_id, version, public_background="new text")
        )
        pause.wait_reached(editing)
        releasing = race.start("release", do_release(g, npc, g.o1, version))
        race.wait_blocked_by(pause, releasing)
        pause.release()
        race.join_all()
    assert editing.error is None and editing.result.row_version == version + 1
    assert isinstance(
        releasing.error, StaleWriteError
    )  # the restricted releaser never saw "new text"
    assert len(release_rows(postgres_engine, g, npc)) == 1
    after = row(postgres_engine, g, npc)
    assert after["background_watermark"] == version + 1  # restricted again for o1


def test_a_release_that_commits_first_covers_only_the_earlier_text_and_the_edit_restricts_again(
    client_factory: Callable[[uuid.UUID], Any],
    postgres_engine: Engine,
    g: Gate,
    m: Members,
    npc: uuid.UUID,
) -> None:
    version = _released_copy_at_version_three(client_factory, postgres_engine, g, m, npc)
    with LockRace(postgres_engine) as race:
        pause = race.pause(thread_name="release", pattern=CLOCK)
        releasing = race.start("release", do_release(g, npc, g.o1, version))
        pause.wait_reached(releasing)  # holds the draft FOR UPDATE
        editing = race.start(
            "edit", do_save(g, npc, m.gm_user_id, version, public_background="new text")
        )
        race.wait_blocked_by(pause, editing)
        pause.release()
        race.join_all()
    assert releasing.error is None and releasing.result.version_number == 2
    assert editing.error is None and editing.result.row_version == version + 1
    rows = release_rows(postgres_engine, g, npc)
    assert [r["public_background"] for r in rows] == [
        FULL,
        FULL,
    ]  # release 2 holds the earlier text
    after = row(postgres_engine, g, npc)
    assert after["public_background"] == "new text"
    assert after["background_watermark"] == version + 1  # past release 2 (from version 3): withheld
