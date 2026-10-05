import { describe, expect, it } from "vitest"
import type { Calendar } from "../types/worldTime"
import {
    EMPTY_CALENDAR_FORM,
    emptyWorldTimeForm,
    parseWhole,
    toCalendarBody,
    toWorldTimeBody,
    validateCalendarForm,
    validateWorldTimeForm,
} from "./worldTimeForm"

const CALENDAR: Calendar = {
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

const ids = (errors: { fieldId: string }[]) => errors.map((e) => e.fieldId)

describe("parseWhole", () => {
    it("parses integers and distinguishes empty from invalid", () => {
        expect(parseWhole("42")).toBe(42)
        expect(parseWhole(" -7 ")).toBe(-7)
        expect(parseWhole("")).toBeNull()
        expect(parseWhole("  ")).toBeNull()
        expect(parseWhole("1.5")).toBe("invalid")
        expect(parseWhole("abc")).toBe("invalid")
    })
})

describe("calendar form", () => {
    it("requires a name and valid months", () => {
        const errors = validateCalendarForm({
            ...EMPTY_CALENDAR_FORM,
            months: [
                { name: "", dayCount: "30" },
                { name: "Frost", dayCount: "0" },
                { name: "frost", dayCount: "10" },
            ],
        })
        expect(ids(errors)).toEqual([
            "calendar-name",
            "calendar-month-0-name",
            "calendar-month-1-days",
            "calendar-month-2-name",
        ])
    })

    it("rejects an out-of-range days-per-week and accepts empty", () => {
        const base = { ...EMPTY_CALENDAR_FORM, name: "C", months: [{ name: "A", dayCount: "5" }] }
        expect(ids(validateCalendarForm({ ...base, daysPerWeek: "31" }))).toEqual([
            "calendar-days-per-week",
        ])
        expect(validateCalendarForm({ ...base, daysPerWeek: "" })).toEqual([])
    })

    it("builds a trimmed body with numbers and nulls", () => {
        expect(
            toCalendarBody({
                name: " Common ",
                description: " ",
                daysPerWeek: "7",
                epochLabel: " Founding ",
                months: [{ name: " Frost ", dayCount: "30" }],
            }),
        ).toEqual({
            name: "Common",
            description: null,
            days_per_week: 7,
            epoch_label: "Founding",
            months: [{ name: "Frost", day_count: 30 }],
        })
    })
})

describe("world-time form", () => {
    const form = (over: object) => ({ ...emptyWorldTimeForm([CALENDAR]), ...over })

    it("starts in calendar mode with a single calendar preselected, narrative when none", () => {
        expect(emptyWorldTimeForm([CALENDAR]).mode).toBe("calendar")
        expect(emptyWorldTimeForm([CALENDAR]).calendarId).toBe("cal-1")
        expect(emptyWorldTimeForm([]).mode).toBe("narrative")
    })

    it("requires a year and keeps finer components consistent", () => {
        expect(ids(validateWorldTimeForm(form({ year: "" }), [CALENDAR]))).toEqual(["time-year"])
        expect(ids(validateWorldTimeForm(form({ year: "3", day: "2" }), [CALENDAR]))).toContain(
            "time-month",
        )
        expect(
            ids(validateWorldTimeForm(form({ year: "3", month: "1", hour: "4" }), [CALENDAR])),
        ).toContain("time-day")
        expect(
            ids(validateWorldTimeForm(form({ year: "3", month: "1", day: "2", minute: "5" }), [CALENDAR])),
        ).toContain("time-hour")
    })

    it("checks month, day, hour and minute ranges against the chosen calendar", () => {
        expect(
            ids(validateWorldTimeForm(form({ year: "1", month: "3" }), [CALENDAR])),
        ).toContain("time-month")
        expect(
            ids(validateWorldTimeForm(form({ year: "1", month: "2", day: "29" }), [CALENDAR])),
        ).toContain("time-day")
        expect(
            validateWorldTimeForm(form({ year: "1", month: "2", day: "28", hour: "23", minute: "59" }), [
                CALENDAR,
            ]),
        ).toEqual([])
        expect(
            ids(validateWorldTimeForm(form({ year: "1", month: "1", day: "1", hour: "24" }), [CALENDAR])),
        ).toContain("time-hour")
    })

    it("requires a label and an anchor for a narrative time", () => {
        expect(ids(validateWorldTimeForm(form({ mode: "narrative" }), [CALENDAR]))).toEqual([
            "time-label",
            "time-after",
        ])
        expect(
            validateWorldTimeForm(form({ mode: "narrative", label: "Dusk", afterId: "t1" }), [CALENDAR]),
        ).toEqual([])
    })

    it("builds calendar and narrative bodies without empty components", () => {
        expect(
            toWorldTimeBody(form({ year: "-3", month: "2", approximate: true })),
        ).toEqual({ calendar_id: "cal-1", year: -3, month_number: 2, approximate: true })
        expect(
            toWorldTimeBody(
                form({ mode: "narrative", label: " Dusk ", afterId: "t1", beforeId: "t2" }),
            ),
        ).toEqual({ label: "Dusk", after_world_time_id: "t1", before_world_time_id: "t2" })
        expect(toWorldTimeBody(form({ mode: "narrative", label: "x", afterId: "t1" }))).toEqual({
            label: "x",
            after_world_time_id: "t1",
        })
    })
})
