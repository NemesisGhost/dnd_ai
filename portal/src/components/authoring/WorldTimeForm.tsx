import { useState } from "react"
import { createWorldTime } from "../../api/worldTime"
import { useSession } from "../../context/SessionContext"
import { useAuthoringMutation } from "../../hooks/useAuthoringMutation"
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
    onCreated: (receipt: WorldTimeReceipt) => void
    onCancel: () => void
    heading?: string
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
}: WorldTimeFormProps) {
    const { reload } = useSession()
    const [values, setValues] = useState<WorldTimeFormValues>(() => emptyWorldTimeForm(calendars))
    const [errors, setErrors] = useState<FieldError[]>([])
    const [attempt, setAttempt] = useState(0)

    const mutation = useAuthoringMutation<CreateWorldTimeBody, WorldTimeReceipt>({
        scopeKey: `create-world-time:${campaignId}`,
        request: (body, ctx) => createWorldTime(campaignId, body, ctx),
        onSuccess: (receipt) => {
            setValues(emptyWorldTimeForm(calendars))
            setErrors([])
            onCreated(receipt)
        },
    })
    const pending = mutation.status.kind === "pending"
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
        return (value: WorldTimeFormValues[K]) => setValues((current) => ({ ...current, [key]: value }))
    }

    function submit() {
        const found = validateWorldTimeForm(values, calendars)
        setErrors(found)
        setAttempt((n) => n + 1)
        if (found.length === 0) mutation.submit(toWorldTimeBody(values))
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

    return (
        <AuthoringForm label={heading ?? "Record a world time"} onSubmit={submit}>
            <ErrorSummary errors={all} attempt={attempt} />
            {noBackendMessage}
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
                        id="time-calendar"
                        label="Calendar"
                        value={values.calendarId}
                        placeholder="Choose a calendar"
                        required
                        options={calendars.map((c) => ({ value: c.calendar_id, label: c.name }))}
                        onChange={set("calendarId")}
                        error={errorFor("time-calendar")}
                    />
                    <TextField
                        id="time-year"
                        label="Year"
                        value={values.year}
                        required
                        hint="A whole number; negative years count back from the epoch."
                        onChange={set("year")}
                        error={errorFor("time-year")}
                    />
                    <SelectField
                        id="time-month"
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
                        id="time-day"
                        label="Day"
                        value={values.day}
                        onChange={set("day")}
                        error={errorFor("time-day")}
                    />
                    <TextField
                        id="time-hour"
                        label="Hour (0–23)"
                        value={values.hour}
                        onChange={set("hour")}
                        error={errorFor("time-hour")}
                    />
                    <TextField
                        id="time-minute"
                        label="Minute (0–59)"
                        value={values.minute}
                        onChange={set("minute")}
                        error={errorFor("time-minute")}
                    />
                    <label className="authoring-checkbox" htmlFor="time-approximate">
                        <input
                            id="time-approximate"
                            type="checkbox"
                            checked={values.approximate}
                            onChange={(event) => set("approximate")(event.target.checked)}
                        />
                        This date is approximate
                    </label>
                    <TextField
                        id="time-label"
                        label="Label (optional)"
                        value={values.label}
                        onChange={set("label")}
                        error={errorFor("time-label")}
                    />
                </>
            ) : (
                <>
                    <TextField
                        id="time-label"
                        label="Describe this moment"
                        value={values.label}
                        required
                        onChange={set("label")}
                        error={errorFor("time-label")}
                    />
                    <SelectField
                        id="time-after"
                        label="Comes after"
                        value={values.afterId}
                        placeholder="Choose a time"
                        required
                        options={timeOptions}
                        onChange={set("afterId")}
                        error={errorFor("time-after")}
                    />
                    <SelectField
                        id="time-before"
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
            />
        </AuthoringForm>
    )
}
