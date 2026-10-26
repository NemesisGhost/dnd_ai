import { describe, expect, it } from "vitest"
import { pickQueryStates, readQueryState, resolveReturnTo } from "./returnState"

describe("return state readers", () => {
    it("honours only a string that is a query", () => {
        expect(readQueryState({ worldSearch: "?category=npc" }, "worldSearch")).toBe("?category=npc")
        for (const bad of ["category=npc", "/elsewhere", "https://example.test/?x=1", 7, null, undefined, {}]) {
            expect(readQueryState({ worldSearch: bad }, "worldSearch")).toBeUndefined()
        }
        expect(readQueryState(null, "worldSearch")).toBeUndefined()
        expect(readQueryState("?x", "worldSearch")).toBeUndefined()
    })

    it("picks the named keys that are valid, and nothing when none are", () => {
        const state = { a: "?one", b: "nope", c: "?three", unrelated: "?x" }
        expect(pickQueryStates(state, ["a", "b", "c"] as const)).toEqual({ a: "?one", c: "?three" })
        expect(pickQueryStates(state, ["b"] as const)).toBeUndefined()
        expect(pickQueryStates(undefined, ["a"] as const)).toBeUndefined()
    })
})

describe("resolveReturnTo", () => {
    const own = "/app/c1/world/location/l1"
    const allowed = [own, "/app/c1/world/location/l1/areas"]

    it("returns to an allowed address, with its query when that is a query", () => {
        expect(resolveReturnTo({ returnTo: { pathname: own, search: "?section=details" } }, allowed, own)).toBe(
            `${own}?section=details`,
        )
        expect(resolveReturnTo({ returnTo: { pathname: allowed[1], search: "" } }, allowed, own)).toBe(allowed[1])
        expect(resolveReturnTo({ returnTo: { pathname: own, search: "section=x" } }, allowed, own)).toBe(own)
    })

    it("falls back for any address that is not the record's own", () => {
        for (const state of [
            null,
            {},
            { returnTo: { pathname: "/app/c1/world/location/other" } },
            { returnTo: { pathname: "https://example.test/" } },
            { returnTo: { pathname: 5 } },
        ]) {
            expect(resolveReturnTo(state, allowed, "/fallback")).toBe("/fallback")
        }
    })
})
