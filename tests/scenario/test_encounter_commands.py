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
from sqlalchemy.exc import IntegrityError, InternalError, ProgrammingError

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

CONSTRAINT_ERRORS = (IntegrityError, InternalError, ProgrammingError)


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
        # campaign.campaigns/.sessions are neither entity-rooted nor reached
        # by DELETE FROM core.worlds below — that DELETE would normally
        # cascade to them via campaign.timelines (ON DELETE CASCADE), but
        # session_replication_role = replica also disables that cascade, the
        # same way it disables the FK enforcement this cleanup relies on to
        # delete out of dependency order. Left unlisted, every campaign (the
        # fixture's own, plus every ad-hoc "other campaign" individual tests
        # create for mismatch/reparenting cases — all scoped to this same
        # timeline_id) would survive this cleanup indefinitely. That is
        # normally harmless leaked test data, but revision 080's
        # tr_campaigns_retain_access_manager (a DEFERRABLE INITIALLY DEFERRED
        # constraint trigger on campaign.campaigns) makes it actively break
        # an unrelated test: any later UPDATE of campaign.campaigns in the
        # same pytest session — e.g. tests/database/test_seed_idempotency.py
        # replaying revision 024's downgrade() — queues that deferred
        # trigger against whatever campaign rows still exist, then fails
        # with "cannot ALTER TABLE because it has pending trigger events"
        # the moment that same transaction tries to ALTER TABLE campaign.
        # campaigns. Deleted explicitly here, scoped by timeline_id (not
        # just the fixture's own campaign_id) to catch every campaign this
        # test created, sessions first since they reference campaign_id.
        cleanup.execute(
            text(
                "DELETE FROM campaign.sessions WHERE campaign_id IN "
                "(SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t)"
            ),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text("DELETE FROM campaign.campaigns WHERE timeline_id = :t"),
            {"t": fixture.timeline_id},
        )
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


def test_a_concurrent_reparent_attempt_during_an_in_flight_turn_cannot_leave_mixed_provenance(
    postgres_engine: Engine, f: Fixture
) -> None:
    """narrative.encounters.campaign_id is now immutable (revision 081's
    corrected reparenting analysis — see that migration's own docstring):
    reparenting is rejected outright, with or without a race. This proves
    the stronger guarantee holds under genuine concurrency too, not just
    at rest.

    An earlier version of this test (from before campaign_id became
    immutable) proved the *previous* mechanism instead: that
    _lock_encounter's ownership assertion always observed the encounter's
    true, current owner rather than a value cached from before a
    successful reparent. That mechanism is now moot — a reparenting
    UPDATE can no longer succeed at all, so there is nothing for a caller
    to "observe" after the fact. What still needs proving is that the
    *reparent itself* is the one that loses this race, cleanly, and that
    the turn already in flight completes normally under the campaign it
    started with — never a state where the turn's own interaction/event
    rows and the encounter's own campaign_id could end up disagreeing.

    Sequence: a real resolve_combat_turn() call acquires the encounter's
    row lock via _lock_encounter's own FOR UPDATE SELECT, inside an
    uncommitted transaction. A second thread attempts a raw reparenting
    UPDATE — this must block on the same row lock, exactly as it would
    behind any other uncommitted writer. Once genuinely blocked (confirmed
    server-side, not assumed from timing), the main thread commits the
    turn. The previously blocked reparent then proceeds — and must fail
    immediately with the immutability violation, never succeed.

    end_encounter is not separately race-tested: _end_encounter_impl calls
    the identical _lock_encounter, and the immutability trigger this test
    proves is unconditional — it does not depend on which command holds
    the row lock first."""
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

    turn_connection = postgres_engine.connect()
    turn_transaction = turn_connection.begin()

    reparent_started = threading.Event()
    reparent_done = threading.Event()
    pids: dict[str, int] = {}
    errors: dict[str, Exception] = {}

    def _reparent() -> None:
        try:
            with postgres_engine.connect() as connection:
                pids["reparent"] = connection.execute(text("SELECT pg_backend_pid()")).scalar_one()
                reparent_started.set()
                connection.execute(
                    text(
                        "UPDATE narrative.encounters SET campaign_id = :c WHERE encounter_id = :e"
                    ),
                    {"c": other_campaign_id, "e": start.encounter_id},
                )
                connection.commit()
        except Exception as exc:  # noqa: BLE001 - captured for the assertion below
            errors["reparent"] = exc
        finally:
            reparent_done.set()

    turn_result: ResolveCombatTurnResult | None = None
    try:
        # Hold the encounter's row lock via a real, uncommitted turn — the
        # concurrent reparent's own UPDATE must wait behind this exact
        # row lock.
        turn_result = _resolve_combat_turn_impl(
            turn_connection,
            encounter_id=start.encounter_id,
            round_number=1,
            turn_order=0,
            actor_entity_id=f.attacker_id,
            world_time_id=f.world_time_id,
            target_entity_id=f.defender_id,
            hit=True,
            damage_amount=7,
            campaign_id=f.campaign_id,
        )

        thread = threading.Thread(target=_reparent)
        thread.start()
        assert reparent_started.wait(timeout=180), "reparent thread never started"
        reparent_pid = pids["reparent"]

        # Poll pg_stat_activity for confirmation the reparent's own UPDATE
        # is genuinely blocked, rather than assuming a fixed sleep was long
        # enough — matched by exact backend pid (deterministic, unlike
        # matching on query text).
        deadline = time.monotonic() + 60
        blocked = False
        while time.monotonic() < deadline:
            waiting = turn_connection.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE pid = :pid AND wait_event_type = 'Lock'"
                ),
                {"pid": reparent_pid},
            ).scalar()
            if waiting:
                blocked = True
                break
            time.sleep(0.1)

        assert blocked, "the concurrent reparent was never observed blocked behind the turn"
        assert not reparent_done.is_set(), (
            "the reparent completed despite the turn's row lock still being held"
        )
    finally:
        with contextlib.suppress(Exception):
            turn_transaction.commit()
        with contextlib.suppress(Exception):
            turn_connection.close()

    assert reparent_done.wait(timeout=60), "the reparent never completed after the turn committed"
    thread.join(timeout=60)
    assert not thread.is_alive()

    assert turn_result is not None
    assert turn_result.event_id is not None, "the in-flight turn itself must have succeeded"
    assert "reparent" in errors, "the reparent must be rejected once unblocked"
    assert isinstance(errors["reparent"], CONSTRAINT_ERRORS)
    assert "immutable" in str(errors["reparent"])

    with postgres_engine.connect() as verify:
        encounter_row = verify.execute(
            text("SELECT campaign_id FROM narrative.encounters WHERE encounter_id = :e"),
            {"e": start.encounter_id},
        ).one()
        assert encounter_row.campaign_id == f.campaign_id, (
            "the rejected reparent must not have changed the encounter's campaign"
        )

        interaction_row = verify.execute(
            text("""
                SELECT i.campaign_id
                FROM interaction.interactions i
                JOIN interaction.actions a ON a.interaction_id = i.interaction_id
                JOIN interaction.combat_actions ca ON ca.action_id = a.action_id
                JOIN narrative.encounter_turns et ON et.combat_action_id = ca.combat_action_id
                WHERE et.encounter_turn_id = :turn
            """),
            {"turn": turn_result.encounter_turn_id},
        ).one()
        assert interaction_row.campaign_id == f.campaign_id, (
            "the in-flight turn's own provenance must stay attributed to the original campaign"
        )

        event_row = verify.execute(
            text("SELECT campaign_id FROM narrative.events WHERE event_id = :e"),
            {"e": turn_result.event_id},
        ).one()
        assert event_row.campaign_id == f.campaign_id, (
            "the in-flight turn's damage event must stay attributed to the original campaign"
        )


def test_a_concurrent_timeline_reparent_attempt_during_an_in_flight_turn_cannot_leave_mixed_provenance(
    postgres_engine: Engine, f: Fixture
) -> None:
    """The campaign-less counterpart to the campaign_id race above:
    narrative.encounters.timeline_id is now also immutable (revision
    081's "corrected again" reparenting analysis). A campaign-*owned*
    encounter's timeline was already pinned indirectly (campaign_id is
    immutable, and enforce_encounter_world() requires campaign_id to
    belong to timeline_id) — the previously-unprotected path was a
    campaign-*less* encounter, which has no campaign relationship to pin
    its timeline down. This encounter is created with campaign_id=None
    specifically to exercise that path.

    Sequence mirrors the campaign_id race exactly: a real
    resolve_combat_turn() call acquires the encounter's row lock inside
    an uncommitted transaction; a concurrent raw timeline-reparenting
    UPDATE must block on that same row lock; once genuinely blocked
    (confirmed server-side), the turn commits, and the previously blocked
    reparent then proceeds and must fail immediately with the
    immutability violation."""
    start = start_encounter(
        postgres_engine,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_id,
        participant_entity_ids=(f.attacker_id, f.defender_id),
    )
    with postgres_engine.begin() as connection:
        other_timeline_id = make_timeline(connection, f.world_id, name="Other Branch")

    turn_connection = postgres_engine.connect()
    turn_transaction = turn_connection.begin()

    reparent_started = threading.Event()
    reparent_done = threading.Event()
    pids: dict[str, int] = {}
    errors: dict[str, Exception] = {}

    def _reparent() -> None:
        try:
            with postgres_engine.connect() as connection:
                pids["reparent"] = connection.execute(text("SELECT pg_backend_pid()")).scalar_one()
                reparent_started.set()
                connection.execute(
                    text(
                        "UPDATE narrative.encounters SET timeline_id = :t WHERE encounter_id = :e"
                    ),
                    {"t": other_timeline_id, "e": start.encounter_id},
                )
                connection.commit()
        except Exception as exc:  # noqa: BLE001 - captured for the assertion below
            errors["reparent"] = exc
        finally:
            reparent_done.set()

    turn_result: ResolveCombatTurnResult | None = None
    try:
        turn_result = _resolve_combat_turn_impl(
            turn_connection,
            encounter_id=start.encounter_id,
            round_number=1,
            turn_order=0,
            actor_entity_id=f.attacker_id,
            world_time_id=f.world_time_id,
            target_entity_id=f.defender_id,
            hit=True,
            damage_amount=7,
        )

        thread = threading.Thread(target=_reparent)
        thread.start()
        assert reparent_started.wait(timeout=180), "reparent thread never started"
        reparent_pid = pids["reparent"]

        deadline = time.monotonic() + 60
        blocked = False
        while time.monotonic() < deadline:
            waiting = turn_connection.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE pid = :pid AND wait_event_type = 'Lock'"
                ),
                {"pid": reparent_pid},
            ).scalar()
            if waiting:
                blocked = True
                break
            time.sleep(0.1)

        assert blocked, "the concurrent reparent was never observed blocked behind the turn"
        assert not reparent_done.is_set(), (
            "the reparent completed despite the turn's row lock still being held"
        )
    finally:
        with contextlib.suppress(Exception):
            turn_transaction.commit()
        with contextlib.suppress(Exception):
            turn_connection.close()

    assert reparent_done.wait(timeout=60), "the reparent never completed after the turn committed"
    thread.join(timeout=60)
    assert not thread.is_alive()

    assert turn_result is not None
    assert turn_result.event_id is not None, "the in-flight turn itself must have succeeded"
    assert "reparent" in errors, "the reparent must be rejected once unblocked"
    assert isinstance(errors["reparent"], CONSTRAINT_ERRORS)
    assert "immutable" in str(errors["reparent"])

    with postgres_engine.connect() as verify:
        encounter_row = verify.execute(
            text("SELECT timeline_id FROM narrative.encounters WHERE encounter_id = :e"),
            {"e": start.encounter_id},
        ).one()
        assert encounter_row.timeline_id == f.timeline_id, (
            "the rejected reparent must not have changed the encounter's timeline"
        )

        interaction_row = verify.execute(
            text("""
                SELECT i.timeline_id
                FROM interaction.interactions i
                JOIN interaction.actions a ON a.interaction_id = i.interaction_id
                JOIN interaction.combat_actions ca ON ca.action_id = a.action_id
                JOIN narrative.encounter_turns et ON et.combat_action_id = ca.combat_action_id
                WHERE et.encounter_turn_id = :turn
            """),
            {"turn": turn_result.encounter_turn_id},
        ).one()
        assert interaction_row.timeline_id == f.timeline_id, (
            "the in-flight turn's own provenance must stay attributed to the original timeline"
        )

        event_row = verify.execute(
            text("SELECT timeline_id FROM narrative.events WHERE event_id = :e"),
            {"e": turn_result.event_id},
        ).one()
        assert event_row.timeline_id == f.timeline_id, (
            "the in-flight turn's damage event must stay attributed to the original timeline"
        )


# ---------------------------------------------------------------------------
# Campaign provenance (as distinct from the ownership assertion above)
# ---------------------------------------------------------------------------


def test_resolving_a_turn_with_a_matching_campaign_attributes_records_to_it(
    postgres_engine: Engine, f: Fixture
) -> None:
    """The scoped-and-matching path (already exercised indirectly by the
    mismatch/reparenting tests above) gets its own direct positive
    assertion: a caller that supplies the encounter's real campaign_id as
    its ownership assertion gets records attributed to that same campaign
    — the unchanged, still-correct behavior this revision must not
    regress."""
    start = start_encounter(
        postgres_engine,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_id,
        participant_entity_ids=(f.attacker_id, f.defender_id),
        campaign_id=f.campaign_id,
    )

    result = resolve_combat_turn(
        postgres_engine,
        encounter_id=start.encounter_id,
        round_number=1,
        turn_order=0,
        actor_entity_id=f.attacker_id,
        world_time_id=f.world_time_id,
        target_entity_id=f.defender_id,
        hit=True,
        damage_amount=7,
        campaign_id=f.campaign_id,
    )

    with postgres_engine.connect() as verify:
        interaction_row = verify.execute(
            text("""
                SELECT i.campaign_id
                FROM interaction.interactions i
                JOIN interaction.actions a ON a.interaction_id = i.interaction_id
                JOIN interaction.combat_actions ca ON ca.action_id = a.action_id
                JOIN narrative.encounter_turns et ON et.combat_action_id = ca.combat_action_id
                WHERE et.encounter_turn_id = :turn
            """),
            {"turn": result.encounter_turn_id},
        ).one()
        assert interaction_row.campaign_id == f.campaign_id


def test_resolving_a_turn_with_an_omitted_campaign_still_attributes_records_to_the_encounters_actual_campaign(
    postgres_engine: Engine, f: Fixture
) -> None:
    """campaign_id=None on resolve_combat_turn() skips only the ownership
    *assertion* (_lock_encounter's expected_campaign_id) — it must not
    also discard the encounter's real campaign provenance onto the
    interaction.interactions/narrative.events rows this call creates. A
    campaign-owned encounter must still produce campaign-owned records
    even for an unscoped caller, exactly as apply_foundry_combat_sync()
    (which always calls unscoped today) relies on."""
    start = start_encounter(
        postgres_engine,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_id,
        participant_entity_ids=(f.attacker_id, f.defender_id),
        campaign_id=f.campaign_id,
    )

    result = resolve_combat_turn(
        postgres_engine,
        encounter_id=start.encounter_id,
        round_number=1,
        turn_order=0,
        actor_entity_id=f.attacker_id,
        world_time_id=f.world_time_id,
        target_entity_id=f.defender_id,
        hit=True,
        damage_amount=7,
        campaign_id=None,
    )
    assert result.event_id is not None

    with postgres_engine.connect() as verify:
        interaction_row = verify.execute(
            text("""
                SELECT i.campaign_id
                FROM interaction.interactions i
                JOIN interaction.actions a ON a.interaction_id = i.interaction_id
                JOIN interaction.combat_actions ca ON ca.action_id = a.action_id
                JOIN narrative.encounter_turns et ON et.combat_action_id = ca.combat_action_id
                WHERE et.encounter_turn_id = :turn
            """),
            {"turn": result.encounter_turn_id},
        ).one()
        assert interaction_row.campaign_id == f.campaign_id

        event_row = verify.execute(
            text("SELECT campaign_id FROM narrative.events WHERE event_id = :e"),
            {"e": result.event_id},
        ).one()
        assert event_row.campaign_id == f.campaign_id


def test_ending_an_encounter_with_an_omitted_campaign_still_attributes_the_completion_event_to_the_encounters_actual_campaign(
    postgres_engine: Engine, f: Fixture
) -> None:
    """The end_encounter() mirror of the resolve_combat_turn case above:
    an unscoped end_encounter() call must still attribute the completion
    event to the encounter's real campaign, not NULL."""
    start = start_encounter(
        postgres_engine,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_id,
        participant_entity_ids=(f.attacker_id, f.defender_id),
        campaign_id=f.campaign_id,
    )

    result = end_encounter(
        postgres_engine,
        encounter_id=start.encounter_id,
        world_time_id=f.world_time_id,
        campaign_id=None,
    )

    with postgres_engine.connect() as verify:
        event_row = verify.execute(
            text("SELECT campaign_id FROM narrative.events WHERE event_id = :e"),
            {"e": result.event_id},
        ).one()
        assert event_row.campaign_id == f.campaign_id


def test_resolving_a_turn_on_a_campaign_less_encounter_remains_unscoped(
    postgres_engine: Engine, f: Fixture
) -> None:
    """The other half of the same contract: an encounter that genuinely
    has no campaign (campaign_id NULL) must still produce campaign-less
    records — provenance inheritance never invents a campaign that isn't
    there."""
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
        target_entity_id=f.defender_id,
        hit=True,
        damage_amount=7,
    )
    assert result.event_id is not None

    with postgres_engine.connect() as verify:
        interaction_row = verify.execute(
            text("""
                SELECT i.campaign_id
                FROM interaction.interactions i
                JOIN interaction.actions a ON a.interaction_id = i.interaction_id
                JOIN interaction.combat_actions ca ON ca.action_id = a.action_id
                JOIN narrative.encounter_turns et ON et.combat_action_id = ca.combat_action_id
                WHERE et.encounter_turn_id = :turn
            """),
            {"turn": result.encounter_turn_id},
        ).one()
        assert interaction_row.campaign_id is None

        event_row = verify.execute(
            text("SELECT campaign_id FROM narrative.events WHERE event_id = :e"),
            {"e": result.event_id},
        ).one()
        assert event_row.campaign_id is None


def test_ending_a_campaign_less_encounter_remains_unscoped(
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
    )

    with postgres_engine.connect() as verify:
        event_row = verify.execute(
            text("SELECT campaign_id FROM narrative.events WHERE event_id = :e"),
            {"e": result.event_id},
        ).one()
        assert event_row.campaign_id is None


def test_resolving_a_turn_with_an_omitted_campaign_still_accepts_a_session_matching_the_encounters_actual_campaign(
    postgres_engine: Engine, f: Fixture
) -> None:
    """Session validation must be checked against the encounter's actual,
    locked campaign — never against this call's own (possibly unscoped)
    campaign_id argument. Before this fix, an unscoped caller supplying a
    session_id that genuinely belongs to the encounter's real campaign
    would have been wrongly rejected (validated against campaign_id=None,
    which no real session ever matches)."""
    start = start_encounter(
        postgres_engine,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_id,
        participant_entity_ids=(f.attacker_id, f.defender_id),
        campaign_id=f.campaign_id,
    )

    result = resolve_combat_turn(
        postgres_engine,
        encounter_id=start.encounter_id,
        round_number=1,
        turn_order=0,
        actor_entity_id=f.attacker_id,
        world_time_id=f.world_time_id,
        target_entity_id=f.defender_id,
        hit=True,
        damage_amount=7,
        campaign_id=None,
        session_id=f.session_id,
    )

    with postgres_engine.connect() as verify:
        interaction_row = verify.execute(
            text("""
                SELECT i.campaign_id, i.session_id
                FROM interaction.interactions i
                JOIN interaction.actions a ON a.interaction_id = i.interaction_id
                JOIN interaction.combat_actions ca ON ca.action_id = a.action_id
                JOIN narrative.encounter_turns et ON et.combat_action_id = ca.combat_action_id
                WHERE et.encounter_turn_id = :turn
            """),
            {"turn": result.encounter_turn_id},
        ).one()
        assert interaction_row.campaign_id == f.campaign_id
        assert interaction_row.session_id == f.session_id


def test_resolving_a_turn_with_an_omitted_campaign_still_rejects_a_foreign_session(
    postgres_engine: Engine, f: Fixture
) -> None:
    """The other half: an unscoped caller supplying a session_id that
    belongs to a *different* campaign than the encounter's actual owner
    must still be rejected — the assertion being skipped is ownership of
    the encounter, not validity of a supplied session."""
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
        foreign_session_id = make_session(connection, other_campaign_id, 1)

    with pytest.raises(SessionNotInCampaignError):
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
            campaign_id=None,
            session_id=foreign_session_id,
        )

    _no_turn_side_effects(postgres_engine, f, start.encounter_id)


def test_ending_an_encounter_with_an_omitted_campaign_still_rejects_a_foreign_session(
    postgres_engine: Engine, f: Fixture
) -> None:
    """The end_encounter() mirror of the rejection case above."""
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
        foreign_session_id = make_session(connection, other_campaign_id, 1)

    with pytest.raises(SessionNotInCampaignError):
        end_encounter(
            postgres_engine,
            encounter_id=start.encounter_id,
            world_time_id=f.world_time_id,
            campaign_id=None,
            session_id=foreign_session_id,
        )

    _no_end_side_effects(postgres_engine, start.encounter_id)
