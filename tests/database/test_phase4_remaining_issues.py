"""Phase 4 closeout register (PHASE4_REMAINING_ISSUES.md, revisions 031-034).

Covers the seven items the corrections review left open after revision 030:
complete world-ruleset allow-list protection (§1, revision 031), proficiency-
type ruleset-version validation (§3, revision 032), rules-identity parent-
scope immutability (§2, revision 033), and the SQLAlchemy canon-status
default drift class (§4). §5 (ruleset-family/version separation) and §6/§7
(source-enforcement policy, CI cleanup) are data/docs/workflow changes with
no new trigger behavior to exercise here — see PHASE4_VERIFICATION.md.
"""

import uuid

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError, InternalError, ProgrammingError

from dnd_ai.persistence.tables import metadata
from tests.factories import (
    make_character,
    make_ruleset_version_for_world,
    make_timeline,
    make_world,
)

pytestmark = pytest.mark.database

CONSTRAINT_ERRORS = (IntegrityError, InternalError, ProgrammingError)


# ---------------------------------------------------------------------------
# §4: SQLAlchemy metadata server_default drift is now detectable
# ---------------------------------------------------------------------------
# alembic check does not compare server defaults (compare_server_default is
# off in env.py — see tables.py's _provenance_columns() docstring), so a
# metadata default that PostgreSQL would reject outright (like the bare
# subquery rules.rulesets.canon_status_id used to declare) is otherwise
# invisible to CI. This walks every column in the metadata with a text()
# server_default and asserts it matches what PostgreSQL actually stores for
# that column, catching this whole class of drift rather than just this one
# instance of it.


def _text_server_defaults() -> list[tuple[str, str, str, str]]:
    """(schema, table, column, declared default text) for every column in the
    metadata whose server_default is a text() clause. Skips columns whose
    server-side default is something else entirely (e.g. Identity()), which
    have no comparable literal text and are not this bug's shape."""
    out = []
    for table in metadata.tables.values():
        assert table.schema is not None, f"table {table.name} has no schema"
        for column in table.columns:
            default = column.server_default
            if default is None or not hasattr(default, "arg"):
                continue
            arg = default.arg
            if hasattr(arg, "text"):
                out.append((table.schema, table.name, column.name, arg.text))
    return out


@pytest.mark.parametrize("schema, table, column, declared", _text_server_defaults())
def test_metadata_server_default_matches_live_schema(
    db_connection: Connection, schema: str, table: str, column: str, declared: str
) -> None:
    actual = db_connection.execute(
        text(
            "SELECT column_default FROM information_schema.columns "
            "WHERE table_schema = :s AND table_name = :t AND column_name = :c"
        ),
        {"s": schema, "t": table, "c": column},
    ).scalar()
    assert actual == declared, (
        f"{schema}.{table}.{column}: tables.py declares default {declared!r}, "
        f"but the live schema has {actual!r} — PostgreSQL may have silently "
        f"rejected the declared form (e.g. a bare subquery is not a valid "
        f"column DEFAULT)."
    )


# ---------------------------------------------------------------------------
# §1: Complete world-ruleset allow-list protection (revision 031)
# ---------------------------------------------------------------------------


def _bare_ruleset(connection: Connection, code: str) -> uuid.UUID:
    return connection.execute(
        text(
            "INSERT INTO rules.rulesets (code, display_name) VALUES (:c, :c) RETURNING ruleset_id"
        ),
        {"c": code},
    ).scalar()


def _current_version(connection: Connection, ruleset_id: uuid.UUID) -> uuid.UUID:
    return connection.execute(
        text(
            "SELECT ruleset_version_id FROM rules.ruleset_versions "
            "WHERE ruleset_id = :r AND is_current"
        ),
        {"r": ruleset_id},
    ).scalar()


class AllowListFixture:
    """A world with one allowed (non-default) ruleset, ready to attach a
    species/build/condition/resource dependency to before removing it."""

    def __init__(self, connection: Connection, slug: str) -> None:
        from tests.factories import make_ruleset_for_world

        self.world_id = make_world(connection, slug=slug)
        self.ruleset_id = make_ruleset_for_world(
            connection, self.world_id, code=f"allowlist_{slug.replace('-', '_')}", is_default=False
        )
        self.version_id = _current_version(connection, self.ruleset_id)

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
    other_ruleset = _bare_ruleset(db_connection, f"other_{uuid.uuid4().hex[:8]}")

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
    other_ruleset = _bare_ruleset(db_connection, f"other_used_{uuid.uuid4().hex[:8]}")

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "UPDATE rules.world_rulesets SET ruleset_id = :new "
                "WHERE world_id = :w AND ruleset_id = :old"
            ),
            {"new": other_ruleset, "w": alf.world_id, "old": alf.ruleset_id},
        )
    assert "character build" in str(exc.value)


# ---------------------------------------------------------------------------
# §3: Proficiency-type ruleset version (revision 032)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# §2: Rules-identity parent-scope immutability (revision 033)
# ---------------------------------------------------------------------------


def _make_version_pair(connection: Connection, slug: str) -> tuple[uuid.UUID, uuid.UUID]:
    from tests.factories import make_ruleset_version

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
    ruleset_a = _bare_ruleset(db_connection, f"immut_rv_a_{uuid.uuid4().hex[:8]}")
    ruleset_b = _bare_ruleset(db_connection, f"immut_rv_b_{uuid.uuid4().hex[:8]}")
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
