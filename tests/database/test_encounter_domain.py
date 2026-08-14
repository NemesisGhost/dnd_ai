"""narrative.encounters/.encounter_participants/.encounter_rounds/.
encounter_turns, interaction.combat_actions, and narrative.event_causes.
cause_encounter_id (revision 078).

Covers: encounters' not-entity-rooted status CHECK, same-world guards
across the new domain, encounter_participants' side/outcome CHECKs and
per-(encounter, entity) uniqueness, encounter_rounds' per-(encounter,
round_number) uniqueness, combat_actions' action_kind CHECK, encounter_
turns' participant-must-share-round's-encounter guard and per-(round,
participant) uniqueness, and event_causes' extended exactly-one-of-four
cause CHECK plus its new world-agreement trigger.
"""

import contextlib
import threading
import time
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import IntegrityError, InternalError, ProgrammingError

from tests.factories import (
    make_action,
    make_campaign,
    make_character,
    make_combat_action,
    make_encounter,
    make_encounter_participant,
    make_encounter_round,
    make_encounter_turn,
    make_event,
    make_interaction,
    make_item_definition,
    make_item_instance,
    make_location,
    make_ruleset_version_for_world,
    make_session,
    make_world,
    make_world_time,
)
from tests.factories import make_timeline as _make_timeline

pytestmark = pytest.mark.database

CONSTRAINT_ERRORS = (IntegrityError, InternalError, ProgrammingError)


class Fixture:
    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.timeline_id = _make_timeline(connection, self.world_id, is_primary=True)
        self.t0 = make_world_time(connection, self.world_id, 100)
        self.t1 = make_world_time(connection, self.world_id, 200)
        self.location_id = make_location(connection, self.world_id)
        self.character_a = make_character(connection, self.world_id, name="Rin")
        self.character_b = make_character(connection, self.world_id, name="Borrin")
        # "pending" sidesteps the active-campaign access-manager retention
        # invariant (revision 080) — these tests don't grant access.manage
        # and don't otherwise care about campaign lifecycle.
        self.campaign_id = make_campaign(
            connection, self.timeline_id, lifecycle_status_code="pending"
        )
        self.session_id = make_session(connection, self.campaign_id, 1)
        self.encounter_id = make_encounter(connection, self.timeline_id, self.t0)
        self.participant_a = make_encounter_participant(
            connection, self.encounter_id, self.character_a, side="party"
        )
        self.participant_b = make_encounter_participant(
            connection, self.encounter_id, self.character_b, side="enemy"
        )
        self.interaction_id = make_interaction(connection, self.timeline_id, self.t0)
        self.action_id = make_action(connection, self.interaction_id, self.character_a)


@pytest.fixture
def f(db_connection: Connection) -> Fixture:
    return Fixture(db_connection, "encounter-domain-world")


# ---------------------------------------------------------------------------
# narrative.encounters
# ---------------------------------------------------------------------------


def test_an_encounter_can_be_created(db_connection: Connection, f: Fixture) -> None:
    assert f.encounter_id is not None


def test_an_encounters_status_must_be_valid(db_connection: Connection, f: Fixture) -> None:
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_encounter(db_connection, f.timeline_id, f.t0, status="rampaging")
    assert "ck_encounters_status" in str(exc.value)


def test_an_encounters_location_must_share_its_timelines_world(
    db_connection: Connection, f: Fixture
) -> None:
    other_world = make_world(db_connection, slug="encounter-domain-other-world")
    foreign_location = make_location(db_connection, other_world)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_encounter(db_connection, f.timeline_id, f.t0, location_id=foreign_location)
    assert "belongs to world" in str(exc.value)


# ---------------------------------------------------------------------------
# narrative.encounters.campaign_id / .session_id (revision 081)
# ---------------------------------------------------------------------------


def test_an_encounter_with_matching_campaign_and_session_can_be_created(
    db_connection: Connection, f: Fixture
) -> None:
    encounter_id = make_encounter(
        db_connection, f.timeline_id, f.t0, campaign_id=f.campaign_id, session_id=f.session_id
    )
    assert encounter_id is not None


def test_an_encounters_campaign_must_belong_to_its_timeline(
    db_connection: Connection, f: Fixture
) -> None:
    other_timeline = _make_timeline(db_connection, f.world_id, name="Other Branch")
    foreign_campaign = make_campaign(db_connection, other_timeline, lifecycle_status_code="pending")

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_encounter(db_connection, f.timeline_id, f.t0, campaign_id=foreign_campaign)
    assert "belongs to timeline" in str(exc.value)


def test_an_encounters_session_must_belong_to_its_campaign(
    db_connection: Connection, f: Fixture
) -> None:
    """The reported gap: a session belonging to a *different*, same-world
    campaign is not caught by the same-world guard alone — this is the
    dedicated campaign/session ownership check revision 081 adds."""
    other_campaign = make_campaign(db_connection, f.timeline_id, lifecycle_status_code="pending")
    foreign_session = make_session(db_connection, other_campaign, 1)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_encounter(
            db_connection,
            f.timeline_id,
            f.t0,
            campaign_id=f.campaign_id,
            session_id=foreign_session,
        )
    assert "belongs to campaign" in str(exc.value)


def test_an_encounters_session_requires_a_campaign_id(
    db_connection: Connection, f: Fixture
) -> None:
    """campaign_id absent (NULL) with session_id supplied is rejected the
    same way — a session always belongs to exactly one real campaign
    (campaign.sessions.campaign_id NOT NULL), so NULL can never be it."""
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_encounter(db_connection, f.timeline_id, f.t0, session_id=f.session_id)
    assert "belongs to campaign" in str(exc.value)


def test_reparenting_a_sessions_campaign_cannot_invalidate_an_existing_encounter(
    db_connection: Connection, f: Fixture
) -> None:
    """campaign.sessions.campaign_id is already immutable
    (tr_sessions_enforce_immutable, revision 080) — this proves that
    protection still stands and is what keeps an already-valid encounter's
    campaign/session pairing from being invalidated out from under it."""
    make_encounter(
        db_connection, f.timeline_id, f.t0, campaign_id=f.campaign_id, session_id=f.session_id
    )
    other_campaign = make_campaign(db_connection, f.timeline_id, lifecycle_status_code="pending")

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("UPDATE campaign.sessions SET campaign_id = :c WHERE session_id = :s"),
            {"c": other_campaign, "s": f.session_id},
        )
    assert "immutable" in str(exc.value)


# ---------------------------------------------------------------------------
# narrative.encounter_participants
# ---------------------------------------------------------------------------


def test_an_encounter_participants_side_must_be_valid(
    db_connection: Connection, f: Fixture
) -> None:
    third_character = make_character(db_connection, f.world_id, name="Cass")
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_encounter_participant(
            db_connection, f.encounter_id, third_character, side="spectating"
        )
    assert "ck_encounter_participants_side" in str(exc.value)


def test_an_encounter_participants_outcome_must_be_valid(
    db_connection: Connection, f: Fixture
) -> None:
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "UPDATE narrative.encounter_participants SET outcome = 'vaporized' "
                "WHERE encounter_participant_id = :p"
            ),
            {"p": f.participant_a},
        )
    assert "ck_encounter_participants_outcome" in str(exc.value)


def test_an_entity_can_only_be_one_participant_per_encounter(
    db_connection: Connection, f: Fixture
) -> None:
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_encounter_participant(db_connection, f.encounter_id, f.character_a)
    assert "ux_encounter_participants_encounter_entity" in str(exc.value)


def test_an_encounter_participant_must_share_the_encounters_world(
    db_connection: Connection, f: Fixture
) -> None:
    other_world = make_world(db_connection, slug="encounter-domain-participant-other-world")
    foreign_character = make_character(db_connection, other_world)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_encounter_participant(db_connection, f.encounter_id, foreign_character)
    assert "belongs to world" in str(exc.value)


# ---------------------------------------------------------------------------
# narrative.encounter_rounds
# ---------------------------------------------------------------------------


def test_only_one_round_row_per_encounter_and_round_number(
    db_connection: Connection, f: Fixture
) -> None:
    make_encounter_round(db_connection, f.encounter_id, 1)
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_encounter_round(db_connection, f.encounter_id, 1)
    assert "ux_encounter_rounds_encounter_round" in str(exc.value)


# ---------------------------------------------------------------------------
# interaction.combat_actions
# ---------------------------------------------------------------------------


def test_a_combat_action_can_be_created(db_connection: Connection, f: Fixture) -> None:
    combat_action_id = make_combat_action(db_connection, f.action_id, action_kind="attack")
    assert combat_action_id is not None


def test_a_combat_actions_kind_must_be_valid(db_connection: Connection, f: Fixture) -> None:
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_combat_action(db_connection, f.action_id, action_kind="teleport")
    assert "ck_combat_actions_action_kind" in str(exc.value)


def test_a_combat_actions_item_instance_must_share_its_actions_world(
    db_connection: Connection, f: Fixture
) -> None:
    other_world = make_world(db_connection, slug="encounter-domain-combat-other-world")
    other_ruleset_version = make_ruleset_version_for_world(db_connection, other_world)
    other_definition = make_item_definition(db_connection, other_ruleset_version)
    foreign_item = make_item_instance(db_connection, other_world, other_definition)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_combat_action(db_connection, f.action_id, item_instance_id=foreign_item)
    assert "belongs to world" in str(exc.value)


# ---------------------------------------------------------------------------
# narrative.encounter_turns
# ---------------------------------------------------------------------------


def test_an_encounter_turn_can_be_created(db_connection: Connection, f: Fixture) -> None:
    round_id = make_encounter_round(db_connection, f.encounter_id, 1)
    combat_action_id = make_combat_action(db_connection, f.action_id)
    turn_id = make_encounter_turn(
        db_connection, round_id, f.participant_a, 0, combat_action_id=combat_action_id
    )
    assert turn_id is not None


def test_an_encounter_turns_participant_must_belong_to_the_rounds_encounter(
    db_connection: Connection, f: Fixture
) -> None:
    other_encounter_id = make_encounter(db_connection, f.timeline_id, f.t0)
    other_participant = make_encounter_participant(db_connection, other_encounter_id, f.character_a)
    round_id = make_encounter_round(db_connection, f.encounter_id, 1)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_encounter_turn(db_connection, round_id, other_participant, 0)
    assert "belongs to encounter" in str(exc.value)


def test_only_one_turn_row_per_round_and_participant(db_connection: Connection, f: Fixture) -> None:
    round_id = make_encounter_round(db_connection, f.encounter_id, 1)
    make_encounter_turn(db_connection, round_id, f.participant_a, 0)
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_encounter_turn(db_connection, round_id, f.participant_a, 1)
    assert "ux_encounter_turns_round_participant" in str(exc.value)


# ---------------------------------------------------------------------------
# narrative.event_causes.cause_encounter_id
# ---------------------------------------------------------------------------


def test_an_event_cause_can_cite_an_encounter(db_connection: Connection, f: Fixture) -> None:
    event_id = make_event(db_connection, f.world_id, f.timeline_id, f.t0)
    db_connection.execute(
        text(
            "INSERT INTO narrative.event_causes (event_id, cause_encounter_id) "
            "VALUES (:event, :encounter)"
        ),
        {"event": event_id, "encounter": f.encounter_id},
    )


def test_an_event_cause_must_have_exactly_one_cause(db_connection: Connection, f: Fixture) -> None:
    event_id = make_event(db_connection, f.world_id, f.timeline_id, f.t0)
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "INSERT INTO narrative.event_causes "
                "(event_id, cause_encounter_id, cause_description) "
                "VALUES (:event, :encounter, 'also a description')"
            ),
            {"event": event_id, "encounter": f.encounter_id},
        )
    assert "ck_event_causes_has_cause" in str(exc.value)


def test_an_event_causes_encounter_must_share_the_events_timeline(
    db_connection: Connection, f: Fixture
) -> None:
    other_timeline = _make_timeline(db_connection, f.world_id, name="Other Branch")
    event_id = make_event(db_connection, f.world_id, other_timeline, f.t0)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "INSERT INTO narrative.event_causes (event_id, cause_encounter_id) "
                "VALUES (:event, :encounter)"
            ),
            {"event": event_id, "encounter": f.encounter_id},
        )
    assert "belongs to timeline" in str(exc.value)


# ---------------------------------------------------------------------------
# Migration 081's LOCK TABLE ... IN SHARE MODE (the exact lock-conflict
# property that migration's "Locking considerations" docstring depends on)
# ---------------------------------------------------------------------------


class _CommittedFixture:
    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.timeline_id = _make_timeline(connection, self.world_id, is_primary=True)
        self.t0 = make_world_time(connection, self.world_id, 100)


@pytest.fixture
def committed(postgres_engine: Engine) -> Iterator[_CommittedFixture]:
    """A genuinely committed (not rolled-back) world/timeline/world_time —
    unlike this file's own `f` fixture, which lives inside `db_connection`'s
    always-rolled-back transaction and is therefore invisible to any other
    connection. The lock-conflict test below needs two independent
    connections to see the same rows, so it cannot use `f`/`db_connection`."""
    with postgres_engine.begin() as connection:
        fixture = _CommittedFixture(connection, f"encounter-lock-{uuid.uuid4().hex[:8]}")
    yield fixture
    with postgres_engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        cleanup.execute(
            text("DELETE FROM core.entities WHERE world_id = :w"), {"w": fixture.world_id}
        )
        cleanup.execute(
            text("DELETE FROM core.worlds WHERE world_id = :w"), {"w": fixture.world_id}
        )


def test_a_share_lock_on_encounters_blocks_a_concurrent_insert_until_released(
    postgres_engine: Engine, committed: _CommittedFixture
) -> None:
    """Focused database test for the exact lock conflict revision 081's
    migration (database/migrations/versions/081_encounter_session_scope.py)
    depends on for its own correctness, standing in for genuinely pausing
    mid-migration to inject a concurrent write — not feasible with this
    project's migration tooling: tests/conftest.py's postgres_engine
    fixture runs `alembic upgrade head` as one opaque, blocking subprocess
    call with no hook to interject a concurrent statement between two of
    its internal op.execute() calls (docs/PLAN.md §25.6 proportional
    test-infrastructure policy).

    What this proves instead: `LOCK TABLE narrative.encounters IN SHARE
    MODE`, held across a transaction, genuinely blocks a concurrent
    INSERT (the same ROW EXCLUSIVE lock class UPDATE also acquires,
    per PostgreSQL's table-level lock-conflict rules — see the
    migration's own "Locking considerations" docstring) until that
    transaction ends, and the blocked statement then proceeds cleanly.
    Revision 081 acquires this exact lock before its audit and holds it
    through `CREATE OR REPLACE FUNCTION` and its own commit — so if this
    lock genuinely serializes writers against a held SHARE lock (proven
    here), it equally serializes them against that migration's audit +
    function replacement: no concurrent writer can commit a row the
    audit already passed judgment on, because no concurrent writer can
    commit *anything* until the migration's own transaction — audit,
    function replacement, and all — has already committed.
    """
    lock_connection = postgres_engine.connect()
    lock_transaction = lock_connection.begin()

    insert_started = threading.Event()
    insert_done = threading.Event()
    results: dict[str, uuid.UUID] = {}
    errors: dict[str, Exception] = {}

    def _insert() -> None:
        try:
            with postgres_engine.connect() as connection:
                insert_started.set()
                encounter_id = connection.execute(
                    text("""
                        INSERT INTO narrative.encounters (timeline_id, world_time_id)
                        VALUES (:timeline, :world_time)
                        RETURNING encounter_id
                    """),
                    {"timeline": committed.timeline_id, "world_time": committed.t0},
                ).scalar()
                connection.commit()
                assert isinstance(encounter_id, uuid.UUID)
                results["encounter_id"] = encounter_id
        except Exception as exc:  # noqa: BLE001 - captured for the assertion below
            errors["insert"] = exc
        finally:
            insert_done.set()

    # Everything from acquiring the lock to releasing it is inside this
    # try/finally, unconditionally. postgres_engine is session-scoped: a
    # connection left open here with the lock still held — because some
    # assertion below raised before reaching the release code — would
    # block every later test's writes to narrative.encounters for the
    # rest of the pytest session, not just fail this one test. That is
    # not a hypothetical: an earlier version of this test without this
    # try/finally did exactly that, when a too-tight client-side timeout
    # tripped an assertion before the lock was ever released, and every
    # subsequent test touching narrative.encounters then hung indefinitely
    # behind it. The lock itself is released by rollback (LOCK TABLE has
    # no data of its own to commit); rollback/close are each independently
    # guarded so a cleanup failure can never mask a real assertion error
    # already propagating.
    try:
        lock_connection.execute(text("LOCK TABLE narrative.encounters IN SHARE MODE"))

        thread = threading.Thread(target=_insert)
        thread.start()
        # 180s, calibrated to a measured worst case, not guessed: a bare,
        # dependency-free postgres_engine().connect() with no lock, no
        # query, and no relation to this test's own code has been directly
        # timed at ~130s in this sandbox on repeated occasions (most
        # recently: a 3-line throwaway script opening exactly one
        # connection). This is Docker Desktop/host networking latency on
        # this specific long-running sandbox session, not something this
        # codebase can fix — a normal CI runner does not exhibit it. The
        # try/finally above is what actually fixes correctness (a timeout
        # here fails this one test cleanly instead of leaking the lock);
        # this timeout only affects how patient the test is with a slow
        # environment, never whether a timeout can corrupt state for tests
        # that run after it. If this still isn't enough on some run, that
        # is this sandbox continuing to degrade, not a regression here.
        assert insert_started.wait(timeout=180), "insert thread never started"

        # Poll pg_stat_activity server-side for confirmation the INSERT is
        # genuinely blocked on our lock, rather than trusting a fixed
        # client-side sleep to have been long enough.
        deadline = time.monotonic() + 60
        blocked = False
        while time.monotonic() < deadline:
            waiting = lock_connection.execute(
                text("""
                    SELECT count(*) FROM pg_stat_activity
                    WHERE wait_event_type = 'Lock'
                      AND query ILIKE 'INSERT INTO narrative.encounters%'
                """)
            ).scalar()
            if waiting:
                blocked = True
                break
            time.sleep(0.1)

        assert blocked, "the concurrent INSERT was never observed blocked behind the SHARE lock"
        assert not insert_done.is_set(), "INSERT completed despite the SHARE lock still being held"
    finally:
        with contextlib.suppress(Exception):
            lock_transaction.rollback()
        with contextlib.suppress(Exception):
            lock_connection.close()

    assert insert_done.wait(timeout=60), "INSERT never completed after the SHARE lock was released"
    thread.join(timeout=60)
    assert not thread.is_alive()
    assert not errors, f"the INSERT failed after the lock released: {errors}"

    with postgres_engine.connect() as verify:
        exists = verify.execute(
            text("SELECT count(*) FROM narrative.encounters WHERE encounter_id = :e"),
            {"e": results["encounter_id"]},
        ).scalar()
        assert exists == 1, "the INSERT that proceeded after the lock released did not commit"
