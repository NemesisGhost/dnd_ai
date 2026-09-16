import { useEffect, useRef, useState } from "react"
import type { CharacterSheetSkill } from "../types/characterSheet"
import formatSignedNumber from "../utils/signedNumbers"
import { distributeSkills } from "./characterSheetPresentation"

const MIN_TABLE_WIDTH = 28 * 16
const GAP = 16
const ABILITIES: Record<string, string> = {
    strength: "STR", dexterity: "DEX", constitution: "CON",
    intelligence: "INT", wisdom: "WIS", charisma: "CHA",
}

function tableCount(width: number): number {
    return Math.max(1, Math.min(3, Math.floor((width + GAP) / (MIN_TABLE_WIDTH + GAP))))
}

export function CharacterSkillsTables({ skills }: { skills: CharacterSheetSkill[] }) {
    const containerRef = useRef<HTMLDivElement>(null)
    const [count, setCount] = useState(1)

    useEffect(() => {
        if (typeof ResizeObserver === "undefined" || containerRef.current === null) return
        const observer = new ResizeObserver((entries) => {
            const width = entries[0]?.contentRect.width
            if (width !== undefined) setCount(tableCount(width))
        })
        observer.observe(containerRef.current)
        return () => observer.disconnect()
    }, [])

    const groups = distributeSkills(skills, count)
    return (
        <div className="character-skills-tables" ref={containerRef}>
            {groups.map((group, index) => (
                <div className="character-sheet__table-scroll character-skills-tables__table" key={group[0].skill_id}>
                    <table>
                        <caption>{groups.length === 1 ? "Skills" : `Skills, part ${index + 1} of ${groups.length}`}</caption>
                        <thead><tr>
                            <th scope="col">Skill</th><th scope="col">Ability</th>
                            <th scope="col">Proficiency</th><th scope="col">Bonus</th>
                            <th scope="col">Passive</th>
                        </tr></thead>
                        <tbody>{group.map((skill) => (
                            <tr key={skill.skill_id}>
                                <td>{skill.display_name}</td>
                                <td>{ABILITIES[skill.governing_ability_code] ?? skill.governing_ability_code.slice(0, 3).toUpperCase()}</td>
                                <td>{skill.is_expertise ? "Expertise" : skill.is_proficient ? "Proficient" : "Not proficient"}</td>
                                <td>{formatSignedNumber(skill.bonus)}</td>
                                <td>{skill.passive_score ?? "Not recorded"}</td>
                            </tr>
                        ))}</tbody>
                    </table>
                </div>
            ))}
        </div>
    )
}
