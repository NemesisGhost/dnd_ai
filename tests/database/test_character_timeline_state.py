"""campaign.character_state, .character_conditions, .character_resources
(revision 021).

Covers: the world-agreement guard shared across all three tables, HP/death-
save bounds, one active instance of a given condition per character per
timeline, and current-within-maximum for resources.
"""

import uuid

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError, InternalError, ProgrammingError

from tests.factories import make_character, make_ruleset_version, make_timeline, make_world

pytestmark = pytest.mark.database

CONSTRAINT_ERRORS = (IntegrityError, InternalError, ProgrammingError)


class Fixture:
    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        self.character_id = make_character(connection, self.world_id)


@pytest.fixture
def f(db_connection: Connection) -> Fixture:
    return Fixture(db_connection, "state-world")


def _make_condition(connection: Connection, version: uuid.UUID, code: str) -> uuid.UUID:
    return connection.execute(
        text(
            "INSERT INTO rules.conditions (ruleset_version_id, code, display_name) "
            "VALUES (:v, :c, :c) RETURNING condition_id"
        ),
        {"v": version, "c": code},
    ).scalar()


def _make_resource_definition(connection: Connection, version: uuid.UUID, code: str) -> uuid.UUID:
    return connection.execute(
        text(
            "INSERT INTO rules.resource_definitions (ruleset_version_id, code, display_name) "
            "VALUES (:v, :c, :c) RETURNING resource_definition_id"
        ),
        {"v": version, "c": code},
    ).scalar()


# ---------------------------------------------------------------------------
# campaign.character_state
# ---------------------------------------------------------------------------


def test_a_character_can_have_state_on_a_timeline(db_connection: Connection, f: Fixture) -> None:
    db_connection.execute(
        text(
            "INSERT INTO campaign.character_state "
            "(timeline_id, character_id, current_hit_points, maximum_hit_points) "
            "VALUES (:tl, :c, 10, 10)"
        ),
        {"tl": f.timeline_id, "c": f.character_id},
    )


def test_death_saves_cannot_exceed_three(db_connection: Connection, f: Fixture) -> None:
    with pytest.raises(IntegrityError) as exc:
        db_connection.execute(
            text(
                "INSERT INTO campaign.character_state "
                "(timeline_id, character_id, current_hit_points, maximum_hit_points, "
                " death_save_failures) VALUES (:tl, :c, 0, 10, 4)"
            ),
            {"tl": f.timeline_id, "c": f.character_id},
        )
    assert "ck_character_state_death_saves" in str(exc.value)


def test_current_hit_points_cannot_be_negative(db_connection: Connection, f: Fixture) -> None:
    with pytest.raises(IntegrityError) as exc:
        db_connection.execute(
            text(
                "INSERT INTO campaign.character_state "
                "(timeline_id, character_id, current_hit_points, maximum_hit_points) "
                "VALUES (:tl, :c, -1, 10)"
            ),
            {"tl": f.timeline_id, "c": f.character_id},
        )
    assert "ck_character_state_hp_nonnegative" in str(exc.value)


def test_a_character_cannot_be_transformed_into_itself(
    db_connection: Connection, f: Fixture
) -> None:
    with pytest.raises(IntegrityError) as exc:
        db_connection.execute(
            text(
                "INSERT INTO campaign.character_state "
                "(timeline_id, character_id, current_hit_points, maximum_hit_points, "
                " transformed_into_id) VALUES (:tl, :c, 10, 10, :c)"
            ),
            {"tl": f.timeline_id, "c": f.character_id},
        )
    assert "ck_character_state_not_own_transformation" in str(exc.value)


def test_character_state_requires_the_character_belong_to_the_timelines_world(
    db_connection: Connection, f: Fixture
) -> None:
    other_world = make_world(db_connection, slug="state-other-world")
    other_timeline = make_timeline(db_connection, other_world, is_primary=True)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "INSERT INTO campaign.character_state "
                "(timeline_id, character_id, current_hit_points, maximum_hit_points) "
                "VALUES (:tl, :c, 10, 10)"
            ),
            {"tl": other_timeline, "c": f.character_id},
        )
    assert "belongs to world" in str(exc.value)


# ---------------------------------------------------------------------------
# campaign.character_conditions
# ---------------------------------------------------------------------------


def test_a_character_has_at_most_one_instance_of_a_given_condition(
    db_connection: Connection, f: Fixture
) -> None:
    version = make_ruleset_version(db_connection)
    condition = _make_condition(db_connection, version, "poisoned")

    db_connection.execute(
        text(
            "INSERT INTO campaign.character_conditions (timeline_id, character_id, condition_id) "
            "VALUES (:tl, :c, :cond)"
        ),
        {"tl": f.timeline_id, "c": f.character_id, "cond": condition},
    )
    with pytest.raises(IntegrityError):
        db_connection.execute(
            text(
                "INSERT INTO campaign.character_conditions "
                "(timeline_id, character_id, condition_id) VALUES (:tl, :c, :cond)"
            ),
            {"tl": f.timeline_id, "c": f.character_id, "cond": condition},
        )


def test_conditions_require_world_agreement(db_connection: Connection, f: Fixture) -> None:
    other_world = make_world(db_connection, slug="condition-other-world")
    other_timeline = make_timeline(db_connection, other_world, is_primary=True)
    version = make_ruleset_version(db_connection)
    condition = _make_condition(db_connection, version, "prone")

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "INSERT INTO campaign.character_conditions "
                "(timeline_id, character_id, condition_id) VALUES (:tl, :c, :cond)"
            ),
            {"tl": other_timeline, "c": f.character_id, "cond": condition},
        )
    assert "belongs to world" in str(exc.value)


# ---------------------------------------------------------------------------
# campaign.character_resources
# ---------------------------------------------------------------------------


def test_current_amount_cannot_exceed_maximum(db_connection: Connection, f: Fixture) -> None:
    version = make_ruleset_version(db_connection)
    resource = _make_resource_definition(db_connection, version, "spell_slot")

    with pytest.raises(IntegrityError) as exc:
        db_connection.execute(
            text(
                "INSERT INTO campaign.character_resources "
                "(timeline_id, character_id, resource_definition_id, current_amount, maximum_amount) "
                "VALUES (:tl, :c, :r, 5, 3)"
            ),
            {"tl": f.timeline_id, "c": f.character_id, "r": resource},
        )
    assert "ck_character_resources_current_within_max" in str(exc.value)


def test_current_amount_within_maximum_succeeds(db_connection: Connection, f: Fixture) -> None:
    version = make_ruleset_version(db_connection)
    resource = _make_resource_definition(db_connection, version, "ki_point")

    db_connection.execute(
        text(
            "INSERT INTO campaign.character_resources "
            "(timeline_id, character_id, resource_definition_id, current_amount, maximum_amount) "
            "VALUES (:tl, :c, :r, 2, 3)"
        ),
        {"tl": f.timeline_id, "c": f.character_id, "r": resource},
    )
