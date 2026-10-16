import type { ReactNode } from "react"
import { Link } from "react-router"
import { AuthoringForm, FormActions } from "../authoring/feedback"
import type { FieldError } from "../authoring/feedback"
import { monthCountText, yearLengthText } from "./calendarDraft"
import type { CalendarDraft } from "./calendarDraft"

// Everything that will be sent, read back before the one request. The only form on the page that
// can create the calendar lives here, and it holds nothing but the actions.
export function CalendarReview({
    draft,
    problems,
    basicsHref,
    monthsHref,
    pending,
    status,
    onFollow,
    onCreate,
    onCancel,
}: {
    draft: CalendarDraft
    // What is wrong with the draft now, from any step.
    problems: readonly FieldError[]
    basicsHref: string
    monthsHref: string
    pending: boolean
    // A failed attempt, shown beside the action that made it.
    status?: ReactNode
    onFollow: (fieldId: string) => void
    onCreate: () => void
    onCancel: () => void
}) {
    return (
        <div className="calendar-review">
            <section aria-labelledby="calendar-review-details">
                <div className="calendar-review__heading">
                    <h3 id="calendar-review-details">Calendar details</h3>
                    <Link to={basicsHref}>Change basics</Link>
                </div>
                <dl className="calendar-review__facts">
                    <dt>Name</dt>
                    <dd>{draft.name.trim() === "" ? <em>Not entered yet</em> : draft.name.trim()}</dd>
                    <dt>Description</dt>
                    <dd>{draft.description.trim() === "" ? "None" : draft.description.trim()}</dd>
                    <dt>Epoch</dt>
                    <dd>{draft.epochLabel.trim() === "" ? "Not set" : draft.epochLabel.trim()}</dd>
                    <dt>Days per week</dt>
                    <dd>{draft.daysPerWeek.trim() === "" ? "Not set" : draft.daysPerWeek.trim()}</dd>
                </dl>
            </section>
            <section aria-labelledby="calendar-review-months">
                <div className="calendar-review__heading">
                    <h3 id="calendar-review-months">Months in order</h3>
                    <Link to={monthsHref}>Change months</Link>
                </div>
                {draft.months.length === 0 ? <p>No months yet.</p> : null}
                <ol className="record-list calendar-review__months">
                    {draft.months.map((month) => (
                        <li key={month.key}>
                            {month.name.trim() === "" ? <em>Name needed</em> : month.name.trim()} —{" "}
                            {month.dayCount.trim()} days
                        </li>
                    ))}
                </ol>
                <p>
                    <strong>{monthCountText(draft)}</strong>. {yearLengthText(draft)}
                </p>
            </section>
            {problems.length > 0 ? (
                <section aria-labelledby="calendar-review-problems" className="inset-group">
                    <h3 id="calendar-review-problems">Before you can create this calendar</h3>
                    <ul>
                        {problems.map((problem) => (
                            <li key={problem.fieldId}>
                                <a
                                    href={`#${problem.fieldId}`}
                                    onClick={(event) => {
                                        event.preventDefault()
                                        onFollow(problem.fieldId)
                                    }}
                                >
                                    {problem.message}
                                </a>
                            </li>
                        ))}
                    </ul>
                </section>
            ) : null}
            <p className="authoring-note">
                A calendar cannot be changed after it is created.
            </p>
            {status}
            <AuthoringForm label="Create calendar" onSubmit={onCreate}>
                <FormActions
                    pending={pending}
                    saveLabel="Create calendar"
                    pendingLabel="Creating…"
                    onCancel={onCancel}
                />
            </AuthoringForm>
        </div>
    )
}
