import { describe, expect, it } from "vitest"
import { characterSheetFixture } from "../fixtures/characterSheet"
import { distributeSkills, sortAbilityScores } from "./characterSheetPresentation"

const skills = Array.from({ length: 8 }, (_, index) => ({
    ...characterSheetFixture.skills[0], skill_id: `skill-${index}`, display_name: `Skill ${index}`,
}))

describe("distributeSkills", () => {
    it("returns no tables for empty skills", () => {
        expect(distributeSkills([], 3)).toEqual([])
    })

    it.each([[1, [8]], [2, [4, 4]], [3, [3, 3, 2]]])(
        "balances eight skills across %i tables", (count, sizes) => {
            const groups = distributeSkills(skills, count)
            expect(groups.map((group) => group.length)).toEqual(sizes)
            expect(groups.flat().map((skill) => skill.skill_id)).toEqual(skills.map((skill) => skill.skill_id))
        },
    )

    it("caps requested counts by skill count and three-table maximum", () => {
        expect(distributeSkills(skills.slice(0, 2), 99)).toHaveLength(2)
        expect(distributeSkills(skills, 99)).toHaveLength(3)
        expect(distributeSkills(skills, 0)).toHaveLength(1)
    })
})

describe("sortAbilityScores", () => {
    it("forces STR, DEX, CON, INT, WIS, CHA order regardless of input order", () => {
        const shuffled = [...characterSheetFixture.ability_scores].reverse()
        expect(shuffled.map((ability) => ability.ability_code)).not.toEqual(
            characterSheetFixture.ability_scores.map((ability) => ability.ability_code),
        )

        const sorted = sortAbilityScores(shuffled)

        expect(sorted.map((ability) => ability.ability_code)).toEqual([
            "strength", "dexterity", "constitution",
            "intelligence", "wisdom", "charisma",
        ])
    })

    it("does not mutate the input array", () => {
        const shuffled = [...characterSheetFixture.ability_scores].reverse()
        const original = [...shuffled]
        sortAbilityScores(shuffled)
        expect(shuffled).toEqual(original)
    })

    it("keeps unrecognized abilities at the end in their original relative order", () => {
        const withExtra = [
            { ...characterSheetFixture.ability_scores[0], ability_code: "luck", ability_id: "ability-luck" },
            { ...characterSheetFixture.ability_scores[0], ability_code: "fate", ability_id: "ability-fate" },
            characterSheetFixture.ability_scores[5],
            characterSheetFixture.ability_scores[0],
        ]

        const sorted = sortAbilityScores(withExtra)

        expect(sorted.map((ability) => ability.ability_code)).toEqual([
            "strength", "charisma", "luck", "fate",
        ])
    })
})
