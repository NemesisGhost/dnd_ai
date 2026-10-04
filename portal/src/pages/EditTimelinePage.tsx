import { useState } from "react"
import { Link, useNavigate, useParams } from "react-router"
import { timelinePath, updateTimeline } from "../api/timelines"
import { ConfirmDialog } from "../components/authoring/ConfirmDialog"
import { TextAreaField, TextField } from "../components/authoring/fields"
import {
    AuthoringForm,
    ErrorSummary,
    FormActions,
    MutationStatusMessage,
    StaleWriteNotice,
} from "../components/authoring/feedback"
import type { FieldError } from "../components/authoring/feedback"
import { useSession } from "../context/SessionContext"
import { useAuthoringMutation } from "../hooks/useAuthoringMutation"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import { usePageArrival } from "../hooks/usePageArrival"
import { useUnsavedChangesGuard } from "../hooks/useUnsavedChangesGuard"
import type {
    TimelineDetail,
    TimelineMutationResponse,
    UpdateTimelineRequest,
} from "../types/timelineAuthoring"
import { DESCRIPTION_MAX, NAME_MAX, validateDescription, validateName } from "../utils/authoringValidation"
import "../components/authoring/authoring.css"

interface Values {
    name: string
    description: string
}

export function EditTimelinePage() {
    const { worldId = "", timelineId = "" } = useParams()
    const { state, refetch } = useAuthoringResource<TimelineDetail>(timelinePath(worldId, timelineId))
    const headingRef = usePageArrival(state.kind === "ready")
    const [kept, setKept] = useState<Values | null>(null)

    return (
        <main className="app-main">
            <div className="authoring-page">
                <p className="authoring-page__breadcrumb">
                    <Link to="/worlds">Worlds</Link>
                    {" / "}
                    <Link to={`/worlds/${worldId}/timelines/${timelineId}`}>Timeline</Link>
                </p>
                <h1 ref={headingRef} tabIndex={-1}>
                    Edit timeline
                </h1>
                {state.kind === "loading" ? (
                    <p role="status">Loading timeline…</p>
                ) : state.kind === "unavailable" || state.kind === "denied" ? (
                    <p role="alert">This timeline does not exist, or you do not have access to it.</p>
                ) : state.kind === "error" ? (
                    <p role="alert">The timeline could not be loaded. Try reloading the page.</p>
                ) : !state.data.available_actions.includes("update") ? (
                    <p role="alert">
                        This timeline cannot be edited right now.{" "}
                        <Link to={`/worlds/${worldId}/timelines/${timelineId}`}>Back to the timeline</Link>
                    </p>
                ) : (
                    <EditTimelineForm
                        key={state.data.row_version}
                        worldId={worldId}
                        timeline={state.data}
                        refreshing={state.refreshing}
                        kept={kept}
                        onKeep={setKept}
                        refetch={refetch}
                    />
                )}
            </div>
        </main>
    )
}

interface FormProps {
    worldId: string
    timeline: TimelineDetail
    refreshing: boolean
    kept: Values | null
    onKeep: (values: Values | null) => void
    refetch: () => Promise<void>
}

function EditTimelineForm({ worldId, timeline, refreshing, kept, onKeep, refetch }: FormProps) {
    const navigate = useNavigate()
    const { reload } = useSession()
    const [name, setName] = useState(timeline.name)
    const [description, setDescription] = useState(timeline.description ?? "")
    const [errors, setErrors] = useState<FieldError[]>([])
    const [attempt, setAttempt] = useState(0)
    const guard = useUnsavedChangesGuard(
        name !== timeline.name || description !== (timeline.description ?? ""),
    )
    const mutation = useAuthoringMutation<UpdateTimelineRequest, TimelineMutationResponse>({
        scopeKey: `edit-timeline:${timeline.timeline_id}:${timeline.row_version}`,
        request: (body, ctx) => updateTimeline(worldId, timeline.timeline_id, body, ctx),
        onSuccess: () => {
            guard.release()
            onKeep(null)
            void navigate(`/worlds/${worldId}/timelines/${timeline.timeline_id}`, {
                state: { announce: "Timeline saved" },
            })
        },
    })
    const error = mutation.status.kind === "error" ? mutation.status.error : null

    function handleSubmit() {
        const found: FieldError[] = []
        const nameError = validateName(name)
        if (nameError) found.push({ fieldId: "edit-timeline-name", message: nameError })
        const descriptionError = validateDescription(description)
        if (descriptionError) found.push({ fieldId: "edit-timeline-description", message: descriptionError })
        setErrors(found)
        setAttempt((n) => n + 1)
        if (found.length > 0) return
        mutation.submit({
            expected_row_version: timeline.row_version,
            name: name.trim(),
            description: description.trim() === "" ? null : description.trim(),
        })
    }

    const errorFor = (id: string) => errors.find((e) => e.fieldId === id)?.message ?? null
    const mine = (
        <dl className="authoring-fact-list">
            <dt>Name</dt>
            <dd>{name}</dd>
            <dt>Description</dt>
            <dd>{description || "(empty)"}</dd>
        </dl>
    )

    return (
        <>
            {kept !== null ? (
                <section aria-label="Your unsaved changes" className="authoring-message authoring-message--warning">
                    <div>
                        <h2>Your unsaved changes</h2>
                        <dl className="authoring-fact-list">
                            <dt>Name</dt>
                            <dd>{kept.name}</dd>
                            <dt>Description</dt>
                            <dd>{kept.description || "(empty)"}</dd>
                        </dl>
                        <button
                            type="button"
                            className="authoring-button"
                            onClick={() => {
                                setName(kept.name)
                                setDescription(kept.description)
                                onKeep(null)
                            }}
                        >
                            Re-apply my changes
                        </button>
                    </div>
                </section>
            ) : null}
            <AuthoringForm label="Edit timeline" onSubmit={handleSubmit}>
                <ErrorSummary errors={errors} attempt={attempt} />
                {error !== null && error.kind === "stale" ? (
                    <StaleWriteNotice
                        loading={refreshing}
                        yourChanges={mine}
                        onLoadLatest={() => {
                            onKeep({ name, description })
                            mutation.reset()
                            void refetch()
                        }}
                    />
                ) : error !== null ? (
                    <MutationStatusMessage error={error} onRetry={mutation.retry} onCheckSession={reload} />
                ) : null}
                <TextField
                    id="edit-timeline-name"
                    label="Timeline name"
                    value={name}
                    onChange={setName}
                    required
                    maxLength={NAME_MAX}
                    error={errorFor("edit-timeline-name")}
                />
                <TextAreaField
                    id="edit-timeline-description"
                    label="Description"
                    value={description}
                    onChange={setDescription}
                    maxLength={DESCRIPTION_MAX}
                    error={errorFor("edit-timeline-description")}
                />
                <FormActions
                    pending={mutation.status.kind === "pending"}
                    onCancel={() => void navigate(`/worlds/${worldId}/timelines/${timeline.timeline_id}`)}
                />
            </AuthoringForm>
            <ConfirmDialog
                open={guard.blocked}
                title="Discard unsaved changes?"
                description="You have edits to this timeline that have not been saved."
                confirmLabel="Discard changes"
                onConfirm={guard.discard}
                onCancel={guard.stay}
                cancelLabel="Keep editing"
            />
        </>
    )
}
