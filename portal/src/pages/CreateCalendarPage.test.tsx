import { fireEvent, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { TEST_CSRF, installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import { CreateCalendarPage } from "./CreateCalendarPage"

const WORLD_PATH = "/worlds/w1"
const CREATE_PATH = "/worlds/w1/calendars"

const WORLD = (actions: string[]) => ({
    world_id: "w1",
    name: "Mundivita",
    description: null,
    lifecycle_status: "active",
    row_version: 1,
    primary_timeline_id: "t1",
    capabilities: ["campaign.create", "timeline.manage", "world.manage", "world.view"],
    allowed_rulesets: [],
    timelines: [],
    managed_campaigns: [],
    available_actions: actions,
    blocked_actions: [],
})

function setup(actions: string[] = ["update", "create_calendar"]) {
    const server = installMockServer()
    server.on("GET", WORLD_PATH, { body: WORLD(actions) })
    const rendered = renderAuthoringRoutes({
        initialEntry: "/worlds/w1/calendars/new",
        routes: [
            { path: "/worlds/:worldId/calendars/new", element: <CreateCalendarPage /> },
            { path: "/worlds/:worldId", element: <p>World overview page</p> },
        ],
    })
    return { server, ...rendered }
}

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("CreateCalendarPage", () => {
    it("takes focus on the heading and sends no write on open", async () => {
        const { server } = setup()
        const heading = await screen.findByRole("heading", { level: 1, name: "New calendar" })
        await waitFor(() => expect(heading).toHaveFocus())
        expect(server.callsTo("POST", /./)).toEqual([])
    })

    it("says so, without a form, when the world offers no calendar creation", async () => {
        setup(["update"])
        expect(await screen.findByRole("alert")).toHaveTextContent("cannot create a calendar")
        expect(screen.queryByRole("form")).toBeNull()
    })

    it("explains an unavailable world", async () => {
        const server = installMockServer()
        server.on("GET", WORLD_PATH, { status: 404 })
        renderAuthoringRoutes({
            initialEntry: "/worlds/w1/calendars/new",
            routes: [{ path: "/worlds/:worldId/calendars/new", element: <CreateCalendarPage /> }],
        })
        expect(await screen.findByRole("alert")).toHaveTextContent("unavailable")
    })

    it("adds and removes month rows", async () => {
        setup()
        await screen.findByRole("form", { name: "Create calendar" })
        expect(screen.queryByRole("button", { name: /Remove month/ })).toBeNull()
        fireEvent.click(screen.getByRole("button", { name: "Add a month" }))
        expect(screen.getByRole("textbox", { name: /Month 2 name/ })).toBeInTheDocument()
        fireEvent.click(screen.getByRole("button", { name: "Remove month 2" }))
        expect(screen.queryByRole("textbox", { name: /Month 2 name/ })).toBeNull()
    })

    it("validates before sending, focuses the summary, and keeps the input", async () => {
        const { server } = setup()
        await screen.findByRole("form", { name: "Create calendar" })
        fireEvent.change(screen.getByRole("textbox", { name: /Month 1 name/ }), {
            target: { value: "Frost" },
        })
        fireEvent.click(screen.getByRole("button", { name: "Create calendar" }))
        const summary = await screen.findByRole("alert")
        expect(summary).toHaveTextContent("Enter a name for the calendar.")
        await waitFor(() => expect(summary).toHaveFocus())
        expect(server.callsTo("POST", CREATE_PATH)).toHaveLength(0)
        expect(screen.getByRole("textbox", { name: /Month 1 name/ })).toHaveValue("Frost")
    })

    it("creates with CSRF and an idempotency key, then replaces history and announces", async () => {
        const { server, router } = setup()
        server.on("POST", CREATE_PATH, {
            status: 201,
            body: { calendar_id: "cal-1", created: true, changed: true },
        })
        await screen.findByRole("form", { name: "Create calendar" })
        fireEvent.change(screen.getByRole("textbox", { name: /Calendar name/ }), {
            target: { value: " Common Reckoning " },
        })
        fireEvent.change(screen.getByRole("textbox", { name: /Month 1 name/ }), {
            target: { value: "Frost" },
        })
        fireEvent.change(screen.getByRole("textbox", { name: /Month 1 days/ }), {
            target: { value: "30" },
        })
        fireEvent.click(screen.getByRole("button", { name: "Create calendar" }))
        await screen.findByText("World overview page")
        const [call] = server.callsTo("POST", CREATE_PATH)
        expect(call!.headers["X-CSRF-Token"]).toBe(TEST_CSRF)
        expect(call!.headers["Idempotency-Key"]).toBeTruthy()
        expect(call!.body).toEqual({
            name: "Common Reckoning",
            description: null,
            days_per_week: null,
            epoch_label: null,
            months: [{ name: "Frost", day_count: 30 }],
        })
        expect(router.state.historyAction).toBe("REPLACE")
        expect(router.state.location.state).toEqual({ announce: "Calendar created" })
    })
})
