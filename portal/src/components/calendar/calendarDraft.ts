import type { FieldError } from "../authoring/feedback"
import { validateDescription, validateName } from "../../utils/authoringValidation"
import {
    DAYS_PER_WEEK_MAX,
    DAY_COUNT_MAX,
    DEFAULT_DAY_COUNT,
    EPOCH_LABEL_MAX,
    MONTHS_MAX,
    MONTH_NAME_MAX,
    parseWhole,
} from "../../utils/worldTimeForm"

// The unsaved state of the calendar being created: the calendar's own fields, its committed months
// in order, the Add a month panel (always available until the calendar is full), and at most one
// open row editor. Pure, so it can be tested without React. Nothing here is sent anywhere; the page builds
// the one creation request from the committed months only.

// A committed month. `key` is stable for the life of the draft and never reused; it is not the
// position and never reaches the request, so removing a row cannot move another row's input,
// error or focus.
export interface DraftMonth {
    key: string
    name: string
    dayCount: string
}

// The values of an open month form, applied to the draft only on purpose.
export interface MonthBuffer {
    name: string
    dayCount: string
    errors: FieldError[]
}

export interface CalendarDraft {
    name: string
    description: string
    epochLabel: string
    daysPerWeek: string
    months: DraftMonth[]
    composer: MonthBuffer | null
    editing: { key: string; buffer: MonthBuffer } | null
    nextKey: number
    // Any change was made (even one later undone), which is what the leave guard asks about.
    touched: boolean
    // Why a form could not be opened, shown beside the forms.
    notice: string | null
}

export type CalendarField = "name" | "description" | "epochLabel" | "daysPerWeek"

export type DraftAction =
    | { type: "field"; field: CalendarField; value: string }
    | { type: "composer"; patch: Partial<Pick<MonthBuffer, "name" | "dayCount">> }
    | { type: "applyComposer" }
    | { type: "openEdit"; key: string }
    | { type: "edit"; patch: Partial<Pick<MonthBuffer, "name" | "dayCount">> }
    | { type: "applyEdit" }
    | { type: "cancelEdit" }
    | { type: "remove"; key: string }

export const MONTHS_ID = "calendar-months"
export const COMPOSER_NAME_ID = "calendar-composer-name"
export const COMPOSER_DAYS_ID = "calendar-composer-days"
export const monthNameId = (key: string) => `calendar-month-${key}-name`
export const monthDaysId = (key: string) => `calendar-month-${key}-days`
export const monthEditId = (key: string) => `calendar-month-${key}-edit`

const MONTH_FIELD = /^calendar-month-(.+)-(name|days|edit)$/

// The month a field id belongs to, or null.
export function monthKeyOfField(fieldId: string): string | null {
    return MONTH_FIELD.exec(fieldId)?.[1] ?? null
}

export type CalendarStep = "basics" | "months" | "review"

// The step whose panel holds a field.
export function stepForField(fieldId: string): CalendarStep {
    if (
        fieldId === MONTHS_ID ||
        fieldId.startsWith("calendar-composer-") ||
        MONTH_FIELD.test(fieldId)
    ) {
        return "months"
    }
    return "basics"
}

const blankBuffer = (): MonthBuffer => ({ name: "", dayCount: DEFAULT_DAY_COUNT, errors: [] })

// One blank 30-day month, its form already open, as the page has always started.
export function initialDraft(): CalendarDraft {
    return {
        name: "",
        description: "",
        epochLabel: "",
        daysPerWeek: "",
        months: [{ key: "m1", name: "", dayCount: DEFAULT_DAY_COUNT }],
        composer: blankBuffer(),
        editing: { key: "m1", buffer: blankBuffer() },
        nextKey: 2,
        touched: false,
        notice: null,
    }
}

// ---- month rules (shared by Apply and by whole-draft validation) ----

type NameProblem = "empty" | "long" | "duplicate"

function nameProblem(name: string, otherNames: readonly string[]): NameProblem | null {
    const trimmed = name.trim()
    if (trimmed === "") return "empty"
    if (trimmed.length > MONTH_NAME_MAX) return "long"
    const folded = trimmed.toLowerCase()
    return otherNames.some((other) => other.trim().toLowerCase() === folded) ? "duplicate" : null
}

function daysProblem(dayCount: string): boolean {
    const days = parseWhole(dayCount)
    return days === null || days === "invalid" || days < 1 || days > DAY_COUNT_MAX
}

function checkBuffer(
    buffer: MonthBuffer,
    otherNames: readonly string[],
    nameId: string,
    daysId: string,
): FieldError[] {
    const errors: FieldError[] = []
    const problem = nameProblem(buffer.name, otherNames)
    if (problem === "empty") errors.push({ fieldId: nameId, message: "Enter a name for the month." })
    else if (problem === "long") {
        errors.push({
            fieldId: nameId,
            message: `A month name must be ${MONTH_NAME_MAX} characters or fewer.`,
        })
    } else if (problem === "duplicate") {
        errors.push({
            fieldId: nameId,
            message: "Another month already has this name. Month names must be unique.",
        })
    }
    if (daysProblem(buffer.dayCount)) {
        errors.push({
            fieldId: daysId,
            message: `Days must be a whole number from 1 to ${DAY_COUNT_MAX}.`,
        })
    }
    return errors
}

// ---- unapplied forms ----

export type UnappliedForm = { kind: "composer" } | { kind: "edit"; key: string; position: number }

// The open month forms holding values that are not in the draft: a composer with a name or a
// changed day count, or an editor that differs from its row. An untouched form holds nothing.
export function unappliedForms(draft: CalendarDraft): UnappliedForm[] {
    const found: UnappliedForm[] = []
    const { composer, editing } = draft
    if (composer !== null && (composer.name.trim() !== "" || composer.dayCount !== DEFAULT_DAY_COUNT)) {
        found.push({ kind: "composer" })
    }
    if (editing !== null) {
        const index = draft.months.findIndex((m) => m.key === editing.key)
        const row = draft.months[index]
        if (row !== undefined && (editing.buffer.name !== row.name || editing.buffer.dayCount !== row.dayCount)) {
            found.push({ kind: "edit", key: editing.key, position: index + 1 })
        }
    }
    return found
}

// The row editor with unapplied values: opening another row's editor would discard it. The Add
// a month panel never blocks, because it is not replaced by anything.
export function blockingForm(draft: CalendarDraft): Extract<UnappliedForm, { kind: "edit" }> | null {
    const found = unappliedForms(draft).find((f) => f.kind === "edit")
    return found?.kind === "edit" ? found : null
}

function blockedNotice(form: Extract<UnappliedForm, { kind: "edit" }>): string {
    return `Apply or cancel your changes to month ${form.position} first.`
}

// ---- the reducer ----

export function calendarReducer(draft: CalendarDraft, action: DraftAction): CalendarDraft {
    switch (action.type) {
        case "field":
            return { ...draft, [action.field]: action.value, touched: true, notice: null }

        case "composer": {
            if (draft.composer === null) return draft
            return {
                ...draft,
                composer: { ...draft.composer, ...action.patch, errors: [] },
                touched: true,
                notice: null,
            }
        }
        case "applyComposer": {
            const composer = draft.composer
            if (composer === null) return draft
            const errors = checkBuffer(
                composer,
                draft.months.map((m) => m.name),
                COMPOSER_NAME_ID,
                COMPOSER_DAYS_ID,
            )
            if (errors.length > 0) return { ...draft, composer: { ...composer, errors }, notice: null }
            const months = [
                ...draft.months,
                { key: `m${draft.nextKey}`, name: composer.name.trim(), dayCount: composer.dayCount.trim() },
            ]
            return {
                ...draft,
                months,
                // The panel stays ready for the next month, until the calendar is full.
                composer: months.length >= MONTHS_MAX ? null : blankBuffer(),
                nextKey: draft.nextKey + 1,
                touched: true,
                notice: null,
            }
        }
        case "openEdit": {
            const row = draft.months.find((m) => m.key === action.key)
            if (row === undefined || draft.editing?.key === action.key) return draft
            const blocked = blockingForm(draft)
            if (blocked !== null) return { ...draft, notice: blockedNotice(blocked) }
            return {
                ...draft,
                editing: { key: row.key, buffer: { name: row.name, dayCount: row.dayCount, errors: [] } },
                notice: null,
            }
        }
        case "edit": {
            if (draft.editing === null) return draft
            return {
                ...draft,
                editing: {
                    key: draft.editing.key,
                    buffer: { ...draft.editing.buffer, ...action.patch, errors: [] },
                },
                touched: true,
                notice: null,
            }
        }
        case "applyEdit": {
            const editing = draft.editing
            if (editing === null) return draft
            const errors = checkBuffer(
                editing.buffer,
                draft.months.filter((m) => m.key !== editing.key).map((m) => m.name),
                monthNameId(editing.key),
                monthDaysId(editing.key),
            )
            if (errors.length > 0) {
                return { ...draft, editing: { ...editing, buffer: { ...editing.buffer, errors } }, notice: null }
            }
            return {
                ...draft,
                months: draft.months.map((m) =>
                    m.key === editing.key
                        ? { ...m, name: editing.buffer.name.trim(), dayCount: editing.buffer.dayCount.trim() }
                        : m,
                ),
                editing: null,
                touched: true,
                notice: null,
            }
        }
        case "cancelEdit":
            return { ...draft, editing: null, notice: null }

        case "remove": {
            if (draft.months.length <= 1 || !draft.months.some((m) => m.key === action.key)) return draft
            return {
                ...draft,
                months: draft.months.filter((m) => m.key !== action.key),
                // Room again after the calendar was full: the Add a month panel comes back.
                composer: draft.composer ?? blankBuffer(),
                // A form for a month that is gone goes with it.
                editing: draft.editing?.key === action.key ? null : draft.editing,
                touched: true,
                notice: null,
            }
        }
    }
}

// A month named for assistive technology and announcements.
export function monthLabel(position: number, name: string): string {
    return name.trim() === "" ? `month ${position} (no name yet)` : `month ${position}, ${name.trim()}`
}

// ---- summaries ----

export type YearLength =
    | { kind: "known"; days: number }
    // Positions (1-based) of months whose day count is not a usable number.
    | { kind: "unknown"; positions: number[] }

// The year is the sum of the committed months' days. It is a total only when every one counts.
export function yearLength(draft: CalendarDraft): YearLength {
    let total = 0
    const positions: number[] = []
    draft.months.forEach((month, index) => {
        const days = parseWhole(month.dayCount)
        if (days === null || days === "invalid" || days < 1 || days > DAY_COUNT_MAX) {
            positions.push(index + 1)
        } else {
            total += days
        }
    })
    return positions.length === 0 ? { kind: "known", days: total } : { kind: "unknown", positions }
}

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`

export function monthCountText(draft: CalendarDraft): string {
    return plural(draft.months.length, "month", "months")
}

export function yearLengthText(draft: CalendarDraft): string {
    const length = yearLength(draft)
    if (length.kind === "known") return `Year length: ${plural(length.days, "day", "days")}.`
    const which =
        length.positions.length === 1
            ? `month ${length.positions[0]} needs`
            : `months ${length.positions.join(", ")} need`
    return `Year length not known yet: ${which} a day count from 1 to ${DAY_COUNT_MAX}.`
}

// ---- whole-draft validation ----

// Every problem in the draft, whichever step shows it, in the order the steps appear. Unfinished
// month forms are problems too: their values would otherwise be silently left out.
export function validateCalendarDraft(draft: CalendarDraft): FieldError[] {
    const errors: FieldError[] = []
    if (draft.name.trim() === "") {
        errors.push({ fieldId: "calendar-name", message: "Enter a name for the calendar." })
    } else {
        const problem = validateName(draft.name, "Calendar name")
        if (problem !== null) errors.push({ fieldId: "calendar-name", message: problem })
    }
    const description = validateDescription(draft.description)
    if (description !== null) errors.push({ fieldId: "calendar-description", message: description })
    if (draft.epochLabel.trim().length > EPOCH_LABEL_MAX) {
        errors.push({
            fieldId: "calendar-epoch",
            message: `Epoch must be ${EPOCH_LABEL_MAX} characters or fewer.`,
        })
    }
    const dpw = parseWhole(draft.daysPerWeek)
    if (dpw === "invalid" || (dpw !== null && (dpw < 1 || dpw > DAYS_PER_WEEK_MAX))) {
        errors.push({
            fieldId: "calendar-days-per-week",
            message: `Days per week must be a whole number from 1 to ${DAYS_PER_WEEK_MAX}, or empty.`,
        })
    }

    if (draft.months.length < 1 || draft.months.length > MONTHS_MAX) {
        errors.push({
            fieldId: MONTHS_ID,
            message: `A calendar needs between 1 and ${MONTHS_MAX} months.`,
        })
    }
    const unapplied = unappliedForms(draft)
    const editedKey = unapplied.find((f) => f.kind === "edit")?.key
    const seen: string[] = []
    draft.months.forEach((month, index) => {
        const position = index + 1
        const problem = nameProblem(month.name, seen)
        // An unapplied edit of this row reports itself instead (same field).
        if (month.key !== editedKey) {
            if (problem === "empty") {
                errors.push({ fieldId: monthNameId(month.key), message: `Enter a name for month ${position}.` })
            } else if (problem === "long") {
                errors.push({
                    fieldId: monthNameId(month.key),
                    message: `Month ${position}'s name must be ${MONTH_NAME_MAX} characters or fewer.`,
                })
            } else if (problem === "duplicate") {
                errors.push({
                    fieldId: monthNameId(month.key),
                    message: `Month ${position} repeats a name. Month names must be unique.`,
                })
            }
        }
        seen.push(month.name)
        if (daysProblem(month.dayCount)) {
            errors.push({
                fieldId: monthDaysId(month.key),
                message: `Month ${position} needs a day count from 1 to ${DAY_COUNT_MAX}.`,
            })
        }
    })
    for (const form of unapplied) {
        errors.push(
            form.kind === "composer"
                ? {
                      fieldId: COMPOSER_NAME_ID,
                      message: "You started adding a month that is not in the draft yet. Add it to the draft or clear it.",
                  }
                : {
                      fieldId: monthNameId(form.key),
                      message: `Month ${form.position} has changes that are not applied. Apply or cancel them.`,
                  },
        )
    }
    // One entry per field, so the summary never has two links to the same control.
    return errors.filter((e, i) => errors.findIndex((o) => o.fieldId === e.fieldId) === i)
}
