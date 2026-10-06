import { useState } from "react"
import { Link, useNavigate, useParams } from "react-router"
import {
    correctEvent,
    correctionPreviewPath,
    eventPath,
    recordEvent,
    voidEvent,
} from "../api/eventAuthoring"
import { ConfirmDialog } from "../components/authoring/ConfirmDialog"
import { useAnnounce } from "../components/authoring/announcer"
import { SelectField, TextAreaField, TextField } from "../components/authoring/fields"
import {
    AuthoringForm,
    ErrorSummary,
    FormActions,
    MutationStatusMessage,
    StaleWriteNotice,
} from "../components/authoring/feedback"
import type { FieldError } from "../components/authoring/feedback"
import { WorldTimePicker } from "../components/authoring/WorldTimePicker"
import { useSession } from "../context/SessionContext"
import { useAuthoringMutation } from "../hooks/useAuthoringMutation"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import { useCampaignCapability } from "../hooks/useCampaignCapability"
import { usePageArrival } from "../hooks/usePageArrival"
import { useUnsavedChangesGuard } from "../hooks/useUnsavedChangesGuard"
import type {
    CorrectionPreview,
    CorrectionReceipt,
    EventAuthoringView,
    EventReceipt,
} from "../types/eventAuthoring"
import "../components/authoring/authoring.css"

const base = (campaignId: string): string => `/app/${encodeURIComponent(campaignId)}`
const NAME_MAX = 500
const DETAILS_MAX = 4000

const TYPE_OPTIONS = [
    { value: "other", label: "Something that happened" },
    { value: "session_narrative", label: "A moment in a session" },
]

const COMPONENT_LABEL: Readonly<Record<string, string>> = {
    current_hit_points: "Hit points",
    character_build_id: "Active build",
    party_membership: "Party membership",
    quest_status_id: "Quest status",
    objective_status_id: "Objective status",
    knowledge_learned: "Who knows a claim",
    knowledge_public: "Public knowledge",
    party_discovered: "Party discovery",
    awareness_level: "Party awareness",
    belief_awareness_level: "Belief: how it is held",
    belief_confidence: "Belief: confidence",
    belief_interpretation: "Belief: what they think",
    belief_willing_to_share: "Belief: willing to share",
    current_world_time_id: "Campaign time",
    current_location_id: "Location",
}

const REASON_TEXT: Readonly<Record<string, string>> = {
    state_changed: "what it changed has changed since",
    unsupported_effect: "it changed something that cannot be reversed yet",
    effect_not_applied: "one of its effects was never applied",
}

const CODE_MESSAGE: Readonly<Record<string, string>> = {
    event_already_corrected: "This event has already been voided or corrected.",
    event_not_correctable: "A correction cannot be corrected.",
    correction_not_reversible:
        "This event cannot be corrected automatically: something it changed has changed since, or it changed something that cannot be reversed yet.",
    world_time_id_invalid: "That time is not available. Choose another.",
}

const label = (component: string): string =>
    COMPONENT_LABEL[component] ?? component.replace(/_/g, " ")

const show = (value: unknown): string =>
    value === null || value === undefined ? "none" : typeof value === "string" ? value : JSON.stringify(value)

// /app/:campaignId/events/new — record a narrative event (editors only).
export function RecordEventPage() {
    const { campaignId = "" } = useParams()
    const navigate = useNavigate()
    const { reload } = useSession()
    const canEdit = useCampaignCapability(campaignId, "canon.edit")
    const headingRef = usePageArrival(true)
    const [type, setType] = useState("other")
    const [name, setName] = useState("")
    const [details, setDetails] = useState("")
    const [timeId, setTimeId] = useState("")
    const [errors, setErrors] = useState<FieldError[]>([])
    const [attempt, setAttempt] = useState(0)
    const dirty = name !== "" || details !== "" || timeId !== ""
    const guard = useUnsavedChangesGuard(dirty)
    const mutation = useAuthoringMutation<
        { type: string; name: string; details: string | null; timeId: string },
        EventReceipt
    >({
        scopeKey: `record-event:${campaignId}`,
        request: (body, ctx) =>
            recordEvent(
                campaignId,
                {
                    world_time_id: body.timeId,
                    event_type_code: body.type,
                    name: body.name,
                    details: body.details,
                },
                ctx,
            ),
        onSuccess: (receipt) => {
            guard.release()
            void navigate(`${base(campaignId)}/events/${encodeURIComponent(receipt.event_id)}`, {
                replace: true,
                state: { announce: "Event recorded" },
            })
        },
    })
    const error = mutation.status.kind === "error" ? mutation.status.error : null
    const message = error?.code ? (CODE_MESSAGE[error.code] ?? null) : null
    const errorFor = (id: string) => errors.find((e) => e.fieldId === id)?.message ?? null

    function submit() {
        const found: FieldError[] = []
        if (name.trim() === "") found.push({ fieldId: "event-name", message: "Enter what happened." })
        else if (name.trim().length > NAME_MAX)
            found.push({ fieldId: "event-name", message: `Must be ${NAME_MAX} characters or fewer.` })
        if (details.trim().length > DETAILS_MAX)
            found.push({ fieldId: "event-details", message: `Must be ${DETAILS_MAX} characters or fewer.` })
        if (timeId === "") found.push({ fieldId: "event-time", message: "Choose when it happened." })
        setErrors(found)
        setAttempt((n) => n + 1)
        if (found.length > 0) return
        mutation.submit({
            type,
            name: name.trim(),
            details: details.trim() === "" ? null : details.trim(),
            timeId,
        })
    }

    return (
        <section className="authoring-page" aria-labelledby="record-event-heading">
            <p className="authoring-page__breadcrumb">
                <Link to={base(campaignId)}>Campaign Home</Link>
            </p>
            <h1 id="record-event-heading" ref={headingRef} tabIndex={-1}>
                Record an event
            </h1>
            {!canEdit ? (
                <p role="alert">You do not have permission to record events in this campaign.</p>
            ) : (
                <>
                    <AuthoringForm label="Record an event" onSubmit={submit}>
                        <ErrorSummary errors={errors} attempt={attempt} />
                        {message !== null ? (
                            <p role="alert">{message}</p>
                        ) : error !== null ? (
                            <MutationStatusMessage error={error} onRetry={mutation.retry} onCheckSession={reload} />
                        ) : null}
                        <SelectField id="event-type" label="Kind" value={type} options={TYPE_OPTIONS} onChange={setType} />
                        <TextField
                            id="event-name"
                            label="What happened"
                            hint="Visible to everyone in the campaign."
                            value={name}
                            onChange={setName}
                            required
                            maxLength={NAME_MAX}
                            error={errorFor("event-name")}
                        />
                        <TextAreaField
                            id="event-details"
                            label="GM notes"
                            hint="Visible only to people who can edit canon."
                            value={details}
                            onChange={setDetails}
                            maxLength={DETAILS_MAX}
                            error={errorFor("event-details")}
                        />
                        <WorldTimePicker
                            campaignId={campaignId}
                            id="event-time"
                            label="When"
                            value={timeId}
                            onChange={setTimeId}
                            required
                            error={errorFor("event-time")}
                        />
                        <FormActions
                            pending={mutation.status.kind === "pending"}
                            saveLabel="Record event"
                            pendingLabel="Recording…"
                            onCancel={() => void navigate(base(campaignId))}
                        />
                    </AuthoringForm>
                    <ConfirmDialog
                        open={guard.blocked}
                        title="Discard this event?"
                        description="You have entered details that have not been saved."
                        confirmLabel="Discard"
                        cancelLabel="Keep editing"
                        onConfirm={guard.discard}
                        onCancel={guard.stay}
                    />
                </>
            )}
        </section>
    )
}

// /app/:campaignId/events/:eventId — an event with its effects, and Void / Correct.
export function EventDetailPage() {
    const { campaignId = "", eventId = "" } = useParams()
    const canEdit = useCampaignCapability(campaignId, "canon.edit")
    const event = useAuthoringResource<EventAuthoringView>(eventPath(campaignId, eventId))
    const preview = useAuthoringResource<CorrectionPreview>(correctionPreviewPath(campaignId, eventId))
    const headingRef = usePageArrival(event.state.kind === "ready")
    const data = event.state.kind === "ready" ? event.state.data : null
    const plan = preview.state.kind === "ready" ? preview.state.data : null

    return (
        <section className="authoring-page" aria-labelledby="event-heading">
            <p className="authoring-page__breadcrumb">
                <Link to={base(campaignId)}>Campaign Home</Link>
            </p>
            <h1 id="event-heading" ref={headingRef} tabIndex={-1}>
                {data !== null ? data.name : "Event"}
            </h1>
            {!canEdit ? (
                <p role="alert">You do not have permission to view this event.</p>
            ) : event.state.kind === "loading" ? (
                <p role="status">Loading event…</p>
            ) : data === null ? (
                <p role="alert">This event does not exist, or you do not have access to it.</p>
            ) : (
                <EventBody
                    campaignId={campaignId}
                    event={data}
                    plan={plan}
                    refetch={async () => {
                        await event.refetch()
                        await preview.refetch()
                    }}
                />
            )}
        </section>
    )
}

function EventBody({
    campaignId,
    event,
    plan,
    refetch,
}: {
    campaignId: string
    event: EventAuthoringView
    plan: CorrectionPreview | null
    refetch: () => Promise<void>
}) {
    const link = (id: string) => `${base(campaignId)}/events/${encodeURIComponent(id)}`
    const blocked = plan !== null ? plan.effects.filter((e) => !e.reversible) : []
    return (
        <>
            <p>
                Status: <strong>{event.status}</strong> · When: {event.world_time} · Kind:{" "}
                {event.event_type_code.replace(/_/g, " ")}
            </p>
            {event.details !== null ? <p className="authoring-note">GM notes: {event.details}</p> : null}
            {event.corrects_event_id !== null ? (
                <p>
                    Relates to <Link to={link(event.corrects_event_id)}>an earlier event</Link>.
                </p>
            ) : null}
            {event.participants.length > 0 ? (
                <p>Involved: {event.participants.map((p) => p.name).join(", ")}</p>
            ) : null}

            <section aria-labelledby="effects-heading">
                <h2 id="effects-heading">What it changed</h2>
                {event.effects.length === 0 ? (
                    <p>Nothing: this event only records what happened.</p>
                ) : (
                    <ul className="authoring-choice-list">
                        {event.effects.map((effect, index) => (
                            <li key={index}>
                                {label(effect.component)}: {show(effect.previous)} to {show(effect.new)}
                                {plan !== null && plan.effects[index] !== undefined
                                    ? plan.effects[index]!.reversible
                                        ? " (can be reversed)"
                                        : " (cannot be reversed)"
                                    : ""}
                            </li>
                        ))}
                    </ul>
                )}
            </section>

            {event.correction !== null ? (
                <section aria-labelledby="correction-heading">
                    <h2 id="correction-heading">Correction</h2>
                    <p>
                        This event was {event.correction.kind === "void" ? "voided" : "corrected"}: {event.correction.reason}
                    </p>
                    <p>
                        <Link to={link(event.correction.correcting_event_id)}>The correcting event</Link>
                        {event.correction.replacement_event_id !== null ? (
                            <>
                                {" · "}
                                <Link to={link(event.correction.replacement_event_id)}>The replacement</Link>
                            </>
                        ) : null}
                    </p>
                </section>
            ) : plan !== null && plan.is_correction ? (
                <p className="authoring-note">This event is a correction and cannot itself be corrected.</p>
            ) : event.status === "recorded" && plan !== null ? (
                <Corrections
                    campaignId={campaignId}
                    event={event}
                    canCorrect={plan.can_correct}
                    blockedReasons={blocked.map((e) => e.reason)}
                    refetch={refetch}
                />
            ) : null}
        </>
    )
}

function Corrections({
    campaignId,
    event,
    canCorrect,
    blockedReasons,
    refetch,
}: {
    campaignId: string
    event: EventAuthoringView
    canCorrect: boolean
    blockedReasons: (string | null)[]
    refetch: () => Promise<void>
}) {
    const { reload } = useSession()
    const announce = useAnnounce()
    const [dialog, setDialog] = useState<"void" | "correct" | null>(null)
    const [reason, setReason] = useState("")
    const [reasonError, setReasonError] = useState<string | null>(null)
    const [name, setName] = useState(event.name)
    const [details, setDetails] = useState(event.details ?? "")
    const [timeId, setTimeId] = useState("")
    const [nameError, setNameError] = useState<string | null>(null)
    const mutation = useAuthoringMutation<"void" | "correct", CorrectionReceipt>({
        scopeKey: `correct-event:${event.event_id}`,
        request: (action, ctx) =>
            action === "void"
                ? voidEvent(campaignId, event.event_id, { reason: reason.trim() }, ctx)
                : correctEvent(
                      campaignId,
                      event.event_id,
                      {
                          reason: reason.trim(),
                          replacement: {
                              event_type_code: event.event_type_code === "session_narrative" ? "session_narrative" : "other",
                              name: name.trim(),
                              details: details.trim() === "" ? null : details.trim(),
                              world_time_id: timeId === "" ? null : timeId,
                          },
                      },
                      ctx,
                  ),
        onSuccess: async () => {
            const done = dialog === "void" ? "Event voided" : "Event corrected"
            setDialog(null)
            setReason("")
            await refetch()
            announce(done)
        },
    })
    const error = mutation.status.kind === "error" ? mutation.status.error : null
    const message = error?.code ? (CODE_MESSAGE[error.code] ?? null) : null
    const reasons = [...new Set(blockedReasons.filter((r): r is string => r !== null))]

    function confirm() {
        if (reason.trim() === "") {
            setReasonError("Enter a reason.")
            return
        }
        if (dialog === "correct" && (name.trim() === "" || name.trim().length > NAME_MAX)) {
            setNameError("Enter what really happened, up to 500 characters.")
            return
        }
        if (dialog !== null) mutation.submit(dialog)
    }

    return (
        <section aria-labelledby="corrections-heading">
            <h2 id="corrections-heading">Correct this event</h2>
            {canCorrect ? (
                <p>
                    Voiding or correcting keeps this event in the history and reverses what it changed.
                </p>
            ) : (
                <p className="authoring-note">
                    This event cannot be corrected automatically
                    {reasons.length > 0
                        ? `: ${reasons.map((r) => REASON_TEXT[r] ?? r).join("; ")}`
                        : ""}
                    .
                </p>
            )}
            <p className="authoring-actions">
                <button
                    type="button"
                    className="authoring-button"
                    disabled={!canCorrect}
                    onClick={() => {
                        mutation.reset()
                        setDialog("void")
                    }}
                >
                    Void event
                </button>
                <button
                    type="button"
                    className="authoring-button"
                    disabled={!canCorrect}
                    onClick={() => {
                        mutation.reset()
                        setDialog("correct")
                    }}
                >
                    Correct event
                </button>
            </p>
            <ConfirmDialog
                open={dialog !== null}
                title={dialog === "correct" ? "Correct this event?" : "Void this event?"}
                description={
                    dialog === "correct"
                        ? "What it changed is reversed and the event you enter below takes its place. The original stays in the history."
                        : "What it changed is reversed and the event is marked as voided. It stays in the history."
                }
                confirmLabel={dialog === "correct" ? "Correct event" : "Void event"}
                pending={mutation.status.kind === "pending"}
                reason={{
                    label: "Reason",
                    required: true,
                    value: reason,
                    onChange: (value) => {
                        setReason(value)
                        setReasonError(null)
                    },
                    error: reasonError,
                }}
                error={
                    error?.kind === "stale" ? (
                        <StaleWriteNotice
                            onLoadLatest={() => {
                                mutation.reset()
                                setDialog(null)
                                void refetch()
                            }}
                        />
                    ) : message !== null ? (
                        <p role="alert">{message}</p>
                    ) : error !== null ? (
                        <MutationStatusMessage error={error} onRetry={mutation.retry} onCheckSession={reload} />
                    ) : null
                }
                onConfirm={confirm}
                onCancel={() => {
                    setDialog(null)
                    setReason("")
                    setReasonError(null)
                    setNameError(null)
                    mutation.reset()
                }}
            >
                {dialog === "correct" ? (
                    <>
                        <TextField
                            id="replacement-name"
                            label="What really happened"
                            value={name}
                            onChange={(value) => {
                                setName(value)
                                setNameError(null)
                            }}
                            required
                            maxLength={NAME_MAX}
                            error={nameError}
                        />
                        <TextAreaField
                            id="replacement-details"
                            label="GM notes"
                            value={details}
                            onChange={setDetails}
                            maxLength={DETAILS_MAX}
                        />
                        <WorldTimePicker
                            campaignId={campaignId}
                            id="replacement-time"
                            label="When"
                            hint="Leave empty to keep the original time."
                            value={timeId}
                            onChange={setTimeId}
                        />
                    </>
                ) : null}
            </ConfirmDialog>
        </section>
    )
}
