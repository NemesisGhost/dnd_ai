import { describe, expect, it } from "vitest"
import { SelectionArrival } from "./selectionArrival"
import { contextEligible } from "./selectionEligibility"
import type { SelectionChange, SelectionScope } from "./selectionChange"

const bootstrap = {
    campaigns: [
        { campaign_id: "alpha", world_id: "w1" },
        { campaign_id: "gamma", world_id: "w2" },
    ],
} as never

const arrival = (change: SelectionChange, scope: SelectionScope) =>
    new SelectionArrival(change, scope, { key: "k", pathname: "/", search: "", hash: "", state: null }, null)
const empty = { owner: "o", campaignId: null, worldId: null, timelineId: null, characterId: undefined, revision: 0 }
const sel = (over: Record<string, unknown>) => ({ ...empty, ...over }) as never

describe("contextEligible", () => {
    it("campaign: the committed campaign is the chosen one", () => {
        const a = arrival({ level: "campaign", id: "alpha" }, { campaignId: "alpha", worldId: null })
        expect(contextEligible(a, sel({ campaignId: "alpha" }), bootstrap)).toBe(true)
        expect(contextEligible(a, sel({ campaignId: "gamma" }), bootstrap)).toBe(false)
        expect(contextEligible(a, sel({}), bootstrap)).toBe(false)
    })

    it("world through a campaign: the marker's world must be that campaign's world and the committed campaign", () => {
        const through = arrival({ level: "world", id: "w1" }, { campaignId: "alpha", worldId: "w1" })
        expect(contextEligible(through, sel({ worldId: "w1", campaignId: "alpha" }), bootstrap)).toBe(true)
        expect(contextEligible(through, sel({ worldId: "w1", campaignId: null }), bootstrap)).toBe(false)
        const other = arrival({ level: "world", id: "w2" }, { campaignId: "alpha", worldId: "w2" })
        expect(contextEligible(other, sel({ worldId: "w2", campaignId: "alpha" }), bootstrap)).toBe(false)
        const unknown = arrival({ level: "world", id: "w1" }, { campaignId: "stranger", worldId: "w1" })
        expect(contextEligible(unknown, sel({ worldId: "w1", campaignId: "stranger" }), bootstrap)).toBe(false)
    })

    it("a direct world: only the committed world matters", () => {
        const a = arrival({ level: "world", id: "w3" }, { campaignId: null, worldId: "w3" })
        expect(contextEligible(a, sel({ worldId: "w3" }), bootstrap)).toBe(true)
        expect(contextEligible(a, sel({ worldId: "w1" }), bootstrap)).toBe(false)
    })

    it("timeline: the committed timeline and the world the route names", () => {
        const a = arrival({ level: "timeline", id: "t2" }, { campaignId: null, worldId: "w1" })
        expect(contextEligible(a, sel({ timelineId: "t2", worldId: "w1" }), bootstrap)).toBe(true)
        expect(contextEligible(a, sel({ timelineId: "t2", worldId: "w2" }), bootstrap)).toBe(false)
        expect(contextEligible(a, sel({ timelineId: null, worldId: "w1" }), bootstrap)).toBe(false)
    })

    it("character: the campaign and the committed perspective, an explicit none included", () => {
        const a = arrival({ level: "character", id: "a2", campaignId: "alpha" }, { campaignId: "alpha", worldId: null })
        expect(contextEligible(a, sel({ campaignId: "alpha", characterId: "a2" }), bootstrap)).toBe(true)
        expect(contextEligible(a, sel({ campaignId: "alpha", characterId: "a3" }), bootstrap)).toBe(false)
        expect(contextEligible(a, sel({ campaignId: "alpha", characterId: undefined }), bootstrap)).toBe(false)
        const none = arrival({ level: "character", id: null, campaignId: "alpha" }, { campaignId: "alpha", worldId: null })
        expect(contextEligible(none, sel({ campaignId: "alpha", characterId: null }), bootstrap)).toBe(true)
        expect(contextEligible(none, sel({ campaignId: "alpha", characterId: "a2" }), bootstrap)).toBe(false)
    })
})
