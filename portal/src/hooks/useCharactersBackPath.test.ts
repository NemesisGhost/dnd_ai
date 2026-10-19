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
        "/app/c1/world",
        "?type=npc",
        "",
    ])("ignores %s", (value) => {
        expect(readCharactersReturn("c1", { charactersReturn: value })).toBeUndefined()
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
