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

    it("reports a confirmed advance whose clock re-read fails, holds Advance and Correct, and recovers by reading only", async () => {
        const server = installMockServer()
        let state = { ...STATE }
        let readFails = false
        server.on("GET", CLOCK_PATH, () => (readFails ? { status: 500, body: {} } : { body: state }))
        server.on("GET", TIMES_PATH, {
            body: { items: [TIME("t2", "Year 2"), TIME("t1", "Year 1")], next_cursor: null },
        })
        server.on("GET", CALENDARS_PATH, { body: { calendars: [] } })
        server.on("POST", `${CLOCK_PATH}/advance`, () => {
            state = { ...state, current: { world_time_id: "t2", display: "Year 2" }, row_version: 2 }
            readFails = true
            return { body: { world_time_id: "t2", event_id: "ev-2", row_version: 2, created: false, changed: true } }
        })
        renderAuthoringRoutes({
            initialEntry: "/clock",
            bootstrap: bootstrap(true),
            routes: [{ path: "/clock", element: <CampaignClockCard campaignId={CAMPAIGN} /> }],
        })
        fireEvent.click(await screen.findByRole("button", { name: "Advance time" }))
        fireEvent.change(await screen.findByRole("combobox", { name: /Advance to/ }), { target: { value: "t2" } })
        const form = screen.getByRole("form", { name: "Advance time" })
        fireEvent.click(within(form).getByRole("button", { name: "Advance time" }))

        expect(await screen.findByText(/Clock advanced\. The latest campaign time could not be loaded/)).toBeInTheDocument()
        const live = screen.getByTestId("authoring-announcer")
        expect(live).toHaveTextContent("Saved, but the latest data could not be loaded.")
        expect(live).not.toHaveTextContent(/^Clock advanced/)
        // The card keeps the time it last read, and offers nothing that would name its version.
        expect(screen.getByText("Now: Year 1")).toBeInTheDocument()
        expect(screen.getByRole("button", { name: "Advance time" })).toBeDisabled()
        expect(screen.getByRole("button", { name: "Correct time" })).toBeDisabled()
        expect(server.callsTo("POST", `${CLOCK_PATH}/advance`)).toHaveLength(1)

        readFails = false
        fireEvent.click(screen.getByRole("button", { name: "Try again" }))
        expect(await screen.findByText("Now: Year 2")).toBeInTheDocument()
        await waitFor(() => expect(live).toHaveTextContent("Clock advanced"))
        expect(screen.getByRole("button", { name: "Advance time" })).toBeEnabled()
        expect(screen.queryByText(/could not be loaded/)).toBeNull()
        expect(server.callsTo("POST", `${CLOCK_PATH}/advance`)).toHaveLength(1)
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

const CHOICES_PATH = new RegExp(`${CLOCK_PATH}/cause-choices`)
const BRIDGE = { event_id: "ev-bridge", name: "The bridge falls", in_world_time: "Year 1" }
const RECEIPT = { world_time_id: "t2", event_id: "ev-2", row_version: 2, created: false, changed: true }

function setupAdvance(choicesResponse: { status?: number; body: object }) {
    const server = installMockServer()
    server.on("GET", CLOCK_PATH, { body: STATE })
    server.on("GET", TIMES_PATH, {
        body: { items: [TIME("t2", "Year 2"), TIME("t1", "Year 1")], next_cursor: null },
    })
    server.on("GET", CALENDARS_PATH, { body: { calendars: [] } })
    server.on("GET", CHOICES_PATH, choicesResponse)
    renderAuthoringRoutes({
        initialEntry: "/clock",
        bootstrap: bootstrap(true),
        routes: [{ path: "/clock", element: <CampaignClockCard campaignId={CAMPAIGN} /> }],
    })
    return server
}

async function openAdvance(time = "t2") {
    fireEvent.click(await screen.findByRole("button", { name: "Advance time" }))
    fireEvent.change(await screen.findByRole("combobox", { name: /Advance to/ }), {
        target: { value: time },
    })
}

const submitAdvance = () => fireEvent.click(screen.getAllByRole("button", { name: "Advance time" }).at(-1)!)

describe("CampaignClockCard optional cause and explanation", () => {
    it("sends the chosen cause and explanation, and says who can read the explanation", async () => {
        const server = setupAdvance({ body: { choices: [BRIDGE] } })
        server.on("POST", `${CLOCK_PATH}/advance`, { status: 200, body: RECEIPT })
        await openAdvance()
        const cause = await screen.findByRole("combobox", { name: "Cause" })
        expect(within(cause).getByRole("option", { name: "The bridge falls (Year 1)" })).toBeInTheDocument()
        fireEvent.change(cause, { target: { value: "ev-bridge" } })
        const note = screen.getByRole("textbox", { name: "Explanation for members" })
        expect(note).toHaveAccessibleDescription(/campaign members who can view this event/)
        expect(note).toHaveAccessibleDescription(/Do not include GM-only notes/)
        fireEvent.change(note, { target: { value: "  The caravan reached the pass.  " } })
        submitAdvance()
        await waitFor(() => expect(server.callsTo("POST", `${CLOCK_PATH}/advance`)).toHaveLength(1))
        expect(server.callsTo("POST", `${CLOCK_PATH}/advance`)[0]!.body).toEqual({
            world_time_id: "t2",
            expected_row_version: 1,
            cause_event_id: "ev-bridge",
            explanation: "The caravan reached the pass.",
        })
        // The picker asked only for events that take effect by the chosen time.
        expect(server.callsTo("GET", CHOICES_PATH).at(-1)!.path).toContain("world_time_id=t2")
    })

    it("sends only the explanation when no cause is chosen", async () => {
        const server = setupAdvance({ body: { choices: [BRIDGE] } })
        server.on("POST", `${CLOCK_PATH}/advance`, { status: 200, body: RECEIPT })
        await openAdvance()
        fireEvent.change(await screen.findByRole("textbox", { name: "Explanation for members" }), {
            target: { value: "Only words" },
        })
        submitAdvance()
        await waitFor(() => expect(server.callsTo("POST", `${CLOCK_PATH}/advance`)).toHaveLength(1))
        expect(server.callsTo("POST", `${CLOCK_PATH}/advance`)[0]!.body).toEqual({
            world_time_id: "t2",
            expected_row_version: 1,
            explanation: "Only words",
        })
    })

    it("sends only the cause when no explanation is written", async () => {
        const server = setupAdvance({ body: { choices: [BRIDGE] } })
        server.on("POST", `${CLOCK_PATH}/advance`, { status: 200, body: RECEIPT })
        await openAdvance()
        fireEvent.change(await screen.findByRole("combobox", { name: "Cause" }), {
            target: { value: "ev-bridge" },
        })
        submitAdvance()
        await waitFor(() => expect(server.callsTo("POST", `${CLOCK_PATH}/advance`)).toHaveLength(1))
        expect(server.callsTo("POST", `${CLOCK_PATH}/advance`)[0]!.body).toEqual({
            world_time_id: "t2",
            expected_row_version: 1,
            cause_event_id: "ev-bridge",
        })
    })

    it("keeps a manual advance simple: no extra fields are sent", async () => {
        const server = setupAdvance({ body: { choices: [BRIDGE] } })
        server.on("POST", `${CLOCK_PATH}/advance`, { status: 200, body: RECEIPT })
        await openAdvance()
        await screen.findByRole("combobox", { name: "Cause" })
        submitAdvance()
        await waitFor(() => expect(server.callsTo("POST", `${CLOCK_PATH}/advance`)).toHaveLength(1))
        expect(server.callsTo("POST", `${CLOCK_PATH}/advance`)[0]!.body).toEqual({
            world_time_id: "t2",
            expected_row_version: 1,
        })
    })

    it("explains an empty list instead of showing an empty picker", async () => {
        setupAdvance({ body: { choices: [] } })
        await openAdvance()
        expect(await screen.findByText(/No recorded events could have caused an advance/)).toBeInTheDocument()
        expect(screen.queryByRole("combobox", { name: "Cause" })).toBeNull()
        expect(screen.getByRole("textbox", { name: "Explanation for members" })).toBeInTheDocument()
    })

    it("still advances manually when the optional choices cannot be read", async () => {
        const server = setupAdvance({
            status: 500,
            body: { error: { code: "internal_error", message: "m", correlation_id: "c" } },
        })
        server.on("POST", `${CLOCK_PATH}/advance`, { status: 200, body: RECEIPT })
        await openAdvance()
        expect(await screen.findByText(/could not be loaded. You can still advance the clock manually/)).toBeInTheDocument()
        submitAdvance()
        await waitFor(() => expect(server.callsTo("POST", `${CLOCK_PATH}/advance`)).toHaveLength(1))
        expect(server.callsTo("POST", `${CLOCK_PATH}/advance`)[0]!.body).toEqual({
            world_time_id: "t2",
            expected_row_version: 1,
        })
    })

    it("keeps the input and shows an accessible message when the server refuses the cause", async () => {
        const server = setupAdvance({ body: { choices: [BRIDGE] } })
        server.on("POST", `${CLOCK_PATH}/advance`, {
            status: 422,
            body: { error: { code: "clock_cause_invalid", message: "m", correlation_id: "c" } },
        })
        await openAdvance()
        fireEvent.change(await screen.findByRole("combobox", { name: "Cause" }), {
            target: { value: "ev-bridge" },
        })
        fireEvent.change(screen.getByRole("textbox", { name: "Explanation for members" }), {
            target: { value: "Kept words" },
        })
        submitAdvance()
        expect(await screen.findByRole("alert")).toHaveTextContent("can no longer be recorded as the cause")
        expect(screen.getByRole("textbox", { name: "Explanation for members" })).toHaveValue("Kept words")
        expect(screen.getByRole("combobox", { name: "Cause" })).toHaveValue("ev-bridge")
        expect(screen.getByRole("combobox", { name: /Advance to/ })).toHaveValue("t2")
    })

    it("retries a failed write with the same body and idempotency key", async () => {
        const server = setupAdvance({ body: { choices: [BRIDGE] } })
        server.on("POST", `${CLOCK_PATH}/advance`, {
            status: 500,
            body: { error: { code: "internal_error", message: "m", correlation_id: "c" } },
        })
        await openAdvance()
        fireEvent.change(await screen.findByRole("combobox", { name: "Cause" }), {
            target: { value: "ev-bridge" },
        })
        fireEvent.change(screen.getByRole("textbox", { name: "Explanation for members" }), {
            target: { value: "Same words" },
        })
        submitAdvance()
        // Editing after the failure must not change what a retry sends.
        const retry = await screen.findByRole("button", { name: "Retry" })
        fireEvent.change(screen.getByRole("textbox", { name: "Explanation for members" }), {
            target: { value: "Edited later" },
        })
        fireEvent.click(retry)
        await waitFor(() => expect(server.callsTo("POST", `${CLOCK_PATH}/advance`)).toHaveLength(2))
        const [first, second] = server.callsTo("POST", `${CLOCK_PATH}/advance`)
        expect(second!.body).toEqual(first!.body)
        expect(second!.headers["Idempotency-Key"]).toBe(first!.headers["Idempotency-Key"])
        expect(first!.body).toMatchObject({ explanation: "Same words", cause_event_id: "ev-bridge" })
    })

    it("does not send a cause that the newly chosen time no longer offers", async () => {
        const server = installMockServer()
        server.on("GET", CLOCK_PATH, { body: STATE })
        server.on("GET", TIMES_PATH, {
            body: { items: [TIME("t2", "Year 2"), TIME("t1", "Year 1")], next_cursor: null },
        })
        server.on("GET", CALENDARS_PATH, { body: { calendars: [] } })
        server.on("GET", CHOICES_PATH, (call) => ({
            body: { choices: call.path.includes("world_time_id=t2") ? [BRIDGE] : [] },
        }))
        server.on("POST", `${CLOCK_PATH}/advance`, { status: 200, body: RECEIPT })
        renderAuthoringRoutes({
            initialEntry: "/clock",
            bootstrap: bootstrap(true),
            routes: [{ path: "/clock", element: <CampaignClockCard campaignId={CAMPAIGN} /> }],
        })
        await openAdvance("t2")
        fireEvent.change(await screen.findByRole("combobox", { name: "Cause" }), {
            target: { value: "ev-bridge" },
        })
        fireEvent.change(screen.getByRole("combobox", { name: /Advance to/ }), { target: { value: "t1" } })
        await screen.findByText(/No recorded events could have caused an advance/)
        submitAdvance()
        await waitFor(() => expect(server.callsTo("POST", `${CLOCK_PATH}/advance`)).toHaveLength(1))
        expect(server.callsTo("POST", `${CLOCK_PATH}/advance`)[0]!.body).toEqual({
            world_time_id: "t1",
            expected_row_version: 1,
        })
    })

    it("offers no optional fields to a member without canon.edit, nor to a correction", async () => {
        const server = installMockServer()
        server.on("GET", CLOCK_PATH, { body: STATE })
        renderAuthoringRoutes({
            initialEntry: "/clock",
            bootstrap: bootstrap(false),
            routes: [{ path: "/clock", element: <CampaignClockCard campaignId={CAMPAIGN} /> }],
        })
        await screen.findByText("Now: Year 1")
        expect(server.callsTo("GET", CHOICES_PATH)).toHaveLength(0)
        expect(screen.queryByRole("textbox", { name: "Explanation for members" })).toBeNull()
    })
})
