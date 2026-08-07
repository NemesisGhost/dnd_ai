"""World-ruleset allow-list dependency protection and its concurrency
safety (revisions 031, 035, 068).

Split from test_phase4_remaining_issues.py (DEVELOPMENT.md §2.1): removing
or repointing a world's allowed ruleset must be rejected while any
species/build/condition/resource/language depends on it, including under
concurrent creation racing the removal. Revision 068 (a Phase 6 exit-review
correction) closed the last two gaps in this list: an interaction check
request's ability/skill, and a conditional route's required ability/skill.
"""

import threading
import time
import uuid

import pytest
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import IntegrityError, InternalError, ProgrammingError

from tests.factories import (
    current_ruleset_version_id,
    make_ability,
    make_action,
    make_area_connection,
    make_bare_ruleset,
    make_campaign,
    make_character,
    make_dungeon,
    make_dungeon_area,
    make_interaction,
    make_ruleset_for_world,
    make_skill,
    make_timeline,
    make_world,
    make_world_time,
)

pytestmark = pytest.mark.database

CONSTRAINT_ERRORS = (IntegrityError, InternalError, ProgrammingError)


class AllowListFixture:
    """A world with one allowed (non-default) ruleset, ready to attach a
    species/build/condition/resource dependency to before removing it."""

    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.ruleset_id = make_ruleset_for_world(
            connection, self.world_id, code=f"allowlist_{slug.replace('-', '_')}", is_default=False
        )
        self.version_id = current_ruleset_version_id(connection, self.ruleset_id)

    def delete(self, connection: Connection) -> None:
        connection.execute(
            text("DELETE FROM rules.world_rulesets WHERE world_id = :w AND ruleset_id = :r"),
            {"w": self.world_id, "r": self.ruleset_id},
        )


@pytest.fixture
def alf(db_connection: Connection) -> AllowListFixture:
    return AllowListFixture(db_connection, f"allowlist-{uuid.uuid4().hex[:6]}")


def test_removing_a_ruleset_a_characters_species_depends_on_is_rejected(
    db_connection: Connection, alf: AllowListFixture
) -> None:
    species = db_connection.execute(
        text(
            "INSERT INTO rules.species (ruleset_version_id, code, display_name) "
            "VALUES (:v, 'human', 'Human') RETURNING species_id"
        ),
        {"v": alf.version_id},
    ).scalar()
    make_character(db_connection, alf.world_id, species_id=species)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        alf.delete(db_connection)
    assert "species from it" in str(exc.value)


def test_removing_a_ruleset_a_character_builds_version_depends_on_is_rejected(
    db_connection: Connection, alf: AllowListFixture
) -> None:
    character_id = make_character(db_connection, alf.world_id)
    db_connection.execute(
        text(
            "INSERT INTO character.character_builds (character_id, ruleset_version_id) "
            "VALUES (:c, :v)"
        ),
        {"c": character_id, "v": alf.version_id},
    )

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        alf.delete(db_connection)
    assert "character build" in str(exc.value)


def test_removing_a_ruleset_an_applied_condition_depends_on_is_rejected(
    db_connection: Connection, alf: AllowListFixture
) -> None:
    timeline_id = make_timeline(db_connection, alf.world_id, is_primary=True)
    character_id = make_character(db_connection, alf.world_id)
    condition = db_connection.execute(
        text(
            "INSERT INTO rules.conditions (ruleset_version_id, code, display_name) "
            "VALUES (:v, 'poisoned', 'Poisoned') RETURNING condition_id"
        ),
        {"v": alf.version_id},
    ).scalar()
    db_connection.execute(
        text(
            "INSERT INTO campaign.character_conditions (timeline_id, character_id, condition_id) "
            "VALUES (:t, :c, :cond)"
        ),
        {"t": timeline_id, "c": character_id, "cond": condition},
    )

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        alf.delete(db_connection)
    assert "applied character condition" in str(exc.value)


def test_removing_a_ruleset_a_tracked_resource_depends_on_is_rejected(
    db_connection: Connection, alf: AllowListFixture
) -> None:
    timeline_id = make_timeline(db_connection, alf.world_id, is_primary=True)
    character_id = make_character(db_connection, alf.world_id)
    resource = db_connection.execute(
        text(
            "INSERT INTO rules.resource_definitions (ruleset_version_id, code, display_name) "
            "VALUES (:v, 'ki', 'Ki') RETURNING resource_definition_id"
        ),
        {"v": alf.version_id},
    ).scalar()
    db_connection.execute(
        text(
            "INSERT INTO campaign.character_resources "
            "(timeline_id, character_id, resource_definition_id, current_amount, maximum_amount) "
            "VALUES (:t, :c, :r, 3, 3)"
        ),
        {"t": timeline_id, "c": character_id, "r": resource},
    )

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        alf.delete(db_connection)
    assert "tracked character resource" in str(exc.value)


def test_repointing_an_unused_allowed_ruleset_actually_takes_effect(
    db_connection: Connection, alf: AllowListFixture
) -> None:
    """revision 027 always `RETURN OLD`, which silently cancelled a permitted
    UPDATE (a BEFORE UPDATE trigger's return value is what gets written).
    revision 031 returns NEW on UPDATE — the repoint must actually stick."""
    other_ruleset = make_bare_ruleset(db_connection, f"other_{uuid.uuid4().hex[:8]}")

    db_connection.execute(
        text(
            "UPDATE rules.world_rulesets SET ruleset_id = :new "
            "WHERE world_id = :w AND ruleset_id = :old"
        ),
        {"new": other_ruleset, "w": alf.world_id, "old": alf.ruleset_id},
    )

    current = db_connection.execute(
        text("SELECT ruleset_id FROM rules.world_rulesets WHERE world_id = :w"),
        {"w": alf.world_id},
    ).scalar()
    assert current == other_ruleset


def test_repointing_a_ruleset_still_in_use_is_rejected(
    db_connection: Connection, alf: AllowListFixture
) -> None:
    character_id = make_character(db_connection, alf.world_id)
    db_connection.execute(
        text(
            "INSERT INTO character.character_builds (character_id, ruleset_version_id) "
            "VALUES (:c, :v)"
        ),
        {"c": character_id, "v": alf.version_id},
    )
    other_ruleset = make_bare_ruleset(db_connection, f"other_used_{uuid.uuid4().hex[:8]}")

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "UPDATE rules.world_rulesets SET ruleset_id = :new "
                "WHERE world_id = :w AND ruleset_id = :old"
            ),
            {"new": other_ruleset, "w": alf.world_id, "old": alf.ruleset_id},
        )
    assert "character build" in str(exc.value)


def test_removing_a_ruleset_a_characters_language_depends_on_is_rejected(
    db_connection: Connection, alf: AllowListFixture
) -> None:
    character_id = make_character(db_connection, alf.world_id)
    language = db_connection.execute(
        text(
            "INSERT INTO rules.languages (ruleset_version_id, code, display_name) "
            "VALUES (:v, 'common', 'Common') RETURNING language_id"
        ),
        {"v": alf.version_id},
    ).scalar()
    db_connection.execute(
        text(
            "INSERT INTO character.character_languages (character_id, language_id) VALUES (:c, :l)"
        ),
        {"c": character_id, "l": language},
    )

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        alf.delete(db_connection)
    assert "language from it" in str(exc.value)


def test_repointing_a_ruleset_a_characters_language_depends_on_is_rejected(
    db_connection: Connection, alf: AllowListFixture
) -> None:
    character_id = make_character(db_connection, alf.world_id)
    language = db_connection.execute(
        text(
            "INSERT INTO rules.languages (ruleset_version_id, code, display_name) "
            "VALUES (:v, 'common', 'Common') RETURNING language_id"
        ),
        {"v": alf.version_id},
    ).scalar()
    db_connection.execute(
        text(
            "INSERT INTO character.character_languages (character_id, language_id) VALUES (:c, :l)"
        ),
        {"c": character_id, "l": language},
    )
    other_ruleset = make_bare_ruleset(db_connection, f"other_lang_used_{uuid.uuid4().hex[:8]}")

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "UPDATE rules.world_rulesets SET ruleset_id = :new "
                "WHERE world_id = :w AND ruleset_id = :old"
            ),
            {"new": other_ruleset, "w": alf.world_id, "old": alf.ruleset_id},
        )
    assert "language from it" in str(exc.value)


def test_removing_a_ruleset_a_check_requests_skill_depends_on_is_rejected(
    db_connection: Connection, alf: AllowListFixture
) -> None:
    ability = make_ability(db_connection, alf.version_id)
    skill = make_skill(db_connection, alf.version_id, ability)
    actor = make_character(db_connection, alf.world_id)
    timeline_id = make_timeline(db_connection, alf.world_id, is_primary=True)
    world_time_id = make_world_time(db_connection, alf.world_id, 100)
    interaction_id = make_interaction(db_connection, timeline_id, world_time_id)
    action_id = make_action(db_connection, interaction_id, actor)
    db_connection.execute(
        text(
            "INSERT INTO interaction.check_requests "
            "(action_id, actor_entity_id, check_kind, skill_id, difficulty) "
            "VALUES (:a, :actor, 'skill_check', :s, 10)"
        ),
        {"a": action_id, "actor": actor, "s": skill},
    )

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        alf.delete(db_connection)
    assert "check request" in str(exc.value)


def test_repointing_a_ruleset_a_check_requests_skill_depends_on_is_rejected(
    db_connection: Connection, alf: AllowListFixture
) -> None:
    ability = make_ability(db_connection, alf.version_id)
    skill = make_skill(db_connection, alf.version_id, ability)
    actor = make_character(db_connection, alf.world_id)
    timeline_id = make_timeline(db_connection, alf.world_id, is_primary=True)
    world_time_id = make_world_time(db_connection, alf.world_id, 100)
    interaction_id = make_interaction(db_connection, timeline_id, world_time_id)
    action_id = make_action(db_connection, interaction_id, actor)
    db_connection.execute(
        text(
            "INSERT INTO interaction.check_requests "
            "(action_id, actor_entity_id, check_kind, skill_id, difficulty) "
            "VALUES (:a, :actor, 'skill_check', :s, 10)"
        ),
        {"a": action_id, "actor": actor, "s": skill},
    )
    other_ruleset = make_bare_ruleset(db_connection, f"other_check_used_{uuid.uuid4().hex[:8]}")

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "UPDATE rules.world_rulesets SET ruleset_id = :new "
                "WHERE world_id = :w AND ruleset_id = :old"
            ),
            {"new": other_ruleset, "w": alf.world_id, "old": alf.ruleset_id},
        )
    assert "check request" in str(exc.value)


def test_removing_a_ruleset_a_conditional_routes_skill_depends_on_is_rejected(
    db_connection: Connection, alf: AllowListFixture
) -> None:
    ability = make_ability(db_connection, alf.version_id)
    skill = make_skill(db_connection, alf.version_id, ability)
    dungeon_id = make_dungeon(db_connection, alf.world_id)
    area_a = make_dungeon_area(db_connection, dungeon_id)
    area_b = make_dungeon_area(db_connection, dungeon_id)
    connection_id = make_area_connection(db_connection, area_a, area_b)
    db_connection.execute(
        text(
            "UPDATE world.area_connections SET is_conditional = true, "
            "condition_description = 'requires a check', required_check_kind = 'skill_check', "
            "required_skill_id = :s, required_difficulty = 10 WHERE area_connection_id = :c"
        ),
        {"s": skill, "c": connection_id},
    )

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        alf.delete(db_connection)
    assert "conditional route" in str(exc.value)


def test_repointing_a_ruleset_a_conditional_routes_skill_depends_on_is_rejected(
    db_connection: Connection, alf: AllowListFixture
) -> None:
    ability = make_ability(db_connection, alf.version_id)
    skill = make_skill(db_connection, alf.version_id, ability)
    dungeon_id = make_dungeon(db_connection, alf.world_id)
    area_a = make_dungeon_area(db_connection, dungeon_id)
    area_b = make_dungeon_area(db_connection, dungeon_id)
    connection_id = make_area_connection(db_connection, area_a, area_b)
    db_connection.execute(
        text(
            "UPDATE world.area_connections SET is_conditional = true, "
            "condition_description = 'requires a check', required_check_kind = 'skill_check', "
            "required_skill_id = :s, required_difficulty = 10 WHERE area_connection_id = :c"
        ),
        {"s": skill, "c": connection_id},
    )
    other_ruleset = make_bare_ruleset(db_connection, f"other_route_used_{uuid.uuid4().hex[:8]}")

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "UPDATE rules.world_rulesets SET ruleset_id = :new "
                "WHERE world_id = :w AND ruleset_id = :old"
            ),
            {"new": other_ruleset, "w": alf.world_id, "old": alf.ruleset_id},
        )
    assert "conditional route" in str(exc.value)


class ConcurrencyWorld:
    """A world with one ruleset allowed (not default) and a timeline/character
    ready to attach a build/condition/resource/campaign dependency to.
    Committed, not rolled back — the tests using this own their teardown."""

    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.ruleset_id = make_ruleset_for_world(
            connection,
            self.world_id,
            code=f"concurrency_{slug.replace('-', '_')}",
            is_default=False,
        )
        self.version_id = current_ruleset_version_id(connection, self.ruleset_id)
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        self.character_id = make_character(connection, self.world_id)


def _cleanup_concurrency_world(engine: Engine, slug: str) -> None:
    with engine.begin() as cleanup:
        params = {
            "s": slug,
            "ruleset_code": f"concurrency_{slug.replace('-', '_')}%",
        }
        for statement in (
            """DELETE FROM campaign.character_resources WHERE timeline_id IN (
                SELECT timeline_id FROM campaign.timelines
                WHERE world_id IN (SELECT world_id FROM core.worlds WHERE slug = :s)
            )""",
            """DELETE FROM campaign.character_conditions WHERE timeline_id IN (
                SELECT timeline_id FROM campaign.timelines
                WHERE world_id IN (SELECT world_id FROM core.worlds WHERE slug = :s)
            )""",
            """DELETE FROM campaign.campaigns WHERE timeline_id IN (
                SELECT timeline_id FROM campaign.timelines
                WHERE world_id IN (SELECT world_id FROM core.worlds WHERE slug = :s)
            )""",
            """DELETE FROM character.character_builds WHERE character_id IN (
                SELECT entity_id FROM core.entities
                WHERE world_id IN (SELECT world_id FROM core.worlds WHERE slug = :s)
            )""",
            """DELETE FROM character.characters WHERE character_id IN (
                SELECT entity_id FROM core.entities
                WHERE world_id IN (SELECT world_id FROM core.worlds WHERE slug = :s)
            )""",
            """DELETE FROM campaign.timelines
               WHERE world_id IN (SELECT world_id FROM core.worlds WHERE slug = :s)""",
            """DELETE FROM core.entities
               WHERE world_id IN (SELECT world_id FROM core.worlds WHERE slug = :s)""",
            """DELETE FROM rules.world_rulesets
               WHERE world_id IN (SELECT world_id FROM core.worlds WHERE slug = :s)""",
            """DELETE FROM rules.ruleset_versions WHERE ruleset_id IN (
                SELECT ruleset_id FROM rules.rulesets
                WHERE code LIKE :ruleset_code
            )""",
            "DELETE FROM rules.rulesets WHERE code LIKE :ruleset_code",
            "DELETE FROM core.worlds WHERE slug = :s",
        ):
            cleanup.execute(text(statement), params)


def _assert_delete_races_dependent_creation(
    engine: Engine,
    world_id: uuid.UUID,
    ruleset_id: uuid.UUID,
    create_dependent: object,
    expected_message: str,
) -> None:
    """The shared race proof: a dependent-creating transaction takes the
    FOR SHARE lock (revision 035) before committing; a concurrent DELETE of
    the association must block behind it, then — once unblocked by the
    dependent's commit — must be rejected outright by the pre-existing
    still-in-use check (revision 031), never silently succeed alongside it."""
    with engine.connect() as first, engine.connect() as second:
        first.begin()
        second.begin()

        create_dependent(first)

        second.execute(text("SET LOCAL lock_timeout = '2s'"))
        with pytest.raises(Exception) as exc:
            second.execute(
                text("DELETE FROM rules.world_rulesets WHERE world_id = :w AND ruleset_id = :r"),
                {"w": world_id, "r": ruleset_id},
            )
            second.commit()
        message = str(exc.value)
        assert "lock_timeout" in message or "canceling statement" in message, (
            f"expected the delete to block on the dependent-creator's FOR SHARE lock, "
            f"got: {message}"
        )
        second.rollback()

        first.commit()

        with engine.begin() as third:
            with pytest.raises(CONSTRAINT_ERRORS) as exc2:
                third.execute(
                    text(
                        "DELETE FROM rules.world_rulesets WHERE world_id = :w AND ruleset_id = :r"
                    ),
                    {"w": world_id, "r": ruleset_id},
                )
            assert expected_message in str(exc2.value)


def test_concurrent_species_creation_blocks_a_concurrent_removal(
    postgres_engine: Engine,
) -> None:
    engine = postgres_engine
    slug = f"conc-species-{uuid.uuid4().hex[:8]}"
    try:
        with engine.begin() as setup:
            cw = ConcurrencyWorld(setup, slug)

        def create(conn: Connection) -> None:
            species = conn.execute(
                text(
                    "INSERT INTO rules.species (ruleset_version_id, code, display_name) "
                    "VALUES (:v, 'human', 'Human') RETURNING species_id"
                ),
                {"v": cw.version_id},
            ).scalar()
            make_character(conn, cw.world_id, species_id=species)

        _assert_delete_races_dependent_creation(
            engine, cw.world_id, cw.ruleset_id, create, "species from it"
        )
    finally:
        _cleanup_concurrency_world(engine, slug)


def test_concurrent_build_creation_blocks_a_concurrent_removal(postgres_engine: Engine) -> None:
    engine = postgres_engine
    slug = f"conc-build-{uuid.uuid4().hex[:8]}"
    try:
        with engine.begin() as setup:
            cw = ConcurrencyWorld(setup, slug)

        def create(conn: Connection) -> None:
            conn.execute(
                text(
                    "INSERT INTO character.character_builds (character_id, ruleset_version_id) "
                    "VALUES (:c, :v)"
                ),
                {"c": cw.character_id, "v": cw.version_id},
            )

        _assert_delete_races_dependent_creation(
            engine, cw.world_id, cw.ruleset_id, create, "character build"
        )
    finally:
        _cleanup_concurrency_world(engine, slug)


def test_concurrent_condition_creation_blocks_a_concurrent_removal(
    postgres_engine: Engine,
) -> None:
    engine = postgres_engine
    slug = f"conc-condition-{uuid.uuid4().hex[:8]}"
    try:
        with engine.begin() as setup:
            cw = ConcurrencyWorld(setup, slug)
            condition_id = setup.execute(
                text(
                    "INSERT INTO rules.conditions (ruleset_version_id, code, display_name) "
                    "VALUES (:v, 'poisoned', 'Poisoned') RETURNING condition_id"
                ),
                {"v": cw.version_id},
            ).scalar()

        def create(conn: Connection) -> None:
            conn.execute(
                text(
                    "INSERT INTO campaign.character_conditions "
                    "(timeline_id, character_id, condition_id) VALUES (:t, :c, :cond)"
                ),
                {"t": cw.timeline_id, "c": cw.character_id, "cond": condition_id},
            )

        _assert_delete_races_dependent_creation(
            engine, cw.world_id, cw.ruleset_id, create, "applied character condition"
        )
    finally:
        _cleanup_concurrency_world(engine, slug)


def test_concurrent_resource_creation_blocks_a_concurrent_removal(
    postgres_engine: Engine,
) -> None:
    engine = postgres_engine
    slug = f"conc-resource-{uuid.uuid4().hex[:8]}"
    try:
        with engine.begin() as setup:
            cw = ConcurrencyWorld(setup, slug)
            resource_id = setup.execute(
                text(
                    "INSERT INTO rules.resource_definitions (ruleset_version_id, code, display_name) "
                    "VALUES (:v, 'ki', 'Ki') RETURNING resource_definition_id"
                ),
                {"v": cw.version_id},
            ).scalar()

        def create(conn: Connection) -> None:
            conn.execute(
                text(
                    "INSERT INTO campaign.character_resources "
                    "(timeline_id, character_id, resource_definition_id, current_amount, "
                    "maximum_amount) VALUES (:t, :c, :r, 3, 3)"
                ),
                {"t": cw.timeline_id, "c": cw.character_id, "r": resource_id},
            )

        _assert_delete_races_dependent_creation(
            engine, cw.world_id, cw.ruleset_id, create, "tracked character resource"
        )
    finally:
        _cleanup_concurrency_world(engine, slug)


def test_concurrent_campaign_creation_blocks_a_concurrent_removal(postgres_engine: Engine) -> None:
    engine = postgres_engine
    slug = f"conc-campaign-{uuid.uuid4().hex[:8]}"
    try:
        with engine.begin() as setup:
            cw = ConcurrencyWorld(setup, slug)

        def create(conn: Connection) -> None:
            make_campaign(conn, cw.timeline_id, ruleset_version_id=cw.version_id)

        _assert_delete_races_dependent_creation(
            engine, cw.world_id, cw.ruleset_id, create, "still pinned to a version of it"
        )
    finally:
        _cleanup_concurrency_world(engine, slug)


def test_concurrent_world_default_assignment_blocks_a_concurrent_removal(
    postgres_engine: Engine,
) -> None:
    engine = postgres_engine
    slug = f"conc-default-{uuid.uuid4().hex[:8]}"
    try:
        with engine.begin() as setup:
            cw = ConcurrencyWorld(setup, slug)

        def create(conn: Connection) -> None:
            conn.execute(
                text("UPDATE core.worlds SET default_ruleset_id = :r WHERE world_id = :w"),
                {"r": cw.ruleset_id, "w": cw.world_id},
            )

        _assert_delete_races_dependent_creation(
            engine, cw.world_id, cw.ruleset_id, create, "is that world's default"
        )
    finally:
        with engine.begin() as reset:
            reset.execute(
                text("UPDATE core.worlds SET default_ruleset_id = NULL WHERE slug = :s"),
                {"s": slug},
            )
        _cleanup_concurrency_world(engine, slug)


def test_concurrent_language_creation_blocks_a_concurrent_removal(postgres_engine: Engine) -> None:
    engine = postgres_engine
    slug = f"conc-language-{uuid.uuid4().hex[:8]}"
    try:
        with engine.begin() as setup:
            cw = ConcurrencyWorld(setup, slug)
            language_id = setup.execute(
                text(
                    "INSERT INTO rules.languages (ruleset_version_id, code, display_name) "
                    "VALUES (:v, 'common', 'Common') RETURNING language_id"
                ),
                {"v": cw.version_id},
            ).scalar()

        def create(conn: Connection) -> None:
            conn.execute(
                text(
                    "INSERT INTO character.character_languages (character_id, language_id) "
                    "VALUES (:c, :l)"
                ),
                {"c": cw.character_id, "l": language_id},
            )

        _assert_delete_races_dependent_creation(
            engine, cw.world_id, cw.ruleset_id, create, "language from it"
        )
    finally:
        _cleanup_concurrency_world(engine, slug)


def test_concurrent_build_creation_blocks_a_concurrent_repoint(postgres_engine: Engine) -> None:
    """The same FOR SHARE lock protects an UPDATE-based repoint of the
    association, not just a DELETE — revision 031's trigger fires on both."""
    engine = postgres_engine
    slug = f"conc-repoint-{uuid.uuid4().hex[:8]}"
    try:
        with engine.begin() as setup:
            cw = ConcurrencyWorld(setup, slug)
            other_ruleset_id = make_bare_ruleset(
                setup, f"conc_repoint_target_{uuid.uuid4().hex[:8]}"
            )

        with engine.connect() as first, engine.connect() as second:
            first.begin()
            second.begin()

            first.execute(
                text(
                    "INSERT INTO character.character_builds (character_id, ruleset_version_id) "
                    "VALUES (:c, :v)"
                ),
                {"c": cw.character_id, "v": cw.version_id},
            )

            second.execute(text("SET LOCAL lock_timeout = '2s'"))
            with pytest.raises(Exception) as exc:
                second.execute(
                    text(
                        "UPDATE rules.world_rulesets SET ruleset_id = :new "
                        "WHERE world_id = :w AND ruleset_id = :old"
                    ),
                    {"new": other_ruleset_id, "w": cw.world_id, "old": cw.ruleset_id},
                )
                second.commit()
            message = str(exc.value)
            assert "lock_timeout" in message or "canceling statement" in message, (
                f"expected the repoint to block on the dependent-creator's FOR SHARE lock, "
                f"got: {message}"
            )
            second.rollback()

            first.commit()

            with engine.begin() as third:
                with pytest.raises(CONSTRAINT_ERRORS) as exc2:
                    third.execute(
                        text(
                            "UPDATE rules.world_rulesets SET ruleset_id = :new "
                            "WHERE world_id = :w AND ruleset_id = :old"
                        ),
                        {"new": other_ruleset_id, "w": cw.world_id, "old": cw.ruleset_id},
                    )
                assert "character build" in str(exc2.value)
    finally:
        with engine.begin() as cleanup:
            cleanup.execute(
                text("DELETE FROM rules.rulesets WHERE code LIKE 'conc_repoint_target_%'")
            )
        _cleanup_concurrency_world(engine, slug)


def test_concurrent_language_creation_blocks_a_concurrent_repoint(
    postgres_engine: Engine,
) -> None:
    """Character-language creation takes the same shared allow-list lock for
    an UPDATE-based repoint that the removal test proves for DELETE."""
    engine = postgres_engine
    slug = f"conc-lang-repoint-{uuid.uuid4().hex[:8]}"
    other_ruleset_id: uuid.UUID | None = None
    try:
        with engine.begin() as setup:
            cw = ConcurrencyWorld(setup, slug)
            other_ruleset_id = make_bare_ruleset(
                setup, f"conc_lang_repoint_target_{uuid.uuid4().hex[:8]}"
            )
            language_id = setup.execute(
                text(
                    "INSERT INTO rules.languages (ruleset_version_id, code, display_name) "
                    "VALUES (:v, 'common', 'Common') RETURNING language_id"
                ),
                {"v": cw.version_id},
            ).scalar()

        with engine.connect() as first, engine.connect() as second:
            first.begin()
            second.begin()

            first.execute(
                text(
                    "INSERT INTO character.character_languages (character_id, language_id) "
                    "VALUES (:c, :l)"
                ),
                {"c": cw.character_id, "l": language_id},
            )

            second.execute(text("SET LOCAL lock_timeout = '2s'"))
            with pytest.raises(Exception) as exc:
                second.execute(
                    text(
                        "UPDATE rules.world_rulesets SET ruleset_id = :new "
                        "WHERE world_id = :w AND ruleset_id = :old"
                    ),
                    {"new": other_ruleset_id, "w": cw.world_id, "old": cw.ruleset_id},
                )
                second.commit()
            message = str(exc.value)
            assert "lock_timeout" in message or "canceling statement" in message, (
                "expected the repoint to block on the character-language creator's "
                f"FOR SHARE lock, got: {message}"
            )
            second.rollback()

            first.commit()

            with engine.begin() as third:
                with pytest.raises(CONSTRAINT_ERRORS) as exc2:
                    third.execute(
                        text(
                            "UPDATE rules.world_rulesets SET ruleset_id = :new "
                            "WHERE world_id = :w AND ruleset_id = :old"
                        ),
                        {"new": other_ruleset_id, "w": cw.world_id, "old": cw.ruleset_id},
                    )
                assert "language from it" in str(exc2.value)
    finally:
        if other_ruleset_id is not None:
            with engine.begin() as cleanup:
                cleanup.execute(
                    text("DELETE FROM rules.rulesets WHERE ruleset_id = :r"),
                    {"r": other_ruleset_id},
                )
        _cleanup_concurrency_world(engine, slug)


def _assert_blocked_delete_resumes_and_is_rejected(
    engine: Engine,
    world_id: uuid.UUID,
    ruleset_id: uuid.UUID,
    create_dependent: object,
    expected_message: str,
) -> None:
    outcome: list[tuple[str, Exception | None]] = []
    backend_pid: list[int] = []

    def blocked_delete() -> None:
        with engine.connect() as second:
            second.begin()
            backend_pid.append(second.execute(text("SELECT pg_backend_pid()")).scalar())
            try:
                second.execute(
                    text(
                        "DELETE FROM rules.world_rulesets WHERE world_id = :w AND ruleset_id = :r"
                    ),
                    {"w": world_id, "r": ruleset_id},
                )
            except Exception as exc:  # noqa: BLE001 - reported to the main thread, not swallowed
                second.rollback()
                outcome.append(("failed", exc))
            else:
                second.commit()
                outcome.append(("committed", None))

    with engine.connect() as first:
        first.begin()
        create_dependent(first)

        thread = threading.Thread(target=blocked_delete)
        thread.start()

        deadline = time.monotonic() + 5.0
        while not backend_pid and time.monotonic() < deadline:
            time.sleep(0.05)
        assert backend_pid, "blocked DELETE thread never reported its backend pid"
        pid = backend_pid[0]

        waiting = False
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            wait_event_type = first.execute(
                text("SELECT wait_event_type FROM pg_stat_activity WHERE pid = :p"), {"p": pid}
            ).scalar()
            if wait_event_type == "Lock":
                waiting = True
                break
            time.sleep(0.05)
        assert waiting, (
            "expected the concurrent DELETE to be genuinely waiting on the "
            "dependent-creator's FOR SHARE lock before the creator commits"
        )

        first.commit()

        thread.join(timeout=10.0)
        assert not thread.is_alive(), (
            "the blocked DELETE did not resume within 10s of the creator's commit"
        )

    assert outcome, "blocked DELETE thread reported no outcome"
    result, exc = outcome[0]
    assert result == "failed", (
        f"expected the resumed DELETE to be rejected by the still-in-use check, got: {result}"
    )
    assert expected_message in str(exc)


def test_a_blocked_language_removal_resumes_and_is_rejected_once_the_creator_commits(
    postgres_engine: Engine,
) -> None:
    engine = postgres_engine
    slug = f"conc-lang-resume-{uuid.uuid4().hex[:8]}"
    try:
        with engine.begin() as setup:
            cw = ConcurrencyWorld(setup, slug)
            language_id = setup.execute(
                text(
                    "INSERT INTO rules.languages (ruleset_version_id, code, display_name) "
                    "VALUES (:v, 'common', 'Common') RETURNING language_id"
                ),
                {"v": cw.version_id},
            ).scalar()

        def create(conn: Connection) -> None:
            conn.execute(
                text(
                    "INSERT INTO character.character_languages (character_id, language_id) "
                    "VALUES (:c, :l)"
                ),
                {"c": cw.character_id, "l": language_id},
            )

        _assert_blocked_delete_resumes_and_is_rejected(
            engine, cw.world_id, cw.ruleset_id, create, "language from it"
        )
    finally:
        _cleanup_concurrency_world(engine, slug)
