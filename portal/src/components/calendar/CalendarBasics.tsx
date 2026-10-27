import type { Dispatch } from "react"
import { TextAreaField, TextField } from "../authoring/fields"
import { DESCRIPTION_MAX, NAME_MAX } from "../../utils/authoringValidation"
import { DAYS_PER_WEEK_MAX, EPOCH_LABEL_MAX } from "../../utils/worldTimeForm"
import type { CalendarDraft, DraftAction } from "./calendarDraft"

// The calendar's own fields. They are not inside a form, so pressing Enter in one never creates
// the calendar; only the last step does.
export function CalendarBasics({
    draft,
    dispatch,
    errorFor,
}: {
    draft: CalendarDraft
    dispatch: Dispatch<DraftAction>
    errorFor: (fieldId: string) => string | null
}) {
    return (
        <div className="authoring-form">
            <TextField
                id="calendar-name"
                label="Calendar name"
                value={draft.name}
                required
                maxLength={NAME_MAX}
                onChange={(value) => dispatch({ type: "field", field: "name", value })}
                error={errorFor("calendar-name")}
            />
            <TextAreaField
                id="calendar-description"
                label="Description"
                hint="Optional."
                value={draft.description}
                maxLength={DESCRIPTION_MAX}
                onChange={(value) => dispatch({ type: "field", field: "description", value })}
                error={errorFor("calendar-description")}
            />
            <TextField
                id="calendar-epoch"
                label="Epoch (what year zero is counted from)"
                hint="Optional, for example “the Founding”."
                value={draft.epochLabel}
                maxLength={EPOCH_LABEL_MAX}
                onChange={(value) => dispatch({ type: "field", field: "epochLabel", value })}
                error={errorFor("calendar-epoch")}
            />
            <TextField
                id="calendar-days-per-week"
                label="Days per week"
                hint={`Optional, a whole number from 1 to ${DAYS_PER_WEEK_MAX}. Leave empty if the calendar has no fixed week.`}
                inputMode="numeric"
                value={draft.daysPerWeek}
                onChange={(value) => dispatch({ type: "field", field: "daysPerWeek", value })}
                error={errorFor("calendar-days-per-week")}
            />
        </div>
    )
}
