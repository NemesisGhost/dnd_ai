import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../../test/authoringHarness"
import type { Calendar, WorldTimeItem } from "../../types/worldTime"
import { WorldTimeForm } from "./WorldTimeForm"

// C09-S01: the form reads existing points as the World times page does, says how a calendar date will be
// recorded, and never leaves a value behind a field that does not show it.

const TIMES = /\/campaigns\/[^/]+\/world-times/

const COMMON: Calendar = {
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
const SHORT: Calendar = {
    ...COMMON,
    calendar_id: "cal-2",
    code: "short",
    name: "Short Count",
    epoch_label: null,
    months: [{ month_number: 1, name: "Frost", day_count: 20 }],
}
const point = (id: string, over: Partial<WorldTimeItem>): WorldTimeItem => ({
    world_time_id: id,
    calendar_id: "cal-1",
    year: 3,
    month_number: 2,
    day: 5,
    hour: 9,
    minute: 0,
    label: null,
    precision: "exact",
    sort_key: 1,
    display: "Year 3 (Founding), Bloom 5",
    ...over,
})
const MORNING = point("t-am", {})
const AFTERNOON = point("t-pm", { hour: 14 })
const NARRATIVE = point("t-n", {
    calendar_id: null,
    year: null,
    month_number: null,
    day: null,
    hour: null,
    minute: null,
    label: "The sack of Vael",
    precision: "narrative",
    display: "The sack of Vael",
})

afterEach(() => {
    vi.restoreAllMocks()
})

function renderForm(times: WorldTimeItem[] = [MORNING, AFTERNOON, NARRATIVE]) {
    const server = installMockServer()
    server.on("POST", TIMES, { status: 201, body: { world_time_id: "new", created: true, changed: true } })
    renderAuthoringRoutes({
        initialEntry: "/form",
        bootstrap: bootstrapWith(),
        routes: [
            {
                path: "/form",
                element: (
                    <WorldTimeForm
                        campaignId="c1"
                        calendars={[COMMON, SHORT]}
                        times={times}
                        onCreated={() => {}}
                        onCancel={() => {}}
                    />
                ),
            },
        ],
    })
    return server
}

const field = (name: string | RegExp) => screen.getByRole("textbox", { name })
const month = () => screen.getByRole("combobox", { name: "Month" }) as HTMLSelectElement
const calendar = () => screen.getByRole("combobox", { name: /^Calendar/ })
function enter(values: { calendar?: string; year?: string; month?: string; day?: string; hour?: string; minute?: string }) {
    if (values.calendar !== undefined) fireEvent.change(calendar(), { target: { value: values.calendar } })
    if (values.year !== undefined) fireEvent.change(field(/Year/), { target: { value: values.year } })
    if (values.month !== undefined) fireEvent.change(month(), { target: { value: values.month } })
    if (values.day !== undefined) fireEvent.change(field("Day"), { target: { value: values.day } })
    if (values.hour !== undefined) fireEvent.change(field(/Hour/), { target: { value: values.hour } })
    if (values.minute !== undefined) fireEvent.change(field(/Minute/), { target: { value: values.minute } })
}
const preview = () => screen.queryByText(/Will be recorded as/)
const optionLabels = (name: string) =>
    within(screen.getByRole("combobox", { name: new RegExp(`^${name}`) })).getAllByRole("option").map((o) => o.textContent)

describe("WorldTimeForm: reading existing points (E2, E3)", () => {
    it("labels the after and before choices as the World times page reads each point", async () => {
        renderForm()
        fireEvent.click(await screen.findByRole("radio", { name: /A moment placed after another time/ }))
        const expected = [
            "Choose a time",
            "Common Reckoning: Year 3 (Founding), Bloom 5, 09:00",
            "Common Reckoning: Year 3 (Founding), Bloom 5, 14:00",
            "The sack of Vael",
        ]
        expect(optionLabels("Comes after")).toEqual(expected)
        expect(optionLabels("Comes before")).toEqual(["No later limit", ...expected.slice(1)])
    })
})

describe("WorldTimeForm: how the date will be recorded (E6)", () => {
    it("states the reading and precision once the fields validate, and follows the fields", async () => {
        renderForm()
        await screen.findByRole("combobox", { name: /^Calendar/ })
        expect(preview()).toBeNull()
        enter({ calendar: "cal-1", year: "3", month: "2", day: "5", hour: "14", minute: "0" })
        expect(
            screen.getByText("Will be recorded as: Common Reckoning: Year 3 (Founding), Bloom 5, 14:00. Precision: exact (a specific day)."),
        ).toBeInTheDocument()
        enter({ day: "" , hour: "", minute: "" })
        expect(
            screen.getByText("Will be recorded as: Common Reckoning: Year 3 (Founding), Bloom. Precision: partial (year or month only)."),
        ).toBeInTheDocument()
        enter({ day: "5" })
        fireEvent.click(screen.getByRole("checkbox", { name: "This date is approximate" }))
        expect(screen.getByText(/Precision: approximate \(marked approximate\)\./)).toBeInTheDocument()
        // Not a live region: it is read when reached, not announced on every keystroke.
        expect(preview()!.closest("[aria-live]")).toBeNull()
        expect(preview()).not.toHaveAttribute("role", "status")
        // Invalid fields hide it.
        enter({ day: "99" })
        expect(preview()).toBeNull()
        enter({ day: "5" })
        expect(preview()).not.toBeNull()
        // Narrative mode shows nothing new.
        fireEvent.click(screen.getByRole("radio", { name: /A moment placed after another time/ }))
        expect(preview()).toBeNull()
    })
})

describe("WorldTimeForm: changing the calendar (E8, E16)", () => {
    it("clears a month the new calendar lacks, says so politely, and keeps the visible fields equal to the form", async () => {
        const server = renderForm()
        await screen.findByRole("combobox", { name: /^Calendar/ })
        enter({ calendar: "cal-1", year: "3", month: "2", day: "20", hour: "14", minute: "30" })
        fireEvent.click(screen.getByRole("checkbox", { name: "This date is approximate" }))
        fireEvent.change(field(/Label/), { target: { value: "Feast" } })
        enter({ calendar: "cal-2" })
        expect(month().value).toBe("")
        expect(field("Day")).toHaveValue("")
        expect(field(/Hour/)).toHaveValue("")
        expect(field(/Minute/)).toHaveValue("")
        expect(field(/Year/)).toHaveValue("3")
        expect(screen.getByRole("checkbox", { name: "This date is approximate" })).toBeChecked()
        expect(field(/Label/)).toHaveValue("Feast")
        const note = screen.getByRole("status")
        expect(note).toHaveTextContent(/Short Count has no such month/)
        // Submitting sends exactly what is shown: no month the calendar lacks.
        fireEvent.click(screen.getByRole("button", { name: "Record time" }))
        await waitFor(() => expect(server.callsTo("POST", TIMES)).toHaveLength(1))
        expect(server.callsTo("POST", TIMES)[0]!.body).toEqual({
            calendar_id: "cal-2",
            year: 3,
            approximate: true,
            label: "Feast",
        })
    })

    it("clears only a day the month lacks, keeping the month and valid values", async () => {
        renderForm()
        await screen.findByRole("combobox", { name: /^Calendar/ })
        enter({ calendar: "cal-1", year: "3", month: "1", day: "25", hour: "8" })
        enter({ calendar: "cal-2" })
        expect(month().value).toBe("1")
        expect(field("Day")).toHaveValue("")
        expect(field(/Hour/)).toHaveValue("")
        expect(screen.getByRole("status")).toHaveTextContent(/Day, hour and minute were cleared/)
        enter({ calendar: "cal-1", day: "18", hour: "8" })
        enter({ calendar: "cal-2" })
        expect(month().value).toBe("1")
        expect(field("Day")).toHaveValue("18")
        expect(field(/Hour/)).toHaveValue("8")
        expect(screen.queryByRole("status")).toBeNull()
    })
})
