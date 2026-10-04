import { useState } from "react"
import { Link, useNavigate, useParams } from "react-router"
import { createTimeline } from "../api/timelines"
import { worldPath } from "../api/worlds"
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
import type { CreateTimelineRequest, CreateTimelineResponse } from "../types/timelineAuthoring"
import type { WorldDetail } from "../types/worldAuthoring"
import { DESCRIPTION_MAX, NAME_MAX, validateDescription, validateName } from "../utils/authoringValidation"
import "../components/authoring/authoring.css"

export function CreateTimelinePage() {
    const { worldId = "" } = useParams()
    const { state } = useAuthoringResource<WorldDetail>(worldPath(worldId))
    const headingRef = usePageArrival(state.kind !== "loading")

    return (
        <main className="app-main">
            <div className="authoring-page">
                <p className="authoring-page__breadcrumb">
                    <Link to="/worlds">Worlds</Link>
                    {" / "}
                    <Link to={`/worlds/${worldId}`}>{state.kind === "ready" ? state.data.name : "World"}</Link>
                </p>
                <h1 ref={headingRef} tabIndex={-1}>
                    New timeline
                </h1>
                {state.kind === "loading" ? (
                    <p role="status">Loading world…</p>
                ) : state.kind !== "ready" ? (
                    <p role="alert">This world does not exist, or you do not have access to it.</p>
                ) : !state.data.available_actions.includes("create_timeline") ? (
                    <p role="alert">
                        Timelines cannot be added to this world right now.{" "}
                        <Link to={`/worlds/${worldId}`}>Back to the world</Link>
                    </p>
                ) : (
                    <>
                        <p className="authoring-page__lead">
                            A new timeline starts as its own history. To split a timeline from an
                            existing one, create a branch instead.
                        </p>
                        <CreateTimelineForm worldId={worldId} />
                    </>
                )}
            </div>
        </main>
    )
}

function CreateTimelineForm({ worldId }: { worldId: string }) {
    const navigate = useNavigate()
    const { reload } = useSession()
    const [name, setName] = useState("")
    const [description, setDescription] = useState("")
    const [errors, setErrors] = useState<FieldError[]>([])
    const [attempt, setAttempt] = useState(0)
    const guard = useUnsavedChangesGuard(name !== "" || description !== "")

    const mutation = useAuthoringMutation<CreateTimelineRequest, CreateTimelineResponse>({
        scopeKey: `create-timeline:${worldId}`,
        request: (body, ctx) => createTimeline(worldId, body, ctx),
        onSuccess: (result) => {
            guard.release()
            void navigate(`/worlds/${worldId}/timelines/${result.timeline_id}`, {
                state: { announce: "Timeline created" },
            })
        },
    })
    const error = mutation.status.kind === "error" ? mutation.status.error : null

    function handleSubmit() {
        const found: FieldError[] = []
        const nameError = validateName(name)
        if (nameError) found.push({ fieldId: "timeline-new-name", message: nameError })
        const descriptionError = validateDescription(description)
        if (descriptionError) found.push({ fieldId: "timeline-new-description", message: descriptionError })
        setErrors(found)
        setAttempt((n) => n + 1)
        if (found.length > 0) return
        mutation.submit({
            name: name.trim(),
            description: description.trim() === "" ? null : description.trim(),
        })
    }

    const errorFor = (id: string) => errors.find((e) => e.fieldId === id)?.message ?? null

    return (
        <>
            <AuthoringForm label="Create timeline" onSubmit={handleSubmit}>
                <ErrorSummary errors={errors} attempt={attempt} />
                {error !== null ? (
                    <MutationStatusMessage error={error} onRetry={mutation.retry} onCheckSession={reload} />
                ) : null}
                <TextField
                    id="timeline-new-name"
                    label="Timeline name"
                    value={name}
                    onChange={setName}
                    required
                    maxLength={NAME_MAX}
                    error={errorFor("timeline-new-name")}
                />
                <TextAreaField
                    id="timeline-new-description"
                    label="Description"
                    value={description}
                    onChange={setDescription}
                    maxLength={DESCRIPTION_MAX}
                    error={errorFor("timeline-new-description")}
                />
                <FormActions
                    pending={mutation.status.kind === "pending"}
                    saveLabel="Create timeline"
                    pendingLabel="Creating…"
                    onCancel={() => void navigate(`/worlds/${worldId}`)}
                />
            </AuthoringForm>
            <ConfirmDialog
                open={guard.blocked}
                title="Discard unsaved changes?"
                description="You have entered details for a new timeline that have not been saved."
                confirmLabel="Discard changes"
                onConfirm={guard.discard}
                onCancel={guard.stay}
                cancelLabel="Keep editing"
            />
        </>
    )
}
