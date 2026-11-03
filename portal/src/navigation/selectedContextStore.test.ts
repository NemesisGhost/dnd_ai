import { describe, expect, it, vi } from "vitest"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import type { SessionBootstrap } from "../types/bootstrap"
import { EMPTY_SELECTION, createSelectedContextStore, selectionFor, selectionOwner } from "./selectedContextStore"

const bootstrap = (over: Partial<SessionBootstrap> = {}): SessionBootstrap => ({ ...sessionBootstrapFixture, ...over })
const owner = selectionOwner(bootstrap())
const selection = { owner, campaignId: "c1", worldId: "w1", timelineId: "t1", characterId: "a" as string | null | undefined }

describe("the selected-context store", () => {
    it("starts empty and uninitialized", () => {
        const store = createSelectedContextStore()
        expect(store.getSnapshot()).toMatchObject({ ...EMPTY_SELECTION, revision: 0 })
        expect(store.getSnapshot().characterId).toBeUndefined()
    })

    it("notifies on a change and not on an equal commit", () => {
        const store = createSelectedContextStore()
        const listener = vi.fn()
        store.subscribe(listener)
        store.commit(selection)
        store.commit({ ...selection })
        expect(listener).toHaveBeenCalledTimes(1)
        expect(store.getSnapshot().revision).toBe(1)
        store.commit({ ...selection, characterId: null })
        expect(listener).toHaveBeenCalledTimes(2)
    })

    it("keeps an explicit none apart from an uninitialized perspective", () => {
        const store = createSelectedContextStore()
        store.commit({ ...selection, characterId: undefined })
        store.commit({ ...selection, characterId: null })
        expect(store.getSnapshot().characterId).toBeNull()
        expect(store.getSnapshot().revision).toBe(2)
    })

    it("reset drops everything, once", () => {
        const store = createSelectedContextStore()
        store.commit(selection)
        store.reset()
        const after = store.getSnapshot()
        expect(after).toMatchObject(EMPTY_SELECTION)
        store.reset()
        expect(store.getSnapshot()).toBe(after)
    })

    it("stops notifying an unsubscribed listener", () => {
        const store = createSelectedContextStore()
        const listener = vi.fn()
        store.subscribe(listener)()
        store.commit(selection)
        expect(listener).not.toHaveBeenCalled()
    })

    it("hands a consumer the selection only for the owner that made it", () => {
        const store = createSelectedContextStore()
        store.commit(selection)
        expect(selectionFor(store.getSnapshot(), bootstrap())).toMatchObject({ campaignId: "c1" })
        expect(selectionFor(store.getSnapshot(), bootstrap({ browser_session_id: "other" }))).toBe(EMPTY_SELECTION)
        expect(selectionFor(store.getSnapshot(), null)).toBe(EMPTY_SELECTION)
    })
})
