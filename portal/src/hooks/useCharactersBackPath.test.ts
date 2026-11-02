import { describe, expect, it } from "vitest"
import { pickCharactersReturnState, readCharactersReturn } from "./useCharactersBackPath"

describe("readCharactersReturn", () => {
    it.each([
        "/app/c1/characters",
        "/app/c1/characters/all",
        "/app/c1/characters/all?type=npc&q=mi",
        "/app/c1/characters?type=npc",
        "/app/c1/characters/npc-1",
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
        "/app/c1/characters/a%2520b",
        "/app/c1/characters/char-1/inventory",
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

describe("pickCharactersReturnState", () => {
    it("forwards only the valid key", () => {
        expect(pickCharactersReturnState("c1", { charactersReturn: "/app/c1/characters/all", x: 1 })).toEqual({
            charactersReturn: "/app/c1/characters/all",
        })
        expect(pickCharactersReturnState("c1", { charactersReturn: "/elsewhere" })).toBeUndefined()
    })
})
