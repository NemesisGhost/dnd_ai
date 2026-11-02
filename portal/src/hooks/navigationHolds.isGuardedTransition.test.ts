import { NavigationType } from "react-router"
import type { Location } from "react-router"
import { afterEach, describe, expect, it } from "vitest"
import { isGuardedTransition, readEntryPerspective, runPermissionLossCleanup, setCommittedPerspective } from "./navigationHolds"

function at(pathname: string, state?: unknown, search = ""): Location {
    return { pathname, search, hash: "", state, key: pathname + search }
}
const committedB = { characterId: "b", defaultCharacterId: "a", authorized: new Set(["a", "b"]) }

afterEach(() => setCommittedPerspective(null))

describe("readEntryPerspective", () => {
    it("reads only a version 1 stamp naming null or an authorized id", () => {
        expect(readEntryPerspective({ ctx: { v: 1, characterId: "b" } })).toBe("b")
        expect(readEntryPerspective({ ctx: { v: 1, characterId: null } })).toBeNull()
        expect(readEntryPerspective({ ctx: { v: 1, characterId: "z" } }, new Set(["a"]))).toBeUndefined()
        expect(readEntryPerspective({ ctx: { v: 2, characterId: "b" } })).toBeUndefined()
        expect(readEntryPerspective({ ctx: { v: 1, characterId: 7 } })).toBeUndefined()
        expect(readEntryPerspective({ ctx: "x" })).toBeUndefined()
        expect(readEntryPerspective(null)).toBeUndefined()
        expect(readEntryPerspective("text")).toBeUndefined()
    })
})

describe("isGuardedTransition", () => {
    const stamp = (characterId: string | null) => ({ ctx: { v: 1, characterId } })

    it("guards a pathname change whatever the perspective", () => {
        expect(isGuardedTransition({ currentLocation: at("/a"), nextLocation: at("/b"), historyAction: NavigationType.Push })).toBe(true)
    })

    it("guards a same-path change of perspective, by PUSH or POP", () => {
        setCommittedPerspective(committedB)
        for (const historyAction of [NavigationType.Push, NavigationType.Pop]) {
            expect(isGuardedTransition({ currentLocation: at("/p"), nextLocation: at("/p", stamp("a")), historyAction })).toBe(true)
        }
    })

    it("does not guard a stamping replacement, the same perspective, or a query-only change", () => {
        setCommittedPerspective(committedB)
        expect(isGuardedTransition({ currentLocation: at("/p"), nextLocation: at("/p", stamp("b")), historyAction: NavigationType.Replace })).toBe(false)
        expect(isGuardedTransition({ currentLocation: at("/p"), nextLocation: at("/p", stamp("b")), historyAction: NavigationType.Pop })).toBe(false)
        expect(isGuardedTransition({ currentLocation: at("/p"), nextLocation: at("/p", undefined, "?s=2"), historyAction: NavigationType.Push })).toBe(false)
    })

    it("resolves an unstamped or invalid entry to the default only on Back/Forward", () => {
        setCommittedPerspective(committedB)
        expect(isGuardedTransition({ currentLocation: at("/p"), nextLocation: at("/p"), historyAction: NavigationType.Pop })).toBe(true)
        expect(isGuardedTransition({ currentLocation: at("/p"), nextLocation: at("/p", stamp("zzz")), historyAction: NavigationType.Pop })).toBe(true)
        expect(isGuardedTransition({ currentLocation: at("/p"), nextLocation: at("/p"), historyAction: NavigationType.Push })).toBe(false)
        setCommittedPerspective({ ...committedB, characterId: "a" })
        expect(isGuardedTransition({ currentLocation: at("/p"), nextLocation: at("/p"), historyAction: NavigationType.Pop })).toBe(false)
    })

    it("never guards on perspective outside a campaign workspace", () => {
        expect(isGuardedTransition({ currentLocation: at("/p"), nextLocation: at("/p", stamp("a")), historyAction: NavigationType.Pop })).toBe(false)
    })
})

describe("runPermissionLossCleanup", () => {
    const guarded = (current: Location, next: Location, action: NavigationType) =>
        isGuardedTransition({ currentLocation: current, nextLocation: next, historyAction: action })

    it("exempts only a same-path REPLACE of the named entry, only while it runs", () => {
        setCommittedPerspective(committedB)
        const entry = at("/p", { ctx: { v: 1, characterId: "zzz" } })
        const stale = at("/p", { ctx: { v: 1, characterId: "a" } })
        expect(guarded(entry, stale, NavigationType.Replace)).toBe(true)
        runPermissionLossCleanup(entry.key, () => {
            expect(guarded(entry, stale, NavigationType.Replace)).toBe(false)
            // Not another entry, not another path, not a PUSH or POP.
            expect(guarded(at("/other"), stale, NavigationType.Replace)).toBe(true)
            expect(guarded(entry, at("/elsewhere"), NavigationType.Replace)).toBe(true)
            expect(guarded(entry, stale, NavigationType.Push)).toBe(true)
            expect(guarded(entry, stale, NavigationType.Pop)).toBe(true)
        })
        expect(guarded(entry, stale, NavigationType.Replace)).toBe(true)
    })

    it("releases the exemption when the cleanup throws", () => {
        setCommittedPerspective(committedB)
        const entry = at("/p")
        const stale = at("/p", { ctx: { v: 1, characterId: "a" } })
        expect(() =>
            runPermissionLossCleanup(entry.key, () => {
                throw new Error("boom")
            }),
        ).toThrow("boom")
        expect(guarded(entry, stale, NavigationType.Replace)).toBe(true)
    })
})
