import type { Dispatch } from "react"
import { TextField } from "../authoring/fields"
import { DAY_COUNT_MAX, MONTHS_MAX, MONTH_NAME_MAX } from "../../utils/worldTimeForm"
import {
    calendarReducer,
    COMPOSER_DAYS_ID,
    COMPOSER_NAME_ID,
    MONTHS_ID,
    monthCountText,
    monthDaysId,
    monthEditId,
    monthLabel,
    monthNameId,
    unappliedForms,
    yearLengthText,
} from "./calendarDraft"
import type { CalendarDraft, DraftAction } from "./calendarDraft"

const sentence = (text: string) => text.charAt(0).toUpperCase() + text.slice(1)

interface MonthRosterProps {
    draft: CalendarDraft
    dispatch: Dispatch<DraftAction>
    // Message for an input, from this step's own form or the last failed create.
    errorFor: (fieldId: string) => string | null
    requestFocus: (id: string) => void
    announce: (message: string) => void
}

// The compact, ordered roster of the calendar's months. Add opens a small form above the list;
// Edit expands one row. Every action here changes the unsaved draft only: nothing is sent until
// the last step.
export function MonthRoster({ draft, dispatch, errorFor, requestFocus, announce }: MonthRosterProps) {
    const { months, composer, editing } = draft
    const full = months.length >= MONTHS_MAX
    const unapplied = unappliedForms(draft)

    function submitComposer() {
        // The reducer is pure, so the outcome is known before the action is dispatched.
        const action = { type: "applyComposer" } as const
        const next = calendarReducer(draft, action)
        dispatch(action)
        if (next.months.length > months.length) {
            const added = next.months[next.months.length - 1]!
            announce(sentence(`${monthLabel(next.months.length, added.name)}, added to the draft.`))
            requestFocus(next.composer === null ? MONTHS_ID : COMPOSER_NAME_ID)
        } else {
            // A refused month leaves the form open: focus its first invalid field.
            requestFocus(next.composer?.errors[0]?.fieldId ?? COMPOSER_NAME_ID)
        }
    }

    function submitEdit(key: string) {
        const action = { type: "applyEdit" } as const
        const next = calendarReducer(draft, action)
        dispatch(action)
        requestFocus(next.editing === null ? monthEditId(key) : (next.editing.buffer.errors[0]?.fieldId ?? monthNameId(key)))
    }

    function openEdit(key: string) {
        dispatch({ type: "openEdit", key })
        // Refused over another row's unapplied values: focus that editor instead.
        const blocked = unapplied.find((f) => f.kind === "edit" && f.key !== key)
        requestFocus(blocked?.kind === "edit" ? monthNameId(blocked.key) : monthNameId(key))
    }

    function remove(key: string, position: number, name: string) {
        // Focus moves to a row that still exists: the next, else the previous, else the Add panel.
        const neighbour = months[position] ?? months[position - 2]
        dispatch({ type: "remove", key })
        announce(sentence(`${monthLabel(position, name)}, removed from the draft.`))
        requestFocus(neighbour === undefined ? COMPOSER_NAME_ID : monthEditId(neighbour.key))
    }

    return (
        <div className="calendar-roster">
            <div className="calendar-roster__header">
                <h3 id={MONTHS_ID} tabIndex={-1}>
                    Months in order
                </h3>
                {full ? (
                    <p className="authoring-field__hint">A calendar can have up to {MONTHS_MAX} months.</p>
                ) : null}
            </div>
            <p className="calendar-roster__summary" aria-live="polite">
                <strong>{monthCountText(draft)}</strong>. {yearLengthText(draft)}
                {unapplied.length > 0 ? " Changes you have not applied are not counted." : ""}
            </p>
            <p className="authoring-field__hint">
                Add, Edit and Remove change this unsaved draft only. The calendar is created on the last step.
            </p>
            {draft.notice !== null ? (
                <p className="calendar-roster__notice" role="status">
                    {draft.notice}
                </p>
            ) : null}

            {composer !== null ? (
                <form
                    id="calendar-composer"
                    className="inset-group calendar-roster__form"
                    aria-label="Add a month"
                    noValidate
                    onSubmit={(event) => {
                        event.preventDefault()
                        submitComposer()
                    }}
                >
                    <p className="calendar-roster__form-title">
                        Add a month <span className="authoring-field__hint">(becomes month {months.length + 1})</span>
                    </p>
                    <div className="calendar-roster__fields">
                        <TextField
                            id={COMPOSER_NAME_ID}
                            label="New month name"
                            required
                            maxLength={MONTH_NAME_MAX}
                            value={composer.name}
                            onChange={(value) => dispatch({ type: "composer", patch: { name: value } })}
                            error={errorFor(COMPOSER_NAME_ID)}
                        />
                        <TextField
                            id={COMPOSER_DAYS_ID}
                            label={`New month days (1–${DAY_COUNT_MAX})`}
                            required
                            inputMode="numeric"
                            value={composer.dayCount}
                            onChange={(value) => dispatch({ type: "composer", patch: { dayCount: value } })}
                            error={errorFor(COMPOSER_DAYS_ID)}
                        />
                    </div>
                    <div className="row-actions">
                        <button type="submit" className="authoring-button authoring-button--primary">
                            Add to draft
                        </button>
                    </div>
                </form>
            ) : null}

            <div className="calendar-roster__head" aria-hidden="true">
                <span>No.</span>
                <span>Month</span>
                <span>Days</span>
                <span />
            </div>
            <ol className="calendar-roster__list">
                {months.map((month, index) => {
                    const position = index + 1
                    const open = editing?.key === month.key
                    const label = monthLabel(position, month.name)
                    return (
                        <li key={month.key}>
                            <div className="calendar-roster__row">
                                <span className="calendar-roster__position">{position}</span>
                                <span className="calendar-roster__name">
                                    {month.name.trim() === "" ? (
                                        <em>Name needed</em>
                                    ) : (
                                        month.name
                                    )}
                                </span>
                                <span className="calendar-roster__days">{month.dayCount}</span>
                                <span className="calendar-roster__actions">
                                    <button
                                        type="button"
                                        id={monthEditId(month.key)}
                                        className="authoring-button"
                                        aria-label={`Edit ${label}`}
                                        aria-expanded={open}
                                        aria-controls={`calendar-month-${month.key}-form`}
                                        onClick={() => openEdit(month.key)}
                                    >
                                        Edit
                                    </button>
                                    {months.length > 1 ? (
                                        <button
                                            type="button"
                                            className="authoring-button"
                                            aria-label={`Remove ${label} from the draft`}
                                            onClick={() => remove(month.key, position, month.name)}
                                        >
                                            Remove
                                        </button>
                                    ) : null}
                                </span>
                            </div>
                            {open && editing !== null ? (
                                <form
                                    id={`calendar-month-${month.key}-form`}
                                    className="inset-group calendar-roster__form"
                                    aria-label={`Edit month ${position}`}
                                    noValidate
                                    onSubmit={(event) => {
                                        event.preventDefault()
                                        submitEdit(month.key)
                                    }}
                                >
                                    <div className="calendar-roster__fields">
                                        <TextField
                                            id={monthNameId(month.key)}
                                            label={`Month ${position} name`}
                                            required
                                            maxLength={MONTH_NAME_MAX}
                                            value={editing.buffer.name}
                                            onChange={(value) => dispatch({ type: "edit", patch: { name: value } })}
                                            error={errorFor(monthNameId(month.key))}
                                        />
                                        <TextField
                                            id={monthDaysId(month.key)}
                                            label={`Month ${position} days (1–${DAY_COUNT_MAX})`}
                                            required
                                            inputMode="numeric"
                                            value={editing.buffer.dayCount}
                                            onChange={(value) => dispatch({ type: "edit", patch: { dayCount: value } })}
                                            error={errorFor(monthDaysId(month.key))}
                                        />
                                    </div>
                                    <div className="row-actions">
                                        <button type="submit" className="authoring-button authoring-button--primary">
                                            Apply to draft
                                        </button>
                                        <button
                                            type="button"
                                            className="authoring-button"
                                            onClick={() => {
                                                dispatch({ type: "cancelEdit" })
                                                requestFocus(monthEditId(month.key))
                                            }}
                                        >
                                            Cancel edit
                                        </button>
                                    </div>
                                </form>
                            ) : null}
                        </li>
                    )
                })}
            </ol>
        </div>
    )
}
