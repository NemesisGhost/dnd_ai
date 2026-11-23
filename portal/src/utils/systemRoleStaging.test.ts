import { describe, expect, it } from "vitest"
import { describeChange, isDirty, knownRoles, stagedChanges } from "./systemRoleStaging"

describe("stagedChanges", () => {
    it("is empty when the draft matches the baseline, whatever the order", () => {
        expect(stagedChanges(["player", "gm"], ["gm", "player"])).toEqual([])
    })

    it("lists grants first, then removals, each in option order", () => {
        expect(stagedChanges(["admin", "player"], ["gm", "observer"])).toEqual([
            { code: "gm", action: "add" },
            { code: "observer", action: "add" },
            { code: "admin", action: "remove" },
            { code: "player", action: "remove" },
        ])
    })

    it("sends the signed-in account's own Administrator removal last", () => {
        expect(stagedChanges(["admin", "player"], ["observer"], true)).toEqual([
            { code: "observer", action: "add" },
            { code: "player", action: "remove" },
            { code: "admin", action: "remove" },
        ])
    })

    it("does not move an Administrator removal for another account", () => {
        expect(stagedChanges(["admin", "player"], ["observer"], false).map((c) => c.code)).toEqual([
            "observer",
            "admin",
            "player",
        ])
    })

    it("ignores role codes it does not know", () => {
        expect(stagedChanges(["legacy"], ["legacy", "player"])).toEqual([{ code: "player", action: "add" }])
    })
})

describe("isDirty and describeChange", () => {
    it("reports a difference only", () => {
        expect(isDirty(["player"], ["player"])).toBe(false)
        expect(isDirty(["player"], [])).toBe(true)
    })

    it("names a change with the option label", () => {
        expect(describeChange({ code: "gm", action: "add" })).toBe("Add Game master")
        expect(describeChange({ code: "player", action: "remove" })).toBe("Remove Player")
    })

    it("keeps known roles in option order", () => {
        expect(knownRoles(["observer", "legacy", "admin"])).toEqual(["admin", "observer"])
    })
})
