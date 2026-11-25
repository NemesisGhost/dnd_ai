import { describe, expect, it } from "vitest"
import type { Calendar } from "../types/worldTime"
import {
    calendarPrecision,
    emptyWorldTimeForm,
    onCalendarChange,
    parseWhole,
    toCalendarBody,
    toWorldTimeBody,
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

describe("calendar body", () => {
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

const SHORT: Calendar = {
    ...CALENDAR,
    calendar_id: "cal-2",
    name: "Short Count",
    epoch_label: null,
    months: [{ month_number: 1, name: "Frost", day_count: 20 }],
}
const withValues = (over: Partial<ReturnType<typeof emptyWorldTimeForm>>) => ({
    ...emptyWorldTimeForm([CALENDAR]),
    ...over,
})

describe("calendarPrecision (E7)", () => {
    it("is exact with a day, partial without one, and approximate wins", () => {
        expect(calendarPrecision(withValues({ year: "3", month: "2", day: "5" }))).toBe("exact")
        expect(calendarPrecision(withValues({ year: "3", month: "2" }))).toBe("partial")
        expect(calendarPrecision(withValues({ year: "3" }))).toBe("partial")
        expect(calendarPrecision(withValues({ year: "3", month: "2", day: "5", approximate: true }))).toBe(
            "approximate",
        )
        expect(calendarPrecision(withValues({ year: "3", approximate: true }))).toBe("approximate")
    })
})

describe("onCalendarChange (E8)", () => {
    const entered = withValues({
        calendarId: "cal-2",
        year: "3",
        month: "2",
        day: "5",
        hour: "14",
        minute: "30",
        approximate: true,
        label: "Feast",
    })

    it("clears a month the new calendar lacks, with its day, hour and minute", () => {
        const next = onCalendarChange(entered, [CALENDAR, SHORT])
        expect(next.values).toEqual({
            ...entered,
            month: "",
            day: "",
            hour: "",
            minute: "",
        })
        expect(next.note).toMatch(/Short Count has no such month/)
    })

    it("clears a day the month lacks, with its hour and minute, keeping the month", () => {
        const next = onCalendarChange({ ...entered, month: "1", day: "25" }, [CALENDAR, SHORT])
        expect(next.values).toEqual({ ...entered, month: "1", day: "", hour: "", minute: "" })
        expect(next.note).toMatch(/Day, hour and minute were cleared/)
    })

    it("keeps every value the new calendar has and says nothing", () => {
        const next = onCalendarChange({ ...entered, month: "1", day: "20" }, [CALENDAR, SHORT])
        expect(next.values).toEqual({ ...entered, month: "1", day: "20" })
        expect(next.note).toBeNull()
    })
})
