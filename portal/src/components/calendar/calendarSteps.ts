import type { CalendarStep } from "./calendarDraft"

// The three local steps of creating a calendar. They are presentation over one unsaved draft:
// choosing one changes the address (`?section=`) and nothing else, none gates another, and none is
// a lifecycle status or a submission for review.

export interface CalendarStepDef {
    key: CalendarStep
    label: string
    purpose: string
}

export const CALENDAR_STEPS: readonly CalendarStepDef[] = [
    {
        key: "basics",
        label: "Basics",
        purpose: "Name the calendar and say how it counts years and weeks.",
    },
    {
        key: "months",
        label: "Months",
        purpose: "List the months in order. The days in each month add up to the length of a year.",
    },
    {
        key: "review",
        label: "Review & create",
        purpose: "Check the calendar before creating it. Nothing has been saved or sent for review yet.",
    },
]

export const calendarStepHeadingId = (step: CalendarStep) => `calendar-step-${step}`
