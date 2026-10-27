import { fireEvent, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { CreateWorldRoute, EditWorldRoute } from "../layouts/WorldAccessRoutes"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import type { MockServer } from "../test/authoringHarness"
import { CreateCalendarPage } from "./CreateCalendarPage"
import { CreateTimelineBranchPage } from "./CreateTimelineBranchPage"
import { CreateTimelinePage } from "./CreateTimelinePage"
import { WorldSharingPage } from "./WorldSharingPage"

// The presentation policy for unavailable and unauthorized destinations (docs/UI_DESIGN.md,
// "Unavailable and unauthorized destinations"), checked on the world-level pages. The campaign
// pages are in App.unavailableStates.test.tsx.

afterEach(() => {
    vi.unstubAllGlobals()
    document.title = "portal"
})

const WORLD = {
    world_id: "w1",
    name: "Eberron",
    description: null,
    lifecycle_status: "active",
    row_version: 3,
    capabilities: ["world.view"],
    default_ruleset_id: null,
    allowed_rulesets: [],
    timelines: [],
    managed_campaigns: [],
    available_actions: [] as string[],
    blocked_actions: [] as { action: string; reason: string }[],
}
const TIMELINE = {
    timeline_id: "t1",
    name: "Main",
    description: null,
    is_primary: true,
    parent_timeline_id: null,
    branch_point: null,
    lifecycle_status: "active",
    row_version: 2,
    children: [],
    managed_campaigns: [],
    available_actions: ["create_branch"],
    blocked_actions: [] as { action: string; reason: string }[],
}
const SERVER_ERROR = { status: 500, body: { error: { code: "internal", message: "m", correlation_id: "c" } } }
const NOT_FOUND = { status: 404, body: { error: { code: "not_found", message: "m", correlation_id: "c" } } }
const FORBIDDEN = { status: 403, body: { error: { code: "forbidden", message: "m", correlation_id: "c" } } }

const nonGet = (server: MockServer) => server.calls.filter((call) => call.method !== "GET")

describe("a static destination the account lacks the capability for", () => {
    const routes = [{ path: "/worlds/new", element: <CreateWorldRoute /> }]

    it("mounts the form and asks for rulesets for a creator", async () => {
        const server = installMockServer()
        server.on("GET", "/rulesets", { body: { items: [] } })
        renderAuthoringRoutes({ initialEntry: "/worlds/new", routes })
        expect(await screen.findByRole("heading", { level: 1, name: "Create a world" })).toBeInTheDocument()
        expect(server.callsTo("GET", "/rulesets")).toHaveLength(1)
    })

    it("denies explicitly, mounting no form and sending no request, for a Player", async () => {
        const server = installMockServer()
        renderAuthoringRoutes({
            initialEntry: "/worlds/new",
            routes,
            bootstrap: bootstrapWith({ global_capabilities: [] }),
        })
        const heading = await screen.findByRole("heading", { level: 1, name: "Access denied" })
        // One focus move on arrival is the announcement; there is no second live region.
        await waitFor(() => expect(heading).toHaveFocus())
        expect(screen.queryByRole("alert")).toBeNull()
        expect(document.title).toBe("Access denied · portal")
        expect(screen.queryByRole("main")).toBeNull()
        expect(screen.queryByRole("textbox")).toBeNull()
        expect(screen.getByRole("link", { name: "Go to Worlds" })).toHaveAttribute("href", "/worlds")
        expect(server.calls).toEqual([])
    })

    it("puts the previous document title back when the person leaves", async () => {
        installMockServer()
        document.title = "Elsewhere"
        const view = renderAuthoringRoutes({
            initialEntry: "/worlds/new",
            routes: [...routes, { path: "/worlds", element: <p>Worlds list</p> }],
            bootstrap: bootstrapWith({ global_capabilities: [] }),
        })
        await screen.findByRole("heading", { name: "Access denied" })
        expect(document.title).toBe("Access denied · portal")
        fireEvent.click(screen.getByRole("link", { name: "Go to Worlds" }))
        await screen.findByText("Worlds list")
        expect(document.title).toBe("Elsewhere")
        view.unmount()
    })
})

describe("/worlds/:worldId/edit", () => {
    const routes = [{ path: "/worlds/:worldId/edit", element: <EditWorldRoute /> }]
    const open = (server: MockServer) => {
        void server
        return renderAuthoringRoutes({ initialEntry: "/worlds/w1/edit", routes })
    }

    it("opens the form for an owner", async () => {
        const server = installMockServer()
        server.on("GET", "/worlds/w1", { body: { ...WORLD, available_actions: ["update"] } })
        open(server)
        expect(await screen.findByRole("textbox", { name: /World name/ })).toHaveValue("Eberron")
    })

    it("tells a Player + Editor + Reviewer their role does not include editing, sending no write", async () => {
        const server = installMockServer()
        server.on("GET", "/worlds/w1", { body: { ...WORLD, available_actions: [] } })
        open(server)
        const heading = await screen.findByRole("heading", { level: 1, name: "Editing unavailable" })
        await waitFor(() => expect(heading).toHaveFocus())
        expect(screen.getByRole("alert")).toHaveTextContent("Your role on this world does not include being able to edit it")
        expect(screen.queryByRole("textbox")).toBeNull()
        expect(screen.getByRole("link", { name: "Back to Eberron" })).toHaveAttribute("href", "/worlds/w1")
        expect(document.title).toBe("Action unavailable · portal")
        expect(nonGet(server)).toEqual([])
    })

    it("names the world's state, not the role, for an archived or blocked world", async () => {
        const server = installMockServer()
        server.on("GET", "/worlds/w1", {
            body: {
                ...WORLD,
                lifecycle_status: "archived",
                available_actions: ["restore"],
                blocked_actions: [{ action: "update", reason: "entity_archived" }],
            },
        })
        open(server)
        expect(await screen.findByRole("alert")).toHaveTextContent("the record is archived")
        expect(screen.getByRole("alert")).not.toHaveTextContent("Your role")
    })

    it("gives a missing world and a hidden world the same output", async () => {
        const outputs: string[] = []
        for (const body of [NOT_FOUND.body, { error: { code: "hidden", message: "other", correlation_id: "z" } }]) {
            const server = installMockServer()
            server.on("GET", "/worlds/w1", { status: 404, body })
            const view = open(server)
            await screen.findByRole("heading", { level: 1, name: "World not available" })
            outputs.push(`${document.title}|${view.container.innerHTML}`)
            view.unmount()
        }
        expect(outputs[0]).toBe(outputs[1])
        expect(outputs[0]).not.toContain("Eberron")
    })

    it("says a refusal is a refusal, and a failure is a failure that only a read can retry", async () => {
        const denied = installMockServer()
        denied.on("GET", "/worlds/w1", FORBIDDEN)
        const view = open(denied)
        expect(await screen.findByRole("heading", { level: 1, name: "Access denied" })).toBeInTheDocument()
        expect(screen.getByRole("alert")).toHaveTextContent("You do not have access to the world")
        expect(screen.queryByRole("button", { name: "Try again" })).toBeNull()
        view.unmount()

        const failing = installMockServer()
        let fail = true
        failing.on("GET", "/worlds/w1", () =>
            fail ? SERVER_ERROR : { body: { ...WORLD, available_actions: ["update"] } },
        )
        open(failing)
        expect(await screen.findByRole("heading", { level: 1, name: "World could not be loaded" })).toBeInTheDocument()
        expect(screen.getByRole("alert")).toHaveTextContent("could not be loaded")
        fail = false
        fireEvent.click(screen.getByRole("button", { name: "Try again" }))
        expect(await screen.findByRole("textbox", { name: /World name/ })).toBeInTheDocument()
        expect(nonGet(failing)).toEqual([])
    })

    it("has one page structure while loading, with its heading and breadcrumb", async () => {
        const server = installMockServer()
        server.on("GET", "/worlds/w1", () => new Promise(() => undefined) as never)
        open(server)
        expect(screen.getByRole("heading", { level: 1, name: "Edit world" })).toBeInTheDocument()
        expect(screen.getByRole("status")).toHaveTextContent("Loading")
        expect(screen.getByRole("link", { name: "Worlds" })).toBeInTheDocument()
    })
})

describe("first-load failures differ from refusals on the world pages", () => {
    const cases: [string, string, string, { path: string; element: React.ReactNode }, (s: MockServer, r: object) => void][] = [
        [
            "new timeline",
            "/worlds/w1/timelines/new",
            "world",
            { path: "/worlds/:worldId/timelines/new", element: <CreateTimelinePage /> },
            (s, r) => s.on("GET", "/worlds/w1", r),
        ],
        [
            "new calendar",
            "/worlds/w1/calendars/new",
            "world",
            { path: "/worlds/:worldId/calendars/new", element: <CreateCalendarPage /> },
            (s, r) => s.on("GET", "/worlds/w1", r),
        ],
        [
            "sharing",
            "/worlds/w1/sharing",
            "sharing list",
            { path: "/worlds/:worldId/sharing", element: <WorldSharingPage /> },
            (s, r) => {
                s.on("GET", "/worlds/w1", { body: WORLD })
                s.on("GET", "/worlds/w1/access", r)
            },
        ],
        [
            "branch",
            "/worlds/w1/timelines/t1/branch",
            "timeline",
            { path: "/worlds/:worldId/timelines/:timelineId/branch", element: <CreateTimelineBranchPage /> },
            (s, r) => {
                s.on("GET", "/worlds/w1/timelines/t1", r)
                s.on("GET", /\/branch-points/, { body: { items: [] } })
            },
        ],
    ]

    it.each(cases)("%s: 500 offers a read-only retry; 403 and 404 do not", async (_name, entry, what, route, wire) => {
        const results: string[] = []
        for (const [response, expected, retry] of [
            [SERVER_ERROR, `The ${what} could not be loaded.`, true],
            [FORBIDDEN, `You do not have access to the ${what}.`, false],
            [NOT_FOUND, `The ${what} is not available, or you can no longer access it.`, false],
        ] as const) {
            const server = installMockServer()
            wire(server, response)
            const view = renderAuthoringRoutes({ initialEntry: entry, routes: [route] })
            expect(await screen.findByText(expected)).toBeInTheDocument()
            expect(screen.queryByRole("button", { name: "Try again" }) !== null).toBe(retry)
            expect(nonGet(server)).toEqual([])
            results.push(expected)
            view.unmount()
        }
        expect(new Set(results).size).toBe(3)
    })

    it("does not turn a failed branch-point read into an empty catalog, and retrying only reads", async () => {
        const server = installMockServer()
        server.on("GET", "/worlds/w1/timelines/t1", { body: TIMELINE })
        let fail = true
        server.on("GET", /\/branch-points/, () => (fail ? SERVER_ERROR : { body: { items: [] } }))
        renderAuthoringRoutes({
            initialEntry: "/worlds/w1/timelines/t1/branch",
            routes: [
                { path: "/worlds/:worldId/timelines/:timelineId/branch", element: <CreateTimelineBranchPage /> },
            ],
        })
        expect(await screen.findByText("The list of branch points could not be loaded.")).toBeInTheDocument()
        expect(screen.queryByRole("textbox", { name: /Branch name/ })).toBeNull()
        fail = false
        fireEvent.click(screen.getByRole("button", { name: "Try again" }))
        expect(await screen.findByRole("textbox", { name: /Branch name/ })).toBeInTheDocument()
        expect(nonGet(server)).toEqual([])
    })

    it("explains an archived timeline from its lifecycle, not its role", async () => {
        const server = installMockServer()
        server.on("GET", "/worlds/w1/timelines/t1", {
            body: { ...TIMELINE, lifecycle_status: "archived", available_actions: ["restore"] },
        })
        server.on("GET", /\/branch-points/, { body: { items: [] } })
        renderAuthoringRoutes({
            initialEntry: "/worlds/w1/timelines/t1/branch",
            routes: [
                { path: "/worlds/:worldId/timelines/:timelineId/branch", element: <CreateTimelineBranchPage /> },
            ],
        })
        expect(await screen.findByRole("alert")).toHaveTextContent("because it is archived")
    })
})

describe("a 401 on a first read", () => {
    it("reloads the session instead of showing a terminal state", async () => {
        const server = installMockServer()
        server.on("GET", "/worlds/w1", { status: 401, body: { error: { code: "unauthenticated", message: "m", correlation_id: "c" } } })
        const view = renderAuthoringRoutes({
            initialEntry: "/worlds/w1/edit",
            routes: [{ path: "/worlds/:worldId/edit", element: <EditWorldRoute /> }],
        })
        await waitFor(() => expect(view.reload).toHaveBeenCalled())
        expect(screen.queryByRole("alert")).toBeNull()
    })
})
