import { describe, expect, it } from "vitest"
import { adaptLegacyReturn } from "./legacyReturn"
import { resolveTask } from "./resolveTask"
import { ROUTE_METAS, matchRouteMeta } from "./routeMeta"
import { MAX_TRAIL, continueTask, defaultTask, isSafeSearch, parseTask, startTask, validateTask } from "./taskOrigin"
import type { TaskOriginV1 } from "./taskOrigin"

const CAMPAIGN = "c1"
const UUID = "0f8fad5b-d9cb-469f-a165-0c0b0d6c1b3e"
const partyEdit = matchRouteMeta(`/app/${CAMPAIGN}/parties/p1/edit`)!

function task(over: Partial<TaskOriginV1> = {}): TaskOriginV1 {
    return { v: 1, root: "parties", scope: { campaignId: CAMPAIGN }, trail: [], ...over }
}
const partiesRef = { route: "parties.list", params: { campaignId: CAMPAIGN } }
const partyRef = { route: "parties.detail", params: { campaignId: CAMPAIGN, partyId: "p1" } }
const asState = (value: unknown) => ({ task: value })

describe("parseTask (shape and version)", () => {
    it("round-trips a well-formed descriptor as a fresh copy", () => {
        const input = task({ trail: [partiesRef, partyRef], list: { route: "parties.list", search: "?q=a" }, transition: "context" })
        const parsed = parseTask(asState(input))
        expect(parsed).toEqual(input)
        expect(parsed).not.toBe(input)
        expect(parsed!.trail[0]).not.toBe(input.trail[0])
    })

    it.each([
        ["no state", undefined],
        ["a string state", "x"],
        ["an array state", [task()]],
        ["no task", {}],
        ["an array task", asState([task()])],
        ["a wrong version", asState({ ...task(), v: 2 })],
        ["a missing root", asState({ ...task(), root: undefined })],
        ["an unknown root", asState({ ...task(), root: "admin" })],
        ["no scope", asState({ ...task(), scope: undefined })],
        ["both scopes", asState({ ...task(), scope: { campaignId: "c", worldId: "w" } })],
        ["a non-id scope", asState({ ...task(), scope: { campaignId: "../c" } })],
        ["a non-array trail", asState({ ...task(), trail: "x" })],
        ["a trail over the limit", asState({ ...task(), trail: Array.from({ length: MAX_TRAIL + 1 }, () => partiesRef) })],
        ["a 20-entry trail", asState({ ...task(), trail: Array.from({ length: 20 }, () => partiesRef) })],
        ["a URL in params", asState({ ...task(), trail: [{ route: "parties.detail", params: { partyId: "https://evil.example/x" } }] })],
        ["a label in params", asState({ ...task(), trail: [{ route: "parties.detail", params: { partyId: "Lantern Company" } }] })],
        ["a bad section", asState({ ...task(), trail: [{ ...partiesRef, section: "Not A Key" }] })],
        ["an unsafe list search", asState({ ...task(), list: { route: "parties.list", search: "?a b" } })],
        ["a list search without ?", asState({ ...task(), list: { route: "parties.list", search: "x=1" } })],
        ["a list that is not an object", asState({ ...task(), list: "x" })],
    ])("rejects %s", (_label, state) => {
        expect(parseTask(state)).toBeNull()
    })

    it("drops unknown keys, ignores inherited ones, and treats an unknown transition as absent", () => {
        const parsed = parseTask(asState({ ...task(), label: "Lantern Company", draft: "x", transition: "elsewhere" }))
        expect(parsed).toEqual(task())
        expect(parseTask(Object.create({ task: task() }))).toBeNull()
        const polluted = JSON.parse('{"task":{"v":1,"root":"parties","scope":{"campaignId":"c1"},"trail":[],"__proto__":{"root":"world"}}}')
        expect(parseTask(polluted)).toEqual(task())
        expect(({} as { root?: string }).root).toBeUndefined()
    })
})

describe("validateTask (fit to the route)", () => {
    it("accepts a task of the route's scope whose root the route allows", () => {
        expect(validateTask(task({ trail: [partiesRef, partyRef] }), partyEdit)).toEqual(task({ trail: [partiesRef, partyRef] }))
    })

    it("rejects a foreign scope", () => {
        expect(validateTask(task({ scope: { campaignId: "other" } }), partyEdit)).toBeNull()
        expect(validateTask(task({ scope: { worldId: "c1" } }), partyEdit)).toBeNull()
    })

    it("rejects a root the route does not allow", () => {
        expect(validateTask(task({ root: "world" }), partyEdit)).toBeNull()
        expect(validateTask(task({ root: "characters" }), partyEdit)).not.toBeNull()
    })

    it("rejects a trail entry that is unknown, foreign, or has the wrong params", () => {
        const bad = (entry: unknown) => validateTask(task({ trail: [entry as never] }), partyEdit)
        expect(bad({ route: "no.such.route", params: {} })).toBeNull()
        expect(bad({ route: "parties.detail", params: { campaignId: "other", partyId: "p1" } })).toBeNull()
        expect(bad({ route: "parties.detail", params: { campaignId: CAMPAIGN } })).toBeNull()
        expect(bad({ route: "parties.detail", params: { campaignId: CAMPAIGN, partyId: "p1", extra: "x" } })).toBeNull()
        expect(bad({ route: "worlds.detail", params: { worldId: "w1" } })).toBeNull()
        expect(bad({ route: "public.login", params: {} })).toBeNull()
    })

    it("allows an unscoped list ancestor with no params, and nothing else unscoped", () => {
        const world = matchRouteMeta("/worlds/w1/timelines")!
        const worldTask: TaskOriginV1 = { v: 1, root: "world", scope: { worldId: "w1" }, trail: [{ route: "worlds.list", params: {} }] }
        expect(validateTask(worldTask, world)).toEqual(worldTask)
        const withParams = { ...worldTask, trail: [{ route: "worlds.list", params: { x: "1" } }] }
        expect(validateTask(withParams, world)).toBeNull()
    })

    it("removes duplicates and the current page, keeping order", () => {
        const here = { route: "parties.edit", params: { campaignId: CAMPAIGN, partyId: "p1" } }
        const result = validateTask(task({ trail: [partiesRef, partyRef, partiesRef, here] }), partyEdit)
        expect(result!.trail).toEqual([partiesRef, partyRef])
    })

    it("has no task on a route with no execution scope", () => {
        expect(validateTask(task(), matchRouteMeta("/campaigns")!)).toBeNull()
    })

    it("requires a list to be a list route of the same scope", () => {
        expect(validateTask(task({ list: { route: "parties.list", search: "?a=1" } }), partyEdit)!.list).toEqual({
            route: "parties.list",
            search: "?a=1",
        })
        expect(validateTask(task({ list: { route: "parties.detail", search: "?a=1" } }), partyEdit)).toBeNull()
        expect(validateTask(task({ list: { route: "worlds.list", search: "?a=1" } }), partyEdit)).toBeNull()
        expect(validateTask(task({ list: { route: "nope", search: "?a=1" } }), partyEdit)).toBeNull()
    })
})

describe("startTask and continueTask", () => {
    it("starts with no trail and copies the scope", () => {
        const scope = { campaignId: CAMPAIGN }
        const started = startTask("quests", scope)
        expect(started).toEqual({ v: 1, root: "quests", scope, trail: [] })
        expect(started.scope).not.toBe(scope)
    })

    it("adds the page being left, collapses duplicates, keeps the newest entries, and drops the hint", () => {
        let current = task({ transition: "context", list: { route: "parties.list", search: "?a=1" } })
        for (let index = 0; index < 6; index++) {
            current = continueTask(current, { route: "parties.detail", params: { campaignId: CAMPAIGN, partyId: `p${index}` } })
        }
        expect(current.trail).toHaveLength(MAX_TRAIL)
        expect(current.trail.map((entry) => entry.params.partyId)).toEqual(["p2", "p3", "p4", "p5"])
        expect(current.transition).toBeUndefined()
        expect(current.list).toEqual({ route: "parties.list", search: "?a=1" })
        const again = continueTask(current, { route: "parties.detail", params: { campaignId: CAMPAIGN, partyId: "p3" } })
        expect(again.trail.map((entry) => entry.params.partyId)).toEqual(["p2", "p4", "p5", "p3"])
    })
})

describe("origin resolution (steps 1-3)", () => {
    const path = `/app/${CAMPAIGN}/parties/p1/edit`

    it("uses a valid state.task (step 1)", () => {
        const resolved = resolveTask(path, asState(task({ root: "characters", trail: [partiesRef] })))
        expect(resolved).toEqual({ source: "state", task: task({ root: "characters", trail: [partiesRef] }) })
    })

    it("falls back to the route default for tampered or foreign state (step 3)", () => {
        const expected = defaultTask(partyEdit)!
        for (const state of [
            undefined,
            "x",
            asState(task({ scope: { campaignId: "other" } })),
            asState(task({ root: "world" })),
            asState({ ...task(), trail: Array.from({ length: 20 }, () => partiesRef) }),
            asState(task({ trail: [{ route: "parties.detail", params: { campaignId: CAMPAIGN, partyId: "https://x.test" } }] })),
        ]) {
            expect(resolveTask(path, state), JSON.stringify(state)).toEqual({ source: "default", task: expected })
        }
        expect(expected.root).toBe("parties")
        expect(expected.trail.map((entry) => entry.route)).toEqual(["parties.list", "parties.detail"])
    })

    it("has no task on routes that are not task pages", () => {
        for (const pathname of ["/campaigns", "/login", "/settings", "/home", `/app/${CAMPAIGN}/nothing`, `/app/${CAMPAIGN}/quests/q1/edit`]) {
            expect(resolveTask(pathname, asState(task())), pathname).toBeNull()
        }
    })

    it("gives every task page a default task whose own trail validates", () => {
        for (const meta of ROUTE_METAS.filter((candidate) => candidate.defaultRoot !== null && candidate.scope !== "none")) {
            const pathname = meta.pattern.replace(/:(\w+)/g, (_m, name: string) => `${name}1`)
            const match = matchRouteMeta(pathname)
            expect(match?.meta.id, pathname).toBe(meta.id)
            const own = defaultTask(match!)!
            expect(validateTask(own, match!), meta.id).toEqual(own)
        }
    })
})

describe("legacy return adapters (step 2)", () => {
    const sheet = matchRouteMeta(`/app/${CAMPAIGN}/characters/${UUID}`)!
    const adapt = (state: unknown, match = sheet) => adaptLegacyReturn(match, state)

    it("adapts charactersReturn to the Characters root with its list state", () => {
        expect(adapt({ charactersReturn: `/app/${CAMPAIGN}/characters/all?q=sella` })?.task).toEqual({
            v: 1,
            root: "characters",
            scope: { campaignId: CAMPAIGN },
            trail: [],
            list: { route: "characters.browse", search: "?q=sella" },
        })
        expect(adapt({ charactersReturn: `/app/${CAMPAIGN}/characters/${UUID}/inventory` })?.task?.trail).toEqual([
            { route: "characters.inventory", params: { campaignId: CAMPAIGN, characterId: UUID } },
        ])
    })

    it("keeps the canonical Characters validation: other campaigns, traversal and non-UUID ids are ignored", () => {
        for (const charactersReturn of [
            `/app/other/characters/all`,
            `/app/${CAMPAIGN}/characters/../../x`,
            `/app/${CAMPAIGN}/characters/%2e%2e/world`,
            `/app/${CAMPAIGN}/characters/synthetic-id`,
            `/app/${CAMPAIGN}/characters/new`,
            `//evil.example/app/${CAMPAIGN}/characters/all`,
        ]) {
            expect(adapt({ charactersReturn }), charactersReturn).toBeNull()
        }
    })

    it.each([
        ["worldSearch", "world", "campaign.world"],
        ["reviewSearch", "review", "review.queue"],
        ["itemsSearch", "items", "items.list"],
        ["definitionsSearch", "items", "itemDefinitions.list"],
    ])("adapts %s to its root and list", (key, root, route) => {
        expect(adapt({ [key]: "?category=npcs&page=2" })?.task).toEqual({
            v: 1,
            root,
            scope: { campaignId: CAMPAIGN },
            trail: [],
            list: { route, search: "?category=npcs&page=2" },
        })
    })

    it("ignores a search value that is not a query, and prefers the Review queue over the World browser", () => {
        expect(adapt({ worldSearch: "category=npcs" })).toBeNull()
        expect(adapt({ worldSearch: "?a b" })).toBeNull()
        expect(adapt({ worldSearch: "?a=1", reviewSearch: "?status=open" })?.task?.root).toBe("review")
    })

    it("keeps returnTo as the page's Back target only", () => {
        const result = adapt({ returnTo: { pathname: `/app/${CAMPAIGN}/items/i1`, search: "?section=details" } })
        expect(result).toEqual({ task: null, backTarget: `/app/${CAMPAIGN}/items/i1?section=details` })
        for (const pathname of ["/app/other/items/i1", "//evil.example", "https://evil.example", `/app/${CAMPAIGN}/../x`, `/app/${CAMPAIGN}/home/`]) {
            expect(adapt({ returnTo: { pathname } }), pathname).toBeNull()
        }
        expect(adapt({ returnTo: { pathname: `/app/${CAMPAIGN}/items/i1`, search: "x" } })).toBeNull()
    })

    it("resolves through resolveTask as source legacy, falling back to defaults when the adapted root does not fit", () => {
        const resolved = resolveTask(`/app/${CAMPAIGN}/characters/${UUID}`, { charactersReturn: `/app/${CAMPAIGN}/characters/all?q=a` })
        expect(resolved?.source).toBe("legacy")
        expect(resolved?.task.root).toBe("characters")
        expect(resolved?.task.list?.search).toBe("?q=a")
        // A World list cannot be the origin of a Parties page: the root is not allowed there, so defaults apply.
        const unfit = resolveTask(`/app/${CAMPAIGN}/parties/p1`, { worldSearch: "?a=1" })
        expect(unfit?.source).toBe("default")
        expect(unfit?.task.root).toBe("parties")
        // returnTo gives a Back target without changing the task.
        const back = resolveTask(`/app/${CAMPAIGN}/items/i1/edit`, { returnTo: { pathname: `/app/${CAMPAIGN}/items/i1`, search: "?section=details" } })
        expect(back).toMatchObject({ source: "legacy", backTarget: `/app/${CAMPAIGN}/items/i1?section=details` })
        expect(back?.task.root).toBe("items")
    })

    it("lets a valid state.task win over legacy keys", () => {
        const own = task({ root: "characters" })
        const resolved = resolveTask(`/app/${CAMPAIGN}/parties/p1`, { ...asState(own), worldSearch: "?a=1" })
        expect(resolved?.source).toBe("state")
    })
})

describe("isSafeSearch", () => {
    it.each(["?", "?a=1&b=2", "?q=%20x"])("accepts %s", (value) => expect(isSafeSearch(value)).toBe(true))
    it.each(["", "a=1", "?a b", "?a#b", "?a\\b", `?${"x".repeat(1100)}`, 3, null])("rejects %s", (value) =>
        expect(isSafeSearch(value)).toBe(false),
    )
})
