import { describe, expect, it } from "vitest"
import { retainedChanges } from "./retainedChanges"

describe("retainedChanges", () => {
    const loaded = { name: "Founders Hall", summary: "The secret vault is under the dais.", population: 40 }

    it("keeps only the fields the person changed, never what the server had sent", () => {
        const kept = retainedChanges(loaded, { ...loaded, name: "Founders' Hall" }, "")
        expect(kept).toEqual([{ label: "Name", value: "Founders' Hall" }])
        expect(JSON.stringify(kept)).not.toContain("secret vault")
    })

    it("keeps a cleared field as cleared, not as the loaded text", () => {
        expect(retainedChanges(loaded, { ...loaded, summary: "" }, "")).toEqual([
            { label: "Summary", value: "(cleared)" },
        ])
    })

    it("keeps the change note", () => {
        expect(retainedChanges(loaded, loaded, "  fixed the spelling ")).toEqual([
            { label: "Change note", value: "fixed the spelling" },
        ])
    })

    it("keeps nothing when nothing changed", () => {
        expect(retainedChanges(loaded, { ...loaded }, "")).toEqual([])
    })

    it("compares nested values structurally", () => {
        const a = { tags: ["x", "y"] }
        expect(retainedChanges(a, { tags: ["x", "y"] }, "")).toEqual([])
        expect(retainedChanges(a, { tags: ["x", "z"] }, "")).toEqual([{ label: "Tags", value: '["x","z"]' }])
    })

    it("keeps nothing for values that are not plain objects of fields", () => {
        expect(retainedChanges("loaded text", "typed text", "")).toEqual([])
        expect(retainedChanges(["a"], ["b"], "")).toEqual([])
    })
})
