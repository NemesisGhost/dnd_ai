import { describe, expect, it } from "vitest"
import { SECTIONS, STAGES, defaultSection, parseSection, sectionsOf, stageOf } from "./runStages"

describe("run stages", () => {
    it("groups the sections under the three stages in order", () => {
        expect(STAGES.map((s) => s.key)).toEqual(["prepare", "run", "wrap"])
        expect(sectionsOf("prepare").map((s) => s.key)).toEqual(["participants", "encounter-prep"])
        expect(sectionsOf("run").map((s) => s.key)).toEqual(["log", "travel", "award-item", "encounters"])
        expect(sectionsOf("wrap").map((s) => s.key)).toEqual(["review", "end"])
        expect(SECTIONS).toHaveLength(8)
    })

    it("derives the stage from the section", () => {
        expect(stageOf("participants")).toBe("prepare")
        expect(stageOf("travel")).toBe("run")
        expect(stageOf("end")).toBe("wrap")
    })

    it("accepts only known section keys", () => {
        expect(parseSection("award-item")).toBe("award-item")
        expect(parseSection("bogus")).toBeNull()
        expect(parseSection("")).toBeNull()
        expect(parseSection(null)).toBeNull()
    })

    it.each([
        ["active", "unscheduled", "participants"],
        ["active", "scheduled", "participants"],
        ["active", "in_progress", "log"],
        ["active", "completed", "review"],
        ["archived", "in_progress", "review"],
        ["pending", "scheduled", "review"],
    ] as const)("opens a %s / %s session on %s", (status, play, expected) => {
        expect(defaultSection({ status_code: status, play_status: play })).toBe(expected)
    })
})
