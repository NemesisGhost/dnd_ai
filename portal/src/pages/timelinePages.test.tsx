import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import { afterEach, describe, expect, it, vi } from "vitest"
import { TimelineTree } from "../components/TimelineTree"
import { installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import type { TimelineSummary } from "../types/worldAuthoring"
import { describeBranchPoint } from "../utils/branchPoints"
import { CreateTimelineBranchPage } from "./CreateTimelineBranchPage"
import { CreateTimelinePage } from "./CreateTimelinePage"
import { EditTimelinePage } from "./EditTimelinePage"
import { TimelinePage } from "./TimelinePage"

const tl = (over: Partial<TimelineSummary> = {}): TimelineSummary => ({
    timeline_id: "t1",
    name: "Main",
    description: null,
    is_primary: true,
    parent_timeline_id: null,
    branch_point: null,
    lifecycle_status: "active",
    row_version: 2,
    ...over,
})

const detail = (over: object = {}) => ({
    ...tl(),
    children: [],
    managed_campaigns: [],
    available_actions: ["update", "create_branch", "create_campaign"],
    blocked_actions: [],
    ...over,
})

const routes = [
    { path: "/worlds/:worldId/timelines/new", element: <CreateTimelinePage /> },
    { path: "/worlds/:worldId/timelines/:timelineId", element: <TimelinePage /> },
    { path: "/worlds/:worldId/timelines/:timelineId/edit", element: <EditTimelinePage /> },
    { path: "/worlds/:worldId/timelines/:timelineId/branch", element: <CreateTimelineBranchPage /> },
    { path: "/worlds/:worldId", element: <p>World page</p> },
]

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("TimelineTree", () => {
    it("nests branches under their parent and shows the branch point in words", () => {
        render(
            <MemoryRouter>
                <TimelineTree
                    worldId="w1"
                    timelines={[
                        tl(),
                        tl({
                            timeline_id: "t2",
                            name: "Bridge",
                            is_primary: false,
                            parent_timeline_id: "t1",
                            branch_point: { world_time_id: "x", label: "The Night the Bridge Fell", sort_key: 0 },
                        }),
                        tl({ timeline_id: "t3", name: "Old", is_primary: false, lifecycle_status: "archived" }),
                    ]}
                />
            </MemoryRouter>,
        )
        const nested = screen.getByRole("group")
        expect(nested).toHaveTextContent("Bridge")
        expect(nested).toHaveTextContent("branched at The Night the Bridge Fell")
        expect(screen.getByText("Primary")).toBeInTheDocument()
        expect(screen.getByText("Archived")).toBeInTheDocument()
    })
})

describe("describeBranchPoint", () => {
    it("prefers the label, then the date, then the position, never an id", () => {
        const base = { world_time_id: "SECRET", month_number: null, day: null, sort_key: 7 }
        expect(describeBranchPoint({ ...base, label: "The Fall", year: 1 })).toBe("The Fall")
        expect(describeBranchPoint({ ...base, label: null, year: 1042, month_number: 3, day: 5 })).toBe(
            "Year 1042, month 3, day 5",
        )
        expect(describeBranchPoint({ ...base, label: null, year: null })).toBe("Unlabeled point (position 7)")
    })
})

describe("TimelinePage", () => {
    it("shows server-driven actions, branches, and explains blocked ones", async () => {
        const server = installMockServer()
        server.on("GET", "/worlds/w1/timelines/t1", {
            body: detail({
                blocked_actions: [{ action: "archive", reason: "primary_timeline_not_archivable" }],
                children: [tl({ timeline_id: "t2", name: "Child", is_primary: false, parent_timeline_id: "t1" })],
            }),
        })
        renderAuthoringRoutes({ initialEntry: "/worlds/w1/timelines/t1", routes })
        expect(await screen.findByRole("heading", { level: 1, name: "Main" })).toBeInTheDocument()
        expect(screen.getByRole("link", { name: "Create branch" })).toHaveAttribute(
            "href",
            "/worlds/w1/timelines/t1/branch",
        )
        expect(screen.getByRole("list", { name: "Unavailable actions" })).toHaveTextContent(
            "primary timeline cannot be archived",
        )
        expect(screen.queryByRole("button", { name: "Archive timeline" })).not.toBeInTheDocument()
        expect(screen.getByRole("link", { name: "Child" })).toBeInTheDocument()
    })

    it("hides Create branch for an archived parent and shows the reason", async () => {
        const server = installMockServer()
        server.on("GET", "/worlds/w1/timelines/t1", {
            body: detail({
                is_primary: false,
                lifecycle_status: "archived",
                available_actions: ["restore"],
                blocked_actions: [{ action: "create_branch", reason: "timeline_archived" }],
            }),
        })
        renderAuthoringRoutes({ initialEntry: "/worlds/w1/timelines/t1", routes })
        await screen.findByRole("heading", { level: 1, name: "Main" })
        expect(screen.queryByRole("link", { name: "Create branch" })).not.toBeInTheDocument()
        expect(screen.getByRole("button", { name: "Restore timeline" })).toBeInTheDocument()
        expect(screen.getByRole("list", { name: "Unavailable actions" })).toHaveTextContent("timeline is archived")
    })

    it("is non-disclosing when the timeline cannot be reached", async () => {
        installMockServer().on("GET", "/worlds/w1/timelines/t1", { status: 404 })
        renderAuthoringRoutes({ initialEntry: "/worlds/w1/timelines/t1", routes })
        expect(await screen.findByRole("alert")).toHaveTextContent("does not exist, or you do not have access")
    })
})

describe("CreateTimelinePage", () => {
    it("validates, then creates and navigates with an announcement", async () => {
        const server = installMockServer()
        server.on("GET", "/worlds/w1", {
            body: { name: "World", available_actions: ["create_timeline"] },
        })
        server.on("POST", "/worlds/w1/timelines", { status: 201, body: { timeline_id: "t9", row_version: 1 } })
        const { router } = renderAuthoringRoutes({ initialEntry: "/worlds/w1/timelines/new", routes })
        await screen.findByRole("textbox", { name: /Timeline name/ })

        fireEvent.click(screen.getByRole("button", { name: "Create timeline" }))
        expect(await screen.findByRole("alert")).toHaveTextContent("Name is required.")
        expect(server.callsTo("POST", "/worlds/w1/timelines")).toHaveLength(0)

        fireEvent.change(screen.getByRole("textbox", { name: /Timeline name/ }), { target: { value: "Side" } })
        fireEvent.click(screen.getByRole("button", { name: "Create timeline" }))
        await waitFor(() => expect(router.state.location.pathname).toBe("/worlds/w1/timelines/t9"))
        expect(router.state.location.state).toEqual({ announce: "Timeline created" })
    })

    it("refuses when the server does not offer create_timeline", async () => {
        installMockServer().on("GET", "/worlds/w1", { body: { name: "World", available_actions: [] } })
        renderAuthoringRoutes({ initialEntry: "/worlds/w1/timelines/new", routes })
        expect(await screen.findByRole("alert")).toHaveTextContent("cannot be added")
    })
})

describe("EditTimelinePage", () => {
    it("recovers from a stale write keeping the user's values", async () => {
        const server = installMockServer()
        let current: object = detail({ name: "Main", row_version: 2 })
        server.on("GET", "/worlds/w1/timelines/t1", () => ({ body: current }))
        server.on("POST", "/worlds/w1/timelines/t1/update", {
            status: 409,
            body: { error: { code: "stale_write", message: "m", correlation_id: "c" } },
        })
        renderAuthoringRoutes({ initialEntry: "/worlds/w1/timelines/t1/edit", routes })
        const name = await screen.findByRole("textbox", { name: /Timeline name/ })
        fireEvent.change(name, { target: { value: "Mine" } })
        fireEvent.click(screen.getByRole("button", { name: "Save" }))
        await screen.findByRole("button", { name: "Load latest version" })

        current = detail({ name: "Theirs", row_version: 5 })
        fireEvent.click(screen.getByRole("button", { name: "Load latest version" }))
        await waitFor(() => expect(screen.getByRole("textbox", { name: /Timeline name/ })).toHaveValue("Theirs"))
        expect(screen.getByRole("region", { name: "Your unsaved changes" })).toHaveTextContent("Mine")
    })
})

describe("CreateTimelineBranchPage", () => {
    const history = {
        items: [
            { world_time_id: "wt2", label: null, year: 1042, month_number: 3, day: null, sort_key: 20 },
            { world_time_id: "wt1", label: "The Betrayal", year: null, month_number: null, day: null, sort_key: 10 },
        ],
        next_cursor: null,
    }

    function setup(points: object = history, timeline: object = detail()) {
        const server = installMockServer()
        server.on("GET", "/worlds/w1/timelines/t1", { body: timeline })
        server.on("GET", /^\/worlds\/w1\/timelines\/t1\/branch-points/, { body: points })
        return { server, ...renderAuthoringRoutes({ initialEntry: "/worlds/w1/timelines/t1/branch", routes }) }
    }

    it("creates a 'latest' branch with a required label", async () => {
        const { server, router } = setup()
        server.on("POST", "/worlds/w1/timelines/t1/branches", {
            status: 201,
            body: { timeline_id: "t7", branch_world_time_id: "wtn", row_version: 1 },
        })
        await screen.findByRole("textbox", { name: /Branch name/ })
        fireEvent.change(screen.getByRole("textbox", { name: /Branch name/ }), { target: { value: "Bridge" } })
        fireEvent.click(screen.getByRole("button", { name: "Create branch" }))
        expect(await screen.findByRole("alert")).toHaveTextContent("A label is required.")

        fireEvent.change(screen.getByRole("textbox", { name: /Label for the branch point/ }), {
            target: { value: "The night the bridge fell" },
        })
        fireEvent.click(screen.getByRole("button", { name: "Create branch" }))
        await waitFor(() => expect(router.state.location.pathname).toBe("/worlds/w1/timelines/t7"))
        expect(server.callsTo("POST", "/worlds/w1/timelines/t1/branches")[0]!.body).toEqual({
            name: "Bridge",
            description: null,
            branch_point: { kind: "latest", label: "The night the bridge fell" },
        })
    })

    it("offers existing branch points only from the server list, described in words", async () => {
        const { server } = setup()
        server.on("POST", "/worlds/w1/timelines/t1/branches", {
            status: 201,
            body: { timeline_id: "t7", branch_world_time_id: "wt1", row_version: 1 },
        })
        await screen.findByRole("textbox", { name: /Branch name/ })
        fireEvent.change(screen.getByRole("textbox", { name: /Branch name/ }), { target: { value: "B" } })
        fireEvent.click(screen.getByRole("radio", { name: "An earlier moment in its history" }))
        const select = screen.getByRole("combobox", { name: /Branch point/ })
        expect(Array.from(select.querySelectorAll("option")).map((o) => o.textContent)).toEqual([
            "Choose a moment",
            "Year 1042, month 3",
            "The Betrayal",
        ])
        expect(document.body.textContent).not.toMatch(/wt1|wt2/)
        fireEvent.change(select, { target: { value: "wt1" } })
        fireEvent.click(screen.getByRole("button", { name: "Create branch" }))
        await waitFor(() => expect(server.callsTo("POST", "/worlds/w1/timelines/t1/branches")).toHaveLength(1))
        expect(server.callsTo("POST", "/worlds/w1/timelines/t1/branches")[0]!.body).toMatchObject({
            branch_point: { kind: "existing_world_time", world_time_id: "wt1" },
        })
    })

    it("explains why only 'latest' is available when there is no history", async () => {
        setup({ items: [], next_cursor: null })
        await screen.findByRole("textbox", { name: /Branch name/ })
        expect(screen.getByText(/this timeline has no recorded history/)).toBeInTheDocument()
        fireEvent.click(screen.getByRole("radio", { name: "An earlier moment in its history" }))
        expect(screen.getByRole("combobox", { name: /Branch point/ })).toBeDisabled()
    })

    it("maps branch_point_invalid onto the branch point field and keeps input", async () => {
        const { server } = setup()
        server.on("POST", "/worlds/w1/timelines/t1/branches", {
            status: 400,
            body: { error: { code: "branch_point_invalid", message: "m", correlation_id: "c" } },
        })
        await screen.findByRole("textbox", { name: /Branch name/ })
        fireEvent.change(screen.getByRole("textbox", { name: /Branch name/ }), { target: { value: "B" } })
        fireEvent.click(screen.getByRole("radio", { name: "An earlier moment in its history" }))
        fireEvent.change(screen.getByRole("combobox", { name: /Branch point/ }), { target: { value: "wt1" } })
        fireEvent.click(screen.getByRole("button", { name: "Create branch" }))
        expect(await screen.findByText(/not valid for this timeline/, { selector: "p.authoring-field__error" })).toBeInTheDocument()
        expect(screen.getByRole("textbox", { name: /Branch name/ })).toHaveValue("B")
    })

    it("does not offer branching for an archived parent", async () => {
        setup(history, detail({ available_actions: ["restore"], lifecycle_status: "archived" }))
        expect(await screen.findByRole("alert")).toHaveTextContent("cannot be branched right now")
        expect(screen.queryByRole("textbox", { name: /Branch name/ })).not.toBeInTheDocument()
    })
})

// A `world_viewer` (world.view only): the server sends no available or
// blocked action on the world or its timelines (dnd_ai.domain.world_authority.
// authorized_actions), so every timeline page renders read-only and no form
// mounts, whatever the timeline's lifecycle state.
describe("world_viewer timeline pages", () => {
    const viewerTimeline = detail({ available_actions: [], blocked_actions: [] })

    it("shows the timeline with no action, link, or unavailable-action list", async () => {
        const server = installMockServer()
        server.on("GET", "/worlds/w1/timelines/t1", {
            body: {
                ...viewerTimeline,
                children: [tl({ timeline_id: "t2", name: "Child", is_primary: false, parent_timeline_id: "t1" })],
            },
        })
        renderAuthoringRoutes({ initialEntry: "/worlds/w1/timelines/t1", routes })
        await screen.findByRole("heading", { level: 1, name: "Main" })

        for (const name of ["Edit timeline", "Create branch", "New campaign"]) {
            expect(screen.queryByRole("link", { name })).not.toBeInTheDocument()
        }
        for (const name of ["Archive timeline", "Restore timeline"]) {
            expect(screen.queryByRole("button", { name })).not.toBeInTheDocument()
        }
        expect(screen.queryByRole("list", { name: "Unavailable actions" })).not.toBeInTheDocument()
        expect(server.calls.filter((call) => call.method === "POST")).toHaveLength(0)
    })

    it("never mounts the edit, branch, or new-timeline forms", async () => {
        const server = installMockServer()
        server.on("GET", "/worlds/w1/timelines/t1", { body: viewerTimeline })
        server.on("GET", /^\/worlds\/w1\/timelines\/t1\/branch-points/, {
            body: { items: [], next_cursor: null },
        })
        server.on("GET", "/worlds/w1", {
            body: { name: "World", capabilities: ["world.view"], available_actions: [] },
        })

        const edit = renderAuthoringRoutes({ initialEntry: "/worlds/w1/timelines/t1/edit", routes })
        expect(await screen.findByRole("alert")).toHaveTextContent("cannot be edited")
        expect(screen.queryByRole("textbox")).not.toBeInTheDocument()
        edit.unmount()

        const branch = renderAuthoringRoutes({ initialEntry: "/worlds/w1/timelines/t1/branch", routes })
        expect(await screen.findByRole("alert")).toHaveTextContent("cannot be branched")
        expect(screen.queryByRole("textbox")).not.toBeInTheDocument()
        branch.unmount()

        renderAuthoringRoutes({ initialEntry: "/worlds/w1/timelines/new", routes })
        expect(await screen.findByRole("alert")).toHaveTextContent("cannot be added")
        expect(screen.queryByRole("textbox")).not.toBeInTheDocument()
        expect(server.calls.filter((call) => call.method === "POST")).toHaveLength(0)
    })
})
