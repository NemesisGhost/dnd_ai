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

import contextlib
import threading
import time
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, Engine, text

from dnd_ai.commands.encounters import (
    EncounterNotActiveError,
    EncounterNotFoundError,
    EndEncounterResult,
    ResolveCombatTurnResult,
    SessionNotInCampaignError,
    _resolve_combat_turn_impl,
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


# ---------------------------------------------------------------------------
# Cross-campaign encounter ownership
# ---------------------------------------------------------------------------


def _no_turn_side_effects(postgres_engine: Engine, f: Fixture, encounter_id: uuid.UUID) -> None:
    with postgres_engine.connect() as verify:
        round_count = verify.execute(
            text("SELECT count(*) FROM narrative.encounter_rounds WHERE encounter_id = :e"),
            {"e": encounter_id},
        ).scalar()
        assert round_count == 0, "a rejected turn left a round row behind"

        turn_count = verify.execute(
            text("""
                SELECT count(*) FROM narrative.encounter_turns et
                JOIN narrative.encounter_rounds er ON er.encounter_round_id = et.encounter_round_id
                WHERE er.encounter_id = :e
            """),
            {"e": encounter_id},
        ).scalar()
        assert turn_count == 0, "a rejected turn left a turn row behind"

        interaction_count = verify.execute(
            text("SELECT count(*) FROM interaction.interactions WHERE timeline_id = :t"),
            {"t": f.timeline_id},
        ).scalar()
        assert interaction_count == 0, "a rejected turn left an interaction row behind"

        event_count = verify.execute(
            text("SELECT count(*) FROM narrative.events WHERE timeline_id = :t"),
            {"t": f.timeline_id},
        ).scalar()
        assert event_count == 0, "a rejected turn left an event row behind"

        hp = verify.execute(
            text(
                "SELECT current_hit_points FROM campaign.character_state "
                "WHERE timeline_id = :t AND character_id = :c"
            ),
            {"t": f.timeline_id, "c": f.defender_id},
        ).scalar()
        assert hp == 20, "a rejected turn changed character HP"


def _no_end_side_effects(postgres_engine: Engine, encounter_id: uuid.UUID) -> None:
    with postgres_engine.connect() as verify:
        row = verify.execute(
            text(
                "SELECT status, resulting_event_id FROM narrative.encounters "
                "WHERE encounter_id = :e"
            ),
            {"e": encounter_id},
        ).one()
        assert row.status == "active", "a rejected end request must not change encounter status"
        assert row.resulting_event_id is None

        cause_count = verify.execute(
            text("SELECT count(*) FROM narrative.event_causes WHERE cause_encounter_id = :e"),
            {"e": encounter_id},
        ).scalar()
        assert cause_count == 0, "a rejected end request must not record a completion event"

        outcome_count = verify.execute(
            text(
                "SELECT count(*) FROM narrative.encounter_participants "
                "WHERE encounter_id = :e AND outcome IS NOT NULL"
            ),
            {"e": encounter_id},
        ).scalar()
        assert outcome_count == 0, "a rejected end request must not apply any outcome"


def test_resolving_a_turn_with_a_mismatched_campaign_is_rejected(
    postgres_engine: Engine, f: Fixture
) -> None:
    """resolve_combat_turn(campaign_id=...) requires the encounter to
    belong to exactly that campaign — a caller-supplied campaign_id that
    does not match the encounter's own is rejected with the identical
    fixed 404 a nonexistent encounter_id gets (EncounterNotFoundError),
    not treated as "no campaign scope requested"."""
    start = start_encounter(
        postgres_engine,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_id,
        participant_entity_ids=(f.attacker_id, f.defender_id),
        campaign_id=f.campaign_id,
    )
    with postgres_engine.begin() as connection:
        other_campaign_id = make_campaign(
            connection, f.timeline_id, lifecycle_status_code="pending"
        )

    with pytest.raises(EncounterNotFoundError):
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
            campaign_id=other_campaign_id,
        )

    _no_turn_side_effects(postgres_engine, f, start.encounter_id)


def test_ending_an_encounter_with_a_mismatched_campaign_is_rejected(
    postgres_engine: Engine, f: Fixture
) -> None:
    """end_encounter(campaign_id=...) requires the same exact-match rule."""
    start = start_encounter(
        postgres_engine,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_id,
        participant_entity_ids=(f.attacker_id, f.defender_id),
        campaign_id=f.campaign_id,
    )
    with postgres_engine.begin() as connection:
        other_campaign_id = make_campaign(
            connection, f.timeline_id, lifecycle_status_code="pending"
        )

    with pytest.raises(EncounterNotFoundError):
        end_encounter(
            postgres_engine,
            encounter_id=start.encounter_id,
            world_time_id=f.world_time_id,
            campaign_id=other_campaign_id,
        )

    _no_end_side_effects(postgres_engine, start.encounter_id)


def test_reparenting_an_encounters_campaign_mid_flight_is_observed_by_the_locked_command(
    postgres_engine: Engine, f: Fixture
) -> None:
    """Controlled two-connection race, standing in for the TOCTOU this
    revision closes: a caller observes (or is authorized against) an
    encounter's campaign at one point in time, then a *different*
    transaction reparents the encounter to another campaign on the same
    timeline before the caller's own mutation runs. _lock_encounter's
    ownership check must observe the encounter's true, current owner —
    never a value cached from before the reparent — because it reads
    campaign_id from the same FOR UPDATE-locked row a reparenting UPDATE
    must also wait behind.

    Sequence: a raw connection acquires the encounter's row lock via an
    uncommitted `UPDATE ... SET campaign_id = other` (not yet committed).
    A second thread calls _resolve_combat_turn_impl expecting the
    *original* campaign_id — this must block on the same row lock. Once
    genuinely blocked (confirmed server-side, not assumed from timing),
    the main thread commits the reparent. The previously blocked call then
    proceeds, observes the *new* campaign_id, and must reject — proving
    the check always sees the encounter's true owner at the moment it
    actually locks the row, not whatever was true earlier.

    end_encounter is not separately race-tested: _end_encounter_impl calls
    the identical _lock_encounter, so this proves the shared mechanism for
    both callers."""
    start = start_encounter(
        postgres_engine,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_id,
        participant_entity_ids=(f.attacker_id, f.defender_id),
        campaign_id=f.campaign_id,
    )
    with postgres_engine.begin() as connection:
        other_campaign_id = make_campaign(
            connection, f.timeline_id, lifecycle_status_code="pending"
        )

    reparent_connection = postgres_engine.connect()
    reparent_transaction = reparent_connection.begin()

    turn_started = threading.Event()
    turn_done = threading.Event()
    pids: dict[str, int] = {}
    results: dict[str, ResolveCombatTurnResult] = {}
    errors: dict[str, Exception] = {}

    def _turn() -> None:
        try:
            with postgres_engine.connect() as connection:
                # SELECT pg_backend_pid() auto-begins this connection's
                # transaction (SQLAlchemy 2.x) — _resolve_combat_turn_impl
                # below runs in that same, already-open transaction rather
                # than a second one started via connection.begin() (which
                # would raise InvalidRequestError: a connection can't
                # begin() a transaction while one it already auto-began is
                # still open). commit() is called explicitly, only on
                # success — if _resolve_combat_turn_impl raises, this
                # function's own `with` block closes the connection
                # without committing, rolling the autobegun transaction
                # back, exactly as the rejection-with-no-side-effects
                # cases elsewhere in this module require.
                pids["turn"] = connection.execute(text("SELECT pg_backend_pid()")).scalar_one()
                turn_started.set()
                results["turn"] = _resolve_combat_turn_impl(
                    connection,
                    encounter_id=start.encounter_id,
                    round_number=1,
                    turn_order=0,
                    actor_entity_id=f.attacker_id,
                    world_time_id=f.world_time_id,
                    target_entity_id=f.defender_id,
                    hit=True,
                    damage_amount=7,
                    # The campaign the caller observed/was authorized
                    # against *before* this call — the reparent below
                    # happens after this value was decided.
                    campaign_id=f.campaign_id,
                )
                connection.commit()
        except Exception as exc:  # noqa: BLE001 - captured for the assertion below
            errors["turn"] = exc
        finally:
            turn_done.set()

    try:
        # Acquire the encounter's row lock via an uncommitted reparenting
        # UPDATE — _resolve_combat_turn_impl's own FOR UPDATE SELECT must
        # wait behind this exact row lock, the same as it would behind any
        # other uncommitted writer.
        reparent_connection.execute(
            text("UPDATE narrative.encounters SET campaign_id = :c WHERE encounter_id = :e"),
            {"c": other_campaign_id, "e": start.encounter_id},
        )

        thread = threading.Thread(target=_turn)
        thread.start()
        assert turn_started.wait(timeout=180), "turn thread never started"
        turn_pid = pids["turn"]

        # Poll pg_stat_activity for confirmation the turn's own locking
        # SELECT is genuinely blocked, rather than assuming a fixed sleep
        # was long enough — matched by exact backend pid (deterministic,
        # unlike matching on query text).
        deadline = time.monotonic() + 60
        blocked = False
        while time.monotonic() < deadline:
            waiting = reparent_connection.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE pid = :pid AND wait_event_type = 'Lock'"
                ),
                {"pid": turn_pid},
            ).scalar()
            if waiting:
                blocked = True
                break
            time.sleep(0.1)

        assert blocked, "the concurrent turn was never observed blocked behind the reparent"
        assert not turn_done.is_set(), (
            "the turn completed despite the reparent lock still being held"
        )
    finally:
        with contextlib.suppress(Exception):
            reparent_transaction.commit()
        with contextlib.suppress(Exception):
            reparent_connection.close()

    assert turn_done.wait(timeout=60), "the turn never completed after the reparent committed"
    thread.join(timeout=60)
    assert not thread.is_alive()

    assert "turn" not in results, "the turn must not succeed once its expected campaign is stale"
    assert "turn" in errors, "the turn must reject the now-reparented encounter"
    assert isinstance(errors["turn"], EncounterNotFoundError)

    with postgres_engine.connect() as verify:
        row = verify.execute(
            text("SELECT campaign_id FROM narrative.encounters WHERE encounter_id = :e"),
            {"e": start.encounter_id},
        ).one()
        assert row.campaign_id == other_campaign_id, "the reparent itself must have committed"

    _no_turn_side_effects(postgres_engine, f, start.encounter_id)
