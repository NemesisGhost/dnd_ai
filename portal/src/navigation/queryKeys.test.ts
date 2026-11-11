import type { Location } from "react-router"
import { describe, expect, it } from "vitest"
import { PERSPECTIVE_QUERY_CHANGED, queryKeysChanged } from "./queryKeys"

const at = (search: string): Location => ({ pathname: "/p", search, hash: "", state: null, key: "k" })

describe("PERSPECTIVE_QUERY_CHANGED", () => {
    it("is true for a changed, added or removed character or party", () => {
        expect(PERSPECTIVE_QUERY_CHANGED(at("?character_id=a"), at("?character_id=b"))).toBe(true)
        expect(PERSPECTIVE_QUERY_CHANGED(at(""), at("?party_id=p"))).toBe(true)
        expect(PERSPECTIVE_QUERY_CHANGED(at("?character_id=a&party_id=p"), at("?character_id=a"))).toBe(true)
    })

    it("is false for the same values in any order and for every other key", () => {
        expect(PERSPECTIVE_QUERY_CHANGED(at("?character_id=a&party_id=p"), at("?party_id=p&character_id=a"))).toBe(false)
        expect(PERSPECTIVE_QUERY_CHANGED(at("?character_id=a&section=x"), at("?character_id=a&section=y&q=1"))).toBe(false)
        expect(PERSPECTIVE_QUERY_CHANGED(at(""), at(""))).toBe(false)
    })

    it("compares only the named keys", () => {
        expect(queryKeysChanged("section")(at("?section=a"), at("?section=b"))).toBe(true)
        expect(queryKeysChanged("section")(at("?character_id=a"), at("?character_id=b"))).toBe(false)
    })
})
