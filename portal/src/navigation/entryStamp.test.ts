import { describe, expect, it } from "vitest"
import { differsOnlyInSection, entryRoot, markStamp, sameStateButCtx, stampRoot } from "./entryStamp"

describe("stamp identity", () => {
    it("only the object the writer marked is a stamp; its root is the first entry that was not one", () => {
        const first = { key: "k1", state: { announce: "Saved." } }
        const stamp1 = { ...first.state, ctx: { v: 1 } }
        markStamp(first, stamp1)

        expect(stampRoot(stamp1)).toBe("k1")
        expect(entryRoot({ key: "k2", state: stamp1 })).toBe("k1")
        // A chain keeps one root.
        const stamp2 = { ...stamp1, ctx: { v: 2 } }
        markStamp({ key: "k2", state: stamp1 }, stamp2)
        expect(stampRoot(stamp2)).toBe("k1")
    })

    it("a copy, a spread, an equal object, a forged value or a non-object is never a stamp", () => {
        const first = { key: "k1", state: { announce: "Saved." } }
        const stamped = { ...first.state, ctx: { v: 1 } }
        markStamp(first, stamped)

        expect(stampRoot({ ...stamped })).toBeNull()
        expect(stampRoot(structuredClone(stamped))).toBeNull()
        expect(stampRoot({ announce: "Saved.", ctx: { v: 1 } })).toBeNull()
        expect(stampRoot({ stampRoot: "k1" })).toBeNull()
        expect(stampRoot(null)).toBeNull()
        expect(stampRoot("k1")).toBeNull()
        expect(entryRoot({ key: "k9", state: { ...stamped } })).toBe("k9")
    })
})

describe("state comparisons", () => {
    it("sameStateButCtx ignores only ctx", () => {
        expect(sameStateButCtx({ a: 1, ctx: { v: 1 } }, { a: 1 })).toBe(true)
        expect(sameStateButCtx({ a: 1, ctx: { v: 1 } }, { a: 2, ctx: { v: 1 } })).toBe(false)
        expect(sameStateButCtx({ a: { b: [1] } }, { a: { b: [1] } })).toBe(true)
        expect(sameStateButCtx({ a: 1 }, { a: 1, b: 2 })).toBe(false)
    })

    it("differsOnlyInSection is true only for a query that differs in section alone", () => {
        expect(differsOnlyInSection("", "?section=sheet")).toBe(true)
        expect(differsOnlyInSection("?section=a", "?section=b")).toBe(true)
        expect(differsOnlyInSection("?x=1", "?x=1&section=sheet")).toBe(true)
        expect(differsOnlyInSection("?x=1", "?x=2&section=sheet")).toBe(false)
        expect(differsOnlyInSection("?section=a", "?section=a")).toBe(false)
        expect(differsOnlyInSection("", "?q=1")).toBe(false)
    })
})
