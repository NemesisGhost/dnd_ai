import { describe, expect, it } from "vitest"
import { buildFragmentLink } from "./oneTimeLink"

describe("buildFragmentLink", () => {
    it("builds a link from window.location.origin with the given path and an encoded token fragment", () => {
        const link = buildFragmentLink("/auth/activate", "raw token/with special+chars")
        expect(link).toBe(
            `${window.location.origin}/auth/activate#token=raw%20token%2Fwith%20special%2Bchars`,
        )
    })
})
