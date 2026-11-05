import { describe, expect, it } from "vitest"
import { breadcrumbModel, continuedState } from "./breadcrumbModel"
import { carriedListSearch, carriedState } from "./taskReturn"

const page = "/app/c1/world/location/e1"
const task = (over: object = {}) => ({
    v: 1,
    root: "world",
    scope: { campaignId: "c1" },
    trail: [],
    list: { route: "campaign.world", search: "?category=location&q=mill" },
    ...over,
})

describe("carriedListSearch", () => {
    it("reads the query the list was left on, for the root and list that name it", () => {
        expect(carriedListSearch(page, { task: task() }, "world", "campaign.world")).toBe("?category=location&q=mill")
    })

    it("reads nothing for another root, another list, another campaign or a direct entry", () => {
        const state = { task: task() }
        expect(carriedListSearch(page, state, "review", "review.queue")).toBeUndefined()
        expect(carriedListSearch(page, state, "world", "items.list")).toBeUndefined()
        expect(carriedListSearch(page, { task: task({ scope: { campaignId: "c2" } }) }, "world", "campaign.world")).toBeUndefined()
        expect(carriedListSearch(page, undefined, "world", "campaign.world")).toBeUndefined()
        expect(carriedListSearch("/home", state, "world", "campaign.world")).toBeUndefined()
    })

    it("reads nothing for a query the list's contract does not accept", () => {
        const bad = task({ list: { route: "campaign.world", search: "?category=location&next=https://evil.example" } })
        expect(carriedListSearch(page, { task: bad }, "world", "campaign.world")).toBeUndefined()
        const unknownKey = task({ list: { route: "campaign.world", search: "?token=abc" } })
        expect(carriedListSearch(page, { task: unknownKey }, "world", "campaign.world")).toBeUndefined()
    })

    it("still reads an entry written before the task existed, through the legacy adapter", () => {
        expect(carriedListSearch(page, { worldSearch: "?category=location" }, "world", "campaign.world")).toBe("?category=location")
        expect(carriedListSearch(page, { worldSearch: "https://evil.example/" }, "world", "campaign.world")).toBeUndefined()
    })
})

describe("carriedState", () => {
  it("hands the task on as written, without the one-shot transition hint, and nothing else of the entry", () => {
        const carried = carriedState(page, { task: task({ transition: "context" }), announce: "Saved", returnTo: { pathname: "/x" } })
        expect(carried).toEqual({ task: task() })
        expect(Object.keys(carried!)).toEqual(["task"])
    })

    it("hands on a root this route would not accept, for the record that does", () => {
        // /world/dungeon/:id/edit allows only World's own task; the Review task still goes back to its record.
        const review = task({ root: "review", list: { route: "review.queue", search: "?status=draft" } })
        expect(carriedState("/app/c1/world/dungeon/d1/edit", { task: review })).toEqual({ task: review })
    })

    it("hands on nothing after a direct entry, a malformed or foreign task, or off a campaign route", () => {
        expect(carriedState(page, undefined)).toBeUndefined()
        expect(carriedState(page, { task: { v: 2 } })).toBeUndefined()
        expect(carriedState(page, { task: task({ scope: { campaignId: "c2" } }) })).toBeUndefined()
        expect(carriedState(page, { task: task({ root: "nonsense" }) })).toBeUndefined()
        expect(carriedState(page, { task: task({ trail: new Array(20).fill({ route: "world.record", params: {} }) }) })).toBeUndefined()
        expect(carriedState("/home", { task: task() })).toBeUndefined()
    })
})

describe("an explicit task that does not hold up does not hide a valid historical origin", () => {
    const edit = "/app/c1/world/dungeon/d1/edit"
    const legacy = { reviewSearch: "?status=draft" }
    const fromLegacy = {
        v: 1,
        root: "review",
        scope: { campaignId: "c1" },
        trail: [],
        list: { route: "review.queue", search: "?status=draft" },
    }

    it.each<[string, object]>([
        ["a foreign explicit task (another campaign)", { task: task({ scope: { campaignId: "c2" } }) }],
        ["an explicit task whose list the root does not own", { task: task({ root: "review", list: { route: "items.list", search: "" } }) }],
        ["an explicit task with a trail entry of an unknown route", { task: task({ trail: [{ route: "nowhere", params: {} }] }) }],
        ["an explicit task with a list query its contract rejects", { task: task({ list: { route: "campaign.world", search: "?token=abc" } }) }],
        ["a malformed explicit task", { task: { v: 2 } }],
    ])("%s, beside a valid legacy origin, carries the legacy origin", (_name, explicit) => {
        expect(carriedState(edit, { ...explicit, ...legacy })).toEqual({ task: fromLegacy })
        expect(carriedListSearch(edit, { ...explicit, ...legacy }, "review", "review.queue")).toBe("?status=draft")
    })

    it("a valid explicit task wins over a conflicting legacy origin", () => {
        const carried = carriedState(page, { task: task(), ...legacy })
        expect(carried).toEqual({ task: task() })
        expect(carriedListSearch(page, { task: task(), ...legacy }, "world", "campaign.world")).toBe("?category=location&q=mill")
        expect(carriedListSearch(page, { task: task(), ...legacy }, "review", "review.queue")).toBeUndefined()
    })

    it("an explicit task this page does not allow the root of still passes through", () => {
        const review = task({ root: "review", list: { route: "review.queue", search: "?status=draft" } })
        expect(carriedState(edit, { task: review, worldSearch: "?category=location" })).toEqual({ task: review })
    })

    it("nothing is carried when the explicit task and the legacy state are both invalid", () => {
        const bad = { task: task({ scope: { campaignId: "c2" } }), reviewSearch: "?status=draft&redirect=/x", worldSearch: "https://evil.example/" }
        expect(carriedState(edit, bad)).toBeUndefined()
        expect(carriedListSearch(edit, bad, "review", "review.queue")).toBeUndefined()
        expect(carriedState(edit, { task: { v: 2 }, charactersReturn: "/app/c2/characters/all" })).toBeUndefined()
    })

    it("emits the task alone: no legacy key, no announcement, no transition, no unrelated state", () => {
        const carried = carriedState(edit, { task: task({ scope: { campaignId: "c2" } }), ...legacy, announce: "Saved", returnTo: { pathname: "/x" }, ctx: { a: 1 } })
        expect(Object.keys(carried!)).toEqual(["task"])
        expect(carried!.task).not.toHaveProperty("transition")
    })
})

describe("a trail entry records the section it was left on", () => {
    const sheet = "/app/c1/characters/ch1"

    it("is recorded for a section token, and reopens the page on it", () => {
        const link = continuedState(sheet, undefined, "inventory")
        expect(link?.task.trail.at(-1)).toEqual({ route: "characters.detail", params: { campaignId: "c1", characterId: "ch1" }, section: "inventory" })
    })

    it("makes the page's crumb open on that section, in the task a page below it carries", () => {
        const link = continuedState(sheet, undefined, "inventory")
        const model = breadcrumbModel("/app/c1/characters/pc/new", link)
        expect(model?.ancestors.at(-1)).toMatchObject({ ref: { route: "characters.detail" }, to: "/app/c1/characters/ch1?section=inventory" })
    })

    it("is not recorded for anything that is not a section token", () => {
        for (const bad of ["../x", "Inventory", "a b", "", "x".repeat(40)]) {
            expect(continuedState(sheet, undefined, bad)?.task.trail.at(-1)).not.toHaveProperty("section")
        }
        expect(continuedState(sheet, undefined)?.task.trail.at(-1)).not.toHaveProperty("section")
    })
})
