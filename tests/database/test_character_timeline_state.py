"""campaign.character_state, .character_conditions, .character_resources
(revision 021; corrected and extended by revisions 028-029).

Covers: the world-agreement guard shared across all three tables, HP/death-
save bounds (including current-not-exceeding-maximum, added by revision 029),
one active instance of a given condition per character per timeline,
current-within-maximum for resources, transformed_into_id same-world
(revision 029), timeline-scoped active build selection via
character_build_id (revision 028), and rule content (conditions/resources)
being allowed for the character's own world (revision 029).
"""

import uuid

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError, InternalError, ProgrammingError

from tests.factories import (
    make_character,
    make_ruleset_version,
    make_ruleset_version_for_world,
    make_timeline,
    make_world,
)

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
    version = make_ruleset_version_for_world(db_connection, f.world_id)
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
    version = make_ruleset_version_for_world(db_connection, other_world)
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
    version = make_ruleset_version_for_world(db_connection, f.world_id)
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
    version = make_ruleset_version_for_world(db_connection, f.world_id)
    resource = _make_resource_definition(db_connection, version, "ki_point")

    db_connection.execute(
        text(
            "INSERT INTO campaign.character_resources "
            "(timeline_id, character_id, resource_definition_id, current_amount, maximum_amount) "
            "VALUES (:tl, :c, :r, 2, 3)"
        ),
        {"tl": f.timeline_id, "c": f.character_id, "r": resource},
    )


def test_a_condition_from_a_disallowed_ruleset_is_rejected(
    db_connection: Connection, f: Fixture
) -> None:
    """revision 029: a condition must be drawn from a ruleset the character's
    world actually allows, not merely exist."""
    foreign_version = make_ruleset_version(db_connection)
    condition = _make_condition(db_connection, foreign_version, "stunned")

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "INSERT INTO campaign.character_conditions "
                "(timeline_id, character_id, condition_id) VALUES (:tl, :c, :cond)"
            ),
            {"tl": f.timeline_id, "c": f.character_id, "cond": condition},
        )
    assert "not allowed for world" in str(exc.value)


def test_a_resource_definition_from_a_disallowed_ruleset_is_rejected(
    db_connection: Connection, f: Fixture
) -> None:
    foreign_version = make_ruleset_version(db_connection)
    resource = _make_resource_definition(db_connection, foreign_version, "rage_use")

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "INSERT INTO campaign.character_resources "
                "(timeline_id, character_id, resource_definition_id, current_amount, "
                " maximum_amount) VALUES (:tl, :c, :r, 1, 1)"
            ),
            {"tl": f.timeline_id, "c": f.character_id, "r": resource},
        )
    assert "not allowed for world" in str(exc.value)


# ---------------------------------------------------------------------------
# campaign.character_state.current_hit_points <= maximum_hit_points
# ---------------------------------------------------------------------------


def test_current_hit_points_cannot_exceed_maximum(db_connection: Connection, f: Fixture) -> None:
    with pytest.raises(IntegrityError) as exc:
        db_connection.execute(
            text(
                "INSERT INTO campaign.character_state "
                "(timeline_id, character_id, current_hit_points, maximum_hit_points) "
                "VALUES (:tl, :c, 15, 10)"
            ),
            {"tl": f.timeline_id, "c": f.character_id},
        )
    assert "ck_character_state_current_within_max" in str(exc.value)


def test_current_hit_points_at_maximum_succeeds(db_connection: Connection, f: Fixture) -> None:
    db_connection.execute(
        text(
            "INSERT INTO campaign.character_state "
            "(timeline_id, character_id, current_hit_points, maximum_hit_points) "
            "VALUES (:tl, :c, 10, 10)"
        ),
        {"tl": f.timeline_id, "c": f.character_id},
    )


# ---------------------------------------------------------------------------
# campaign.character_state.transformed_into_id must share the character's world
# ---------------------------------------------------------------------------


def test_transformed_into_must_share_the_characters_world(
    db_connection: Connection, f: Fixture
) -> None:
    other_world = make_world(db_connection, slug="transform-other-world")
    foreign_character = make_character(db_connection, other_world)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "INSERT INTO campaign.character_state "
                "(timeline_id, character_id, current_hit_points, maximum_hit_points, "
                " transformed_into_id) VALUES (:tl, :c, 10, 10, :t)"
            ),
            {"tl": f.timeline_id, "c": f.character_id, "t": foreign_character},
        )
    assert "belongs to world" in str(exc.value)


def test_transformed_into_a_character_in_the_same_world_succeeds(
    db_connection: Connection, f: Fixture
) -> None:
    other_character = make_character(db_connection, f.world_id)

    db_connection.execute(
        text(
            "INSERT INTO campaign.character_state "
            "(timeline_id, character_id, current_hit_points, maximum_hit_points, "
            " transformed_into_id) VALUES (:tl, :c, 10, 10, :t)"
        ),
        {"tl": f.timeline_id, "c": f.character_id, "t": other_character},
    )


# ---------------------------------------------------------------------------
# campaign.character_state.character_build_id — timeline-scoped active build
# ---------------------------------------------------------------------------


def _make_build(connection: Connection, character_id: uuid.UUID, version: uuid.UUID) -> uuid.UUID:
    return connection.execute(
        text(
            "INSERT INTO character.character_builds (character_id, ruleset_version_id) "
            "VALUES (:c, :v) RETURNING character_build_id"
        ),
        {"c": character_id, "v": version},
    ).scalar()


def test_a_timeline_can_select_an_active_build_for_a_character(
    db_connection: Connection, f: Fixture
) -> None:
    version = make_ruleset_version_for_world(db_connection, f.world_id)
    build = _make_build(db_connection, f.character_id, version)

    db_connection.execute(
        text(
            "INSERT INTO campaign.character_state "
            "(timeline_id, character_id, current_hit_points, maximum_hit_points, "
            " character_build_id) VALUES (:tl, :c, 10, 10, :b)"
        ),
        {"tl": f.timeline_id, "c": f.character_id, "b": build},
    )

    selected = db_connection.execute(
        text(
            "SELECT character_build_id FROM campaign.character_state "
            "WHERE timeline_id = :tl AND character_id = :c"
        ),
        {"tl": f.timeline_id, "c": f.character_id},
    ).scalar()
    assert selected == build


def test_a_build_belonging_to_another_character_is_rejected(
    db_connection: Connection, f: Fixture
) -> None:
    version = make_ruleset_version_for_world(db_connection, f.world_id)
    other_character = make_character(db_connection, f.world_id, species_id=None)
    foreign_build = _make_build(db_connection, other_character, version)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "INSERT INTO campaign.character_state "
                "(timeline_id, character_id, current_hit_points, maximum_hit_points, "
                " character_build_id) VALUES (:tl, :c, 10, 10, :b)"
            ),
            {"tl": f.timeline_id, "c": f.character_id, "b": foreign_build},
        )
    assert "belongs to character" in str(exc.value)


def test_one_character_can_have_different_active_builds_on_different_timelines(
    db_connection: Connection, f: Fixture
) -> None:
    """The scenario ux_character_builds_one_current_per_character (revision
    020) could not represent: the same character, built two different ways,
    active simultaneously on two different timelines after a branch."""
    version = make_ruleset_version_for_world(db_connection, f.world_id)
    build_a = _make_build(db_connection, f.character_id, version)
    build_b = _make_build(db_connection, f.character_id, version)

    other_timeline = make_timeline(db_connection, f.world_id, name="Branch")

    db_connection.execute(
        text(
            "INSERT INTO campaign.character_state "
            "(timeline_id, character_id, current_hit_points, maximum_hit_points, "
            " character_build_id) VALUES (:tl, :c, 10, 10, :b)"
        ),
        {"tl": f.timeline_id, "c": f.character_id, "b": build_a},
    )
    db_connection.execute(
        text(
            "INSERT INTO campaign.character_state "
            "(timeline_id, character_id, current_hit_points, maximum_hit_points, "
            " character_build_id) VALUES (:tl, :c, 10, 10, :b)"
        ),
        {"tl": other_timeline, "c": f.character_id, "b": build_b},
    )

    selected = {
        r[0]: r[1]
        for r in db_connection.execute(
            text(
                "SELECT timeline_id, character_build_id FROM campaign.character_state "
                "WHERE character_id = :c"
            ),
            {"c": f.character_id},
        )
    }
    assert selected[f.timeline_id] == build_a
    assert selected[other_timeline] == build_b
