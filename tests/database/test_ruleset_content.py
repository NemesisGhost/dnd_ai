"""Ruleset content cross-references (revisions 014, 015).

Covers the guards that keep content within one ruleset version consistent:
a skill's governing ability, a subclass's class, and a feature's class/
subclass/species must all belong to the same ruleset version (or, for
subclass/feature associations, the correct parent row).
"""

import uuid

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError, InternalError, ProgrammingError

from tests.factories import make_ruleset_version, make_species

pytestmark = pytest.mark.database

CONSTRAINT_ERRORS = (IntegrityError, InternalError, ProgrammingError)


def _make_ability(connection: Connection, ruleset_version_id: uuid.UUID, code: str) -> uuid.UUID:
    return connection.execute(
        text("""
            INSERT INTO rules.abilities (ruleset_version_id, code, display_name)
            VALUES (:v, :c, :c) RETURNING ability_id
        """),
        {"v": ruleset_version_id, "c": code},
    ).scalar()


def _make_class(
    connection: Connection, ruleset_version_id: uuid.UUID, code: str, hit_die: int = 8
) -> uuid.UUID:
    return connection.execute(
        text("""
            INSERT INTO rules.classes (ruleset_version_id, code, display_name, hit_die)
            VALUES (:v, :c, :c, :h) RETURNING class_id
        """),
        {"v": ruleset_version_id, "c": code, "h": hit_die},
    ).scalar()


def _make_subclass(connection: Connection, class_id: uuid.UUID, ruleset_version_id, code):
    return connection.execute(
        text("""
            INSERT INTO rules.subclasses (class_id, ruleset_version_id, code, display_name)
            VALUES (:cl, :v, :c, :c) RETURNING subclass_id
        """),
        {"cl": class_id, "v": ruleset_version_id, "c": code},
    ).scalar()


# ---------------------------------------------------------------------------
# rules.skills
# ---------------------------------------------------------------------------


def test_a_skill_and_its_ability_must_share_a_ruleset_version(db_connection: Connection) -> None:
    version_a = make_ruleset_version(db_connection)
    version_b = make_ruleset_version(db_connection)
    ability = _make_ability(db_connection, version_a, "dexterity")

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("""
                INSERT INTO rules.skills (ruleset_version_id, ability_id, code, display_name)
                VALUES (:v, :a, 'stealth', 'Stealth')
            """),
            {"v": version_b, "a": ability},
        )
    assert "ruleset version" in str(exc.value)


def test_a_skill_in_the_same_version_as_its_ability_succeeds(db_connection: Connection) -> None:
    version = make_ruleset_version(db_connection)
    ability = _make_ability(db_connection, version, "dexterity")

    db_connection.execute(
        text("""
            INSERT INTO rules.skills (ruleset_version_id, ability_id, code, display_name)
            VALUES (:v, :a, 'stealth', 'Stealth')
        """),
        {"v": version, "a": ability},
    )


# ---------------------------------------------------------------------------
# rules.subclasses
# ---------------------------------------------------------------------------


def test_a_subclass_and_its_class_must_share_a_ruleset_version(db_connection: Connection) -> None:
    version_a = make_ruleset_version(db_connection)
    version_b = make_ruleset_version(db_connection)
    class_id = _make_class(db_connection, version_a, "fighter")

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("""
                INSERT INTO rules.subclasses (class_id, ruleset_version_id, code, display_name)
                VALUES (:cl, :v, 'champion', 'Champion')
            """),
            {"cl": class_id, "v": version_b},
        )
    assert "ruleset version" in str(exc.value)


def test_two_classes_may_each_define_a_subclass_with_the_same_code(
    db_connection: Connection,
) -> None:
    version = make_ruleset_version(db_connection)
    fighter = _make_class(db_connection, version, "fighter")
    wizard = _make_class(db_connection, version, "wizard")

    _make_subclass(db_connection, fighter, version, "shared_code")
    _make_subclass(db_connection, wizard, version, "shared_code")


# ---------------------------------------------------------------------------
# rules.features
# ---------------------------------------------------------------------------


def test_a_feature_may_belong_to_a_class(db_connection: Connection) -> None:
    version = make_ruleset_version(db_connection)
    fighter = _make_class(db_connection, version, "fighter")

    db_connection.execute(
        text("""
            INSERT INTO rules.features (ruleset_version_id, class_id, code, display_name)
            VALUES (:v, :cl, 'second_wind', 'Second Wind')
        """),
        {"v": version, "cl": fighter},
    )


def test_a_feature_may_belong_to_a_species_with_no_level(db_connection: Connection) -> None:
    version = make_ruleset_version(db_connection)
    species = make_species(db_connection, version, code="elf")

    db_connection.execute(
        text("""
            INSERT INTO rules.features
                (ruleset_version_id, species_id, code, display_name, granted_at_level)
            VALUES (:v, :s, 'darkvision', 'Darkvision', NULL)
        """),
        {"v": version, "s": species},
    )


def test_a_feature_needs_no_class_subclass_or_species(db_connection: Connection) -> None:
    """The three associations are independently nullable, not required —
    a standalone feature (e.g. from a future feat-granted mechanism) is
    valid."""
    version = make_ruleset_version(db_connection)

    db_connection.execute(
        text("""
            INSERT INTO rules.features (ruleset_version_id, code, display_name)
            VALUES (:v, 'standalone', 'Standalone Feature')
        """),
        {"v": version},
    )


# ---------------------------------------------------------------------------
# rules.spells
# ---------------------------------------------------------------------------


def test_a_cantrip_is_level_zero(db_connection: Connection) -> None:
    version = make_ruleset_version(db_connection)

    db_connection.execute(
        text("""
            INSERT INTO rules.spells (ruleset_version_id, code, display_name, level)
            VALUES (:v, 'fire_bolt', 'Fire Bolt', 0)
        """),
        {"v": version},
    )


def test_a_spell_may_omit_its_damage_type(db_connection: Connection) -> None:
    """Not every spell deals typed damage (Cure Wounds, for instance)."""
    version = make_ruleset_version(db_connection)

    db_connection.execute(
        text("""
            INSERT INTO rules.spells (ruleset_version_id, code, display_name, level)
            VALUES (:v, 'cure_wounds', 'Cure Wounds', 1)
        """),
        {"v": version},
    )
