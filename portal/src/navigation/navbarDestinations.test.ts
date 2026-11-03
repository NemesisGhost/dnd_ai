import { describe, expect, it } from "vitest"
import type { CampaignContext } from "../types/bootstrap"
import { campaignAction, charactersAction, selectedCharacter, worldAction } from "./navbarDestinations"
import type { SelectedContextState } from "./selectedContextStore"

function campaign(overrides: Partial<CampaignContext> = {}): CampaignContext {
    return {
        campaign_id: "c1",
        campaign_name: "Alpha",
        world_id: "w1",
        world_name: "Mundivita",
        timeline_id: "t1",
        timeline_name: "Primary",
        roles: [],
        character_perspectives: [
            { character_id: "ch1", character_name: "Ixamarra", authorized_parties: [] },
            { character_id: "ch2", character_name: "Brin", authorized_parties: [] },
        ],
        selected_character_id: "ch1",
        capabilities: [],
        ...overrides,
    }
}

const selection = (overrides: Partial<SelectedContextState> = {}): SelectedContextState => ({
    owner: "o",
    campaignId: "c1",
    worldId: "w1",
    timelineId: "t1",
    characterId: undefined,
    ...overrides,
})

const elsewhere = { pathname: "/settings", currentRoot: null } as const

describe("campaignAction", () => {
    it("is a link to the selected campaign's Home away from the Campaign section", () => {
        expect(campaignAction(campaign(), elsewhere)).toEqual({
            kind: "link",
            to: "/app/c1/home",
            root: "campaign",
            name: "Open campaign Alpha",
        })
    })

    it("is a button when the current task is already a Campaign task", () => {
        expect(campaignAction(campaign(), { pathname: "/app/c1/world-times", currentRoot: "campaign" })).toEqual({
            kind: "button",
            reason: "in-section",
        })
    })

    it("is a button when the page shown is already the destination, even in another task", () => {
        expect(campaignAction(campaign(), { pathname: "/app/c1/home/", currentRoot: "parties" })).toEqual({
            kind: "button",
            reason: "at-destination",
        })
    })

    it("is a button, never a guessed link, with no campaign", () => {
        expect(campaignAction(null, elsewhere)).toEqual({ kind: "button", reason: "none" })
    })
})

describe("selectedCharacter", () => {
    it("uses the explicit choice for this campaign", () => {
        expect(selectedCharacter(campaign(), selection({ characterId: "ch2" }))).toEqual({
            characterId: "ch2",
            name: "Brin",
        })
    })

    it("treats an explicit none as no selection, not the server default", () => {
        expect(selectedCharacter(campaign(), selection({ characterId: null }))).toBeNull()
    })

    it("uses the bootstrap default only while no choice has been made for this campaign", () => {
        expect(selectedCharacter(campaign(), selection({ characterId: undefined }))).toEqual({
            characterId: "ch1",
            name: "Ixamarra",
        })
        // A choice made for another campaign says nothing about this one.
        expect(selectedCharacter(campaign(), selection({ campaignId: "other", characterId: "ch2" }))).toEqual({
            characterId: "ch1",
            name: "Ixamarra",
        })
    })

    it("drops a character the campaign no longer lists (revoked)", () => {
        expect(selectedCharacter(campaign(), selection({ characterId: "gone" }))).toBeNull()
        expect(selectedCharacter(campaign({ selected_character_id: "gone" }), selection())).toBeNull()
    })

    it("has none without a campaign", () => {
        expect(selectedCharacter(null, selection())).toBeNull()
    })
})

describe("charactersAction", () => {
    const ixamarra = { characterId: "ch1", name: "Ixamarra" }

    it("is a link to the selected character's record shell away from the Characters section", () => {
        expect(charactersAction(campaign(), ixamarra, { pathname: "/app/c1/parties", currentRoot: "parties" })).toEqual({
            kind: "link",
            to: "/app/c1/characters/ch1",
            root: "characters",
            name: "Open character Ixamarra",
        })
    })

    it("is a button inside a Characters task, and when the shell is already shown", () => {
        expect(charactersAction(campaign(), ixamarra, { pathname: "/app/c1/characters/all", currentRoot: "characters" })).toEqual({
            kind: "button",
            reason: "in-section",
        })
        expect(charactersAction(campaign(), ixamarra, { pathname: "/app/c1/characters/ch1", currentRoot: "parties" })).toEqual({
            kind: "button",
            reason: "at-destination",
        })
    })

    it("does not turn a viewed record into a destination", () => {
        // The page shows ch2, but only ch1 is selected: the link is ch1's, never ch2's.
        expect(charactersAction(campaign(), ixamarra, { pathname: "/app/c1/characters/ch2", currentRoot: "parties" })).toMatchObject({
            kind: "link",
            to: "/app/c1/characters/ch1",
        })
    })

    it("is a button with none selected or no campaign", () => {
        expect(charactersAction(campaign(), null, elsewhere)).toEqual({ kind: "button", reason: "none" })
        expect(charactersAction(null, ixamarra, elsewhere)).toEqual({ kind: "button", reason: "none" })
    })
})

describe("worldAction", () => {
    const viewable = { worldId: "w1", name: "Mundivita", canView: true, campaignId: "c1" }

    it("links to /worlds/:w when the caller is known to view it (PD-3)", () => {
        expect(worldAction(viewable, elsewhere)).toEqual({
            kind: "link",
            to: "/worlds/w1",
            root: "world",
            name: "Open world Mundivita",
        })
    })

    it("falls back to the campaign's world page without world.view, and to a button with no campaign", () => {
        expect(worldAction({ ...viewable, canView: false }, elsewhere)).toMatchObject({
            kind: "link",
            to: "/app/c1/world",
        })
        expect(worldAction({ ...viewable, canView: false, campaignId: null }, elsewhere)).toEqual({
            kind: "button",
            reason: "none",
        })
    })

    it("names the world generically when its name is unknown", () => {
        expect(worldAction({ ...viewable, name: null }, elsewhere)).toMatchObject({ name: "Open selected world" })
    })

    it("is a button inside a World task, when already at the destination, and with no world", () => {
        expect(worldAction(viewable, { pathname: "/worlds/w1/timelines", currentRoot: "world" })).toEqual({
            kind: "button",
            reason: "in-section",
        })
        expect(worldAction(viewable, { pathname: "/worlds/w1", currentRoot: "characters" })).toEqual({
            kind: "button",
            reason: "at-destination",
        })
        expect(worldAction(null, elsewhere)).toEqual({ kind: "button", reason: "none" })
    })
})
