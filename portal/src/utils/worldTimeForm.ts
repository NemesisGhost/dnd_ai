import type { FieldError } from "../components/authoring/feedback"
import type { Calendar, CreateCalendarBody, CreateWorldTimeBody } from "../types/worldTime"

// Pure validation and body-building for the calendar and world-time forms. The
// server re-validates everything; this only saves a round trip and names the
// field.

export const MONTHS_MAX = 60
export const DAY_COUNT_MAX = 400
export const YEAR_LIMIT = 1_000_000
// Mirrors of the domain limits (domain/world_time.py); the server stays authoritative.
export const DAYS_PER_WEEK_MAX = 30
export const EPOCH_LABEL_MAX = 200
export const MONTH_NAME_MAX = 100
// A new month starts at this many days.
export const DEFAULT_DAY_COUNT = "30"

export interface MonthRow {
    name: string
    dayCount: string
}

export interface CalendarFormValues {
    name: string
    description: string
    daysPerWeek: string
    epochLabel: string
    months: MonthRow[]
}

// A whole number in text form: "" means absent, anything else must be an integer.
export function parseWhole(text: string): number | null | "invalid" {
    const trimmed = text.trim()
    if (trimmed === "") return null
    if (!/^-?\d+$/.test(trimmed)) return "invalid"
    return Number(trimmed)
}

// The request body for a calendar. The draft is validated first (calendarDraft.ts).
export function toCalendarBody(values: CalendarFormValues): CreateCalendarBody {
    const dpw = parseWhole(values.daysPerWeek)
    return {
        name: values.name.trim(),
        description: values.description.trim() === "" ? null : values.description.trim(),
        days_per_week: typeof dpw === "number" ? dpw : null,
        epoch_label: values.epochLabel.trim() === "" ? null : values.epochLabel.trim(),
        months: values.months.map((m) => ({ name: m.name.trim(), day_count: Number(m.dayCount) })),
    }
}

export type WorldTimeMode = "calendar" | "narrative"

export interface WorldTimeFormValues {
    mode: WorldTimeMode
    calendarId: string
    year: string
    month: string
    day: string
    hour: string
    minute: string
    approximate: boolean
    label: string
    afterId: string
    beforeId: string
}

export function emptyWorldTimeForm(calendars: Calendar[]): WorldTimeFormValues {
    return {
        mode: calendars.length > 0 ? "calendar" : "narrative",
        calendarId: calendars.length === 1 ? calendars[0]!.calendar_id : "",
        year: "",
        month: "",
        day: "",
        hour: "",
        minute: "",
        approximate: false,
        label: "",
        afterId: "",
        beforeId: "",
    }
}

function wholeInRange(
    text: string,
    fieldId: string,
    label: string,
    min: number,
    max: number,
    errors: FieldError[],
): void {
    const parsed = parseWhole(text)
    if (parsed === "invalid" || (parsed !== null && (parsed < min || parsed > max))) {
        errors.push({ fieldId, message: `${label} must be a whole number from ${min} to ${max}.` })
    }
}

export function validateWorldTimeForm(
    values: WorldTimeFormValues,
    calendars: Calendar[],
): FieldError[] {
    const errors: FieldError[] = []
    if (values.mode === "calendar") {
        const calendar = calendars.find((c) => c.calendar_id === values.calendarId)
        if (calendar === undefined) {
            errors.push({ fieldId: "time-calendar", message: "Choose a calendar." })
        }
        const year = parseWhole(values.year)
        if (year === null || year === "invalid" || Math.abs(year) > YEAR_LIMIT) {
            errors.push({
                fieldId: "time-year",
                message: `Enter a whole-number year between -${YEAR_LIMIT} and ${YEAR_LIMIT}.`,
            })
        }
        const month = parseWhole(values.month)
        const day = parseWhole(values.day)
        const hour = parseWhole(values.hour)
        const minute = parseWhole(values.minute)
        if (day !== null && month === null) {
            errors.push({ fieldId: "time-month", message: "A day needs a month." })
        }
        if (hour !== null && day === null) {
            errors.push({ fieldId: "time-day", message: "An hour needs a day." })
        }
        if (minute !== null && hour === null) {
            errors.push({ fieldId: "time-hour", message: "A minute needs an hour." })
        }
        if (calendar !== undefined) {
            wholeInRange(values.month, "time-month", "Month", 1, calendar.months.length, errors)
            const selectedMonth = typeof month === "number" ? calendar.months[month - 1] : undefined
            wholeInRange(values.day, "time-day", "Day", 1, selectedMonth?.day_count ?? DAY_COUNT_MAX, errors)
        }
        wholeInRange(values.hour, "time-hour", "Hour", 0, 23, errors)
        wholeInRange(values.minute, "time-minute", "Minute", 0, 59, errors)
    } else {
        if (values.label.trim() === "") {
            errors.push({ fieldId: "time-label", message: "Describe this moment." })
        }
        if (values.afterId === "") {
            errors.push({ fieldId: "time-after", message: "Choose the time it comes after." })
        }
    }
    return errors
}

export function toWorldTimeBody(values: WorldTimeFormValues): CreateWorldTimeBody {
    if (values.mode === "narrative") {
        return {
            label: values.label.trim(),
            after_world_time_id: values.afterId,
            ...(values.beforeId === "" ? {} : { before_world_time_id: values.beforeId }),
        }
    }
    const number = (text: string): number | undefined => {
        const parsed = parseWhole(text)
        return typeof parsed === "number" ? parsed : undefined
    }
    const optional = (key: keyof CreateWorldTimeBody, value: number | undefined) =>
        value === undefined ? {} : { [key]: value }
    return {
        calendar_id: values.calendarId,
        year: number(values.year)!,
        ...optional("month_number", number(values.month)),
        ...optional("day", number(values.day)),
        ...optional("hour", number(values.hour)),
        ...optional("minute", number(values.minute)),
        ...(values.approximate ? { approximate: true } : {}),
        ...(values.label.trim() === "" ? {} : { label: values.label.trim() }),
    }
}

export type CalendarPrecision = "exact" | "partial" | "approximate"

// What the server will derive for a calendar date (domain `calendar_precision`): approximate when the box
// is checked, exact when a day is entered, otherwise partial. For display only; the saved point's own
// precision is authoritative.
export function calendarPrecision(values: WorldTimeFormValues): CalendarPrecision {
    if (values.approximate) return "approximate"
    return parseWhole(values.day) === null ? "partial" : "exact"
}

export const PRECISION_DESCRIPTIONS: Readonly<Record<CalendarPrecision, string>> = {
    exact: "exact (a specific day)",
    partial: "partial (year or month only)",
    approximate: "approximate (marked approximate)",
}

// The values after the calendar was changed to `values.calendarId`: a month the new calendar lacks is
// cleared with the day, hour and minute that depend on it, and a day the month lacks is cleared with its
// hour and minute. Nothing is converted, and a value the new calendar has is kept. `note` says what was
// cleared (null when nothing was).
export function onCalendarChange(
    values: WorldTimeFormValues,
    calendars: Calendar[],
): { values: WorldTimeFormValues; note: string | null } {
    const calendar = calendars.find((c) => c.calendar_id === values.calendarId)
    if (calendar === undefined) return { values, note: null }
    const month = parseWhole(values.month)
    if (typeof month === "number" && (month < 1 || month > calendar.months.length)) {
        const cleared = ["Month"]
        if (values.day.trim() !== "") cleared.push("day")
        if (values.hour.trim() !== "") cleared.push("hour")
        if (values.minute.trim() !== "") cleared.push("minute")
        return {
            values: { ...values, month: "", day: "", hour: "", minute: "" },
            note: `${listNames(cleared)} ${cleared.length === 1 ? "was" : "were"} cleared: ${calendar.name} has no such month.`,
        }
    }
    const day = parseWhole(values.day)
    const selectedMonth = typeof month === "number" ? calendar.months[month - 1] : undefined
    if (typeof day === "number" && selectedMonth !== undefined && day > selectedMonth.day_count) {
        return {
            values: { ...values, day: "", hour: "", minute: "" },
            note: `Day, hour and minute were cleared: ${selectedMonth.name} in ${calendar.name} has no such day.`,
        }
    }
    return { values, note: null }
}

function listNames(names: string[]): string {
    if (names.length === 1) return names[0]!
    return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`
}
