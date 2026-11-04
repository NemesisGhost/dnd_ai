import { describe, expect, it } from "vitest"
import { readCharactersReturn } from "../hooks/useCharactersBackPath"
import { breadcrumbModel, continuedState, continuedStateVia, legacyKeys, outsideTaskOf, retainedState } from "./breadcrumbModel"
import type { Crumb } from "./breadcrumbModel"
import { startTask } from "./taskOrigin"
import type { TaskOriginV1 } from "./taskOrigin"

const C = "c1"
const P = "p1"
const base = `/app/${C}`

const summary = (crumbs: Crumb[]) => crumbs.map((crumb) => [crumb.generic, crumb.to])

function modelOf(pathname: string, state?: unknown) {
    const model = breadcrumbModel(pathname, state)
    if (model === null) throw new Error(`no model for ${pathname}`)
    return model
}

describe("direct entry gives the route's defaults", () => {
    it("Parties list is the top of its task: no ancestors", () => {
        const model = modelOf(`${base}/parties`)
        expect(model.ancestors).toEqual([])
        expect(model.current.generic).toBe("Parties")
        expect(model.source).toBe("default")
    })

    it("a party page is under Parties, never Campaign Home", () => {
        const model = modelOf(`${base}/parties/${P}`)
        expect(summary(model.ancestors)).toEqual([["Parties", `${base}/parties`]])
        expect(model.current.generic).toBe("Party")
        expect(JSON.stringify(model)).not.toContain("Campaign Home")
    })

    it("a party's edit page is Parties, the party, then Edit", () => {
        const model = modelOf(`${base}/parties/${P}/edit`)
        expect(summary(model.ancestors)).toEqual([
            ["Parties", `${base}/parties`],
            ["Party", `${base}/parties/${P}`],
        ])
        expect(model.ancestors[1]!.named).toBe(true)
        expect(model.ancestors[0]!.named).toBe(false)
        expect(model.current.generic).toBe("Edit")
    })

    it("the New party page is Parties then New party", () => {
        const model = modelOf(`${base}/parties/new`)
        expect(summary(model.ancestors)).toEqual([["Parties", `${base}/parties`]])
        expect(model.current.generic).toBe("New party")
    })

    it("the New character chooser goes back to the characters browser", () => {
        const model = modelOf(`${base}/characters/new`)
        expect(summary(model.ancestors)).toEqual([["Characters", `${base}/characters/all`]])
        expect(model.current.generic).toBe("New character")
    })

    it("a page that is not a task page has no ancestors and no task", () => {
        const model = modelOf("/settings")
        expect(model.source).toBe("none")
        expect(model.ancestors).toEqual([])
    })
})

describe("a valid task in the entry's state", () => {
    it("continuing from the list, then the detail, builds the trail with the root once", () => {
        const fromList = continuedState(`${base}/parties`, undefined)!
        expect(fromList.task.trail).toEqual([{ route: "parties.list", params: { campaignId: C } }])
        const detail = modelOf(`${base}/parties/${P}`, fromList)
        expect(detail.source).toBe("state")
        expect(summary(detail.ancestors)).toEqual([["Parties", `${base}/parties`]])

        const fromDetail = continuedState(`${base}/parties/${P}`, fromList)!
        const edit = modelOf(`${base}/parties/${P}/edit`, fromDetail)
        expect(edit.source).toBe("state")
        expect(summary(edit.ancestors)).toEqual([
            ["Parties", `${base}/parties`],
            ["Party", `${base}/parties/${P}`],
        ])
    })

    it("each ancestor link carries the task cut back to that ancestor", () => {
        const fromDetail = continuedState(`${base}/parties/${P}`, continuedState(`${base}/parties`, undefined))!
        const [root, party] = modelOf(`${base}/parties/${P}/edit`, fromDetail).ancestors
        expect(root!.state.task.trail).toEqual([])
        // What precedes the party in the trail stays (the list page); the party itself and what follows go.
        expect(party!.state.task.trail).toEqual([{ route: "parties.list", params: { campaignId: C } }])
        expect(party!.state.task.root).toBe("parties")
        expect(party!.state.task.scope).toEqual({ campaignId: C })
        // The cut task is itself a valid origin for the page it links to.
        const back = modelOf(`${base}/parties/${P}`, party!.state)
        expect(back.source).toBe("state")
        expect(summary(back.ancestors)).toEqual([["Parties", `${base}/parties`]])
    })

    it("a task cut in the middle of a longer trail keeps only what precedes the ancestor", () => {
        const task: TaskOriginV1 = {
            ...startTask("characters", { campaignId: C }),
            trail: [
                { route: "characters.browse", params: { campaignId: C } },
                { route: "parties.list", params: { campaignId: C } },
                { route: "parties.detail", params: { campaignId: C, partyId: P } },
            ],
        }
        const model = modelOf(`${base}/characters/c9`, { task })
        const party = model.ancestors.find((crumb) => crumb.ref.route === "parties.detail")!
        expect(party.state.task.trail.map((entry) => entry.route)).toEqual(["characters.browse", "parties.list"])
    })

    it("collapses duplicate trail entries and drops the current page", () => {
        const task: TaskOriginV1 = {
            ...startTask("parties", { campaignId: C }),
            trail: [
                { route: "parties.list", params: { campaignId: C } },
                { route: "parties.detail", params: { campaignId: C, partyId: P } },
                { route: "parties.detail", params: { campaignId: C, partyId: P } },
            ],
        }
        const model = modelOf(`${base}/parties/${P}/edit`, { task })
        expect(summary(model.ancestors)).toEqual([
            ["Parties", `${base}/parties`],
            ["Party", `${base}/parties/${P}`],
        ])
        const onDetail = modelOf(`${base}/parties/${P}`, { task })
        expect(onDetail.ancestors.map((crumb) => crumb.ref.route)).toEqual(["parties.list"])
    })

    it("a character reached from a party keeps the Parties task", () => {
        const fromParty = continuedState(`${base}/parties/${P}`, continuedState(`${base}/parties`, undefined))!
        const model = modelOf(`${base}/characters/c9`, fromParty)
        expect(model.source).toBe("state")
        expect(summary(model.ancestors)).toEqual([
            ["Parties", `${base}/parties`],
            ["Party", `${base}/parties/${P}`],
        ])
    })
})

describe("invalid or foreign state falls back to the reviewed defaults", () => {
    const edit = `${base}/parties/${P}/edit`
    const defaults = summary(modelOf(edit).ancestors)

    it.each<[string, unknown]>([
        ["no state", undefined],
        ["null", null],
        ["an array", []],
        ["a string", "task"],
        ["a task that is a string", { task: "parties" }],
        ["a wrong version", { task: { v: 2, root: "parties", scope: { campaignId: C }, trail: [] } }],
        ["an unknown root", { task: { v: 1, root: "nowhere", scope: { campaignId: C }, trail: [] } }],
        ["a foreign scope", { task: { v: 1, root: "parties", scope: { campaignId: "other" }, trail: [] } }],
        ["a world scope on a campaign page", { task: { v: 1, root: "parties", scope: { worldId: "w1" }, trail: [] } }],
        ["a root this page does not allow", { task: { v: 1, root: "items", scope: { campaignId: C }, trail: [] } }],
        [
            "an unknown route in the trail",
            { task: { v: 1, root: "parties", scope: { campaignId: C }, trail: [{ route: "nope", params: {} }] } },
        ],
        [
            "a trail entry in another campaign",
            {
                task: {
                    v: 1,
                    root: "parties",
                    scope: { campaignId: C },
                    trail: [{ route: "parties.detail", params: { campaignId: "other", partyId: P } }],
                },
            },
        ],
        [
            "a non-id parameter",
            {
                task: {
                    v: 1,
                    root: "parties",
                    scope: { campaignId: C },
                    trail: [{ route: "parties.detail", params: { campaignId: C, partyId: "../x" } }],
                },
            },
        ],
        [
            "an over-long trail",
            {
                task: {
                    v: 1,
                    root: "parties",
                    scope: { campaignId: C },
                    trail: Array.from({ length: 5 }, () => ({ route: "parties.list", params: { campaignId: C } })),
                },
            },
        ],
        ["a prototype-pollution shape", JSON.parse('{"task":{"__proto__":{"root":"parties"},"v":1}}') as unknown],
    ])("%s", (_name, state) => {
        const model = modelOf(edit, state)
        expect(model.source).toBe("default")
        expect(summary(model.ancestors)).toEqual(defaults)
    })
})

describe("legacy return keys are adapted, not trusted", () => {
    const FROM = `${base}/characters/all?type=npc&q=mira`

    it("a validated charactersReturn is the Characters root with its filters", () => {
        const model = modelOf(`${base}/characters/pc/new`, { charactersReturn: FROM })
        expect(model.source).toBe("legacy")
        expect(summary(model.ancestors)).toEqual([["Characters", FROM]])
        expect(model.current.generic).toBe("New PC")
    })

    it("a worldSearch is the World root with its filters", () => {
        const model = modelOf(`${base}/characters/npc/new`, { worldSearch: "?category=character&q=mira" })
        expect(model.source).toBe("legacy")
        expect(summary(model.ancestors)).toEqual([["World", `${base}/world?category=character&q=mira`]])
    })

    it.each<[string, unknown]>([
        ["another campaign", { charactersReturn: "/app/other/characters/all" }],
        ["an external address", { charactersReturn: "https://example.com/app/c1/characters" }],
        ["a protocol-relative address", { charactersReturn: "//evil.example/app/c1/characters" }],
        ["a crafted worldSearch", { worldSearch: "https://evil.example/" }],
        ["a worldSearch with an unknown key", { worldSearch: "?token=abc" }],
    ])("ignores %s", (_name, state) => {
        const model = modelOf(`${base}/characters/npc/new`, state)
        expect(model.source).toBe("default")
        expect(summary(model.ancestors)).toEqual([
            ["Characters", `${base}/characters/all`],
            ["New character", `${base}/characters/new`],
        ])
    })

    it("a task in the entry wins over a legacy key", () => {
        const task = startTask("characters", { campaignId: C })
        const model = modelOf(`${base}/characters/pc/new`, { task, worldSearch: "?category=character" })
        expect(model.source).toBe("state")
        expect(summary(model.ancestors)).toEqual([["Characters", `${base}/characters/all`]])
    })
})

describe("legacy dual writing", () => {
    it("writes charactersReturn for a Characters list task, and it validates with the canonical reader", () => {
        const task: TaskOriginV1 = {
            ...startTask("characters", { campaignId: C }),
            list: { route: "characters.browse", search: "?type=npc&q=mira" },
        }
        const keys = legacyKeys(task)
        expect(keys).toEqual({ charactersReturn: `${base}/characters/all?type=npc&q=mira` })
        expect(readCharactersReturn(C, keys)).toBe(keys.charactersReturn)
    })

    it("writes worldSearch and reviewSearch for their list tasks, and nothing without list state", () => {
        expect(
            legacyKeys({ ...startTask("world", { campaignId: C }), list: { route: "campaign.world", search: "?category=location" } }),
        ).toEqual({ worldSearch: "?category=location" })
        expect(
            legacyKeys({ ...startTask("review", { campaignId: C }), list: { route: "review.queue", search: "?status=pending" } }),
        ).toEqual({ reviewSearch: "?status=pending" })
        expect(legacyKeys(startTask("parties", { campaignId: C }))).toEqual({})
    })

    it("continuing a legacy Characters origin keeps charactersReturn beside the task", () => {
        const from = `${base}/characters/all?type=npc`
        const chooser = continuedState(`${base}/characters/new`, { charactersReturn: from })!
        expect(chooser.charactersReturn).toBe(from)
        expect(chooser.task.root).toBe("characters")
        expect(chooser.task.trail.map((entry) => entry.route)).toContain("characters.new")
        const npc = modelOf(`${base}/characters/npc/new`, chooser)
        expect(summary(npc.ancestors)[0]).toEqual(["Characters", from])
        expect(npc.ancestors.map((crumb) => crumb.ref.route)).toEqual(["characters.browse", "characters.new"])
    })
})

describe("what a link's state may contain", () => {
    const ALLOWED = new Set(["task", "charactersReturn", "worldSearch", "reviewSearch"])
    const TASK_KEYS = new Set(["v", "root", "scope", "trail", "list", "campaignId", "worldId", "route", "params", "search", "section", "transition"])
    const PARAM_KEYS = new Set(["campaignId", "partyId", "characterId", "worldId"])

    function keysOf(value: unknown, path = ""): string[] {
        if (typeof value !== "object" || value === null) return []
        return Object.entries(value).flatMap(([key, child]) => [`${path}.${key}`, ...keysOf(child, `${path}.${key}`)])
    }

    it("carries only ids, route ids and approved query strings: never a name or label", () => {
        const states = [
            continuedState(`${base}/parties/${P}`, continuedState(`${base}/parties`, undefined)),
            continuedState(`${base}/characters/new`, { charactersReturn: `${base}/characters/all?q=mira` }),
            ...modelOf(`${base}/parties/${P}/edit`).ancestors.map((crumb) => crumb.state),
            ...modelOf(`${base}/characters/npc/new`, { worldSearch: "?category=character&q=mira" }).ancestors.map(
                (crumb) => crumb.state,
            ),
        ]
        for (const state of states) {
            expect(state).not.toBeNull()
            for (const key of Object.keys(state!)) expect(ALLOWED.has(key)).toBe(true)
            for (const path of keysOf(state!.task)) {
                const key = path.split(".").pop()!
                expect(TASK_KEYS.has(key) || PARAM_KEYS.has(key) || /^\d+$/.test(key)).toBe(true)
            }
        }
    })
})

describe("retainedState: a link that stays on the record inside its task", () => {
    const record = `${base}/characters/ch1`
    const partiesTask: TaskOriginV1 = {
        v: 1,
        root: "parties",
        scope: { campaignId: C },
        trail: [{ route: "parties.list", params: { campaignId: C } }],
        transition: "context",
    }

    it("is null after a direct entry, so a link cannot turn no evidence into an origin", () => {
        expect(retainedState(record, undefined)).toBeNull()
        expect(retainedState(record, { task: { v: 2 } })).toBeNull()
        expect(retainedState(`${base}/not-a-route`, { task: partiesTask })).toBeNull()
    })

    it("keeps the task as it is without the one-shot transition hint, and does not add the current page", () => {
        const kept = retainedState(record, { task: partiesTask })
        expect(kept?.task).toEqual({
            v: 1,
            root: "parties",
            scope: { campaignId: C },
            trail: [{ route: "parties.list", params: { campaignId: C } }],
        })
        expect(kept?.task).not.toHaveProperty("transition")
    })

    it("regenerates the legacy keys from an adapted legacy entry", () => {
        const kept = retainedState(record, { charactersReturn: `${base}/characters/all?type=npc` })
        expect(kept?.task).toMatchObject({ root: "characters", list: { route: "characters.browse", search: "?type=npc" } })
        expect(kept?.charactersReturn).toBe(`${base}/characters/all?type=npc`)
    })
})

describe("outsideTaskOf: a record opened inside another task than World's or the Review queue's", () => {
    const world = `${base}/world/character/ch1`

    it("is null for a direct entry, a World task and a Review task", () => {
        expect(outsideTaskOf(world, undefined)).toBeNull()
        expect(outsideTaskOf(world, { worldSearch: "?category=character" })).toBeNull()
        expect(outsideTaskOf(world, { reviewSearch: "?status=draft" })).toBeNull()
    })

    it("gives the nearest ancestor and the state that keeps the task for a Characters or Parties task", () => {
        const fromCharacters = outsideTaskOf(world, { charactersReturn: `${base}/characters/all?type=npc` })
        expect(fromCharacters?.nearest.generic).toBe("Characters")
        expect(fromCharacters?.nearest.to).toBe(`${base}/characters/all?type=npc`)
        expect(fromCharacters?.state.task).toMatchObject({ root: "characters" })
        const partiesTask = continuedState(`${base}/parties/${P}`, continuedState(`${base}/parties`, undefined))
        const fromParties = outsideTaskOf(world, partiesTask)
        expect(fromParties?.nearest.to).toBe(`${base}/parties/${P}`)
        expect(fromParties?.state.task).toMatchObject({ root: "parties" })
    })
})

describe("Sessions and Run (P02-7a)", () => {
    const S = "s1"
    const E = "e1"
    const run = `${base}/sessions/${S}/run`

    it("a direct entry follows the documented hierarchy: Run is under the session, an encounter under Run", () => {
        expect(summary(modelOf(`${base}/sessions/${S}`).ancestors)).toEqual([["Sessions", `${base}/sessions`]])
        expect(summary(modelOf(run).ancestors)).toEqual([
            ["Sessions", `${base}/sessions`],
            ["Session", `${base}/sessions/${S}`],
        ])
        expect(summary(modelOf(`${base}/sessions/${S}/encounters/${E}`).ancestors)).toEqual([
            ["Sessions", `${base}/sessions`],
            ["Session", `${base}/sessions/${S}`],
            ["Run session", run],
        ])
        expect(summary(modelOf(`${base}/sessions/${S}/encounters/new`).ancestors).at(-1)).toEqual(["Run session", run])
    })

    it("continuedStateVia adds the page and then the parent the person skipped, once", () => {
        const fromList = continuedStateVia(`${base}/sessions`, undefined, {
            route: "sessions.detail",
            params: { campaignId: C, sessionId: S },
        })
        expect(fromList?.task.root).toBe("sessions")
        expect(fromList?.task.trail.map((entry) => entry.route)).toEqual(["sessions.list", "sessions.detail"])
        expect(summary(modelOf(run, fromList).ancestors)).toEqual([
            ["Sessions", `${base}/sessions`],
            ["Session", `${base}/sessions/${S}`],
        ])
        // From the session itself the parent is already the current page: it is not added twice.
        const fromDetail = continuedStateVia(`${base}/sessions/${S}`, undefined, {
            route: "sessions.detail",
            params: { campaignId: C, sessionId: S },
        })
        expect(fromDetail?.task.trail.map((entry) => entry.route)).toEqual(["sessions.list", "sessions.detail"])
        expect(continuedStateVia(`${base}/not-a-route`, undefined, { route: "sessions.detail", params: {} })).toBeNull()
    })

    it("a character opened from Run shows the whole Sessions trail, and carries ids only", () => {
        const fromRun = continuedState(run, continuedState(`${base}/sessions/${S}`, undefined))
        const model = modelOf(`${base}/characters/ch1`, fromRun)
        expect(summary(model.ancestors)).toEqual([
            ["Sessions", `${base}/sessions`],
            ["Session", `${base}/sessions/${S}`],
            ["Run session", run],
        ])
        expect(JSON.stringify(fromRun)).not.toMatch(/Hollow|name|label/i)
    })
})
