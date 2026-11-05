import { matchRoutes } from "react-router"
import { describe, expect, it } from "vitest"
import { readCharactersReturn } from "./legacyCharactersReturn"

const ID = "0b8f6c1e-5d2a-4c3b-9e7f-1a2b3c4d5e6f"
const ID_UPPER = ID.toUpperCase()

// The production Characters routes of App.tsx, in order, as the installed matcher sees them.
const CHARACTER_ROUTES = [
    { id: "browser", path: "/app/:campaignId/characters" },
    { id: "all", path: "/app/:campaignId/characters/all" },
    { id: "chooser", path: "/app/:campaignId/characters/new" },
    { id: "npc-new", path: "/app/:campaignId/characters/npc/new" },
    { id: "pc-new", path: "/app/:campaignId/characters/pc/new" },
    { id: "builds", path: "/app/:campaignId/characters/:characterId/builds" },
    { id: "builds-new", path: "/app/:campaignId/characters/:characterId/builds/new" },
    { id: "portrayal", path: "/app/:campaignId/characters/:characterId/portrayal" },
    { id: "edit", path: "/app/:campaignId/characters/:characterId/edit" },
    { id: "inventory", path: "/app/:campaignId/characters/:characterId/inventory" },
    { id: "sheet", path: "/app/:campaignId/characters/:characterId" },
]
const RETURN_ROUTES = new Set(["browser", "all", "sheet", "inventory"])
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

function routed(address: string) {
    const url = new URL(address, "http://return.invalid")
    const match = matchRoutes(CHARACTER_ROUTES, url.pathname)?.[0]
    return match === undefined ? undefined : { id: match.route.id, params: match.params }
}

describe("readCharactersReturn against the production route matcher", () => {
    it.each([
        "/app/c1/characters",
        "/app/c1/characters/all",
        "/app/c1/characters/all?type=player_character&q=a%2Fb&cursor=x%3D",
        `/app/c1/characters/${ID}`,
        `/app/c1/characters/${ID_UPPER}`,
        `/app/c1/characters/${ID}/inventory`,
    ])("an accepted %s matches a return route with an allowed id", (value) => {
        const accepted = readCharactersReturn("c1", { charactersReturn: value })
        expect(accepted).toBe(value)
        const match = routed(accepted ?? "")
        expect(match).toBeDefined()
        expect(RETURN_ROUTES.has(String(match?.id))).toBe(true)
        expect(match?.params.campaignId).toBe("c1")
        if (match?.params.characterId !== undefined) expect(match.params.characterId).toMatch(UUID)
    })

    it.each([
        "/app/c1/characters/New",
        "/app/c1/characters/NEW",
        "/app/c1/characters/ALL",
        "/app/c1/characters/All",
        "/app/c1/characters/NPC/New",
        "/app/c1/characters/pc/NEW",
        "/app/c1/characters/a%252Fb",
        "/app/c1/characters/a%25252Fb",
        "/app/c1/characters/%252e%252e",
        "/app/c1/characters/%2525",
        "/app/c1/characters/%6eew",
        "/app/c1/characters/%4eew",
        `/app/c1/characters/${ID}%2Fx`,
        `/app/c1/characters/${ID}%252Fx`,
        `/app/c1/characters/${ID}/Inventory`,
        `/app/c1/characters/${ID}/inventory/x`,
        `/app/c1/characters/${ID}/edit`,
        `/app/c1/characters/${ID}/builds`,
        `/app/c1/characters/${ID}/portrayal`,
        "/app/c1/characters/hero",
        "/app/c1/characters/c1",
        "/app/c1/characters/",
        "/app/c1/characters/all/",
    ])("ignores %s", (value) => {
        expect(readCharactersReturn("c1", { charactersReturn: value })).toBeUndefined()
    })

    it("documents why: the matcher routes the rejected shapes to creation or decodes a separator into the id", () => {
        expect(routed("/app/c1/characters/New")?.id).toBe("chooser")
        expect(routed("/app/c1/characters/NPC/New")?.id).toBe("npc-new")
        expect(routed("/app/c1/characters/a%252Fb")?.params.characterId).toMatch(/[/%]/)
    })
})

describe("readCharactersReturn", () => {
    it.each([
        "/app/c1/characters",
        "/app/c1/characters/all",
        "/app/c1/characters/all?type=npc&q=mi",
        "/app/c1/characters?type=npc",
        `/app/c1/characters/${ID}`,
    ])("honours %s", (value) => {
        expect(readCharactersReturn("c1", { charactersReturn: value })).toBe(value)
    })

    it.each([
        "https://evil.example/app/c1/characters",
        "//evil.example/app/c1/characters",
        "/app/c2/characters/all",
        "/app/c1/charactersX",
        "/app/c1/characters/../world",
        "/app/c1/characters/%2e%2e/%2e%2e/c2/characters/all",
        "/app/c1/characters/%2E%2e/%2e%2E/c2/characters/all",
        "/app/c1/characters/.%2e/.%2e/c2/characters/all",
        "/app/c1/characters/%2e%2e/world",
        "/app/c1/characters/%2e/%2e%2e/world",
        "/app/c1/characters/a/%2e%2e/%2e%2e/world",
        "/app/c1/characters/a%2Fb",
        "/app/c1/characters/%2fall",
        "/app/c1/characters%2f..%2fworld",
        "/app/c1%2fcharacters/all",
        "/app/c1/characters\\..\\world",
        "/app/c1\\characters/all",
        "\\\\evil.example/app/c1/characters",
        "/\\evil.example/app/c1/characters",
        "/app/c1/characters/%zz",
        "/app/c1/characters/%",
        "/app/c1/characters/all%0a",
        "/app/c1/characters/new",
        "/app/c1/characters/npc/new",
        "/app/c1/characters/a/b/c",
        "/app/c1/characters/all/extra",
        "/app/c1/characters/all#frag",
        "/app/c1/characters/.",
        "/app/c1/characters/./../world",
        "/app/c1/characters/all?x=1#/app/c2",
        "/app/c1/characters/\u0000",
        " /app/c1/characters/all",
        "/app/c1/world",
        "?type=npc",
        "",
    ])("ignores %s", (value) => {
        expect(readCharactersReturn("c1", { charactersReturn: value })).toBeUndefined()
    })

    it.each([
        `/app/c1/characters/${ID}/inventory`,
        "/app/c1/characters/all?type=player_character&q=a%2Fb&cursor=x%3D",
    ])("honours the supported destination %s unchanged", (value) => {
        expect(readCharactersReturn("c1", { charactersReturn: value })).toBe(value)
    })

    it("never accepts a target that resolves outside the campaign's Characters routes", () => {
        const crafted = [
            "/app/c1/characters/%2e%2e/%2e%2e/c2/characters/all",
            "/app/c1/characters/%2E%2E/world",
            "/app/c1/characters/.%2E/world",
        ]
        for (const value of crafted) {
            const accepted = readCharactersReturn("c1", { charactersReturn: value })
            if (accepted === undefined) continue
            expect(new URL(accepted, "http://x.invalid").pathname.startsWith("/app/c1/characters")).toBe(true)
        }
    })

    it("ignores a missing or non-string value", () => {
        expect(readCharactersReturn("c1", null)).toBeUndefined()
        expect(readCharactersReturn("c1", {})).toBeUndefined()
        expect(readCharactersReturn("c1", { charactersReturn: 3 })).toBeUndefined()
    })

    it("encodes the campaign id like the routes do", () => {
        expect(readCharactersReturn("a b", { charactersReturn: "/app/a%20b/characters/all" })).toBe(
            "/app/a%20b/characters/all",
        )
    })
})

