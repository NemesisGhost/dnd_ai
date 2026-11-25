import { act, fireEvent, screen, waitFor, within } from "@testing-library/react"
import { useState } from "react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { sessionBootstrapFixture } from "../../fixtures/sessionBootstrap"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../../test/authoringHarness"
import { WorldTimePicker } from "./WorldTimePicker"

// C09-S01: the picker's options and its kept-input message read a calendar point as the World times page
// does (E1, E4, E11, E14, E15).

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
const point = (id: string, hour: number, over: Record<string, unknown> = {}) => ({
    world_time_id: id,
    calendar_id: "cal-1",
    year: 3,
    month_number: 2,
    day: 5,
    hour,
    minute: 0,
    label: null,
    precision: "exact",
    sort_key: hour,
    display: "Year 3 (Founding), Bloom 5",
    ...over,
})

afterEach(() => {
    vi.restoreAllMocks()
})

function Host() {
    const [when, setWhen] = useState("")
    return <WorldTimePicker campaignId={CAMPAIGN} id="when" label="When" value={when} onChange={setWhen} />
}

function setup(items: unknown[], calendars: unknown[] = [CALENDAR], post?: () => unknown) {
    const server = installMockServer()
    const state = { items, hold: null as Promise<void> | null }
    server.on("GET", TIMES, async () => {
        await state.hold
        return { body: { items: state.items, next_cursor: null } }
    })
    server.on("GET", CALENDARS, { body: { calendars } })
    let posts = 0
    server.on("POST", TIMES, async () => {
        posts += 1
        if (post !== undefined && posts === 1) return post() as never
        state.items = [point("new", 20, { label: "The feast" }), ...items]
        return { status: 201, body: { world_time_id: "new", created: true, changed: true } }
    })
    renderAuthoringRoutes({
        initialEntry: "/pick",
        bootstrap: bootstrapWith(),
        routes: [{ path: "/pick", element: <Host /> }],
    })
    return { server, state }
}

const options = () =>
    within(screen.getByRole("combobox", { name: "When" })).queryAllByRole("option").map((o) => o.textContent)
const dialog = () => screen.getByRole("dialog", { name: "Record a world time" })

describe("WorldTimePicker: how points read", () => {
    it("tells two points on the same day apart (E1) and reads a labelled point as the page does (E4)", async () => {
        setup([
            point("t2", 14, { label: "The feast" }),
            point("t1", 9),
            point("n", 0, { calendar_id: null, year: null, month_number: null, day: null, hour: null, minute: null, label: "Vael", display: "Vael", precision: "narrative" }),
        ])
        await screen.findByRole("combobox", { name: "When" })
        expect(options()).toEqual([
            "Choose a time",
            "Common Reckoning: Year 3 (Founding), Bloom 5, 14:00 — The feast",
            "Common Reckoning: Year 3 (Founding), Bloom 5, 09:00",
            "Vael",
        ])
    })

    it("never invents a calendar or month for a point whose calendar is not loaded (E15)", async () => {
        setup([point("t1", 9, { calendar_id: "gone" })], [CALENDAR])
        await screen.findByRole("combobox", { name: "When" })
        expect(options()).toEqual(["Choose a time", "Year 3 (Founding), Bloom 5, 09:00"])
    })

    it("sends only its two reads when it loads (E14)", async () => {
        const { server } = setup([point("t1", 9)])
        await screen.findByRole("combobox", { name: "When" })
        expect(server.callsTo("GET", TIMES)).toHaveLength(1)
        expect(server.callsTo("GET", CALENDARS)).toHaveLength(1)
        expect(server.callsTo("POST", TIMES)).toHaveLength(0)
    })

    it("names the recorded time in the kept-input message with its reading (E11)", async () => {
        const { state } = setup([point("t1", 9)], [CALENDAR], () => ({ networkError: true }))
        fireEvent.click(await screen.findByRole("button", { name: "Record a new time" }))
        await screen.findByRole("dialog", { name: "Record a world time" })
        const inDialog = () => within(dialog())
        const enter = (year: string, monthNumber: string, day: string, hour: string) => {
            fireEvent.change(inDialog().getByRole("combobox", { name: /^Calendar/ }), { target: { value: "cal-1" } })
            fireEvent.change(inDialog().getByRole("textbox", { name: /Year/ }), { target: { value: year } })
            fireEvent.change(inDialog().getByRole("combobox", { name: "Month" }), { target: { value: monthNumber } })
            fireEvent.change(inDialog().getByRole("textbox", { name: "Day" }), { target: { value: day } })
            fireEvent.change(inDialog().getByRole("textbox", { name: /Hour/ }), { target: { value: hour } })
            fireEvent.change(inDialog().getByRole("textbox", { name: /Label/ }), { target: { value: "The feast" } })
        }
        enter("3", "2", "5", "20")
        fireEvent.click(inDialog().getByRole("button", { name: "Record time" }))
        await inDialog().findByText(/cannot tell whether this was saved/)
        let release: () => void = () => {}
        state.hold = new Promise<void>((resolve) => {
            release = resolve
        })
        fireEvent.click(inDialog().getByRole("button", { name: "Retry" }))
        await waitFor(() => expect(inDialog().getByRole("textbox", { name: /Year/ })).toHaveValue(""))
        fireEvent.change(inDialog().getByRole("textbox", { name: /Year/ }), { target: { value: "4" } })
        state.hold = null
        await act(async () => release())
        expect(
            await inDialog().findByText(
                /The time you submitted earlier was recorded: Common Reckoning: Year 3 \(Founding\), Bloom 5, 20:00 — The feast\. What is in the form now has not been recorded/,
            ),
        ).toBeInTheDocument()
    })

    it("stays dirty after a calendar change cleared values: Escape asks, Keep editing keeps what is left (E9)", async () => {
        setup([point("t1", 9)], [CALENDAR, { ...CALENDAR, calendar_id: "cal-2", name: "Short Count", months: [{ month_number: 1, name: "Frost", day_count: 20 }] }])
        fireEvent.click(await screen.findByRole("button", { name: "Record a new time" }))
        await screen.findByRole("dialog", { name: "Record a world time" })
        const inDialog = () => within(dialog())
        fireEvent.change(inDialog().getByRole("combobox", { name: /^Calendar/ }), { target: { value: "cal-1" } })
        fireEvent.change(inDialog().getByRole("textbox", { name: /Year/ }), { target: { value: "3" } })
        fireEvent.change(inDialog().getByRole("combobox", { name: "Month" }), { target: { value: "2" } })
        fireEvent.change(inDialog().getByRole("combobox", { name: /^Calendar/ }), { target: { value: "cal-2" } })
        expect(inDialog().getByRole("combobox", { name: "Month" })).toHaveValue("")
        fireEvent(dialog(), new Event("cancel", { cancelable: true }))
        expect(inDialog().getByText(/Discard this time/)).toBeInTheDocument()
        fireEvent.click(inDialog().getByRole("button", { name: "Keep editing" }))
        expect(inDialog().getByRole("textbox", { name: /Year/ })).toHaveValue("3")
    })
})
