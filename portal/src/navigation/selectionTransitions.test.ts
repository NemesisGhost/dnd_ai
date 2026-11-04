import { describe, expect, it } from "vitest"
import { perspectiveRequest, scopeRequest } from "./selectionTransitions"

const scope = { campaignId: "alpha", worldId: "w1", timelineId: "t1" }

describe("perspectiveRequest", () => {
    it("opens the chosen character's details as a new Characters task, recording the context it commits under", () => {
        const request = perspectiveRequest("alpha", "a2", scope)
        expect(request.to).toBe("/app/alpha/characters/a2")
        expect(request.state.task).toMatchObject({ v: 1, root: "characters", scope: { campaignId: "alpha" }, trail: [] })
        expect(request.state.task?.list).toBeUndefined()
        expect(request.state.ctx).toEqual({ v: 1, ...scope, characterId: "a2" })
    })

    it("opens All characters for none and never builds a character route from null", () => {
        const request = perspectiveRequest("alpha", null, scope)
        expect(request.to).toBe("/app/alpha/characters/all")
        expect(request.state.task).toMatchObject({ root: "characters", trail: [] })
        expect(request.state.ctx?.characterId).toBeNull()
        expect(request.to).not.toMatch(/null|undefined/)
    })

    it("encodes ids and carries nothing of the page left (no query, no hash, no other state)", () => {
        const request = perspectiveRequest("alpha", "a/b?c=d", scope)
        expect(request.to).toBe("/app/alpha/characters/a%2Fb%3Fc%3Dd")
        expect(Object.keys(request.state).sort()).toEqual(["ctx", "selection", "task"])
    })

    it("names the level and id chosen, and only that (never a label)", () => {
        expect(perspectiveRequest("alpha", "a2", scope).state.selection).toEqual({
            level: "character",
            id: "a2",
            campaignId: "alpha",
        })
        expect(perspectiveRequest("alpha", null, scope).state.selection).toEqual({
            level: "character",
            id: null,
            campaignId: "alpha",
        })
    })
})

describe("scopeRequest", () => {
    it("starts a task with the section's root in the destination's own scope", () => {
        expect(scopeRequest("/app/beta/home", "campaign", { level: "campaign", id: "beta" }).state.task).toMatchObject({
            root: "campaign",
            scope: { campaignId: "beta" },
        })
        expect(scopeRequest("/worlds/w1", "world", { level: "world", id: "w1" }).state.task).toMatchObject({
            root: "world",
            scope: { worldId: "w1" },
        })
    })

    it("starts nothing for an address that is not a task page, and still names the destination", () => {
        const request = scopeRequest("/campaigns", "campaign", { level: "campaign", id: "beta" })
        expect(request.to).toBe("/campaigns")
        expect(request.state.task).toBeUndefined()
        expect(request.state.selection).toEqual({ level: "campaign", id: "beta" })
    })
})
