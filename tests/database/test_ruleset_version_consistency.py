"""Ruleset-version consistency across dependent rule content (revisions
026, 029, 030, 032).

Split from test_phase4_corrections.py and test_phase4_remaining_issues.py
(DEVELOPMENT.md §2.1): every place a piece of rule content, a character
build, or a proficiency must share its ruleset_version_id with what it
references, gathered into one topic file instead of two phase-oriented
ones.
"""

import uuid

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError, InternalError, ProgrammingError

from tests.factories import (
    make_character,
    make_ruleset_version_for_world,
    make_world,
)

pytestmark = pytest.mark.database

CONSTRAINT_ERRORS = (IntegrityError, InternalError, ProgrammingError)


class RulesFixture:
    """Two ruleset versions plus enough content in each to build cross-version
    mismatches: an ability, a class, a species, a damage type."""

    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.version = make_ruleset_version_for_world(connection, self.world_id)
        self.other_version = make_ruleset_version_for_world(
            connection, self.world_id, code=f"other_{slug.replace(chr(45), chr(95))}"
        )


@pytest.fixture
def rf(db_connection: Connection) -> RulesFixture:
    return RulesFixture(db_connection, f"rules-consistency-{uuid.uuid4().hex[:6]}")


def _ability(connection: Connection, version: uuid.UUID, code: str = "strength") -> uuid.UUID:
    return connection.execute(
        text(
            "INSERT INTO rules.abilities (ruleset_version_id, code, display_name) "
            "VALUES (:v, :c, :c) RETURNING ability_id"
        ),
        {"v": version, "c": code},
    ).scalar()


def _species(connection: Connection, version: uuid.UUID, code: str = "human") -> uuid.UUID:
    return connection.execute(
        text(
            "INSERT INTO rules.species (ruleset_version_id, code, display_name) "
            "VALUES (:v, :c, :c) RETURNING species_id"
        ),
        {"v": version, "c": code},
    ).scalar()


def _damage_type(connection: Connection, version: uuid.UUID, code: str = "fire") -> uuid.UUID:
    return connection.execute(
        text(
            "INSERT INTO rules.damage_types (ruleset_version_id, code, display_name) "
            "VALUES (:v, :c, :c) RETURNING damage_type_id"
        ),
        {"v": version, "c": code},
    ).scalar()


def _class(connection: Connection, version: uuid.UUID, code: str = "fighter") -> uuid.UUID:
    return connection.execute(
        text(
            "INSERT INTO rules.classes (ruleset_version_id, code, display_name, hit_die) "
            "VALUES (:v, :c, :c, 10) RETURNING class_id"
        ),
        {"v": version, "c": code},
    ).scalar()


def test_a_classs_primary_ability_must_share_its_ruleset_version(
    db_connection: Connection, rf: RulesFixture
) -> None:
    foreign_ability = _ability(db_connection, rf.other_version)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "INSERT INTO rules.classes "
                "(ruleset_version_id, code, display_name, hit_die, primary_ability_id) "
                "VALUES (:v, 'wizard', 'Wizard', 6, :a)"
            ),
            {"v": rf.version, "a": foreign_ability},
        )
    assert "primary ability" in str(exc.value)


def test_a_classs_primary_ability_in_the_same_version_succeeds(
    db_connection: Connection, rf: RulesFixture
) -> None:
    ability = _ability(db_connection, rf.version)
    db_connection.execute(
        text(
            "INSERT INTO rules.classes "
            "(ruleset_version_id, code, display_name, hit_die, primary_ability_id) "
            "VALUES (:v, 'wizard', 'Wizard', 6, :a)"
        ),
        {"v": rf.version, "a": ability},
    )


@pytest.mark.parametrize("association", ["class_id", "subclass_id", "species_id"])
def test_a_features_association_must_share_its_ruleset_version(
    db_connection: Connection, rf: RulesFixture, association: str
) -> None:
    if association == "class_id":
        foreign_id = _class(db_connection, rf.other_version)
    elif association == "species_id":
        foreign_id = _species(db_connection, rf.other_version)
    else:
        foreign_class = _class(db_connection, rf.other_version)
        foreign_id = db_connection.execute(
            text(
                "INSERT INTO rules.subclasses (class_id, ruleset_version_id, code, display_name) "
                "VALUES (:cl, :v, 'champion', 'Champion') RETURNING subclass_id"
            ),
            {"cl": foreign_class, "v": rf.other_version},
        ).scalar()

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                f"INSERT INTO rules.features (ruleset_version_id, {association}, code, display_name) "
                f"VALUES (:v, :fid, 'test_feature', 'Test Feature')"
            ),
            {"v": rf.version, "fid": foreign_id},
        )
    assert "ruleset version" in str(exc.value)


def test_a_spells_damage_type_must_share_its_ruleset_version(
    db_connection: Connection, rf: RulesFixture
) -> None:
    foreign_damage_type = _damage_type(db_connection, rf.other_version)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "INSERT INTO rules.spells "
                "(ruleset_version_id, code, display_name, level, damage_type_id) "
                "VALUES (:v, 'fireball', 'Fireball', 3, :d)"
            ),
            {"v": rf.version, "d": foreign_damage_type},
        )
    assert "ruleset version" in str(exc.value)


class BuildFixture:
    """A character and a build pinned to a world-tied ruleset version, ready
    to attach proficiencies/features/spellcasting to."""

    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.version = make_ruleset_version_for_world(connection, self.world_id)
        self.other_version = make_ruleset_version_for_world(
            connection, self.world_id, code=f"other_{slug.replace(chr(45), chr(95))}"
        )
        self.character_id = make_character(connection, self.world_id)
        self.build_id = connection.execute(
            text(
                "INSERT INTO character.character_builds (character_id, ruleset_version_id) "
                "VALUES (:c, :v) RETURNING character_build_id"
            ),
            {"c": self.character_id, "v": self.version},
        ).scalar()


@pytest.fixture
def bf(db_connection: Connection) -> BuildFixture:
    return BuildFixture(db_connection, f"build-consistency-{uuid.uuid4().hex[:6]}")


def test_a_proficiencys_skill_must_share_the_builds_ruleset_version(
    db_connection: Connection, bf: BuildFixture
) -> None:
    ability = _ability(db_connection, bf.other_version)
    foreign_skill = db_connection.execute(
        text(
            "INSERT INTO rules.skills (ruleset_version_id, ability_id, code, display_name) "
            "VALUES (:v, :a, 'stealth', 'Stealth') RETURNING skill_id"
        ),
        {"v": bf.other_version, "a": ability},
    ).scalar()
    prof_type = db_connection.execute(
        text(
            "INSERT INTO rules.proficiency_types "
            "(ruleset_version_id, code, display_name, target_kind) "
            "VALUES (:v, 'skill', 'Skill', 'skill') RETURNING proficiency_type_id"
        ),
        {"v": bf.version},
    ).scalar()

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "INSERT INTO character.character_proficiencies "
                "(character_build_id, proficiency_type_id, skill_id) VALUES (:b, :t, :s)"
            ),
            {"b": bf.build_id, "t": prof_type, "s": foreign_skill},
        )
    assert "ruleset version" in str(exc.value)


def test_a_features_grant_must_share_the_builds_ruleset_version(
    db_connection: Connection, bf: BuildFixture
) -> None:
    foreign_feature = db_connection.execute(
        text(
            "INSERT INTO rules.features (ruleset_version_id, code, display_name) "
            "VALUES (:v, 'foreign_feature', 'Foreign Feature') RETURNING feature_id"
        ),
        {"v": bf.other_version},
    ).scalar()

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "INSERT INTO character.character_features (character_build_id, feature_id) "
                "VALUES (:b, :f)"
            ),
            {"b": bf.build_id, "f": foreign_feature},
        )
    assert "ruleset version" in str(exc.value)


def test_a_spellcasting_profiles_class_must_share_the_builds_ruleset_version(
    db_connection: Connection, bf: BuildFixture
) -> None:
    foreign_class = _class(db_connection, bf.other_version, code="foreign_class")
    ability = _ability(db_connection, bf.version, code="intelligence")

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "INSERT INTO character.character_spellcasting_profiles "
                "(character_build_id, class_id, spellcasting_ability_id) VALUES (:b, :cl, :a)"
            ),
            {"b": bf.build_id, "cl": foreign_class, "a": ability},
        )
    assert "ruleset version" in str(exc.value)


def test_a_spellcasting_profiles_ability_must_share_the_builds_ruleset_version(
    db_connection: Connection, bf: BuildFixture
) -> None:
    foreign_ability = _ability(db_connection, bf.other_version, code="foreign_ability")

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "INSERT INTO character.character_spellcasting_profiles "
                "(character_build_id, spellcasting_ability_id) VALUES (:b, :a)"
            ),
            {"b": bf.build_id, "a": foreign_ability},
        )
    assert "ruleset version" in str(exc.value)


def test_a_known_spell_must_share_its_profiles_builds_ruleset_version(
    db_connection: Connection, bf: BuildFixture
) -> None:
    ability = _ability(db_connection, bf.version, code="intelligence")
    profile = db_connection.execute(
        text(
            "INSERT INTO character.character_spellcasting_profiles "
            "(character_build_id, spellcasting_ability_id) VALUES (:b, :a) "
            "RETURNING character_spellcasting_profile_id"
        ),
        {"b": bf.build_id, "a": ability},
    ).scalar()
    foreign_spell = db_connection.execute(
        text(
            "INSERT INTO rules.spells (ruleset_version_id, code, display_name, level) "
            "VALUES (:v, 'foreign_spell', 'Foreign Spell', 1) RETURNING spell_id"
        ),
        {"v": bf.other_version},
    ).scalar()

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "INSERT INTO character.character_known_spells "
                "(character_spellcasting_profile_id, spell_id) VALUES (:p, :s)"
            ),
            {"p": profile, "s": foreign_spell},
        )
    assert "ruleset version" in str(exc.value)


def test_a_prepared_spell_must_share_its_profiles_builds_ruleset_version(
    db_connection: Connection, bf: BuildFixture
) -> None:
    ability = _ability(db_connection, bf.version, code="intelligence")
    profile = db_connection.execute(
        text(
            "INSERT INTO character.character_spellcasting_profiles "
            "(character_build_id, spellcasting_ability_id) VALUES (:b, :a) "
            "RETURNING character_spellcasting_profile_id"
        ),
        {"b": bf.build_id, "a": ability},
    ).scalar()
    foreign_spell = db_connection.execute(
        text(
            "INSERT INTO rules.spells (ruleset_version_id, code, display_name, level) "
            "VALUES (:v, 'foreign_spell2', 'Foreign Spell 2', 1) RETURNING spell_id"
        ),
        {"v": bf.other_version},
    ).scalar()

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "INSERT INTO character.character_prepared_spells "
                "(character_spellcasting_profile_id, spell_id) VALUES (:p, :s)"
            ),
            {"p": profile, "s": foreign_spell},
        )
    assert "ruleset version" in str(exc.value)


def test_spell_code_must_be_snake_case(db_connection: Connection, rf: RulesFixture) -> None:
    with pytest.raises(IntegrityError) as exc:
        db_connection.execute(
            text(
                "INSERT INTO rules.spells (ruleset_version_id, code, display_name, level) "
                "VALUES (:v, 'Fire-Bolt', 'Fire Bolt', 0)"
            ),
            {"v": rf.version},
        )
    assert "ck_spells_code_format" in str(exc.value)


def test_a_build_cannot_be_granted_the_same_skill_proficiency_twice(
    db_connection: Connection, bf: BuildFixture
) -> None:
    ability = _ability(db_connection, bf.version, code="dexterity")
    skill = db_connection.execute(
        text(
            "INSERT INTO rules.skills (ruleset_version_id, ability_id, code, display_name) "
            "VALUES (:v, :a, 'stealth', 'Stealth') RETURNING skill_id"
        ),
        {"v": bf.version, "a": ability},
    ).scalar()
    prof_type = db_connection.execute(
        text(
            "INSERT INTO rules.proficiency_types "
            "(ruleset_version_id, code, display_name, target_kind) "
            "VALUES (:v, 'skill', 'Skill', 'skill') RETURNING proficiency_type_id"
        ),
        {"v": bf.version},
    ).scalar()
    db_connection.execute(
        text(
            "INSERT INTO character.character_proficiencies "
            "(character_build_id, proficiency_type_id, skill_id) VALUES (:b, :t, :s)"
        ),
        {"b": bf.build_id, "t": prof_type, "s": skill},
    )

    with pytest.raises(IntegrityError) as exc:
        db_connection.execute(
            text(
                "INSERT INTO character.character_proficiencies "
                "(character_build_id, proficiency_type_id, skill_id) VALUES (:b, :t, :s)"
            ),
            {"b": bf.build_id, "t": prof_type, "s": skill},
        )
    assert "ux_character_proficiencies_build_skill" in str(exc.value)


def test_a_build_cannot_be_granted_the_same_free_text_proficiency_twice(
    db_connection: Connection, bf: BuildFixture
) -> None:
    prof_type = db_connection.execute(
        text(
            "INSERT INTO rules.proficiency_types "
            "(ruleset_version_id, code, display_name, target_kind) "
            "VALUES (:v, 'weapon', 'Weapon', 'free_text') RETURNING proficiency_type_id"
        ),
        {"v": bf.version},
    ).scalar()
    db_connection.execute(
        text(
            "INSERT INTO character.character_proficiencies "
            "(character_build_id, proficiency_type_id, target_label) VALUES (:b, :t, 'longsword')"
        ),
        {"b": bf.build_id, "t": prof_type},
    )

    with pytest.raises(IntegrityError) as exc:
        db_connection.execute(
            text(
                "INSERT INTO character.character_proficiencies "
                "(character_build_id, proficiency_type_id, target_label) "
                "VALUES (:b, :t, 'longsword')"
            ),
            {"b": bf.build_id, "t": prof_type},
        )
    assert "ux_character_proficiencies_build_target_label" in str(exc.value)


def test_a_proficiency_of_the_wrong_kind_for_its_type_is_rejected(
    db_connection: Connection, bf: BuildFixture
) -> None:
    """proficiency_type_id='skill' requires skill_id — setting only
    target_label instead is rejected even though exactly one target column
    is set (ck_character_proficiencies_one_target alone would accept it)."""
    prof_type = db_connection.execute(
        text(
            "INSERT INTO rules.proficiency_types "
            "(ruleset_version_id, code, display_name, target_kind) "
            "VALUES (:v, 'skill', 'Skill', 'skill') RETURNING proficiency_type_id"
        ),
        {"v": bf.version},
    ).scalar()

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "INSERT INTO character.character_proficiencies "
                "(character_build_id, proficiency_type_id, target_label) "
                "VALUES (:b, :t, 'not-a-skill-id')"
            ),
            {"b": bf.build_id, "t": prof_type},
        )
    assert "requires a skill target" in str(exc.value)


def test_a_character_cannot_use_a_species_from_a_disallowed_ruleset(
    db_connection: Connection,
) -> None:
    world_id = make_world(db_connection, slug="species-disallowed-world")
    foreign_version = make_ruleset_version_for_world(
        db_connection, make_world(db_connection, slug="species-foreign-world")
    )
    species = _species(db_connection, foreign_version)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_character(db_connection, world_id, species_id=species)
    assert "not allowed for world" in str(exc.value)


def test_a_build_cannot_pin_a_disallowed_ruleset_version(db_connection: Connection) -> None:
    world_id = make_world(db_connection, slug="build-disallowed-world")
    character_id = make_character(db_connection, world_id)
    foreign_version = make_ruleset_version_for_world(
        db_connection, make_world(db_connection, slug="build-foreign-world")
    )

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "INSERT INTO character.character_builds (character_id, ruleset_version_id) "
                "VALUES (:c, :v)"
            ),
            {"c": character_id, "v": foreign_version},
        )
    assert "not allowed for world" in str(exc.value)


class ProficiencyBuildFixture:
    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.version = make_ruleset_version_for_world(connection, self.world_id)
        self.other_version = make_ruleset_version_for_world(
            connection, self.world_id, code=f"other_{slug.replace('-', '_')}"
        )
        self.character_id = make_character(connection, self.world_id)
        self.build_id = connection.execute(
            text(
                "INSERT INTO character.character_builds (character_id, ruleset_version_id) "
                "VALUES (:c, :v) RETURNING character_build_id"
            ),
            {"c": self.character_id, "v": self.version},
        ).scalar()


@pytest.fixture
def pbf(db_connection: Connection) -> ProficiencyBuildFixture:
    return ProficiencyBuildFixture(db_connection, f"prof-version-{uuid.uuid4().hex[:6]}")


def test_a_proficiencys_type_must_share_the_builds_ruleset_version(
    db_connection: Connection, pbf: ProficiencyBuildFixture
) -> None:
    foreign_type = db_connection.execute(
        text(
            "INSERT INTO rules.proficiency_types "
            "(ruleset_version_id, code, display_name, target_kind) "
            "VALUES (:v, 'weapon', 'Weapon', 'free_text') RETURNING proficiency_type_id"
        ),
        {"v": pbf.other_version},
    ).scalar()

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "INSERT INTO character.character_proficiencies "
                "(character_build_id, proficiency_type_id, target_label) "
                "VALUES (:b, :t, 'dagger')"
            ),
            {"b": pbf.build_id, "t": foreign_type},
        )
    assert "proficiency type" in str(exc.value)


def test_a_proficiencys_type_in_the_same_version_succeeds(
    db_connection: Connection, pbf: ProficiencyBuildFixture
) -> None:
    prof_type = db_connection.execute(
        text(
            "INSERT INTO rules.proficiency_types "
            "(ruleset_version_id, code, display_name, target_kind) "
            "VALUES (:v, 'weapon', 'Weapon', 'free_text') RETURNING proficiency_type_id"
        ),
        {"v": pbf.version},
    ).scalar()

    db_connection.execute(
        text(
            "INSERT INTO character.character_proficiencies "
            "(character_build_id, proficiency_type_id, target_label) "
            "VALUES (:b, :t, 'dagger')"
        ),
        {"b": pbf.build_id, "t": prof_type},
    )


def test_updating_a_proficiencys_type_to_a_different_version_is_rejected(
    db_connection: Connection, pbf: ProficiencyBuildFixture
) -> None:
    """revision 032 enforces the version check on UPDATE as well as INSERT —
    the closeout suite only proved the insert and same-version paths."""
    prof_type = db_connection.execute(
        text(
            "INSERT INTO rules.proficiency_types "
            "(ruleset_version_id, code, display_name, target_kind) "
            "VALUES (:v, 'weapon', 'Weapon', 'free_text') RETURNING proficiency_type_id"
        ),
        {"v": pbf.version},
    ).scalar()
    proficiency_id = db_connection.execute(
        text(
            "INSERT INTO character.character_proficiencies "
            "(character_build_id, proficiency_type_id, target_label) "
            "VALUES (:b, :t, 'dagger') RETURNING character_proficiency_id"
        ),
        {"b": pbf.build_id, "t": prof_type},
    ).scalar()

    foreign_type = db_connection.execute(
        text(
            "INSERT INTO rules.proficiency_types "
            "(ruleset_version_id, code, display_name, target_kind) "
            "VALUES (:v, 'armor', 'Armor', 'free_text') RETURNING proficiency_type_id"
        ),
        {"v": pbf.other_version},
    ).scalar()

    # A SAVEPOINT (begin_nested): the failed UPDATE aborts the current
    # transaction in PostgreSQL, which would poison every later statement on
    # this connection — including the very query below that proves the row
    # is unchanged — unless the failure is scoped to a sub-transaction that
    # rolls back on its own.
    with pytest.raises(CONSTRAINT_ERRORS) as exc, db_connection.begin_nested():
        db_connection.execute(
            text(
                "UPDATE character.character_proficiencies SET proficiency_type_id = :t "
                "WHERE character_proficiency_id = :p"
            ),
            {"t": foreign_type, "p": proficiency_id},
        )
    assert "proficiency type" in str(exc.value)

    unchanged = db_connection.execute(
        text(
            "SELECT proficiency_type_id FROM character.character_proficiencies "
            "WHERE character_proficiency_id = :p"
        ),
        {"p": proficiency_id},
    ).scalar()
    assert unchanged == prof_type, "the failed UPDATE must not have partially applied"
