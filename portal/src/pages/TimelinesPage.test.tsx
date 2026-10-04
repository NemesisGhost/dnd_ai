import { fireEvent, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import type { TimelineSummary } from "../types/worldAuthoring"
import { TimelinePage } from "./TimelinePage"
import { TimelinesPage } from "./TimelinesPage"

const tl = (over: Partial<TimelineSummary> = {}): TimelineSummary => ({
    timeline_id: "t1",
    name: "Main",
    description: null,
    is_primary: true,
    parent_timeline_id: null,
    branch_point: null,
    lifecycle_status: "active",
    row_version: 1,
    ...over,
})

const world = (over: object = {}) => ({
    world_id: "w1",
    name: "World One",
    timelines: [
        tl(),
        tl({ timeline_id: "t2", name: "Bridge", is_primary: false, parent_timeline_id: "t1" }),
        tl({ timeline_id: "t3", name: "Elsewhere", is_primary: false }),
    ],
    available_actions: ["create_timeline"],
    blocked_actions: [],
    ...over,
})

const routes = [
    { path: "/worlds/:worldId/timelines", element: <TimelinesPage /> },
    { path: "/worlds/:worldId/timelines/:timelineId", element: <TimelinePage /> },
]

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("TimelinesPage", () => {
    it("lists every authorized timeline of the route world, each linking to its detail route", async () => {
        const server = installMockServer()
        server.on("GET", "/worlds/w1", { body: world() })
        renderAuthoringRoutes({ initialEntry: "/worlds/w1/timelines", routes })

        expect(await screen.findByRole("link", { name: "Main" })).toHaveAttribute(
            "href",
            "/worlds/w1/timelines/t1",
        )
        expect(screen.getByRole("link", { name: "Bridge" })).toHaveAttribute(
            "href",
            "/worlds/w1/timelines/t2",
        )
        expect(screen.getByRole("link", { name: "Elsewhere" })).toHaveAttribute(
            "href",
            "/worlds/w1/timelines/t3",
        )
        expect(screen.getByRole("heading", { level: 1, name: "Timelines" })).toBeInTheDocument()
        // Only the world read is made: not scoped to any campaign.
        expect(server.calls.map((call) => call.path)).toEqual(["/worlds/w1"])
    })

    it("offers New timeline only when the server says it is available", async () => {
        const server = installMockServer()
        server.on("GET", "/worlds/w1", { body: world({ available_actions: [] }) })
        renderAuthoringRoutes({ initialEntry: "/worlds/w1/timelines", routes })

        await screen.findByRole("link", { name: "Main" })
        expect(screen.queryByRole("link", { name: "New timeline" })).toBeNull()
    })

    it("shows a loading status, then an empty state", async () => {
        const server = installMockServer()
        server.on("GET", "/worlds/w1", { body: world({ timelines: [] }) })
        renderAuthoringRoutes({ initialEntry: "/worlds/w1/timelines", routes })

        expect(screen.getByRole("status")).toHaveTextContent("Loading timelines")
        expect(await screen.findByText("This world has no timelines.")).toBeInTheDocument()
    })

    it("is non-disclosing for a denied or unavailable world", async () => {
        for (const status of [403, 404]) {
            const server = installMockServer()
            server.on("GET", "/worlds/w9", { status, body: { detail: "secret-world-name" } })
            const { unmount } = renderAuthoringRoutes({
                initialEntry: "/worlds/w9/timelines",
                routes,
            })

            expect(await screen.findByRole("alert")).toHaveTextContent(
                "does not exist, or you do not have access",
            )
            expect(
                screen.getByRole("heading", { level: 1, name: "Timelines not available" }),
            ).toBeInTheDocument()
            expect(document.body.innerHTML).not.toContain("secret-world-name")
            expect(screen.queryByRole("link", { name: "World overview" })).toBeNull()
            unmount()
        }
    })

    it("recovers from a failed load with Try again", async () => {
        const server = installMockServer()
        let attempts = 0
        server.on("GET", "/worlds/w1", () => {
            attempts += 1
            return attempts === 1 ? { status: 500, body: {} } : { body: world() }
        })
        renderAuthoringRoutes({ initialEntry: "/worlds/w1/timelines", routes })

        expect(await screen.findByRole("alert")).toHaveTextContent("could not be loaded")
        fireEvent.click(screen.getByRole("button", { name: "Try again" }))
        expect(await screen.findByRole("link", { name: "Main" })).toBeInTheDocument()
    })

    it("does not show a previous world's timelines under the next world", async () => {
        const server = installMockServer()
        server.on("GET", "/worlds/w1", { body: world() })
        server.on("GET", "/worlds/w2", async () => {
            await new Promise(() => {})
            return { body: {} }
        })
        const { router } = renderAuthoringRoutes({ initialEntry: "/worlds/w1/timelines", routes })
        await screen.findByRole("link", { name: "Main" })

        await router.navigate("/worlds/w2/timelines")

        await waitFor(() => expect(screen.getByRole("status")).toBeInTheDocument())
        expect(screen.queryByRole("link", { name: "Main" })).toBeNull()
    })
})

describe("Timeline detail as an independent route", () => {
    it("reloads from its own URL without any campaign context, linking back to its world", async () => {
        const server = installMockServer()
        server.on("GET", "/worlds/w1/timelines/t2", {
            body: {
                ...tl({ timeline_id: "t2", name: "Bridge", is_primary: false }),
                children: [],
                managed_campaigns: [],
                available_actions: [],
                blocked_actions: [],
            },
        })
        renderAuthoringRoutes({ initialEntry: "/worlds/w1/timelines/t2", routes })

        expect(await screen.findByRole("heading", { level: 1, name: "Bridge" })).toBeInTheDocument()
        expect(screen.getByRole("link", { name: "World overview" })).toHaveAttribute(
            "href",
            "/worlds/w1",
        )
        expect(screen.getByRole("link", { name: "Timelines" })).toHaveAttribute(
            "href",
            "/worlds/w1/timelines",
        )
        expect(server.calls.map((call) => call.path)).toEqual(["/worlds/w1/timelines/t2"])
    })

    it("rejects a timeline that belongs to another world without disclosure", async () => {
        const server = installMockServer()
        server.on("GET", "/worlds/w1/timelines/other-world-timeline", { status: 404 })
        renderAuthoringRoutes({
            initialEntry: "/worlds/w1/timelines/other-world-timeline",
            routes,
        })

        expect(await screen.findByRole("alert")).toHaveTextContent(
            "does not exist, or you do not have access",
        )
        expect(screen.queryByRole("heading", { level: 1, name: "Bridge" })).toBeNull()
    })
})
