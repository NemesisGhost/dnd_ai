"""transfer_item_possession() / identify_item(): a dungeon event changes who
currently holds an item instance, or what a knower currently knows about one
(docs/PLAN.md Phase 9). Required scenario test per
docs/DATABASE_CONVENTIONS.md §32.2.

Mirrors dnd_ai.commands.relationships' scenario test: build a concrete
scenario, drive it through the real commands, and verify the recorded
event, the updated campaign.inventory_entries/knowledge.item_identification
row, and the linking narrative.event_effects row — not by inspecting the
transaction boundary. Also covers a first-write concurrency regression for
transfer_item_possession() (the same _lock_item_instance guard
evolve_relationship_reaction() has a test for) and an atomic-rollback proof.
"""

import threading
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import IntegrityError

from dnd_ai.commands.items import (
    TransferItemPossessionResult,
    identify_item,
    transfer_item_possession,
)
from tests.factories import (
    make_character,
    make_item_definition,
    make_item_instance,
    make_location,
    make_ruleset_version_for_world,
    make_timeline,
    make_world,
    make_world_time,
)

pytestmark = pytest.mark.scenario


class Fixture:
    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        self.world_time_id = make_world_time(connection, self.world_id, 100)
        self.actor_id = make_character(connection, self.world_id, name="Rin")
        self.holder_id = make_character(connection, self.world_id, name="Borrin")
        self.location_id = make_location(connection, self.world_id)
        ruleset_version_id = make_ruleset_version_for_world(connection, self.world_id)
        item_definition_id = make_item_definition(connection, ruleset_version_id)
        self.item_instance_id = make_item_instance(connection, self.world_id, item_definition_id)


@pytest.fixture
def f(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as connection:
        fixture = Fixture(connection, f"item-commands-{uuid.uuid4().hex[:8]}")
    yield fixture
    with postgres_engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        cleanup.execute(
            text("DELETE FROM core.entities WHERE world_id = :w"), {"w": fixture.world_id}
        )
        cleanup.execute(
            text("DELETE FROM core.worlds WHERE world_id = :w"), {"w": fixture.world_id}
        )


def _inventory_entry(
    postgres_engine: Engine, timeline_id: uuid.UUID, item_instance_id: uuid.UUID
) -> tuple[uuid.UUID | None, uuid.UUID | None, uuid.UUID | None] | None:
    with postgres_engine.connect() as verify:
        row = verify.execute(
            text("""
                SELECT holder_entity_id, container_id, location_id
                FROM campaign.inventory_entries
                WHERE timeline_id = :t AND item_instance_id = :i
            """),
            {"t": timeline_id, "i": item_instance_id},
        ).one_or_none()
    return (row.holder_entity_id, row.container_id, row.location_id) if row is not None else None


def test_an_event_places_an_item_with_a_holder(postgres_engine: Engine, f: Fixture) -> None:
    result = transfer_item_possession(
        postgres_engine,
        item_instance_id=f.item_instance_id,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_id,
        holder_entity_id=f.holder_id,
        actor_entity_id=f.actor_id,
    )

    with postgres_engine.connect() as verify:
        event_row = verify.execute(
            text("""
                SELECT et.code AS type_code
                FROM narrative.events ev
                JOIN narrative.event_types et ON et.event_type_id = ev.event_type_id
                WHERE ev.event_id = :e
            """),
            {"e": result.event_id},
        ).one()
        assert event_row.type_code == "item_transferred"

        effect_row = verify.execute(
            text("SELECT target_entity_id FROM narrative.event_effects WHERE event_id = :e"),
            {"e": result.event_id},
        ).one()
        assert effect_row.target_entity_id == f.item_instance_id

    assert _inventory_entry(postgres_engine, f.timeline_id, f.item_instance_id) == (
        f.holder_id,
        None,
        None,
    )


def test_transferring_an_already_placed_item_updates_the_same_row(
    postgres_engine: Engine, f: Fixture
) -> None:
    first = transfer_item_possession(
        postgres_engine,
        item_instance_id=f.item_instance_id,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_id,
        holder_entity_id=f.holder_id,
    )
    second = transfer_item_possession(
        postgres_engine,
        item_instance_id=f.item_instance_id,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_id,
        location_id=f.location_id,
    )

    assert first.inventory_entry_id == second.inventory_entry_id
    assert _inventory_entry(postgres_engine, f.timeline_id, f.item_instance_id) == (
        None,
        None,
        f.location_id,
    )


def test_an_event_advances_a_knowers_identification_of_an_item(
    postgres_engine: Engine, f: Fixture
) -> None:
    result = identify_item(
        postgres_engine,
        item_instance_id=f.item_instance_id,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_id,
        knower_entity_id=f.holder_id,
        new_level="fully_identified",
        known_properties={"bonus": "+1"},
        actor_entity_id=f.actor_id,
    )

    assert result.previous_level is None
    assert result.new_level == "fully_identified"

    with postgres_engine.connect() as verify:
        row = verify.execute(
            text("""
                SELECT identification_level, known_properties_jsonb
                FROM knowledge.item_identification
                WHERE timeline_id = :t AND item_instance_id = :i AND knower_entity_id = :k
            """),
            {"t": f.timeline_id, "i": f.item_instance_id, "k": f.holder_id},
        ).one()
    assert row.identification_level == "fully_identified"
    assert row.known_properties_jsonb == {"bonus": "+1"}


def test_two_concurrent_first_placements_for_the_same_item_serialize(
    postgres_engine: Engine, f: Fixture
) -> None:
    """Concurrency regression: two concurrent transfer_item_possession()
    calls for the same (timeline, item instance), both starting from "no
    campaign.inventory_entries row yet", must not both race to INSERT and
    collide on ux_inventory_entries_timeline_item — the _lock_item_instance
    row lock should serialize them into two clean sequential writes
    instead."""
    barrier = threading.Barrier(2)
    results: dict[str, TransferItemPossessionResult] = {}
    errors: dict[str, Exception] = {}

    def _transfer(label: str, holder_id: uuid.UUID | None, location_id: uuid.UUID | None) -> None:
        barrier.wait(timeout=30)
        try:
            results[label] = transfer_item_possession(
                postgres_engine,
                item_instance_id=f.item_instance_id,
                timeline_id=f.timeline_id,
                world_time_id=f.world_time_id,
                holder_entity_id=holder_id,
                location_id=location_id,
            )
        except Exception as exc:  # noqa: BLE001 - captured for the assertion below
            errors[label] = exc

    thread_a = threading.Thread(target=_transfer, args=("a", f.holder_id, None))
    thread_b = threading.Thread(target=_transfer, args=("b", None, f.location_id))
    thread_a.start()
    thread_b.start()
    thread_a.join(timeout=30)
    thread_b.join(timeout=30)
    assert not thread_a.is_alive(), "transfer_item_possession for thread a did not finish"
    assert not thread_b.is_alive(), "transfer_item_possession for thread b did not finish"

    assert not errors, f"expected both calls to serialize cleanly, got errors: {errors}"
    assert len(results) == 2

    with postgres_engine.connect() as verify:
        entry_count = verify.execute(
            text("""
                SELECT count(*) FROM campaign.inventory_entries
                WHERE timeline_id = :t AND item_instance_id = :i
            """),
            {"t": f.timeline_id, "i": f.item_instance_id},
        ).scalar()
        assert entry_count == 1

        event_count = verify.execute(
            text("""
                SELECT count(*) FROM narrative.events ev
                JOIN narrative.event_types et ON et.event_type_id = ev.event_type_id
                WHERE et.code = 'item_transferred' AND ev.timeline_id = :t
            """),
            {"t": f.timeline_id},
        ).scalar()
        assert event_count == 2


def test_a_failed_transfer_leaves_no_partial_write(postgres_engine: Engine, f: Fixture) -> None:
    """Atomicity proof: transfer_item_possession() has no lookup-code
    argument of its own to fail on, so this exercises identify_item()'s
    invalid new_level instead — lookup_id() is not involved there either,
    but the CHECK constraint on knowledge.item_identification.
    identification_level fires only at commit-time INSERT, after
    _insert_event_row() has already run inside the same transaction. The
    whole engine.begin() transaction must roll back, leaving no trace of
    the event or the event_effects row."""
    with pytest.raises(IntegrityError):
        identify_item(
            postgres_engine,
            item_instance_id=f.item_instance_id,
            timeline_id=f.timeline_id,
            world_time_id=f.world_time_id,
            knower_entity_id=f.holder_id,
            new_level="not_a_real_level",
        )

    with postgres_engine.connect() as verify:
        event_count = verify.execute(
            text("SELECT count(*) FROM narrative.events WHERE timeline_id = :t"),
            {"t": f.timeline_id},
        ).scalar()
        assert event_count == 0, "an event survived a rolled-back identify_item"

        identification_count = verify.execute(
            text("SELECT count(*) FROM knowledge.item_identification WHERE timeline_id = :t"),
            {"t": f.timeline_id},
        ).scalar()
        assert identification_count == 0, (
            "an item_identification row survived a rolled-back identify_item"
        )


def test_a_transfer_with_an_unknown_actor_leaves_no_partial_write(
    postgres_engine: Engine, f: Fixture
) -> None:
    """A second atomicity proof via a different failure path: a nonexistent
    actor_entity_id passes transfer_item_possession()'s own checks (it has
    no lookup-code argument to fail on the way evolve_relationship_reaction
    does) but fails the foreign key on narrative.event_participants.
    participant_entity_id — after _insert_event_row() has already inserted
    core.entities/narrative.events in the same transaction. The whole
    engine.begin() transaction must still roll back."""
    with pytest.raises(IntegrityError):
        transfer_item_possession(
            postgres_engine,
            item_instance_id=f.item_instance_id,
            timeline_id=f.timeline_id,
            world_time_id=f.world_time_id,
            holder_entity_id=f.holder_id,
            actor_entity_id=uuid.uuid4(),
        )

    with postgres_engine.connect() as verify:
        event_count = verify.execute(
            text("SELECT count(*) FROM narrative.events WHERE timeline_id = :t"),
            {"t": f.timeline_id},
        ).scalar()
        assert event_count == 0, "an event survived a rolled-back transfer_item_possession"

        entry_count = verify.execute(
            text("""
                SELECT count(*) FROM campaign.inventory_entries
                WHERE timeline_id = :t AND item_instance_id = :i
            """),
            {"t": f.timeline_id, "i": f.item_instance_id},
        ).scalar()
        assert entry_count == 0, (
            "an inventory_entries row survived a rolled-back transfer_item_possession"
        )
