import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import { WorldTimesPage } from "./WorldTimesPage"

// C09-S01-1: the World times page keeps its own visible text for a point whose calendar is not in the
// loaded list: the literal "Calendar:" reading it had before the shared formatter (no epoch, no month
// name, clock time and label kept). The picker, form and receipt use the display-text fallback instead.

const CAMPAIGN = sessionBootstrapFixture.campaigns[0]!.campaign_id
const TIMES = /\/campaigns\/[^/]+\/world-times/
const CALENDARS = /\/campaigns\/[^/]+\/calendars/
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
const ORPHAN = {
    world_time_id: "t9",
    calendar_id: "cal-gone",
    year: 3,
    month_number: 2,
    day: 5,
    hour: 14,
    minute: 30,
    label: "The feast",
    precision: "exact",
    sort_key: 9,
    display: "Year 3 (Founding), Bloom 5",
}
const KNOWN = { ...ORPHAN, world_time_id: "t1", calendar_id: "cal-1", label: null, sort_key: 1 }

afterEach(() => {
    vi.unstubAllGlobals()
})

function setup(items: unknown[]) {
    const server = installMockServer()
    server.on("GET", TIMES, { body: { items, next_cursor: null } })
    server.on("GET", CALENDARS, { body: { calendars: [CALENDAR] } })
    server.on("POST", TIMES, { status: 201, body: { world_time_id: "t9", created: true, changed: true } })
    renderAuthoringRoutes({
        initialEntry: `/app/${CAMPAIGN}/world-times`,
        bootstrap: {
            ...bootstrapWith(),
            campaigns: [{ ...bootstrapWith().campaigns[0]!, capabilities: ["canon.edit"] }],
        },
        routes: [{ path: "/app/:campaignId/world-times", element: <WorldTimesPage /> }],
    })
    return server
}

describe("WorldTimesPage: a point whose calendar is not loaded", () => {
    it("lists it as the page always did, while ordinary points read in full", async () => {
        setup([ORPHAN, KNOWN])
        const list = await screen.findByRole("list")
        const entries = within(list).getAllByRole("listitem").map((item) => item.textContent ?? "")
        expect(entries[0]).toMatch(/^Calendar: Year 3, 14:30 — The feast/)
        expect(entries[0]).not.toMatch(/Founding|Bloom/)
        expect(entries[1]).toMatch(/^Common Reckoning: Year 3 \(Founding\), Bloom 5, 14:30/)
    })

    it("confirms it with the same reading after recording", async () => {
        setup([ORPHAN])
        fireEvent.click(await screen.findByRole("button", { name: "Record a time" }))
        const dialog = await screen.findByRole("dialog", { name: "Record a world time" })
        fireEvent.change(within(dialog).getByRole("combobox", { name: /^Calendar/ }), { target: { value: "cal-1" } })
        fireEvent.change(within(dialog).getByRole("textbox", { name: /Year/ }), { target: { value: "3" } })
        fireEvent.click(within(dialog).getByRole("button", { name: "Record time" }))
        await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
        expect(await screen.findByText(/World time recorded: Calendar: Year 3, 14:30 — The feast/)).toBeInTheDocument()
    })
})
