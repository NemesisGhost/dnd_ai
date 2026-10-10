import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { TEST_CSRF, bootstrapWith, installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { WorldTimesPage } from "./WorldTimesPage"

const CAMPAIGN = sessionBootstrapFixture.campaigns[0]!.campaign_id
const TIMES_PATH = new RegExp(`/campaigns/${CAMPAIGN}/world-times`)
const CALENDARS_PATH = `/campaigns/${CAMPAIGN}/calendars`

const CALENDAR = {
    calendar_id: "cal-1",
    code: "common",
    name: "Common Reckoning",
    description: null,
    days_per_week: 7,
    epoch_label: "Founding",
    months: [
        { month_number: 1, name: "Frost", day_count: 30 },
        { month_number: 2, name: "Bloom", day_count: 28 },
    ],
}

const TIME = (id: string, display: string) => ({
    world_time_id: id,
    calendar_id: null,
    year: null,
    month_number: null,
    day: null,
    hour: null,
    minute: null,
    label: display,
    precision: "narrative",
    sort_key: 1,
    display,
})

function bootstrap(canEdit: boolean) {
    const base = bootstrapWith()
    return {
        ...base,
        campaigns: [
            {
                ...base.campaigns[0]!,
                capabilities: canEdit ? ["canon.edit"] : ["campaign.view"],
            },
        ],
    }
}

function setup(canEdit = true) {
    const server = installMockServer()
    const rendered = renderAuthoringRoutes({
        initialEntry: `/app/${CAMPAIGN}/world-times`,
        bootstrap: bootstrap(canEdit),
        routes: [
            { path: "/app/:campaignId/world-times", element: <WorldTimesPage /> },
            { path: "/app/:campaignId/home", element: <p>Campaign home page</p> },
        ],
    })
    return { server, ...rendered }
}

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("WorldTimesPage", () => {
    it("shows a denial and sends no request without canon.edit", () => {
        const { server } = setup(false)
        expect(screen.getByRole("alert")).toHaveTextContent("do not have permission")
        expect(server.callsTo("GET", /world-times|calendars/)).toHaveLength(0)
    })

    it("lists recorded times latest first and offers the form", async () => {
        const server = installMockServer()
        server.on("GET", TIMES_PATH, {
            body: { items: [TIME("t2", "After the siege"), TIME("t1", "Year 1")], next_cursor: null },
        })
        server.on("GET", CALENDARS_PATH, { body: { calendars: [CALENDAR] } })
        renderAuthoringRoutes({
            initialEntry: `/app/${CAMPAIGN}/world-times`,
            bootstrap: bootstrap(true),
            routes: [{ path: "/app/:campaignId/world-times", element: <WorldTimesPage /> }],
        })
        const heading = await screen.findByRole("heading", { level: 1, name: "World times" })
        await waitFor(() => expect(heading).toHaveFocus())
        const items = within(screen.getByRole("list")).getAllByRole("listitem")
        expect(items.map((i) => i.textContent)).toEqual([
            "After the siege (narrative)",
            "Year 1 (narrative)",
        ])
        expect(screen.getByRole("form", { name: "Record a world time" })).toBeInTheDocument()
        expect(screen.queryByRole("button", { name: "Show earlier times" })).toBeNull()
    })

    it("pages earlier times with the server cursor", async () => {
        const server = installMockServer()
        server.on("GET", TIMES_PATH, (call) =>
            call.path.includes("cursor=c1")
                ? { body: { items: [TIME("t0", "Long ago")], next_cursor: null } }
                : { body: { items: [TIME("t1", "Recent")], next_cursor: "c1" } },
        )
        server.on("GET", CALENDARS_PATH, { body: { calendars: [CALENDAR] } })
        renderAuthoringRoutes({
            initialEntry: `/app/${CAMPAIGN}/world-times`,
            bootstrap: bootstrap(true),
            routes: [{ path: "/app/:campaignId/world-times", element: <WorldTimesPage /> }],
        })
        fireEvent.click(await screen.findByRole("button", { name: "Show earlier times" }))
        await screen.findByText(/Long ago/)
        expect(screen.queryByRole("button", { name: "Show earlier times" })).toBeNull()
    })

    it("records a calendar date with CSRF and an idempotency key, then refetches and announces", async () => {
        const server = installMockServer()
        let recorded = false
        server.on("GET", TIMES_PATH, () => ({
            body: {
                items: recorded ? [TIME("t9", "Year 3 (Founding), Bloom 5")] : [],
                next_cursor: null,
            },
        }))
        server.on("GET", CALENDARS_PATH, { body: { calendars: [CALENDAR] } })
        server.on("POST", TIMES_PATH, () => {
            recorded = true
            return { status: 201, body: { world_time_id: "t9", created: true, changed: true } }
        })
        renderAuthoringRoutes({
            initialEntry: `/app/${CAMPAIGN}/world-times`,
            bootstrap: bootstrap(true),
            routes: [{ path: "/app/:campaignId/world-times", element: <WorldTimesPage /> }],
        })
        await screen.findByRole("form", { name: "Record a world time" })
        fireEvent.change(screen.getByRole("textbox", { name: /Year/ }), { target: { value: "3" } })
        fireEvent.change(screen.getByRole("combobox", { name: "Month" }), { target: { value: "2" } })
        fireEvent.change(screen.getByRole("textbox", { name: "Day" }), { target: { value: "5" } })
        fireEvent.click(screen.getByRole("button", { name: "Record time" }))
        await screen.findByText(/Year 3 \(Founding\), Bloom 5/)
        const [call] = server.callsTo("POST", TIMES_PATH)
        expect(call!.headers["X-CSRF-Token"]).toBe(TEST_CSRF)
        expect(call!.headers["Idempotency-Key"]).toBeTruthy()
        expect(call!.body).toEqual({ calendar_id: "cal-1", year: 3, month_number: 2, day: 5 })
    })

    it("validates before sending and keeps the input", async () => {
        const server = installMockServer()
        server.on("GET", TIMES_PATH, { body: { items: [], next_cursor: null } })
        server.on("GET", CALENDARS_PATH, { body: { calendars: [CALENDAR] } })
        renderAuthoringRoutes({
            initialEntry: `/app/${CAMPAIGN}/world-times`,
            bootstrap: bootstrap(true),
            routes: [{ path: "/app/:campaignId/world-times", element: <WorldTimesPage /> }],
        })
        await screen.findByRole("form", { name: "Record a world time" })
        fireEvent.change(screen.getByRole("textbox", { name: "Day" }), { target: { value: "2" } })
        fireEvent.click(screen.getByRole("button", { name: "Record time" }))
        const summary = await screen.findByRole("alert")
        expect(summary).toHaveTextContent("Enter a whole-number year")
        expect(summary).toHaveTextContent("A day needs a month.")
        expect(server.callsTo("POST", TIMES_PATH)).toHaveLength(0)
        expect(screen.getByRole("textbox", { name: "Day" })).toHaveValue("2")
    })

    it("maps a closed gap to its own message on the narrative form", async () => {
        const server = installMockServer()
        server.on("GET", TIMES_PATH, {
            body: { items: [TIME("t1", "Year 1")], next_cursor: null },
        })
        server.on("GET", CALENDARS_PATH, { body: { calendars: [] } })
        server.on("POST", TIMES_PATH, {
            status: 409,
            body: { error: { code: "world_time_no_gap", message: "m", correlation_id: "c" } },
        })
        renderAuthoringRoutes({
            initialEntry: `/app/${CAMPAIGN}/world-times`,
            bootstrap: bootstrap(true),
            routes: [{ path: "/app/:campaignId/world-times", element: <WorldTimesPage /> }],
        })
        // No calendar: the form opens on the narrative kind.
        fireEvent.change(await screen.findByRole("textbox", { name: /Describe this moment/ }), {
            target: { value: "Dusk" },
        })
        fireEvent.change(screen.getByRole("combobox", { name: /Comes after/ }), {
            target: { value: "t1" },
        })
        fireEvent.click(screen.getByRole("button", { name: "Record time" }))
        expect(await screen.findAllByText(/no room to place a new time/)).not.toHaveLength(0)
        expect(screen.getByRole("textbox", { name: /Describe this moment/ })).toHaveValue("Dusk")
    })

    it("explains an unreadable list without a form", async () => {
        const server = installMockServer()
        server.on("GET", TIMES_PATH, { status: 500 })
        server.on("GET", CALENDARS_PATH, { body: { calendars: [] } })
        renderAuthoringRoutes({
            initialEntry: `/app/${CAMPAIGN}/world-times`,
            bootstrap: bootstrap(true),
            routes: [{ path: "/app/:campaignId/world-times", element: <WorldTimesPage /> }],
        })
        expect(await screen.findByRole("alert")).toHaveTextContent("could not be loaded")
        expect(screen.queryByRole("form")).toBeNull()
    })
})
