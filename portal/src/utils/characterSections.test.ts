import { describe, expect, it } from "vitest"
import { sectionsOf } from "./characterSections"

const NONE = { details: false, sheet: false, relationships: false, inventory: false, parties: false, public_profile: false }
const ALL = { details: true, sheet: true, relationships: true, inventory: true, parties: true, public_profile: true }

describe("sectionsOf", () => {
    it("reads an answer without sections as before sections existed, and never grants the inventory or parties", () => {
        expect(sectionsOf({})).toEqual({
            details: true,
            sheet: true,
            relationships: true,
            inventory: false,
            parties: false,
            public_profile: false,
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

describe("sectionsOf public_profile", () => {
    it("reads only an explicit true as the public profile being offered", () => {
        expect(sectionsOf({ sections: { ...NONE, public_profile: true } }).public_profile).toBe(true)
        expect(sectionsOf({ sections: { ...NONE, public_profile: "yes" as unknown as boolean } }).public_profile).toBe(false)
        // An answer from before the flag existed does not offer it.
        const older = { details: true, sheet: true, relationships: true, inventory: false, parties: false }
        expect(sectionsOf({ sections: older as unknown as typeof ALL }).public_profile).toBe(false)
    })
})
