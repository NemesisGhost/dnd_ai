import { describe, expect, it } from "vitest"
import { isContextStamp } from "./entryStamp"

const ctx = { v: 1, campaignId: "alpha", worldId: "w1", timelineId: "t-w1", characterId: null }
const entry = (state: unknown, extra: Partial<{ pathname: string; search: string; hash: string }> = {}) => ({
    pathname: "/worlds/w1",
    search: "",
    hash: "",
    state,
    ...extra,
})

describe("isContextStamp", () => {
    const arrived = entry({ announce: "Saved." })

    it("the same entry with only a well-formed ctx added or changed is a stamp", () => {
        expect(isContextStamp(arrived, entry({ announce: "Saved.", ctx }))).toBe(true)
        expect(
            isContextStamp(entry({ announce: "Saved.", ctx }), entry({ announce: "Saved.", ctx: { ...ctx, characterId: "a1" } })),
        ).toBe(true)
    })

    it("a distinct operation repeating the same message and address, without a stamp, is not", () => {
        expect(isContextStamp(entry({ announce: "Saved.", ctx }), entry({ announce: "Saved." }))).toBe(false)
        expect(isContextStamp(arrived, entry({ announce: "Saved." }))).toBe(false)
    })

    it.each([
        ["another message", entry({ announce: "Deleted.", ctx })],
        ["an added key", entry({ announce: "Saved.", extra: 1, ctx })],
        ["another query", entry({ announce: "Saved.", ctx }, { search: "?q=1" })],
        ["a hash", entry({ announce: "Saved.", ctx }, { hash: "#a" })],
        ["another path", entry({ announce: "Saved.", ctx }, { pathname: "/worlds/w2" })],
        ["a malformed ctx", entry({ announce: "Saved.", ctx: { v: 2 } })],
    ])("%s is not a stamp", (_name, after) => {
        expect(isContextStamp(arrived, after)).toBe(false)
    })

    it("a staged page's own section is tolerated only on request", () => {
        const before = entry({ ctx })
        const after = entry({ ctx }, { search: "?section=sheet" })
        expect(isContextStamp(before, after)).toBe(false)
        expect(isContextStamp(before, after, { tolerateSection: true })).toBe(true)
    })
})
