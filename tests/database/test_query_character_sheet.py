"""`dnd_ai.queries.character_sheet.get_character_sheet_view` — the Phase 13D
Character workspace Sheet-panel query (docs/PHASE13D_CHARACTER_SHEET_BACKEND.md).

Every test builds its own character/build graph with `tests/factories.py`
builders on the function-scoped, always-rolled-back `db_connection` fixture
and calls `get_character_sheet_view` directly — the same "exercise the
query function against a real database, not a mock" discipline
`tests/database/test_query_bootstrap.py` already establishes for its own
domain. HTTP-layer authorization concerns (full-tier access, summary-tier
rejection, character-targeted denial, non-disclosure) are covered
separately in `tests/database/test_api_character_sheet.py`.

Every rules-content row this module creates uses a "sheet_"-prefixed code,
never a code already seeded by migration 022 (e.g. "strength", "fighter",
"common") — `ruleset_version_id` below reuses the real, already-migrated
`dnd5e` ruleset (via `tests.factories.use_dnd5e_ruleset`, since `dnd_ai.
domain.character_calculations.supports_ruleset()` only recognizes that
exact ruleset code), and `rules.*.code` is unique per ruleset_version_id,
not globally — a colliding code would fail the insert outright.
"""

import uuid

import pytest
from sqlalchemy import Connection

from dnd_ai.queries.character_sheet import CharacterSheetNotFoundError, get_character_sheet_view
from tests.factories import (
    make_ability,
    make_character,
    make_character_ability_score,
    make_character_build,
    make_character_class_level,
    make_character_feature,
    make_character_known_spell,
    make_character_language,
    make_character_movement,
    make_character_prepared_spell,
    make_character_proficiency,
    make_character_sense,
    make_character_spellcasting_profile,
    make_character_state,
    make_class,
    make_damage_type,
    make_feature,
    make_language,
    make_proficiency_type,
    make_ruleset_version_for_world,
    make_skill,
    make_species,
    make_spell,
    make_subclass,
    make_timeline,
    make_world,
    use_dnd5e_ruleset,
)

pytestmark = pytest.mark.database


@pytest.fixture
def world_id(db_connection: Connection) -> uuid.UUID:
    return make_world(db_connection, slug=f"sheet-query-{uuid.uuid4().hex[:8]}")


@pytest.fixture
def timeline_id(db_connection: Connection, world_id: uuid.UUID) -> uuid.UUID:
    return make_timeline(db_connection, world_id, is_primary=True)


@pytest.fixture
def ruleset_version_id(db_connection: Connection, world_id: uuid.UUID) -> uuid.UUID:
    """The real, already-seeded dnd5e/2024 ruleset (migration 022) —
    dnd_ai.domain.character_calculations.supports_ruleset() gates every
    derived field on this exact ruleset code, so most tests in this module
    need it to compute anything beyond raw values. Every rules-content row
    a test then creates for this ruleset version must use a "sheet_"-
    prefixed code to avoid colliding with the seeded content."""
    return use_dnd5e_ruleset(db_connection, world_id)


@pytest.fixture
def character_id(
    db_connection: Connection, world_id: uuid.UUID, ruleset_version_id: uuid.UUID
) -> uuid.UUID:
    species_id = make_species(db_connection, ruleset_version_id, code="sheet_species")
    return make_character(db_connection, world_id, species_id=species_id, name="Aria")


def test_a_valid_character_with_no_character_state_row_gets_the_empty_sheet(
    db_connection: Connection, world_id: uuid.UUID, timeline_id: uuid.UUID, character_id: uuid.UUID
) -> None:
    view = get_character_sheet_view(
        db_connection,
        character_id=character_id,
        timeline_id=timeline_id,
        expected_world_id=world_id,
    )
    assert view.name == "Aria"
    assert view.character_build_id is None
    assert view.build_label is None
    assert view.ruleset_code is None
    assert view.ruleset_version_id is None
    assert view.total_level == 0
    assert view.proficiency_bonus is None
    assert view.class_levels == ()
    assert view.ability_scores == ()
    assert view.skills == ()
    assert view.saving_throws == ()
    assert view.other_proficiencies == ()
    assert view.features == ()
    assert view.spellcasting_profiles == ()
    assert view.languages == ()
    assert view.senses == ()
    assert view.movements == ()


def test_a_character_state_row_with_no_build_selected_also_gets_the_empty_sheet(
    db_connection: Connection, world_id: uuid.UUID, timeline_id: uuid.UUID, character_id: uuid.UUID
) -> None:
    make_character_state(db_connection, timeline_id, character_id)

    view = get_character_sheet_view(
        db_connection,
        character_id=character_id,
        timeline_id=timeline_id,
        expected_world_id=world_id,
    )
    assert view.character_build_id is None
    assert view.class_levels == ()


def test_character_level_languages_senses_and_movements_are_returned_even_with_no_active_build(
    db_connection: Connection,
    world_id: uuid.UUID,
    timeline_id: uuid.UUID,
    character_id: uuid.UUID,
    ruleset_version_id: uuid.UUID,
) -> None:
    language_id = make_language(db_connection, ruleset_version_id, code="sheet_language")
    make_character_language(db_connection, character_id, language_id)
    make_character_sense(db_connection, character_id, sense_type="darkvision", range_feet=60)
    make_character_movement(db_connection, character_id, movement_type="walk", speed_feet=30)

    view = get_character_sheet_view(
        db_connection,
        character_id=character_id,
        timeline_id=timeline_id,
        expected_world_id=world_id,
    )
    assert view.character_build_id is None
    assert [lang.code for lang in view.languages] == ["sheet_language"]
    assert [(s.sense_type, s.range_feet) for s in view.senses] == [("darkvision", 60)]
    assert [(m.movement_type, m.speed_feet) for m in view.movements] == [("walk", 30)]


def test_active_build_is_resolved_from_character_state_not_the_newest_or_an_arbitrary_build(
    db_connection: Connection,
    world_id: uuid.UUID,
    timeline_id: uuid.UUID,
    character_id: uuid.UUID,
    ruleset_version_id: uuid.UUID,
) -> None:
    older_build_id = make_character_build(
        db_connection, character_id, ruleset_version_id, label="older"
    )
    make_character_build(
        db_connection, character_id, ruleset_version_id, label="newer-but-not-selected"
    )
    make_character_build(db_connection, character_id, ruleset_version_id, label="also-not-selected")

    make_character_state(
        db_connection, timeline_id, character_id, character_build_id=older_build_id
    )

    view = get_character_sheet_view(
        db_connection,
        character_id=character_id,
        timeline_id=timeline_id,
        expected_world_id=world_id,
    )
    assert view.character_build_id == older_build_id
    assert view.build_label == "older"


def test_different_timelines_select_different_builds_for_the_same_character(
    db_connection: Connection,
    world_id: uuid.UUID,
    character_id: uuid.UUID,
    ruleset_version_id: uuid.UUID,
) -> None:
    timeline_a_id = make_timeline(db_connection, world_id, name="Timeline A")
    timeline_b_id = make_timeline(db_connection, world_id, name="Timeline B")

    build_a_id = make_character_build(
        db_connection, character_id, ruleset_version_id, label="build-a"
    )
    build_b_id = make_character_build(
        db_connection, character_id, ruleset_version_id, label="build-b"
    )
    make_character_state(db_connection, timeline_a_id, character_id, character_build_id=build_a_id)
    make_character_state(db_connection, timeline_b_id, character_id, character_build_id=build_b_id)

    view_a = get_character_sheet_view(
        db_connection,
        character_id=character_id,
        timeline_id=timeline_a_id,
        expected_world_id=world_id,
    )
    view_b = get_character_sheet_view(
        db_connection,
        character_id=character_id,
        timeline_id=timeline_b_id,
        expected_world_id=world_id,
    )
    assert view_a.character_build_id == build_a_id
    assert view_b.character_build_id == build_b_id
    assert view_a.build_label == "build-a"
    assert view_b.build_label == "build-b"


def test_a_nonexistent_character_is_rejected(
    db_connection: Connection, world_id: uuid.UUID, timeline_id: uuid.UUID
) -> None:
    with pytest.raises(CharacterSheetNotFoundError):
        get_character_sheet_view(
            db_connection,
            character_id=uuid.uuid4(),
            timeline_id=timeline_id,
            expected_world_id=world_id,
        )


def test_a_character_in_a_different_world_is_rejected(
    db_connection: Connection, timeline_id: uuid.UUID, character_id: uuid.UUID
) -> None:
    other_world_id = make_world(db_connection, slug=f"sheet-query-other-{uuid.uuid4().hex[:8]}")
    with pytest.raises(CharacterSheetNotFoundError):
        get_character_sheet_view(
            db_connection,
            character_id=character_id,
            timeline_id=timeline_id,
            expected_world_id=other_world_id,
        )


class _MulticlassFixture:
    """A Fighter 2 / Wizard 1 build (multiclass, non-alphabetical insertion
    order) with a partial ability-score set (no Dexterity), one proficient
    skill, one expertise skill, one proficient saving throw, and one
    free-text proficiency — enough to exercise ordering, derived-value
    gating, and the proficiency/expertise split in one build."""

    def __init__(
        self, connection: Connection, world_id: uuid.UUID, ruleset_version_id: uuid.UUID
    ) -> None:
        self.ruleset_version_id = ruleset_version_id
        self.str_id = make_ability(connection, ruleset_version_id, code="sheet_strength")
        self.int_id = make_ability(connection, ruleset_version_id, code="sheet_intelligence")
        self.dex_id = make_ability(connection, ruleset_version_id, code="sheet_dexterity")

        self.athletics_id = make_skill(
            connection, ruleset_version_id, self.str_id, code="sheet_athletics"
        )
        self.arcana_id = make_skill(
            connection, ruleset_version_id, self.int_id, code="sheet_arcana"
        )
        self.stealth_id = make_skill(
            connection, ruleset_version_id, self.dex_id, code="sheet_stealth"
        )

        self.skill_proficiency_type_id = make_proficiency_type(
            connection, ruleset_version_id, code="sheet_skill", target_kind="skill"
        )
        self.saving_throw_proficiency_type_id = make_proficiency_type(
            connection, ruleset_version_id, code="sheet_saving_throw", target_kind="saving_throw"
        )
        self.weapon_proficiency_type_id = make_proficiency_type(
            connection, ruleset_version_id, code="sheet_weapon", target_kind="free_text"
        )

        species_id = make_species(connection, ruleset_version_id, code="sheet_multiclass_species")
        self.character_id = make_character(
            connection, world_id, species_id=species_id, name="Multi"
        )
        self.build_id = make_character_build(connection, self.character_id, ruleset_version_id)

        make_character_ability_score(connection, self.build_id, self.str_id, 16)
        make_character_ability_score(connection, self.build_id, self.int_id, 12)
        # Dexterity deliberately has no character_ability_scores row.

        # Inserted wizard-then-fighter to prove ordering is not insertion order.
        self.wizard_id = make_class(connection, ruleset_version_id, code="sheet_wizard", hit_die=6)
        make_character_class_level(connection, self.build_id, self.wizard_id, 1)
        self.fighter_id = make_class(
            connection, ruleset_version_id, code="sheet_fighter", hit_die=10
        )
        self.champion_id = make_subclass(
            connection, self.fighter_id, ruleset_version_id, code="sheet_champion"
        )
        make_character_class_level(
            connection, self.build_id, self.fighter_id, 2, subclass_id=self.champion_id
        )

        make_character_proficiency(
            connection, self.build_id, self.skill_proficiency_type_id, skill_id=self.athletics_id
        )
        make_character_proficiency(
            connection,
            self.build_id,
            self.skill_proficiency_type_id,
            skill_id=self.arcana_id,
            is_expertise=True,
        )
        make_character_proficiency(
            connection,
            self.build_id,
            self.saving_throw_proficiency_type_id,
            saving_throw_ability_id=self.str_id,
        )
        make_character_proficiency(
            connection,
            self.build_id,
            self.weapon_proficiency_type_id,
            target_label="Martial Weapons",
        )


def test_multiclass_total_level_and_deterministic_class_ordering(
    db_connection: Connection,
    world_id: uuid.UUID,
    timeline_id: uuid.UUID,
    ruleset_version_id: uuid.UUID,
) -> None:
    fx = _MulticlassFixture(db_connection, world_id, ruleset_version_id)
    make_character_state(
        db_connection, timeline_id, fx.character_id, character_build_id=fx.build_id
    )

    view = get_character_sheet_view(
        db_connection,
        character_id=fx.character_id,
        timeline_id=timeline_id,
        expected_world_id=world_id,
    )

    assert view.total_level == 3
    assert view.proficiency_bonus == 2  # 2 + floor((3-1)/4) == 2
    assert [c.class_code for c in view.class_levels] == ["sheet_fighter", "sheet_wizard"]
    fighter_level = next(c for c in view.class_levels if c.class_code == "sheet_fighter")
    assert fighter_level.level == 2
    assert fighter_level.subclass_code == "sheet_champion"
    wizard_level = next(c for c in view.class_levels if c.class_code == "sheet_wizard")
    assert wizard_level.subclass_id is None
    assert wizard_level.subclass_code is None


@pytest.mark.parametrize(
    "score,expected_modifier", [(1, -5), (7, -2), (10, 0), (11, 0), (15, 2), (20, 5)]
)
def test_ability_modifier_uses_floor_division_including_odd_scores_below_ten(
    db_connection: Connection,
    world_id: uuid.UUID,
    timeline_id: uuid.UUID,
    character_id: uuid.UUID,
    ruleset_version_id: uuid.UUID,
    score: int,
    expected_modifier: int,
) -> None:
    ability_id = make_ability(db_connection, ruleset_version_id, code="sheet_modifier_ability")
    build_id = make_character_build(db_connection, character_id, ruleset_version_id)
    make_character_ability_score(db_connection, build_id, ability_id, score)
    make_character_state(db_connection, timeline_id, character_id, character_build_id=build_id)

    view = get_character_sheet_view(
        db_connection,
        character_id=character_id,
        timeline_id=timeline_id,
        expected_world_id=world_id,
    )
    assert view.ability_scores[0].score == score
    assert view.ability_scores[0].modifier == expected_modifier


def test_skill_list_includes_every_ruleset_skill_not_only_proficient_ones(
    db_connection: Connection,
    world_id: uuid.UUID,
    timeline_id: uuid.UUID,
    ruleset_version_id: uuid.UUID,
) -> None:
    fx = _MulticlassFixture(db_connection, world_id, ruleset_version_id)
    make_character_state(
        db_connection, timeline_id, fx.character_id, character_build_id=fx.build_id
    )

    view = get_character_sheet_view(
        db_connection,
        character_id=fx.character_id,
        timeline_id=timeline_id,
        expected_world_id=world_id,
    )

    fixture_codes = {"sheet_athletics", "sheet_arcana", "sheet_stealth"}
    codes = {s.code for s in view.skills if s.code in fixture_codes}
    assert codes == fixture_codes

    athletics = next(s for s in view.skills if s.code == "sheet_athletics")
    assert athletics.is_proficient is True
    assert athletics.is_expertise is False
    assert athletics.bonus is not None
    assert athletics.passive_score == 10 + athletics.bonus

    arcana = next(s for s in view.skills if s.code == "sheet_arcana")
    assert arcana.is_proficient is True
    assert arcana.is_expertise is True
    # Expertise doubles the proficiency bonus rather than being treated as
    # plain proficiency.
    proficiency_bonus = 2  # total level 3 -> 2 + floor((3-1)/4)
    int_modifier = 1  # score 12 -> floor((12-10)/2)
    assert arcana.bonus == int_modifier + 2 * proficiency_bonus

    stealth = next(s for s in view.skills if s.code == "sheet_stealth")
    assert stealth.is_proficient is False
    assert stealth.is_expertise is False
    # Governed by Dexterity, which this build has no score for.
    assert stealth.governing_ability_modifier is None
    assert stealth.bonus is None
    assert stealth.passive_score is None


def test_saving_throw_proficiency_and_bonus(
    db_connection: Connection,
    world_id: uuid.UUID,
    timeline_id: uuid.UUID,
    ruleset_version_id: uuid.UUID,
) -> None:
    fx = _MulticlassFixture(db_connection, world_id, ruleset_version_id)
    make_character_state(
        db_connection, timeline_id, fx.character_id, character_build_id=fx.build_id
    )

    view = get_character_sheet_view(
        db_connection,
        character_id=fx.character_id,
        timeline_id=timeline_id,
        expected_world_id=world_id,
    )

    fixture_codes = {"sheet_strength", "sheet_intelligence", "sheet_dexterity"}
    codes = {st.ability_code for st in view.saving_throws if st.ability_code in fixture_codes}
    assert codes == fixture_codes

    strength_save = next(st for st in view.saving_throws if st.ability_code == "sheet_strength")
    assert strength_save.is_proficient is True
    assert strength_save.ability_modifier == 3  # score 16
    assert strength_save.bonus == 3 + 2  # ability modifier + proficiency bonus

    intelligence_save = next(
        st for st in view.saving_throws if st.ability_code == "sheet_intelligence"
    )
    assert intelligence_save.is_proficient is False
    assert intelligence_save.bonus == intelligence_save.ability_modifier

    dexterity_save = next(st for st in view.saving_throws if st.ability_code == "sheet_dexterity")
    assert dexterity_save.ability_modifier is None
    assert dexterity_save.bonus is None


def test_other_proficiencies_are_free_text_and_kept_separate_from_skills_and_saving_throws(
    db_connection: Connection,
    world_id: uuid.UUID,
    timeline_id: uuid.UUID,
    ruleset_version_id: uuid.UUID,
) -> None:
    fx = _MulticlassFixture(db_connection, world_id, ruleset_version_id)
    make_character_state(
        db_connection, timeline_id, fx.character_id, character_build_id=fx.build_id
    )

    view = get_character_sheet_view(
        db_connection,
        character_id=fx.character_id,
        timeline_id=timeline_id,
        expected_world_id=world_id,
    )

    assert len(view.other_proficiencies) == 1
    assert view.other_proficiencies[0].target_label == "Martial Weapons"
    assert view.other_proficiencies[0].proficiency_type_code == "sheet_weapon"
    assert view.other_proficiencies[0].is_expertise is False


def test_features_report_source_category_from_class_subclass_and_species(
    db_connection: Connection,
    world_id: uuid.UUID,
    timeline_id: uuid.UUID,
    ruleset_version_id: uuid.UUID,
) -> None:
    species_id = make_species(db_connection, ruleset_version_id, code="sheet_feature_species")
    character_id = make_character(db_connection, world_id, species_id=species_id, name="Featured")
    build_id = make_character_build(db_connection, character_id, ruleset_version_id)

    fighter_id = make_class(
        db_connection, ruleset_version_id, code="sheet_feature_fighter", hit_die=10
    )
    class_feature_id = make_feature(
        db_connection,
        ruleset_version_id,
        code="sheet_second_wind",
        class_id=fighter_id,
        granted_at_level=1,
    )
    species_feature_id = make_feature(
        db_connection, ruleset_version_id, code="sheet_darkvision_trait", species_id=species_id
    )
    make_character_feature(db_connection, build_id, class_feature_id)
    make_character_feature(db_connection, build_id, species_feature_id)
    make_character_state(db_connection, timeline_id, character_id, character_build_id=build_id)

    view = get_character_sheet_view(
        db_connection,
        character_id=character_id,
        timeline_id=timeline_id,
        expected_world_id=world_id,
    )
    by_code = {f.code: f for f in view.features}
    assert by_code["sheet_second_wind"].source_category == "class"
    assert by_code["sheet_darkvision_trait"].source_category == "species"
    # Deterministic ordering: granted_at_level (NULLS treated as 0) then code.
    assert [f.code for f in view.features] == ["sheet_darkvision_trait", "sheet_second_wind"]


def test_known_and_prepared_spells_are_independent_associations(
    db_connection: Connection,
    world_id: uuid.UUID,
    timeline_id: uuid.UUID,
    ruleset_version_id: uuid.UUID,
) -> None:
    species_id = make_species(db_connection, ruleset_version_id, code="sheet_caster_species")
    character_id = make_character(db_connection, world_id, species_id=species_id, name="Caster")
    build_id = make_character_build(db_connection, character_id, ruleset_version_id)
    int_id = make_ability(db_connection, ruleset_version_id, code="sheet_caster_intelligence")
    make_character_ability_score(db_connection, build_id, int_id, 16)
    wizard_id = make_class(db_connection, ruleset_version_id, code="sheet_caster_wizard", hit_die=6)
    make_character_class_level(db_connection, build_id, wizard_id, 3)

    fire_damage_id = make_damage_type(db_connection, ruleset_version_id, code="sheet_fire")
    known_only_id = make_spell(db_connection, ruleset_version_id, code="sheet_mage_hand", level=0)
    both_id = make_spell(
        db_connection,
        ruleset_version_id,
        code="sheet_fire_bolt",
        level=0,
        damage_type_id=fire_damage_id,
    )
    prepared_only_id = make_spell(
        db_connection, ruleset_version_id, code="sheet_cure_wounds", level=1
    )

    profile_id = make_character_spellcasting_profile(
        db_connection, build_id, int_id, class_id=wizard_id
    )
    make_character_known_spell(db_connection, profile_id, known_only_id)
    make_character_known_spell(db_connection, profile_id, both_id)
    make_character_prepared_spell(db_connection, profile_id, both_id)
    make_character_prepared_spell(db_connection, profile_id, prepared_only_id)

    make_character_state(db_connection, timeline_id, character_id, character_build_id=build_id)

    view = get_character_sheet_view(
        db_connection,
        character_id=character_id,
        timeline_id=timeline_id,
        expected_world_id=world_id,
    )
    assert len(view.spellcasting_profiles) == 1
    profile = view.spellcasting_profiles[0]
    assert profile.class_code == "sheet_caster_wizard"
    assert profile.spellcasting_ability_modifier == 3
    assert profile.spell_attack_bonus == 3 + 2
    assert profile.spell_save_dc == 8 + 3 + 2

    spells_by_code = {s.code: s for s in profile.spells}
    assert len(spells_by_code) == 3, "each spell appears exactly once per profile"
    assert spells_by_code["sheet_mage_hand"].is_known is True
    assert spells_by_code["sheet_mage_hand"].is_prepared is False
    assert spells_by_code["sheet_fire_bolt"].is_known is True
    assert spells_by_code["sheet_fire_bolt"].is_prepared is True
    assert spells_by_code["sheet_fire_bolt"].damage_type_code == "sheet_fire"
    assert spells_by_code["sheet_cure_wounds"].is_known is False
    assert spells_by_code["sheet_cure_wounds"].is_prepared is True
    # Deterministic ordering: level then code.
    assert [s.code for s in profile.spells] == [
        "sheet_fire_bolt",
        "sheet_mage_hand",
        "sheet_cure_wounds",
    ]


def test_legitimate_empty_collections_for_a_build_with_only_a_class_level(
    db_connection: Connection,
    world_id: uuid.UUID,
    timeline_id: uuid.UUID,
    ruleset_version_id: uuid.UUID,
) -> None:
    species_id = make_species(db_connection, ruleset_version_id, code="sheet_bare_species")
    character_id = make_character(db_connection, world_id, species_id=species_id, name="Bare")
    build_id = make_character_build(db_connection, character_id, ruleset_version_id)
    fighter_id = make_class(
        db_connection, ruleset_version_id, code="sheet_bare_fighter", hit_die=10
    )
    make_character_class_level(db_connection, build_id, fighter_id, 1)
    make_character_state(db_connection, timeline_id, character_id, character_build_id=build_id)

    view = get_character_sheet_view(
        db_connection,
        character_id=character_id,
        timeline_id=timeline_id,
        expected_world_id=world_id,
    )
    assert view.total_level == 1
    assert view.proficiency_bonus == 2
    assert view.ability_scores == ()
    assert view.other_proficiencies == ()
    assert view.features == ()
    assert view.spellcasting_profiles == ()
    assert view.languages == ()
    assert view.senses == ()
    assert view.movements == ()
    # The real dnd5e ruleset's own seeded skills/abilities still appear
    # (the complete-list contract applies regardless of this build's own
    # content), but every one is legitimately non-proficient with no
    # governing-ability modifier, since this build has no ability scores
    # or proficiencies at all.
    assert len(view.skills) > 0
    assert all(not s.is_proficient and s.governing_ability_modifier is None for s in view.skills)
    assert len(view.saving_throws) > 0
    assert all(not st.is_proficient and st.ability_modifier is None for st in view.saving_throws)


def test_an_unsupported_ruleset_returns_raw_values_with_every_derived_field_none(
    db_connection: Connection, world_id: uuid.UUID, timeline_id: uuid.UUID
) -> None:
    homebrew_ruleset_version_id = make_ruleset_version_for_world(
        db_connection, world_id, code="homebrew_system"
    )
    species_id = make_species(db_connection, homebrew_ruleset_version_id, code="human")
    character_id = make_character(db_connection, world_id, species_id=species_id, name="Homebrew")
    build_id = make_character_build(db_connection, character_id, homebrew_ruleset_version_id)
    ability_id = make_ability(db_connection, homebrew_ruleset_version_id, code="might")
    make_character_ability_score(db_connection, build_id, ability_id, 18)
    skill_id = make_skill(db_connection, homebrew_ruleset_version_id, ability_id, code="smashing")
    proficiency_type_id = make_proficiency_type(
        db_connection, homebrew_ruleset_version_id, code="skill", target_kind="skill"
    )
    make_character_proficiency(db_connection, build_id, proficiency_type_id, skill_id=skill_id)
    fighter_id = make_class(db_connection, homebrew_ruleset_version_id, code="brawler", hit_die=12)
    make_character_class_level(db_connection, build_id, fighter_id, 5)
    make_character_state(db_connection, timeline_id, character_id, character_build_id=build_id)

    view = get_character_sheet_view(
        db_connection,
        character_id=character_id,
        timeline_id=timeline_id,
        expected_world_id=world_id,
    )
    assert view.total_level == 5
    assert view.proficiency_bonus is None
    assert view.ability_scores[0].score == 18
    assert view.ability_scores[0].modifier is None
    assert view.skills[0].is_proficient is True
    assert view.skills[0].bonus is None
    assert view.skills[0].passive_score is None
    assert view.saving_throws[0].bonus is None
