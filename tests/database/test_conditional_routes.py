"""world.area_connections check requirements, interaction.check_requests.
target_id, and world.conditional_route_requirement_satisfied() (revision 064).

Covers: the CHECK constraints tying required_check_kind/ability_id/skill_id/
difficulty together and to is_conditional, the ruleset-allow-list guard on
the requirement, the target-belongs-to-same-action guard on check_requests.
target_id, and the pure evaluation function's positive/negative cases —
matching check succeeded, wrong kind, insufficient difficulty, failed check,
and a check for an unrelated target.
"""

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError, InternalError, ProgrammingError

from tests.factories import (
    make_ability,
    make_action,
    make_area_connection,
    make_character,
    make_check_request,
    make_check_result,
    make_dungeon,
    make_dungeon_area,
    make_interaction,
    make_ruleset_version_for_world,
    make_skill,
    make_target,
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
        self.dungeon_id = make_dungeon(connection, self.world_id)
        self.area_a = make_dungeon_area(connection, self.dungeon_id, name="Entry Hall")
        self.area_b = make_dungeon_area(connection, self.dungeon_id, name="Vault")
        self.connection_id = make_area_connection(connection, self.area_a, self.area_b)
        self.actor_id = make_character(connection, self.world_id, name="Rin")
        self.interaction_id = make_interaction(connection, self.timeline_id, self.world_time_id)
        self.action_id = make_action(connection, self.interaction_id, self.actor_id)
        self.target_id = make_target(
            connection, self.action_id, target_area_connection_id=self.connection_id
        )
        ruleset_version_id = make_ruleset_version_for_world(connection, self.world_id)
        self.ability_id = make_ability(connection, ruleset_version_id)
        self.skill_id = make_skill(connection, ruleset_version_id, self.ability_id)

    def make_conditional(self, connection: Connection, **kwargs: object) -> None:
        connection.execute(
            text(
                "UPDATE world.area_connections SET is_conditional = true, "
                "condition_description = 'requires a check' WHERE area_connection_id = :c"
            ),
            {"c": self.connection_id},
        )
        if kwargs:
            columns = ", ".join(f"{k} = :{k}" for k in kwargs)
            connection.execute(
                text(f"UPDATE world.area_connections SET {columns} WHERE area_connection_id = :c"),
                {**kwargs, "c": self.connection_id},
            )


@pytest.fixture
def f(db_connection: Connection) -> Fixture:
    return Fixture(db_connection, "conditional-route-world")


# ---------------------------------------------------------------------------
# world.area_connections requirement CHECKs
# ---------------------------------------------------------------------------


def test_a_route_can_require_a_skill_check(db_connection: Connection, f: Fixture) -> None:
    f.make_conditional(
        db_connection,
        required_check_kind="skill_check",
        required_skill_id=f.skill_id,
        required_difficulty=15,
    )


def test_required_check_kind_must_be_a_known_value(db_connection: Connection, f: Fixture) -> None:
    f.make_conditional(db_connection)
    with pytest.raises(IntegrityError) as exc:
        db_connection.execute(
            text(
                "UPDATE world.area_connections SET required_check_kind = 'bogus' "
                "WHERE area_connection_id = :c"
            ),
            {"c": f.connection_id},
        )
    assert "ck_area_connections_check_requirement_kind" in str(exc.value)


def test_a_skill_check_requirement_cannot_also_set_ability_id(
    db_connection: Connection, f: Fixture
) -> None:
    f.make_conditional(db_connection)
    with pytest.raises(IntegrityError) as exc:
        db_connection.execute(
            text(
                "UPDATE world.area_connections SET required_check_kind = 'skill_check', "
                "required_skill_id = :s, required_ability_id = :a, required_difficulty = 10 "
                "WHERE area_connection_id = :c"
            ),
            {"c": f.connection_id, "s": f.skill_id, "a": f.ability_id},
        )
    assert "ck_area_connections_check_requirement_reference" in str(exc.value)


def test_a_check_requirement_requires_the_route_to_be_conditional(
    db_connection: Connection, f: Fixture
) -> None:
    with pytest.raises(IntegrityError) as exc:
        db_connection.execute(
            text(
                "UPDATE world.area_connections SET required_check_kind = 'ability_check', "
                "required_ability_id = :a, required_difficulty = 10 WHERE area_connection_id = :c"
            ),
            {"c": f.connection_id, "a": f.ability_id},
        )
    assert "ck_area_connections_check_requirement_conditional" in str(exc.value)


def test_a_check_requirement_ability_must_be_from_a_ruleset_the_world_allows(
    db_connection: Connection, f: Fixture
) -> None:
    other_world = make_world(db_connection, slug="conditional-route-other-world")
    disallowed_ruleset_version = make_ruleset_version_for_world(db_connection, other_world)
    disallowed_ability = make_ability(db_connection, disallowed_ruleset_version)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        f.make_conditional(
            db_connection,
            required_check_kind="ability_check",
            required_ability_id=disallowed_ability,
            required_difficulty=10,
        )
    assert "not allowed for world" in str(exc.value)


# ---------------------------------------------------------------------------
# interaction.check_requests.target_id
# ---------------------------------------------------------------------------


def test_a_check_request_can_target_a_specific_target(
    db_connection: Connection, f: Fixture
) -> None:
    make_check_request(
        db_connection,
        f.action_id,
        f.actor_id,
        check_kind="ability_check",
        ability_id=f.ability_id,
        target_id=f.target_id,
    )


def test_a_check_requests_target_must_belong_to_the_same_action(
    db_connection: Connection, f: Fixture
) -> None:
    other_action = make_action(db_connection, f.interaction_id, f.actor_id, sequence_number=1)
    other_target = make_target(
        db_connection, other_action, target_description="something else entirely"
    )

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_check_request(
            db_connection,
            f.action_id,
            f.actor_id,
            check_kind="ability_check",
            ability_id=f.ability_id,
            target_id=other_target,
        )
    assert "belongs to action" in str(exc.value)


# ---------------------------------------------------------------------------
# world.conditional_route_requirement_satisfied()
# ---------------------------------------------------------------------------


def _satisfied(connection: Connection, connection_id, check_result_id) -> bool:
    value = connection.execute(
        text("SELECT world.conditional_route_requirement_satisfied(:c, :r)"),
        {"c": connection_id, "r": check_result_id},
    ).scalar()
    assert isinstance(value, bool)
    return value


def test_a_successful_matching_check_satisfies_the_requirement(
    db_connection: Connection, f: Fixture
) -> None:
    f.make_conditional(
        db_connection,
        required_check_kind="skill_check",
        required_skill_id=f.skill_id,
        required_difficulty=15,
    )
    request_id = make_check_request(
        db_connection,
        f.action_id,
        f.actor_id,
        check_kind="skill_check",
        skill_id=f.skill_id,
        difficulty=15,
        target_id=f.target_id,
    )
    result_id = make_check_result(db_connection, request_id, degree_of_success="success")

    assert _satisfied(db_connection, f.connection_id, result_id) is True


def test_a_failed_check_does_not_satisfy_the_requirement(
    db_connection: Connection, f: Fixture
) -> None:
    f.make_conditional(
        db_connection,
        required_check_kind="skill_check",
        required_skill_id=f.skill_id,
        required_difficulty=15,
    )
    request_id = make_check_request(
        db_connection,
        f.action_id,
        f.actor_id,
        check_kind="skill_check",
        skill_id=f.skill_id,
        difficulty=15,
        target_id=f.target_id,
    )
    result_id = make_check_result(db_connection, request_id, degree_of_success="failure")

    assert _satisfied(db_connection, f.connection_id, result_id) is False


def test_a_lower_difficulty_check_does_not_satisfy_the_requirement(
    db_connection: Connection, f: Fixture
) -> None:
    f.make_conditional(
        db_connection,
        required_check_kind="skill_check",
        required_skill_id=f.skill_id,
        required_difficulty=15,
    )
    request_id = make_check_request(
        db_connection,
        f.action_id,
        f.actor_id,
        check_kind="skill_check",
        skill_id=f.skill_id,
        difficulty=10,
        target_id=f.target_id,
    )
    result_id = make_check_result(db_connection, request_id, degree_of_success="success")

    assert _satisfied(db_connection, f.connection_id, result_id) is False


def test_a_check_of_the_wrong_kind_does_not_satisfy_the_requirement(
    db_connection: Connection, f: Fixture
) -> None:
    f.make_conditional(
        db_connection,
        required_check_kind="skill_check",
        required_skill_id=f.skill_id,
        required_difficulty=15,
    )
    request_id = make_check_request(
        db_connection,
        f.action_id,
        f.actor_id,
        check_kind="ability_check",
        ability_id=f.ability_id,
        difficulty=15,
        target_id=f.target_id,
    )
    result_id = make_check_result(db_connection, request_id, degree_of_success="success")

    assert _satisfied(db_connection, f.connection_id, result_id) is False


def test_a_successful_check_with_no_target_does_not_satisfy_the_requirement(
    db_connection: Connection, f: Fixture
) -> None:
    f.make_conditional(
        db_connection,
        required_check_kind="skill_check",
        required_skill_id=f.skill_id,
        required_difficulty=15,
    )
    request_id = make_check_request(
        db_connection,
        f.action_id,
        f.actor_id,
        check_kind="skill_check",
        skill_id=f.skill_id,
        difficulty=15,
    )
    result_id = make_check_result(db_connection, request_id, degree_of_success="success")

    assert _satisfied(db_connection, f.connection_id, result_id) is False


def test_a_successful_check_targeting_a_different_connection_does_not_satisfy_it(
    db_connection: Connection, f: Fixture
) -> None:
    other_connection = make_area_connection(db_connection, f.area_b, f.area_a)
    db_connection.execute(
        text(
            "UPDATE world.area_connections SET is_conditional = true, "
            "condition_description = 'requires a check', required_check_kind = 'skill_check', "
            "required_skill_id = :s, required_difficulty = 15 WHERE area_connection_id = :c"
        ),
        {"s": f.skill_id, "c": other_connection},
    )
    f.make_conditional(
        db_connection,
        required_check_kind="skill_check",
        required_skill_id=f.skill_id,
        required_difficulty=15,
    )

    other_target = make_target(
        db_connection, f.action_id, target_area_connection_id=other_connection
    )
    request_id = make_check_request(
        db_connection,
        f.action_id,
        f.actor_id,
        check_kind="skill_check",
        skill_id=f.skill_id,
        difficulty=15,
        target_id=other_target,
    )
    result_id = make_check_result(db_connection, request_id, degree_of_success="success")

    # Satisfies the OTHER connection's requirement, not f.connection_id's.
    assert _satisfied(db_connection, other_connection, result_id) is True
    assert _satisfied(db_connection, f.connection_id, result_id) is False
