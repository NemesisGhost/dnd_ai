"""start_encounter() / resolve_combat_turn() / end_encounter(): a dungeon
(or Foundry) combat session updates persistent character and world state
(docs/PLAN.md Phase 9 exit criterion: "Foundry combat can update persistent
character and world state"). Required scenario test per
docs/DATABASE_CONVENTIONS.md §32.2.

Mirrors dnd_ai.commands.relationships' scenario test: build a concrete
scenario, drive it through the real commands, and verify the recorded
event, the updated campaign.character_state row, and the linking
narrative.event_effects/event_causes rows — not by inspecting the
transaction boundary.
"""

import threading
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, Engine, text

from dnd_ai.commands.encounters import (
    EncounterNotActiveError,
    EndEncounterResult,
    SessionNotInCampaignError,
    end_encounter,
    resolve_combat_turn,
    start_encounter,
)
from tests.factories import (
    make_campaign,
    make_character,
    make_character_state,
    make_session,
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
        self.attacker_id = make_character(connection, self.world_id, name="Rin")
        self.defender_id = make_character(connection, self.world_id, name="Borrin")
        # "pending" sidesteps the active-campaign access-manager retention
        # invariant (revision 080) — these tests don't grant access.manage
        # and don't otherwise care about campaign lifecycle.
        self.campaign_id = make_campaign(
            connection, self.timeline_id, lifecycle_status_code="pending"
        )
        self.session_id = make_session(connection, self.campaign_id, 1)
        make_character_state(
            connection,
            self.timeline_id,
            self.defender_id,
            current_hit_points=20,
            maximum_hit_points=20,
        )


@pytest.fixture
def f(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as connection:
        fixture = Fixture(connection, f"encounter-commands-{uuid.uuid4().hex[:8]}")
    yield fixture
    with postgres_engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        cleanup.execute(
            text("DELETE FROM core.entities WHERE world_id = :w"), {"w": fixture.world_id}
        )
        cleanup.execute(
            text("DELETE FROM core.worlds WHERE world_id = :w"), {"w": fixture.world_id}
        )


def _character_hit_points(
    postgres_engine: Engine, timeline_id: uuid.UUID, character_id: uuid.UUID
) -> int:
    with postgres_engine.connect() as verify:
        value = verify.execute(
            text("""
                SELECT current_hit_points FROM campaign.character_state
                WHERE timeline_id = :t AND character_id = :c
            """),
            {"t": timeline_id, "c": character_id},
        ).scalar()
    assert isinstance(value, int)
    return value


def test_starting_an_encounter_creates_it_with_its_participants(
    postgres_engine: Engine, f: Fixture
) -> None:
    result = start_encounter(
        postgres_engine,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_id,
        participant_entity_ids=(f.attacker_id, f.defender_id),
    )

    with postgres_engine.connect() as verify:
        row = verify.execute(
            text("SELECT status FROM narrative.encounters WHERE encounter_id = :e"),
            {"e": result.encounter_id},
        ).one()
        assert row.status == "active"

        participant_count = verify.execute(
            text("SELECT count(*) FROM narrative.encounter_participants WHERE encounter_id = :e"),
            {"e": result.encounter_id},
        ).scalar()
        assert participant_count == 2


def test_a_damaging_combat_turn_updates_persistent_character_state(
    postgres_engine: Engine, f: Fixture
) -> None:
    """The exit criterion's core claim: combat updates persistent
    character state, with a causal event citing the encounter."""
    start = start_encounter(
        postgres_engine,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_id,
        participant_entity_ids=(f.attacker_id, f.defender_id),
    )

    result = resolve_combat_turn(
        postgres_engine,
        encounter_id=start.encounter_id,
        round_number=1,
        turn_order=0,
        actor_entity_id=f.attacker_id,
        world_time_id=f.world_time_id,
        action_kind="attack",
        target_entity_id=f.defender_id,
        hit=True,
        damage_amount=7,
    )

    assert result.previous_hit_points == 20
    assert result.new_hit_points == 13
    assert result.event_id is not None
    assert _character_hit_points(postgres_engine, f.timeline_id, f.defender_id) == 13

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
        assert event_row.type_code == "combat_damage_dealt"

        cause_row = verify.execute(
            text("SELECT cause_encounter_id FROM narrative.event_causes WHERE event_id = :e"),
            {"e": result.event_id},
        ).one()
        assert cause_row.cause_encounter_id == start.encounter_id

        effect_row = verify.execute(
            text("""
                SELECT target_entity_id, previous_value, new_value
                FROM narrative.event_effects WHERE event_id = :e
            """),
            {"e": result.event_id},
        ).one()
        assert effect_row.target_entity_id == f.defender_id
        assert effect_row.previous_value == 20
        assert effect_row.new_value == 13

        combat_action_row = verify.execute(
            text("""
                SELECT ca.hit, ca.damage_amount
                FROM narrative.encounter_turns et
                JOIN interaction.combat_actions ca ON ca.combat_action_id = et.combat_action_id
                WHERE et.encounter_turn_id = :turn
            """),
            {"turn": result.encounter_turn_id},
        ).one()
        assert combat_action_row.hit is True
        assert combat_action_row.damage_amount == 7


def test_a_miss_leaves_character_state_and_events_untouched(
    postgres_engine: Engine, f: Fixture
) -> None:
    """Not every attack roll needs a permanent world event
    (docs/architecture/DATABASE_MODEL.md §12.3) — a miss updates only the
    turn/combat_action record."""
    start = start_encounter(
        postgres_engine,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_id,
        participant_entity_ids=(f.attacker_id, f.defender_id),
    )

    result = resolve_combat_turn(
        postgres_engine,
        encounter_id=start.encounter_id,
        round_number=1,
        turn_order=0,
        actor_entity_id=f.attacker_id,
        world_time_id=f.world_time_id,
        action_kind="attack",
        target_entity_id=f.defender_id,
        hit=False,
    )

    assert result.event_id is None
    assert result.new_hit_points is None
    assert _character_hit_points(postgres_engine, f.timeline_id, f.defender_id) == 20


def test_a_miss_with_a_submitted_damage_amount_still_never_applies_it(
    postgres_engine: Engine, f: Fixture
) -> None:
    """Regression: hit=False must be authoritative over damage_amount — a
    caller that reports both a miss and a rolled damage number (a
    submitted-but-not-landed roll) must never have that damage applied or
    an event recorded, even though damage_amount alone would previously
    have triggered both. The submitted damage_amount is still preserved on
    the combat_actions row as payload/result data."""
    start = start_encounter(
        postgres_engine,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_id,
        participant_entity_ids=(f.attacker_id, f.defender_id),
    )

    result = resolve_combat_turn(
        postgres_engine,
        encounter_id=start.encounter_id,
        round_number=1,
        turn_order=0,
        actor_entity_id=f.attacker_id,
        world_time_id=f.world_time_id,
        action_kind="attack",
        target_entity_id=f.defender_id,
        hit=False,
        damage_amount=7,
    )

    assert result.event_id is None
    assert result.new_hit_points is None
    assert result.previous_hit_points is None
    assert _character_hit_points(postgres_engine, f.timeline_id, f.defender_id) == 20

    with postgres_engine.connect() as verify:
        combat_action_row = verify.execute(
            text("""
                SELECT ca.hit, ca.damage_amount
                FROM narrative.encounter_turns et
                JOIN interaction.combat_actions ca ON ca.combat_action_id = et.combat_action_id
                WHERE et.encounter_turn_id = :turn
            """),
            {"turn": result.encounter_turn_id},
        ).one()
        assert combat_action_row.hit is False
        assert combat_action_row.damage_amount == 7

        event_count = verify.execute(
            text("SELECT count(*) FROM narrative.events WHERE timeline_id = :t"),
            {"t": f.timeline_id},
        ).scalar()
        assert event_count == 0


def test_ending_an_encounter_records_outcomes_and_completes_it(
    postgres_engine: Engine, f: Fixture
) -> None:
    start = start_encounter(
        postgres_engine,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_id,
        participant_entity_ids=(f.attacker_id, f.defender_id),
    )

    result = end_encounter(
        postgres_engine,
        encounter_id=start.encounter_id,
        world_time_id=f.world_time_id,
        outcomes=((f.defender_id, "defeated"),),
        summary="The party prevailed.",
    )

    with postgres_engine.connect() as verify:
        encounter_row = verify.execute(
            text("""
                SELECT status, resulting_event_id, summary FROM narrative.encounters
                WHERE encounter_id = :e
            """),
            {"e": start.encounter_id},
        ).one()
        assert encounter_row.status == "completed"
        assert encounter_row.resulting_event_id == result.event_id
        assert encounter_row.summary == "The party prevailed."

        outcome_row = verify.execute(
            text("""
                SELECT outcome FROM narrative.encounter_participants
                WHERE encounter_id = :e AND participant_entity_id = :p
            """),
            {"e": start.encounter_id, "p": f.defender_id},
        ).one()
        assert outcome_row.outcome == "defeated"


def test_resolving_a_turn_for_a_non_participant_fails_cleanly(
    postgres_engine: Engine, f: Fixture
) -> None:
    """Atomicity proof: an actor who never joined the encounter fails
    _participant_id()'s lookup after the round has already been created —
    the whole transaction must roll back, leaving no round or turn behind."""
    start = start_encounter(
        postgres_engine,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_id,
        participant_entity_ids=(f.attacker_id,),
    )

    with postgres_engine.begin() as connection:
        outsider_id = make_character(connection, f.world_id, name="Outsider")

    with pytest.raises(ValueError, match="is not a participant"):
        resolve_combat_turn(
            postgres_engine,
            encounter_id=start.encounter_id,
            round_number=1,
            turn_order=0,
            actor_entity_id=outsider_id,
            world_time_id=f.world_time_id,
        )

    with postgres_engine.connect() as verify:
        round_count = verify.execute(
            text("SELECT count(*) FROM narrative.encounter_rounds WHERE encounter_id = :e"),
            {"e": start.encounter_id},
        ).scalar()
        assert round_count == 0, "a round row survived a rolled-back resolve_combat_turn"


# ---------------------------------------------------------------------------
# Encounter lifecycle enforcement
# ---------------------------------------------------------------------------


def test_resolving_a_turn_on_a_completed_encounter_is_rejected(
    postgres_engine: Engine, f: Fixture
) -> None:
    start = start_encounter(
        postgres_engine,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_id,
        participant_entity_ids=(f.attacker_id, f.defender_id),
    )
    end_encounter(postgres_engine, encounter_id=start.encounter_id, world_time_id=f.world_time_id)

    with pytest.raises(EncounterNotActiveError):
        resolve_combat_turn(
            postgres_engine,
            encounter_id=start.encounter_id,
            round_number=1,
            turn_order=0,
            actor_entity_id=f.attacker_id,
            world_time_id=f.world_time_id,
            target_entity_id=f.defender_id,
            hit=True,
            damage_amount=7,
        )

    # No round/turn/event survived the rejected turn, and HP is untouched.
    with postgres_engine.connect() as verify:
        round_count = verify.execute(
            text("SELECT count(*) FROM narrative.encounter_rounds WHERE encounter_id = :e"),
            {"e": start.encounter_id},
        ).scalar()
        assert round_count == 0
    assert _character_hit_points(postgres_engine, f.timeline_id, f.defender_id) == 20


def test_ending_an_already_completed_encounter_is_rejected_and_leaves_state_untouched(
    postgres_engine: Engine, f: Fixture
) -> None:
    start = start_encounter(
        postgres_engine,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_id,
        participant_entity_ids=(f.attacker_id, f.defender_id),
    )
    first = end_encounter(
        postgres_engine,
        encounter_id=start.encounter_id,
        world_time_id=f.world_time_id,
        summary="First completion.",
    )

    with pytest.raises(EncounterNotActiveError):
        end_encounter(
            postgres_engine,
            encounter_id=start.encounter_id,
            world_time_id=f.world_time_id,
            summary="Second completion attempt.",
        )

    with postgres_engine.connect() as verify:
        row = verify.execute(
            text(
                "SELECT status, resulting_event_id, summary FROM narrative.encounters "
                "WHERE encounter_id = :e"
            ),
            {"e": start.encounter_id},
        ).one()
        assert row.status == "completed"
        assert row.resulting_event_id == first.event_id
        assert row.summary == "First completion."

        cause_count = verify.execute(
            text("SELECT count(*) FROM narrative.event_causes WHERE cause_encounter_id = :e"),
            {"e": start.encounter_id},
        ).scalar()
        assert cause_count == 1, "a second completion event was recorded"


def test_two_concurrent_completion_attempts_leave_exactly_one_canonical_event(
    postgres_engine: Engine, f: Fixture
) -> None:
    """narrative.encounters' own FOR UPDATE lock (_lock_encounter) serializes
    two genuinely concurrent end_encounter() calls for the same encounter —
    the loser observes the winner's already-'completed' status and is
    rejected with EncounterNotActiveError rather than racing to record a
    second completion event or overwrite resulting_event_id."""
    start = start_encounter(
        postgres_engine,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_id,
        participant_entity_ids=(f.attacker_id, f.defender_id),
    )

    barrier = threading.Barrier(2)
    results: dict[str, EndEncounterResult] = {}
    errors: dict[str, Exception] = {}

    def _end(label: str) -> None:
        barrier.wait(timeout=90)
        try:
            results[label] = end_encounter(
                postgres_engine,
                encounter_id=start.encounter_id,
                world_time_id=f.world_time_id,
                summary=f"completion {label}",
            )
        except Exception as exc:  # noqa: BLE001 - captured for the assertion below
            errors[label] = exc

    thread_a = threading.Thread(target=_end, args=("a",))
    thread_b = threading.Thread(target=_end, args=("b",))
    thread_a.start()
    thread_b.start()
    thread_a.join(timeout=90)
    thread_b.join(timeout=90)

    assert not thread_a.is_alive(), "thread a did not finish"
    assert not thread_b.is_alive(), "thread b did not finish"
    assert len(results) == 1, "exactly one completion must succeed"
    assert len(errors) == 1, "exactly one completion must be rejected"
    (loser_error,) = errors.values()
    assert isinstance(loser_error, EncounterNotActiveError)

    (winner_result,) = results.values()
    with postgres_engine.connect() as verify:
        row = verify.execute(
            text(
                "SELECT status, resulting_event_id FROM narrative.encounters "
                "WHERE encounter_id = :e"
            ),
            {"e": start.encounter_id},
        ).one()
        assert row.status == "completed"
        assert row.resulting_event_id == winner_result.event_id

        cause_count = verify.execute(
            text("SELECT count(*) FROM narrative.event_causes WHERE cause_encounter_id = :e"),
            {"e": start.encounter_id},
        ).scalar()
        assert cause_count == 1, "exactly one completion event must remain canonical"


# ---------------------------------------------------------------------------
# End-encounter outcome validation
# ---------------------------------------------------------------------------


def test_ending_an_encounter_with_an_unknown_outcome_participant_is_rejected(
    postgres_engine: Engine, f: Fixture
) -> None:
    start = start_encounter(
        postgres_engine,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_id,
        participant_entity_ids=(f.attacker_id, f.defender_id),
    )
    with postgres_engine.begin() as connection:
        stranger_id = make_character(connection, f.world_id, name="Stranger")

    with pytest.raises(ValueError, match="not participants"):
        end_encounter(
            postgres_engine,
            encounter_id=start.encounter_id,
            world_time_id=f.world_time_id,
            outcomes=((stranger_id, "defeated"),),
        )

    with postgres_engine.connect() as verify:
        row = verify.execute(
            text(
                "SELECT status, resulting_event_id FROM narrative.encounters "
                "WHERE encounter_id = :e"
            ),
            {"e": start.encounter_id},
        ).one()
        assert row.status == "active", "a rejected completion must not change encounter status"
        assert row.resulting_event_id is None

        event_count = verify.execute(
            text("SELECT count(*) FROM narrative.events WHERE timeline_id = :t"),
            {"t": f.timeline_id},
        ).scalar()
        assert event_count == 0, "a rejected completion must not record an event"

        outcome = verify.execute(
            text(
                "SELECT outcome FROM narrative.encounter_participants "
                "WHERE encounter_id = :e AND participant_entity_id = :p"
            ),
            {"e": start.encounter_id, "p": f.defender_id},
        ).scalar()
        assert outcome is None, "a rejected completion must not partially apply outcomes"


def test_ending_an_encounter_with_duplicate_outcome_participants_is_rejected(
    postgres_engine: Engine, f: Fixture
) -> None:
    start = start_encounter(
        postgres_engine,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_id,
        participant_entity_ids=(f.attacker_id, f.defender_id),
    )

    with pytest.raises(ValueError, match="duplicate"):
        end_encounter(
            postgres_engine,
            encounter_id=start.encounter_id,
            world_time_id=f.world_time_id,
            outcomes=((f.defender_id, "defeated"), (f.defender_id, "escaped")),
        )

    with postgres_engine.connect() as verify:
        row = verify.execute(
            text(
                "SELECT status, resulting_event_id FROM narrative.encounters "
                "WHERE encounter_id = :e"
            ),
            {"e": start.encounter_id},
        ).one()
        assert row.status == "active"
        assert row.resulting_event_id is None

        event_count = verify.execute(
            text("SELECT count(*) FROM narrative.events WHERE timeline_id = :t"),
            {"t": f.timeline_id},
        ).scalar()
        assert event_count == 0

        outcome = verify.execute(
            text(
                "SELECT outcome FROM narrative.encounter_participants "
                "WHERE encounter_id = :e AND participant_entity_id = :p"
            ),
            {"e": start.encounter_id, "p": f.defender_id},
        ).scalar()
        assert outcome is None


# ---------------------------------------------------------------------------
# Cross-campaign session integrity
# ---------------------------------------------------------------------------


def _no_encounter_or_participant_rows(postgres_engine: Engine, timeline_id: uuid.UUID) -> None:
    with postgres_engine.connect() as verify:
        encounter_count = verify.execute(
            text("SELECT count(*) FROM narrative.encounters WHERE timeline_id = :t"),
            {"t": timeline_id},
        ).scalar()
        assert encounter_count == 0, "a rejected start_encounter left an encounter row behind"

        participant_count = verify.execute(
            text("""
                SELECT count(*) FROM narrative.encounter_participants ep
                JOIN narrative.encounters e ON e.encounter_id = ep.encounter_id
                WHERE e.timeline_id = :t
            """),
            {"t": timeline_id},
        ).scalar()
        assert participant_count == 0, "a rejected start_encounter left a participant row behind"


def test_starting_an_encounter_with_a_matching_campaign_and_session_succeeds(
    postgres_engine: Engine, f: Fixture
) -> None:
    result = start_encounter(
        postgres_engine,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_id,
        participant_entity_ids=(f.attacker_id,),
        campaign_id=f.campaign_id,
        session_id=f.session_id,
    )

    with postgres_engine.connect() as verify:
        row = verify.execute(
            text(
                "SELECT campaign_id, session_id FROM narrative.encounters WHERE encounter_id = :e"
            ),
            {"e": result.encounter_id},
        ).one()
        assert row.campaign_id == f.campaign_id
        assert row.session_id == f.session_id


def test_starting_an_encounter_with_a_foreign_campaign_session_is_rejected(
    postgres_engine: Engine, f: Fixture
) -> None:
    """The reported gap: a same-world but different campaign's session
    must be rejected even though enforce_encounter_world's own same-world
    check alone would never catch it."""
    with postgres_engine.begin() as connection:
        other_campaign_id = make_campaign(
            connection, f.timeline_id, lifecycle_status_code="pending"
        )
        foreign_session_id = make_session(connection, other_campaign_id, 1)

    with pytest.raises(SessionNotInCampaignError):
        start_encounter(
            postgres_engine,
            timeline_id=f.timeline_id,
            world_time_id=f.world_time_id,
            participant_entity_ids=(f.attacker_id,),
            campaign_id=f.campaign_id,
            session_id=foreign_session_id,
        )

    _no_encounter_or_participant_rows(postgres_engine, f.timeline_id)


def test_starting_an_encounter_with_a_nonexistent_session_is_rejected(
    postgres_engine: Engine, f: Fixture
) -> None:
    with pytest.raises(SessionNotInCampaignError):
        start_encounter(
            postgres_engine,
            timeline_id=f.timeline_id,
            world_time_id=f.world_time_id,
            participant_entity_ids=(f.attacker_id,),
            campaign_id=f.campaign_id,
            session_id=uuid.uuid4(),
        )

    _no_encounter_or_participant_rows(postgres_engine, f.timeline_id)


def test_starting_an_encounter_with_a_session_but_no_campaign_id_is_rejected(
    postgres_engine: Engine, f: Fixture
) -> None:
    """Decided rule (matches narrative.events'/interaction.interactions'
    own campaign_id/session_id chain check): a session always belongs to
    exactly one real campaign, so a caller supplying session_id without
    campaign_id is rejected rather than silently treated as unscoped."""
    with pytest.raises(SessionNotInCampaignError):
        start_encounter(
            postgres_engine,
            timeline_id=f.timeline_id,
            world_time_id=f.world_time_id,
            participant_entity_ids=(f.attacker_id,),
            campaign_id=None,
            session_id=f.session_id,
        )

    _no_encounter_or_participant_rows(postgres_engine, f.timeline_id)


def test_resolving_a_turn_with_a_foreign_campaign_session_is_rejected(
    postgres_engine: Engine, f: Fixture
) -> None:
    """_validate_session_campaign() also guards resolve_combat_turn's own
    session_id, which lands on the interaction.interactions row that turn
    creates, not on the encounter itself."""
    start = start_encounter(
        postgres_engine,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_id,
        participant_entity_ids=(f.attacker_id, f.defender_id),
        campaign_id=f.campaign_id,
        session_id=f.session_id,
    )
    with postgres_engine.begin() as connection:
        other_campaign_id = make_campaign(
            connection, f.timeline_id, lifecycle_status_code="pending"
        )
        foreign_session_id = make_session(connection, other_campaign_id, 1)

    with pytest.raises(SessionNotInCampaignError):
        resolve_combat_turn(
            postgres_engine,
            encounter_id=start.encounter_id,
            round_number=1,
            turn_order=0,
            actor_entity_id=f.attacker_id,
            world_time_id=f.world_time_id,
            campaign_id=f.campaign_id,
            session_id=foreign_session_id,
        )

    with postgres_engine.connect() as verify:
        round_count = verify.execute(
            text("SELECT count(*) FROM narrative.encounter_rounds WHERE encounter_id = :e"),
            {"e": start.encounter_id},
        ).scalar()
        assert round_count == 0, "a rejected turn left a round row behind"


def test_ending_an_encounter_with_a_foreign_campaign_session_is_rejected(
    postgres_engine: Engine, f: Fixture
) -> None:
    """_validate_session_campaign() also guards end_encounter's own
    session_id, which lands on the completion narrative.events row, not
    on the encounter itself."""
    start = start_encounter(
        postgres_engine,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_id,
        participant_entity_ids=(f.attacker_id, f.defender_id),
        campaign_id=f.campaign_id,
        session_id=f.session_id,
    )
    with postgres_engine.begin() as connection:
        other_campaign_id = make_campaign(
            connection, f.timeline_id, lifecycle_status_code="pending"
        )
        foreign_session_id = make_session(connection, other_campaign_id, 1)

    with pytest.raises(SessionNotInCampaignError):
        end_encounter(
            postgres_engine,
            encounter_id=start.encounter_id,
            world_time_id=f.world_time_id,
            campaign_id=f.campaign_id,
            session_id=foreign_session_id,
        )

    with postgres_engine.connect() as verify:
        row = verify.execute(
            text(
                "SELECT status, resulting_event_id FROM narrative.encounters "
                "WHERE encounter_id = :e"
            ),
            {"e": start.encounter_id},
        ).one()
        assert row.status == "active"
        assert row.resulting_event_id is None
