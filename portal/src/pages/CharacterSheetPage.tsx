import { useId } from "react"
import { HitPointsMeter } from "../components/HitPointsMeter"
import type { CharacterDetail } from "../types/character"
import type {
    CharacterSheet,
    CharacterSheetClassLevel,
    CharacterSheetMovement,
    CharacterSheetSkill,
    CharacterSheetSpell,
    CharacterSheetSpellcastingProfile,
} from "../types/characterSheet"
import formatSignedNumber from "../utils/signedNumbers"

interface CharacterSheetPageProps {
    sheet: CharacterSheet
    character: CharacterDetail
}

const SKILL_COLUMN_COUNT = 3

function distributeIntoColumns<T>(
    items: T[],
    columnCount: number,
): T[][] {
    const safeColumnCount = Math.max(
        1,
        Math.min(columnCount, items.length || 1),
    )

    const baseSize = Math.floor(
        items.length / safeColumnCount,
    )

    const extraItems = items.length % safeColumnCount

    let offset = 0

    return Array.from(
        { length: safeColumnCount },
        (_, columnIndex) => {
            const columnSize =
                baseSize +
                (columnIndex < extraItems ? 1 : 0)

            const column = items.slice(
                offset,
                offset + columnSize,
            )

            offset += columnSize

            return column
        },
    )
}

function capitalize(text: string): string {
    return text.length === 0
        ? text
        : text.charAt(0).toUpperCase() + text.slice(1)
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

function describeMovement(
    movement: CharacterSheetMovement,
): string {
    return `${capitalize(movement.movement_type)} ${movement.speed_feet} ft`
}

function sortSpells(
    spells: CharacterSheetSpell[],
): CharacterSheetSpell[] {
    return [...spells].sort(
        (a, b) =>
            a.level - b.level ||
            a.display_name.localeCompare(b.display_name),
    )
}

interface OtherEntry {
    key: string
    category: string
    name: string
    detail: string
}

function buildOtherEntries(sheet: CharacterSheet): OtherEntry[] {
    const proficiencyEntries: OtherEntry[] =
        sheet.other_proficiencies.map((proficiency) => ({
            key: `proficiency-${proficiency.proficiency_type_code}-${proficiency.target_label}`,
            category: proficiency.proficiency_type_display_name,
            name: proficiency.target_label,
            detail: proficiency.is_expertise
                ? "Expertise"
                : "—",
        }))

    const languageEntries: OtherEntry[] = sheet.languages.map(
        (language) => ({
            key: `language-${language.language_id}`,
            category: "Language",
            name: language.display_name,
            detail: "—",
        }),
    )

    const senseEntries: OtherEntry[] = sheet.senses.map(
        (sense) => ({
            key: `sense-${sense.sense_type}`,
            category: "Sense",
            name: capitalize(sense.sense_type),
            detail: `${sense.range_feet} ft`,
        }),
    )

    return [
        ...proficiencyEntries,
        ...languageEntries,
        ...senseEntries,
    ]
}

interface SkillColumnTableProps {
    skills: CharacterSheetSkill[]
    columnNumber: number
}

function SkillColumnTable({
    skills,
    columnNumber,
}: SkillColumnTableProps) {
    return (
        <div className="character-sheet__table-scroll">
            <table>
                <caption>Skills (column {columnNumber})</caption>
                <thead>
                    <tr>
                        <th scope="col">Skill</th>
                        <th scope="col">Ability</th>
                        <th scope="col">Proficiency</th>
                        <th scope="col">Modifier</th>
                        <th scope="col">Passive</th>
                    </tr>
                </thead>
                <tbody>
                    {skills.map((skill) => (
                        <tr key={skill.skill_id}>
                            <td>{skill.display_name}</td>
                            <td>{skill.governing_ability_code.toUpperCase()}</td>
                            <td>
                                {describeProficiency(
                                    skill.is_proficient,
                                    skill.is_expertise,
                                )}
                            </td>
                            <td>{formatSignedNumber(skill.bonus)}</td>
                            <td>
                                {skill.passive_score ?? "Not recorded"}
                            </td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    )
}

interface SpellcastingProfileSectionProps {
    profile: CharacterSheetSpellcastingProfile
}

function SpellcastingProfileSection({
    profile,
}: SpellcastingProfileSectionProps) {
    const headingId = useId()
    const sortedSpells = sortSpells(profile.spells)

    return (
        <section aria-labelledby={headingId}>
            <h3 id={headingId}>
                {profile.class_display_name ?? "Spellcasting"}
            </h3>

            <dl className="character-sheet__summary">
                <div>
                    <dt>Spellcasting ability</dt>
                    <dd>
                        {profile.spellcasting_ability_display_name}
                    </dd>
                </div>

                <div>
                    <dt>Spell attack bonus</dt>
                    <dd>
                        {formatSignedNumber(
                            profile.spell_attack_bonus,
                        )}
                    </dd>
                </div>

                <div>
                    <dt>Spell save DC</dt>
                    <dd>
                        {profile.spell_save_dc ?? "Not recorded"}
                    </dd>
                </div>
            </dl>

            {sortedSpells.length > 0 ? (
                <div className="character-sheet__table-scroll">
                    <table>
                        <caption>
                            {profile.class_display_name ?? "Spellcasting"}
                            {" spells"}
                        </caption>
                        <thead>
                            <tr>
                                <th scope="col">Level</th>
                                <th scope="col">Name</th>
                                <th scope="col">School</th>
                                <th scope="col">Known</th>
                                <th scope="col">Prepared</th>
                            </tr>
                        </thead>
                        <tbody>
                            {sortedSpells.map((spell) => (
                                <tr key={spell.spell_id}>
                                    <td>
                                        {spell.level === 0
                                            ? "Cantrip"
                                            : spell.level}
                                    </td>
                                    <td>{spell.display_name}</td>
                                    <td>
                                        {spell.school ?? "Not recorded"}
                                    </td>
                                    <td>
                                        {spell.is_known
                                            ? "Known"
                                            : "Not known"}
                                    </td>
                                    <td>
                                        {spell.is_prepared
                                            ? "Prepared"
                                            : "Not prepared"}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
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
    const skillColumns = distributeIntoColumns(
        sheet.skills,
        SKILL_COLUMN_COUNT,
    )

    const otherEntries = buildOtherEntries(sheet)

    return (
        <section
            className="character-sheet"
            aria-labelledby="character-sheet-heading"
        >
            <h1 id="character-sheet-heading">{sheet.name}</h1>

            <dl className="character-sheet__summary">
                <div>
                    <dt>Species</dt>
                    <dd>{sheet.species_display_name}</dd>
                </div>

                <div>
                    <dt>Size</dt>
                    <dd>{sheet.size_category}</dd>
                </div>

                <div>
                    <dt>Character level</dt>
                    <dd>{sheet.total_level}</dd>
                </div>

                <div>
                    <dt>Proficiency bonus</dt>
                    <dd>
                        {formatSignedNumber(
                            sheet.proficiency_bonus,
                        )}
                    </dd>
                </div>

                <div>
                    <dt>Hit points</dt>
                    <dd className="character-sheet__hit-points-value">
                        {character.current_hit_points !== null &&
                            character.maximum_hit_points !== null ? (
                            <HitPointsMeter
                                currentHitPoints={
                                    character.current_hit_points
                                }
                                maximumHitPoints={
                                    character.maximum_hit_points
                                }
                            />
                        ) : (
                            "Not recorded"
                        )}
                    </dd>
                </div>

                <div>
                    <dt>Build</dt>
                    <dd>{sheet.build_label ?? "No active build"}</dd>
                </div>

                <div>
                    <dt>Ruleset</dt>
                    <dd>
                        {sheet.ruleset_display_name ?? "Not recorded"}
                    </dd>
                </div>

                <div>
                    <dt>Ruleset version</dt>
                    <dd>
                        {sheet.ruleset_version_label ?? "Not recorded"}
                    </dd>
                </div>

                <div>
                    <dt>Classes</dt>
                    <dd>
                        {sheet.class_levels.length > 0 ? (
                            <ul className="character-sheet__inline-list">
                                {sheet.class_levels.map(
                                    (classLevel) => (
                                        <li key={classLevel.class_id}>
                                            {describeClassLevel(
                                                classLevel,
                                            )}
                                        </li>
                                    ),
                                )}
                            </ul>
                        ) : (
                            "None recorded"
                        )}
                    </dd>
                </div>

                <div>
                    <dt>Movement</dt>
                    <dd>
                        {sheet.movements.length > 0 ? (
                            <ul className="character-sheet__inline-list">
                                {sheet.movements.map((movement) => (
                                    <li key={movement.movement_type}>
                                        {describeMovement(movement)}
                                    </li>
                                ))}
                            </ul>
                        ) : (
                            "Not recorded"
                        )}
                    </dd>
                </div>
            </dl>

            {sheet.character_build_id === null && (
                <p className="character-sheet__empty-build">
                    No active character build is selected for this
                    timeline.
                </p>
            )}

            <section aria-labelledby="ability-scores-heading">
                <h2 id="ability-scores-heading">
                    Ability Scores &amp; Saving Throws
                </h2>

                {sheet.ability_scores.length > 0 ? (
                    <div className="character-sheet__table-scroll">
                        <table>
                            <caption>
                                Ability scores and saving throws
                            </caption>
                            <thead>
                                <tr>
                                    <th scope="col">Ability</th>
                                    <th scope="col">Score</th>
                                    <th scope="col">Modifier</th>
                                    <th scope="col">Save proficiency</th>
                                    <th scope="col">Save modifier</th>
                                </tr>
                            </thead>
                            <tbody>
                                {sheet.ability_scores.map((ability) => {
                                    const savingThrow =
                                        sheet.saving_throws.find(
                                            (candidate) =>
                                                candidate.ability_id ===
                                                ability.ability_id,
                                        )

                                    return (
                                        <tr key={ability.ability_id}>
                                            <td>
                                                {ability.ability_display_name}
                                            </td>
                                            <td>{ability.score}</td>
                                            <td>
                                                {formatSignedNumber(
                                                    ability.modifier,
                                                )}
                                            </td>
                                            <td>
                                                {savingThrow !== undefined
                                                    ? describeProficiency(
                                                        savingThrow.is_proficient,
                                                        false,
                                                    )
                                                    : "Not recorded"}
                                            </td>
                                            <td>
                                                {savingThrow !== undefined
                                                    ? formatSignedNumber(
                                                        savingThrow.bonus,
                                                    )
                                                    : "Not recorded"}
                                            </td>
                                        </tr>
                                    )
                                })}
                            </tbody>
                        </table>
                    </div>
                ) : (
                    <p>No ability scores recorded.</p>
                )}
            </section>

            <section aria-labelledby="skills-heading">
                <h2 id="skills-heading">Skills</h2>

                {sheet.skills.length > 0 ? (
                    <div className="character-sheet__skill-columns">
                        {skillColumns.map((column, columnIndex) => (
                            <SkillColumnTable
                                key={`skill-column-${columnIndex}`}
                                skills={column}
                                columnNumber={columnIndex + 1}
                            />
                        ))}
                    </div>
                ) : (
                    <p>No skills recorded.</p>
                )}
            </section>

            <section aria-labelledby="other-proficiencies-heading">
                <h2 id="other-proficiencies-heading">
                    Other Proficiencies, Languages, &amp; Senses
                </h2>

                {otherEntries.length > 0 ? (
                    <div className="character-sheet__table-scroll">
                        <table>
                            <caption>
                                Other proficiencies, languages, and senses
                            </caption>
                            <thead>
                                <tr>
                                    <th scope="col">Category</th>
                                    <th scope="col">Name</th>
                                    <th scope="col">Detail</th>
                                </tr>
                            </thead>
                            <tbody>
                                {otherEntries.map((entry) => (
                                    <tr key={entry.key}>
                                        <td>{entry.category}</td>
                                        <td>{entry.name}</td>
                                        <td>{entry.detail}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                ) : (
                    <p>
                        No other proficiencies, languages, or senses
                        recorded.
                    </p>
                )}
            </section>

            <section aria-labelledby="features-heading">
                <h2 id="features-heading">Features</h2>

                {sheet.features.length > 0 ? (
                    <div className="character-sheet__table-scroll">
                        <table>
                            <caption>Features and traits</caption>
                            <thead>
                                <tr>
                                    <th scope="col">Name</th>
                                    <th scope="col">Effect</th>
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
                                            {capitalize(
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
                ) : (
                    <p>No features recorded.</p>
                )}
            </section>

            <section aria-labelledby="spellcasting-heading">
                <h2 id="spellcasting-heading">Spellcasting</h2>

                {sheet.spellcasting_profiles.length > 0 ? (
                    sheet.spellcasting_profiles.map((profile) => (
                        <SpellcastingProfileSection
                            key={
                                profile.character_spellcasting_profile_id
                            }
                            profile={profile}
                        />
                    ))
                ) : (
                    <p>No spellcasting abilities recorded.</p>
                )}
            </section>
        </section>
    )
}
