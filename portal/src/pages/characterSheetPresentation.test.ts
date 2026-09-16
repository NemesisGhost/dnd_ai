import { describe, expect, it } from "vitest"
import { characterSheetFixture } from "../fixtures/characterSheet"
import { distributeSkills } from "./characterSheetPresentation"

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
