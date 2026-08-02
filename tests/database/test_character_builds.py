"""character.character_builds and everything hanging off it (revision 020).

Covers: a build pins one ruleset version; ability scores and class levels
must agree with that version; multiclassing (more than one class per build);
a subclass must belong to its class; proficiencies name exactly one target;
spellcasting profiles and known/prepared spells.
"""

import uuid

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError, InternalError, ProgrammingError

from tests.factories import (
    make_character,
    make_ruleset_version,
    make_ruleset_version_for_world,
    make_species,
    make_world,
)

pytestmark = pytest.mark.database

CONSTRAINT_ERRORS = (IntegrityError, InternalError, ProgrammingError)


def _make_ability(connection: Connection, version: uuid.UUID, code: str) -> uuid.UUID:
    return connection.execute(
        text(
            "INSERT INTO rules.abilities (ruleset_version_id, code, display_name) "
            "VALUES (:v, :c, :c) RETURNING ability_id"
        ),
        {"v": version, "c": code},
    ).scalar()


def _make_class(
    connection: Connection, version: uuid.UUID, code: str, hit_die: int = 8
) -> uuid.UUID:
    return connection.execute(
        text(
            "INSERT INTO rules.classes (ruleset_version_id, code, display_name, hit_die) "
            "VALUES (:v, :c, :c, :h) RETURNING class_id"
        ),
        {"v": version, "c": code, "h": hit_die},
    ).scalar()


def _make_subclass(
    connection: Connection, class_id: uuid.UUID, version: uuid.UUID, code: str
) -> uuid.UUID:
    return connection.execute(
        text(
            "INSERT INTO rules.subclasses (class_id, ruleset_version_id, code, display_name) "
            "VALUES (:cl, :v, :c, :c) RETURNING subclass_id"
        ),
        {"cl": class_id, "v": version, "c": code},
    ).scalar()


def _make_proficiency_type(connection: Connection, version: uuid.UUID, code: str) -> uuid.UUID:
    """target_kind (revision 029) is derived from code the same way the seed
    migration's backfill did: skill/saving_throw name themselves, anything
    else (weapon, armor, tool, ...) is free_text."""
    target_kind = code if code in ("skill", "saving_throw") else "free_text"
    return connection.execute(
        text(
            "INSERT INTO rules.proficiency_types "
            "(ruleset_version_id, code, display_name, target_kind) "
            "VALUES (:v, :c, :c, :k) RETURNING proficiency_type_id"
        ),
        {"v": version, "c": code, "k": target_kind},
    ).scalar()


def _make_spell(connection: Connection, version: uuid.UUID, code: str, level: int = 0) -> uuid.UUID:
    return connection.execute(
        text(
            "INSERT INTO rules.spells (ruleset_version_id, code, display_name, level) "
            "VALUES (:v, :c, :c, :lvl) RETURNING spell_id"
        ),
        {"v": version, "c": code, "lvl": level},
    ).scalar()


class Fixture:
    """A world, a character, a ruleset version, and a build on it."""

    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.version = make_ruleset_version_for_world(connection, self.world_id)
        species = make_species(connection, self.version)
        self.character_id = make_character(connection, self.world_id, species_id=species)
        self.build_id = connection.execute(
            text(
                "INSERT INTO character.character_builds (character_id, ruleset_version_id) "
                "VALUES (:c, :v) RETURNING character_build_id"
            ),
            {"c": self.character_id, "v": self.version},
        ).scalar()


@pytest.fixture
def f(db_connection: Connection) -> Fixture:
    return Fixture(db_connection, "build-world")


# ---------------------------------------------------------------------------
# character_builds
# ---------------------------------------------------------------------------


def test_a_character_may_have_more_than_one_build(db_connection: Connection, f: Fixture) -> None:
    db_connection.execute(
        text(
            "INSERT INTO character.character_builds (character_id, ruleset_version_id, label) "
            "VALUES (:c, :v, 'v2')"
        ),
        {"c": f.character_id, "v": f.version},
    )

    count = db_connection.execute(
        text("SELECT count(*) FROM character.character_builds WHERE character_id = :c"),
        {"c": f.character_id},
    ).scalar()
    assert count == 2


def test_a_build_is_no_longer_globally_current(db_connection: Connection, f: Fixture) -> None:
    """Revision 028: active-build selection moved to timeline state
    (campaign.character_state.character_build_id) — character_builds no
    longer has an is_current column or a global uniqueness rule at all. Two
    builds for the same character coexist freely; see
    test_character_timeline_state.py for the timeline-scoped selection this
    replaced it with."""
    db_connection.execute(
        text(
            "INSERT INTO character.character_builds (character_id, ruleset_version_id) "
            "VALUES (:c, :v)"
        ),
        {"c": f.character_id, "v": f.version},
    )
    count = db_connection.execute(
        text("SELECT count(*) FROM character.character_builds WHERE character_id = :c"),
        {"c": f.character_id},
    ).scalar()
    assert count == 2

    columns = {
        r[0]
        for r in db_connection.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'character' AND table_name = 'character_builds'"
            )
        )
    }
    assert "is_current" not in columns


# ---------------------------------------------------------------------------
# character_ability_scores
# ---------------------------------------------------------------------------


def test_ability_score_must_match_the_builds_ruleset_version(
    db_connection: Connection, f: Fixture
) -> None:
    other_version = make_ruleset_version(db_connection)
    ability = _make_ability(db_connection, other_version, "strength")

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "INSERT INTO character.character_ability_scores "
                "(character_build_id, ability_id, score) VALUES (:b, :a, 16)"
            ),
            {"b": f.build_id, "a": ability},
        )
    assert "ruleset version" in str(exc.value)


def test_ability_score_in_the_right_version_succeeds(db_connection: Connection, f: Fixture) -> None:
    ability = _make_ability(db_connection, f.version, "strength")
    db_connection.execute(
        text(
            "INSERT INTO character.character_ability_scores "
            "(character_build_id, ability_id, score) VALUES (:b, :a, 16)"
        ),
        {"b": f.build_id, "a": ability},
    )


# ---------------------------------------------------------------------------
# character_class_levels — multiclassing and subclass consistency
# ---------------------------------------------------------------------------


def test_a_build_can_have_levels_in_more_than_one_class(
    db_connection: Connection, f: Fixture
) -> None:
    fighter = _make_class(db_connection, f.version, "fighter", hit_die=10)
    wizard = _make_class(db_connection, f.version, "wizard", hit_die=6)

    for class_id in (fighter, wizard):
        db_connection.execute(
            text(
                "INSERT INTO character.character_class_levels "
                "(character_build_id, class_id, level) VALUES (:b, :cl, 1)"
            ),
            {"b": f.build_id, "cl": class_id},
        )

    count = db_connection.execute(
        text("SELECT count(*) FROM character.character_class_levels WHERE character_build_id = :b"),
        {"b": f.build_id},
    ).scalar()
    assert count == 2


def test_class_level_must_match_the_builds_ruleset_version(
    db_connection: Connection, f: Fixture
) -> None:
    other_version = make_ruleset_version(db_connection)
    foreign_class = _make_class(db_connection, other_version, "foreign")

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "INSERT INTO character.character_class_levels "
                "(character_build_id, class_id, level) VALUES (:b, :cl, 1)"
            ),
            {"b": f.build_id, "cl": foreign_class},
        )
    assert "ruleset version" in str(exc.value)


def test_subclass_must_belong_to_the_class_it_is_attached_to(
    db_connection: Connection, f: Fixture
) -> None:
    fighter = _make_class(db_connection, f.version, "fighter", hit_die=10)
    wizard = _make_class(db_connection, f.version, "wizard", hit_die=6)
    evocation = _make_subclass(db_connection, wizard, f.version, "evocation")

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "INSERT INTO character.character_class_levels "
                "(character_build_id, class_id, subclass_id, level) VALUES (:b, :cl, :sc, 1)"
            ),
            {"b": f.build_id, "cl": fighter, "sc": evocation},
        )
    assert "belongs to class" in str(exc.value)


def test_subclass_matching_its_class_succeeds(db_connection: Connection, f: Fixture) -> None:
    fighter = _make_class(db_connection, f.version, "fighter", hit_die=10)
    champion = _make_subclass(db_connection, fighter, f.version, "champion")

    db_connection.execute(
        text(
            "INSERT INTO character.character_class_levels "
            "(character_build_id, class_id, subclass_id, level) VALUES (:b, :cl, :sc, 3)"
        ),
        {"b": f.build_id, "cl": fighter, "sc": champion},
    )


# ---------------------------------------------------------------------------
# character_proficiencies — exactly one target
# ---------------------------------------------------------------------------


def test_a_proficiency_naming_no_target_is_rejected(db_connection: Connection, f: Fixture) -> None:
    """Since revision 029, character.enforce_proficiency_target_kind() fires
    before ck_character_proficiencies_one_target ever gets evaluated — a
    proficiency_type_id always requires its specific target column, so a row
    naming none is rejected with a more specific message than the bare CHECK.
    test_a_proficiency_naming_two_targets_is_rejected below still exercises
    the CHECK directly, for the case the trigger does not cover."""
    prof_type = _make_proficiency_type(db_connection, f.version, "weapon")

    with pytest.raises(IntegrityError) as exc:
        db_connection.execute(
            text(
                "INSERT INTO character.character_proficiencies "
                "(character_build_id, proficiency_type_id) VALUES (:b, :t)"
            ),
            {"b": f.build_id, "t": prof_type},
        )
    assert "requires a free-text target" in str(exc.value)


def test_a_proficiency_naming_two_targets_is_rejected(
    db_connection: Connection, f: Fixture
) -> None:
    """A skill proficiency that also sets target_label satisfies
    enforce_proficiency_target_kind() (skill_id is present, as 'skill'
    requires) but still trips ck_character_proficiencies_one_target, since
    that CHECK counts every non-null target column, not just the required
    one."""
    prof_type = _make_proficiency_type(db_connection, f.version, "skill")
    skill = db_connection.execute(
        text(
            "INSERT INTO rules.skills (ruleset_version_id, ability_id, code, display_name) "
            "VALUES (:v, :a, 'stealth', 'Stealth') RETURNING skill_id"
        ),
        {"v": f.version, "a": _make_ability(db_connection, f.version, "dexterity")},
    ).scalar()

    with pytest.raises(IntegrityError) as exc:
        db_connection.execute(
            text(
                "INSERT INTO character.character_proficiencies "
                "(character_build_id, proficiency_type_id, skill_id, target_label) "
                "VALUES (:b, :t, :s, 'longsword')"
            ),
            {"b": f.build_id, "t": prof_type, "s": skill},
        )
    assert "ck_character_proficiencies_one_target" in str(exc.value)


def test_a_free_text_target_proficiency_succeeds(db_connection: Connection, f: Fixture) -> None:
    prof_type = _make_proficiency_type(db_connection, f.version, "weapon")
    db_connection.execute(
        text(
            "INSERT INTO character.character_proficiencies "
            "(character_build_id, proficiency_type_id, target_label) "
            "VALUES (:b, :t, 'longsword')"
        ),
        {"b": f.build_id, "t": prof_type},
    )


# ---------------------------------------------------------------------------
# spellcasting profiles and known/prepared spells
# ---------------------------------------------------------------------------


def test_a_build_may_have_at_most_one_spellcasting_profile_per_class(
    db_connection: Connection, f: Fixture
) -> None:
    wizard = _make_class(db_connection, f.version, "wizard", hit_die=6)
    ability = _make_ability(db_connection, f.version, "intelligence")

    db_connection.execute(
        text(
            "INSERT INTO character.character_spellcasting_profiles "
            "(character_build_id, class_id, spellcasting_ability_id) VALUES (:b, :cl, :a)"
        ),
        {"b": f.build_id, "cl": wizard, "a": ability},
    )
    with pytest.raises(IntegrityError) as exc:
        db_connection.execute(
            text(
                "INSERT INTO character.character_spellcasting_profiles "
                "(character_build_id, class_id, spellcasting_ability_id) VALUES (:b, :cl, :a)"
            ),
            {"b": f.build_id, "cl": wizard, "a": ability},
        )
    assert "ux_spellcasting_profiles_build_class" in str(exc.value)


def test_known_spells_need_not_be_prepared(db_connection: Connection, f: Fixture) -> None:
    """Known and prepared are independent associations — a Sorcerer-style
    caster knows spells without ever separately preparing them."""
    ability = _make_ability(db_connection, f.version, "charisma")
    profile_id = db_connection.execute(
        text(
            "INSERT INTO character.character_spellcasting_profiles "
            "(character_build_id, spellcasting_ability_id) VALUES (:b, :a) "
            "RETURNING character_spellcasting_profile_id"
        ),
        {"b": f.build_id, "a": ability},
    ).scalar()
    spell = _make_spell(db_connection, f.version, "fire_bolt")

    db_connection.execute(
        text(
            "INSERT INTO character.character_known_spells "
            "(character_spellcasting_profile_id, spell_id) VALUES (:p, :s)"
        ),
        {"p": profile_id, "s": spell},
    )

    prepared_count = db_connection.execute(
        text(
            "SELECT count(*) FROM character.character_prepared_spells "
            "WHERE character_spellcasting_profile_id = :p"
        ),
        {"p": profile_id},
    ).scalar()
    assert prepared_count == 0
