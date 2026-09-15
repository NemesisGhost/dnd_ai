"""Audience-filtered active-build character sheet query.

`character.characters` describes identity-level facts (species, size);
`character.character_builds` and its ruleset-scoped children
(`character_ability_scores`, `character_class_levels`,
`character_proficiencies`, `character_features`,
`character_spellcasting_profiles`, `character_known_spells`,
`character_prepared_spells`) describe one versioned mechanical build; which
build is *active* on a given timeline is timeline state
(`campaign.character_state.character_build_id`, docs/architecture/
DATABASE_MODEL.md §7.4/§17) — never a property of the build itself, a
caller-supplied build id, the newest build, or an arbitrary pick among
several. A timeline that has not itself diverged has no local
`character_state` row at all; `dnd_ai.queries.character_build_resolution.
resolve_effective_character_build_id()` resolves the branch-effective value
in that case (see its own docstring for the exact resolution order and a
documented schema limitation). This module resolves that chain for one
character on one timeline and assembles the full mechanical sheet from it.

`character.character_languages`/`.character_senses`/`.character_movements`
are character-level records, not build-owned — they are fetched by
`character_id` alone, in functions that never take a `character_build_id`
parameter, so that distinction stays structurally visible in this module's
own code even though the assembled `CharacterSheetView` presents them
alongside the build-owned collections for the portal's convenience.

This module is framework-free and performs no authorization of its own:
the caller must already have authorized the *full* character-view tier
(`dnd_ai.api.access.resolve_character_view_tier`) for `character_id` before
calling `get_character_sheet_view()` — the same "authorization happens at
the API/access boundary, the query only filters" split every other query
module in this package follows (`dnd_ai.queries.character`,
`.inventory`, ...).

Derived calculations (ability modifiers, proficiency bonus, skill/saving-
throw bonuses, passive scores, spell attack bonus, spell save DC) are
computed via `dnd_ai.domain.character_calculations`, gated by
`supports_ruleset(build's ruleset code)`. For an unsupported (non-`dnd5e`)
ruleset, every derived field in the response is `None` and only the raw,
authoritative database values are returned — this module never falls back
to guessing a D&D-shaped number for a ruleset it doesn't recognize. A
derived value is also `None` whenever one of its own raw inputs is
missing — most commonly a skill or saving throw whose governing ability
has no `character_ability_scores` row in this build, or any proficiency-
gated bonus when the build has no class levels at all (no total level, so
no proficiency bonus to add).

No active build — `campaign.character_state.character_build_id IS NULL` on
`timeline_id` itself, or no build resolvable anywhere in its branch
ancestry — is a legitimate, successful state, not an error:
`get_character_sheet_view()`
still returns a full `CharacterSheetView` identifying the character, with
every build-owned field/collection at its documented "no build" value
(`character_build_id`/`build_label`/`ruleset_*` all `None`, `total_level`
0, `proficiency_bonus` `None`, every build-owned collection empty) —
the character-level `languages`/`senses`/`movements` collections are still
populated, since they do not depend on a build at all.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection, text

from dnd_ai.domain.character_calculations import (
    ability_modifier,
    passive_score,
    saving_throw_bonus,
    skill_bonus,
    spell_attack_bonus,
    spell_save_dc,
    supports_ruleset,
)
from dnd_ai.domain.character_calculations import (
    proficiency_bonus as calculate_proficiency_bonus,
)
from dnd_ai.domain.character_calculations import (
    total_level as calculate_total_level,
)
from dnd_ai.domain.errors import DomainAuthorizationError
from dnd_ai.queries.character_build_resolution import resolve_effective_character_build_id


class CharacterSheetNotFoundError(DomainAuthorizationError):
    """Raised by `get_character_sheet_view()` for a nonexistent
    `character_id`, or one whose own world does not match the caller's
    `expected_world_id` — identically, so a caller can never distinguish
    "doesn't exist" from "belongs to a different world" (mirroring
    `dnd_ai.queries.character.CharacterNotFoundError`'s identical
    reasoning). The supplied character/world ids are included only in the
    constructor's `detail` argument (`str(self)`), never in
    `safe_message`."""


@dataclass(frozen=True)
class ClassLevelView:
    class_id: uuid.UUID
    class_code: str
    class_display_name: str
    level: int
    hit_die: int
    subclass_id: uuid.UUID | None
    subclass_code: str | None
    subclass_display_name: str | None


@dataclass(frozen=True)
class AbilityScoreView:
    ability_id: uuid.UUID
    ability_code: str
    ability_display_name: str
    score: int
    modifier: int | None


@dataclass(frozen=True)
class SkillView:
    skill_id: uuid.UUID
    code: str
    display_name: str
    governing_ability_code: str
    governing_ability_modifier: int | None
    is_proficient: bool
    is_expertise: bool
    bonus: int | None
    passive_score: int | None


@dataclass(frozen=True)
class SavingThrowView:
    ability_id: uuid.UUID
    ability_code: str
    ability_display_name: str
    ability_modifier: int | None
    is_proficient: bool
    bonus: int | None


@dataclass(frozen=True)
class OtherProficiencyView:
    proficiency_type_code: str
    proficiency_type_display_name: str
    target_label: str
    is_expertise: bool


@dataclass(frozen=True)
class FeatureView:
    feature_id: uuid.UUID
    code: str
    display_name: str
    description: str | None
    granted_at_level: int | None
    source_category: str
    """One of "class", "subclass", "species", or "other" — derived from
    which of `rules.features.class_id`/`.subclass_id`/`.species_id` is set.
    The three associations are independently nullable and not mutually
    exclusive (docs/architecture/DATABASE_MODEL.md §8), so a feature with
    more than one set is reported under the most specific: subclass, then
    class, then species."""


@dataclass(frozen=True)
class SpellView:
    spell_id: uuid.UUID
    code: str
    display_name: str
    level: int
    school: str | None
    casting_time: str | None
    range: str | None
    duration: str | None
    description: str | None
    damage_type_code: str | None
    damage_type_display_name: str | None
    is_known: bool
    is_prepared: bool


@dataclass(frozen=True)
class SpellcastingProfileView:
    character_spellcasting_profile_id: uuid.UUID
    class_id: uuid.UUID | None
    class_code: str | None
    class_display_name: str | None
    spellcasting_ability_id: uuid.UUID
    spellcasting_ability_code: str
    spellcasting_ability_display_name: str
    spellcasting_ability_modifier: int | None
    spell_attack_bonus: int | None
    spell_save_dc: int | None
    spells: tuple[SpellView, ...]


@dataclass(frozen=True)
class LanguageView:
    language_id: uuid.UUID
    code: str
    display_name: str


@dataclass(frozen=True)
class SenseView:
    sense_type: str
    range_feet: int


@dataclass(frozen=True)
class MovementView:
    movement_type: str
    speed_feet: int


@dataclass(frozen=True)
class CharacterSheetView:
    character_id: uuid.UUID
    name: str
    species_code: str
    species_display_name: str
    size_category: str
    character_build_id: uuid.UUID | None
    build_label: str | None
    ruleset_code: str | None
    ruleset_display_name: str | None
    ruleset_version_id: uuid.UUID | None
    ruleset_version_label: str | None
    total_level: int
    proficiency_bonus: int | None
    class_levels: tuple[ClassLevelView, ...]
    ability_scores: tuple[AbilityScoreView, ...]
    skills: tuple[SkillView, ...]
    saving_throws: tuple[SavingThrowView, ...]
    other_proficiencies: tuple[OtherProficiencyView, ...]
    features: tuple[FeatureView, ...]
    spellcasting_profiles: tuple[SpellcastingProfileView, ...]
    languages: tuple[LanguageView, ...]
    senses: tuple[SenseView, ...]
    movements: tuple[MovementView, ...]


def _feature_source_category(row: Any) -> str:
    if row["subclass_id"] is not None:
        return "subclass"
    if row["class_id"] is not None:
        return "class"
    if row["species_id"] is not None:
        return "species"
    return "other"


def _fetch_languages(connection: Connection, character_id: uuid.UUID) -> tuple[LanguageView, ...]:
    """Character-level, not build-owned — see this module's own docstring."""
    rows = connection.execute(
        text("""
            SELECT cl.language_id, l.code, l.display_name
            FROM character.character_languages cl
            JOIN rules.languages l ON l.language_id = cl.language_id
            WHERE cl.character_id = :character
            ORDER BY l.code
        """),
        {"character": character_id},
    ).mappings()
    return tuple(
        LanguageView(language_id=r["language_id"], code=r["code"], display_name=r["display_name"])
        for r in rows
    )


def _fetch_senses(connection: Connection, character_id: uuid.UUID) -> tuple[SenseView, ...]:
    """Character-level, not build-owned — see this module's own docstring."""
    rows = connection.execute(
        text("""
            SELECT sense_type, range_feet FROM character.character_senses
            WHERE character_id = :character
            ORDER BY sense_type
        """),
        {"character": character_id},
    ).mappings()
    return tuple(SenseView(sense_type=r["sense_type"], range_feet=r["range_feet"]) for r in rows)


def _fetch_movements(connection: Connection, character_id: uuid.UUID) -> tuple[MovementView, ...]:
    """Character-level, not build-owned — see this module's own docstring."""
    rows = connection.execute(
        text("""
            SELECT movement_type, speed_feet FROM character.character_movements
            WHERE character_id = :character
            ORDER BY movement_type
        """),
        {"character": character_id},
    ).mappings()
    return tuple(
        MovementView(movement_type=r["movement_type"], speed_feet=r["speed_feet"]) for r in rows
    )


def get_character_sheet_view(
    connection: Connection,
    *,
    character_id: uuid.UUID,
    timeline_id: uuid.UUID,
    expected_world_id: uuid.UUID,
) -> CharacterSheetView:
    """The active-build mechanical sheet for `character_id` on
    `timeline_id`, resolved via `campaign.character_state.
    character_build_id` — for `timeline_id` itself, or, when it has not
    diverged, the branch-effective value inherited from its ancestry (see
    `dnd_ai.queries.character_build_resolution.
    resolve_effective_character_build_id`'s own docstring for the full
    resolution order and its documented limitation) — never the newest
    build, an arbitrary pick, a caller-supplied build id, or an inference
    from the campaign's general ruleset. Raises `CharacterSheetNotFoundError`
    for a nonexistent character or one belonging to a different world than
    `expected_world_id` (always the caller's own resolved-timeline world —
    `dnd_ai.api._shared.timeline_world_id`, never caller-supplied)."""
    identity_row = (
        connection.execute(
            text("""
                SELECT c.character_id, e.world_id, e.canonical_name, sp.code AS species_code,
                       sp.display_name AS species_display_name, c.size_category
                FROM character.characters c
                JOIN core.entities e ON e.entity_id = c.character_id
                JOIN rules.species sp ON sp.species_id = c.species_id
                WHERE c.character_id = :character
            """),
            {"character": character_id},
        )
        .mappings()
        .one_or_none()
    )

    if identity_row is None or identity_row["world_id"] != expected_world_id:
        raise CharacterSheetNotFoundError(
            f"character {character_id} does not exist in world {expected_world_id} "
            f"(actual world: {identity_row['world_id'] if identity_row is not None else None})"
        )

    languages = _fetch_languages(connection, character_id)
    senses = _fetch_senses(connection, character_id)
    movements = _fetch_movements(connection, character_id)

    character_build_id = resolve_effective_character_build_id(
        connection, character_id=character_id, timeline_id=timeline_id
    )

    if character_build_id is None:
        return CharacterSheetView(
            character_id=identity_row["character_id"],
            name=identity_row["canonical_name"],
            species_code=identity_row["species_code"],
            species_display_name=identity_row["species_display_name"],
            size_category=identity_row["size_category"],
            character_build_id=None,
            build_label=None,
            ruleset_code=None,
            ruleset_display_name=None,
            ruleset_version_id=None,
            ruleset_version_label=None,
            total_level=0,
            proficiency_bonus=None,
            class_levels=(),
            ability_scores=(),
            skills=(),
            saving_throws=(),
            other_proficiencies=(),
            features=(),
            spellcasting_profiles=(),
            languages=languages,
            senses=senses,
            movements=movements,
        )

    build_row = (
        connection.execute(
            text("""
                SELECT cb.character_build_id, cb.label, rv.ruleset_version_id, rv.version_label,
                       r.code AS ruleset_code, r.display_name AS ruleset_display_name
                FROM character.character_builds cb
                JOIN rules.ruleset_versions rv ON rv.ruleset_version_id = cb.ruleset_version_id
                JOIN rules.rulesets r ON r.ruleset_id = rv.ruleset_id
                WHERE cb.character_build_id = :build AND cb.character_id = :character
            """),
            {"build": character_build_id, "character": character_id},
        )
        .mappings()
        .one_or_none()
    )
    if build_row is None:
        # campaign.character_state.character_build_id is trigger-enforced
        # (revision 028) to belong to this same character — unreachable
        # in practice; a data-integrity assertion, not a caller-facing
        # error.
        raise AssertionError(
            f"active build {character_build_id} for character {character_id} on timeline "
            f"{timeline_id} does not belong to this character despite the DB trigger invariant"
        )

    ruleset_version_id = build_row["ruleset_version_id"]
    supported = supports_ruleset(build_row["ruleset_code"])

    ability_rows = connection.execute(
        text("""
            SELECT cas.ability_id, a.code, a.display_name, cas.score
            FROM character.character_ability_scores cas
            JOIN rules.abilities a ON a.ability_id = cas.ability_id
            WHERE cas.character_build_id = :build
            ORDER BY a.code
        """),
        {"build": character_build_id},
    ).mappings()

    ability_modifiers: dict[uuid.UUID, int] = {}
    ability_scores = []
    for row in ability_rows:
        modifier = ability_modifier(row["score"]) if supported else None
        if modifier is not None:
            ability_modifiers[row["ability_id"]] = modifier
        ability_scores.append(
            AbilityScoreView(
                ability_id=row["ability_id"],
                ability_code=row["code"],
                ability_display_name=row["display_name"],
                score=row["score"],
                modifier=modifier,
            )
        )

    class_rows = list(
        connection.execute(
            text("""
                SELECT ccl.class_id, c.code, c.display_name, ccl.level, c.hit_die,
                       ccl.subclass_id, s.code AS subclass_code,
                       s.display_name AS subclass_display_name
                FROM character.character_class_levels ccl
                JOIN rules.classes c ON c.class_id = ccl.class_id
                LEFT JOIN rules.subclasses s ON s.subclass_id = ccl.subclass_id
                WHERE ccl.character_build_id = :build
                ORDER BY c.code
            """),
            {"build": character_build_id},
        ).mappings()
    )
    class_levels = tuple(
        ClassLevelView(
            class_id=row["class_id"],
            class_code=row["code"],
            class_display_name=row["display_name"],
            level=row["level"],
            hit_die=row["hit_die"],
            subclass_id=row["subclass_id"],
            subclass_code=row["subclass_code"],
            subclass_display_name=row["subclass_display_name"],
        )
        for row in class_rows
    )
    computed_total_level = calculate_total_level(row["level"] for row in class_rows)
    computed_proficiency_bonus = (
        calculate_proficiency_bonus(computed_total_level)
        if supported and computed_total_level >= 1
        else None
    )

    skill_proficiencies: dict[uuid.UUID, bool] = {
        row["skill_id"]: row["is_expertise"]
        for row in connection.execute(
            text("""
                SELECT skill_id, is_expertise FROM character.character_proficiencies
                WHERE character_build_id = :build AND skill_id IS NOT NULL
            """),
            {"build": character_build_id},
        ).mappings()
    }
    saving_throw_proficiencies: set[uuid.UUID] = {
        row["saving_throw_ability_id"]
        for row in connection.execute(
            text("""
                SELECT saving_throw_ability_id FROM character.character_proficiencies
                WHERE character_build_id = :build AND saving_throw_ability_id IS NOT NULL
            """),
            {"build": character_build_id},
        ).mappings()
    }
    other_proficiency_rows = connection.execute(
        text("""
            SELECT pt.code AS proficiency_type_code, pt.display_name AS proficiency_type_display_name,
                   cp.target_label, cp.is_expertise
            FROM character.character_proficiencies cp
            JOIN rules.proficiency_types pt ON pt.proficiency_type_id = cp.proficiency_type_id
            WHERE cp.character_build_id = :build AND cp.target_label IS NOT NULL
            ORDER BY pt.code, cp.target_label
        """),
        {"build": character_build_id},
    ).mappings()
    other_proficiencies = tuple(
        OtherProficiencyView(
            proficiency_type_code=row["proficiency_type_code"],
            proficiency_type_display_name=row["proficiency_type_display_name"],
            target_label=row["target_label"],
            is_expertise=row["is_expertise"],
        )
        for row in other_proficiency_rows
    )

    skill_rows = connection.execute(
        text("""
            SELECT sk.skill_id, sk.code, sk.display_name, a.ability_id AS governing_ability_id,
                   a.code AS governing_ability_code
            FROM rules.skills sk
            JOIN rules.abilities a ON a.ability_id = sk.ability_id
            WHERE sk.ruleset_version_id = :ruleset_version
            ORDER BY sk.code
        """),
        {"ruleset_version": ruleset_version_id},
    ).mappings()
    skills = []
    for row in skill_rows:
        governing_modifier = ability_modifiers.get(row["governing_ability_id"])
        is_expertise = skill_proficiencies.get(row["skill_id"], False)
        is_proficient = row["skill_id"] in skill_proficiencies
        needs_proficiency_bonus = is_proficient or is_expertise
        if (
            not supported
            or governing_modifier is None
            or (needs_proficiency_bonus and computed_proficiency_bonus is None)
        ):
            bonus, passive = None, None
        else:
            bonus = skill_bonus(
                governing_modifier,
                computed_proficiency_bonus or 0,
                is_proficient=is_proficient,
                is_expertise=is_expertise,
            )
            passive = passive_score(bonus)
        skills.append(
            SkillView(
                skill_id=row["skill_id"],
                code=row["code"],
                display_name=row["display_name"],
                governing_ability_code=row["governing_ability_code"],
                governing_ability_modifier=governing_modifier,
                is_proficient=is_proficient,
                is_expertise=is_expertise,
                bonus=bonus,
                passive_score=passive,
            )
        )

    saving_throw_ability_rows = connection.execute(
        text("""
            SELECT ability_id, code, display_name FROM rules.abilities
            WHERE ruleset_version_id = :ruleset_version
            ORDER BY code
        """),
        {"ruleset_version": ruleset_version_id},
    ).mappings()
    saving_throws = []
    for row in saving_throw_ability_rows:
        ability_mod = ability_modifiers.get(row["ability_id"])
        is_proficient = row["ability_id"] in saving_throw_proficiencies
        if (
            not supported
            or ability_mod is None
            or (is_proficient and computed_proficiency_bonus is None)
        ):
            bonus = None
        else:
            bonus = saving_throw_bonus(
                ability_mod, computed_proficiency_bonus or 0, is_proficient=is_proficient
            )
        saving_throws.append(
            SavingThrowView(
                ability_id=row["ability_id"],
                ability_code=row["code"],
                ability_display_name=row["display_name"],
                ability_modifier=ability_mod,
                is_proficient=is_proficient,
                bonus=bonus,
            )
        )

    feature_rows = connection.execute(
        text("""
            SELECT f.feature_id, f.code, f.display_name, f.description, f.granted_at_level,
                   f.class_id, f.subclass_id, f.species_id
            FROM character.character_features cf
            JOIN rules.features f ON f.feature_id = cf.feature_id
            WHERE cf.character_build_id = :build
            ORDER BY COALESCE(f.granted_at_level, 0), f.code
        """),
        {"build": character_build_id},
    ).mappings()
    features = tuple(
        FeatureView(
            feature_id=row["feature_id"],
            code=row["code"],
            display_name=row["display_name"],
            description=row["description"],
            granted_at_level=row["granted_at_level"],
            source_category=_feature_source_category(row),
        )
        for row in feature_rows
    )

    profile_rows = list(
        connection.execute(
            text("""
                SELECT csp.character_spellcasting_profile_id, csp.class_id, c.code AS class_code,
                       c.display_name AS class_display_name, csp.spellcasting_ability_id,
                       a.code AS ability_code, a.display_name AS ability_display_name
                FROM character.character_spellcasting_profiles csp
                LEFT JOIN rules.classes c ON c.class_id = csp.class_id
                JOIN rules.abilities a ON a.ability_id = csp.spellcasting_ability_id
                WHERE csp.character_build_id = :build
                ORDER BY COALESCE(c.code, ''), a.code, csp.character_spellcasting_profile_id
            """),
            {"build": character_build_id},
        ).mappings()
    )
    profile_ids = [row["character_spellcasting_profile_id"] for row in profile_rows]

    known_ids_by_profile: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    prepared_ids_by_profile: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    spell_rows_by_profile: dict[uuid.UUID, dict[uuid.UUID, Any]] = defaultdict(dict)

    if profile_ids:
        # Two batch queries covering every profile's spells at once —
        # never one query per profile or per spell.
        known_rows = connection.execute(
            text("""
                SELECT ks.character_spellcasting_profile_id, sp.spell_id, sp.code,
                       sp.display_name, sp.level, sp.school, sp.casting_time, sp.range,
                       sp.duration, sp.description, dt.code AS damage_type_code,
                       dt.display_name AS damage_type_display_name
                FROM character.character_known_spells ks
                JOIN rules.spells sp ON sp.spell_id = ks.spell_id
                LEFT JOIN rules.damage_types dt ON dt.damage_type_id = sp.damage_type_id
                WHERE ks.character_spellcasting_profile_id = ANY(:profiles)
            """),
            {"profiles": profile_ids},
        ).mappings()
        for row in known_rows:
            profile_id = row["character_spellcasting_profile_id"]
            known_ids_by_profile[profile_id].add(row["spell_id"])
            spell_rows_by_profile[profile_id][row["spell_id"]] = row

        prepared_rows = connection.execute(
            text("""
                SELECT ps.character_spellcasting_profile_id, sp.spell_id, sp.code,
                       sp.display_name, sp.level, sp.school, sp.casting_time, sp.range,
                       sp.duration, sp.description, dt.code AS damage_type_code,
                       dt.display_name AS damage_type_display_name
                FROM character.character_prepared_spells ps
                JOIN rules.spells sp ON sp.spell_id = ps.spell_id
                LEFT JOIN rules.damage_types dt ON dt.damage_type_id = sp.damage_type_id
                WHERE ps.character_spellcasting_profile_id = ANY(:profiles)
            """),
            {"profiles": profile_ids},
        ).mappings()
        for row in prepared_rows:
            profile_id = row["character_spellcasting_profile_id"]
            prepared_ids_by_profile[profile_id].add(row["spell_id"])
            spell_rows_by_profile[profile_id].setdefault(row["spell_id"], row)

    spellcasting_profiles = []
    for row in profile_rows:
        profile_id = row["character_spellcasting_profile_id"]
        ability_mod = ability_modifiers.get(row["spellcasting_ability_id"])
        if not supported or ability_mod is None or computed_proficiency_bonus is None:
            attack_bonus, save_dc = None, None
        else:
            attack_bonus = spell_attack_bonus(ability_mod, computed_proficiency_bonus)
            save_dc = spell_save_dc(ability_mod, computed_proficiency_bonus)

        known_ids = known_ids_by_profile[profile_id]
        prepared_ids = prepared_ids_by_profile[profile_id]
        spells = tuple(
            SpellView(
                spell_id=spell_row["spell_id"],
                code=spell_row["code"],
                display_name=spell_row["display_name"],
                level=spell_row["level"],
                school=spell_row["school"],
                casting_time=spell_row["casting_time"],
                range=spell_row["range"],
                duration=spell_row["duration"],
                description=spell_row["description"],
                damage_type_code=spell_row["damage_type_code"],
                damage_type_display_name=spell_row["damage_type_display_name"],
                is_known=spell_id in known_ids,
                is_prepared=spell_id in prepared_ids,
            )
            for spell_id, spell_row in sorted(
                spell_rows_by_profile[profile_id].items(),
                key=lambda item: (item[1]["level"], item[1]["code"]),
            )
        )

        spellcasting_profiles.append(
            SpellcastingProfileView(
                character_spellcasting_profile_id=profile_id,
                class_id=row["class_id"],
                class_code=row["class_code"],
                class_display_name=row["class_display_name"],
                spellcasting_ability_id=row["spellcasting_ability_id"],
                spellcasting_ability_code=row["ability_code"],
                spellcasting_ability_display_name=row["ability_display_name"],
                spellcasting_ability_modifier=ability_mod,
                spell_attack_bonus=attack_bonus,
                spell_save_dc=save_dc,
                spells=spells,
            )
        )

    return CharacterSheetView(
        character_id=identity_row["character_id"],
        name=identity_row["canonical_name"],
        species_code=identity_row["species_code"],
        species_display_name=identity_row["species_display_name"],
        size_category=identity_row["size_category"],
        character_build_id=build_row["character_build_id"],
        build_label=build_row["label"],
        ruleset_code=build_row["ruleset_code"],
        ruleset_display_name=build_row["ruleset_display_name"],
        ruleset_version_id=ruleset_version_id,
        ruleset_version_label=build_row["version_label"],
        total_level=computed_total_level,
        proficiency_bonus=computed_proficiency_bonus,
        class_levels=class_levels,
        ability_scores=tuple(ability_scores),
        skills=tuple(skills),
        saving_throws=tuple(saving_throws),
        other_proficiencies=other_proficiencies,
        features=features,
        spellcasting_profiles=tuple(spellcasting_profiles),
        languages=languages,
        senses=senses,
        movements=movements,
    )
