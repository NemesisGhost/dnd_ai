import { describe, expect, it } from "vitest"
import { createArrivalTracker } from "./selectionArrivalTracker"
import { readSelectionChange } from "./selectionChange"

type Action = "PUSH" | "REPLACE" | "POP"
interface Fake {
    state: {
        location: { key: string; pathname: string; search: string; hash: string; state: unknown }
        historyAction: Action
    }
    listeners: Set<(state: Fake["state"]) => void>
}

// The router as the tracker sees it: committed locations, announced to subscribers as they happen.
function fakeRouter(initial = { key: "k0", pathname: "/start" }, state: unknown = null, action: Action = "POP") {
    const fake: Fake = {
        state: { location: { search: "", hash: "", ...initial, state }, historyAction: action },
        listeners: new Set(),
    }
    const router = {
        get state() {
            return fake.state
        },
        subscribe(listener: (state: Fake["state"]) => void) {
            fake.listeners.add(listener)
            return () => {
                fake.listeners.delete(listener)
            }
        },
    }
    const commit = (
        key: string,
        pathname: string,
        action: Action,
        state: unknown = null,
        extra: { search?: string; hash?: string } = {},
    ) => {
        fake.state = { location: { key, pathname, search: "", hash: "", ...extra, state }, historyAction: action }
        fake.listeners.forEach((listener) => listener(fake.state))
    }
    return { router, commit }
}

const choice = { selection: { level: "character", id: "a2", campaignId: "alpha" } }
const task = { v: 1, root: "characters", scope: { campaignId: "alpha" }, trail: [] }
const stamped = (characterId: string | null = "a2") => ({
    task,
    ...choice,
    ctx: { v: 1, campaignId: "alpha", worldId: "w1", timelineId: "t-w1", characterId },
})
const DETAILS = "/app/alpha/characters/a2"

describe("createArrivalTracker", () => {
    it("a PUSH that carries a selection is an arrival, noting the campaign selected before it", () => {
        const { router, commit } = fakeRouter()
        const tracker = createArrivalTracker(router as never, () => "alpha")
        tracker.subscribe(() => undefined)
        expect(tracker.getSnapshot()).toBeNull()

        commit("k1", DETAILS, "PUSH", choice)

        const arrival = tracker.getSnapshot()
        expect(arrival?.change).toEqual({ level: "character", id: "a2", campaignId: "alpha" })
        expect(arrival?.campaignBefore).toBe("alpha")
    })

    describe("a note must belong to the destination it arrived at", () => {
        const cases: Array<[string, string, unknown]> = [
            ["a character note on another route", "/app/alpha/knowledge", choice],
            ["a character note on another character", "/app/alpha/characters/a3", choice],
            ["a character note on another campaign", "/app/beta/characters/a2", choice],
            ["a none note on a character's details", DETAILS, { selection: { level: "character", id: null, campaignId: "alpha" } }],
            ["a character note on All characters", "/app/alpha/characters/all", choice],
            ["a campaign note on another campaign's Home", "/app/beta/home", { selection: { level: "campaign", id: "alpha" } }],
            ["a campaign note on a deeper campaign route", "/app/alpha/home/extra", { selection: { level: "campaign", id: "alpha" } }],
            ["a world note on another world", "/worlds/w2", { selection: { level: "world", id: "w1" } }],
            ["a world note on a timeline page", "/worlds/w1/timelines/t1", { selection: { level: "world", id: "w1" } }],
            ["a timeline note on another timeline", "/worlds/w1/timelines/t9", { selection: { level: "timeline", id: "t2" } }],
            ["a timeline note on the world page", "/worlds/w1", { selection: { level: "timeline", id: "t2" } }],
            ["a note on an unscoped route", "/settings", { selection: { level: "campaign", id: "alpha" } }],
        ]
        it.each(cases)("%s is not an arrival", (_name, path, state) => {
            const { router, commit } = fakeRouter()
            const tracker = createArrivalTracker(router as never, () => null)
            tracker.subscribe(() => undefined)
            commit("k1", path, "PUSH", state)
            expect(tracker.getSnapshot()).toBeNull()
        })

        it.each([
            ["character details", DETAILS, choice, { campaignId: "alpha", worldId: null }],
            [
                "character none",
                "/app/alpha/characters/all",
                { selection: { level: "character", id: null, campaignId: "alpha" } },
                { campaignId: "alpha", worldId: null },
            ],
            ["campaign", "/app/beta/home", { selection: { level: "campaign", id: "beta" } }, { campaignId: "beta", worldId: null }],
            ["world", "/worlds/w2", { selection: { level: "world", id: "w2" } }, { campaignId: null, worldId: "w2" }],
            [
                "world through a campaign",
                "/app/alpha/world",
                { selection: { level: "world", id: "w1" } },
                { campaignId: "alpha", worldId: "w1" },
            ],
            [
                "timeline",
                "/worlds/w1/timelines/t2",
                { selection: { level: "timeline", id: "t2" } },
                { campaignId: null, worldId: "w1" },
            ],
        ])("%s is an arrival with the scope its address names", (_name, path, state, scope) => {
            const { router, commit } = fakeRouter()
            const tracker = createArrivalTracker(router as never, () => null)
            tracker.subscribe(() => undefined)
            commit("k1", path, "PUSH", state)
            expect(tracker.getSnapshot()?.scope).toEqual(scope)
        })
    })

    describe("a REPLACE keeps the arrival only when it is the entry's own stamp", () => {
        const arrive = (state: unknown = { task, ...choice }) => {
            const { router, commit } = fakeRouter()
            const tracker = createArrivalTracker(router as never, () => null)
            tracker.subscribe(() => undefined)
            commit("k1", DETAILS, "PUSH", state)
            return { tracker, commit, arrival: tracker.getSnapshot() }
        }

        it("the stamp of the same address and state keeps it; the new key is the same arrival's", () => {
            const { tracker, commit, arrival } = arrive()
            commit("k2", DETAILS, "REPLACE", stamped("a2"))
            expect(tracker.getSnapshot()).toBe(arrival)
            expect(arrival?.owns("k1")).toBe(true)
            expect(arrival?.owns("k2")).toBe(true)
        })

        it("a stamp that still records the selection from before the choice is the same stamp", () => {
            const { tracker, commit, arrival } = arrive()
            commit("k2", DETAILS, "REPLACE", stamped("a1"))
            expect(tracker.getSnapshot()).toBe(arrival)
        })

        it("a second stamp of the stamped entry keeps it too", () => {
            const { tracker, commit, arrival } = arrive()
            commit("k2", DETAILS, "REPLACE", stamped("a1"))
            commit("k3", DETAILS, "REPLACE", stamped("a2"))
            expect(tracker.getSnapshot()).toBe(arrival)
            expect(arrival?.owns("k3")).toBe(true)
        })

        it("the default section a staged page writes for itself keeps it; no other query does", () => {
            const { tracker, commit, arrival } = arrive()
            commit("k2", DETAILS, "REPLACE", stamped("a2"), { search: "?section=sheet" })
            expect(tracker.getSnapshot()).toBe(arrival)
            commit("k3", DETAILS, "REPLACE", stamped("a2"), { search: "?section=sheet&q=x" })
            expect(tracker.getSnapshot()).toBeNull()
        })

        it.each([
            ["another query", DETAILS, stamped("a2"), { search: "?q=elsewhere" }],
            ["a hash", DETAILS, stamped("a2"), { hash: "#notes" }],
            [
                "another marker",
                DETAILS,
                { ...stamped("a2"), selection: { level: "character", id: "a3", campaignId: "alpha" } },
                {},
            ],
            ["no marker", DETAILS, { task, ctx: stamped("a2").ctx }, {}],
            ["another task", DETAILS, { ...stamped("a2"), task: { ...task, root: "world" } }, {}],
            ["another task trail", DETAILS, { ...stamped("a2"), task: { ...task, trail: [{ route: "x" }] } }, {}],
            ["unrelated state", DETAILS, { ...stamped("a2"), charactersReturn: "/app/alpha/characters/all" }, {}],
            ["no stamp at all", DETAILS, { task, ...choice }, {}],
            ["a malformed stamp", DETAILS, { task, ...choice, ctx: { v: 2, characterId: "a2" } }, {}],
            ["another path", "/app/alpha/characters/a3", stamped("a2"), {}],
        ])("same entry, %s: ends the arrival", (_name, path, state, extra) => {
            const { tracker, commit } = arrive()
            commit("k2", path, "REPLACE", state, extra)
            expect(tracker.getSnapshot()).toBeNull()
        })

        it("an ended arrival is not revived by a later look-alike stamp", () => {
            const { tracker, commit } = arrive()
            commit("k2", DETAILS, "REPLACE", { ...stamped("a2"), task: { ...task, root: "world" } })
            commit("k3", DETAILS, "REPLACE", stamped("a2"))
            expect(tracker.getSnapshot()).toBeNull()
        })

        it("a REPLACE of an entry that is not the arrival's own is not a stamp of it", () => {
            const { router, commit } = fakeRouter({ key: "k0", pathname: DETAILS }, { task, ...choice }, "POP")
            const tracker = createArrivalTracker(router as never, () => null)
            tracker.subscribe(() => undefined)
            commit("k1", DETAILS, "REPLACE", stamped("a2"))
            expect(tracker.getSnapshot()).toBeNull()
        })
    })

    it("a REPLACE batched ahead of the render still leaves the PUSH's arrival (the tracker sees every location)", () => {
        const { router, commit } = fakeRouter()
        const tracker = createArrivalTracker(router as never, () => null)
        const seen: unknown[] = []
        tracker.subscribe(() => seen.push(tracker.getSnapshot()))
        const note = { selection: { level: "timeline", id: "t2" } }
        const ctx = { v: 1, campaignId: null, worldId: "w1", timelineId: "t2", characterId: null }

        commit("k1", "/worlds/w1/timelines/t2", "PUSH", note)
        commit("k2", "/worlds/w1/timelines/t2", "REPLACE", { ...note, ctx })

        expect(tracker.getSnapshot()?.change).toEqual({ level: "timeline", id: "t2" })
        expect(seen).toHaveLength(1)
    })

    it("a REPLACE elsewhere, a link, Back/Forward and a reload are not arrivals and end one", () => {
        const { router, commit } = fakeRouter()
        const tracker = createArrivalTracker(router as never, () => null)
        tracker.subscribe(() => undefined)
        commit("k1", DETAILS, "PUSH", choice)
        expect(tracker.getSnapshot()).not.toBeNull()
        commit("k2", "/b", "REPLACE", choice)
        expect(tracker.getSnapshot()).toBeNull()

        commit("k3", DETAILS, "PUSH", choice)
        commit("k4", "/d", "PUSH", null)
        expect(tracker.getSnapshot()).toBeNull()

        commit("k5", DETAILS, "PUSH", choice)
        commit("k6", DETAILS, "POP", choice)
        expect(tracker.getSnapshot()).toBeNull()
        // A REPLACE of a Back/Forward entry that carries the choice's state is a stamp, not an arrival.
        commit("k7", DETAILS, "REPLACE", stamped("a2"))
        expect(tracker.getSnapshot()).toBeNull()
    })

    it("a newer choice supersedes an older one and nothing of the older one is kept", () => {
        const { router, commit } = fakeRouter()
        const tracker = createArrivalTracker(router as never, () => null)
        tracker.subscribe(() => undefined)
        commit("k1", DETAILS, "PUSH", choice)
        const first = tracker.getSnapshot()

        commit("k2", "/app/alpha/characters/a3", "PUSH", { selection: { level: "character", id: "a3", campaignId: "alpha" } })

        expect(tracker.getSnapshot()).not.toBe(first)
        expect(tracker.getSnapshot()?.change.id).toBe("a3")
    })

    it("the location it is created under counts (a scope change remounts the shell on the accepted location)", () => {
        const { router } = fakeRouter({ key: "k9", pathname: "/app/beta/home" }, { selection: { level: "campaign", id: "beta" } }, "PUSH")
        const tracker = createArrivalTracker(router as never, () => "alpha")
        expect(tracker.getSnapshot()?.change).toEqual({ level: "campaign", id: "beta" })
        expect(tracker.getSnapshot()?.campaignBefore).toBe("alpha")
    })

    it("the announcement is claimed once", () => {
        const { router, commit } = fakeRouter()
        const tracker = createArrivalTracker(router as never, () => null)
        tracker.subscribe(() => undefined)
        commit("k1", "/app/alpha/home", "PUSH", { selection: { level: "campaign", id: "alpha" } })
        const arrival = tracker.getSnapshot()!

        expect(arrival.claimAnnouncement()).toBe(true)
        expect(arrival.claimAnnouncement()).toBe(false)
    })
})

describe("readSelectionChange", () => {
    it("reads a well-formed selection and nothing else", () => {
        expect(readSelectionChange({ selection: { level: "campaign", id: "beta" } })).toEqual({ level: "campaign", id: "beta" })
        expect(readSelectionChange({ selection: { level: "character", id: null, campaignId: "alpha" } })).toEqual({
            level: "character",
            id: null,
            campaignId: "alpha",
        })
        for (const bad of [
            null,
            "x",
            {},
            { selection: null },
            { selection: { level: "world", id: null } },
            { selection: { level: "universe", id: "u" } },
            { selection: { level: "character", id: "a2" } },
            { selection: { level: "campaign", id: "has spaces" } },
            { selection: { level: "campaign", id: 4 } },
        ]) {
            expect(readSelectionChange(bad)).toBeNull()
        }
    })

    it("an inherited property is not a selection", () => {
        const state = Object.create({ selection: { level: "campaign", id: "beta" } }) as unknown
        expect(readSelectionChange(state)).toBeNull()
    })
})
