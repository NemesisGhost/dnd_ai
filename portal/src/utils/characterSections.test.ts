import { describe, expect, it } from "vitest"
import { sectionsOf } from "./characterSections"

const NONE = { details: false, sheet: false, relationships: false, inventory: false, parties: false }
const ALL = { details: true, sheet: true, relationships: true, inventory: true, parties: true }

describe("sectionsOf", () => {
    it("reads an answer without sections as before sections existed, and never grants the inventory or parties", () => {
        expect(sectionsOf({})).toEqual({
            details: true,
            sheet: true,
            relationships: true,
            inventory: false,
            parties: false,
        })
    })

    it("treats an explicit all-false answer as the server's decision, not as missing data", () => {
        expect(sectionsOf({ sections: NONE })).toEqual(NONE)
    })

    it("treats an explicit all-true answer as granted", () => {
        expect(sectionsOf({ sections: ALL })).toEqual(ALL)
    })

    it("treats a flag missing from a present answer as not offered, never as the legacy default", () => {
        const partial = { details: true, inventory: true } as unknown as typeof ALL
        expect(sectionsOf({ sections: partial })).toEqual({ ...NONE, details: true, inventory: true })
        // An empty object is an answer too: nothing is offered, not the legacy sheet and relationships.
        expect(sectionsOf({ sections: {} as unknown as typeof ALL })).toEqual(NONE)
    })

    it("does not read a null sections as granting anything beyond the legacy fallback", () => {
        expect(sectionsOf({ sections: null as unknown as undefined }).inventory).toBe(false)
    })
})
