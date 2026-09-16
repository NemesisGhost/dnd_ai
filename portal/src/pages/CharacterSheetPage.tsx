import { useId } from "react"
import { AbilityScoreCard } from "../components/AbilityScoreCard"
import { DetailPanel } from "../components/DetailPanel"
import { FactGrid } from "../components/FactGrid"
import type { FactGridItem } from "../components/FactGrid"
import { HitPointsMeter } from "../components/HitPointsMeter"
import { StatCard } from "../components/StatCard"
import type { CharacterDetail } from "../types/character"
import type {
    CharacterSheet,
    CharacterSheetClassLevel,
    CharacterSheetSpell,
    CharacterSheetSpellcastingProfile,
} from "../types/characterSheet"
import formatSignedNumber from "../utils/signedNumbers"

interface CharacterSheetPageProps {
    sheet: CharacterSheet
    character: CharacterDetail
}

const ABILITY_ABBREVIATIONS: Record<string, string> = {
    strength: "STR",
    dexterity: "DEX",
    constitution: "CON",
    intelligence: "INT",
    wisdom: "WIS",
    charisma: "CHA",
}

function abbreviateAbility(code: string): string {
    return ABILITY_ABBREVIATIONS[code] ?? code.slice(0, 3).toUpperCase()
}

function humanizeCode(code: string): string {
    return code
        .split("_")
        .filter((word) => word.length > 0)
        .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
        .join(" ")
}

function describeProficiency(
    isProficient: boolean,
    isExpertise: boolean,
): string {
    if (isExpertise) {
        return "Expertise"
    }
    if (isProficient) {
        return "Proficient"
    }
    return "Not proficient"
}

function describeClassLevel(
    classLevel: CharacterSheetClassLevel,
): string {
    const subclassSuffix =
        classLevel.subclass_display_name !== null
            ? ` – ${classLevel.subclass_display_name}`
            : ""

    return `${classLevel.class_display_name} ${classLevel.level}${subclassSuffix}`
}

interface SpellLevelGroup {
    level: number
    spells: CharacterSheetSpell[]
}

function groupSpellsByLevel(
    spells: CharacterSheetSpell[],
): SpellLevelGroup[] {
    const groups = new Map<number, CharacterSheetSpell[]>()

    for (const spell of spells) {
        const existing = groups.get(spell.level)
        if (existing !== undefined) {
            existing.push(spell)
        } else {
            groups.set(spell.level, [spell])
        }
    }

    return Array.from(groups.entries())
        .sort(([levelA], [levelB]) => levelA - levelB)
        .map(([level, levelSpells]) => ({
            level,
            spells: levelSpells,
        }))
}

function describeSpellLevel(level: number): string {
    return level === 0 ? "Cantrips" : `Level ${level}`
}

interface SpellcastingProfileSectionProps {
    profile: CharacterSheetSpellcastingProfile
}

function SpellcastingProfileSection({
    profile,
}: SpellcastingProfileSectionProps) {
    const headingId = useId()
    const spellLevelGroups = groupSpellsByLevel(profile.spells)

    return (
        <section
            className="spellcasting-profile"
            aria-labelledby={headingId}
        >
            <h3 id={headingId}>
                {profile.class_display_name ?? "Spellcasting"}
            </h3>

            <div className="character-sheet__stat-row character-sheet__stat-row--compact">
                <StatCard
                    label="Spellcasting ability"
                    value={profile.spellcasting_ability_display_name}
                />

                <StatCard
                    label="Spell attack bonus"
                    value={formatSignedNumber(
                        profile.spell_attack_bonus,
                    )}
                />

                <StatCard
                    label="Spell save DC"
                    value={profile.spell_save_dc ?? "Not recorded"}
                />
            </div>

            {spellLevelGroups.length > 0 ? (
                spellLevelGroups.map((group) => (
                    <div
                        className="spellcasting-profile__level-group"
                        key={group.level}
                    >
                        <h4>{describeSpellLevel(group.level)}</h4>

                        <ul className="character-sheet__fact-list">
                            {group.spells.map((spell) => (
                                <li key={spell.spell_id}>
                                    <span className="character-sheet__fact-list-primary">
                                        {spell.display_name}
                                    </span>

                                    {spell.school !== null && (
                                        <span className="character-sheet__fact-list-secondary">
                                            {" "}
                                            · {humanizeCode(spell.school)}
                                        </span>
                                    )}

                                    <span className="spellcasting-profile__spell-state">
                                        {spell.is_known
                                            ? "Known"
                                            : "Not known"}
                                    </span>

                                    <span className="spellcasting-profile__spell-state">
                                        {spell.is_prepared
                                            ? "Prepared"
                                            : "Not prepared"}
                                    </span>
                                </li>
                            ))}
                        </ul>
                    </div>
                ))
            ) : (
                <p>No spells recorded.</p>
            )}
        </section>
    )
}

export function CharacterSheetPage({
    sheet,
    character,
}: CharacterSheetPageProps) {
    const headerFacts: FactGridItem[] = [
        {
            key: "build",
            label: "Build",
            value: sheet.build_label ?? "No active build",
        },
        {
            key: "ruleset",
            label: "Ruleset",
            value: sheet.ruleset_display_name ?? "Not recorded",
        },
        {
            key: "ruleset-version",
            label: "Ruleset version",
            value: sheet.ruleset_version_label ?? "Not recorded",
        },
        {
            key: "classes",
            label: "Classes",
            value:
                sheet.class_levels.length > 0 ? (
                    <ul className="character-sheet__inline-list">
                        {sheet.class_levels.map((classLevel) => (
                            <li key={classLevel.class_id}>
                                {describeClassLevel(classLevel)}
                            </li>
                        ))}
                    </ul>
                ) : (
                    "None recorded"
                ),
        },
        {
            key: "total-level",
            label: "Character level",
            value: sheet.total_level,
        },
    ]

    const conditions = character.conditions
    const resources = character.resources

    const hasKnownDeathSaves =
        character.death_save_successes !== null &&
        character.death_save_failures !== null

    return (
        <div className="character-sheet">
            <header className="character-sheet__header">
                <p className="character-sheet__eyebrow">
                    {sheet.species_display_name}
                    {" · "}
                    {humanizeCode(sheet.size_category)}
                </p>

                <h1>{sheet.name}</h1>

                <FactGrid
                    className="character-sheet__header-facts"
                    items={headerFacts}
                />
            </header>

            {sheet.character_build_id === null && (
                <p className="character-sheet__empty-build">
                    No active character build is selected for this
                    timeline.
                </p>
            )}

            <section
                className="character-sheet__stat-row"
                aria-label="Primary stats"
            >
                <StatCard
                    label="Proficiency bonus"
                    value={formatSignedNumber(sheet.proficiency_bonus)}
                />

                {sheet.movements.length > 0 ? (
                    sheet.movements.map((movement) => (
                        <StatCard
                            key={movement.movement_type}
                            label={humanizeCode(movement.movement_type)}
                            value={`${movement.speed_feet} ft`}
                        />
                    ))
                ) : (
                    <StatCard label="Movement" value="Not recorded" />
                )}

                <StatCard
                    label="Hit points"
                    value={
                        character.current_hit_points !== null &&
                            character.maximum_hit_points !== null
                            ? undefined
                            : "Not recorded"
                    }
                >
                    {character.current_hit_points !== null &&
                        character.maximum_hit_points !== null && (
                            <HitPointsMeter
                                currentHitPoints={
                                    character.current_hit_points
                                }
                                maximumHitPoints={
                                    character.maximum_hit_points
                                }
                            />
                        )}
                </StatCard>

                <StatCard
                    label="Temporary hit points"
                    value={
                        character.temporary_hit_points ??
                        "Not recorded"
                    }
                />

                <StatCard
                    label="Exhaustion"
                    value={
                        character.exhaustion_level ?? "Not recorded"
                    }
                />

                <StatCard
                    label="Death saves"
                    value={
                        hasKnownDeathSaves
                            ? `${character.death_save_successes} / ${character.death_save_failures}`
                            : "Not recorded"
                    }
                />
            </section>

            <div className="character-sheet__panel-grid">
                <DetailPanel
                    title="Ability Scores & Saving Throws"
                    className="detail-panel--wide"
                    isEmpty={sheet.ability_scores.length === 0}
                    emptyState={<p>No ability scores recorded.</p>}
                >
                    <div className="character-sheet__ability-grid">
                        {sheet.ability_scores.map((ability) => {
                            const savingThrow = sheet.saving_throws.find(
                                (candidate) =>
                                    candidate.ability_id ===
                                    ability.ability_id,
                            )

                            return (
                                <AbilityScoreCard
                                    key={ability.ability_id}
                                    abilityDisplayName={
                                        ability.ability_display_name
                                    }
                                    score={ability.score}
                                    modifier={ability.modifier}
                                    savingThrow={
                                        savingThrow !== undefined
                                            ? {
                                                bonus: savingThrow.bonus,
                                                isProficient:
                                                    savingThrow.is_proficient,
                                            }
                                            : null
                                    }
                                />
                            )
                        })}
                    </div>
                </DetailPanel>

                <DetailPanel
                    title="Skills"
                    className="detail-panel--wide"
                    isEmpty={sheet.skills.length === 0}
                    emptyState={<p>No skills recorded.</p>}
                >
                    <div className="character-sheet__table-scroll">
                        <table>
                            <caption>Skills</caption>
                            <thead>
                                <tr>
                                    <th scope="col">Skill</th>
                                    <th scope="col">Ability</th>
                                    <th scope="col">Proficiency</th>
                                    <th scope="col">Bonus</th>
                                    <th scope="col">Passive</th>
                                </tr>
                            </thead>
                            <tbody>
                                {sheet.skills.map((skill) => (
                                    <tr key={skill.skill_id}>
                                        <td>{skill.display_name}</td>
                                        <td>
                                            {abbreviateAbility(
                                                skill.governing_ability_code,
                                            )}
                                        </td>
                                        <td>
                                            {describeProficiency(
                                                skill.is_proficient,
                                                skill.is_expertise,
                                            )}
                                        </td>
                                        <td>
                                            {formatSignedNumber(skill.bonus)}
                                        </td>
                                        <td>
                                            {skill.passive_score ??
                                                "Not recorded"}
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </DetailPanel>

                <DetailPanel
                    title="Other Proficiencies"
                    isEmpty={sheet.other_proficiencies.length === 0}
                    emptyState={
                        <p>No other proficiencies recorded.</p>
                    }
                >
                    <ul className="character-sheet__fact-list">
                        {sheet.other_proficiencies.map(
                            (proficiency) => (
                                <li
                                    key={`${proficiency.proficiency_type_code}-${proficiency.target_label}`}
                                >
                                    <span className="character-sheet__fact-list-primary">
                                        {proficiency.target_label}
                                    </span>{" "}
                                    <span className="character-sheet__fact-list-secondary">
                                        (
                                        {
                                            proficiency.proficiency_type_display_name
                                        }
                                        {proficiency.is_expertise
                                            ? ", Expertise"
                                            : ""}
                                        )
                                    </span>
                                </li>
                            ),
                        )}
                    </ul>
                </DetailPanel>

                <DetailPanel
                    title="Languages"
                    isEmpty={sheet.languages.length === 0}
                    emptyState={<p>No languages recorded.</p>}
                >
                    <ul className="character-sheet__fact-list">
                        {sheet.languages.map((language) => (
                            <li key={language.language_id}>
                                {language.display_name}
                            </li>
                        ))}
                    </ul>
                </DetailPanel>

                <DetailPanel
                    title="Senses"
                    isEmpty={sheet.senses.length === 0}
                    emptyState={<p>No senses recorded.</p>}
                >
                    <FactGrid
                        items={sheet.senses.map((sense) => ({
                            key: sense.sense_type,
                            label: humanizeCode(sense.sense_type),
                            value: `${sense.range_feet} ft`,
                        }))}
                    />
                </DetailPanel>

                <DetailPanel
                    title="Conditions"
                    isEmpty={
                        conditions === null ||
                        conditions.length === 0
                    }
                    emptyState={
                        <p>
                            {conditions === null
                                ? "Not recorded."
                                : "No conditions are currently recorded."}
                        </p>
                    }
                >
                    {conditions !== null && (
                        <ul className="character-sheet__fact-list">
                            {conditions.map((condition) => (
                                <li key={condition.condition_code}>
                                    <span className="character-sheet__fact-list-primary">
                                        {humanizeCode(
                                            condition.condition_code,
                                        )}
                                    </span>
                                    {condition.source_description !==
                                        null && (
                                            <span className="character-sheet__fact-list-secondary">
                                                {" — "}
                                                {condition.source_description}
                                            </span>
                                        )}
                                </li>
                            ))}
                        </ul>
                    )}
                </DetailPanel>

                <DetailPanel
                    title="Resources"
                    isEmpty={
                        resources === null || resources.length === 0
                    }
                    emptyState={
                        <p>
                            {resources === null
                                ? "Not recorded."
                                : "No resources are currently recorded."}
                        </p>
                    }
                >
                    {resources !== null && (
                        <ul className="character-sheet__fact-list">
                            {resources.map((resource) => (
                                <li key={resource.resource_code}>
                                    <span className="character-sheet__fact-list-primary">
                                        {humanizeCode(
                                            resource.resource_code,
                                        )}
                                    </span>{" "}
                                    {resource.current_amount} /{" "}
                                    {resource.maximum_amount}
                                </li>
                            ))}
                        </ul>
                    )}
                </DetailPanel>

                <DetailPanel
                    title="Features & Traits"
                    className="detail-panel--wide"
                    isEmpty={sheet.features.length === 0}
                    emptyState={<p>No features recorded.</p>}
                >
                    <div className="character-sheet__table-scroll">
                        <table>
                            <caption>Features and traits</caption>
                            <thead>
                                <tr>
                                    <th scope="col">Name</th>
                                    <th scope="col">Description</th>
                                    <th scope="col">Source</th>
                                    <th scope="col">Granted at level</th>
                                </tr>
                            </thead>
                            <tbody>
                                {sheet.features.map((feature) => (
                                    <tr key={feature.feature_id}>
                                        <td>{feature.display_name}</td>
                                        <td>
                                            {feature.description ??
                                                "No description recorded."}
                                        </td>
                                        <td>
                                            {humanizeCode(
                                                feature.source_category,
                                            )}
                                        </td>
                                        <td>
                                            {feature.granted_at_level ??
                                                "Not recorded"}
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </DetailPanel>

                <DetailPanel
                    title="Spellcasting"
                    className="detail-panel--wide"
                    isEmpty={sheet.spellcasting_profiles.length === 0}
                    emptyState={
                        <p>No spellcasting abilities recorded.</p>
                    }
                >
                    {sheet.spellcasting_profiles.map((profile) => (
                        <SpellcastingProfileSection
                            key={
                                profile.character_spellcasting_profile_id
                            }
                            profile={profile}
                        />
                    ))}
                </DetailPanel>
            </div>
        </div>
    )
}
