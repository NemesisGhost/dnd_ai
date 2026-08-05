"""narrative.events, event_participants, event_locations, event_causes,
event_effects, event_observations (revisions 057, 062).

Covers: the CTI subtype registration for events, each table's world-agreement
guard, and the CHECK constraints that don't depend on cross-row lookups
(event_causes' exactly-one-cause/no-self-cause rules, event_effects'
at-most-one-target rule, event_locations' role vocabulary,
event_observations' text length). event_causes.cause_interaction_id
(revision 062) is covered here too, since it lives on this table. Branch-aware
effective history is a separate concern — see
tests/scenario/test_branch_effective_history.py.
"""

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError, InternalError, ProgrammingError

from tests.factories import (
    lookup_id,
    make_area_hazard,
    make_campaign,
    make_dungeon,
    make_dungeon_area,
    make_entity,
    make_event,
    make_interaction,
    make_location,
    make_session,
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
        self.world_time_id = make_world_time(connection, self.world_id, 100)
        self.campaign_id = make_campaign(connection, self.timeline_id)
        self.session_id = make_session(connection, self.campaign_id, 1)
        self.dungeon_id = make_dungeon(connection, self.world_id)
        self.area_id = make_dungeon_area(connection, self.dungeon_id)
        self.hazard_id = make_area_hazard(connection, self.area_id)
        self.event_id = make_event(
            connection,
            self.world_id,
            self.timeline_id,
            self.world_time_id,
            campaign_id=self.campaign_id,
            session_id=self.session_id,
        )


@pytest.fixture
def f(db_connection: Connection) -> Fixture:
    return Fixture(db_connection, "narrative-event-world")


# ---------------------------------------------------------------------------
# narrative.events — CTI subtype and world/scope consistency
# ---------------------------------------------------------------------------


def test_an_event_row_requires_an_event_typed_entity(db_connection: Connection, f: Fixture) -> None:
    """core.enforce_entity_subtype() rejects a narrative.events row for an
    entity whose type chain doesn't require it — here, a dungeon area."""
    with pytest.raises(CONSTRAINT_ERRORS):
        db_connection.execute(
            text("""
                INSERT INTO narrative.events
                    (event_id, timeline_id, event_type_id, event_status_id, world_time_id)
                VALUES (
                    :area,
                    :timeline,
                    (SELECT event_type_id FROM narrative.event_types WHERE code = 'other'),
                    (SELECT event_status_id FROM narrative.event_statuses WHERE code = 'recorded'),
                    :world_time
                )
            """),
            {"area": f.area_id, "timeline": f.timeline_id, "world_time": f.world_time_id},
        )


def test_an_event_can_be_created_with_campaign_and_session(
    db_connection: Connection, f: Fixture
) -> None:
    row = db_connection.execute(
        text(
            "SELECT timeline_id, campaign_id, session_id FROM narrative.events WHERE event_id = :e"
        ),
        {"e": f.event_id},
    ).one()
    assert row.timeline_id == f.timeline_id
    assert row.campaign_id == f.campaign_id
    assert row.session_id == f.session_id


def test_event_timeline_must_belong_to_the_events_world(
    db_connection: Connection, f: Fixture
) -> None:
    other_world = make_world(db_connection, slug="narrative-event-other-world")
    other_timeline = make_timeline(db_connection, other_world, is_primary=True)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_event(db_connection, f.world_id, other_timeline, f.world_time_id)
    assert "belongs to world" in str(exc.value)


def test_event_world_time_must_belong_to_the_events_world(
    db_connection: Connection, f: Fixture
) -> None:
    other_world = make_world(db_connection, slug="narrative-event-time-other-world")
    other_world_time = make_world_time(db_connection, other_world, 50)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_event(db_connection, f.world_id, f.timeline_id, other_world_time)
    assert "belongs to world" in str(exc.value)


def test_event_campaign_must_belong_to_the_events_timeline(
    db_connection: Connection, f: Fixture
) -> None:
    other_timeline = make_timeline(db_connection, f.world_id, name="Other Timeline")
    other_campaign = make_campaign(db_connection, other_timeline)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_event(
            db_connection,
            f.world_id,
            f.timeline_id,
            f.world_time_id,
            campaign_id=other_campaign,
        )
    assert "belongs to timeline" in str(exc.value)


def test_event_session_must_belong_to_the_events_campaign(
    db_connection: Connection, f: Fixture
) -> None:
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_event(
            db_connection,
            f.world_id,
            f.timeline_id,
            f.world_time_id,
            session_id=f.session_id,
            # campaign_id omitted: the session belongs to f.campaign_id, so this
            # is a mismatch (NULL != f.campaign_id).
        )
    assert "campaign_id" in str(exc.value)


def test_event_session_from_a_different_campaign_is_rejected(
    db_connection: Connection, f: Fixture
) -> None:
    other_campaign = make_campaign(db_connection, f.timeline_id)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_event(
            db_connection,
            f.world_id,
            f.timeline_id,
            f.world_time_id,
            campaign_id=other_campaign,
            session_id=f.session_id,
        )
    assert "campaign_id" in str(exc.value)


# ---------------------------------------------------------------------------
# narrative.event_participants
# ---------------------------------------------------------------------------


def test_a_participant_can_be_added_with_a_role(db_connection: Connection, f: Fixture) -> None:
    actor = make_entity(
        db_connection,
        f.world_id,
        lookup_id(db_connection, "core", "entity_types", "entity_type_id", "location"),
    )
    db_connection.execute(
        text("""
            INSERT INTO narrative.event_participants
                (event_id, participant_entity_id, participant_role_id)
            VALUES (
                :event, :entity,
                (SELECT event_participant_role_id FROM narrative.event_participant_roles
                 WHERE code = 'actor')
            )
        """),
        {"event": f.event_id, "entity": actor},
    )


def test_a_participant_must_belong_to_the_events_world(
    db_connection: Connection, f: Fixture
) -> None:
    other_world = make_world(db_connection, slug="narrative-participant-other-world")
    other_entity = make_entity(
        db_connection,
        other_world,
        lookup_id(db_connection, "core", "entity_types", "entity_type_id", "location"),
    )

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("""
                INSERT INTO narrative.event_participants
                    (event_id, participant_entity_id, participant_role_id)
                VALUES (
                    :event, :entity,
                    (SELECT event_participant_role_id FROM narrative.event_participant_roles
                     WHERE code = 'witness')
                )
            """),
            {"event": f.event_id, "entity": other_entity},
        )
    assert "belongs to world" in str(exc.value)


# ---------------------------------------------------------------------------
# narrative.event_locations
# ---------------------------------------------------------------------------


def test_an_event_location_defaults_to_occurred_at(db_connection: Connection, f: Fixture) -> None:
    location_id = make_location(db_connection, f.world_id)
    db_connection.execute(
        text("INSERT INTO narrative.event_locations (event_id, location_id) VALUES (:e, :l)"),
        {"e": f.event_id, "l": location_id},
    )
    role = db_connection.execute(
        text(
            "SELECT event_location_role FROM narrative.event_locations "
            "WHERE event_id = :e AND location_id = :l"
        ),
        {"e": f.event_id, "l": location_id},
    ).scalar()
    assert role == "occurred_at"


def test_an_event_location_role_must_be_a_known_value(
    db_connection: Connection, f: Fixture
) -> None:
    location_id = make_location(db_connection, f.world_id)
    with pytest.raises(IntegrityError) as exc:
        db_connection.execute(
            text(
                "INSERT INTO narrative.event_locations (event_id, location_id, "
                "event_location_role) VALUES (:e, :l, 'somewhere_else')"
            ),
            {"e": f.event_id, "l": location_id},
        )
    assert "ck_event_locations_role" in str(exc.value)


def test_an_event_location_must_belong_to_the_events_world(
    db_connection: Connection, f: Fixture
) -> None:
    other_world = make_world(db_connection, slug="narrative-location-other-world")
    other_location = make_location(db_connection, other_world)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("INSERT INTO narrative.event_locations (event_id, location_id) VALUES (:e, :l)"),
            {"e": f.event_id, "l": other_location},
        )
    assert "belongs to world" in str(exc.value)


# ---------------------------------------------------------------------------
# narrative.event_causes
# ---------------------------------------------------------------------------


def test_an_event_cause_needs_an_event_or_a_description(
    db_connection: Connection, f: Fixture
) -> None:
    with pytest.raises(IntegrityError) as exc:
        db_connection.execute(
            text("INSERT INTO narrative.event_causes (event_id) VALUES (:e)"),
            {"e": f.event_id},
        )
    assert "ck_event_causes_has_cause" in str(exc.value)


def test_an_event_cannot_cause_itself(db_connection: Connection, f: Fixture) -> None:
    with pytest.raises(IntegrityError) as exc:
        db_connection.execute(
            text("INSERT INTO narrative.event_causes (event_id, cause_event_id) VALUES (:e, :e)"),
            {"e": f.event_id},
        )
    assert "ck_event_causes_no_self_cause" in str(exc.value)


def test_an_event_cause_can_reference_a_prior_event(db_connection: Connection, f: Fixture) -> None:
    later_time = make_world_time(db_connection, f.world_id, 200)
    later_event = make_event(db_connection, f.world_id, f.timeline_id, later_time)
    db_connection.execute(
        text("INSERT INTO narrative.event_causes (event_id, cause_event_id) VALUES (:e, :c)"),
        {"e": later_event, "c": f.event_id},
    )


def test_an_event_cause_can_be_a_free_text_description(
    db_connection: Connection, f: Fixture
) -> None:
    db_connection.execute(
        text(
            "INSERT INTO narrative.event_causes (event_id, cause_description) "
            "VALUES (:e, 'the party opened the vault')"
        ),
        {"e": f.event_id},
    )


def test_an_event_cause_can_reference_an_interaction(db_connection: Connection, f: Fixture) -> None:
    interaction_id = make_interaction(db_connection, f.timeline_id, f.world_time_id)
    db_connection.execute(
        text("INSERT INTO narrative.event_causes (event_id, cause_interaction_id) VALUES (:e, :i)"),
        {"e": f.event_id, "i": interaction_id},
    )


def test_an_event_cause_cannot_set_both_event_and_interaction(
    db_connection: Connection, f: Fixture
) -> None:
    later_time = make_world_time(db_connection, f.world_id, 200)
    later_event = make_event(db_connection, f.world_id, f.timeline_id, later_time)
    interaction_id = make_interaction(db_connection, f.timeline_id, f.world_time_id)

    with pytest.raises(IntegrityError) as exc:
        db_connection.execute(
            text(
                "INSERT INTO narrative.event_causes "
                "(event_id, cause_event_id, cause_interaction_id) VALUES (:e, :c, :i)"
            ),
            {"e": later_event, "c": f.event_id, "i": interaction_id},
        )
    assert "ck_event_causes_has_cause" in str(exc.value)


def test_an_event_causes_interaction_must_belong_to_the_events_timeline(
    db_connection: Connection, f: Fixture
) -> None:
    other_timeline = make_timeline(db_connection, f.world_id, name="Other Timeline")
    other_interaction = make_interaction(db_connection, other_timeline, f.world_time_id)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "INSERT INTO narrative.event_causes (event_id, cause_interaction_id) "
                "VALUES (:e, :i)"
            ),
            {"e": f.event_id, "i": other_interaction},
        )
    assert "belongs to timeline" in str(exc.value)


# ---------------------------------------------------------------------------
# narrative.event_effects
# ---------------------------------------------------------------------------


def test_an_event_effect_can_target_a_hazard(db_connection: Connection, f: Fixture) -> None:
    db_connection.execute(
        text(
            "INSERT INTO narrative.event_effects "
            "(event_id, target_area_hazard_id, target_component, new_value) "
            "VALUES (:e, :h, 'hazard_status_id', '\"disarmed\"'::jsonb)"
        ),
        {"e": f.event_id, "h": f.hazard_id},
    )


def test_an_event_effect_cannot_target_two_things_at_once(
    db_connection: Connection, f: Fixture
) -> None:
    other_entity = make_entity(
        db_connection,
        f.world_id,
        lookup_id(db_connection, "core", "entity_types", "entity_type_id", "location"),
    )
    with pytest.raises(IntegrityError) as exc:
        db_connection.execute(
            text(
                "INSERT INTO narrative.event_effects "
                "(event_id, target_entity_id, target_area_hazard_id, target_component) "
                "VALUES (:e, :entity, :hazard, 'x')"
            ),
            {"e": f.event_id, "entity": other_entity, "hazard": f.hazard_id},
        )
    assert "ck_event_effects_at_most_one_target" in str(exc.value)


def test_an_event_effect_target_must_belong_to_the_events_world(
    db_connection: Connection, f: Fixture
) -> None:
    other_world = make_world(db_connection, slug="narrative-effect-other-world")
    other_entity = make_entity(
        db_connection,
        other_world,
        lookup_id(db_connection, "core", "entity_types", "entity_type_id", "location"),
    )

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "INSERT INTO narrative.event_effects "
                "(event_id, target_entity_id, target_component) VALUES (:e, :t, 'x')"
            ),
            {"e": f.event_id, "t": other_entity},
        )
    assert "belongs to world" in str(exc.value)


def test_an_event_effect_application_status_must_be_a_known_value(
    db_connection: Connection, f: Fixture
) -> None:
    with pytest.raises(IntegrityError) as exc:
        db_connection.execute(
            text(
                "INSERT INTO narrative.event_effects "
                "(event_id, target_component, application_status) VALUES (:e, 'x', 'bogus')"
            ),
            {"e": f.event_id},
        )
    assert "ck_event_effects_application_status" in str(exc.value)


# ---------------------------------------------------------------------------
# narrative.event_observations
# ---------------------------------------------------------------------------


def test_an_observation_can_be_recorded(db_connection: Connection, f: Fixture) -> None:
    observer = make_entity(
        db_connection,
        f.world_id,
        lookup_id(db_connection, "core", "entity_types", "entity_type_id", "location"),
    )
    db_connection.execute(
        text(
            "INSERT INTO narrative.event_observations "
            "(event_id, observer_entity_id, observation_text) VALUES (:e, :o, 'A loud bang.')"
        ),
        {"e": f.event_id, "o": observer},
    )


def test_an_observation_cannot_be_empty(db_connection: Connection, f: Fixture) -> None:
    observer = make_entity(
        db_connection,
        f.world_id,
        lookup_id(db_connection, "core", "entity_types", "entity_type_id", "location"),
    )
    with pytest.raises(IntegrityError) as exc:
        db_connection.execute(
            text(
                "INSERT INTO narrative.event_observations "
                "(event_id, observer_entity_id, observation_text) VALUES (:e, :o, '')"
            ),
            {"e": f.event_id, "o": observer},
        )
    assert "ck_event_observations_text_length" in str(exc.value)


def test_an_observer_must_belong_to_the_events_world(db_connection: Connection, f: Fixture) -> None:
    other_world = make_world(db_connection, slug="narrative-observer-other-world")
    other_observer = make_entity(
        db_connection,
        other_world,
        lookup_id(db_connection, "core", "entity_types", "entity_type_id", "location"),
    )

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "INSERT INTO narrative.event_observations "
                "(event_id, observer_entity_id, observation_text) VALUES (:e, :o, 'Something.')"
            ),
            {"e": f.event_id, "o": other_observer},
        )
    assert "belongs to world" in str(exc.value)
