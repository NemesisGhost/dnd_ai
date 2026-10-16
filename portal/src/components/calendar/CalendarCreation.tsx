import { useEffect, useReducer, useRef, useState } from "react"
import { Link, useNavigate } from "react-router"
import { createCalendar } from "../../api/worldTime"
import { ConfirmDialog } from "../authoring/ConfirmDialog"
import { useAnnounce } from "../authoring/announcer"
import { ErrorSummary, MutationStatusMessage } from "../authoring/feedback"
import type { FieldError } from "../authoring/feedback"
import { SectionPanel, StageNav } from "../staged/StagedNav"
import { useStagedNavigation } from "../staged/useStagedNavigation"
import { useSession } from "../../context/SessionContext"
import { useAuthoringMutation } from "../../hooks/useAuthoringMutation"
import { useUnsavedChangesGuard } from "../../hooks/useUnsavedChangesGuard"
import type { CalendarReceipt, CreateCalendarBody } from "../../types/worldTime"
import { toCalendarBody } from "../../utils/worldTimeForm"
import { CalendarBasics } from "./CalendarBasics"
import { CalendarReview } from "./CalendarReview"
import { MonthRoster } from "./MonthRoster"
import {
    blockingForm,
    calendarReducer,
    initialDraft,
    monthKeyOfField,
    monthNameId,
    stepForField,
    validateCalendarDraft,
} from "./calendarDraft"
import type { CalendarStep, DraftAction } from "./calendarDraft"
import { CALENDAR_STEPS, calendarStepHeadingId } from "./calendarSteps"
import "../authoring/authoring.css"

const STEP_REFS = CALENDAR_STEPS.map((s) => ({ key: s.key, stage: s.key }))

// Creating a calendar in three local steps: Basics, Months, Review & create. The steps only change
// what is shown (`?section=`); every panel stays mounted and the whole draft lives here, so nothing
// typed is lost by moving between them. Nothing is sent until the single Create calendar action on
// the last step, which sends the complete ordered calendar in one request.
export function CalendarCreation({ worldId }: { worldId: string }) {
    const navigate = useNavigate()
    const { reload } = useSession()
    const announce = useAnnounce()
    const [draft, dispatch] = useReducer(calendarReducer, undefined, initialDraft)
    const [reported, setReported] = useState<FieldError[]>([])
    const [attempt, setAttempt] = useState(0)
    const nav = useStagedNavigation<CalendarStep, CalendarStep>(STEP_REFS, "basics", { ready: true })
    const guard = useUnsavedChangesGuard(draft.touched)
    const worldHref = `/worlds/${encodeURIComponent(worldId)}`

    const mutation = useAuthoringMutation<CreateCalendarBody, CalendarReceipt>({
        scopeKey: `create-calendar:${worldId}`,
        request: (body, ctx) => createCalendar(worldId, body, ctx),
        onSuccess: () => {
            guard.release()
            void navigate(worldHref, { replace: true, state: { announce: "Calendar created" } })
        },
    })
    const pending = mutation.status.kind === "pending"
    const serverError = mutation.status.kind === "error" ? mutation.status.error : null

    // A change to what would be sent clears a failed attempt, so Retry can only ever replay the
    // body that is on screen. A form being opened or typed in changes nothing that is sent.
    function change(action: DraftAction) {
        if (
            mutation.status.kind === "error" &&
            JSON.stringify(toCalendarBody(calendarReducer(draft, action))) !==
                JSON.stringify(toCalendarBody(draft))
        ) {
            mutation.reset()
        }
        dispatch(action)
    }

    // The problems found by the last Create, kept only while they still apply: fixing one removes
    // it, but a new one never appears (or takes focus) except on the next Create.
    const current = validateCalendarDraft(draft)
    const shown = reported.flatMap((r) => current.find((c) => c.fieldId === r.fieldId) ?? [])
    const errorFor = (fieldId: string): string | null =>
        shown.find((e) => e.fieldId === fieldId)?.message ??
        draft.composer?.errors.find((e) => e.fieldId === fieldId)?.message ??
        draft.editing?.buffer.errors.find((e) => e.fieldId === fieldId)?.message ??
        null

    function create() {
        const found = validateCalendarDraft(draft)
        setReported(found)
        setAttempt((n) => n + 1)
        if (found.length === 0) mutation.submit(toCalendarBody(draft))
    }

    // ---- focus: a step change focuses its heading; a requested field is focused once it is visible ----
    const [reveal, setReveal] = useState<{ id: string; seq: number } | null>(null)
    const seq = useRef(0)
    const handled = useRef(0)
    function requestFocus(id: string) {
        seq.current += 1
        setReveal({ id, seq: seq.current })
    }

    const lastStep = useRef<CalendarStep | null>(null)
    useEffect(() => {
        if (lastStep.current === null) {
            lastStep.current = nav.section
        } else if (lastStep.current !== nav.section) {
            lastStep.current = nav.section
            if (!(reveal !== null && handled.current !== reveal.seq)) {
                document.getElementById(calendarStepHeadingId(nav.section))?.focus()
            }
        }
    })
    useEffect(() => {
        if (reveal === null || handled.current === reveal.seq) return
        const el = document.getElementById(reveal.id)
        if (el === null || el.closest("[hidden]") !== null) return
        handled.current = reveal.seq
        el.focus()
        el.scrollIntoView?.({ block: "nearest" })
    })

    // An error link: show the step, open the row when it is collapsed, then focus the field. A form
    // holding unapplied values is never closed to show something else; its own field gets focus.
    function follow(fieldId: string) {
        let target = fieldId
        const key = monthKeyOfField(fieldId)
        if (key !== null && draft.months.some((m) => m.key === key) && draft.editing?.key !== key) {
            const blocked = blockingForm(draft)
            if (blocked === null) {
                dispatch({ type: "openEdit", key })
            } else {
                target = monthNameId(blocked.key)
            }
        }
        const step = stepForField(target)
        if (step !== nav.section) void navigate(nav.sectionHref(step))
        requestFocus(target)
    }

    const hrefs = {
        basics: nav.sectionHref("basics"),
        months: nav.sectionHref("months"),
        review: nav.sectionHref("review"),
    }

    return (
        <>
            <p className="authoring-page__lead calendar-lead">A calendar lets you record dates in this world.</p>
            <ErrorSummary errors={shown} attempt={attempt} onFollow={follow} />
            <StageNav
                ariaLabel="New calendar workflow"
                stages={CALENDAR_STEPS.map((s) => ({ key: s.key, label: s.label }))}
                current={nav.stage}
                hrefFor={nav.stageHref}
            />
            <div className="staged-workspace">
                <div className="session-run__content">
                    {CALENDAR_STEPS.map((step) => (
                        <SectionPanel
                            key={step.key}
                            wide
                            headingId={calendarStepHeadingId(step.key)}
                            label={step.label}
                            purpose={step.purpose}
                            active={step.key === nav.section}
                        >
                            {/* Disabled while the request is in flight, so the draft cannot differ from the body sent. */}
                            <fieldset className="calendar-lock" disabled={pending}>
                                {step.key === "basics" ? (
                                    <>
                                        <CalendarBasics draft={draft} dispatch={change} errorFor={errorFor} />
                                        <StepActions next={{ href: hrefs.months, label: "Next: Months" }} pending={pending} onCancel={() => void navigate(worldHref)} />
                                    </>
                                ) : step.key === "months" ? (
                                    <>
                                        <MonthRoster
                                            draft={draft}
                                            dispatch={change}
                                            errorFor={errorFor}
                                            requestFocus={requestFocus}
                                            announce={announce}
                                        />
                                        <StepActions
                                            back={{ href: hrefs.basics, label: "Back: Basics" }}
                                            next={{ href: hrefs.review, label: "Next: Review & create" }}
                                            pending={pending}
                                            onCancel={() => void navigate(worldHref)}
                                        />
                                    </>
                                ) : (
                                    <>
                                        <CalendarReview
                                            draft={draft}
                                            problems={current}
                                            basicsHref={hrefs.basics}
                                            monthsHref={hrefs.months}
                                            pending={pending}
                                            status={
                                                serverError !== null ? (
                                                    <MutationStatusMessage
                                                        error={serverError}
                                                        onRetry={mutation.retry}
                                                        onCheckSession={reload}
                                                    />
                                                ) : null
                                            }
                                            onFollow={follow}
                                            onCreate={create}
                                            onCancel={() => void navigate(worldHref)}
                                        />
                                    </>
                                )}
                            </fieldset>
                        </SectionPanel>
                    ))}
                </div>
            </div>
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

// Plain navigation between the steps, and Cancel. These are links and a button that never submit.
function StepActions({
    back,
    next,
    pending,
    onCancel,
}: {
    back?: { href: string; label: string }
    next: { href: string; label: string }
    pending: boolean
    onCancel: () => void
}) {
    return (
        <div className="authoring-actions calendar-step-actions">
            {back !== undefined ? (
                <Link className="authoring-button" to={back.href}>
                    {back.label}
                </Link>
            ) : null}
            <Link className="authoring-button authoring-button--primary" to={next.href}>
                {next.label}
            </Link>
            <button type="button" className="authoring-button" onClick={onCancel} disabled={pending}>
                Cancel
            </button>
        </div>
    )
}
