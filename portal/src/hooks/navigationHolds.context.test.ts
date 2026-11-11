import { NavigationType } from "react-router"
import type { Location } from "react-router"
import { afterEach, describe, expect, it } from "vitest"
import { queryKeysChanged } from "../navigation/queryKeys"
import {
    isGuardedTransition,
    runPermissionLossCleanup,
    setCommittedContext,
    setCommittedPerspective,
} from "./navigationHolds"
import type { CommittedContext } from "./navigationHolds"

// The shared transition predicate over the full entry context (P02-1). The perspective-only cases it
// generalizes stay in navigationHolds.isGuardedTransition.test.ts and must keep passing unchanged.

function at(pathname: string, state?: unknown, search = "", key = pathname + search): Location {
    return { pathname, search, hash: "", state, key }
}
const stamp = (over: Record<string, unknown> = {}) => ({
    ctx: { v: 1, campaignId: "c1", worldId: "w1", timelineId: "t1", characterId: "b", ...over },
})
const committed: CommittedContext = {
    characterId: "b",
    defaultCharacterId: "a",
    authorized: new Set(["a", "b"]),
    campaignId: "c1",
    worldId: "w1",
    timelineId: "t1",
}
const { Push, Replace, Pop } = NavigationType
const guarded = (next: Location, action: NavigationType, current = at("/p"), options?: Parameters<typeof isGuardedTransition>[1]) =>
    isGuardedTransition({ currentLocation: current, nextLocation: next, historyAction: action }, options)

afterEach(() => setCommittedContext(null))

describe("isGuardedTransition over the full entry context", () => {
    it("treats the old and new setters as one", () => {
        expect(setCommittedPerspective).toBe(setCommittedContext)
    })

    it.each([Push, Replace, Pop])("never guards a stamp equal to the committed context (%s)", (action) => {
        setCommittedContext(committed)
        expect(guarded(at("/p", stamp()), action)).toBe(false)
    })

    it.each([
        ["campaign", { campaignId: "c2" }],
        ["world", { worldId: "w2" }],
        ["timeline", { timelineId: "t2" }],
        ["perspective", { characterId: "a" }],
        ["perspective to none", { characterId: null }],
        ["a level to none", { timelineId: null }],
    ])("guards a same-path change of %s, by PUSH and by POP", (_label, over) => {
        setCommittedContext(committed)
        expect(guarded(at("/p", stamp(over)), Push)).toBe(true)
        expect(guarded(at("/p", stamp(over)), Pop)).toBe(true)
    })

    it("does not compare a level the owner has not committed", () => {
        setCommittedContext({ characterId: "b", defaultCharacterId: "a", authorized: new Set(["a", "b"]) })
        expect(guarded(at("/p", stamp({ campaignId: "zzz", worldId: "zzz", timelineId: "zzz" })), Pop)).toBe(false)
        expect(guarded(at("/p", stamp({ characterId: "a" })), Pop)).toBe(true)
    })

    it("does not compare a level the stamp does not record (the P02-0a stamp)", () => {
        setCommittedContext(committed)
        expect(guarded(at("/p", { ctx: { v: 1, characterId: "b" } }), Pop)).toBe(false)
        expect(guarded(at("/p", { ctx: { v: 1, characterId: "a" } }), Pop)).toBe(true)
    })

    it("treats null as a committed value, different from not committed", () => {
        setCommittedContext({ ...committed, worldId: null })
        expect(guarded(at("/p", stamp({ worldId: null })), Pop)).toBe(false)
        expect(guarded(at("/p", stamp({ worldId: "w1" })), Pop)).toBe(true)
    })

    it("resolves an unstamped, malformed or unauthorized entry to the default on POP only", () => {
        setCommittedContext(committed)
        for (const state of [undefined, { ctx: { v: 2 } }, { ctx: { ...stamp().ctx, characterId: "zzz" } }, { ctx: "x" }]) {
            expect(guarded(at("/p", state), Pop), JSON.stringify(state)).toBe(true)
            expect(guarded(at("/p", state), Push), JSON.stringify(state)).toBe(false)
            expect(guarded(at("/p", state), Replace), JSON.stringify(state)).toBe(false)
        }
        setCommittedContext({ ...committed, characterId: "a" })
        expect(guarded(at("/p"), Pop)).toBe(false)
    })

    it("never guards a stamp-only or hint-strip REPLACE, which keeps path and context", () => {
        setCommittedContext(committed)
        const stampOnly = at("/p", { ...stamp(), task: { v: 1 } }, "", "same")
        expect(guarded(stampOnly, Replace, at("/p", undefined, "", "same"))).toBe(false)
    })

    it("keeps a pathname change guarded with no committed context", () => {
        expect(guarded(at("/q"), Push)).toBe(true)
        expect(guarded(at("/p", stamp({ characterId: "zzz" })), Pop)).toBe(false)
    })

    it("keeps the permission-loss exemption exactly as narrow as before", () => {
        setCommittedContext(committed)
        const current = at("/p", stamp(), "?x=1", "entry")
        const next = at("/p", stamp({ characterId: null }), "", "entry")
        let during: boolean | null = null
        runPermissionLossCleanup("entry", () => {
            during = guarded(next, Replace, current)
        })
        expect(during).toBe(false)
        expect(guarded(next, Replace, current)).toBe(true)
        runPermissionLossCleanup("entry", () => {
            expect(guarded(at("/q"), Replace, current)).toBe(true)
            expect(guarded(next, Push, current)).toBe(true)
        })
    })
})

describe("the query rule", () => {
    const here = at("/p", undefined, "?section=a&step=1")
    const to = (search: string) => at("/p", undefined, search)
    const disposing = { disposingQuery: queryKeysChanged("step", "party_id") }

    it("never guards a query-only change when no option is given (default compatibility)", () => {
        setCommittedContext(committed)
        expect(guarded(to("?section=b&step=2"), Push, here)).toBe(false)
        expect(guarded(to(""), Replace, here)).toBe(false)
        // Back/Forward to an unstamped entry is still the context rule's business (the default differs
        // from the committed perspective here), not the query's: with equal defaults it is unguarded.
        setCommittedContext({ ...committed, defaultCharacterId: "b" })
        expect(guarded(to(""), Pop, here)).toBe(false)
    })

    it("guards a query-only change the caller declares disposing, and only that one", () => {
        expect(guarded(to("?section=a&step=2"), Push, here, disposing)).toBe(true)
        expect(guarded(to("?section=a"), Push, here, disposing)).toBe(true)
        expect(guarded(to("?section=a&step=1&party_id=p"), Pop, here, disposing)).toBe(true)
        expect(guarded(to("?section=b&step=1"), Push, here, disposing)).toBe(false)
        expect(guarded(to("?step=1&section=a"), Push, here, disposing)).toBe(false)
    })

    it("does not evaluate the declaration when the query is unchanged", () => {
        let calls = 0
        const options = { disposingQuery: () => (calls++, true) }
        expect(guarded(at("/p", undefined, "?a=1"), Replace, at("/p", undefined, "?a=1"), options)).toBe(false)
        expect(calls).toBe(0)
    })

    it("lets the permission-loss exemption win over a disposing query", () => {
        const current = at("/p", undefined, "?step=1", "entry")
        runPermissionLossCleanup("entry", () => {
            expect(guarded(at("/p", undefined, "?step=2", "entry"), Replace, current, disposing)).toBe(false)
        })
    })

    it("never lets a declaration weaken a pathname or context change", () => {
        setCommittedContext(committed)
        const never = { disposingQuery: () => false }
        expect(guarded(at("/q"), Push, here, never)).toBe(true)
        expect(guarded(at("/p", stamp({ characterId: "a" })), Push, here, never)).toBe(true)
    })
})

describe("queryKeysChanged", () => {
    const loc = (search: string) => at("/p", undefined, search)
    it("compares the value list of the named keys only", () => {
        const changed = queryKeysChanged("a")
        expect(changed(loc("?a=1&b=1"), loc("?a=1&b=2"))).toBe(false)
        expect(changed(loc("?a=1"), loc("?a=2"))).toBe(true)
        expect(changed(loc("?a=1"), loc(""))).toBe(true)
        expect(changed(loc(""), loc("?a=1"))).toBe(true)
        expect(changed(loc("?a=1&a=2"), loc("?a=1"))).toBe(true)
        expect(changed(loc("?a=1&a=2"), loc("?b=0&a=1&a=2"))).toBe(false)
    })
    it("is false with no keys", () => {
        expect(queryKeysChanged()(loc("?a=1"), loc("?a=2"))).toBe(false)
    })
})

describe("a route-scoped owner (the campaign layout)", () => {
    const scoped: CommittedContext = { ...committed, routeScoped: true }

    it("treats a versioned stamp naming another campaign, world or timeline as no stamp", () => {
        setCommittedContext(scoped)
        for (const over of [{ campaignId: "c2" }, { worldId: "w2" }, { timelineId: "t2" }]) {
            // PUSH/REPLACE with no valid stamp keeps the committed context; POP resolves to the default (a ≠ b).
            expect(guarded(at("/p", stamp(over)), Push)).toBe(false)
            expect(guarded(at("/p", stamp(over)), Replace)).toBe(false)
            expect(guarded(at("/p", stamp(over)), Pop)).toBe(true)
        }
    })

    it("still compares a stamp made under this scope, and the perspective-only stamp", () => {
        setCommittedContext(scoped)
        expect(guarded(at("/p", stamp({ characterId: "a" })), Push)).toBe(true)
        expect(guarded(at("/p", stamp()), Pop)).toBe(false)
        expect(guarded(at("/p", { ctx: { v: 1, characterId: "a" } }), Pop)).toBe(true)
        expect(guarded(at("/p", { ctx: { v: 1, characterId: "b" } }), Pop)).toBe(false)
    })

    it("an owner that is not route-scoped compares the levels as before", () => {
        setCommittedContext(committed)
        expect(guarded(at("/p", stamp({ campaignId: "c2" })), Push)).toBe(true)
    })
})
