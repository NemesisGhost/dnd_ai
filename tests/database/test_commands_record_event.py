"""dnd_ai.commands.events.record_event — the RecordEvent command
(docs/ENTITY_LIFECYCLE.md §21).

The first application-layer code in this repository that mutates state
(docs/architecture/SYSTEM_ARCHITECTURE.md §5.3). record_event() owns its own
transaction (engine.begin()), so these tests use postgres_engine directly
rather than the rolled-back db_connection fixture, and verify results from a
fresh connection on the same engine — real commits, not an uncommitted
transaction the test fixture would discard.
"""

import uuid

import pytest
from sqlalchemy import Engine, text

from dnd_ai.commands._shared import LookupCodeNotFoundError
from dnd_ai.commands.events import EventParticipant, record_event
from tests.factories import (
    make_character,
    make_interaction,
    make_timeline,
    make_world,
    make_world_time,
)

pytestmark = pytest.mark.database


@pytest.fixture
def world(postgres_engine: Engine) -> uuid.UUID:
    with postgres_engine.begin() as connection:
        world_id = make_world(connection, slug=f"record-event-command-{uuid.uuid4().hex[:8]}")
    yield world_id
    with postgres_engine.begin() as cleanup:
        # These tests record real events at status = recorded, which
        # revision 065's triggers now correctly make append-only (including
        # under cascade) — exactly the behavior under test. Test-only
        # teardown is the one place that legitimately needs to remove that
        # data anyway, so it bypasses triggers for this transaction only.
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        # Entities first: cascades away narrative.events (and event_causes,
        # which must be gone before interactions are deleted below, since
        # event_causes.cause_interaction_id is ON DELETE SET NULL and would
        # otherwise violate ck_event_causes_has_cause on a cause-only row).
        cleanup.execute(text("DELETE FROM core.entities WHERE world_id = :w"), {"w": world_id})
        # interaction.interactions.world_time_id is ON DELETE RESTRICT, and
        # core.worlds cascades to core.world_times independently of the
        # timeline_id cascade path that would otherwise remove interactions
        # first — delete interactions explicitly so the two cascade paths
        # can't race.
        cleanup.execute(
            text("""
                DELETE FROM interaction.interactions
                WHERE timeline_id IN (SELECT timeline_id FROM campaign.timelines WHERE world_id = :w)
            """),
            {"w": world_id},
        )
        cleanup.execute(text("DELETE FROM core.worlds WHERE world_id = :w"), {"w": world_id})


def test_record_event_creates_the_entity_and_events_row(
    postgres_engine: Engine, world: uuid.UUID
) -> None:
    with postgres_engine.begin() as connection:
        timeline_id = make_timeline(connection, world, is_primary=True)
        world_time_id = make_world_time(connection, world, 100)

    result = record_event(
        postgres_engine,
        world_id=world,
        timeline_id=timeline_id,
        world_time_id=world_time_id,
        event_type_code="other",
        name="A quiet arrival",
        details="The party enters the ruin.",
    )

    with postgres_engine.connect() as verify:
        row = verify.execute(
            text("""
                SELECT e.canonical_name, ev.details, ev.timeline_id, ev.world_time_id,
                       est.code AS status_code, et.code AS type_code
                FROM core.entities e
                JOIN narrative.events ev ON ev.event_id = e.entity_id
                JOIN narrative.event_statuses est ON est.event_status_id = ev.event_status_id
                JOIN narrative.event_types et ON et.event_type_id = ev.event_type_id
                WHERE e.entity_id = :id
            """),
            {"id": result.event_id},
        ).one()
        assert row.canonical_name == "A quiet arrival"
        assert row.details == "The party enters the ruin."
        assert row.timeline_id == timeline_id
        assert row.world_time_id == world_time_id
        assert row.status_code == "recorded"
        assert row.type_code == "other"


def test_record_event_records_participants_and_an_interaction_cause(
    postgres_engine: Engine, world: uuid.UUID
) -> None:
    with postgres_engine.begin() as connection:
        timeline_id = make_timeline(connection, world, is_primary=True)
        world_time_id = make_world_time(connection, world, 100)
        actor_id = make_character(connection, world, name="Rin")
        interaction_id = make_interaction(connection, timeline_id, world_time_id)

    result = record_event(
        postgres_engine,
        world_id=world,
        timeline_id=timeline_id,
        world_time_id=world_time_id,
        event_type_code="other",
        name="Rin acts",
        participants=(EventParticipant(entity_id=actor_id, role_code="actor"),),
        cause_interaction_id=interaction_id,
    )

    with postgres_engine.connect() as verify:
        participant_role = verify.execute(
            text("""
                SELECT r.code FROM narrative.event_participants p
                JOIN narrative.event_participant_roles r
                    ON r.event_participant_role_id = p.participant_role_id
                WHERE p.event_id = :e AND p.participant_entity_id = :actor
            """),
            {"e": result.event_id, "actor": actor_id},
        ).scalar()
        assert participant_role == "actor"

        cause_interaction = verify.execute(
            text("SELECT cause_interaction_id FROM narrative.event_causes WHERE event_id = :e"),
            {"e": result.event_id},
        ).scalar()
        assert cause_interaction == interaction_id


def test_record_event_rejects_an_unknown_event_type_code_before_writing_anything(
    postgres_engine: Engine, world: uuid.UUID
) -> None:
    with postgres_engine.begin() as connection:
        timeline_id = make_timeline(connection, world, is_primary=True)
        world_time_id = make_world_time(connection, world, 100)

    with pytest.raises(LookupCodeNotFoundError):
        record_event(
            postgres_engine,
            world_id=world,
            timeline_id=timeline_id,
            world_time_id=world_time_id,
            event_type_code="not_a_real_event_type",
            name="Should not exist",
        )

    with postgres_engine.connect() as verify:
        count = verify.execute(
            text("SELECT count(*) FROM narrative.events WHERE timeline_id = :t"),
            {"t": timeline_id},
        ).scalar()
        assert count == 0, "a rejected record_event() call left an events row behind"
