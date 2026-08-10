"""integration.external_systems/.external_identifiers/.sync_jobs/.
sync_state/.delivery_attempts (revision 079).

Covers: external_systems' system_type CHECK, external_identifiers'
per-(system, kind, external_id) uniqueness and same-world guard, sync_jobs'
direction/status CHECKs and at-most-one-target CHECK, sync_state's
exactly-one-target CHECK and per-(system, target) uniqueness, both tables'
same-world guards, and delivery_attempts' per-(job, attempt_number)
uniqueness.
"""

import pytest
from sqlalchemy import Connection
from sqlalchemy.exc import IntegrityError, InternalError, ProgrammingError

from tests.factories import (
    make_character,
    make_delivery_attempt,
    make_encounter,
    make_encounter_participant,
    make_encounter_round,
    make_encounter_turn,
    make_external_identifier,
    make_external_system,
    make_sync_job,
    make_sync_state,
    make_timeline,
    make_world,
    make_world_time,
)

pytestmark = pytest.mark.database

CONSTRAINT_ERRORS = (IntegrityError, InternalError, ProgrammingError)


class Fixture:
    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        self.t0 = make_world_time(connection, self.world_id, 100)
        self.character_id = make_character(connection, self.world_id, name="Rin")
        self.encounter_id = make_encounter(connection, self.timeline_id, self.t0)
        self.external_system_id = make_external_system(connection, self.world_id)
        self.encounter_round_id = make_encounter_round(connection, self.encounter_id, 1)
        self.participant_id = make_encounter_participant(
            connection, self.encounter_id, self.character_id
        )
        self.encounter_turn_id = make_encounter_turn(
            connection, self.encounter_round_id, self.participant_id, 0
        )


@pytest.fixture
def f(db_connection: Connection) -> Fixture:
    return Fixture(db_connection, "integration-domain-world")


# ---------------------------------------------------------------------------
# integration.external_systems
# ---------------------------------------------------------------------------


def test_an_external_system_can_be_registered(db_connection: Connection, f: Fixture) -> None:
    assert f.external_system_id is not None


def test_an_external_systems_type_must_be_valid(db_connection: Connection, f: Fixture) -> None:
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_external_system(db_connection, f.world_id, system_type="carrier_pigeon")
    assert "ck_external_systems_system_type" in str(exc.value)


# ---------------------------------------------------------------------------
# integration.external_identifiers
# ---------------------------------------------------------------------------


def test_an_external_identifier_can_be_created(db_connection: Connection, f: Fixture) -> None:
    identifier_id = make_external_identifier(db_connection, f.external_system_id, f.character_id)
    assert identifier_id is not None


def test_an_external_identifier_is_unique_per_system_kind_and_external_id(
    db_connection: Connection, f: Fixture
) -> None:
    other_character = make_character(db_connection, f.world_id, name="Borrin")
    make_external_identifier(
        db_connection, f.external_system_id, f.character_id, external_id="actor-1"
    )
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_external_identifier(
            db_connection, f.external_system_id, other_character, external_id="actor-1"
        )
    assert "ux_external_identifiers_system_kind_external" in str(exc.value)


def test_an_external_identifiers_entity_must_share_the_systems_world(
    db_connection: Connection, f: Fixture
) -> None:
    other_world = make_world(db_connection, slug="integration-domain-other-world")
    foreign_character = make_character(db_connection, other_world)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_external_identifier(db_connection, f.external_system_id, foreign_character)
    assert "belongs to world" in str(exc.value)


# ---------------------------------------------------------------------------
# integration.sync_jobs
# ---------------------------------------------------------------------------


def test_a_sync_job_can_be_created(db_connection: Connection, f: Fixture) -> None:
    job_id = make_sync_job(db_connection, f.external_system_id, target_encounter_id=f.encounter_id)
    assert job_id is not None


def test_a_sync_jobs_direction_must_be_valid(db_connection: Connection, f: Fixture) -> None:
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_sync_job(db_connection, f.external_system_id, direction="sideways")
    assert "ck_sync_jobs_direction" in str(exc.value)


def test_a_sync_jobs_status_must_be_valid(db_connection: Connection, f: Fixture) -> None:
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_sync_job(db_connection, f.external_system_id, status="stuck")
    assert "ck_sync_jobs_status" in str(exc.value)


def test_a_sync_job_rejects_more_than_one_target(db_connection: Connection, f: Fixture) -> None:
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_sync_job(
            db_connection,
            f.external_system_id,
            target_entity_id=f.character_id,
            target_encounter_id=f.encounter_id,
        )
    assert "ck_sync_jobs_at_most_one_target" in str(exc.value)


def test_a_sync_job_with_no_target_is_valid(db_connection: Connection, f: Fixture) -> None:
    job_id = make_sync_job(db_connection, f.external_system_id)
    assert job_id is not None


def test_a_sync_jobs_target_encounter_must_share_the_systems_world(
    db_connection: Connection, f: Fixture
) -> None:
    other_world = make_world(db_connection, slug="integration-domain-job-other-world")
    other_timeline = make_timeline(db_connection, other_world, is_primary=True)
    other_t0 = make_world_time(db_connection, other_world, 100)
    foreign_encounter = make_encounter(db_connection, other_timeline, other_t0)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_sync_job(db_connection, f.external_system_id, target_encounter_id=foreign_encounter)
    assert "belongs to world" in str(exc.value)


def test_a_sync_job_can_record_its_resulting_encounter_turn(
    db_connection: Connection, f: Fixture
) -> None:
    job_id = make_sync_job(
        db_connection,
        f.external_system_id,
        target_encounter_id=f.encounter_id,
        status="completed",
        resulting_encounter_turn_id=f.encounter_turn_id,
    )
    assert job_id is not None


def test_an_external_operation_id_is_unique_per_external_system(
    db_connection: Connection, f: Fixture
) -> None:
    make_sync_job(db_connection, f.external_system_id, external_operation_id="op-1")
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_sync_job(db_connection, f.external_system_id, external_operation_id="op-1")
    assert "ux_sync_jobs_system_operation" in str(exc.value)


def test_the_same_external_operation_id_is_allowed_on_a_different_system(
    db_connection: Connection, f: Fixture
) -> None:
    other_system_id = make_external_system(db_connection, f.world_id, display_name="Other System")
    make_sync_job(db_connection, f.external_system_id, external_operation_id="op-1")
    job_id = make_sync_job(db_connection, other_system_id, external_operation_id="op-1")
    assert job_id is not None


def test_multiple_sync_jobs_may_omit_an_external_operation_id(
    db_connection: Connection, f: Fixture
) -> None:
    make_sync_job(db_connection, f.external_system_id)
    job_id = make_sync_job(db_connection, f.external_system_id)
    assert job_id is not None


# ---------------------------------------------------------------------------
# integration.sync_state
# ---------------------------------------------------------------------------


def test_sync_state_requires_exactly_one_target(db_connection: Connection, f: Fixture) -> None:
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_sync_state(db_connection, f.external_system_id)
    assert "ck_sync_state_exactly_one_target" in str(exc.value)


def test_sync_state_rejects_both_targets(db_connection: Connection, f: Fixture) -> None:
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_sync_state(
            db_connection,
            f.external_system_id,
            target_entity_id=f.character_id,
            target_encounter_id=f.encounter_id,
        )
    assert "ck_sync_state_exactly_one_target" in str(exc.value)


def test_sync_states_status_must_be_valid(db_connection: Connection, f: Fixture) -> None:
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_sync_state(
            db_connection, f.external_system_id, target_entity_id=f.character_id, sync_status="lost"
        )
    assert "ck_sync_state_status" in str(exc.value)


def test_only_one_sync_state_row_per_system_and_entity(
    db_connection: Connection, f: Fixture
) -> None:
    make_sync_state(db_connection, f.external_system_id, target_entity_id=f.character_id)
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_sync_state(db_connection, f.external_system_id, target_entity_id=f.character_id)
    assert "ux_sync_state_system_entity" in str(exc.value)


def test_only_one_sync_state_row_per_system_and_encounter(
    db_connection: Connection, f: Fixture
) -> None:
    make_sync_state(db_connection, f.external_system_id, target_encounter_id=f.encounter_id)
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_sync_state(db_connection, f.external_system_id, target_encounter_id=f.encounter_id)
    assert "ux_sync_state_system_encounter" in str(exc.value)


def test_sync_states_target_entity_must_share_the_systems_world(
    db_connection: Connection, f: Fixture
) -> None:
    other_world = make_world(db_connection, slug="integration-domain-state-other-world")
    foreign_character = make_character(db_connection, other_world)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_sync_state(db_connection, f.external_system_id, target_entity_id=foreign_character)
    assert "belongs to world" in str(exc.value)


# ---------------------------------------------------------------------------
# integration.delivery_attempts
# ---------------------------------------------------------------------------


def test_a_delivery_attempt_can_be_recorded(db_connection: Connection, f: Fixture) -> None:
    job_id = make_sync_job(db_connection, f.external_system_id)
    attempt_id = make_delivery_attempt(db_connection, job_id, succeeded=False)
    assert attempt_id is not None


def test_only_one_delivery_attempt_per_job_and_attempt_number(
    db_connection: Connection, f: Fixture
) -> None:
    job_id = make_sync_job(db_connection, f.external_system_id)
    make_delivery_attempt(db_connection, job_id, attempt_number=1, succeeded=False)
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_delivery_attempt(db_connection, job_id, attempt_number=1, succeeded=True)
    assert "ux_delivery_attempts_job_attempt" in str(exc.value)
