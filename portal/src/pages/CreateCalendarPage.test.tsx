import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { TEST_CSRF, installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import type { FetchCall, MockResponse } from "../test/authoringHarness"
import { CreateCalendarPage } from "./CreateCalendarPage"

// The page re-renders every panel on each keystroke and these tests type a lot; give them room when the
// whole suite runs in parallel.
vi.setConfig({ testTimeout: 20_000 })

const WORLD_PATH = "/worlds/w1"
const CREATE_PATH = "/worlds/w1/calendars"

const WORLD = (actions: string[], id = "w1") => ({
    world_id: id,
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

const RECEIPT = { status: 201, body: { calendar_id: "cal-1", created: true, changed: true } }

function setup(actions: string[] = ["update", "create_calendar"], entry = "/worlds/w1/calendars/new") {
    const server = installMockServer()
    server.on("GET", WORLD_PATH, { body: WORLD(actions) })
    server.on("GET", "/worlds/w2", { body: WORLD(actions, "w2") })
    const rendered = renderAuthoringRoutes({
        initialEntry: entry,
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

// ---- helpers: the page is driven the way a person would ----

async function ready() {
    await screen.findByRole("navigation", { name: "New calendar workflow" })
}
// Router navigation resolves asynchronously, so a step is reached once its heading shows.
async function go(label: string, heading: string) {
    fireEvent.click(screen.getByRole("link", { name: label }))
    await screen.findByRole("heading", { level: 2, name: heading }, { timeout: 5000 })
}
const toBasics = () => go("1. Basics", "Basics")
const toMonths = () => go("2. Months", "Months")
const toReview = () => go("3. Review & create", "Review & create")
const type = (name: RegExp | string, value: string) =>
    fireEvent.change(screen.getByRole("textbox", { name }), { target: { value } })
const press = (name: RegExp | string) => fireEvent.click(screen.getByRole("button", { name }))
const monthsPanel = () => screen.getByRole("region", { name: "Months" })
const rows = () => screen.getAllByRole("listitem").filter((li) => li.querySelector(".calendar-roster__row"))
const rowTexts = () => rows().map((li) => li.querySelector(".calendar-roster__row")!.textContent)

// Names month 1 through its open editor and applies it.
function nameFirstMonth(name = "Frost", days = "30") {
    type(/^Month 1 name/, name)
    type(/^Month 1 days/, days)
    press("Apply to draft")
}
// Adds a month through the composer, opening it first when it is closed.
function addMonth(name: string, days = "30") {
    if (screen.queryByRole("form", { name: "Add a month" }) === null) press("Add a month")
    type(/^New month name/, name)
    type(/^New month days/, days)
    press("Add to draft")
}
// A complete, valid draft ready to create from the Review step.
async function completeDraft() {
    type(/^Calendar name/, " Common Reckoning ")
    await toMonths()
    nameFirstMonth(" Frost ")
    addMonth("Thaw", "31")
    press("Done")
}

const createCalls = (server: ReturnType<typeof installMockServer>) => server.callsTo("POST", CREATE_PATH)

describe("access and arrival", () => {
    it("takes focus on the heading and sends no write on open", async () => {
        const { server } = setup()
        const heading = await screen.findByRole("heading", { level: 1, name: "New calendar" })
        await waitFor(() => expect(heading).toHaveFocus())
        expect(server.callsTo("POST", /./)).toEqual([])
    })

    it("says so, without a form or steps, when the world offers no calendar creation", async () => {
        setup(["update"], "/worlds/w1/calendars/new?section=review")
        expect(await screen.findByRole("alert")).toHaveTextContent("cannot create a calendar")
        expect(screen.queryByRole("form")).toBeNull()
        expect(screen.queryByRole("navigation", { name: "New calendar workflow" })).toBeNull()
        expect(screen.queryByRole("button", { name: "Create calendar" })).toBeNull()
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

    it("keeps the World breadcrumb", async () => {
        setup()
        await ready()
        expect(screen.getByRole("link", { name: "World" })).toHaveAttribute("href", "/worlds/w1")
    })
})

describe("steps", () => {
    it("opens on Basics, marks it as the current step and writes nothing", async () => {
        const { server, router } = setup()
        await ready()
        expect(screen.getByRole("link", { name: "1. Basics" })).toHaveAttribute("aria-current", "step")
        expect(screen.getByRole("heading", { level: 2, name: "Basics" })).toBeVisible()
        expect(screen.queryByRole("heading", { level: 2, name: "Months" })).toBeNull()
        await waitFor(() => expect(router.state.location.search).toBe("?section=basics"))
        expect(server.callsTo("POST", /./)).toEqual([])
    })

    it("moves between steps by link, pushing history, with no request", async () => {
        const { server, router } = setup()
        await ready()
        await waitFor(() => expect(router.state.location.search).toBe("?section=basics"))
        await toMonths()
        expect(router.state.location.search).toBe("?section=months")
        expect(screen.getByRole("heading", { level: 2, name: "Months" })).toBeVisible()
        expect(screen.getByRole("link", { name: "2. Months" })).toHaveAttribute("aria-current", "step")
        await toReview()
        expect(screen.getByRole("heading", { level: 2, name: "Review & create" })).toBeVisible()
        await router.navigate(-1)
        await waitFor(() => expect(screen.getByRole("heading", { level: 2, name: "Months" })).toBeVisible())
        expect(server.callsTo("POST", /./)).toEqual([])
        // Moving the focus to the new step's heading.
        await toBasics()
        await waitFor(() => expect(screen.getByRole("heading", { level: 2, name: "Basics" })).toHaveFocus())
    })

    it("replaces an unknown step and honours a direct link to one", async () => {
        const { router } = setup(["create_calendar"], "/worlds/w1/calendars/new?section=nope")
        await ready()
        await waitFor(() => expect(router.state.location.search).toBe("?section=basics"))
    })

    it("keeps every entered value, and the unfinished forms, through every step", async () => {
        setup()
        await ready()
        type(/^Calendar name/, "Common")
        type(/^Description/, "A note")
        type(/^Epoch/, "Founding")
        type(/^Days per week/, "7")
        await toMonths()
        nameFirstMonth("Frost")
        press("Add a month")
        type(/^New month name/, "Thaw")
        type(/^New month days/, "31")
        await toReview()
        await toBasics()
        expect(screen.getByRole("textbox", { name: /^Calendar name/ })).toHaveValue("Common")
        expect(screen.getByRole("textbox", { name: /^Description/ })).toHaveValue("A note")
        expect(screen.getByRole("textbox", { name: /^Epoch/ })).toHaveValue("Founding")
        expect(screen.getByRole("textbox", { name: /^Days per week/ })).toHaveValue("7")
        await toMonths()
        expect(screen.getByRole("textbox", { name: /^New month name/ })).toHaveValue("Thaw")
        expect(screen.getByRole("textbox", { name: /^New month days/ })).toHaveValue("31")
        // A half-made edit survives as well.
        press("Add to draft")
        press("Done")
        press("Edit month 2, Thaw")
        type(/^Month 2 name/, "Melt")
        await toReview()
        await toMonths()
        expect(screen.getByRole("textbox", { name: /^Month 2 name/ })).toHaveValue("Melt")
    })
})

describe("the month roster", () => {
    it("starts with one blank 30-day month, open for entry, with no Remove and no example data", async () => {
        setup()
        await ready()
        await toMonths()
        expect(rowTexts()).toEqual(["1Name needed30Edit"])
        expect(screen.getByRole("textbox", { name: /^Month 1 name/ })).toHaveValue("")
        expect(screen.getByRole("textbox", { name: /^Month 1 days/ })).toHaveValue("30")
        expect(screen.queryByRole("button", { name: /^Remove/ })).toBeNull()
        expect(within(monthsPanel()).getByText("1 month")).toBeInTheDocument()
        expect(within(monthsPanel()).getByText(/Year length: 30 days\./)).toBeInTheDocument()
    })

    it("says that its actions change the draft only", async () => {
        setup()
        await ready()
        await toMonths()
        expect(screen.getByText(/Add, Edit and Remove change this unsaved draft only/)).toBeInTheDocument()
        expect(screen.getByRole("button", { name: "Apply to draft" })).toBeInTheDocument()
    })

    it("adds a month through a form above the roster, which stays open for the next one", async () => {
        const { server } = setup()
        await ready()
        await toMonths()
        nameFirstMonth("Frost")
        press("Add a month")
        const composer = screen.getByRole("form", { name: "Add a month" })
        const list = document.querySelector(".calendar-roster__list")!
        expect(composer.compareDocumentPosition(list) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
        type(/^New month name/, "Thaw")
        type(/^New month days/, "31")
        press("Add to draft")
        expect(rowTexts()).toEqual(["1Frost30EditRemove", "2Thaw31EditRemove"])
        expect(screen.getByRole("textbox", { name: /^New month name/ })).toHaveValue("")
        expect(screen.getByRole("textbox", { name: /^New month days/ })).toHaveValue("30")
        expect(within(monthsPanel()).getByText("2 months")).toBeInTheDocument()
        expect(within(monthsPanel()).getByText(/Year length: 61 days\./)).toBeInTheDocument()
        expect(server.callsTo("POST", /./)).toEqual([])
    })

    it("expands only the selected row for editing and applies it to the draft", async () => {
        setup()
        await ready()
        await toMonths()
        nameFirstMonth("Frost")
        addMonth("Thaw", "31")
        addMonth("Bloom", "28")
        press("Done")
        press("Edit month 2, Thaw")
        expect(screen.getAllByRole("form", { name: /^Edit month/ })).toHaveLength(1)
        expect(screen.getByRole("form", { name: "Edit month 2" })).toBeInTheDocument()
        type(/^Month 2 name/, "Melt")
        type(/^Month 2 days/, "29")
        // Not in the roster or the total until applied.
        expect(rowTexts()[1]).toContain("Thaw")
        expect(within(monthsPanel()).getByText(/Year length: 89 days\. Changes you have not applied are not counted/)).toBeInTheDocument()
        press("Apply to draft")
        expect(rowTexts()).toEqual(["1Frost30EditRemove", "2Melt29EditRemove", "3Bloom28EditRemove"])
        expect(within(monthsPanel()).getByText(/Year length: 87 days\./)).toBeInTheDocument()
        expect(screen.queryByRole("form", { name: /^Edit month/ })).toBeNull()
    })

    it("cancelling an edit leaves the row as it was", async () => {
        setup()
        await ready()
        await toMonths()
        nameFirstMonth("Frost")
        addMonth("Thaw")
        press("Done")
        press("Edit month 2, Thaw")
        type(/^Month 2 name/, "Other")
        press("Cancel edit")
        expect(rowTexts()[1]).toContain("Thaw")
    })

    it("rejects a repeated name in any case and a day count outside 1–400 or not whole", async () => {
        setup()
        await ready()
        await toMonths()
        nameFirstMonth("Frost")
        press("Add a month")
        for (const [name, days, message] of [
            [" FROST ", "30", /Another month already has this name/],
            ["Thaw", "0", /Days must be a whole number from 1 to 400/],
            ["Thaw", "401", /Days must be a whole number from 1 to 400/],
            ["Thaw", "2.5", /Days must be a whole number from 1 to 400/],
            ["", "30", /Enter a name for the month/],
        ] as const) {
            type(/^New month name/, name)
            type(/^New month days/, days)
            press("Add to draft")
            expect(screen.getByText(message)).toBeInTheDocument()
            expect(rows()).toHaveLength(1)
        }
        // The bounds themselves are accepted.
        addMonth("Short", "1")
        addMonth("Long", "400")
        expect(rows()).toHaveLength(3)
    })

    it("lets an edited row keep its own name", async () => {
        setup()
        await ready()
        await toMonths()
        nameFirstMonth("Frost")
        press("Edit month 1, Frost")
        type(/^Month 1 days/, "20")
        press("Apply to draft")
        expect(rowTexts()).toEqual(["1Frost20Edit"])
    })

    it("keeps each remaining row's values on its own row after a removal, and renumbers", async () => {
        setup()
        await ready()
        await toMonths()
        nameFirstMonth("Frost", "10")
        addMonth("Thaw", "20")
        addMonth("Bloom", "30")
        press("Done")
        press("Remove month 2, Thaw from the draft")
        expect(rowTexts()).toEqual(["1Frost10EditRemove", "2Bloom30EditRemove"])
        // The surviving row's own editor and its own error stay together.
        press("Edit month 2, Bloom")
        type(/^Month 2 days/, "0")
        press("Apply to draft")
        expect(within(screen.getByRole("form", { name: "Edit month 2" })).getByText(/Days must be a whole number/)).toBeInTheDocument()
        expect(screen.getByRole("textbox", { name: /^Month 2 name/ })).toHaveValue("Bloom")
        // Removing down to one month removes the last Remove.
        press("Cancel edit")
        press("Remove month 1, Frost from the draft")
        expect(rowTexts()).toEqual(["1Bloom30Edit"])
        expect(screen.queryByRole("button", { name: /^Remove/ })).toBeNull()
    })

    it("allows at most 60 months", async () => {
        setup()
        await ready()
        await toMonths()
        nameFirstMonth("Month 1")
        for (let i = 2; i <= 60; i += 1) addMonth(`Month ${i}`)
        expect(rows()).toHaveLength(60)
        expect(within(monthsPanel()).getByText("60 months")).toBeInTheDocument()
        expect(screen.queryByRole("button", { name: "Add a month" })).toBeNull()
        expect(screen.queryByRole("form", { name: "Add a month" })).toBeNull()
        expect(screen.getByText(/up to 60 months/)).toBeInTheDocument()
        expect(within(monthsPanel()).getByText(/Year length: 1800 days\./)).toBeInTheDocument()
        press("Remove month 60, Month 60 from the draft")
        expect(screen.getByRole("button", { name: "Add a month" })).toBeInTheDocument()
    }, 30_000)

    it("announces additions and removals, and focuses the first invalid field of a refused month", async () => {
        setup()
        await ready()
        await toMonths()
        nameFirstMonth("Frost")
        addMonth("Thaw")
        const announcer = screen.getByTestId("authoring-announcer")
        expect(announcer).toHaveTextContent("Month 2, Thaw, added to the draft.")
        type(/^New month name/, "Bloom")
        type(/^New month days/, "0")
        press("Add to draft")
        await waitFor(() => expect(screen.getByRole("textbox", { name: /^New month days/ })).toHaveFocus())
        // Closing a form that holds unadded values says that it discards them.
        press("Discard and close")
        press("Remove month 2, Thaw from the draft")
        expect(announcer).toHaveTextContent("Month 2, Thaw, removed from the draft.")
        // Focus goes to a row that still exists: here month 1's Edit button.
        await waitFor(() => expect(screen.getByRole("button", { name: "Edit month 1, Frost" })).toHaveFocus())
    })

    it("will not open a second form over unapplied values, and says why", async () => {
        setup()
        await ready()
        await toMonths()
        nameFirstMonth("Frost")
        addMonth("Thaw")
        press("Done")
        press("Edit month 2, Thaw")
        type(/^Month 2 name/, "Melt")
        press("Edit month 1, Frost")
        expect(screen.getByRole("status")).toHaveTextContent("Apply or cancel your changes to month 2 first")
        expect(screen.getByRole("textbox", { name: /^Month 2 name/ })).toHaveValue("Melt")
        await waitFor(() => expect(screen.getByRole("textbox", { name: /^Month 2 name/ })).toHaveFocus())
    })
})

describe("creating", () => {
    it("never creates from Basics or Months: those fields are not inside the creating form", async () => {
        const { server } = setup()
        await ready()
        const nameInput = screen.getByRole("textbox", { name: /^Calendar name/ })
        expect(nameInput.closest("form")).toBeNull()
        await toMonths()
        const composerOpener = screen.getByRole("button", { name: "Add a month" })
        fireEvent.click(composerOpener)
        // Submitting a month form (what Enter does there) adds to the draft and sends nothing.
        type(/^New month name/, "Thaw")
        fireEvent.submit(screen.getByRole("form", { name: "Add a month" }))
        expect(rows()).toHaveLength(2)
        fireEvent.submit(screen.getByRole("form", { name: "Add a month" }))
        expect(server.callsTo("POST", /./)).toEqual([])
        // The only submit button for the calendar is in the Review form, with nothing to type in.
        await toReview()
        const form = screen.getByRole("form", { name: "Create calendar" })
        expect(within(form).queryAllByRole("textbox")).toEqual([])
        expect(within(form).getByRole("button", { name: "Create calendar" })).toHaveAttribute("type", "submit")
    })

    it("shows the details, the ordered months, the year length and the permanence notice on Review", async () => {
        setup()
        await ready()
        await completeDraft()
        await toReview()
        const facts = document.querySelector(".calendar-review__facts")!
        expect(facts).toHaveTextContent("NameCommon Reckoning")
        expect(facts).toHaveTextContent("DescriptionNone")
        expect(facts).toHaveTextContent("EpochNot set")
        expect(facts).toHaveTextContent("Days per weekNot set")
        const months = within(document.querySelector(".calendar-review__months") as HTMLElement).getAllByRole("listitem")
        expect(months.map((m) => m.textContent)).toEqual(["Frost — 30 days", "Thaw — 31 days"])
        const review = screen.getByRole("region", { name: "Review & create" })
        expect(within(review).getByText(/Year length: 61 days\./)).toBeInTheDocument()
        expect(screen.getByText(/cannot be changed after it is created/)).toBeInTheDocument()
        expect(screen.getByRole("link", { name: "Change basics" })).toHaveAttribute("href", expect.stringContaining("section=basics"))
        expect(screen.getByRole("link", { name: "Change months" })).toHaveAttribute("href", expect.stringContaining("section=months"))
        expect(screen.queryByText("Before you can create this calendar")).toBeNull()
    })

    it("sends exactly one request with CSRF, an idempotency key and the ordered, trimmed payload, then redirects", async () => {
        const { server, router } = setup()
        server.on("POST", CREATE_PATH, RECEIPT)
        await ready()
        await completeDraft()
        await toBasics()
        type(/^Description/, "  ")
        await toReview()
        press("Create calendar")
        await screen.findByText("World overview page")
        const calls = createCalls(server)
        expect(calls).toHaveLength(1)
        expect(calls[0]!.headers["X-CSRF-Token"]).toBe(TEST_CSRF)
        expect(calls[0]!.headers["Idempotency-Key"]).toBeTruthy()
        expect(calls[0]!.body).toEqual({
            name: "Common Reckoning",
            description: null,
            days_per_week: null,
            epoch_label: null,
            months: [
                { name: "Frost", day_count: 30 },
                { name: "Thaw", day_count: 31 },
            ],
        })
        expect(router.state.historyAction).toBe("REPLACE")
        expect(router.state.location.state).toEqual({ announce: "Calendar created" })
        expect(server.callsTo("POST", /./)).toHaveLength(1)
    })

    it("sends the optional fields when given", async () => {
        const { server } = setup()
        server.on("POST", CREATE_PATH, RECEIPT)
        await ready()
        await completeDraft()
        await toBasics()
        type(/^Description/, " About ")
        type(/^Epoch/, " Founding ")
        type(/^Days per week/, "7")
        await toReview()
        press("Create calendar")
        await screen.findByText("World overview page")
        expect(createCalls(server)[0]!.body).toMatchObject({
            description: "About",
            epoch_label: "Founding",
            days_per_week: 7,
        })
    })

    it("validates the whole draft from Review, focuses the summary and keeps the input", async () => {
        const { server } = setup()
        await ready()
        await toReview()
        press("Create calendar")
        const heading = await screen.findByRole("heading", { name: "There is a problem" })
        const summary = heading.closest("div")!
        await waitFor(() => expect(summary).toHaveFocus())
        expect(within(summary).getByRole("link", { name: "Enter a name for the calendar." })).toBeInTheDocument()
        expect(within(summary).getByRole("link", { name: "Enter a name for month 1." })).toBeInTheDocument()
        expect(createCalls(server)).toHaveLength(0)
    })

    it("reports a problem in a step that is not showing, and its link shows the step and focuses the field", async () => {
        setup()
        await ready()
        type(/^Days per week/, "31")
        await toReview()
        press("Create calendar")
        const summary = (await screen.findByRole("heading", { name: "There is a problem" })).closest("div")!
        fireEvent.click(within(summary).getByRole("link", { name: /Days per week must be a whole number/ }))
        await waitFor(() => expect(screen.getByRole("textbox", { name: /^Days per week/ })).toHaveFocus())
        expect(screen.getByRole("heading", { level: 2, name: "Basics" })).toBeVisible()
        expect(screen.getByText(/Days per week must be a whole number from 1 to 30, or empty\./, { selector: "p" })).toBeInTheDocument()
    })

    it("opens the collapsed row a month problem belongs to before focusing its field", async () => {
        setup()
        await ready()
        type(/^Calendar name/, "Common")
        await toMonths()
        // Opening Add closes the untouched editor, leaving the unnamed month collapsed.
        press("Add a month")
        press("Done")
        expect(screen.queryByRole("textbox", { name: /^Month 1 name/ })).toBeNull()
        await toReview()
        press("Create calendar")
        const summary = (await screen.findByRole("heading", { name: "There is a problem" })).closest("div")!
        fireEvent.click(within(summary).getByRole("link", { name: "Enter a name for month 1." }))
        await waitFor(() => expect(screen.getByRole("textbox", { name: /^Month 1 name/ })).toHaveFocus())
        expect(screen.getByRole("heading", { level: 2, name: "Months" })).toBeVisible()
    })

    it("refuses to create over an unfinished month form, names it, and creates once it is applied", async () => {
        const { server } = setup()
        server.on("POST", CREATE_PATH, RECEIPT)
        await ready()
        await completeDraft()
        await toMonths()
        press("Add a month")
        type(/^New month name/, "Bloom")
        await toReview()
        press("Create calendar")
        const summary = (await screen.findByRole("heading", { name: "There is a problem" })).closest("div")!
        expect(createCalls(server)).toHaveLength(0)
        fireEvent.click(within(summary).getByRole("link", { name: /not in the draft yet/ }))
        await waitFor(() => expect(screen.getByRole("textbox", { name: /^New month name/ })).toHaveFocus())
        expect(screen.getByRole("textbox", { name: /^New month name/ })).toHaveValue("Bloom")
        press("Add to draft")
        await toReview()
        press("Create calendar")
        await screen.findByText("World overview page")
        expect((createCalls(server)[0]!.body as { months: unknown[] }).months).toHaveLength(3)
    })

    it("does not send a half-made edit: a changed row editor blocks creation", async () => {
        const { server } = setup()
        await ready()
        await completeDraft()
        await toMonths()
        press("Edit month 2, Thaw")
        type(/^Month 2 name/, "Melt")
        await toReview()
        press("Create calendar")
        const summary = (await screen.findByRole("heading", { name: "There is a problem" })).closest("div")!
        expect(within(summary).getByRole("link", { name: /Month 2 has changes that are not applied/ })).toBeInTheDocument()
        expect(createCalls(server)).toHaveLength(0)
    })

    it("lets fixed problems disappear without moving focus for new ones", async () => {
        setup()
        await ready()
        await toReview()
        press("Create calendar")
        const summary = (await screen.findByRole("heading", { name: "There is a problem" })).closest("div")!
        await waitFor(() => expect(summary).toHaveFocus())
        await toBasics()
        type(/^Calendar name/, "Common")
        expect(within(summary).queryByRole("link", { name: "Enter a name for the calendar." })).toBeNull()
        expect(within(summary).getByRole("link", { name: "Enter a name for month 1." })).toBeInTheDocument()
        // A problem not reported by the last Create does not appear on its own.
        type(/^Days per week/, "99")
        expect(within(summary).queryByRole("link", { name: /Days per week/ })).toBeNull()
        expect(screen.getByRole("textbox", { name: /^Days per week/ })).not.toHaveAttribute("aria-invalid")
    })
})

describe("failure and retry", () => {
    function failThenSucceed(server: ReturnType<typeof installMockServer>): { seen: FetchCall[] } {
        const seen: FetchCall[] = []
        server.on("POST", CREATE_PATH, (call): MockResponse => {
            seen.push(call)
            return seen.length === 1 ? { networkError: true } : RECEIPT
        })
        return { seen }
    }

    it("keeps the whole draft and the step on a failure, and Retry replays the same request", async () => {
        const { server } = setup()
        const { seen } = failThenSucceed(server)
        await ready()
        await completeDraft()
        await toReview()
        press("Create calendar")
        expect(await screen.findByText(/could not reach the server/)).toBeInTheDocument()
        expect(screen.getByRole("heading", { level: 2, name: "Review & create" })).toBeVisible()
        await toMonths()
        expect(rowTexts()).toEqual(["1Frost30EditRemove", "2Thaw31EditRemove"])
        await toReview()
        press("Retry")
        await screen.findByText("World overview page")
        expect(seen).toHaveLength(2)
        expect(seen[1]!.headers["Idempotency-Key"]).toBe(seen[0]!.headers["Idempotency-Key"])
        expect(seen[1]!.body).toEqual(seen[0]!.body)
    })

    it("withdraws Retry when the draft is changed, so a new attempt sends what is on screen", async () => {
        const { server } = setup()
        const { seen } = failThenSucceed(server)
        await ready()
        await completeDraft()
        await toReview()
        press("Create calendar")
        await screen.findByText(/could not reach the server/)
        await toBasics()
        type(/^Calendar name/, "Renamed")
        await toReview()
        expect(screen.queryByRole("button", { name: "Retry" })).toBeNull()
        press("Create calendar")
        await screen.findByText("World overview page")
        expect(seen).toHaveLength(2)
        expect((seen[1]!.body as { name: string }).name).toBe("Renamed")
        expect(seen[1]!.headers["Idempotency-Key"]).not.toBe(seen[0]!.headers["Idempotency-Key"])
    })

    it("opening a month form after a failure does not discard Retry", async () => {
        const { server } = setup()
        failThenSucceed(server)
        await ready()
        await completeDraft()
        await toReview()
        press("Create calendar")
        await screen.findByText(/could not reach the server/)
        await toMonths()
        press("Add a month")
        type(/^New month name/, "Unsent")
        await toReview()
        expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument()
    })

    it("disables the draft while the request is pending", async () => {
        const { server } = setup()
        let release: (r: MockResponse) => void = () => {}
        server.on("POST", CREATE_PATH, () => new Promise<MockResponse>((resolve) => (release = resolve)))
        await ready()
        await completeDraft()
        await toReview()
        press("Create calendar")
        expect(await screen.findByRole("button", { name: "Creating…" })).toBeDisabled()
        expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled()
        await toBasics()
        expect(screen.getByRole("textbox", { name: /^Calendar name/ })).toBeDisabled()
        await toMonths()
        expect(screen.getByRole("button", { name: "Add a month" })).toBeDisabled()
        // A second submit while pending is ignored.
        await toReview()
        release(RECEIPT)
        await screen.findByText("World overview page")
        expect(createCalls(server)).toHaveLength(1)
    })
})

describe("leaving", () => {
    it("moves between steps freely, but asks before a draft with changes is abandoned", async () => {
        const { router } = setup()
        await ready()
        type(/^Calendar name/, "Common")
        await toMonths()
        await toReview()
        expect(screen.queryByRole("dialog")).toBeNull()
        fireEvent.click(screen.getByRole("button", { name: "Cancel" }))
        await waitFor(() => expect(screen.getByRole("heading", { name: "Discard unsaved changes?" })).toBeInTheDocument())
        expect(router.state.location.pathname).toBe("/worlds/w1/calendars/new")
        fireEvent.click(screen.getByRole("button", { name: "Keep editing" }))
        await toBasics()
        expect(screen.getByRole("textbox", { name: /^Calendar name/ })).toHaveValue("Common")
        press("Cancel")
        fireEvent.click(await screen.findByRole("button", { name: "Discard changes" }))
        await screen.findByText("World overview page")
    })

    it("leaves a draft with no changes without asking", async () => {
        setup()
        await ready()
        press("Cancel")
        await screen.findByText("World overview page")
    })
})

describe("owning world", () => {
    it("sends the request to the world in the route", async () => {
        const { server } = setup(["create_calendar"], "/worlds/w2/calendars/new")
        server.on("POST", "/worlds/w2/calendars", RECEIPT)
        await ready()
        await completeDraft()
        await toReview()
        press("Create calendar")
        await screen.findByText("World overview page")
        expect(server.callsTo("POST", "/worlds/w2/calendars")).toHaveLength(1)
        expect(createCalls(server)).toHaveLength(0)
    })

    it("starts a fresh draft for another world rather than carrying one over", async () => {
        const { router } = setup()
        await ready()
        type(/^Calendar name/, "Common")
        await router.navigate("/worlds/w2/calendars/new")
        fireEvent.click(await screen.findByRole("button", { name: "Discard changes" }))
        await waitFor(() => expect(router.state.location.pathname).toBe("/worlds/w2/calendars/new"))
        await waitFor(() => expect(screen.getByRole("textbox", { name: /^Calendar name/ })).toHaveValue(""))
        expect(screen.getByRole("link", { name: "World" })).toHaveAttribute("href", "/worlds/w2")
    })
})
