import { useState } from "react"
import { Link, useNavigate, useParams } from "react-router"
import { createCalendar } from "../api/worldTime"
import { ConfirmDialog } from "../components/authoring/ConfirmDialog"
import { TextAreaField, TextField } from "../components/authoring/fields"
import {
    AuthoringForm,
    ErrorSummary,
    FormActions,
    MutationStatusMessage,
} from "../components/authoring/feedback"
import type { FieldError } from "../components/authoring/feedback"
import { useSession } from "../context/SessionContext"
import { useAuthoringMutation } from "../hooks/useAuthoringMutation"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import { usePageArrival } from "../hooks/usePageArrival"
import { useUnsavedChangesGuard } from "../hooks/useUnsavedChangesGuard"
import type { WorldDetail } from "../types/worldAuthoring"
import type { CalendarReceipt, CreateCalendarBody } from "../types/worldTime"
import { DESCRIPTION_MAX, NAME_MAX } from "../utils/authoringValidation"
import {
    DAY_COUNT_MAX,
    EMPTY_CALENDAR_FORM,
    MONTHS_MAX,
    toCalendarBody,
    validateCalendarForm,
} from "../utils/worldTimeForm"
import type { CalendarFormValues } from "../utils/worldTimeForm"
import { worldPath } from "../api/worlds"
import "../components/authoring/authoring.css"

// /worlds/:worldId/calendars/new — a world owner defines a calendar: its name,
// optional epoch and days per week, and its months in order. A calendar is
// created whole; editing one after times refer to it is not offered.
export function CreateCalendarPage() {
    const { worldId } = useParams<{ worldId: string }>()
    const id = worldId ?? ""
    const { state } = useAuthoringResource<WorldDetail>(worldId ? worldPath(id) : null)
    const headingRef = usePageArrival(state.kind !== "loading")
    const canCreate =
        state.kind === "ready" && state.data.available_actions.includes("create_calendar")

    return (
        <div className="world-page">
            <div className="authoring-page">
                <p className="authoring-page__breadcrumb">
                    <Link to={`/worlds/${encodeURIComponent(id)}`}>World</Link>
                </p>
                <h1 ref={headingRef} tabIndex={-1}>
                    New calendar
                </h1>
                {state.kind === "loading" ? (
                    <p role="status">Loading…</p>
                ) : state.kind === "unavailable" || state.kind === "denied" ? (
                    <p role="alert">This world is unavailable or you do not have access to it.</p>
                ) : state.kind === "error" ? (
                    <p role="alert">The world could not be loaded. Try reloading the page.</p>
                ) : !canCreate ? (
                    <p role="alert">You cannot create a calendar for this world right now.</p>
                ) : (
                    <CalendarForm worldId={id} />
                )}
            </div>
        </div>
    )
}

function CalendarForm({ worldId }: { worldId: string }) {
    const navigate = useNavigate()
    const { reload } = useSession()
    const [values, setValues] = useState<CalendarFormValues>(EMPTY_CALENDAR_FORM)
    const [touched, setTouched] = useState(false)
    const [errors, setErrors] = useState<FieldError[]>([])
    const [attempt, setAttempt] = useState(0)
    const guard = useUnsavedChangesGuard(touched)

    const mutation = useAuthoringMutation<CreateCalendarBody, CalendarReceipt>({
        scopeKey: `create-calendar:${worldId}`,
        request: (body, ctx) => createCalendar(worldId, body, ctx),
        onSuccess: () => {
            guard.release()
            void navigate(`/worlds/${encodeURIComponent(worldId)}`, {
                replace: true,
                state: { announce: "Calendar created" },
            })
        },
    })
    const pending = mutation.status.kind === "pending"
    const serverError = mutation.status.kind === "error" ? mutation.status.error : null
    const errorFor = (fieldId: string) => errors.find((e) => e.fieldId === fieldId)?.message ?? null

    function update(next: Partial<CalendarFormValues>) {
        setTouched(true)
        setValues((current) => ({ ...current, ...next }))
    }
    function updateMonth(index: number, patch: Partial<{ name: string; dayCount: string }>) {
        update({ months: values.months.map((m, i) => (i === index ? { ...m, ...patch } : m)) })
    }
    function addMonth() {
        update({ months: [...values.months, { name: "", dayCount: "30" }] })
    }
    function removeMonth(index: number) {
        update({ months: values.months.filter((_, i) => i !== index) })
    }

    function submit() {
        const found = validateCalendarForm(values)
        setErrors(found)
        setAttempt((n) => n + 1)
        if (found.length === 0) mutation.submit(toCalendarBody(values))
    }

    return (
        <>
            <p className="authoring-page__lead">
                A calendar lets you record dates in this world. Add its months in order; the
                number of days in each sets the length of a year.
            </p>
            <AuthoringForm label="Create calendar" onSubmit={submit}>
                <ErrorSummary errors={errors} attempt={attempt} />
                {serverError !== null ? (
                    <MutationStatusMessage
                        error={serverError}
                        onRetry={mutation.retry}
                        onCheckSession={reload}
                    />
                ) : null}
                <TextField
                    id="calendar-name"
                    label="Calendar name"
                    value={values.name}
                    required
                    maxLength={NAME_MAX}
                    onChange={(value) => update({ name: value })}
                    error={errorFor("calendar-name")}
                />
                <TextAreaField
                    id="calendar-description"
                    label="Description"
                    value={values.description}
                    maxLength={DESCRIPTION_MAX}
                    onChange={(value) => update({ description: value })}
                />
                <TextField
                    id="calendar-epoch"
                    label="Epoch (what year zero is counted from)"
                    value={values.epochLabel}
                    onChange={(value) => update({ epochLabel: value })}
                />
                <TextField
                    id="calendar-days-per-week"
                    label="Days per week"
                    value={values.daysPerWeek}
                    onChange={(value) => update({ daysPerWeek: value })}
                    error={errorFor("calendar-days-per-week")}
                />
                <fieldset className="authoring-field">
                    <legend className="authoring-field__label">
                        Months (in order, up to {MONTHS_MAX})
                    </legend>
                    {values.months.map((month, index) => (
                        <div className="authoring-month-row" key={index}>
                            <TextField
                                id={`calendar-month-${index}-name`}
                                label={`Month ${index + 1} name`}
                                value={month.name}
                                required
                                onChange={(value) => updateMonth(index, { name: value })}
                                error={errorFor(`calendar-month-${index}-name`)}
                            />
                            <TextField
                                id={`calendar-month-${index}-days`}
                                label={`Month ${index + 1} days (1–${DAY_COUNT_MAX})`}
                                value={month.dayCount}
                                required
                                onChange={(value) => updateMonth(index, { dayCount: value })}
                                error={errorFor(`calendar-month-${index}-days`)}
                            />
                            {values.months.length > 1 ? (
                                <button
                                    type="button"
                                    className="authoring-button"
                                    onClick={() => removeMonth(index)}
                                >
                                    Remove month {index + 1}
                                </button>
                            ) : null}
                        </div>
                    ))}
                    {values.months.length < MONTHS_MAX ? (
                        <button type="button" className="authoring-button" onClick={addMonth}>
                            Add a month
                        </button>
                    ) : null}
                </fieldset>
                <FormActions
                    pending={pending}
                    saveLabel="Create calendar"
                    pendingLabel="Creating…"
                    onCancel={() => void navigate(`/worlds/${encodeURIComponent(worldId)}`)}
                />
            </AuthoringForm>
            <ConfirmDialog
                open={guard.blocked}
                title="Discard unsaved changes?"
                description="You have entered details for a new calendar that have not been saved."
                confirmLabel="Discard changes"
                onConfirm={guard.discard}
                onCancel={guard.stay}
                cancelLabel="Keep editing"
            />
        </>
    )
}
