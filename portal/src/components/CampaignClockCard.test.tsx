import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { TEST_CSRF, bootstrapWith, installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import { CampaignClockCard } from "./CampaignClockCard"

const CAMPAIGN = sessionBootstrapFixture.campaigns[0]!.campaign_id
const CLOCK_PATH = `/campaigns/${CAMPAIGN}/clock`
const TIMES_PATH = new RegExp(`/campaigns/${CAMPAIGN}/world-times`)
const CALENDARS_PATH = `/campaigns/${CAMPAIGN}/calendars`

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

const STATE = {
    current: { world_time_id: "t1", display: "Year 1" },
    row_version: 1,
    inherited: false,
    last_event_id: "ev-1",
}

function bootstrap(canEdit: boolean) {
    const base = bootstrapWith()
    return {
        ...base,
        campaigns: [
            { ...base.campaigns[0]!, capabilities: canEdit ? ["canon.edit"] : ["campaign.view"] },
        ],
    }
}

function setup(clock: unknown, canEdit = true) {
    const server = installMockServer()
    server.on("GET", CLOCK_PATH, () => ({ body: clock as object }))
    server.on("GET", TIMES_PATH, {
        body: { items: [TIME("t2", "Year 2"), TIME("t1", "Year 1")], next_cursor: null },
    })
    server.on("GET", CALENDARS_PATH, { body: { calendars: [] } })
    const rendered = renderAuthoringRoutes({
        initialEntry: "/clock",
        bootstrap: bootstrap(canEdit),
        routes: [{ path: "/clock", element: <CampaignClockCard campaignId={CAMPAIGN} /> }],
    })
    return { server, ...rendered }
}

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("CampaignClockCard", () => {
    it("shows the current time to every member and offers no actions without canon.edit", async () => {
        const { server } = setup(STATE, false)
        expect(await screen.findByText("Now: Year 1")).toBeInTheDocument()
        expect(screen.queryByRole("button", { name: /Advance time|Correct time/ })).toBeNull()
        expect(server.callsTo("POST", /./)).toHaveLength(0)
        expect(server.callsTo("GET", TIMES_PATH)).toHaveLength(0)
    })

    it("says so when no time is recorded, and notes an inherited value", async () => {
        const empty = setup({ current: null, row_version: 0, inherited: false, last_event_id: null })
        expect(await screen.findByText(/No time has been recorded/)).toBeInTheDocument()
        expect(screen.queryByRole("button", { name: "Correct time" })).toBeNull()
        empty.unmount()
        setup({
            current: { world_time_id: "t1", display: "Year 4" },
            row_version: 0,
            inherited: true,
            last_event_id: null,
        })
        expect(await screen.findByText(/Year 4/)).toHaveTextContent("carried over")
        expect(screen.queryByRole("button", { name: "Correct time" })).toBeNull()
    })

    it("advances with the version, CSRF and an idempotency key, then refetches and announces", async () => {
        const server = installMockServer()
        let state = { ...STATE, current: { world_time_id: "t1", display: "Year 1" } }
        server.on("GET", CLOCK_PATH, () => ({ body: state }))
        server.on("GET", TIMES_PATH, {
            body: { items: [TIME("t2", "Year 2"), TIME("t1", "Year 1")], next_cursor: null },
        })
        server.on("GET", CALENDARS_PATH, { body: { calendars: [] } })
        server.on("POST", `${CLOCK_PATH}/advance`, () => {
            state = { ...state, current: { world_time_id: "t2", display: "Year 2" }, row_version: 2 }
            return {
                status: 200,
                body: { world_time_id: "t2", event_id: "ev-2", row_version: 2, created: false, changed: true },
            }
        })
        renderAuthoringRoutes({
            initialEntry: "/clock",
            bootstrap: bootstrap(true),
            routes: [{ path: "/clock", element: <CampaignClockCard campaignId={CAMPAIGN} /> }],
        })
        fireEvent.click(await screen.findByRole("button", { name: "Advance time" }))
        fireEvent.change(await screen.findByRole("combobox", { name: /Advance to/ }), {
            target: { value: "t2" },
        })
        fireEvent.click(screen.getByRole("button", { name: "Advance time", hidden: false }))
        await screen.findByText("Now: Year 2")
        const [call] = server.callsTo("POST", `${CLOCK_PATH}/advance`)
        expect(call!.headers["X-CSRF-Token"]).toBe(TEST_CSRF)
        expect(call!.headers["Idempotency-Key"]).toBeTruthy()
        expect(call!.body).toEqual({ world_time_id: "t2", expected_row_version: 1 })
        await waitFor(() =>
            expect(screen.getByTestId("authoring-announcer")).toHaveTextContent("Clock advanced"),
        )
    })

    it("requires a chosen time before sending", async () => {
        const { server } = setup(STATE)
        fireEvent.click(await screen.findByRole("button", { name: "Advance time" }))
        await screen.findByRole("combobox", { name: /Advance to/ })
        const submit = screen.getAllByRole("button", { name: "Advance time" }).at(-1)!
        fireEvent.click(submit)
        expect(await screen.findByText("Choose a time.")).toBeInTheDocument()
        expect(server.callsTo("POST", /./)).toHaveLength(0)
    })

    it("shows a plain message for a time that is not later and keeps the form", async () => {
        const { server } = setup(STATE)
        server.on("POST", `${CLOCK_PATH}/advance`, {
            status: 409,
            body: { error: { code: "clock_not_advanced", message: "m", correlation_id: "c" } },
        })
        fireEvent.click(await screen.findByRole("button", { name: "Advance time" }))
        fireEvent.change(await screen.findByRole("combobox", { name: /Advance to/ }), {
            target: { value: "t1" },
        })
        fireEvent.click(screen.getAllByRole("button", { name: "Advance time" }).at(-1)!)
        expect(await screen.findByRole("alert")).toHaveTextContent("must be later")
        expect(screen.getByRole("combobox", { name: /Advance to/ })).toHaveValue("t1")
    })

    it("confirms a correction and cites the event it corrects", async () => {
        const { server } = setup(STATE)
        server.on("POST", `${CLOCK_PATH}/correct`, {
            status: 200,
            body: { world_time_id: "t2", event_id: "ev-3", row_version: 2, created: false, changed: true },
        })
        fireEvent.click(await screen.findByRole("button", { name: "Correct time" }))
        fireEvent.change(await screen.findByRole("combobox", { name: /Correct to/ }), {
            target: { value: "t2" },
        })
        fireEvent.click(screen.getAllByRole("button", { name: "Correct time" }).at(-1)!)
        // Nothing is sent until the confirmation is accepted.
        expect(server.callsTo("POST", /./)).toHaveLength(0)
        const dialog = await screen.findByRole("dialog", { name: "Correct the campaign time?" })
        expect(dialog).toHaveTextContent("stays in the campaign's history")
        fireEvent.click(within(dialog).getByRole("button", { name: "Correct time" }))
        await waitFor(() => expect(server.callsTo("POST", `${CLOCK_PATH}/correct`)).toHaveLength(1))
        expect(server.callsTo("POST", `${CLOCK_PATH}/correct`)[0]!.body).toEqual({
            world_time_id: "t2",
            expected_row_version: 1,
            corrects_event_id: "ev-1",
        })
    })

    it("offers to reload when the clock moved on (stale write)", async () => {
        const { server } = setup(STATE)
        server.on("POST", `${CLOCK_PATH}/advance`, {
            status: 409,
            body: { error: { code: "stale_write", message: "m", correlation_id: "c" } },
        })
        fireEvent.click(await screen.findByRole("button", { name: "Advance time" }))
        fireEvent.change(await screen.findByRole("combobox", { name: /Advance to/ }), {
            target: { value: "t2" },
        })
        fireEvent.click(screen.getAllByRole("button", { name: "Advance time" }).at(-1)!)
        expect(await screen.findByRole("button", { name: "Load latest version" })).toBeInTheDocument()
    })
})
