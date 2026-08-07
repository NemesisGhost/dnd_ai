"""Event + typed-state changes commit atomically, or not at all (rule 6).

docs/PLAN.md names this Phase 6's "first full exercise of rule 6" (state
changes need a causal event, committing atomically) and requires: "A failure
partway through a multi-domain command leaves no partial write — proven by a
test that forces the failure, not by inspecting the transaction boundary."

No command/service layer exists yet in src/dnd_ai (confirmed by survey before
writing this) — docs/architecture/DATABASE_MODEL.md §17 is explicit that rule
6's atomicity guarantee is "a transaction-boundary guarantee the command
layer provides, not a column these tables were missing." This test proves the
schema supports that guarantee: a hand-written transaction that writes an
event, an event_effect, and updates campaign.hazard_state's last_event_id all
together, then deliberately fails a later statement in the same transaction,
demonstrably leaves none of it behind — checked from an independent
connection, not by inspecting the transaction code.
"""

import uuid

import pytest
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import IntegrityError

from tests.factories import (
    lookup_id,
    make_area_hazard,
    make_dungeon,
    make_dungeon_area,
    make_entity,
    make_event,
    make_timeline,
    make_world,
    make_world_time,
)

pytestmark = pytest.mark.database


def _hazard_status_code(
    connection: Connection, timeline_id: uuid.UUID, hazard_id: uuid.UUID
) -> str | None:
    return connection.execute(
        text("""
            SELECT hs.code FROM campaign.hazard_state hst
            JOIN campaign.hazard_statuses hs ON hs.hazard_status_id = hst.hazard_status_id
            WHERE hst.timeline_id = :tl AND hst.area_hazard_id = :h
        """),
        {"tl": timeline_id, "h": hazard_id},
    ).scalar()


def test_a_failed_transaction_leaves_no_partial_event_or_state_write(
    postgres_engine: Engine,
) -> None:
    engine = postgres_engine
    slug = f"event-atomicity-{uuid.uuid4().hex[:8]}"

    with engine.begin() as setup:
        world_id = make_world(setup, slug=slug)
        timeline_id = make_timeline(setup, world_id, is_primary=True)
        world_time_id = make_world_time(setup, world_id, 100)
        dungeon_id = make_dungeon(setup, world_id)
        area_id = make_dungeon_area(setup, dungeon_id)
        hazard_id = make_area_hazard(setup, area_id, is_hidden=True)
        armed = lookup_id(setup, "campaign", "hazard_statuses", "hazard_status_id", "armed")
        disarmed = lookup_id(setup, "campaign", "hazard_statuses", "hazard_status_id", "disarmed")

        # Pre-existing current state, as if a prior (successful) command had
        # armed the hazard.
        setup.execute(
            text(
                "INSERT INTO campaign.hazard_state (timeline_id, area_hazard_id, "
                "hazard_status_id) VALUES (:tl, :h, :s)"
            ),
            {"tl": timeline_id, "h": hazard_id, "s": armed},
        )

    try:
        work = engine.connect()
        try:
            work.begin()

            # Step 1: record the event.
            event_id = make_event(
                work, world_id, timeline_id, world_time_id, details="The party disarms the trap."
            )

            # Step 2: record the machine-readable effect.
            work.execute(
                text(
                    "INSERT INTO narrative.event_effects "
                    "(event_id, target_area_hazard_id, target_component, "
                    "previous_value, new_value) "
                    "VALUES (:e, :h, 'hazard_status_id', '\"armed\"'::jsonb, '\"disarmed\"'::jsonb)"
                ),
                {"e": event_id, "h": hazard_id},
            )

            # Step 3: close old state, insert new state (rule 6, step 6 of
            # docs/architecture/SYSTEM_ARCHITECTURE.md §6's command flow).
            work.execute(
                text(
                    "UPDATE campaign.hazard_state SET hazard_status_id = :s, last_event_id = :e "
                    "WHERE timeline_id = :tl AND area_hazard_id = :h"
                ),
                {"s": disarmed, "e": event_id, "tl": timeline_id, "h": hazard_id},
            )

            # Step 4: something later in the same command fails — a second,
            # malformed effect row (violates the at-most-one-target CHECK; a
            # real same-world entity is used as the second target so the
            # world-agreement trigger passes and the CHECK is what actually
            # fires). This is the forced failure the exit criterion requires.
            location_entity_type = lookup_id(
                work, "core", "entity_types", "entity_type_id", "location"
            )
            other_target = make_entity(work, world_id, location_entity_type)
            with pytest.raises(IntegrityError) as exc:
                work.execute(
                    text(
                        "INSERT INTO narrative.event_effects "
                        "(event_id, target_area_hazard_id, target_entity_id, target_component) "
                        "VALUES (:e, :h, :other, 'x')"
                    ),
                    {"e": event_id, "h": hazard_id, "other": other_target},
                )
            assert "ck_event_effects_at_most_one_target" in str(exc.value)
        finally:
            # PostgreSQL aborts the whole transaction once a statement fails;
            # rollback is the only valid next step, and is itself the point —
            # this is what "leaves no partial write" actually rests on.
            work.rollback()
            work.close()

        # Verify from a brand-new, independent connection: nothing committed.
        with engine.connect() as verify:
            event_exists = verify.execute(
                text("SELECT 1 FROM narrative.events WHERE event_id = :e"), {"e": event_id}
            ).scalar()
            assert event_exists is None, "the event survived a rolled-back transaction"

            effect_count = verify.execute(
                text("SELECT count(*) FROM narrative.event_effects WHERE event_id = :e"),
                {"e": event_id},
            ).scalar()
            assert effect_count == 0, "an event_effects row survived a rolled-back transaction"

            status = _hazard_status_code(verify, timeline_id, hazard_id)
            assert status == "armed", (
                f"hazard_state shows {status!r} — the rolled-back UPDATE partially took effect"
            )
    finally:
        with engine.begin() as cleanup:
            cleanup.execute(text("DELETE FROM core.entities WHERE world_id = :w"), {"w": world_id})
            cleanup.execute(text("DELETE FROM core.worlds WHERE world_id = :w"), {"w": world_id})
