import { useId, useLayoutEffect, useRef, useState } from "react"
import type { ReactNode } from "react"
import { createWorldTime } from "../../api/worldTime"
import { useSession } from "../../context/SessionContext"
import { useAuthoringMutation } from "../../hooks/useAuthoringMutation"
import type { AuthoringMutationStatus, RefreshOutcome } from "../../hooks/useAuthoringMutation"
import type {
    Calendar,
    CreateWorldTimeBody,
    WorldTimeItem,
    WorldTimeReceipt,
} from "../../types/worldTime"
import {
    emptyWorldTimeForm,
    toWorldTimeBody,
    validateWorldTimeForm,
} from "../../utils/worldTimeForm"
import type { WorldTimeFormValues, WorldTimeMode } from "../../utils/worldTimeForm"
import { RadioGroupField, SelectField, TextField } from "./fields"
import { AuthoringForm, ErrorSummary, FormActions, MutationStatusMessage } from "./feedback"
import type { FieldError } from "./feedback"
import "./authoring.css"

// Server error codes that belong to one field of this form.
const FIELD_FOR_CODE: Readonly<Record<string, string>> = {
    calendar_id_invalid: "time-calendar",
    world_time_id_invalid: "time-after",
}
const MESSAGE_FOR_CODE: Readonly<Record<string, string>> = {
    calendar_id_invalid: "That calendar is not available. Choose another.",
    world_time_id_invalid: "That time is not available. Choose another.",
    world_time_no_gap:
        "There is no room to place a new time there. Choose a different position.",
}

interface WorldTimeFormProps {
    campaignId: string
    calendars: Calendar[]
    // Existing points (latest first), offered as the "after"/"before" anchors.
    times: WorldTimeItem[]
    // The time was recorded. A caller that reads the times again afterwards returns what that read
    // did, so a recorded time whose read-back failed is reported as such (and never recorded twice).
    // `hasUnrecordedInput` reads the form as it is when called, so a caller that waits (for the list to be
    // read) asks at the moment it decides what to do next, not at the confirmation: values entered while
    // it waited count, and values put back to an empty form do not.
    onCreated: (
        receipt: WorldTimeReceipt,
        form: { hasUnrecordedInput: () => boolean },
    ) => void | RefreshOutcome | Promise<void | RefreshOutcome>
    onCancel: () => void
    heading?: string
    // The form sits inside another form (the picker does): render a group that saves by click or
    // Enter, never a nested <form>.
    nested?: boolean
    // Reports whether the entered values differ from an empty form (for a caller that guards leaving).
    onDirtyChange?: (dirty: boolean) => void
    // Reports the status of the recording request (pending, unknown outcome, confirmed...).
    onStatusChange?: (status: AuthoringMutationStatus) => void
    // For a form kept across a dialog closing: while an earlier attempt's outcome is unknown, a changed
    // form re-sends that attempt (same key and body) instead of recording a second time, and a
    // confirmed attempt clears the form only if the form still holds what it sent.
    holdUnresolved?: boolean
}

// Records one point in fictional time: a date on a calendar, or a narrative
// moment placed after (and optionally before) existing points. The server
// computes the permanent sort key; nothing here invents an ordering.
export function WorldTimeForm({
    campaignId,
    calendars,
    times,
    onCreated,
    onCancel,
    heading,
    nested = false,
    onDirtyChange,
    onStatusChange,
    holdUnresolved = false,
}: WorldTimeFormProps) {
    const { reload } = useSession()
    const [values, setValuesState] = useState<WorldTimeFormValues>(() => emptyWorldTimeForm(calendars))
    // What the form holds right now. Every change goes through `setValues`, which updates this at once: a
    // render is not guaranteed to have happened between a change and a callback that asks about it.
    const valuesRef = useRef(values)
    const calendarsRef = useRef(calendars)
    function setValues(next: WorldTimeFormValues) {
        valuesRef.current = next
        setValuesState(next)
    }
    const isEmptyNow = () =>
        JSON.stringify(valuesRef.current) === JSON.stringify(emptyWorldTimeForm(calendarsRef.current))
    const [errors, setErrors] = useState<FieldError[]>([])
    // Several of these forms can be mounted at once (one behind each picker's dialog), so no id is fixed.
    const uid = useId()
    const fid = (base: string) => `${uid}-${base}`
    const [attempt, setAttempt] = useState(0)
    // The earlier attempt was sent again first because its outcome was unknown (`holdUnresolved`).
    const [resent, setResent] = useState(false)

    const mutation = useAuthoringMutation<CreateWorldTimeBody, WorldTimeReceipt>({
        scopeKey: `create-world-time:${campaignId}`,
        request: (body, ctx) => createWorldTime(campaignId, body, ctx),
        // The caller words the outcome of its own read-back (a notice beside the form).
        ownsRefreshNotice: true,
        holdUnresolved,
        onSuccess: (receipt, body) => {
            setResent(false)
            // The confirmed attempt's own values leave the form; anything else was entered since and stays.
            if (!holdUnresolved || !differsFrom(body)) {
                setValues(emptyWorldTimeForm(calendars))
                setErrors([])
            }
            return onCreated(receipt, { hasUnrecordedInput: () => !isEmptyNow() })
        },
    })
    const pending = mutation.status.kind === "pending"
    const initial = emptyWorldTimeForm(calendars)
    const dirty = JSON.stringify(values) !== JSON.stringify(initial)
    // Mirrored before paint (layout effects), so a caller that decides from them never acts on a stale copy.
    useLayoutEffect(() => {
        calendarsRef.current = calendars
        onDirtyChange?.(dirty)
    }, [dirty, onDirtyChange, calendars])
    useLayoutEffect(() => {
        onStatusChange?.(mutation.status)
    }, [mutation.status, onStatusChange])
    const serverError = mutation.status.kind === "error" ? mutation.status.error : null
    const code = serverError?.code ?? null
    const serverFieldId = code === null ? null : (FIELD_FOR_CODE[code] ?? null)
    const serverErrors: FieldError[] =
        code !== null && MESSAGE_FOR_CODE[code] !== undefined
            ? [{ fieldId: serverFieldId ?? "time-after", message: MESSAGE_FOR_CODE[code]! }]
            : []
    const all = [...errors, ...serverErrors]
    const errorFor = (id: string) => all.find((e) => e.fieldId === id)?.message ?? null

    const selected = calendars.find((c) => c.calendar_id === values.calendarId)

    function set<K extends keyof WorldTimeFormValues>(key: K) {
        return (value: WorldTimeFormValues[K]) => setValues({ ...valuesRef.current, [key]: value })
    }

    // Whether the form now holds something other than `sent` (the body of the attempt just confirmed).
    function differsFrom(sent: CreateWorldTimeBody): boolean {
        const now = valuesRef.current
        if (validateWorldTimeForm(now, calendars).length > 0) return true
        return JSON.stringify(toWorldTimeBody(now)) !== JSON.stringify(sent)
    }

    function submit() {
        // A request is already on its way: nothing is validated or sent again.
        if (pending) return
        const found = validateWorldTimeForm(values, calendars)
        setErrors(found)
        setAttempt((n) => n + 1)
        if (found.length === 0 && mutation.submit(toWorldTimeBody(values)) === "resolving-earlier") {
            setResent(true)
        }
    }

    const timeOptions = times.map((t) => ({ value: t.world_time_id, label: t.display }))
    const noBackendMessage =
        serverError !== null && serverErrors.length === 0 ? (
            <MutationStatusMessage
                error={serverError}
                onRetry={mutation.retry}
                onCheckSession={reload}
            />
        ) : null

    const label = heading ?? "Record a world time"
    const Shell = nested ? NestedGroup : AuthoringForm
    return (
        <Shell label={label} onSubmit={submit}>
            <ErrorSummary errors={all.map((e) => ({ ...e, fieldId: fid(e.fieldId) }))} attempt={attempt} />
            {noBackendMessage}
            {resent && serverError !== null ? (
                <p role="status">
                    Your earlier time may already have been recorded, so it was sent again first. What you changed
                    is kept; record it once that is settled.
                </p>
            ) : null}
            <RadioGroupField
                legend="Kind of time"
                value={values.mode}
                options={[
                    {
                        value: "calendar",
                        label: "A date on a calendar",
                        description: calendars.length === 0 ? "Create a calendar first." : undefined,
                    },
                    { value: "narrative", label: "A moment placed after another time" },
                ]}
                onChange={(value) => set("mode")(value as WorldTimeMode)}
            />
            {values.mode === "calendar" ? (
                <>
                    <SelectField
                        id={fid("time-calendar")}
                        label="Calendar"
                        value={values.calendarId}
                        placeholder="Choose a calendar"
                        required
                        options={calendars.map((c) => ({ value: c.calendar_id, label: c.name }))}
                        onChange={set("calendarId")}
                        error={errorFor("time-calendar")}
                    />
                    <TextField
                        id={fid("time-year")}
                        label="Year"
                        value={values.year}
                        required
                        hint="A whole number; negative years count back from the epoch."
                        onChange={set("year")}
                        error={errorFor("time-year")}
                    />
                    <SelectField
                        id={fid("time-month")}
                        label="Month"
                        value={values.month}
                        placeholder="Not specified"
                        options={(selected?.months ?? []).map((m) => ({
                            value: String(m.month_number),
                            label: m.name,
                        }))}
                        onChange={set("month")}
                        error={errorFor("time-month")}
                    />
                    <TextField
                        id={fid("time-day")}
                        label="Day"
                        value={values.day}
                        onChange={set("day")}
                        error={errorFor("time-day")}
                    />
                    <TextField
                        id={fid("time-hour")}
                        label="Hour (0–23)"
                        value={values.hour}
                        onChange={set("hour")}
                        error={errorFor("time-hour")}
                    />
                    <TextField
                        id={fid("time-minute")}
                        label="Minute (0–59)"
                        value={values.minute}
                        onChange={set("minute")}
                        error={errorFor("time-minute")}
                    />
                    <label className="authoring-checkbox" htmlFor={fid("time-approximate")}>
                        <input
                            id={fid("time-approximate")}
                            type="checkbox"
                            checked={values.approximate}
                            onChange={(event) => set("approximate")(event.target.checked)}
                        />
                        This date is approximate
                    </label>
                    <TextField
                        id={fid("time-label")}
                        label="Label (optional)"
                        value={values.label}
                        onChange={set("label")}
                        error={errorFor("time-label")}
                    />
                </>
            ) : (
                <>
                    <TextField
                        id={fid("time-label")}
                        label="Describe this moment"
                        value={values.label}
                        required
                        onChange={set("label")}
                        error={errorFor("time-label")}
                    />
                    <SelectField
                        id={fid("time-after")}
                        label="Comes after"
                        value={values.afterId}
                        placeholder="Choose a time"
                        required
                        options={timeOptions}
                        onChange={set("afterId")}
                        error={errorFor("time-after")}
                    />
                    <SelectField
                        id={fid("time-before")}
                        label="Comes before (optional)"
                        value={values.beforeId}
                        placeholder="No later limit"
                        options={timeOptions}
                        onChange={set("beforeId")}
                        error={errorFor("time-before")}
                    />
                </>
            )}
            <FormActions
                pending={pending}
                saveLabel="Record time"
                pendingLabel="Recording…"
                onCancel={onCancel}
                onSave={nested ? submit : undefined}
            />
        </Shell>
    )
}

// What a form is, minus the <form>: Enter in a text box saves, as it would in a form.
function NestedGroup({ onSubmit, children, label }: { onSubmit: () => void; children: ReactNode; label: string }) {
    return (
        <div
            role="group"
            className="authoring-form"
            aria-label={label}
            onKeyDown={(event) => {
                if (event.key === "Enter" && event.target instanceof HTMLInputElement && event.target.type !== "radio") {
                    event.preventDefault()
                    onSubmit()
                }
            }}
        >
            {children}
        </div>
    )
}
