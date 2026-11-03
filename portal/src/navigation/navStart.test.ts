import { describe, expect, it } from "vitest"
import { navTaskState } from "./navStart"
import type { NavRoot } from "./routeMeta"

const C = "mundivita"
const base = `/app/${C}`

// Every destination the Navbar offers, with the root of the item that offers it.
const CAMPAIGN_DESTINATIONS: Array<[string, string, NavRoot]> = [
    ["Campaign Home", `${base}/home`, "campaign"],
    ["Characters", `${base}/characters`, "characters"],
    ["Parties", `${base}/parties`, "parties"],
    ["Quests", `${base}/quests`, "quests"],
    ["Sessions", `${base}/sessions`, "sessions"],
    ["Knowledge", `${base}/knowledge`, "knowledge"],
    ["Knowledge > Member preview", `${base}/knowledge/member-preview`, "knowledge"],
    ["Review queue", `${base}/review`, "review"],
    ["Items > Inventory", `${base}/items`, "items"],
    ["Items > Definitions", `${base}/item-definitions`, "items"],
    ["Ask", `${base}/ask`, "campaign"],
    ["Access > Access Management", `${base}/access`, "access"],
    ["Access > Invitations", `${base}/access/invitations`, "access"],
    ["Access > Audit History", `${base}/access/audit`, "access"],
    ["Access > Campaign Settings", `${base}/settings`, "campaign"],
    ["Worlds > Campaign world", `${base}/world`, "world"],
]

const WORLD_DESTINATIONS: Array<[string, string]> = [
    ["Worlds > World overview", "/worlds/w1"],
    ["Worlds > Timelines", "/worlds/w1/timelines"],
    ["Worlds > Timeline overview", "/worlds/w1/timelines/t1"],
    ["Worlds > Published canon", "/worlds/w1/canon"],
    ["Worlds > Sharing", "/worlds/w1/sharing"],
]

describe("a Navbar destination starts a task", () => {
    it.each(CAMPAIGN_DESTINATIONS)("%s", (_label, to, root) => {
        expect(navTaskState(to, root)).toEqual({
            task: { v: 1, root, scope: { campaignId: C }, trail: [] },
        })
    })

    it.each(WORLD_DESTINATIONS)("%s", (_label, to) => {
        expect(navTaskState(to, "world")).toEqual({
            task: { v: 1, root: "world", scope: { worldId: "w1" }, trail: [] },
        })
    })

    it("carries no trail, list state, label or transition hint", () => {
        const state = navTaskState(`${base}/parties`, "parties")!
        expect(Object.keys(state)).toEqual(["task"])
        expect(Object.keys(state.task).sort()).toEqual(["root", "scope", "trail", "v"])
    })

    it("ignores a query or fragment on the destination when matching the route", () => {
        expect(navTaskState(`${base}/parties?x=1#top`, "parties")?.task.root).toBe("parties")
    })
})

describe("nothing is started where nothing valid can be", () => {
    it.each<[string, string, NavRoot]>([
        ["the campaign list", "/campaigns", "campaign"],
        ["the worlds list", "/worlds", "world"],
        ["new world", "/worlds/new", "world"],
        ["an unknown address", "/nowhere/at/all", "campaign"],
        ["a root the destination does not allow", `${base}/parties`, "items"],
        ["an id that is not id-shaped", "/app/bad%20id/parties", "parties"],
    ])("%s", (_label, to, root) => {
        expect(navTaskState(to, root)).toBeUndefined()
    })
})
