"""Immutable identity and parent-scope columns (revisions 030, 033, 036).

Split from test_phase4_corrections.py and test_phase4_remaining_issues.py
(DEVELOPMENT.md §2.1): every column that identifies what a row *is* rather
than its current attributes (a world_time's world_id, a build's
ruleset_version_id, a feature's class_id, ...) and must never change after
insert, gathered into one topic file instead of two phase-oriented ones.
"""

import uuid

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError, InternalError, ProgrammingError

from tests.factories import (
    make_bare_ruleset,
    make_campaign,
    make_character,
    make_party,
    make_ruleset_version,
    make_ruleset_version_for_world,
    make_timeline,
    make_world,
    make_world_time,
)

pytestmark = pytest.mark.database

CONSTRAINT_ERRORS = (IntegrityError, InternalError, ProgrammingError)


@pytest.fixture
def world_id(db_connection: Connection) -> uuid.UUID:
    return make_world(db_connection, slug="immutable-identity-world")


@pytest.fixture
def campaign_id(db_connection: Connection, world_id: uuid.UUID) -> uuid.UUID:
    timeline_id = make_timeline(db_connection, world_id, is_primary=True)
    return make_campaign(db_connection, timeline_id)


def test_world_time_sort_key_is_immutable(db_connection: Connection, world_id: uuid.UUID) -> None:
    world_time_id = make_world_time(db_connection, world_id, 500)
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("UPDATE core.world_times SET sort_key = 501 WHERE world_time_id = :w"),
            {"w": world_time_id},
        )
    assert "immutable" in str(exc.value)


def test_world_time_world_id_is_immutable(db_connection: Connection, world_id: uuid.UUID) -> None:
    other_world = make_world(db_connection, slug="immutable-world-time-other")
    world_time_id = make_world_time(db_connection, world_id, 500)
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("UPDATE core.world_times SET world_id = :w WHERE world_time_id = :t"),
            {"w": other_world, "t": world_time_id},
        )
    assert "immutable" in str(exc.value)


def test_entity_world_id_is_immutable(db_connection: Connection, world_id: uuid.UUID) -> None:
    other_world = make_world(db_connection, slug="immutable-entity-other")
    character_id = make_character(db_connection, world_id)
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("UPDATE core.entities SET world_id = :w WHERE entity_id = :e"),
            {"w": other_world, "e": character_id},
        )
    assert "immutable" in str(exc.value)


def test_timeline_world_id_is_immutable(db_connection: Connection, world_id: uuid.UUID) -> None:
    other_world = make_world(db_connection, slug="immutable-timeline-other")
    timeline_id = make_timeline(db_connection, world_id, is_primary=True)
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("UPDATE campaign.timelines SET world_id = :w WHERE timeline_id = :t"),
            {"w": other_world, "t": timeline_id},
        )
    assert "immutable" in str(exc.value)


def test_party_world_id_is_immutable(db_connection: Connection, world_id: uuid.UUID) -> None:

    other_world = make_world(db_connection, slug="immutable-party-other")
    party_id = make_party(db_connection, world_id)
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("UPDATE campaign.parties SET world_id = :w WHERE party_id = :p"),
            {"w": other_world, "p": party_id},
        )
    assert "immutable" in str(exc.value)


def test_campaign_timeline_id_is_immutable(
    db_connection: Connection, world_id: uuid.UUID, campaign_id: uuid.UUID
) -> None:
    other_timeline = make_timeline(db_connection, world_id, name="Other")
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("UPDATE campaign.campaigns SET timeline_id = :t WHERE campaign_id = :c"),
            {"t": other_timeline, "c": campaign_id},
        )
    assert "immutable" in str(exc.value)


def test_unrelated_columns_remain_freely_updatable(
    db_connection: Connection, campaign_id: uuid.UUID
) -> None:
    """The immutability triggers are scoped to specific columns — everything
    else on the same rows still updates normally."""
    db_connection.execute(
        text("UPDATE campaign.campaigns SET name = 'Renamed' WHERE campaign_id = :c"),
        {"c": campaign_id},
    )
    name = db_connection.execute(
        text("SELECT name FROM campaign.campaigns WHERE campaign_id = :c"), {"c": campaign_id}
    ).scalar()
    assert name == "Renamed"


def _make_version_pair(connection: Connection, slug: str) -> tuple[uuid.UUID, uuid.UUID]:
    return (
        make_ruleset_version(connection, code=f"{slug}_a"),
        make_ruleset_version(connection, code=f"{slug}_b"),
    )


SIMPLE_RULESET_VERSION_TABLES = [
    (
        "abilities",
        "ability_id",
        "INSERT INTO rules.abilities (ruleset_version_id, code, display_name) "
        "VALUES (:v, 'strength', 'Strength') RETURNING ability_id",
    ),
    (
        "species",
        "species_id",
        "INSERT INTO rules.species (ruleset_version_id, code, display_name) "
        "VALUES (:v, 'human', 'Human') RETURNING species_id",
    ),
    (
        "damage_types",
        "damage_type_id",
        "INSERT INTO rules.damage_types (ruleset_version_id, code, display_name) "
        "VALUES (:v, 'fire', 'Fire') RETURNING damage_type_id",
    ),
    (
        "conditions",
        "condition_id",
        "INSERT INTO rules.conditions (ruleset_version_id, code, display_name) "
        "VALUES (:v, 'poisoned', 'Poisoned') RETURNING condition_id",
    ),
    (
        "resource_definitions",
        "resource_definition_id",
        "INSERT INTO rules.resource_definitions (ruleset_version_id, code, display_name) "
        "VALUES (:v, 'ki', 'Ki') RETURNING resource_definition_id",
    ),
    (
        "proficiency_types",
        "proficiency_type_id",
        "INSERT INTO rules.proficiency_types "
        "(ruleset_version_id, code, display_name, target_kind) "
        "VALUES (:v, 'weapon', 'Weapon', 'free_text') RETURNING proficiency_type_id",
    ),
]


@pytest.mark.parametrize("table, pk, insert_sql", SIMPLE_RULESET_VERSION_TABLES)
def test_ruleset_version_id_is_immutable_on_simple_content_tables(
    db_connection: Connection, table: str, pk: str, insert_sql: str
) -> None:
    version, other_version = _make_version_pair(db_connection, f"immut_{table}")
    row_id = db_connection.execute(text(insert_sql), {"v": version}).scalar()

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(f"UPDATE rules.{table} SET ruleset_version_id = :o WHERE {pk} = :id"),
            {"o": other_version, "id": row_id},
        )
    assert "immutable" in str(exc.value)


def test_ruleset_versions_ruleset_id_is_immutable(db_connection: Connection) -> None:
    ruleset_a = make_bare_ruleset(db_connection, f"immut_rv_a_{uuid.uuid4().hex[:8]}")
    ruleset_b = make_bare_ruleset(db_connection, f"immut_rv_b_{uuid.uuid4().hex[:8]}")
    version_id = db_connection.execute(
        text(
            "INSERT INTO rules.ruleset_versions (ruleset_id, version_label) "
            "VALUES (:r, 'v1') RETURNING ruleset_version_id"
        ),
        {"r": ruleset_a},
    ).scalar()

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("UPDATE rules.ruleset_versions SET ruleset_id = :b WHERE ruleset_version_id = :v"),
            {"b": ruleset_b, "v": version_id},
        )
    assert "immutable" in str(exc.value)


def test_skills_ruleset_version_id_is_immutable(db_connection: Connection) -> None:
    version, other_version = _make_version_pair(db_connection, "immut_skills")
    ability = db_connection.execute(
        text(
            "INSERT INTO rules.abilities (ruleset_version_id, code, display_name) "
            "VALUES (:v, 'dexterity', 'Dexterity') RETURNING ability_id"
        ),
        {"v": version},
    ).scalar()
    other_ability = db_connection.execute(
        text(
            "INSERT INTO rules.abilities (ruleset_version_id, code, display_name) "
            "VALUES (:v, 'dexterity', 'Dexterity') RETURNING ability_id"
        ),
        {"v": other_version},
    ).scalar()
    skill = db_connection.execute(
        text(
            "INSERT INTO rules.skills (ruleset_version_id, ability_id, code, display_name) "
            "VALUES (:v, :a, 'stealth', 'Stealth') RETURNING skill_id"
        ),
        {"v": version, "a": ability},
    ).scalar()

    # ability_id is changed alongside ruleset_version_id, to an ability that
    # *does* belong to other_version — otherwise revision 014's own
    # self-consistency trigger (which fires first, alphabetically, for this
    # table) would reject the row for a different reason before this
    # migration's immutability trigger gets the chance to.
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "UPDATE rules.skills SET ruleset_version_id = :o, ability_id = :a "
                "WHERE skill_id = :s"
            ),
            {"o": other_version, "a": other_ability, "s": skill},
        )
    assert "immutable" in str(exc.value)


def test_classes_ruleset_version_id_is_immutable(db_connection: Connection) -> None:
    version, other_version = _make_version_pair(db_connection, "immut_classes")
    class_id = db_connection.execute(
        text(
            "INSERT INTO rules.classes (ruleset_version_id, code, display_name, hit_die) "
            "VALUES (:v, 'fighter', 'Fighter', 10) RETURNING class_id"
        ),
        {"v": version},
    ).scalar()

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("UPDATE rules.classes SET ruleset_version_id = :o WHERE class_id = :c"),
            {"o": other_version, "c": class_id},
        )
    assert "immutable" in str(exc.value)


def test_spells_ruleset_version_id_is_immutable(db_connection: Connection) -> None:
    version, other_version = _make_version_pair(db_connection, "immut_spells")
    spell_id = db_connection.execute(
        text(
            "INSERT INTO rules.spells (ruleset_version_id, code, display_name, level) "
            "VALUES (:v, 'fire_bolt', 'Fire Bolt', 0) RETURNING spell_id"
        ),
        {"v": version},
    ).scalar()

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("UPDATE rules.spells SET ruleset_version_id = :o WHERE spell_id = :s"),
            {"o": other_version, "s": spell_id},
        )
    assert "immutable" in str(exc.value)


def test_proficiency_types_target_kind_is_immutable(db_connection: Connection) -> None:
    version, _ = _make_version_pair(db_connection, "immut_proftype_kind")
    prof_type = db_connection.execute(
        text(
            "INSERT INTO rules.proficiency_types "
            "(ruleset_version_id, code, display_name, target_kind) "
            "VALUES (:v, 'skill', 'Skill', 'skill') RETURNING proficiency_type_id"
        ),
        {"v": version},
    ).scalar()

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "UPDATE rules.proficiency_types SET target_kind = 'saving_throw' "
                "WHERE proficiency_type_id = :p"
            ),
            {"p": prof_type},
        )
    assert "immutable" in str(exc.value)


class SubclassFixture:
    """Two ruleset versions, each with one class, ready to test subclasses'
    ruleset_version_id and class_id immutability independently."""

    def __init__(self, connection: Connection, slug: str) -> None:
        self.version, self.other_version = _make_version_pair(connection, slug)
        self.class_id = connection.execute(
            text(
                "INSERT INTO rules.classes (ruleset_version_id, code, display_name, hit_die) "
                "VALUES (:v, 'fighter', 'Fighter', 10) RETURNING class_id"
            ),
            {"v": self.version},
        ).scalar()
        self.other_class_id = connection.execute(
            text(
                "INSERT INTO rules.classes (ruleset_version_id, code, display_name, hit_die) "
                "VALUES (:v, 'other_fighter', 'Other Fighter', 10) RETURNING class_id"
            ),
            {"v": self.version},
        ).scalar()
        self.subclass_id = connection.execute(
            text(
                "INSERT INTO rules.subclasses (class_id, ruleset_version_id, code, display_name) "
                "VALUES (:cl, :v, 'champion', 'Champion') RETURNING subclass_id"
            ),
            {"cl": self.class_id, "v": self.version},
        ).scalar()


@pytest.fixture
def scf(db_connection: Connection) -> SubclassFixture:
    return SubclassFixture(db_connection, f"immut_subclass_{uuid.uuid4().hex[:6]}")


def test_subclasses_ruleset_version_id_is_immutable(
    db_connection: Connection, scf: SubclassFixture
) -> None:
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("UPDATE rules.subclasses SET ruleset_version_id = :o WHERE subclass_id = :s"),
            {"o": scf.other_version, "s": scf.subclass_id},
        )
    assert "immutable" in str(exc.value)


def test_subclasses_class_id_is_immutable(db_connection: Connection, scf: SubclassFixture) -> None:
    """Repointing a subclass to a different class in the *same* ruleset
    version would pass revision 015's own version-equality trigger, but
    would still silently invalidate any character_class_levels row that
    already asserted the subclass belonged to the original class."""
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("UPDATE rules.subclasses SET class_id = :o WHERE subclass_id = :s"),
            {"o": scf.other_class_id, "s": scf.subclass_id},
        )
    assert "immutable" in str(exc.value)


class FeatureFixture:
    """A feature with all three optional associations set, plus a second
    valid value for each to repoint to."""

    def __init__(self, connection: Connection, slug: str) -> None:
        self.version, self.other_version = _make_version_pair(connection, slug)
        self.class_id = connection.execute(
            text(
                "INSERT INTO rules.classes (ruleset_version_id, code, display_name, hit_die) "
                "VALUES (:v, 'fighter', 'Fighter', 10) RETURNING class_id"
            ),
            {"v": self.version},
        ).scalar()
        self.other_class_id = connection.execute(
            text(
                "INSERT INTO rules.classes (ruleset_version_id, code, display_name, hit_die) "
                "VALUES (:v, 'wizard', 'Wizard', 6) RETURNING class_id"
            ),
            {"v": self.version},
        ).scalar()
        self.subclass_id = connection.execute(
            text(
                "INSERT INTO rules.subclasses (class_id, ruleset_version_id, code, display_name) "
                "VALUES (:cl, :v, 'champion', 'Champion') RETURNING subclass_id"
            ),
            {"cl": self.class_id, "v": self.version},
        ).scalar()
        self.other_subclass_id = connection.execute(
            text(
                "INSERT INTO rules.subclasses (class_id, ruleset_version_id, code, display_name) "
                "VALUES (:cl, :v, 'battle_master', 'Battle Master') RETURNING subclass_id"
            ),
            {"cl": self.class_id, "v": self.version},
        ).scalar()
        self.species_id = connection.execute(
            text(
                "INSERT INTO rules.species (ruleset_version_id, code, display_name) "
                "VALUES (:v, 'human', 'Human') RETURNING species_id"
            ),
            {"v": self.version},
        ).scalar()
        self.other_species_id = connection.execute(
            text(
                "INSERT INTO rules.species (ruleset_version_id, code, display_name) "
                "VALUES (:v, 'elf', 'Elf') RETURNING species_id"
            ),
            {"v": self.version},
        ).scalar()
        self.feature_id = connection.execute(
            text(
                "INSERT INTO rules.features "
                "(ruleset_version_id, class_id, subclass_id, species_id, code, display_name) "
                "VALUES (:v, :cl, :sc, :sp, 'test_feature', 'Test Feature') "
                "RETURNING feature_id"
            ),
            {
                "v": self.version,
                "cl": self.class_id,
                "sc": self.subclass_id,
                "sp": self.species_id,
            },
        ).scalar()


@pytest.fixture
def ff(db_connection: Connection) -> FeatureFixture:
    return FeatureFixture(db_connection, f"immut_feature_{uuid.uuid4().hex[:6]}")


def test_features_ruleset_version_id_is_immutable(
    db_connection: Connection, ff: FeatureFixture
) -> None:
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("UPDATE rules.features SET ruleset_version_id = :o WHERE feature_id = :f"),
            {"o": ff.other_version, "f": ff.feature_id},
        )
    assert "immutable" in str(exc.value)


def test_features_class_id_is_immutable(db_connection: Connection, ff: FeatureFixture) -> None:
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("UPDATE rules.features SET class_id = :o WHERE feature_id = :f"),
            {"o": ff.other_class_id, "f": ff.feature_id},
        )
    assert "immutable" in str(exc.value)


def test_a_features_null_association_can_still_be_set_once(db_connection: Connection) -> None:
    """A NULL -> value transition is the column being set, not changed — the
    immutability guard only blocks overwriting an already-non-null value.
    Without this, revision 029's own add-column-then-backfill pattern for
    rules.proficiency_types.target_kind would be unable to run again."""
    version, _ = _make_version_pair(db_connection, "immut_feature_null_set")
    feature_id = db_connection.execute(
        text(
            "INSERT INTO rules.features (ruleset_version_id, code, display_name) "
            "VALUES (:v, 'classless_feature', 'Classless Feature') RETURNING feature_id"
        ),
        {"v": version},
    ).scalar()
    class_id = db_connection.execute(
        text(
            "INSERT INTO rules.classes (ruleset_version_id, code, display_name, hit_die) "
            "VALUES (:v, 'fighter', 'Fighter', 10) RETURNING class_id"
        ),
        {"v": version},
    ).scalar()

    db_connection.execute(
        text("UPDATE rules.features SET class_id = :c WHERE feature_id = :f"),
        {"c": class_id, "f": feature_id},
    )
    stored = db_connection.execute(
        text("SELECT class_id FROM rules.features WHERE feature_id = :f"), {"f": feature_id}
    ).scalar()
    assert stored == class_id

    other_class_id = db_connection.execute(
        text(
            "INSERT INTO rules.classes (ruleset_version_id, code, display_name, hit_die) "
            "VALUES (:v, 'wizard', 'Wizard', 6) RETURNING class_id"
        ),
        {"v": version},
    ).scalar()
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("UPDATE rules.features SET class_id = :o WHERE feature_id = :f"),
            {"o": other_class_id, "f": feature_id},
        )
    assert "immutable" in str(exc.value)


def test_features_subclass_id_is_immutable(db_connection: Connection, ff: FeatureFixture) -> None:
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("UPDATE rules.features SET subclass_id = :o WHERE feature_id = :f"),
            {"o": ff.other_subclass_id, "f": ff.feature_id},
        )
    assert "immutable" in str(exc.value)


def test_features_species_id_is_immutable(db_connection: Connection, ff: FeatureFixture) -> None:
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("UPDATE rules.features SET species_id = :o WHERE feature_id = :f"),
            {"o": ff.other_species_id, "f": ff.feature_id},
        )
    assert "immutable" in str(exc.value)


class ImmutableBuildFixture:
    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.version = make_ruleset_version_for_world(connection, self.world_id)
        self.other_version = make_ruleset_version_for_world(
            connection, self.world_id, code=f"other_{slug.replace('-', '_')}"
        )
        self.character_id = make_character(connection, self.world_id)
        self.other_character_id = make_character(connection, self.world_id)
        self.build_id = connection.execute(
            text(
                "INSERT INTO character.character_builds (character_id, ruleset_version_id) "
                "VALUES (:c, :v) RETURNING character_build_id"
            ),
            {"c": self.character_id, "v": self.version},
        ).scalar()


@pytest.fixture
def ibf(db_connection: Connection) -> ImmutableBuildFixture:
    return ImmutableBuildFixture(db_connection, f"immut-build-{uuid.uuid4().hex[:6]}")


def test_character_builds_character_id_is_immutable(
    db_connection: Connection, ibf: ImmutableBuildFixture
) -> None:
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "UPDATE character.character_builds SET character_id = :o "
                "WHERE character_build_id = :b"
            ),
            {"o": ibf.other_character_id, "b": ibf.build_id},
        )
    assert "immutable" in str(exc.value)


def test_character_builds_ruleset_version_id_is_immutable(
    db_connection: Connection, ibf: ImmutableBuildFixture
) -> None:
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "UPDATE character.character_builds SET ruleset_version_id = :o "
                "WHERE character_build_id = :b"
            ),
            {"o": ibf.other_version, "b": ibf.build_id},
        )
    assert "immutable" in str(exc.value)


def test_spellcasting_profiles_character_build_id_is_immutable(
    db_connection: Connection, ibf: ImmutableBuildFixture
) -> None:
    ability = db_connection.execute(
        text(
            "INSERT INTO rules.abilities (ruleset_version_id, code, display_name) "
            "VALUES (:v, 'intelligence', 'Intelligence') RETURNING ability_id"
        ),
        {"v": ibf.version},
    ).scalar()
    other_build_id = db_connection.execute(
        text(
            "INSERT INTO character.character_builds (character_id, ruleset_version_id) "
            "VALUES (:c, :v) RETURNING character_build_id"
        ),
        {"c": ibf.other_character_id, "v": ibf.version},
    ).scalar()
    profile_id = db_connection.execute(
        text(
            "INSERT INTO character.character_spellcasting_profiles "
            "(character_build_id, spellcasting_ability_id) VALUES (:b, :a) "
            "RETURNING character_spellcasting_profile_id"
        ),
        {"b": ibf.build_id, "a": ability},
    ).scalar()

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "UPDATE character.character_spellcasting_profiles SET character_build_id = :o "
                "WHERE character_spellcasting_profile_id = :p"
            ),
            {"o": other_build_id, "p": profile_id},
        )
    assert "immutable" in str(exc.value)


def test_unrelated_rule_content_columns_remain_freely_updatable(db_connection: Connection) -> None:
    """The new immutability triggers are scoped to specific columns —
    unrelated columns on the same rows, and associations that are not the
    parent side of a cross-version invariant, still update normally."""
    version, _ = _make_version_pair(db_connection, "immut_unrelated")
    class_id = db_connection.execute(
        text(
            "INSERT INTO rules.classes (ruleset_version_id, code, display_name, hit_die) "
            "VALUES (:v, 'fighter', 'Fighter', 10) RETURNING class_id"
        ),
        {"v": version},
    ).scalar()
    ability = db_connection.execute(
        text(
            "INSERT INTO rules.abilities (ruleset_version_id, code, display_name) "
            "VALUES (:v, 'strength', 'Strength') RETURNING ability_id"
        ),
        {"v": version},
    ).scalar()

    db_connection.execute(
        text(
            "UPDATE rules.classes SET display_name = 'Renamed', primary_ability_id = :a "
            "WHERE class_id = :c"
        ),
        {"a": ability, "c": class_id},
    )
    row = db_connection.execute(
        text("SELECT display_name, primary_ability_id FROM rules.classes WHERE class_id = :c"),
        {"c": class_id},
    ).one()
    assert row[0] == "Renamed"
    assert row[1] == ability


def test_creature_types_ruleset_version_id_is_immutable(db_connection: Connection) -> None:
    version, other_version = _make_version_pair(db_connection, "immut_creature_types")
    creature_type_id = db_connection.execute(
        text(
            "INSERT INTO rules.creature_types (ruleset_version_id, code, display_name) "
            "VALUES (:v, 'beast', 'Beast') RETURNING creature_type_id"
        ),
        {"v": version},
    ).scalar()

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "UPDATE rules.creature_types SET ruleset_version_id = :o "
                "WHERE creature_type_id = :c"
            ),
            {"o": other_version, "c": creature_type_id},
        )
    assert "immutable" in str(exc.value)


def test_languages_ruleset_version_id_is_immutable(db_connection: Connection) -> None:
    version, other_version = _make_version_pair(db_connection, "immut_languages")
    language_id = db_connection.execute(
        text(
            "INSERT INTO rules.languages (ruleset_version_id, code, display_name) "
            "VALUES (:v, 'common', 'Common') RETURNING language_id"
        ),
        {"v": version},
    ).scalar()

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("UPDATE rules.languages SET ruleset_version_id = :o WHERE language_id = :l"),
            {"o": other_version, "l": language_id},
        )
    assert "immutable" in str(exc.value)


def test_feats_ruleset_version_id_is_immutable(db_connection: Connection) -> None:
    version, other_version = _make_version_pair(db_connection, "immut_feats")
    feat_id = db_connection.execute(
        text(
            "INSERT INTO rules.feats (ruleset_version_id, code, display_name) "
            "VALUES (:v, 'alert', 'Alert') RETURNING feat_id"
        ),
        {"v": version},
    ).scalar()

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("UPDATE rules.feats SET ruleset_version_id = :o WHERE feat_id = :f"),
            {"o": other_version, "f": feat_id},
        )
    assert "immutable" in str(exc.value)


def test_every_rule_table_with_a_ruleset_version_id_column_protects_it(
    db_connection: Connection,
) -> None:
    """Table-driven, off the live schema rather than a hand-maintained list:
    every rules.* table with a ruleset_version_id column must have an
    immutability trigger covering it, so a future migration that adds a new
    ruleset-scoped rule-content table (as revision 033 itself did not, for
    creature_types/languages/feats) cannot silently omit this policy.

    Excludes rules.ruleset_versions itself: its ruleset_version_id is that
    row's own primary key (its identity), not a reference to a *different*
    ruleset version — the column this policy protects everywhere else. Its
    actual parent reference, ruleset_id, is checked separately below."""
    tables = (
        db_connection.execute(
            text(
                "SELECT table_name FROM information_schema.columns "
                "WHERE table_schema = 'rules' AND column_name = 'ruleset_version_id' "
                "AND table_name != 'ruleset_versions' "
                "ORDER BY table_name"
            )
        )
        .scalars()
        .all()
    )
    assert len(tables) >= 12, f"expected at least 12 ruleset-scoped rule tables, found: {tables}"

    for table in tables:
        trigger_defs = (
            db_connection.execute(
                text(
                    "SELECT pg_get_triggerdef(t.oid) FROM pg_trigger t "
                    "WHERE t.tgrelid = ('rules.' || :table)::regclass AND NOT t.tgisinternal"
                ),
                {"table": table},
            )
            .scalars()
            .all()
        )
        assert any(
            "enforce_immutable_columns" in d and "'ruleset_version_id'" in d for d in trigger_defs
        ), (
            f"rules.{table}.ruleset_version_id has no core.enforce_immutable_columns() trigger "
            f"covering it. Installed triggers: {trigger_defs}"
        )

    # rules.ruleset_versions was excluded above (its ruleset_version_id is
    # its own identity, not a parent reference) but its actual parent
    # reference, ruleset_id, must still be covered.
    ruleset_versions_triggers = (
        db_connection.execute(
            text(
                "SELECT pg_get_triggerdef(t.oid) FROM pg_trigger t "
                "WHERE t.tgrelid = 'rules.ruleset_versions'::regclass AND NOT t.tgisinternal"
            )
        )
        .scalars()
        .all()
    )
    assert any(
        "enforce_immutable_columns" in d and "'ruleset_id'" in d for d in ruleset_versions_triggers
    ), (
        "rules.ruleset_versions.ruleset_id has no core.enforce_immutable_columns() trigger "
        f"covering it. Installed triggers: {ruleset_versions_triggers}"
    )
