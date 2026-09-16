import { useId } from "react"
import { AbilityScoreCard } from "../components/AbilityScoreCard"
import { DetailPanel } from "../components/DetailPanel"
import { FactGrid } from "../components/FactGrid"
import { CharacterDetailsPanel } from "./CharacterDetailsPanel"
import { CharacterSkillsTables } from "./CharacterSkillsTables"
import { FeatureCard } from "./FeatureCard"
import { SpellCard } from "./SpellCard"
import { humanizeCode } from "./characterSheetPresentation"
import { HitPointsMeter } from "../components/HitPointsMeter"
import { StatCard } from "../components/StatCard"
import type { CharacterDetail } from "../types/character"
import type {
    CharacterSheet,
    CharacterSheetSpell,
    CharacterSheetSpellcastingProfile,
} from "../types/characterSheet"
import formatSignedNumber from "../utils/signedNumbers"

interface CharacterSheetPageProps {
    sheet: CharacterSheet
    character: CharacterDetail
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

                        <div className="character-sheet__disclosure-grid">
                            {group.spells.map((spell) => (
                                <SpellCard key={spell.spell_id} spell={spell} />
                            ))}
                        </div>
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
    const conditions = character.conditions
    const resources = character.resources

    const hasKnownDeathSaves =
        character.death_save_successes !== null &&
        character.death_save_failures !== null

    return (
        <div className="character-sheet">
            <CharacterDetailsPanel sheet={sheet} />

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
                    className="stat-card--hit-points"
                    value={character.current_hit_points !== null && character.maximum_hit_points !== null
                        ? undefined : "Not recorded"}
                    secondary={<>Temporary hit points: {character.temporary_hit_points ?? "Not recorded"}</>}
                >
                    {character.current_hit_points !== null && character.maximum_hit_points !== null && (
                        <HitPointsMeter currentHitPoints={character.current_hit_points}
                            maximumHitPoints={character.maximum_hit_points} />
                    )}
                </StatCard>
            </section>

            <DetailPanel title="Current State" className="detail-panel--wide">
                <FactGrid items={[
                    { key: "exhaustion", label: "Exhaustion", value: character.exhaustion_level ?? "Not recorded" },
                    { key: "death-saves", label: "Death saves", value: hasKnownDeathSaves
                        ? `${character.death_save_successes} / ${character.death_save_failures}` : "Not recorded" },
                ]} />
            </DetailPanel>

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
                    <CharacterSkillsTables skills={sheet.skills} />
                </DetailPanel>

                <DetailPanel
                    title="Other Proficiencies"
                    isEmpty={sheet.other_proficiencies.length === 0}
                    emptyState={<p>No other proficiencies recorded.</p>}
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
                    isEmpty={sheet.features.length === 0}
                    emptyState={<p>No features recorded.</p>}
                >
                    <ul className="character-sheet__feature-list">
                        {sheet.features.map((feature) => (
                            <li key={feature.feature_id}>
                                <FeatureCard feature={feature} />
                            </li>
                        ))}
                    </ul>
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
