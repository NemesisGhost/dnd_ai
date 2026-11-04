import { describe, expect, it } from "vitest"
import { createArrivalTracker } from "./selectionArrivalTracker"
import { readSelectionChange } from "./selectionChange"

type Action = "PUSH" | "REPLACE" | "POP"
interface Fake {
    state: { location: { key: string; pathname: string; state: unknown }; historyAction: Action }
    listeners: Set<(state: Fake["state"]) => void>
}

// The router as the tracker sees it: committed locations, announced to subscribers as they happen.
function fakeRouter(initial = { key: "k0", pathname: "/start" }, state: unknown = null, action: Action = "POP") {
    const fake: Fake = { state: { location: { ...initial, state }, historyAction: action }, listeners: new Set() }
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
    const commit = (key: string, pathname: string, action: Action, state: unknown = null) => {
        fake.state = { location: { key, pathname, state }, historyAction: action }
        fake.listeners.forEach((listener) => listener(fake.state))
    }
    return { router, commit }
}

const choice = { selection: { level: "character", id: "a2", campaignId: "alpha" } }

describe("createArrivalTracker", () => {
    it("a PUSH that carries a selection is an arrival, noting the campaign selected before it", () => {
        const { router, commit } = fakeRouter()
        const tracker = createArrivalTracker(router as never, () => "alpha")
        tracker.subscribe(() => undefined)
        expect(tracker.getSnapshot()).toBeNull()

        commit("k1", "/app/alpha/characters/a2", "PUSH", choice)

        const arrival = tracker.getSnapshot()
        expect(arrival?.change).toEqual({ level: "character", id: "a2", campaignId: "alpha" })
        expect(arrival?.campaignBefore).toBe("alpha")
    })

    it("a stamp-only REPLACE of the same address keeps the arrival; the new key is the same arrival's", () => {
        const { router, commit } = fakeRouter()
        const tracker = createArrivalTracker(router as never, () => null)
        tracker.subscribe(() => undefined)
        commit("k1", "/app/alpha/characters/a2", "PUSH", choice)
        const arrival = tracker.getSnapshot()

        commit("k2", "/app/alpha/characters/a2", "REPLACE", { ...choice, ctx: {} })

        expect(tracker.getSnapshot()).toBe(arrival)
    })

    it("a REPLACE batched ahead of the render still leaves the PUSH's arrival (the tracker sees every location)", () => {
        const { router, commit } = fakeRouter()
        const tracker = createArrivalTracker(router as never, () => null)
        const seen: unknown[] = []
        tracker.subscribe(() => seen.push(tracker.getSnapshot()))

        commit("k1", "/worlds/w1/timelines/t2", "PUSH", { selection: { level: "timeline", id: "t2" } })
        commit("k2", "/worlds/w1/timelines/t2", "REPLACE", { selection: { level: "timeline", id: "t2" }, ctx: {} })

        expect(tracker.getSnapshot()?.change).toEqual({ level: "timeline", id: "t2" })
        expect(seen).toHaveLength(1)
    })

    it("a REPLACE elsewhere, a link, Back/Forward and a reload are not arrivals and end one", () => {
        const { router, commit } = fakeRouter()
        const tracker = createArrivalTracker(router as never, () => null)
        tracker.subscribe(() => undefined)
        commit("k1", "/a", "PUSH", choice)
        expect(tracker.getSnapshot()).not.toBeNull()
        commit("k2", "/b", "REPLACE", choice)
        expect(tracker.getSnapshot()).toBeNull()

        commit("k3", "/c", "PUSH", choice)
        commit("k4", "/d", "PUSH", null)
        expect(tracker.getSnapshot()).toBeNull()

        commit("k5", "/e", "PUSH", choice)
        commit("k6", "/f", "POP", choice)
        expect(tracker.getSnapshot()).toBeNull()
        // A REPLACE of a Back/Forward entry that carries the choice's state is a stamp, not an arrival.
        commit("k7", "/f", "REPLACE", choice)
        expect(tracker.getSnapshot()).toBeNull()
    })

    it("a newer choice supersedes an older one and nothing of the older one is kept", () => {
        const { router, commit } = fakeRouter()
        const tracker = createArrivalTracker(router as never, () => null)
        tracker.subscribe(() => undefined)
        commit("k1", "/app/alpha/characters/a2", "PUSH", choice)
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
