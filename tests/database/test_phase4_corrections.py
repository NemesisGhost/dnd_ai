"""Phase 4 corrections review (revisions 023-030).

Covers what the earlier Phase 4 test modules don't already exercise:
sessions' derived world_time_period, rule-content provenance/canon metadata,
the remaining ruleset-version-consistency relationships revision 020 had
deliberately deferred, rules.spells.code format, proficiency duplicate
prevention, species/build world-allowance, and the parent-scope immutability
triggers. Timeline-specific active builds, the world-ruleset single default,
campaign ruleset-version pinning, and character_state HP/transformation
corrections have their own tests already in test_character_timeline_state.py
and test_rulesets.py and are not repeated here.
"""

import uuid

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError, InternalError, ProgrammingError

from tests.factories import (
    make_campaign,
    make_character,
    make_ruleset_version_for_world,
    make_session,
    make_timeline,
    make_world,
    make_world_time,
)

pytestmark = pytest.mark.database

CONSTRAINT_ERRORS = (IntegrityError, InternalError, ProgrammingError)


# ---------------------------------------------------------------------------
# campaign.sessions.world_time_period (revision 023)
# ---------------------------------------------------------------------------


@pytest.fixture
def world_id(db_connection: Connection) -> uuid.UUID:
    return make_world(db_connection, slug="corrections-world")


@pytest.fixture
def campaign_id(db_connection: Connection, world_id: uuid.UUID) -> uuid.UUID:
    timeline_id = make_timeline(db_connection, world_id, is_primary=True)
    return make_campaign(db_connection, timeline_id)


def test_an_unscheduled_session_has_no_world_time_period(
    db_connection: Connection, campaign_id: uuid.UUID
) -> None:
    session_id = make_session(db_connection, campaign_id, 1)
    period = db_connection.execute(
        text("SELECT world_time_period FROM campaign.sessions WHERE session_id = :s"),
        {"s": session_id},
    ).scalar()
    assert period is None


def test_an_open_ended_session_has_an_unbounded_upper_range(
    db_connection: Connection, world_id: uuid.UUID, campaign_id: uuid.UUID
) -> None:
    start = make_world_time(db_connection, world_id, 100)
    session_id = make_session(db_connection, campaign_id, 1, start_world_time_id=start)

    row = db_connection.execute(
        text(
            "SELECT lower(world_time_period), upper_inf(world_time_period) "
            "FROM campaign.sessions WHERE session_id = :s"
        ),
        {"s": session_id},
    ).one()
    assert row[0] == 100
    assert row[1] is True


def test_a_bounded_session_derives_a_half_open_range(
    db_connection: Connection, world_id: uuid.UUID, campaign_id: uuid.UUID
) -> None:
    start = make_world_time(db_connection, world_id, 100)
    end = make_world_time(db_connection, world_id, 200)
    session_id = make_session(
        db_connection, campaign_id, 1, start_world_time_id=start, end_world_time_id=end
    )

    row = db_connection.execute(
        text(
            "SELECT lower(world_time_period), upper(world_time_period) "
            "FROM campaign.sessions WHERE session_id = :s"
        ),
        {"s": session_id},
    ).one()
    assert (row[0], row[1]) == (100, 200)


def test_sessions_may_still_overlap_with_a_derived_range(
    db_connection: Connection, world_id: uuid.UUID, campaign_id: uuid.UUID
) -> None:
    """The derived range is queryable but not exclusion-constrained —
    DATABASE_MODEL.md §6.4's overlap decision is unchanged by revision 023."""
    start = make_world_time(db_connection, world_id, 100)
    end = make_world_time(db_connection, world_id, 300)
    make_session(db_connection, campaign_id, 1, start_world_time_id=start, end_world_time_id=end)
    make_session(db_connection, campaign_id, 2, start_world_time_id=start, end_world_time_id=end)


# ---------------------------------------------------------------------------
# Rule-content provenance and canon status (revision 025)
# ---------------------------------------------------------------------------


def test_ruleset_content_defaults_to_canon(db_connection: Connection) -> None:
    version = make_ruleset_version_for_world(
        db_connection, make_world(db_connection, slug="canon-default-world")
    )
    ability = db_connection.execute(
        text(
            "INSERT INTO rules.abilities (ruleset_version_id, code, display_name) "
            "VALUES (:v, 'strength', 'Strength') RETURNING canon_status_id"
        ),
        {"v": version},
    ).scalar()

    code = db_connection.execute(
        text("SELECT code FROM core.canon_statuses WHERE canon_status_id = :c"), {"c": ability}
    ).scalar()
    assert code == "canon"


def test_ruleset_content_canon_status_can_be_overridden(db_connection: Connection) -> None:
    version = make_ruleset_version_for_world(
        db_connection, make_world(db_connection, slug="canon-override-world")
    )
    draft_status = db_connection.execute(
        text("SELECT canon_status_id FROM core.canon_statuses WHERE code = 'draft'")
    ).scalar()

    ability = db_connection.execute(
        text(
            "INSERT INTO rules.abilities (ruleset_version_id, code, display_name, canon_status_id) "
            "VALUES (:v, 'strength', 'Strength', :status) RETURNING canon_status_id"
        ),
        {"v": version, "status": draft_status},
    ).scalar()
    assert ability == draft_status


def test_rulesets_itself_has_both_provenance_columns(db_connection: Connection) -> None:
    """The comment on rules.rulesets has always claimed both source and canon
    status — revision 025 makes that true rather than aspirational."""
    columns = {
        r[0]
        for r in db_connection.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'rules' AND table_name = 'rulesets'"
            )
        )
    }
    assert {"source_id", "canon_status_id"} <= columns


@pytest.mark.parametrize(
    "table",
    [
        "ruleset_versions",
        "abilities",
        "species",
        "damage_types",
        "conditions",
        "creature_types",
        "languages",
        "proficiency_types",
        "resource_definitions",
        "skills",
        "classes",
        "subclasses",
        "features",
        "feats",
        "spells",
    ],
)
def test_every_rule_content_table_has_provenance_columns(
    db_connection: Connection, table: str
) -> None:
    columns = {
        r[0]
        for r in db_connection.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'rules' AND table_name = :t"
            ),
            {"t": table},
        )
    }
    assert {"source_id", "canon_status_id"} <= columns


# ---------------------------------------------------------------------------
# Remaining ruleset-version consistency (revision 026)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# rules.spells.code format (revision 029)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Proficiency duplicate prevention (revision 029)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Species and build must be allowed for the character's world (revision 029)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Parent-scope immutability (revision 030)
# ---------------------------------------------------------------------------


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
    from tests.factories import make_party

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
