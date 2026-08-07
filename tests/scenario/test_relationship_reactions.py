"""evolve_relationship_reaction() / update_organization_status(): a dungeon
event changes a relationship's current status or subjective reaction, or an
organization's operational status (docs/PLAN.md Phase 8 exit criteria —
"NPC and faction reactions can evolve from events" and "Shared and
subjective relationship data are separate"). Required scenario test per
docs/DATABASE_CONVENTIONS.md §32.2.

Mirrors dnd_ai.commands.quests' advance_objective scenario test: build a
concrete scenario, drive it through the real commands, and verify the
recorded event, the updated campaign.relationship_state/organization_state,
and the linking narrative.event_effects row — not by inspecting the
transaction boundary.
"""

import threading
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, Engine, text

from dnd_ai.commands.relationships import (
    EvolveRelationshipReactionResult,
    evolve_relationship_reaction,
    update_organization_status,
)
from tests.factories import (
    make_character,
    make_organization,
    make_relationship,
    make_relationship_participant,
    make_relationship_perspective,
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
        self.faction_id = make_organization(
            connection,
            self.world_id,
            organization_type_code="criminal_organization",
            name="The Ashen Hand",
        )
        self.relationship_id = make_relationship(
            connection, self.world_id, relationship_type_code="rivalry"
        )
        make_relationship_participant(
            connection, self.relationship_id, self.actor_id, role_code="subject"
        )
        make_relationship_participant(
            connection, self.relationship_id, self.faction_id, role_code="rival"
        )
        # The authored baseline the faction starts with, distinct from the
        # timeline-scoped current reaction the commands below update.
        self.baseline_perspective_id = make_relationship_perspective(
            connection,
            self.relationship_id,
            self.faction_id,
            affinity=0,
            trust=0,
            emotional_tone="neutral",
        )


@pytest.fixture
def f(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as connection:
        fixture = Fixture(connection, f"relationship-reactions-{uuid.uuid4().hex[:8]}")
    yield fixture
    with postgres_engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        cleanup.execute(
            text("DELETE FROM core.entities WHERE world_id = :w"), {"w": fixture.world_id}
        )
        cleanup.execute(
            text("DELETE FROM core.worlds WHERE world_id = :w"), {"w": fixture.world_id}
        )


def _relationship_state(
    postgres_engine: Engine,
    timeline_id: uuid.UUID,
    relationship_id: uuid.UUID,
    holder: uuid.UUID | None,
) -> tuple[str, int | None] | None:
    with postgres_engine.connect() as verify:
        row = verify.execute(
            text("""
                SELECT rs2.code, rst.affinity
                FROM campaign.relationship_state rst
                JOIN campaign.relationship_statuses rs2
                    ON rs2.relationship_status_id = rst.relationship_status_id
                WHERE rst.timeline_id = :t AND rst.relationship_id = :r
                  AND rst.perspective_holder_entity_id IS NOT DISTINCT FROM :holder
            """),
            {"t": timeline_id, "r": relationship_id, "holder": holder},
        ).one_or_none()
    return (row.code, row.affinity) if row is not None else None


def _baseline_perspective_unchanged(postgres_engine: Engine, f: Fixture) -> bool:
    with postgres_engine.connect() as verify:
        row = verify.execute(
            text(
                "SELECT affinity, trust, emotional_tone FROM world.relationship_perspectives "
                "WHERE relationship_perspective_id = :p"
            ),
            {"p": f.baseline_perspective_id},
        ).one()
    return (row.affinity, row.trust, row.emotional_tone) == (0, 0, "neutral")


def test_an_event_changes_a_factions_subjective_reaction(
    postgres_engine: Engine, f: Fixture
) -> None:
    """The exit criterion's core claim: a faction's reaction to the party
    evolves from an event, without touching the authored baseline
    perspective."""
    result = evolve_relationship_reaction(
        postgres_engine,
        relationship_id=f.relationship_id,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_id,
        new_status_code="broken",
        perspective_holder_entity_id=f.faction_id,
        affinity=-70,
        trust=-40,
        emotional_tone="hostile",
        actor_entity_id=f.actor_id,
    )

    assert result.previous_status_code is None
    assert result.new_status_code == "broken"

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
        assert event_row.type_code == "relationship_changed"

        effect_row = verify.execute(
            text("""
                SELECT target_relationship_id, previous_value, new_value
                FROM narrative.event_effects WHERE event_id = :e
            """),
            {"e": result.event_id},
        ).one()
        assert effect_row.target_relationship_id == f.relationship_id
        assert effect_row.previous_value is None
        assert effect_row.new_value == "broken"

    assert _relationship_state(postgres_engine, f.timeline_id, f.relationship_id, f.faction_id) == (
        "broken",
        -70,
    )
    assert _baseline_perspective_unchanged(postgres_engine, f)


def test_shared_and_subjective_relationship_state_evolve_independently(
    postgres_engine: Engine, f: Fixture
) -> None:
    """The second exit criterion: shared/objective status and one
    participant's subjective reaction are separate rows that can diverge."""
    shared_result = evolve_relationship_reaction(
        postgres_engine,
        relationship_id=f.relationship_id,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_id,
        new_status_code="active",
    )
    holder_result = evolve_relationship_reaction(
        postgres_engine,
        relationship_id=f.relationship_id,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_id,
        new_status_code="estranged",
        perspective_holder_entity_id=f.faction_id,
        affinity=-20,
    )

    assert shared_result.relationship_state_id != holder_result.relationship_state_id
    assert _relationship_state(postgres_engine, f.timeline_id, f.relationship_id, None) == (
        "active",
        None,
    )
    assert _relationship_state(postgres_engine, f.timeline_id, f.relationship_id, f.faction_id) == (
        "estranged",
        -20,
    )


def test_evolving_an_existing_reaction_updates_it(postgres_engine: Engine, f: Fixture) -> None:
    first = evolve_relationship_reaction(
        postgres_engine,
        relationship_id=f.relationship_id,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_id,
        new_status_code="active",
        perspective_holder_entity_id=f.faction_id,
        affinity=10,
    )
    second = evolve_relationship_reaction(
        postgres_engine,
        relationship_id=f.relationship_id,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_id,
        new_status_code="broken",
        perspective_holder_entity_id=f.faction_id,
        affinity=-90,
    )

    assert first.relationship_state_id == second.relationship_state_id
    assert second.previous_status_code == "active"
    assert _relationship_state(postgres_engine, f.timeline_id, f.relationship_id, f.faction_id) == (
        "broken",
        -90,
    )


def test_an_event_changes_an_organizations_operational_status(
    postgres_engine: Engine, f: Fixture
) -> None:
    result = update_organization_status(
        postgres_engine,
        organization_id=f.faction_id,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_id,
        new_status_code="banned",
        actor_entity_id=f.actor_id,
    )

    assert result.previous_status_code is None
    assert result.new_status_code == "banned"

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
        assert event_row.type_code == "organization_status_changed"

        effect_row = verify.execute(
            text(
                "SELECT target_entity_id, new_value FROM narrative.event_effects WHERE event_id = :e"
            ),
            {"e": result.event_id},
        ).one()
        assert effect_row.target_entity_id == f.faction_id
        assert effect_row.new_value == "banned"

        state_row = verify.execute(
            text("""
                SELECT os.code
                FROM campaign.organization_state ost
                JOIN campaign.organization_statuses os
                    ON os.organization_status_id = ost.organization_status_id
                WHERE ost.timeline_id = :t AND ost.organization_id = :o
            """),
            {"t": f.timeline_id, "o": f.faction_id},
        ).one()
        assert state_row.code == "banned"


def test_two_concurrent_first_reactions_for_the_same_holder_serialize(
    postgres_engine: Engine, f: Fixture
) -> None:
    """Concurrency regression, mirroring advance_objective's own first-write
    guard: two concurrent evolve_relationship_reaction() calls for the same
    (timeline, relationship, holder) scope, both starting from "no
    campaign.relationship_state row yet", must not both race to INSERT and
    collide on ux_relationship_state_timeline_relationship_holder — the
    _lock_relationship row lock should serialize them into two clean
    sequential writes instead."""
    barrier = threading.Barrier(2)
    results: dict[str, EvolveRelationshipReactionResult] = {}
    errors: dict[str, Exception] = {}

    def _evolve(label: str, status_code: str, affinity: int) -> None:
        barrier.wait(timeout=30)
        try:
            results[label] = evolve_relationship_reaction(
                postgres_engine,
                relationship_id=f.relationship_id,
                timeline_id=f.timeline_id,
                world_time_id=f.world_time_id,
                new_status_code=status_code,
                perspective_holder_entity_id=f.faction_id,
                affinity=affinity,
            )
        except Exception as exc:  # noqa: BLE001 - captured for the assertion below
            errors[label] = exc

    thread_a = threading.Thread(target=_evolve, args=("a", "active", 5))
    thread_b = threading.Thread(target=_evolve, args=("b", "broken", -5))
    thread_a.start()
    thread_b.start()
    thread_a.join(timeout=30)
    thread_b.join(timeout=30)
    assert not thread_a.is_alive(), "evolve_relationship_reaction for thread a did not finish"
    assert not thread_b.is_alive(), "evolve_relationship_reaction for thread b did not finish"

    assert not errors, f"expected both calls to serialize cleanly, got errors: {errors}"
    assert len(results) == 2

    with postgres_engine.connect() as verify:
        state_count = verify.execute(
            text("""
                SELECT count(*) FROM campaign.relationship_state
                WHERE timeline_id = :t AND relationship_id = :r
                  AND perspective_holder_entity_id = :holder
            """),
            {"t": f.timeline_id, "r": f.relationship_id, "holder": f.faction_id},
        ).scalar()
        assert state_count == 1

        event_count = verify.execute(
            text("""
                SELECT count(*) FROM narrative.events ev
                JOIN narrative.event_types et ON et.event_type_id = ev.event_type_id
                WHERE et.code = 'relationship_changed' AND ev.timeline_id = :t
            """),
            {"t": f.timeline_id},
        ).scalar()
        assert event_count == 2
