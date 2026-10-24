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
