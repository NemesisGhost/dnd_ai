import { describe, expect, it } from "vitest"
import { entryContextStamp, isIdShaped, readEntryContext } from "./contexts"

const full = { v: 1, campaignId: "c1", worldId: "w1", timelineId: "t1", characterId: "ch1" }

describe("isIdShaped", () => {
    it.each(["a", "0f8fad5b-d9cb-469f-a165-0c0b0d6c1b3e", "char_b-1"])("accepts %s", (value) => {
        expect(isIdShaped(value)).toBe(true)
    })
    it.each(["", "..", "a/b", "a b", "a.b", "x".repeat(65), 7, null, undefined, {}])("rejects %s", (value) => {
        expect(isIdShaped(value)).toBe(false)
    })
})

describe("readEntryContext", () => {
    it("reads the versioned stamp", () => {
        expect(readEntryContext({ ctx: full })).toEqual({ kind: "v1", context: full })
    })

    it("keeps null as an explicit none, distinct from an absent stamp", () => {
        const none = { v: 1, campaignId: null, worldId: null, timelineId: null, characterId: null }
        expect(readEntryContext({ ctx: none })).toEqual({ kind: "v1", context: none })
        expect(readEntryContext({ ctx: { v: 1, characterId: null } })).toEqual({
            kind: "legacy-perspective",
            characterId: null,
        })
        expect(readEntryContext({})).toEqual({ kind: "absent" })
    })

    it("reads the P02-0a perspective-only stamp as legacy, recording no other level", () => {
        expect(readEntryContext({ ctx: { v: 1, characterId: "char-b" } })).toEqual({
            kind: "legacy-perspective",
            characterId: "char-b",
        })
    })

    it.each([
        ["no state", undefined],
        ["null state", null],
        ["a string state", "text"],
        ["an array state", [{ ctx: full }]],
        ["a non-object ctx", { ctx: "x" }],
        ["a null ctx", { ctx: null }],
        ["an array ctx", { ctx: [full] }],
        ["a future version", { ctx: { ...full, v: 2 } }],
        ["a missing version", { ctx: { characterId: "a" } }],
        ["a string version", { ctx: { ...full, v: "1" } }],
        ["a mistyped perspective", { ctx: { v: 1, characterId: 7 } }],
        ["a mistyped level", { ctx: { ...full, worldId: 7 } }],
        ["a non-id level", { ctx: { ...full, campaignId: "../x" } }],
        ["a partial versioned form (one extra level)", { ctx: { v: 1, characterId: "a", campaignId: "c1" } }],
        ["a partial versioned form (missing perspective)", { ctx: { v: 1, campaignId: "c", worldId: "w", timelineId: "t" } }],
    ])("treats %s as no stamp", (_label, state) => {
        expect(readEntryContext(state)).toEqual({ kind: "absent" })
    })

    it("treats a stamp naming an unauthorized perspective as no stamp, in either form", () => {
        const authorized = new Set(["ch1"])
        expect(readEntryContext({ ctx: full }, authorized).kind).toBe("v1")
        expect(readEntryContext({ ctx: { ...full, characterId: "other" } }, authorized)).toEqual({ kind: "absent" })
        expect(readEntryContext({ ctx: { v: 1, characterId: "other" } }, authorized)).toEqual({ kind: "absent" })
        // none is always authorized
        expect(readEntryContext({ ctx: { v: 1, characterId: null } }, authorized).kind).toBe("legacy-perspective")
    })

    it("is not fooled by inherited properties or a prototype-pollution shape", () => {
        const inherited = Object.create({ ctx: full })
        expect(readEntryContext(inherited)).toEqual({ kind: "absent" })
        const polluted = JSON.parse('{"ctx":{"v":1,"characterId":"a","__proto__":{"campaignId":"x"}}}')
        expect(readEntryContext(polluted)).toEqual({ kind: "legacy-perspective", characterId: "a" })
        expect(({} as { campaignId?: string }).campaignId).toBeUndefined()
    })
})

describe("entryContextStamp", () => {
    it("copies exactly the four ids at version 1", () => {
        const stamp = entryContextStamp({ ...full, extra: "label" } as never)
        expect(stamp).toEqual(full)
        expect(Object.keys(stamp).sort()).toEqual(["campaignId", "characterId", "timelineId", "v", "worldId"])
    })
})
