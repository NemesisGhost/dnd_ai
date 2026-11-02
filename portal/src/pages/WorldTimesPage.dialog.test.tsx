import { act, fireEvent, screen, waitFor, within } from "@testing-library/react"
import { Link } from "react-router"
import { afterEach, describe, expect, it, vi } from "vitest"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import type { MockResponse } from "../test/authoringHarness"
import { TEST_CSRF, bootstrapWith, installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import { WorldTimesPage } from "./WorldTimesPage"

// B1-3a: the page records a time through a dialog. Cancel works, unsaved input is never dropped
// silently, an uncertain write survives the dialog closing, and recording never touches the clock.

const CAMPAIGN = sessionBootstrapFixture.campaigns[0]!.campaign_id
const OTHER = "campaign-two"
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
const RECORDED = {
    world_time_id: "t9",
    calendar_id: "cal-1",
    year: 3,
    month_number: 2,
    day: 5,
    hour: null,
    minute: null,
    label: null,
    precision: "day",
    sort_key: 9,
    display: "Year 3, Bloom 5",
}
const SHOWN = /Year 3 \(Founding\), Bloom 5/
// The other campaign's one time: text that only that campaign's page can show.
const OTHER_TIME = {
    world_time_id: "o1",
    calendar_id: null,
    year: null,
    month_number: null,
    day: null,
    hour: null,
    minute: null,
    label: "Other world marker",
    precision: "narrative",
    sort_key: 1,
    display: "Other world marker",
}

afterEach(() => {
    vi.unstubAllGlobals()
})

function setup(options: { post?: (n: number) => MockResponse | Promise<MockResponse | undefined> | undefined } = {}) {
    const server = installMockServer()
    const state = { items: [] as unknown[], readStatus: 0, posts: 0 }
    server.on("GET", TIMES, (call) =>
        call.path.includes(OTHER)
            ? { body: { items: [OTHER_TIME], next_cursor: null } }
            : state.readStatus !== 0
              ? { status: state.readStatus, body: {} }
              : { body: { items: state.items, next_cursor: null } },
    )
    server.on("GET", CALENDARS, { body: { calendars: [CALENDAR] } })
    server.on("POST", TIMES, async () => {
        state.posts += 1
        const answer = await options.post?.(state.posts)
        if (answer !== undefined) return answer
        state.items = [RECORDED]
        return { status: 201, body: { world_time_id: "t9", created: true, changed: true } }
    })
    const base = bootstrapWith().campaigns[0]!
    renderAuthoringRoutes({
        initialEntry: `/app/${CAMPAIGN}/world-times`,
        bootstrap: bootstrapWith({
            campaigns: [
                { ...base, campaign_id: CAMPAIGN, capabilities: ["canon.edit"] },
                { ...base, campaign_id: OTHER, capabilities: ["canon.edit"] },
            ],
        }),
        routes: [
            {
                path: "/app/:campaignId/world-times",
                element: (
                    <>
                        <Link to={`/app/${CAMPAIGN}/home`}>Go home</Link>
                        <Link to={`/app/${OTHER}/world-times`}>Go to the other campaign</Link>
                        <Link to={{ search: "?view=compact" }}>Same page, other query</Link>
                        <WorldTimesPage />
                    </>
                ),
            },
            { path: "/app/:campaignId/home", element: <p>Campaign home page</p> },
        ],
    })
    return { server, state }
}

function watchAnnouncements(): string[] {
    const spoken: string[] = []
    const region = screen.getByTestId("authoring-announcer")
    new MutationObserver(() => {
        const text = region.textContent?.trim() ?? ""
        if (text !== "") spoken.push(text)
    }).observe(region, { childList: true, subtree: true, characterData: true })
    return spoken
}

const trigger = () => screen.getByRole("button", { name: "Record a time" })
const dialog = () => screen.getByRole("dialog", { name: "Record a world time" })
const noDialog = () => expect(screen.queryByRole("dialog")).toBeNull()
const inDialog = () => within(dialog())
const posts = (server: ReturnType<typeof setup>["server"]) => server.callsTo("POST", TIMES)
const gets = (server: ReturnType<typeof setup>["server"]) => server.callsTo("GET", TIMES).length
const escape = () => {
    const event = new Event("cancel", { cancelable: true })
    fireEvent(dialog(), event)
    return event
}

// The page is usable once it has taken its own arrival focus (the heading); acting earlier races that.
async function ready() {
    await screen.findByRole("button", { name: "Record a time" })
    await waitFor(() => expect(screen.getByRole("heading", { level: 1, name: "World times" })).toHaveFocus())
}
async function openIt() {
    await ready()
    trigger().focus()
    fireEvent.click(trigger())
    return screen.findByRole("dialog", { name: "Record a world time" })
}
function fill(year = "3") {
    fireEvent.change(inDialog().getByRole("textbox", { name: /Year/ }), { target: { value: year } })
    fireEvent.change(inDialog().getByRole("combobox", { name: "Month" }), { target: { value: "2" } })
    fireEvent.change(inDialog().getByRole("textbox", { name: "Day" }), { target: { value: "5" } })
}
const record = () => fireEvent.click(inDialog().getByRole("button", { name: "Record time" }))
function deferred() {
    let release: () => void = () => {}
    const gate = new Promise<void>((resolve) => {
        release = resolve
    })
    return { gate, release }
}

describe("Record a time dialog: opening and closing", () => {
    it("opens a labelled, described modal with focus inside", async () => {
        setup()
        const opened = await openIt()
        expect(opened).toHaveAccessibleDescription(/adds it to this world's list\. It does not change the campaign's current time/)
        expect(opened.contains(document.activeElement)).toBe(true)
        expect(inDialog().getByRole("form", { name: "Record a world time" })).toBeInTheDocument()
    })

    it("closes a pristine form on Cancel without a request and returns focus to the trigger", async () => {
        const { server } = setup()
        await openIt()
        fireEvent.click(inDialog().getByRole("button", { name: "Cancel" }))
        noDialog()
        expect(trigger()).toHaveFocus()
        expect(posts(server)).toHaveLength(0)
    })

    it("closes a pristine form on Escape and returns focus to the trigger", async () => {
        const { server } = setup()
        await openIt()
        expect(escape().defaultPrevented).toBe(true)
        noDialog()
        expect(trigger()).toHaveFocus()
        expect(posts(server)).toHaveLength(0)
    })

    it("asks inside the same dialog before dropping input, and keeps it on Keep editing", async () => {
        const { server } = setup()
        await openIt()
        fill()
        fireEvent.click(inDialog().getByRole("button", { name: "Cancel" }))
        expect(inDialog().getByText("Discard this time? What you entered will be lost.")).toBeInTheDocument()
        expect(screen.getAllByRole("dialog")).toHaveLength(1)
        fireEvent.click(inDialog().getByRole("button", { name: "Keep editing" }))
        expect(inDialog().queryByText(/Discard this time/)).toBeNull()
        expect(inDialog().getByRole("textbox", { name: /Year/ })).toHaveValue("3")
        expect(inDialog().getByRole("textbox", { name: "Day" })).toHaveValue("5")
        // Escape asks the same question.
        escape()
        expect(inDialog().getByText(/Discard this time/)).toBeInTheDocument()
        expect(posts(server)).toHaveLength(0)
    })

    it("discards on Discard: closes with no request, returns focus, and reopens empty", async () => {
        const { server } = setup()
        await openIt()
        fill()
        escape()
        fireEvent.click(inDialog().getByRole("button", { name: "Discard" }))
        noDialog()
        expect(trigger()).toHaveFocus()
        fireEvent.click(trigger())
        expect(await screen.findByRole("textbox", { name: /Year/ })).toHaveValue("")
        expect(posts(server)).toHaveLength(0)
    })

    it("does nothing when the backdrop is clicked", async () => {
        setup()
        await openIt()
        fill()
        fireEvent.click(dialog())
        expect(dialog()).toBeInTheDocument()
        expect(inDialog().queryByText(/Discard this time/)).toBeNull()
        expect(inDialog().getByRole("textbox", { name: /Year/ })).toHaveValue("3")
    })
})

describe("Record a time dialog: recording", () => {
    it("records once, closes, shows and announces it once, and never touches the clock", async () => {
        const { server } = setup()
        await openIt()
        const spoken = watchAnnouncements()
        const readsBefore = gets(server)
        fill()
        record()
        await waitFor(() => noDialog())
        expect(await screen.findByText(/World time recorded: Common Reckoning: Year 3 \(Founding\), Bloom 5/)).toBeInTheDocument()
        expect(within(screen.getByRole("list")).getByText(SHOWN)).toBeInTheDocument()
        await waitFor(() => expect(spoken.filter((s) => s === "World time recorded")).toHaveLength(1))
        await act(async () => {})
        expect(spoken.filter((s) => s === "World time recorded")).toHaveLength(1)
        expect(trigger()).toHaveFocus()
        expect(gets(server)).toBeGreaterThan(readsBefore)
        expect(posts(server)).toHaveLength(1)
        expect(posts(server)[0]!.headers["X-CSRF-Token"]).toBe(TEST_CSRF)
        expect(posts(server)[0]!.headers["Idempotency-Key"]).toBeTruthy()
        expect(server.calls.filter((call) => /clock/.test(call.path))).toHaveLength(0)
    })

    it("shows progress, blocks dismissal and sends a double submit once while pending", async () => {
        const { gate, release } = deferred()
        const { server } = setup({
            post: async () => {
                await gate
                return undefined
            },
        })
        await openIt()
        fill()
        record()
        expect(await inDialog().findByRole("button", { name: "Recording…" })).toBeInTheDocument()
        expect(inDialog().getByRole("button", { name: "Cancel" })).toBeDisabled()
        // Escape and further submissions, by any path, change nothing.
        expect(escape().defaultPrevented).toBe(true)
        expect(dialog()).toBeInTheDocument()
        expect(inDialog().queryByText(/Discard this time/)).toBeNull()
        fireEvent.submit(inDialog().getByRole("form", { name: "Record a world time" }))
        fireEvent.submit(inDialog().getByRole("form", { name: "Record a world time" }))
        expect(posts(server)).toHaveLength(1)
        await act(async () => release())
        await waitFor(() => noDialog())
        expect(posts(server)).toHaveLength(1)
    })

    it("keeps the dialog and the input on a validation problem, with the summary inside it", async () => {
        const { server } = setup()
        await openIt()
        fireEvent.change(inDialog().getByRole("textbox", { name: "Day" }), { target: { value: "2" } })
        record()
        const summary = await inDialog().findByRole("alert")
        expect(summary).toHaveTextContent("Enter a whole-number year")
        expect(inDialog().getByRole("textbox", { name: "Day" })).toHaveValue("2")
        expect(posts(server)).toHaveLength(0)
    })

    it("shows a refused write inside the dialog, with the input kept", async () => {
        const { server } = setup({
            post: () => ({ status: 403, body: { error: { code: "forbidden", message: "m", correlation_id: "c" } } }),
        })
        await openIt()
        fill()
        record()
        expect(await inDialog().findByRole("button", { name: "Check my session" })).toBeInTheDocument()
        expect(inDialog().getByRole("textbox", { name: /Year/ })).toHaveValue("3")
        expect(posts(server)).toHaveLength(1)
    })

    it("fails closed when the list is refused after the write: the dialog goes with the page", async () => {
        const { state } = setup({
            post: () => undefined,
        })
        await openIt()
        fill()
        state.readStatus = 403
        record()
        await waitFor(() => expect(screen.queryByRole("dialog", { hidden: true })).toBeNull())
        expect(screen.queryByRole("form", { hidden: true })).toBeNull()
        expect(screen.queryByDisplayValue("3")).toBeNull()
    })
})

describe("Record a time dialog: a confirmed write whose list cannot be read", () => {
    it("closes, keeps the notice on the page, holds the trigger, and recovers by reading only", async () => {
        const { server, state } = setup()
        await openIt()
        const spoken = watchAnnouncements()
        fill()
        state.readStatus = 500
        record()
        expect(
            await screen.findByText(/World time recorded\. The latest world times could not be loaded/),
        ).toBeInTheDocument()
        noDialog()
        expect(spoken).not.toContain("World time recorded")
        expect(trigger()).toHaveAttribute("aria-disabled", "true")
        expect(trigger()).toHaveAccessibleDescription("Load the latest world times before recording another.")
        fireEvent.click(trigger())
        noDialog()

        state.readStatus = 0
        const readsBefore = gets(server)
        fireEvent.click(screen.getByRole("button", { name: "Try again" }))
        expect(await within(await screen.findByRole("list")).findByText(/Year 3/)).toBeInTheDocument()
        await waitFor(() => expect(spoken.filter((s) => s === "World time recorded")).toHaveLength(1))
        expect(gets(server)).toBeGreaterThan(readsBefore)
        expect(posts(server)).toHaveLength(1)
        expect(trigger()).toHaveAttribute("aria-disabled", "false")
        expect(screen.getByText(/World time recorded: /)).toBeInTheDocument()
        fireEvent.click(trigger())
        expect(await screen.findByRole("dialog", { name: "Record a world time" })).toBeInTheDocument()
    })
})

describe("Record a time dialog: an uncertain write", () => {
    it("survives closing the dialog and is retried only as the same request", async () => {
        const { server } = setup({ post: (n) => (n === 1 ? { networkError: true } : undefined) })
        await openIt()
        fill()
        record()
        expect(await inDialog().findByText(/cannot tell whether this was saved/)).toBeInTheDocument()
        expect(dialog()).toBeInTheDocument()

        // Closing is allowed, and says what it keeps. It is not called discarding or cancelling.
        fireEvent.click(inDialog().getByRole("button", { name: "Cancel" }))
        expect(inDialog().getByText(/may already have been recorded/)).toBeInTheDocument()
        expect(inDialog().queryByRole("button", { name: "Discard" })).toBeNull()
        const readsBefore = gets(server)
        fireEvent.click(inDialog().getByRole("button", { name: "Close and check later" }))
        noDialog()
        expect(gets(server)).toBe(readsBefore)
        expect(screen.getByText(/may or may not have been saved/)).toBeInTheDocument()
        expect(posts(server)).toHaveLength(1)

        // Reopening shows the same unresolved attempt; Retry re-sends it exactly.
        fireEvent.click(screen.getByRole("button", { name: "Reopen to retry" }))
        expect(await inDialog().findByText(/cannot tell whether this was saved/)).toBeInTheDocument()
        expect(inDialog().getByRole("textbox", { name: /Year/ })).toHaveValue("3")
        fireEvent.click(inDialog().getByRole("button", { name: "Retry" }))
        await waitFor(() => noDialog())
        const [first, second] = posts(server)
        expect(second!.body).toEqual(first!.body)
        expect(second!.headers["Idempotency-Key"]).toBe(first!.headers["Idempotency-Key"])
        expect(screen.queryByText(/may or may not have been saved/)).toBeNull()
    })

    it("sends the earlier attempt again, not a new recording, when the form was changed", async () => {
        const { server } = setup({ post: (n) => (n <= 2 ? { networkError: true } : undefined) })
        await openIt()
        fill("3")
        record()
        await inDialog().findByText(/cannot tell whether this was saved/)
        fireEvent.change(inDialog().getByRole("textbox", { name: /Year/ }), { target: { value: "4" } })
        record()
        expect(await inDialog().findByText(/sent again first/)).toBeInTheDocument()
        await waitFor(() => expect(posts(server)).toHaveLength(2))
        const [first, second] = posts(server)
        expect(second!.body).toEqual(first!.body)
        expect(second!.headers["Idempotency-Key"]).toBe(first!.headers["Idempotency-Key"])
        // What was changed is still in the form.
        expect(inDialog().getByRole("textbox", { name: /Year/ })).toHaveValue("4")
    })
})

describe("Record a time dialog: leaving the page", () => {
    it("asks inside the dialog, keeps context and input on Stay, and leaves on Leave", async () => {
        setup()
        await openIt()
        fill()
        fireEvent.click(screen.getByRole("link", { name: "Go home", hidden: true }))
        expect(await inDialog().findByText(/You have entered a time that has not been recorded/)).toBeInTheDocument()
        expect(screen.getAllByRole("dialog")).toHaveLength(1)
        fireEvent.click(inDialog().getByRole("button", { name: "Stay" }))
        expect(inDialog().getByRole("textbox", { name: /Year/ })).toHaveValue("3")
        expect(screen.queryByText("Campaign home page")).toBeNull()

        fireEvent.click(screen.getByRole("link", { name: "Go home", hidden: true }))
        fireEvent.click(await inDialog().findByRole("button", { name: "Leave" }))
        expect(await screen.findByText("Campaign home page")).toBeInTheDocument()
    })

    it("does not ask for a pristine form or a query-only change", async () => {
        setup()
        await openIt()
        fill()
        fireEvent.click(screen.getByRole("link", { name: "Same page, other query", hidden: true }))
        await act(async () => {})
        expect(inDialog().queryByText(/You have entered a time/)).toBeNull()
        expect(inDialog().getByRole("textbox", { name: /Year/ })).toHaveValue("3")

        fireEvent.click(inDialog().getByRole("button", { name: "Cancel" }))
        fireEvent.click(inDialog().getByRole("button", { name: "Discard" }))
        fireEvent.click(screen.getByRole("link", { name: "Go home" }))
        expect(await screen.findByText("Campaign home page")).toBeInTheDocument()
    })

    it("asks about an uncertain write left behind a closed dialog", async () => {
        setup({ post: (n) => (n === 1 ? { networkError: true } : undefined) })
        await openIt()
        fill()
        record()
        await inDialog().findByText(/cannot tell whether this was saved/)
        fireEvent.click(inDialog().getByRole("button", { name: "Cancel" }))
        fireEvent.click(inDialog().getByRole("button", { name: "Close and check later" }))
        noDialog()
        fireEvent.click(screen.getByRole("link", { name: "Go home" }))
        const ask = await screen.findByRole("dialog", { name: "Leave this page?" })
        expect(ask).toHaveAccessibleDescription(/may already have been recorded/)
        fireEvent.click(within(ask).getByRole("button", { name: "Stay" }))
        await waitFor(() => noDialog())
        expect(screen.getByText(/may or may not have been saved/)).toBeInTheDocument()
        expect(screen.queryByText("Campaign home page")).toBeNull()
    })

    it("never shows or announces a late answer under another campaign", async () => {
        const { gate, release } = deferred()
        const { server } = setup({
            post: async () => {
                await gate
                return undefined
            },
        })
        await openIt()
        const spoken = watchAnnouncements()
        fill()
        record()
        await inDialog().findByRole("button", { name: "Recording…" })
        fireEvent.click(screen.getByRole("link", { name: "Go to the other campaign", hidden: true }))
        expect(await inDialog().findByText(/A time is being recorded/)).toBeInTheDocument()
        fireEvent.click(inDialog().getByRole("button", { name: "Leave" }))
        // The destination has loaded: its own time is on screen, and the origin's page is gone.
        expect(await screen.findByText("Other world marker")).toBeInTheDocument()
        expect(screen.queryByText("No times have been recorded for this world yet.")).toBeNull()
        await act(async () => release())
        await act(async () => {})
        expect(screen.queryByText(/World time recorded/)).toBeNull()
        expect(screen.queryByText(/Year 3/)).toBeNull()
        expect(screen.getByText("Other world marker")).toBeInTheDocument()
        expect(spoken).toEqual([])
        expect(screen.queryByRole("dialog")).toBeNull()
        expect(trigger()).toHaveAttribute("aria-disabled", "false")
        expect(posts(server)).toHaveLength(1)
    })
})

describe("Record a time dialog: a retry that succeeds while newer input is waiting", () => {
    it("keeps the dialog and the newer draft, says it is unrecorded, and records it later under a new key", async () => {
        const { server } = setup({ post: (n) => (n === 1 ? { networkError: true } : undefined) })
        await openIt()
        const spoken = watchAnnouncements()
        fill("3")
        record()
        await inDialog().findByText(/cannot tell whether this was saved/)
        fireEvent.change(inDialog().getByRole("textbox", { name: /Year/ }), { target: { value: "4" } })

        // Retry the original operation (year 3); the form already holds year 4.
        fireEvent.click(inDialog().getByRole("button", { name: "Retry" }))
        const notice = await inDialog().findByText(
            /The time you submitted earlier was recorded: Common Reckoning: Year 3 \(Founding\), Bloom 5\. What is in the form now has not been recorded\./,
        )
        expect(notice).toBeInTheDocument()
        await act(async () => {})
        // Not closed, not announced as done, and the draft is intact.
        expect(dialog()).toBeInTheDocument()
        expect(spoken).not.toContain("World time recorded")
        expect(inDialog().getByRole("textbox", { name: /Year/ })).toHaveValue("4")
        expect(inDialog().getByRole("textbox", { name: "Day" })).toHaveValue("5")
        expect(posts(server)).toHaveLength(2)
        const [first, retried] = posts(server)
        expect(retried!.body).toEqual(first!.body)
        expect(retried!.headers["Idempotency-Key"]).toBe(first!.headers["Idempotency-Key"])

        // Still guarded: leaving asks, and Stay brings the draft back.
        fireEvent.click(screen.getByRole("link", { name: "Go home", hidden: true }))
        expect(await inDialog().findByText(/You have entered a time that has not been recorded/)).toBeInTheDocument()
        fireEvent.click(inDialog().getByRole("button", { name: "Stay" }))
        expect(inDialog().getByRole("textbox", { name: /Year/ })).toHaveValue("4")
        expect(screen.queryByText("Campaign home page")).toBeNull()

        // A deliberate recording is a new request: new key, the draft's own body, once.
        record()
        await waitFor(() => noDialog())
        expect(posts(server)).toHaveLength(3)
        const third = posts(server)[2]!
        expect(third.body).toMatchObject({ year: 4 })
        expect(third.headers["Idempotency-Key"]).toBeTruthy()
        expect(third.headers["Idempotency-Key"]).not.toBe(first!.headers["Idempotency-Key"])
        await waitFor(() => expect(spoken.filter((x) => x === "World time recorded")).toHaveLength(1))
        expect(trigger()).toHaveFocus()
    })

    it("closes normally when the retry succeeds and nothing newer was entered", async () => {
        const { server } = setup({ post: (n) => (n === 1 ? { networkError: true } : undefined) })
        await openIt()
        const spoken = watchAnnouncements()
        fill("3")
        record()
        await inDialog().findByText(/cannot tell whether this was saved/)
        fireEvent.click(inDialog().getByRole("button", { name: "Retry" }))
        await waitFor(() => noDialog())
        expect(screen.queryByText(/has not been recorded/)).toBeNull()
        await waitFor(() => expect(spoken.filter((x) => x === "World time recorded")).toHaveLength(1))
        expect(trigger()).toHaveFocus()
        expect(posts(server)).toHaveLength(2)
    })

    it("closes, keeps the draft and the page notice, and reads only, when the list read fails after the retry", async () => {
        const { server, state } = setup({ post: (n) => (n === 1 ? { networkError: true } : undefined) })
        await openIt()
        fill("3")
        record()
        await inDialog().findByText(/cannot tell whether this was saved/)
        fireEvent.change(inDialog().getByRole("textbox", { name: /Year/ }), { target: { value: "4" } })
        state.readStatus = 500
        fireEvent.click(inDialog().getByRole("button", { name: "Retry" }))
        expect(
            await screen.findByText(/World time recorded\. The latest world times could not be loaded/),
        ).toBeInTheDocument()
        noDialog()
        expect(trigger()).toHaveAttribute("aria-disabled", "true")
        expect(screen.getByText(/What you entered after it is kept in the form/)).toBeInTheDocument()
        state.readStatus = 0
        fireEvent.click(screen.getByRole("button", { name: "Try again" }))
        await within(await screen.findByRole("list")).findByText(/Year 3/)
        expect(posts(server)).toHaveLength(2)
        await waitFor(() => expect(trigger()).toHaveAttribute("aria-disabled", "false"))
        fireEvent.click(trigger())
        expect(await screen.findByRole("textbox", { name: /Year/ })).toHaveValue("4")
    })
})

describe("Record a time dialog: Escape answers the question being asked", () => {
    it("means Stay during the leave question: navigation is cancelled and no other question appears", async () => {
        setup()
        await openIt()
        fill()
        fireEvent.click(screen.getByRole("link", { name: "Go home", hidden: true }))
        expect(await inDialog().findByText(/You have entered a time that has not been recorded/)).toBeInTheDocument()
        expect(escape().defaultPrevented).toBe(true)
        await waitFor(() => expect(inDialog().queryByText(/You have entered a time that has not been recorded/)).toBeNull())
        expect(inDialog().queryByText(/Discard this time/)).toBeNull()
        expect(inDialog().queryByRole("group", { name: "Confirm" })).toBeNull()
        expect(screen.queryByText("Campaign home page")).toBeNull()
        expect(inDialog().getByRole("textbox", { name: /Year/ })).toHaveValue("3")
        expect(inDialog().getByRole("textbox", { name: "Day" })).toHaveValue("5")

        // The navigation really was cancelled: ordinary Escape still asks to discard, and a new attempt asks again.
        escape()
        expect(inDialog().getByText(/Discard this time/)).toBeInTheDocument()
        fireEvent.click(inDialog().getByRole("button", { name: "Keep editing" }))
        fireEvent.click(screen.getByRole("link", { name: "Go home", hidden: true }))
        expect(await inDialog().findByText(/You have entered a time that has not been recorded/)).toBeInTheDocument()
    })

    it("replaces a discard question with the leave question and leaves no hidden one behind", async () => {
        setup()
        await openIt()
        fill()
        escape()
        expect(inDialog().getByText(/Discard this time/)).toBeInTheDocument()
        fireEvent.click(screen.getByRole("link", { name: "Go home", hidden: true }))
        expect(await inDialog().findByText(/You have entered a time that has not been recorded/)).toBeInTheDocument()
        expect(inDialog().queryByText(/Discard this time/)).toBeNull()
        fireEvent.click(inDialog().getByRole("button", { name: "Stay" }))
        expect(inDialog().queryByText(/Discard this time/)).toBeNull()
        expect(inDialog().getByRole("textbox", { name: /Year/ })).toHaveValue("3")
    })

    it("means Keep editing during the discard question", async () => {
        const { server } = setup()
        await openIt()
        fill()
        escape()
        expect(inDialog().getByText(/Discard this time/)).toBeInTheDocument()
        escape()
        expect(inDialog().queryByText(/Discard this time/)).toBeNull()
        expect(dialog()).toBeInTheDocument()
        expect(inDialog().getByRole("textbox", { name: /Year/ })).toHaveValue("3")
        expect(posts(server)).toHaveLength(0)
    })

    it("means Stay while a request is pending, and still cannot dismiss the dialog", async () => {
        const { gate, release } = deferred()
        setup({
            post: async () => {
                await gate
                return undefined
            },
        })
        await openIt()
        fill()
        record()
        await inDialog().findByRole("button", { name: "Recording…" })
        fireEvent.click(screen.getByRole("link", { name: "Go home", hidden: true }))
        expect(await inDialog().findByText(/A time is being recorded/)).toBeInTheDocument()
        escape()
        await waitFor(() => expect(inDialog().queryByText(/A time is being recorded/)).toBeNull())
        expect(dialog()).toBeInTheDocument()
        expect(screen.queryByText("Campaign home page")).toBeNull()
        escape()
        expect(dialog()).toBeInTheDocument()
        expect(inDialog().queryByText(/Discard this time/)).toBeNull()
        await act(async () => release())
        await waitFor(() => noDialog())
    })
})

describe("Record a time dialog: where focus goes on closing", () => {
    it("reaches the persistent button when the transient Reopen control that opened the dialog is gone", async () => {
        const { server } = setup({ post: (n) => (n === 1 ? { networkError: true } : undefined) })
        await openIt()
        fill()
        record()
        await inDialog().findByText(/cannot tell whether this was saved/)
        fireEvent.click(inDialog().getByRole("button", { name: "Cancel" }))
        fireEvent.click(inDialog().getByRole("button", { name: "Close and check later" }))
        noDialog()

        const reopen = screen.getByRole("button", { name: "Reopen to retry" })
        reopen.focus()
        fireEvent.click(reopen)
        await inDialog().findByText(/cannot tell whether this was saved/)
        // The control that opened the dialog is no longer on the page.
        expect(reopen.isConnected).toBe(false)
        fireEvent.click(inDialog().getByRole("button", { name: "Retry" }))
        await waitFor(() => noDialog())
        expect(trigger()).toHaveFocus()
        expect(posts(server)).toHaveLength(2)
    })

    it("does not move focus to the page's button once the page has been left", async () => {
        setup()
        await openIt()
        fill()
        fireEvent.click(screen.getByRole("link", { name: "Go home", hidden: true }))
        fireEvent.click(await inDialog().findByRole("button", { name: "Leave" }))
        expect(await screen.findByText("Campaign home page")).toBeInTheDocument()
        expect(screen.queryByRole("button", { name: "Record a time" })).toBeNull()
        expect(document.body.contains(document.activeElement)).toBe(true)
    })
})
