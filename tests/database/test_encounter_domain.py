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
# narrative.encounters.timeline_id/.campaign_id identity immutability
# (revision 081 correction, tr_encounters_identity_immutable)
#
# The original revision 081 argued no reverse-mutation guard was needed here
# because narrative.enforce_encounter_world() re-validates the encounter's
# own row on every UPDATE. That reasoning missed that reparenting silently
# orphans interaction.interactions/narrative.events rows already created
# under the encounter's *original* timeline/campaign — those never
# re-validate against the encounter row changing. Both columns are now
# immutable once set — campaign_id including NULL <-> non-NULL transitions
# (stricter than core.enforce_immutable_columns()'s NULL-transition-
# permitting default) — via one shared trigger; see
# tr_encounters_identity_immutable's own migration docstring for why both
# columns share it rather than two separate triggers.
# ---------------------------------------------------------------------------


def test_an_encounters_campaign_id_is_immutable_once_set(
    db_connection: Connection, f: Fixture
) -> None:
    encounter_id = make_encounter(db_connection, f.timeline_id, f.t0, campaign_id=f.campaign_id)
    other_campaign = make_campaign(db_connection, f.timeline_id, lifecycle_status_code="pending")

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("UPDATE narrative.encounters SET campaign_id = :c WHERE encounter_id = :e"),
            {"c": other_campaign, "e": encounter_id},
        )
    assert "immutable" in str(exc.value)


def test_an_encounters_campaign_id_cannot_go_from_null_to_a_value(
    db_connection: Connection, f: Fixture
) -> None:
    """Deliberately stricter than core.enforce_immutable_columns() (revision
    030/033), which allows one NULL -> value transition for columns like
    rules.features.class_id. A campaign-less encounter's NULL is a
    meaningful, permanent identity choice, not a placeholder awaiting a
    value."""
    encounter_id = make_encounter(db_connection, f.timeline_id, f.t0)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("UPDATE narrative.encounters SET campaign_id = :c WHERE encounter_id = :e"),
            {"c": f.campaign_id, "e": encounter_id},
        )
    assert "immutable" in str(exc.value)


def test_an_encounters_campaign_id_cannot_go_from_a_value_to_null(
    db_connection: Connection, f: Fixture
) -> None:
    encounter_id = make_encounter(db_connection, f.timeline_id, f.t0, campaign_id=f.campaign_id)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("UPDATE narrative.encounters SET campaign_id = NULL WHERE encounter_id = :e"),
            {"e": encounter_id},
        )
    assert "immutable" in str(exc.value)


def test_setting_an_encounters_campaign_id_to_its_current_value_is_not_a_change(
    db_connection: Connection, f: Fixture
) -> None:
    """The trigger compares OLD vs NEW, not whether campaign_id appeared in
    the UPDATE's column list — an UPDATE that re-asserts the same value
    (e.g. a blanket ORM-style save) must not be rejected."""
    encounter_id = make_encounter(db_connection, f.timeline_id, f.t0, campaign_id=f.campaign_id)

    db_connection.execute(
        text(
            "UPDATE narrative.encounters SET campaign_id = :c, summary = 'touched' "
            "WHERE encounter_id = :e"
        ),
        {"c": f.campaign_id, "e": encounter_id},
    )
    row = db_connection.execute(
        text("SELECT campaign_id, summary FROM narrative.encounters WHERE encounter_id = :e"),
        {"e": encounter_id},
    ).one()
    assert row.campaign_id == f.campaign_id
    assert row.summary == "touched"


def test_reparenting_after_a_recorded_turn_is_rejected(
    db_connection: Connection, f: Fixture
) -> None:
    encounter_id = make_encounter(db_connection, f.timeline_id, f.t0, campaign_id=f.campaign_id)
    interaction_id = make_interaction(
        db_connection, f.timeline_id, f.t0, campaign_id=f.campaign_id, session_id=f.session_id
    )
    action_id = make_action(db_connection, interaction_id, f.character_a)
    combat_action_id = make_combat_action(db_connection, action_id)
    round_id = make_encounter_round(db_connection, encounter_id, 1)
    participant_id = make_encounter_participant(db_connection, encounter_id, f.character_a)
    make_encounter_turn(
        db_connection, round_id, participant_id, 0, combat_action_id=combat_action_id
    )

    other_campaign = make_campaign(db_connection, f.timeline_id, lifecycle_status_code="pending")
    # SAVEPOINT (begin_nested): the failed UPDATE aborts the outer
    # transaction in PostgreSQL, which would poison the verification query
    # below unless the attempt is scoped to a sub-transaction.
    with pytest.raises(CONSTRAINT_ERRORS) as exc, db_connection.begin_nested():
        db_connection.execute(
            text("UPDATE narrative.encounters SET campaign_id = :c WHERE encounter_id = :e"),
            {"c": other_campaign, "e": encounter_id},
        )
    assert "immutable" in str(exc.value)

    # The turn's interaction row must still show the original campaign —
    # the rejected reparent must not have left anything half-applied.
    stored = db_connection.execute(
        text("SELECT campaign_id FROM interaction.interactions WHERE interaction_id = :i"),
        {"i": interaction_id},
    ).scalar()
    assert stored == f.campaign_id


def test_reparenting_after_a_damage_event_is_rejected(
    db_connection: Connection, f: Fixture
) -> None:
    encounter_id = make_encounter(db_connection, f.timeline_id, f.t0, campaign_id=f.campaign_id)
    event_id = make_event(
        db_connection,
        f.world_id,
        f.timeline_id,
        f.t0,
        campaign_id=f.campaign_id,
        session_id=f.session_id,
        event_type_code="combat_damage_dealt",
    )
    db_connection.execute(
        text(
            "INSERT INTO narrative.event_causes (event_id, cause_encounter_id) "
            "VALUES (:event, :encounter)"
        ),
        {"event": event_id, "encounter": encounter_id},
    )

    other_campaign = make_campaign(db_connection, f.timeline_id, lifecycle_status_code="pending")
    with pytest.raises(CONSTRAINT_ERRORS) as exc, db_connection.begin_nested():
        db_connection.execute(
            text("UPDATE narrative.encounters SET campaign_id = :c WHERE encounter_id = :e"),
            {"c": other_campaign, "e": encounter_id},
        )
    assert "immutable" in str(exc.value)

    stored = db_connection.execute(
        text("SELECT campaign_id FROM narrative.events WHERE event_id = :e"), {"e": event_id}
    ).scalar()
    assert stored == f.campaign_id


def test_reparenting_after_completion_is_rejected(db_connection: Connection, f: Fixture) -> None:
    event_id = make_event(
        db_connection,
        f.world_id,
        f.timeline_id,
        f.t0,
        campaign_id=f.campaign_id,
        session_id=f.session_id,
    )
    encounter_id = make_encounter(
        db_connection,
        f.timeline_id,
        f.t0,
        campaign_id=f.campaign_id,
        status="completed",
        resulting_event_id=event_id,
    )

    other_campaign = make_campaign(db_connection, f.timeline_id, lifecycle_status_code="pending")
    with pytest.raises(CONSTRAINT_ERRORS) as exc, db_connection.begin_nested():
        db_connection.execute(
            text("UPDATE narrative.encounters SET campaign_id = :c WHERE encounter_id = :e"),
            {"c": other_campaign, "e": encounter_id},
        )
    assert "immutable" in str(exc.value)

    row = db_connection.execute(
        text(
            "SELECT e.campaign_id AS encounter_campaign, ev.campaign_id AS event_campaign "
            "FROM narrative.encounters e "
            "JOIN narrative.events ev ON ev.event_id = e.resulting_event_id "
            "WHERE e.encounter_id = :e"
        ),
        {"e": encounter_id},
    ).one()
    assert row.encounter_campaign == f.campaign_id
    assert row.event_campaign == f.campaign_id


def test_a_campaign_less_encounters_timeline_id_is_immutable_once_set(
    db_connection: Connection, f: Fixture
) -> None:
    """The gap this correction closes: a campaign-owned encounter's
    timeline was already pinned *indirectly* (its campaign_id is
    immutable, and enforce_encounter_world() requires campaign_id to
    belong to timeline_id), but a campaign-less encounter has no campaign
    relationship to pin it down at all — enforce_encounter_world()'s
    same-world check alone happily accepts a move to a different timeline
    in the same world."""
    encounter_id = make_encounter(db_connection, f.timeline_id, f.t0)
    other_timeline = _make_timeline(db_connection, f.world_id, name="Other Branch")

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("UPDATE narrative.encounters SET timeline_id = :t WHERE encounter_id = :e"),
            {"t": other_timeline, "e": encounter_id},
        )
    assert "immutable" in str(exc.value)


def test_a_campaign_owned_encounters_timeline_id_change_remains_rejected(
    db_connection: Connection, f: Fixture
) -> None:
    """campaign_id's own immutability already made this unreachable
    indirectly before this correction — this proves the *new* trigger is
    what fires now (timeline_id is checked first), not merely the
    pre-existing campaign/timeline consistency check, by moving
    timeline_id and campaign_id together to a self-consistent pair on the
    other timeline."""
    encounter_id = make_encounter(db_connection, f.timeline_id, f.t0, campaign_id=f.campaign_id)
    other_timeline = _make_timeline(db_connection, f.world_id, name="Other Branch")
    other_campaign = make_campaign(db_connection, other_timeline, lifecycle_status_code="pending")

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "UPDATE narrative.encounters SET timeline_id = :t, campaign_id = :c "
                "WHERE encounter_id = :e"
            ),
            {"t": other_timeline, "c": other_campaign, "e": encounter_id},
        )
    assert "immutable" in str(exc.value)
    assert "timeline_id" in str(exc.value)


def test_setting_an_encounters_timeline_id_to_its_current_value_is_not_a_change(
    db_connection: Connection, f: Fixture
) -> None:
    encounter_id = make_encounter(db_connection, f.timeline_id, f.t0, campaign_id=f.campaign_id)

    db_connection.execute(
        text(
            "UPDATE narrative.encounters SET timeline_id = :t, campaign_id = :c, "
            "summary = 'touched' WHERE encounter_id = :e"
        ),
        {"t": f.timeline_id, "c": f.campaign_id, "e": encounter_id},
    )
    row = db_connection.execute(
        text(
            "SELECT timeline_id, campaign_id, summary FROM narrative.encounters "
            "WHERE encounter_id = :e"
        ),
        {"e": encounter_id},
    ).one()
    assert row.timeline_id == f.timeline_id
    assert row.campaign_id == f.campaign_id
    assert row.summary == "touched"


def test_reparenting_a_campaign_less_encounters_timeline_after_a_recorded_turn_is_rejected(
    db_connection: Connection, f: Fixture
) -> None:
    """NULL campaign_id plus an existing turn/interaction: the encounter
    has no campaign to indirectly pin its timeline, so only the new
    timeline_id guard itself protects the interaction this turn already
    created on the original timeline."""
    encounter_id = make_encounter(db_connection, f.timeline_id, f.t0)
    interaction_id = make_interaction(db_connection, f.timeline_id, f.t0)
    action_id = make_action(db_connection, interaction_id, f.character_a)
    combat_action_id = make_combat_action(db_connection, action_id)
    round_id = make_encounter_round(db_connection, encounter_id, 1)
    participant_id = make_encounter_participant(db_connection, encounter_id, f.character_a)
    make_encounter_turn(
        db_connection, round_id, participant_id, 0, combat_action_id=combat_action_id
    )

    other_timeline = _make_timeline(db_connection, f.world_id, name="Other Branch")
    with pytest.raises(CONSTRAINT_ERRORS) as exc, db_connection.begin_nested():
        db_connection.execute(
            text("UPDATE narrative.encounters SET timeline_id = :t WHERE encounter_id = :e"),
            {"t": other_timeline, "e": encounter_id},
        )
    assert "immutable" in str(exc.value)

    stored = db_connection.execute(
        text("SELECT timeline_id FROM interaction.interactions WHERE interaction_id = :i"),
        {"i": interaction_id},
    ).scalar()
    assert stored == f.timeline_id


def test_reparenting_a_campaign_less_encounters_timeline_after_a_caused_event_is_rejected(
    db_connection: Connection, f: Fixture
) -> None:
    encounter_id = make_encounter(db_connection, f.timeline_id, f.t0)
    event_id = make_event(
        db_connection,
        f.world_id,
        f.timeline_id,
        f.t0,
        event_type_code="combat_damage_dealt",
    )
    db_connection.execute(
        text(
            "INSERT INTO narrative.event_causes (event_id, cause_encounter_id) "
            "VALUES (:event, :encounter)"
        ),
        {"event": event_id, "encounter": encounter_id},
    )

    other_timeline = _make_timeline(db_connection, f.world_id, name="Other Branch")
    with pytest.raises(CONSTRAINT_ERRORS) as exc, db_connection.begin_nested():
        db_connection.execute(
            text("UPDATE narrative.encounters SET timeline_id = :t WHERE encounter_id = :e"),
            {"t": other_timeline, "e": encounter_id},
        )
    assert "immutable" in str(exc.value)

    stored = db_connection.execute(
        text("SELECT timeline_id FROM narrative.events WHERE event_id = :e"), {"e": event_id}
    ).scalar()
    assert stored == f.timeline_id


def test_reparenting_a_campaign_less_encounters_timeline_after_completion_is_rejected(
    db_connection: Connection, f: Fixture
) -> None:
    event_id = make_event(db_connection, f.world_id, f.timeline_id, f.t0)
    encounter_id = make_encounter(
        db_connection, f.timeline_id, f.t0, status="completed", resulting_event_id=event_id
    )

    other_timeline = _make_timeline(db_connection, f.world_id, name="Other Branch")
    with pytest.raises(CONSTRAINT_ERRORS) as exc, db_connection.begin_nested():
        db_connection.execute(
            text("UPDATE narrative.encounters SET timeline_id = :t WHERE encounter_id = :e"),
            {"t": other_timeline, "e": encounter_id},
        )
    assert "immutable" in str(exc.value)

    row = db_connection.execute(
        text(
            "SELECT e.timeline_id AS encounter_timeline, ev.timeline_id AS event_timeline "
            "FROM narrative.encounters e "
            "JOIN narrative.events ev ON ev.event_id = e.resulting_event_id "
            "WHERE e.encounter_id = :e"
        ),
        {"e": encounter_id},
    ).one()
    assert row.encounter_timeline == f.timeline_id
    assert row.event_timeline == f.timeline_id


def test_the_provenance_audit_detects_a_preexisting_timeline_mismatch(
    db_connection: Connection, f: Fixture
) -> None:
    """Standalone proof that revision 081's second pre-flight audit query
    (the migration's own DO block, reproduced here verbatim as a plain
    SELECT rather than its RAISE-wrapped form) actually flags exactly the
    corruption tr_encounters_identity_immutable now prevents going
    forward: a turn's interaction whose timeline_id disagrees with its
    causing encounter's timeline_id. Nothing currently validates that
    relationship on ordinary INSERT — it is reached only via
    encounter_rounds/encounter_turns/combat_actions/actions, none of
    which cross-check against the encounter's own timeline_id — so this
    scenario is constructible directly through the normal factories,
    without needing to bypass any trigger. Re-running the full migration
    end to end to prove the audit fires is not feasible with this
    project's tooling (see test_a_share_row_exclusive_lock_on_encounters_
    blocks_a_concurrent_insert_until_released's own docstring); this
    proves the audit's own SQL logic instead."""
    encounter_id = make_encounter(db_connection, f.timeline_id, f.t0)
    other_timeline = _make_timeline(db_connection, f.world_id, name="Other Branch")
    interaction_id = make_interaction(db_connection, other_timeline, f.t0)
    action_id = make_action(db_connection, interaction_id, f.character_a)
    combat_action_id = make_combat_action(db_connection, action_id)
    round_id = make_encounter_round(db_connection, encounter_id, 1)
    participant_id = make_encounter_participant(db_connection, encounter_id, f.character_a)
    make_encounter_turn(
        db_connection, round_id, participant_id, 0, combat_action_id=combat_action_id
    )

    violations = db_connection.execute(
        text("""
            SELECT count(*)
            FROM narrative.encounters e
            WHERE EXISTS (
                SELECT 1
                FROM narrative.encounter_rounds er
                JOIN narrative.encounter_turns et ON et.encounter_round_id = er.encounter_round_id
                JOIN interaction.combat_actions ca ON ca.combat_action_id = et.combat_action_id
                JOIN interaction.actions a ON a.action_id = ca.action_id
                JOIN interaction.interactions i ON i.interaction_id = a.interaction_id
                WHERE er.encounter_id = e.encounter_id
                  AND (
                      i.timeline_id IS DISTINCT FROM e.timeline_id
                      OR i.campaign_id IS DISTINCT FROM e.campaign_id
                  )
            )
            AND e.encounter_id = :e
        """),
        {"e": encounter_id},
    ).scalar()
    assert violations == 1, (
        "the migration's own audit query must detect a preexisting timeline mismatch "
        "reached through encounter_rounds/encounter_turns/combat_actions/actions"
    )


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
# Migration 081's LOCK TABLE ... IN SHARE ROW EXCLUSIVE MODE (the exact
# lock-conflict property that migration's "Locking considerations"
# docstring depends on)
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


def test_a_share_row_exclusive_lock_on_encounters_blocks_a_concurrent_insert_until_released(
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
    ROW EXCLUSIVE MODE`, held across a transaction, genuinely blocks a
    concurrent INSERT (the same ROW EXCLUSIVE lock class UPDATE also
    acquires, per PostgreSQL's table-level lock-conflict rules — see the
    migration's own "Locking considerations" docstring) until that
    transaction ends, and the blocked statement then proceeds cleanly.
    Revision 081 acquires this exact lock (SHARE ROW EXCLUSIVE, not plain
    SHARE — needed because its own CREATE TRIGGER requires it, and
    acquired upfront rather than via a later escalation to avoid a
    lock-upgrade deadlock hazard between two concurrent migration runs;
    see the migration's own "Locking considerations" docstring) before
    either of its two audits and holds it through both `CREATE OR REPLACE
    FUNCTION` calls, `CREATE TRIGGER`, and its own commit — so if this
    lock genuinely serializes writers against a held SHARE ROW EXCLUSIVE
    lock (proven here), it equally serializes them against that
    migration's audits + function replacement + trigger creation: no
    concurrent writer can commit a row either audit already passed
    judgment on, because no concurrent writer can commit *anything* until
    the migration's own transaction — both audits, both function
    replacements, the trigger, and all — has already committed.
    """
    lock_connection = postgres_engine.connect()
    lock_transaction = lock_connection.begin()

    insert_started = threading.Event()
    insert_done = threading.Event()
    results: dict[str, uuid.UUID] = {}
    pids: dict[str, int] = {}
    errors: dict[str, Exception] = {}

    def _insert() -> None:
        try:
            with postgres_engine.connect() as connection:
                # Captured before the (blocking) INSERT so the main thread
                # can identify this exact backend in pg_stat_activity
                # deterministically — matching on query *text* is fragile:
                # the literal SQL psycopg sends is this triple-quoted
                # string verbatim, including its own leading newline/
                # indentation, so pg_stat_activity.query never actually
                # begins with "INSERT" (an earlier version of this test
                # matched `query ILIKE 'INSERT INTO narrative.encounters%'`
                # — a pattern with no leading wildcard — and so never
                # matched anything, at any point, in any run). A backend
                # PID is exact and format-independent.
                pids["insert"] = connection.execute(text("SELECT pg_backend_pid()")).scalar_one()
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
        lock_connection.execute(text("LOCK TABLE narrative.encounters IN SHARE ROW EXCLUSIVE MODE"))

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
        insert_pid = pids["insert"]

        # Poll pg_stat_activity server-side for confirmation the INSERT is
        # genuinely blocked on our lock, rather than trusting a fixed
        # client-side sleep to have been long enough. Matched by the exact
        # backend pid captured above — deterministic and format-
        # independent, unlike matching on query text (see _insert()'s own
        # comment on why an earlier version of this pattern never matched).
        deadline = time.monotonic() + 60
        blocked = False
        while time.monotonic() < deadline:
            waiting = lock_connection.execute(
                text("""
                    SELECT count(*) FROM pg_stat_activity
                    WHERE pid = :pid AND wait_event_type = 'Lock'
                """),
                {"pid": insert_pid},
            ).scalar()
            if waiting:
                blocked = True
                break
            time.sleep(0.1)

        assert blocked, (
            "the concurrent INSERT was never observed blocked behind the SHARE ROW EXCLUSIVE lock"
        )
        assert not insert_done.is_set(), (
            "INSERT completed despite the SHARE ROW EXCLUSIVE lock still being held"
        )
    finally:
        with contextlib.suppress(Exception):
            lock_transaction.rollback()
        with contextlib.suppress(Exception):
            lock_connection.close()

    assert insert_done.wait(timeout=60), "INSERT never completed after the lock was released"
    thread.join(timeout=60)
    assert not thread.is_alive()
    assert not errors, f"the INSERT failed after the lock released: {errors}"

    with postgres_engine.connect() as verify:
        exists = verify.execute(
            text("SELECT count(*) FROM narrative.encounters WHERE encounter_id = :e"),
            {"e": results["encounter_id"]},
        ).scalar()
        assert exists == 1, "the INSERT that proceeded after the lock released did not commit"
