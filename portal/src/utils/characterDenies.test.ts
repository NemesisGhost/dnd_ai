import { describe, expect, it } from "vitest"
import type { AccessResourceGrantSummary, DeniableCharacterCapability } from "../types/accessOverview"
import {
    availableDenyCapabilities,
    canOfferCharacterDeny,
    denyHint,
    denyLabel,
    denyReturns,
} from "./characterDenies"

const view: DeniableCharacterCapability = { capability_id: "1", code: "campaign.view", display_name: "View Campaign" }
const edit: DeniableCharacterCapability = { capability_id: "2", code: "canon.edit", display_name: "Edit Canon" }
const other: DeniableCharacterCapability = { capability_id: "3", code: "x.y", display_name: "X Y" }

const grant = (over: Partial<AccessResourceGrantSummary>): AccessResourceGrantSummary => ({
    resource_grant_id: "g",
    capability_code: "campaign.view",
    capability_display_name: "View Campaign",
    effect: "deny",
    target_type: "entity",
    target_id: "ch1",
    target_display_name: "Aria",
    reason: null,
    granted_at: "2026-01-01T00:00:00Z",
    expires_at: null,
    ...over,
})

describe("characterDenies", () => {
    it("offers the kind only with a server list and a character", () => {
        const chars = [{ character_id: "ch1", display_name: "Aria" }]
        expect(canOfferCharacterDeny([view], chars)).toBe(true)
        expect(canOfferCharacterDeny([], chars)).toBe(false)
        expect(canOfferCharacterDeny(undefined, chars)).toBe(false)
        expect(canOfferCharacterDeny([view], [])).toBe(false)
    })

    it("words the two known permissions precisely and invents nothing for another", () => {
        expect(denyLabel(view)).toBe("Everything about this character")
        expect(denyLabel(edit)).toBe("Editing this character's profiles")
        expect(denyLabel(other)).toBe("X Y")
        expect(denyHint("x.y")).toBeNull()
        expect(denyReturns("x.y", "Aria")).toBeNull()
        expect(denyReturns("campaign.view", "Aria")).toMatch(/another source/)
        expect(denyReturns("canon.edit", "Aria")).toBe("They may be able to edit Aria's profiles again.")
    })

    it("hides only a deny already active for this character on an entity target, keeping server order", () => {
        const list = [view, edit, other]
        expect(availableDenyCapabilities(list, [], "ch1")).toEqual(list)
        expect(availableDenyCapabilities(list, [grant({})], "ch1")).toEqual([edit, other])
        // another character, an allow, a character-kind grant and another code do not hide anything
        for (const g of [
            grant({ target_id: "ch2" }),
            grant({ effect: "allow" }),
            grant({ target_type: "character" }),
            grant({ capability_code: "other" }),
        ]) {
            expect(availableDenyCapabilities(list, [g], "ch1")).toEqual(list)
        }
        expect(availableDenyCapabilities(list, [grant({})], "")).toEqual(list)
    })
})
