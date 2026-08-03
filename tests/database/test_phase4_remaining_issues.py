"""Phase 4 closeout register (PHASE4_REMAINING_ISSUES.md, revisions 031-037).

Covers the seven items the corrections review left open after revision 030:
complete world-ruleset allow-list protection (§1, revision 031), proficiency-
type ruleset-version validation (§3, revision 032), rules-identity parent-
scope immutability (§2, revision 033), and the SQLAlchemy canon-status
default drift class (§4). §5 (ruleset-family/version separation) and §6/§7
(source-enforcement policy, CI cleanup) are data/docs/workflow changes with
no new trigger behavior to exercise here — see PHASE4_VERIFICATION.md.

A post-closeout review reopened the register with two further schema
blockers and three verification obligations, closed below: concurrency-safe
allow-list enforcement (§1, revision 035), immutability for the three
rule-definition tables revision 033 omitted (§2, revision 036), a
proficiency-type UPDATE rejection test (§3), and — in `test_seed_idempotency.py`
and `scripts/ci_cleanup.py`/its own test module respectively — the seeded
family/version assertion (§4) and the CI cleanup script test (§5).

A second post-closeout review reopened the register again with one further
schema blocker and two focused verification gaps, closed below: character-
language allow-list enforcement in both directions plus its concurrency
safety (§1, revision 037), and a threaded test proving a genuinely blocked
allow-list DELETE resumes and is rejected once the dependent-creator commits
(§2) — the CI-cleanup-entry-point and exact-family-description gaps (§3, §4)
are closed in `tests/unit/test_ci_cleanup.py` and `test_seed_idempotency.py`
respectively.
"""

import threading
import time
import uuid

import pytest
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import IntegrityError, InternalError, ProgrammingError

from dnd_ai.persistence.tables import metadata
from tests.factories import (
    make_campaign,
    make_character,
    make_ruleset_for_world,
    make_ruleset_version,
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
    other_ruleset = _bare_ruleset(db_connection, f"other_lang_used_{uuid.uuid4().hex[:8]}")

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "UPDATE rules.world_rulesets SET ruleset_id = :new "
                "WHERE world_id = :w AND ruleset_id = :old"
            ),
            {"new": other_ruleset, "w": alf.world_id, "old": alf.ruleset_id},
        )
    assert "language from it" in str(exc.value)


# ---------------------------------------------------------------------------
# §1 (second post-closeout): a character's languages must come from a
# ruleset its own world allows (revision 037)
# ---------------------------------------------------------------------------


class CharacterLanguageFixture:
    """A world with one allowed (non-default) ruleset and a character, plus a
    second allowed ruleset/language (positive: multiple allowed families) and
    a third ruleset/language never added to the world's allow-list
    (negative: disallowed family)."""

    def __init__(self, connection: Connection, slug: str) -> None:
        base = slug.replace("-", "_")
        self.world_id = make_world(connection, slug=slug)
        self.character_id = make_character(connection, self.world_id)

        self.ruleset_id = make_ruleset_for_world(
            connection, self.world_id, code=f"lang_{base}", is_default=False
        )
        self.version_id = _current_version(connection, self.ruleset_id)
        self.language_id = self._make_language(connection, self.version_id, "common")

        self.other_allowed_ruleset_id = make_ruleset_for_world(
            connection, self.world_id, code=f"lang_other_{base}", is_default=False
        )
        self.other_allowed_version_id = _current_version(connection, self.other_allowed_ruleset_id)
        self.other_allowed_language_id = self._make_language(
            connection, self.other_allowed_version_id, "elvish"
        )

        self.disallowed_version_id = make_ruleset_version(
            connection, code=f"lang_disallowed_{base}"
        )
        self.disallowed_language_id = self._make_language(
            connection, self.disallowed_version_id, "draconic"
        )

    @staticmethod
    def _make_language(connection: Connection, version_id: uuid.UUID, code: str) -> uuid.UUID:
        return connection.execute(
            text(
                "INSERT INTO rules.languages (ruleset_version_id, code, display_name) "
                "VALUES (:v, :c, :c) RETURNING language_id"
            ),
            {"v": version_id, "c": code},
        ).scalar()


@pytest.fixture
def clf(db_connection: Connection) -> CharacterLanguageFixture:
    return CharacterLanguageFixture(db_connection, f"lang-{uuid.uuid4().hex[:6]}")


def test_a_character_can_know_a_language_from_its_worlds_allowed_ruleset(
    db_connection: Connection, clf: CharacterLanguageFixture
) -> None:
    db_connection.execute(
        text(
            "INSERT INTO character.character_languages (character_id, language_id) VALUES (:c, :l)"
        ),
        {"c": clf.character_id, "l": clf.language_id},
    )


def test_a_character_can_know_languages_from_multiple_allowed_ruleset_families(
    db_connection: Connection, clf: CharacterLanguageFixture
) -> None:
    for language_id in (clf.language_id, clf.other_allowed_language_id):
        db_connection.execute(
            text(
                "INSERT INTO character.character_languages (character_id, language_id) "
                "VALUES (:c, :l)"
            ),
            {"c": clf.character_id, "l": language_id},
        )
    count = db_connection.execute(
        text("SELECT count(*) FROM character.character_languages WHERE character_id = :c"),
        {"c": clf.character_id},
    ).scalar()
    assert count == 2


def test_a_language_from_a_disallowed_ruleset_family_is_rejected_on_insert(
    db_connection: Connection, clf: CharacterLanguageFixture
) -> None:
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "INSERT INTO character.character_languages (character_id, language_id) "
                "VALUES (:c, :l)"
            ),
            {"c": clf.character_id, "l": clf.disallowed_language_id},
        )
    assert "ruleset is not allowed" in str(exc.value)


def test_updating_a_character_language_to_a_disallowed_ruleset_family_is_rejected(
    db_connection: Connection, clf: CharacterLanguageFixture
) -> None:
    db_connection.execute(
        text(
            "INSERT INTO character.character_languages (character_id, language_id) VALUES (:c, :l)"
        ),
        {"c": clf.character_id, "l": clf.language_id},
    )

    # SAVEPOINT (begin_nested): the failed UPDATE aborts the outer
    # transaction in PostgreSQL, which would poison the follow-up SELECT
    # below unless the failure is scoped to a sub-transaction.
    with pytest.raises(CONSTRAINT_ERRORS) as exc, db_connection.begin_nested():
        db_connection.execute(
            text(
                "UPDATE character.character_languages SET language_id = :new "
                "WHERE character_id = :c AND language_id = :old"
            ),
            {"new": clf.disallowed_language_id, "c": clf.character_id, "old": clf.language_id},
        )
    assert "ruleset is not allowed" in str(exc.value)

    unchanged = db_connection.execute(
        text(
            "SELECT count(*) FROM character.character_languages "
            "WHERE character_id = :c AND language_id = :l"
        ),
        {"c": clf.character_id, "l": clf.language_id},
    ).scalar()
    assert unchanged == 1, "the failed UPDATE must not have partially applied"


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


# ---------------------------------------------------------------------------
# §2: Rules-identity parent-scope immutability (revision 033)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# §1 (post-closeout): concurrency-safe allow-list enforcement (revision 035)
# ---------------------------------------------------------------------------
# Two real connections, following the pattern established in
# test_party_memberships.py::test_concurrent_overlapping_inserts_cannot_both_commit:
# committed setup under a unique slug (this fixture's transaction can't be the
# auto-rollback db_connection, since two independent connections need to see
# each other's committed state), a short lock_timeout on the side that must
# block, and explicit teardown in a finally block.
#
# All six dependency categories are covered for the DELETE race (the race the
# review actually found — a dependent being created while the association is
# concurrently removed). The identical lock also protects an UPDATE-based
# repoint, since revision 031's trigger already fires on
# "BEFORE DELETE OR UPDATE OF world_id, ruleset_id" and repointing needs the
# same exclusive row lock a DELETE does — proven once (build category) rather
# than for all six, since the locking mechanism is table/row-level, not
# category-specific, and repeating it six times would exercise the same
# mechanism six times over rather than six different things.


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
        self.version_id = _current_version(connection, self.ruleset_id)
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        self.character_id = make_character(connection, self.world_id)


def _cleanup_concurrency_world(engine: Engine, slug: str) -> None:
    with engine.begin() as cleanup:
        params = {"s": slug}
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
                WHERE code LIKE ('concurrency_' || :s || '%')
            )""",
            "DELETE FROM rules.rulesets WHERE code LIKE ('concurrency_' || :s || '%')",
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
            other_ruleset_id = _bare_ruleset(setup, f"conc_repoint_target_{uuid.uuid4().hex[:8]}")

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


# ---------------------------------------------------------------------------
# §2 (second post-closeout): a genuinely blocked allow-list DELETE resumes
# and is rejected once the dependent-creator commits
# ---------------------------------------------------------------------------
# The lock_timeout tests above prove a concurrent DELETE/UPDATE blocks behind
# the FOR SHARE lock, then prove a *retry in a new transaction* sees the
# committed dependent and is rejected — but not that the original blocked
# statement itself, left waiting rather than cancelled, resumes and is
# rejected once unblocked. This closes that gap with a real second thread
# (no lock_timeout), a bounded poll of pg_stat_activity proving the DELETE is
# genuinely waiting on the lock before the creator commits, and a bounded
# thread.join so a failed assertion cannot hang the test run.
#
# Exercised once, for the newly added character-language category (revision
# 037): the mechanism under test — a FOR SHARE lock on one row, blocking a
# concurrent exclusive-locking DELETE/UPDATE until the holder's transaction
# ends — is table/row-level, not category-specific (see the comment above
# the lock_timeout test section), so a second full thread-and-poll test for
# each of the other five categories would exercise the same mechanism six
# times over rather than six different things.


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


# ---------------------------------------------------------------------------
# §2 (post-closeout): immutability for the remaining rule-definition tables
# (revision 036)
# ---------------------------------------------------------------------------


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
