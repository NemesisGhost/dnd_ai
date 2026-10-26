import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import { useState } from "react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { sessionBootstrapFixture } from "../../fixtures/sessionBootstrap"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../../test/authoringHarness"
import { WorldTimePicker } from "./WorldTimePicker"

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

function Chooser() {
    const [value, setValue] = useState("")
    return (
        <>
            <WorldTimePicker campaignId={CAMPAIGN} id="when" label="When" value={value} onChange={setValue} />
            <output data-testid="chosen">{value}</output>
        </>
    )
}

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("WorldTimePicker: recording a time inline", () => {
    it("chooses the new time once the list shows it", async () => {
        const server = installMockServer()
        let recorded = false
        server.on("GET", TIMES_PATH, () => ({
            body: { items: recorded ? [TIME("t9", "Year 3, Bloom 5")] : [TIME("t1", "Year 1")], next_cursor: null },
        }))
        server.on("GET", CALENDARS_PATH, { body: { calendars: [CALENDAR] } })
        server.on("POST", TIMES_PATH, () => {
            recorded = true
            return { status: 201, body: { world_time_id: "t9", created: true, changed: true } }
        })
        renderAuthoringRoutes({
            initialEntry: "/pick",
            bootstrap: bootstrapWith(),
            routes: [{ path: "/pick", element: <Chooser /> }],
        })
        fireEvent.click(await screen.findByRole("button", { name: "Record a new time" }))
        const form = await screen.findByRole("group", { name: /Record a new world time/ })
        fireEvent.change(within(form).getByRole("textbox", { name: /Year/ }), { target: { value: "3" } })
        fireEvent.change(within(form).getByRole("combobox", { name: "Month" }), { target: { value: "2" } })
        fireEvent.change(within(form).getByRole("textbox", { name: "Day" }), { target: { value: "5" } })
        fireEvent.click(within(form).getByRole("button", { name: "Record time" }))
        await waitFor(() => expect(screen.getByTestId("chosen")).toHaveTextContent("t9"))
        expect(screen.queryByText(/could not be loaded/)).toBeNull()
    })

    it("keeps the form's page, says the time was recorded but not listed, and chooses it only once the list is read", async () => {
        const server = installMockServer()
        let recorded = false
        let readFails = false
        server.on("GET", TIMES_PATH, () =>
            readFails
                ? { status: 500, body: {} }
                : { body: { items: recorded ? [TIME("t9", "Year 3, Bloom 5")] : [TIME("t1", "Year 1")], next_cursor: null } },
        )
        server.on("GET", CALENDARS_PATH, { body: { calendars: [CALENDAR] } })
        server.on("POST", TIMES_PATH, () => {
            recorded = true
            readFails = true
            return { status: 201, body: { world_time_id: "t9", created: true, changed: true } }
        })
        renderAuthoringRoutes({
            initialEntry: "/pick",
            bootstrap: bootstrapWith(),
            routes: [{ path: "/pick", element: <Chooser /> }],
        })
        fireEvent.click(await screen.findByRole("button", { name: "Record a new time" }))
        const form = await screen.findByRole("group", { name: /Record a new world time/ })
        fireEvent.change(within(form).getByRole("textbox", { name: /Year/ }), { target: { value: "3" } })
        fireEvent.change(within(form).getByRole("combobox", { name: "Month" }), { target: { value: "2" } })
        fireEvent.change(within(form).getByRole("textbox", { name: "Day" }), { target: { value: "5" } })
        fireEvent.click(within(form).getByRole("button", { name: "Record time" }))

        expect(await screen.findByText(/World time recorded\. The latest world times could not be loaded/)).toBeInTheDocument()
        // The picker is still a picker (not an error), the time is not chosen yet, and recording again
        // is not offered while the first one is unread.
        expect(screen.getByRole("combobox", { name: "When" })).toBeInTheDocument()
        expect(screen.getByTestId("chosen")).toHaveTextContent("")
        expect(screen.queryByRole("button", { name: "Record a new time" })).toBeNull()
        expect(screen.queryByRole("button", { name: "Record time" })).toBeNull()
        expect(server.callsTo("POST", TIMES_PATH)).toHaveLength(1)

        readFails = false
        fireEvent.click(screen.getByRole("button", { name: "Load latest" }))
        await waitFor(() => expect(screen.getByTestId("chosen")).toHaveTextContent("t9"))
        expect(screen.getByRole("button", { name: "Record a new time" })).toBeInTheDocument()
        expect(screen.queryByText(/could not be loaded/)).toBeNull()
        expect(server.callsTo("POST", TIMES_PATH)).toHaveLength(1)
    })
})
