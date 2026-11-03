import { describe, expect, it } from "vitest"
import type { CampaignContext } from "../types/bootstrap"
import {
    campaignAction,
    charactersAction,
    isSameDestination,
    selectedCharacter,
    worldAction,
} from "./navbarDestinations"
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

const elsewhere = { pathname: "/settings" }

describe("isSameDestination (route and parameters, never a prefix)", () => {
    it("ignores a trailing slash and compares the same route's ids", () => {
        expect(isSameDestination("/app/c1/characters/ch1/", "/app/c1/characters/ch1")).toBe(true)
        expect(isSameDestination("/app/c1/characters/ch2", "/app/c1/characters/ch1")).toBe(false)
        expect(isSameDestination("/app/c2/characters/ch1", "/app/c1/characters/ch1")).toBe(false)
    })

    it("treats a deeper or different route as a different destination, not a prefix match", () => {
        expect(isSameDestination("/app/c1/characters/ch1/edit", "/app/c1/characters/ch1")).toBe(false)
        expect(isSameDestination("/app/c1/characters/all", "/app/c1/characters/ch1")).toBe(false)
        expect(isSameDestination("/worlds/w1/timelines", "/worlds/w1")).toBe(false)
        expect(isSameDestination("/app/c1/home-extra", "/app/c1/home")).toBe(false)
    })

    it("falls back to the exact path for an address route metadata does not know", () => {
        expect(isSameDestination("/nowhere/a", "/nowhere/a/")).toBe(true)
        expect(isSameDestination("/nowhere/a/b", "/nowhere/a")).toBe(false)
    })
})

describe("campaignAction", () => {
    it("is a link to the selected campaign's Home on any other page, whatever the task", () => {
        expect(campaignAction(campaign(), elsewhere)).toEqual({
            kind: "link",
            to: "/app/c1/home",
            root: "campaign",
            detail: "Alpha",
        })
        // A page of the Campaign task that is not Home (world time) still offers the way to Home.
        expect(campaignAction(campaign(), { pathname: "/app/c1/world-times" })).toMatchObject({
            kind: "link",
            to: "/app/c1/home",
        })
    })

    it("is a button when the page shown is Home, however its address is spelled", () => {
        expect(campaignAction(campaign(), { pathname: "/app/c1/home/" })).toEqual({
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

    it("is a link to the selected character's record shell on any other page", () => {
        expect(charactersAction(campaign(), ixamarra, { pathname: "/app/c1/parties" })).toEqual({
            kind: "link",
            to: "/app/c1/characters/ch1",
            root: "characters",
            detail: "Ixamarra",
        })
    })

    it("offers the selected record while a different one is viewed, even inside a Characters task", () => {
        // ch2 is on screen under the Characters task; ch1 is the selection: the way to ch1 is offered.
        expect(charactersAction(campaign(), ixamarra, { pathname: "/app/c1/characters/ch2" })).toMatchObject({
            kind: "link",
            to: "/app/c1/characters/ch1",
        })
        expect(charactersAction(campaign(), ixamarra, { pathname: "/app/c1/characters/all" })).toMatchObject({
            kind: "link",
            to: "/app/c1/characters/ch1",
        })
        expect(charactersAction(campaign(), ixamarra, { pathname: "/app/c1/characters/ch1/edit" })).toMatchObject({
            kind: "link",
            to: "/app/c1/characters/ch1",
        })
    })

    it("is a button once the selected record's shell is the page shown", () => {
        expect(charactersAction(campaign(), ixamarra, { pathname: "/app/c1/characters/ch1" })).toEqual({
            kind: "button",
            reason: "at-destination",
        })
    })

    it("is a button with none selected or no campaign", () => {
        expect(charactersAction(campaign(), null, elsewhere)).toEqual({ kind: "button", reason: "none" })
        expect(charactersAction(null, ixamarra, elsewhere)).toEqual({ kind: "button", reason: "none" })
    })
})

describe("worldAction", () => {
    const viewable = { worldId: "w1", name: "Mundivita", canView: true, campaignId: "c1" }

    it("links to /worlds/:w when the caller is known to view it (PD-3), from any other page", () => {
        expect(worldAction(viewable, elsewhere)).toEqual({
            kind: "link",
            to: "/worlds/w1",
            root: "world",
            detail: "Mundivita",
        })
        // Inside the World task, on another world page.
        expect(worldAction(viewable, { pathname: "/worlds/w1/timelines" })).toMatchObject({
            kind: "link",
            to: "/worlds/w1",
        })
        expect(worldAction(viewable, { pathname: "/worlds/w2" })).toMatchObject({ kind: "link", to: "/worlds/w1" })
    })

    it("falls back to the campaign world page without world.view, and to a button with no campaign", () => {
        expect(worldAction({ ...viewable, canView: false }, elsewhere)).toMatchObject({
            kind: "link",
            to: "/app/c1/world",
        })
        expect(worldAction({ ...viewable, canView: false }, { pathname: "/app/c1/world" })).toEqual({
            kind: "button",
            reason: "at-destination",
        })
        expect(worldAction({ ...viewable, canView: false, campaignId: null }, elsewhere)).toEqual({
            kind: "button",
            reason: "none",
        })
    })

    it("names the world generically when its name is unknown", () => {
        expect(worldAction({ ...viewable, name: null }, elsewhere)).toMatchObject({ detail: "selected world" })
    })

    it("is a button when already at the world's details, and with no world", () => {
        expect(worldAction(viewable, { pathname: "/worlds/w1" })).toEqual({ kind: "button", reason: "at-destination" })
        expect(worldAction(null, elsewhere)).toEqual({ kind: "button", reason: "none" })
    })
})
