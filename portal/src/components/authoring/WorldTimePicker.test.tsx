import { act, fireEvent, screen, waitFor, within } from "@testing-library/react"
import { StrictMode, useState } from "react"
import { Link } from "react-router"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { sessionBootstrapFixture } from "../../fixtures/sessionBootstrap"
import { useUnsavedChangesGuard } from "../../hooks/useUnsavedChangesGuard"
import type { MockResponse } from "../../test/authoringHarness"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../../test/authoringHarness"
import { navigationRegistryCounts, setCommittedPerspective } from "../../hooks/navigationHolds"
import { ConfirmDialog } from "./ConfirmDialog"
import { WorldTimePicker } from "./WorldTimePicker"

// B1-3b: the picker records a time in the reviewed form dialog. The form around the picker is never
// submitted, reset or marked saved; the recorded time is chosen only once the list shows it.

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
const T1 = TIME("t1", "Year 1")
const T9 = TIME("t9", "Year 3, Bloom 5")
const OTHER_TIME = TIME("o1", "Other world marker")

afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
})

interface Options {
    post?: (n: number) => MockResponse | Promise<MockResponse | undefined> | undefined
}

function setupServer(options: Options = {}) {
    const server = installMockServer()
    // `hold`: while set, this campaign's list reads wait for it and then answer with the state by then.
    const state = { items: [T1] as unknown[], readStatus: 0, hold: null as Promise<void> | null }
    server.on("GET", TIMES, async (call) => {
        if (call.path.includes(OTHER)) return { body: { items: [OTHER_TIME], next_cursor: null } }
        await state.hold
        return state.readStatus !== 0
            ? { status: state.readStatus, body: {} }
            : { body: { items: state.items, next_cursor: null } }
    })
    server.on("GET", CALENDARS, { body: { calendars: [CALENDAR] } })
    let posts = 0
    server.on("POST", TIMES, async () => {
        posts += 1
        const answer = await options.post?.(posts)
        if (answer !== undefined) return answer
        state.items = [T9, T1]
        return { status: 201, body: { world_time_id: "t9", created: true, changed: true } }
    })
    return { server, state }
}

interface OuterProps {
    submit: () => void
    // A page-level guard for the outer form's own input (as the event form has).
    pageGuard?: boolean
    two?: boolean
    initialCampaign?: string
}

// A caller as the real ones are: a real <form> holding fields of its own, a picker, and a submit button.
function Outer({ submit, pageGuard = false, two = false, initialCampaign = CAMPAIGN }: OuterProps) {
    const [campaign, setCampaign] = useState(initialCampaign)
    const [note, setNote] = useState("")
    const [remarks, setRemarks] = useState("")
    const [when, setWhen] = useState("")
    const [other, setOther] = useState("")
    return (
        <>
            <Link to="/away">Go away</Link>
            <Link to="/pick" state={{ ctx: { v: 1, characterId: "char-b" } }}>
                Switch perspective
            </Link>
            <button type="button" onClick={() => setCampaign(OTHER)}>
                Switch campaign
            </button>
            <button type="button" onClick={() => setWhen("t1")}>
                Caller sets t1
            </button>
            <button type="button" onClick={() => setWhen("")}>
                Caller clears
            </button>
            {pageGuard ? <PageGuard dirty={note !== ""} /> : null}
            <form
                aria-label="Outer form"
                onSubmit={(event) => {
                    event.preventDefault()
                    submit()
                }}
            >
                <label>
                    Note
                    <input value={note} onChange={(event) => setNote(event.target.value)} />
                </label>
                <label>
                    Remarks
                    <textarea value={remarks} onChange={(event) => setRemarks(event.target.value)} />
                </label>
                <WorldTimePicker campaignId={campaign} id="when" label="When" value={when} onChange={setWhen} />
                {two ? (
                    <WorldTimePicker campaignId={campaign} id="until" label="Until" value={other} onChange={setOther} />
                ) : null}
                <button type="submit">Save outer</button>
            </form>
            <output data-testid="chosen">{when}</output>
            <output data-testid="chosen-until">{other}</output>
        </>
    )
}

function PageGuard({ dirty }: { dirty: boolean }) {
    const guard = useUnsavedChangesGuard(dirty)
    return (
        <ConfirmDialog
            open={guard.blocked}
            title="Leave the outer page?"
            description="The page has unsaved changes."
            confirmLabel="Leave"
            cancelLabel="Stay"
            onConfirm={guard.discard}
            onCancel={guard.stay}
        />
    )
}

function render(props: Partial<OuterProps> = {}) {
    const submit = vi.fn()
    const view = renderAuthoringRoutes({
        initialEntry: "/pick",
        bootstrap: bootstrapWith(),
        routes: [
            { path: "/pick", element: <Outer submit={submit} {...props} /> },
            { path: "/away", element: <p>Away page</p> },
        ],
    })
    return { submit, router: view.router }
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

const trigger = async () => (await screen.findAllByRole("button", { name: "Record a new time" }))[0]!
const dialog = () => screen.getByRole("dialog", { name: "Record a world time" })
const noDialog = () => expect(screen.queryByRole("dialog")).toBeNull()
const inDialog = () => within(dialog())
const outer = () => within(screen.getByRole("form", { name: "Outer form" }))
const chosen = () => screen.getByTestId("chosen")
const escape = () => {
    const event = new Event("cancel", { cancelable: true })
    fireEvent(dialog(), event)
    return event
}
async function openIt() {
    const button = await trigger()
    button.focus()
    fireEvent.click(button)
    return screen.findByRole("dialog", { name: "Record a world time" })
}
function fill(year = "3") {
    fireEvent.change(inDialog().getByRole("textbox", { name: /Year/ }), { target: { value: year } })
    fireEvent.change(inDialog().getByRole("combobox", { name: "Month" }), { target: { value: "2" } })
    fireEvent.change(inDialog().getByRole("textbox", { name: "Day" }), { target: { value: "5" } })
}
const record = () => fireEvent.click(inDialog().getByRole("button", { name: "Record time" }))
const posts = (server: ReturnType<typeof setupServer>["server"]) => server.callsTo("POST", TIMES)
function deferred() {
    let release: () => void = () => {}
    const gate = new Promise<void>((resolve) => {
        release = resolve
    })
    return { gate, release }
}
const optionNames = () => within(screen.getByRole("combobox", { name: "When" })).queryAllByRole("option").map((o) => o.textContent)

describe("WorldTimePicker: the dialog", () => {
    it("opens a labelled modal outside the surrounding form, with no form nested in it", async () => {
        setupServer()
        render()
        const opened = await openIt()
        expect(opened).toHaveAccessibleDescription(/does not change the campaign's current time/)
        expect(opened.contains(document.activeElement)).toBe(true)
        expect(screen.getByRole("form", { name: "Outer form" }).contains(opened)).toBe(false)
        expect(opened.querySelector("form")).toBeNull()
        expect(inDialog().getByRole("group", { name: "Record a new world time" })).toBeInTheDocument()
        for (const button of inDialog().getAllByRole("button")) expect(button).toHaveAttribute("type", "button")
    })

    it("closes a pristine dialog on Cancel and on Escape with no request, returning focus to the trigger", async () => {
        const { server } = setupServer()
        render()
        await openIt()
        fireEvent.click(inDialog().getByRole("button", { name: "Cancel" }))
        noDialog()
        expect(await trigger()).toHaveFocus()
        await openIt()
        expect(escape().defaultPrevented).toBe(true)
        noDialog()
        expect(await trigger()).toHaveFocus()
        expect(posts(server)).toHaveLength(0)
    })

    it("asks inside the dialog before dropping input; Keep editing keeps it, Discard empties it", async () => {
        const { server } = setupServer()
        render()
        await openIt()
        fill()
        fireEvent.click(inDialog().getByRole("button", { name: "Cancel" }))
        expect(inDialog().getByText(/Discard this time/)).toBeInTheDocument()
        expect(screen.getAllByRole("dialog")).toHaveLength(1)
        // Escape answers that question: Keep editing.
        escape()
        expect(inDialog().queryByText(/Discard this time/)).toBeNull()
        expect(inDialog().getByRole("textbox", { name: /Year/ })).toHaveValue("3")
        // The backdrop does nothing.
        fireEvent.click(dialog())
        expect(inDialog().queryByText(/Discard this time/)).toBeNull()
        fireEvent.click(inDialog().getByRole("button", { name: "Cancel" }))
        fireEvent.click(inDialog().getByRole("button", { name: "Discard" }))
        noDialog()
        expect(await trigger()).toHaveFocus()
        await openIt()
        expect(inDialog().getByRole("textbox", { name: /Year/ })).toHaveValue("")
        expect(posts(server)).toHaveLength(0)
    })
})

describe("WorldTimePicker: the surrounding form", () => {
    it("is never submitted by clicking Record or by Enter in the dialog, and keeps its values", async () => {
        const { server } = setupServer()
        const { submit } = render()
        fireEvent.change(outer().getByRole("textbox", { name: "Note" }), { target: { value: "keep me" } })
        fireEvent.change(outer().getByRole("textbox", { name: "Remarks" }), { target: { value: "line one\nline two" } })

        // Open and cancel.
        await openIt()
        fireEvent.click(inDialog().getByRole("button", { name: "Cancel" }))
        // Enter records (once), and does not submit the outer form.
        await openIt()
        fill()
        fireEvent.keyDown(inDialog().getByRole("textbox", { name: "Day" }), { key: "Enter" })
        await waitFor(() => noDialog())
        expect(posts(server)).toHaveLength(1)
        // Click records too.
        await openIt()
        fill("4")
        record()
        await waitFor(() => noDialog())
        expect(posts(server)).toHaveLength(2)

        expect(submit).not.toHaveBeenCalled()
        expect(outer().getByRole("textbox", { name: "Note" })).toHaveValue("keep me")
        expect(outer().getByRole("textbox", { name: "Remarks" })).toHaveValue("line one\nline two")
    })

    it("does not pass dialog events on to the caller's handlers", async () => {
        setupServer()
        const seen = vi.fn()
        const submit = vi.fn()
        renderAuthoringRoutes({
            initialEntry: "/pick",
            bootstrap: bootstrapWith(),
            routes: [
                {
                    path: "/pick",
                    element: (
                        <div onClick={seen} onKeyDown={seen} onChange={seen}>
                            <Outer submit={submit} />
                        </div>
                    ),
                },
            ],
        })
        await openIt()
        seen.mockClear()
        fireEvent.change(inDialog().getByRole("textbox", { name: /Year/ }), { target: { value: "3" } })
        fireEvent.keyDown(inDialog().getByRole("textbox", { name: /Year/ }), { key: "a" })
        fireEvent.click(inDialog().getByRole("button", { name: "Cancel" }))
        expect(seen).not.toHaveBeenCalled()
    })

    it("keeps a textarea's newline Enter and the dialog's own Enter behaviour apart", async () => {
        setupServer()
        render()
        const remarks = outer().getByRole("textbox", { name: "Remarks" })
        fireEvent.change(remarks, { target: { value: "a\nb" } })
        await openIt()
        const event = fireEvent.keyDown(remarks, { key: "Enter" })
        // Not prevented: the dialog does not swallow Enter for the rest of the page.
        expect(event).toBe(true)
    })
})

describe("WorldTimePicker: choosing the recorded time", () => {
    it("chooses it only once the list that was read afterwards shows it, then closes and announces once", async () => {
        const { server, state } = setupServer()
        render()
        await openIt()
        const spoken = watchAnnouncements()
        fill()
        const read = deferred()
        state.hold = read.gate
        record()
        await waitFor(() => expect(inDialog().getByRole("textbox", { name: /Year/ })).toHaveValue(""))
        expect(posts(server)).toHaveLength(1)
        // Confirmed, not yet read: nothing is chosen, the option is not offered.
        expect(chosen()).toHaveTextContent("")
        expect(optionNames()).not.toContain("Year 3, Bloom 5")
        state.hold = null
        await act(async () => read.release())
        await waitFor(() => expect(chosen()).toHaveTextContent("t9"))
        noDialog()
        await waitFor(() => expect(spoken.filter((s) => s === "World time recorded")).toHaveLength(1))
        await act(async () => {})
        expect(spoken.filter((s) => s === "World time recorded")).toHaveLength(1)
        expect(await trigger()).toHaveFocus()
    })

    it("says so, and chooses nothing, when the list is read but does not show the time", async () => {
        // The write is confirmed but the list (unchanged) does not contain it.
        setupServer({ post: () => ({ status: 201, body: { world_time_id: "t9", created: true, changed: true } }) })
        render()
        await openIt()
        fill()
        record()
        expect(await screen.findByText(/it is not among the times listed here, so it has not been chosen/)).toBeInTheDocument()
        expect(chosen()).toHaveTextContent("")
    })

    it("keeps the previous selection through a failed read and recovers by reading only", async () => {
        const { server, state } = setupServer()
        render()
        fireEvent.change(await screen.findByRole("combobox", { name: "When" }), { target: { value: "t1" } })
        await openIt()
        fill()
        state.readStatus = 500
        record()
        expect(await screen.findByText(/World time recorded\. The latest world times could not be loaded/)).toBeInTheDocument()
        noDialog()
        expect(chosen()).toHaveTextContent("t1")
        const held = await trigger()
        expect(held).toHaveAttribute("aria-disabled", "true")
        fireEvent.click(held)
        noDialog()

        state.readStatus = 0
        const writes = posts(server).length
        fireEvent.click(screen.getByRole("button", { name: "Load latest" }))
        await waitFor(() => expect(chosen()).toHaveTextContent("t9"))
        expect(posts(server)).toHaveLength(writes)
        expect((await trigger()).getAttribute("aria-disabled")).toBe("false")
    })

    it("does not overwrite a newer deliberate selection with a late recovery", async () => {
        const { server, state } = setupServer()
        render()
        await openIt()
        fill()
        state.readStatus = 500
        record()
        await screen.findByText(/could not be loaded/)
        // The person chooses another time while the recorded one is unread.
        fireEvent.change(screen.getByRole("combobox", { name: "When" }), { target: { value: "t1" } })
        state.readStatus = 0
        fireEvent.click(screen.getByRole("button", { name: "Load latest" }))
        await waitFor(() => expect(optionNames()).toContain("Year 3, Bloom 5"))
        await act(async () => {})
        expect(chosen()).toHaveTextContent("t1")
        expect(posts(server)).toHaveLength(1)
    })
})

describe("WorldTimePicker: selection precedence", () => {
    it("does not overwrite a value the caller set itself while the recorded time was unread", async () => {
        const { state } = setupServer()
        render()
        await openIt()
        fill()
        state.readStatus = 500
        record()
        await screen.findByText(/could not be loaded/)
        fireEvent.click(screen.getByRole("button", { name: "Caller sets t1" }))
        expect(chosen()).toHaveTextContent("t1")
        state.readStatus = 0
        fireEvent.click(screen.getByRole("button", { name: "Load latest" }))
        await waitFor(() => expect(optionNames()).toContain("Year 3, Bloom 5"))
        await act(async () => {})
        expect(chosen()).toHaveTextContent("t1")
    })
})

describe("WorldTimePicker: drafts and uncertain requests", () => {
    it("keeps an uncertain request across closing and reopening, and retries it as the same request", async () => {
        const { server } = setupServer({ post: (n) => (n === 1 ? { networkError: true } : undefined) })
        render()
        await openIt()
        fill()
        record()
        await inDialog().findByText(/cannot tell whether this was saved/)
        fireEvent.click(inDialog().getByRole("button", { name: "Cancel" }))
        fireEvent.click(inDialog().getByRole("button", { name: "Close and check later" }))
        noDialog()
        // Reloading the list is a read and proves nothing about the write.
        const reads = server.callsTo("GET", TIMES).length
        fireEvent.click(screen.getByRole("button", { name: "Reload the list" }))
        await waitFor(() => expect(server.callsTo("GET", TIMES).length).toBeGreaterThan(reads))
        expect(screen.getByText(/may or may not have been saved/)).toBeInTheDocument()
        expect(posts(server)).toHaveLength(1)

        // Reopen; change the draft; Retry still replays the original request.
        fireEvent.click(screen.getByRole("button", { name: "Reopen to retry" }))
        await inDialog().findByText(/cannot tell whether this was saved/)
        fireEvent.change(inDialog().getByRole("textbox", { name: /Year/ }), { target: { value: "4" } })
        fireEvent.click(inDialog().getByRole("button", { name: "Retry" }))
        await inDialog().findByText(/What is in the form now has not been recorded/)
        const [first, retried] = posts(server)
        expect(retried!.body).toEqual(first!.body)
        expect(retried!.headers["Idempotency-Key"]).toBe(first!.headers["Idempotency-Key"])
        expect(inDialog().getByRole("textbox", { name: /Year/ })).toHaveValue("4")
        await waitFor(() => expect(chosen()).toHaveTextContent("t9"))

        // Recording the kept draft is a new request.
        record()
        await waitFor(() => noDialog())
        const third = posts(server)[2]!
        expect(third.body).toMatchObject({ year: 4 })
        expect(third.headers["Idempotency-Key"]).not.toBe(first!.headers["Idempotency-Key"])
    })

    it("restores focus to the persistent trigger when the transient Reopen control is gone", async () => {
        setupServer({ post: (n) => (n === 1 ? { networkError: true } : undefined) })
        render()
        await openIt()
        fill()
        record()
        await inDialog().findByText(/cannot tell whether this was saved/)
        fireEvent.click(inDialog().getByRole("button", { name: "Cancel" }))
        fireEvent.click(inDialog().getByRole("button", { name: "Close and check later" }))
        const reopen = screen.getByRole("button", { name: "Reopen to retry" })
        reopen.focus()
        fireEvent.click(reopen)
        await inDialog().findByText(/cannot tell whether this was saved/)
        fireEvent.click(inDialog().getByRole("button", { name: "Retry" }))
        await waitFor(() => noDialog())
        expect(await trigger()).toHaveFocus()
    })

    it("classifies the form as it is after the read: edits during the read and during the request both count", async () => {
        const { state } = setupServer({ post: (n) => (n === 1 ? { networkError: true } : undefined) })
        render()
        await openIt()
        fill("3")
        record()
        await inDialog().findByText(/cannot tell whether this was saved/)
        const read = deferred()
        state.hold = read.gate
        fireEvent.click(inDialog().getByRole("button", { name: "Retry" }))
        await waitFor(() => expect(inDialog().getByRole("textbox", { name: /Year/ })).toHaveValue(""))
        fireEvent.change(inDialog().getByRole("textbox", { name: /Year/ }), { target: { value: "4" } })
        state.hold = null
        await act(async () => read.release())
        await inDialog().findByText(/The time you submitted earlier was recorded: Year 3, Bloom 5\. What is in the form now has not been recorded/)
        expect(dialog()).toBeInTheDocument()
        expect(inDialog().getByRole("textbox", { name: /Year/ })).toHaveValue("4")
        // The recorded time is chosen on the form behind the dialog, which is otherwise untouched.
        await waitFor(() => expect(chosen()).toHaveTextContent("t9"))
    })

    it("keeps input entered while the request runs, unrecorded", async () => {
        const request = deferred()
        setupServer({
            post: async () => {
                await request.gate
                return undefined
            },
        })
        render()
        await openIt()
        fill("3")
        record()
        await inDialog().findByRole("button", { name: "Recording…" })
        fireEvent.change(inDialog().getByRole("textbox", { name: /Year/ }), { target: { value: "4" } })
        await act(async () => request.release())
        await inDialog().findByText(/What is in the form now has not been recorded/)
        expect(inDialog().getByRole("textbox", { name: /Year/ })).toHaveValue("4")
    })

    it("keeps the draft and its status through a failed read, recovery and reopening", async () => {
        const { state } = setupServer({ post: (n) => (n === 1 ? { networkError: true } : undefined) })
        render()
        await openIt()
        fill("3")
        record()
        await inDialog().findByText(/cannot tell whether this was saved/)
        const read = deferred()
        state.hold = read.gate
        fireEvent.click(inDialog().getByRole("button", { name: "Retry" }))
        await waitFor(() => expect(inDialog().getByRole("textbox", { name: /Year/ })).toHaveValue(""))
        fireEvent.change(inDialog().getByRole("textbox", { name: /Year/ }), { target: { value: "4" } })
        state.hold = null
        state.readStatus = 500
        await act(async () => read.release())
        await screen.findByText(/World time recorded\. The latest world times could not be loaded/)
        noDialog()
        expect(screen.getByText(/What you entered after it is kept in the form/)).toBeInTheDocument()
        state.readStatus = 0
        fireEvent.click(screen.getByRole("button", { name: "Load latest" }))
        await waitFor(() => expect(chosen()).toHaveTextContent("t9"))
        await openIt()
        expect(inDialog().getByText(/The time you submitted earlier was recorded: Year 3, Bloom 5/)).toBeInTheDocument()
        expect(inDialog().getByRole("textbox", { name: /Year/ })).toHaveValue("4")
    })
})

describe("WorldTimePicker: scope", () => {
    it("keeps two pickers' dialogs and requests apart", async () => {
        const { server } = setupServer()
        render({ two: true })
        const buttons = await screen.findAllByRole("button", { name: "Record a new time" })
        expect(buttons).toHaveLength(2)
        fireEvent.click(buttons[1]!)
        await screen.findByRole("dialog", { name: "Record a world time" })
        expect(screen.getAllByRole("dialog")).toHaveLength(1)
        fill()
        record()
        await waitFor(() => noDialog())
        expect(screen.getByTestId("chosen-until")).toHaveTextContent("t9")
        expect(chosen()).toHaveTextContent("")
        expect(posts(server)).toHaveLength(1)
        // The other picker's dialog was never opened and holds nothing.
        fireEvent.click((await screen.findAllByRole("button", { name: "Record a new time" }))[0]!)
        expect((await screen.findByRole("textbox", { name: /Year/ }))).toHaveValue("")
    })

    it("never lets a late answer from the previous campaign choose, announce or open anything", async () => {
        const request = deferred()
        const { server } = setupServer({
            post: async () => {
                await request.gate
                return undefined
            },
        })
        render()
        await openIt()
        const spoken = watchAnnouncements()
        fill()
        record()
        await inDialog().findByRole("button", { name: "Recording…" })
        // The caller switches campaign (no navigation); the picker for the new campaign starts afresh.
        // The dialog is modal, so reach the switch the way the page would: through the DOM.
        act(() => {
            screen.getByRole("button", { name: "Switch campaign", hidden: true }).click()
        })
        await waitFor(() => expect(optionNames()).toContain("Other world marker"))
        noDialog()
        await act(async () => request.release())
        await act(async () => {})
        expect(chosen()).toHaveTextContent("")
        expect(spoken).toEqual([])
        noDialog()
        expect(optionNames()).not.toContain("Year 3, Bloom 5")
        expect(posts(server)).toHaveLength(1)
        expect((await trigger()).getAttribute("aria-disabled")).toBe("false")
    })

    it("fails closed when permission is lost: the draft and dialog go, and nothing holds the page", async () => {
        const { state } = setupServer()
        render()
        fireEvent.change(outer().getByRole("textbox", { name: "Note" }), { target: { value: "kept" } })
        await openIt()
        fill()
        state.readStatus = 403
        record()
        expect(await screen.findByText(/You do not have permission to use them/)).toBeInTheDocument()
        noDialog()
        expect(outer().getByRole("textbox", { name: "Note" })).toHaveValue("kept")
        // Nothing is held, so leaving asks nothing.
        fireEvent.click(screen.getByRole("link", { name: "Go away" }))
        expect(await screen.findByText("Away page")).toBeInTheDocument()
    })
})

describe("WorldTimePicker: leaving the page", () => {
    it("asks inside the dialog, treats Escape as Stay, and leaves on Leave", async () => {
        setupServer()
        render()
        await openIt()
        fill()
        fireEvent.click(screen.getByRole("link", { name: "Go away", hidden: true }))
        expect(await inDialog().findByText(/You have entered a time that has not been recorded/)).toBeInTheDocument()
        expect(screen.getAllByRole("dialog")).toHaveLength(1)
        escape()
        await waitFor(() => expect(inDialog().queryByText(/You have entered a time/)).toBeNull())
        expect(inDialog().queryByText(/Discard this time/)).toBeNull()
        expect(screen.queryByText("Away page")).toBeNull()
        expect(inDialog().getByRole("textbox", { name: /Year/ })).toHaveValue("3")
        fireEvent.click(screen.getByRole("link", { name: "Go away", hidden: true }))
        fireEvent.click(await inDialog().findByRole("button", { name: "Leave" }))
        expect(await screen.findByText("Away page")).toBeInTheDocument()
    })

    it("asks in one confirmation about an uncertain request behind a closed dialog", async () => {
        setupServer({ post: (n) => (n === 1 ? { networkError: true } : undefined) })
        render()
        await openIt()
        fill()
        record()
        await inDialog().findByText(/cannot tell whether this was saved/)
        fireEvent.click(inDialog().getByRole("button", { name: "Cancel" }))
        fireEvent.click(inDialog().getByRole("button", { name: "Close and check later" }))
        fireEvent.click(screen.getByRole("link", { name: "Go away" }))
        const ask = await screen.findByRole("dialog", { name: "Leave this page?" })
        expect(ask).toHaveAccessibleDescription(/may already have been recorded/)
        fireEvent.click(within(ask).getByRole("button", { name: "Stay" }))
        await waitFor(() => noDialog())
        expect(screen.getByText(/may or may not have been saved/)).toBeInTheDocument()
        expect(screen.queryByText("Away page")).toBeNull()
    })

    it("lets the page's own guard ask the one question, with no second blocker", async () => {
        setupServer()
        const warn = vi.spyOn(console, "warn").mockImplementation(() => {})
        render({ pageGuard: true })
        fireEvent.change(outer().getByRole("textbox", { name: "Note" }), { target: { value: "dirty outer" } })
        await openIt()
        fill()
        fireEvent.click(screen.getByRole("link", { name: "Go away", hidden: true }))
        const ask = await screen.findByRole("dialog", { name: "Leave the outer page?" })
        // One question: the picker adds none of its own.
        expect(screen.queryByText(/You have entered a time that has not been recorded/)).toBeNull()
        expect(screen.queryByRole("dialog", { name: "Leave this page?" })).toBeNull()
        fireEvent.click(within(ask).getByRole("button", { name: "Stay" }))
        await waitFor(() => expect(screen.queryByRole("dialog", { name: "Leave the outer page?" })).toBeNull())
        expect(inDialog().getByRole("textbox", { name: /Year/ })).toHaveValue("3")
        expect(outer().getByRole("textbox", { name: "Note", hidden: true })).toHaveValue("dirty outer")
        fireEvent.click(screen.getByRole("link", { name: "Go away", hidden: true }))
        fireEvent.click(within(await screen.findByRole("dialog", { name: "Leave the outer page?" })).getByRole("button", { name: "Leave" }))
        expect(await screen.findByText("Away page")).toBeInTheDocument()
        expect(warn.mock.calls.some((call) => String(call[0]).includes("one blocker"))).toBe(false)
    })

    it("holds a page whose own form is clean while the time form has input", async () => {
        setupServer()
        render({ pageGuard: true })
        await openIt()
        fill()
        fireEvent.click(screen.getByRole("link", { name: "Go away", hidden: true }))
        expect(await screen.findByRole("dialog", { name: "Leave the outer page?" })).toBeInTheDocument()
    })
})

// The caller changes the controlled selection away and back: each is a separate observed change.
const callerAwayAndBack = () => {
    fireEvent.click(screen.getByRole("button", { name: "Caller sets t1", hidden: true }))
    fireEvent.click(screen.getByRole("button", { name: "Caller clears", hidden: true }))
}
const NOT_CHOSEN = /It was not chosen because the selection was changed while it was being recorded/

describe("WorldTimePicker: selection revisions", () => {
    it("is withdrawn by a caller change away and back during the request", async () => {
        const request = deferred()
        const { server } = setupServer({
            post: async () => {
                await request.gate
                return undefined
            },
        })
        render()
        await openIt()
        fill()
        record()
        await inDialog().findByRole("button", { name: "Recording…" })
        callerAwayAndBack()
        await act(async () => request.release())
        expect(await screen.findByText(NOT_CHOSEN)).toBeInTheDocument()
        await waitFor(() => expect(optionNames()).toContain("Year 3, Bloom 5"))
        expect(chosen()).toHaveTextContent("")
        expect(posts(server)).toHaveLength(1)
    })

    it("is withdrawn by a caller change away and back during the read", async () => {
        const { state } = setupServer()
        render()
        await openIt()
        fill()
        const read = deferred()
        state.hold = read.gate
        record()
        await waitFor(() => expect(inDialog().getByRole("textbox", { name: /Year/ })).toHaveValue(""))
        callerAwayAndBack()
        state.hold = null
        await act(async () => read.release())
        expect(await screen.findByText(NOT_CHOSEN)).toBeInTheDocument()
        expect(chosen()).toHaveTextContent("")
    })

    it("is not restored by a failed read and its recovery", async () => {
        const { server, state } = setupServer()
        render()
        await openIt()
        fill()
        state.readStatus = 500
        record()
        await screen.findByText(/could not be loaded/)
        callerAwayAndBack()
        state.readStatus = 0
        fireEvent.click(screen.getByRole("button", { name: "Load latest" }))
        expect(await screen.findByText(NOT_CHOSEN)).toBeInTheDocument()
        expect(chosen()).toHaveTextContent("")
        expect(posts(server)).toHaveLength(1)
    })

    it("does not invalidate itself when it chooses, and one recording's change does not touch the next", async () => {
        const { server } = setupServer()
        render()
        await openIt()
        fill()
        record()
        await waitFor(() => expect(chosen()).toHaveTextContent("t9"))
        expect(screen.queryByText(NOT_CHOSEN)).toBeNull()
        // A later change by the caller; the next recording begins after it and is chosen.
        fireEvent.click(screen.getByRole("button", { name: "Caller sets t1" }))
        expect(chosen()).toHaveTextContent("t1")
        expect(screen.queryByText(NOT_CHOSEN)).toBeNull()
        await openIt()
        fill("4")
        record()
        await waitFor(() => expect(chosen()).toHaveTextContent("t9"))
        expect(posts(server)).toHaveLength(2)
    })

    it("keeps an invalidated recording from choosing, and the next recording is judged on its own", async () => {
        const { state } = setupServer()
        render()
        await openIt()
        fill()
        const read = deferred()
        state.hold = read.gate
        record()
        await waitFor(() => expect(inDialog().getByRole("textbox", { name: /Year/ })).toHaveValue(""))
        callerAwayAndBack()
        state.hold = null
        await act(async () => read.release())
        await screen.findByText(NOT_CHOSEN)
        expect(chosen()).toHaveTextContent("")
        // The same time id comes back from a second recording: it is not mistaken for the first.
        await openIt()
        fill("4")
        record()
        await waitFor(() => expect(chosen()).toHaveTextContent("t9"))
    })
})

describe("WorldTimePicker: a perspective change at the same path", () => {
    beforeEach(() => {
        setCommittedPerspective({ characterId: null, defaultCharacterId: null, authorized: new Set(["char-b"]) })
    })
    afterEach(() => setCommittedPerspective(null))

    it("is held by the picker's own blocker as one question; Stay keeps the draft and the path", async () => {
        setupServer()
        const { router } = render()
        await openIt()
        fill()
        const before = router.state.location
        fireEvent.click(screen.getByRole("link", { name: "Switch perspective", hidden: true }))
        expect(await inDialog().findByText(/You have entered a time that has not been recorded/)).toBeInTheDocument()
        expect(screen.getAllByRole("dialog")).toHaveLength(1)
        expect(router.state.location).toBe(before)
        fireEvent.click(inDialog().getByRole("button", { name: "Stay" }))
        await waitFor(() => expect(inDialog().queryByText(/You have entered a time/)).toBeNull())
        expect(inDialog().getByRole("textbox", { name: /Year/ })).toHaveValue("3")
        expect(router.state.location).toBe(before)
    })

    it("is held by the page's guard as the one question when the page has one", async () => {
        setupServer()
        render({ pageGuard: true })
        fireEvent.change(outer().getByRole("textbox", { name: "Note" }), { target: { value: "dirty outer" } })
        await openIt()
        fill()
        fireEvent.click(screen.getByRole("link", { name: "Switch perspective", hidden: true }))
        const ask = await screen.findByRole("dialog", { name: "Leave the outer page?" })
        expect(screen.queryByRole("dialog", { name: "Leave this page?" })).toBeNull()
        expect(screen.queryByText(/You have entered a time that has not been recorded/)).toBeNull()
        fireEvent.click(within(ask).getByRole("button", { name: "Stay" }))
        await waitFor(() => expect(screen.queryByRole("dialog", { name: "Leave the outer page?" })).toBeNull())
        expect(inDialog().getByRole("textbox", { name: /Year/ })).toHaveValue("3")
    })
})

describe("WorldTimePicker: one modal while the page asks to leave", () => {
    const openCount = () => document.querySelectorAll("dialog[open]").length

    it("steps the picker dialog aside for the page's question and restores it on Stay", async () => {
        setupServer()
        render({ pageGuard: true })
        await openIt()
        fill()
        const year = inDialog().getByRole("textbox", { name: /Year/ })
        year.focus()
        fireEvent.click(screen.getByRole("link", { name: "Go away", hidden: true }))
        const ask = await screen.findByRole("dialog", { name: "Leave the outer page?" })
        await waitFor(() => expect(openCount()).toBe(1))
        expect(ask).toHaveAttribute("open")
        fireEvent.click(within(ask).getByRole("button", { name: "Stay" }))
        await waitFor(() => expect(screen.queryByRole("dialog", { name: "Leave the outer page?" })).toBeNull())
        expect(openCount()).toBe(1)
        expect(dialog()).toHaveAttribute("open")
        expect(inDialog().getByRole("textbox", { name: /Year/ })).toHaveValue("3")
        // Focus is back inside the picker dialog, on the control that had it.
        expect(year).toHaveFocus()
        expect(inDialog().queryByText(/Discard this time|You have entered a time/)).toBeNull()
    })

    it("treats Escape on the page's question as Stay, with no further prompt", async () => {
        setupServer()
        render({ pageGuard: true })
        await openIt()
        fill()
        fireEvent.click(screen.getByRole("link", { name: "Go away", hidden: true }))
        const ask = await screen.findByRole("dialog", { name: "Leave the outer page?" })
        fireEvent(ask, new Event("cancel", { cancelable: true }))
        await waitFor(() => expect(screen.queryByRole("dialog", { name: "Leave the outer page?" })).toBeNull())
        expect(openCount()).toBe(1)
        expect(inDialog().queryByText(/Discard this time|You have entered a time|Leave this page/)).toBeNull()
        expect(inDialog().getByRole("textbox", { name: /Year/ })).toHaveValue("3")
        expect(screen.queryByText("Away page")).toBeNull()
    })

    it("leaves once on Leave, without the picker taking focus back", async () => {
        setupServer()
        const { router } = render({ pageGuard: true })
        const arrivals: string[] = []
        router.subscribe((state) => arrivals.push(state.location.pathname))
        await openIt()
        fill()
        fireEvent.click(screen.getByRole("link", { name: "Go away", hidden: true }))
        const ask = await screen.findByRole("dialog", { name: "Leave the outer page?" })
        fireEvent.click(within(ask).getByRole("button", { name: "Leave" }))
        expect(await screen.findByText("Away page")).toBeInTheDocument()
        expect(openCount()).toBe(0)
        expect(arrivals.filter((path) => path === "/away")).toHaveLength(1)
        expect(screen.queryByRole("button", { name: "Record a new time" })).toBeNull()
        expect(screen.queryByRole("textbox", { name: /Year/, hidden: true })).toBeNull()
    })

    it("keeps an uncertain request mounted and recoverable while the question has the screen", async () => {
        setupServer({ post: (n) => (n === 1 ? { networkError: true } : undefined) })
        render({ pageGuard: true })
        await openIt()
        fill()
        record()
        await inDialog().findByText(/cannot tell whether this was saved/)
        fireEvent.click(screen.getByRole("link", { name: "Go away", hidden: true }))
        const ask = await screen.findByRole("dialog", { name: "Leave the outer page?" })
        fireEvent.click(within(ask).getByRole("button", { name: "Stay" }))
        await inDialog().findByText(/cannot tell whether this was saved/)
        fireEvent.click(inDialog().getByRole("button", { name: "Retry" }))
        await waitFor(() => expect(chosen()).toHaveTextContent("t9"))
    })
})

describe("WorldTimePicker: registration and cleanup", () => {
    it("counts several pickers and guards exactly, under StrictMode, and leaves none behind", async () => {
        setupServer()
        const base = navigationRegistryCounts()
        const submit = vi.fn()
        const view = renderAuthoringRoutes({
            initialEntry: "/pick",
            bootstrap: bootstrapWith(),
            routes: [
                {
                    path: "/pick",
                    element: (
                        <StrictMode>
                            <Outer submit={submit} two pageGuard />
                        </StrictMode>
                    ),
                },
                { path: "/away", element: <p>Away page</p> },
            ],
        })
        const [first, second] = await screen.findAllByRole("button", { name: "Record a new time" })
        expect(navigationRegistryCounts()).toEqual({ ...base, pageGuards: base.pageGuards + 1 })
        fireEvent.click(first!)
        await screen.findByRole("dialog", { name: "Record a world time" })
        fill()
        await waitFor(() => expect(navigationRegistryCounts().holds).toBe(base.holds + 1))
        fireEvent.click(within(dialog()).getByRole("button", { name: "Cancel" }))
        fireEvent.click(within(dialog()).getByRole("button", { name: "Discard" }))
        await waitFor(() => expect(navigationRegistryCounts().holds).toBe(base.holds))
        fireEvent.click(second!)
        const dialogs = await screen.findAllByRole("dialog", { name: "Record a world time" })
        expect(dialogs).toHaveLength(1)
        fill()
        await waitFor(() => expect(navigationRegistryCounts().holds).toBe(base.holds + 1))
        fireEvent.click(screen.getByRole("link", { name: "Go away", hidden: true }))
        fireEvent.click(
            within(await screen.findByRole("dialog", { name: "Leave the outer page?" })).getByRole("button", { name: "Leave" }),
        )
        await screen.findByText("Away page")
        expect(navigationRegistryCounts()).toEqual(base)
        view.unmount()
        expect(navigationRegistryCounts()).toEqual(base)
    })
})

describe("WorldTimePicker: a recording that completes while the page's question is open", () => {
    const openCount = () => document.querySelectorAll("dialog[open]").length
    const year = () => screen.getByRole("textbox", { name: /Year/, hidden: true })

    // Submit with the POST held, ask to leave (the picker dialog steps aside), then let the POST succeed
    // with the follow-up read held, all while the question stays open.
    async function postedBehindTheQuestion() {
        const request = deferred()
        const read = deferred()
        const harness = setupServer({
            post: async () => {
                await request.gate
                return undefined
            },
        })
        const view = render({ pageGuard: true })
        await openIt()
        const spoken = watchAnnouncements()
        fill()
        record()
        await inDialog().findByRole("button", { name: "Recording…" })
        fireEvent.click(screen.getByRole("link", { name: "Go away", hidden: true }))
        const ask = await screen.findByRole("dialog", { name: "Leave the outer page?" })
        await waitFor(() => expect(openCount()).toBe(1))

        harness.state.hold = read.gate
        await act(async () => request.release())
        // The confirmation was processed: the form emptied. The question is still the only open modal.
        await waitFor(() => expect(year()).toHaveValue(""))
        return { ...harness, ...view, ask, read, spoken }
    }

    function expectOnlyTheQuestion(ask: HTMLElement) {
        expect(openCount()).toBe(1)
        expect(ask).toHaveAttribute("open")
        expect(screen.getAllByRole("dialog")).toEqual([ask])
        expect(ask.contains(document.activeElement)).toBe(true)
    }

    it("completes behind the question without reopening a modal or taking focus, then Stay shows no finished dialog", async () => {
        const { server, state, ask, read, spoken, submit } = await postedBehindTheQuestion()
        expectOnlyTheQuestion(ask)
        expect(chosen()).toHaveTextContent("")

        // The read answers with the created time; wait until the completion was visibly processed.
        state.hold = null
        await act(async () => read.release())
        await waitFor(() => expect(chosen()).toHaveTextContent("t9"))
        await waitFor(() => expect(spoken.filter((x) => x === "World time recorded")).toHaveLength(1))
        expectOnlyTheQuestion(ask)
        expect(posts(server)).toHaveLength(1)
        expect(submit).not.toHaveBeenCalled()
        expect(server.calls.filter((call) => /clock/.test(call.path))).toHaveLength(0)

        fireEvent.click(within(ask).getByRole("button", { name: "Stay" }))
        await waitFor(() => expect(screen.queryByRole("dialog", { name: "Leave the outer page?" })).toBeNull())
        // The completed, pristine recording dialog is not brought back.
        expect(openCount()).toBe(0)
        expect(screen.queryByRole("dialog")).toBeNull()
        expect(screen.queryByText("Away page")).toBeNull()
        expect(chosen()).toHaveTextContent("t9")
        expect(posts(server)).toHaveLength(1)
        // And it is an ordinary, empty dialog the next time it is asked for.
        await openIt()
        expect(inDialog().getByRole("textbox", { name: /Year/ })).toHaveValue("")
    })

    it("leaves once after the completion, with no focus returned to the left page", async () => {
        const { state, ask, read, router } = await postedBehindTheQuestion()
        const arrivals: string[] = []
        router.subscribe((next) => arrivals.push(next.location.pathname))
        state.hold = null
        await act(async () => read.release())
        await waitFor(() => expect(chosen()).toHaveTextContent("t9"))
        expectOnlyTheQuestion(ask)

        fireEvent.click(within(ask).getByRole("button", { name: "Leave" }))
        expect(await screen.findByText("Away page")).toBeInTheDocument()
        expect(openCount()).toBe(0)
        expect(arrivals.filter((path) => path === "/away")).toHaveLength(1)
        expect(screen.queryByRole("button", { name: "Record a new time" })).toBeNull()
        expect(document.body.contains(document.activeElement) ? document.activeElement?.tagName !== "BUTTON" : true).toBe(true)
    })

    it("keeps a newer draft entered meanwhile: Stay restores it, marked unrecorded", async () => {
        const { server, state, ask, read, spoken } = await postedBehindTheQuestion()
        // Entered while the dialog is stepped aside and the read is still held.
        fireEvent.change(year(), { target: { value: "4" } })
        state.hold = null
        await act(async () => read.release())
        // The recorded time is chosen on the form behind; the dialog is kept (not closed), still stepped aside.
        await waitFor(() => expect(chosen()).toHaveTextContent("t9"))
        await act(async () => {})
        expectOnlyTheQuestion(ask)
        expect(spoken).not.toContain("World time recorded")

        fireEvent.click(within(ask).getByRole("button", { name: "Stay" }))
        await waitFor(() => expect(screen.queryByRole("dialog", { name: "Leave the outer page?" })).toBeNull())
        expect(openCount()).toBe(1)
        expect(dialog()).toHaveAttribute("open")
        expect(inDialog().getByRole("textbox", { name: /Year/ })).toHaveValue("4")
        expect(inDialog().getByText(/The time you submitted earlier was recorded: Year 3, Bloom 5\. What is in the form now has not been recorded/)).toBeInTheDocument()
        expect(posts(server)).toHaveLength(1)
        expect(chosen()).toHaveTextContent("t9")
    })
})
