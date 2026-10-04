import { useState } from "react"
import { Link, useNavigate, useParams } from "react-router"
import { updateWorld, worldPath } from "../api/worlds"
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
    UpdateWorldRequest,
    WorldDetail,
    WorldMutationResponse,
} from "../types/worldAuthoring"
import {
    DESCRIPTION_MAX,
    NAME_MAX,
    validateDescription,
    validateName,
} from "../utils/authoringValidation"
import "../components/authoring/authoring.css"

export function EditWorldPage() {
    const { worldId = "" } = useParams()
    const { state, refetch } = useAuthoringResource<WorldDetail>(worldPath(worldId))
    const headingRef = usePageArrival(state.kind === "ready")
    // The user's unsaved values at the moment a stale write was detected. They
    // stay visible after the form reloads from the server, so nothing typed is
    // lost, and are dropped on save or cancel.
    const [keptChanges, setKeptChanges] = useState<{ name: string; description: string } | null>(
        null,
    )

    return (
        <main className="app-main">
            <div className="authoring-page">
                <p className="authoring-page__breadcrumb">
                    <Link to="/worlds">Worlds</Link>
                    {state.kind === "ready" ? (
                        <>
                            {" / "}
                            <Link to={`/worlds/${worldId}`}>{state.data.name}</Link>
                        </>
                    ) : null}
                </p>
                <h1 ref={headingRef} tabIndex={-1}>
                    Edit world
                </h1>
                {state.kind === "loading" ? (
                    <p role="status">Loading world…</p>
                ) : state.kind === "unavailable" || state.kind === "denied" ? (
                    <p role="alert">This world does not exist, or you do not have access to it.</p>
                ) : state.kind === "error" ? (
                    <p role="alert">The world could not be loaded. Try reloading the page.</p>
                ) : !state.data.available_actions.includes("update") ? (
                    <p role="alert">
                        This world cannot be edited right now.{" "}
                        <Link to={`/worlds/${worldId}`}>Back to the world</Link>
                    </p>
                ) : (
                    <EditWorldForm
                        key={state.data.row_version}
                        world={state.data}
                        refreshing={state.refreshing}
                        keptChanges={keptChanges}
                        onKeepChanges={setKeptChanges}
                        refetch={refetch}
                    />
                )}
            </div>
        </main>
    )
}

interface EditWorldFormProps {
    world: WorldDetail
    refreshing: boolean
    keptChanges: { name: string; description: string } | null
    onKeepChanges: (changes: { name: string; description: string } | null) => void
    refetch: () => Promise<void>
}

function EditWorldForm({
    world,
    refreshing,
    keptChanges,
    onKeepChanges,
    refetch,
}: EditWorldFormProps) {
    const navigate = useNavigate()
    const { reload } = useSession()
    const [name, setName] = useState(world.name)
    const [description, setDescription] = useState(world.description ?? "")
    const [errors, setErrors] = useState<FieldError[]>([])
    const [attempt, setAttempt] = useState(0)

    const dirty = name !== world.name || description !== (world.description ?? "")
    const guard = useUnsavedChangesGuard(dirty)

    const mutation = useAuthoringMutation<UpdateWorldRequest, WorldMutationResponse>({
        scopeKey: `edit-world:${world.world_id}:${world.row_version}`,
        request: (body, ctx) => updateWorld(world.world_id, body, ctx),
        onSuccess: () => {
            guard.release()
            onKeepChanges(null)
            void navigate(`/worlds/${world.world_id}`, { state: { announce: "World saved" } })
        },
    })

    const pending = mutation.status.kind === "pending"
    const error = mutation.status.kind === "error" ? mutation.status.error : null

    function handleSubmit() {
        const found: FieldError[] = []
        const nameError = validateName(name)
        if (nameError) found.push({ fieldId: "edit-world-name", message: nameError })
        const descriptionError = validateDescription(description)
        if (descriptionError) {
            found.push({ fieldId: "edit-world-description", message: descriptionError })
        }
        setErrors(found)
        setAttempt((current) => current + 1)
        if (found.length > 0) {
            return
        }
        mutation.submit({
            expected_row_version: world.row_version,
            name: name.trim(),
            description: description.trim() === "" ? null : description.trim(),
        })
    }

    function errorFor(fieldId: string): string | null {
        return errors.find((e) => e.fieldId === fieldId)?.message ?? null
    }

    return (
        <>
            {keptChanges !== null ? (
                <section aria-label="Your unsaved changes" className="authoring-message authoring-message--warning">
                    <div>
                        <h2>Your unsaved changes</h2>
                        <p>
                            The form below now shows the latest version. These are the values you
                            had entered:
                        </p>
                        <dl className="authoring-fact-list">
                            <dt>Name</dt>
                            <dd>{keptChanges.name}</dd>
                            <dt>Description</dt>
                            <dd>{keptChanges.description || "(empty)"}</dd>
                        </dl>
                        <button
                            type="button"
                            className="authoring-button"
                            onClick={() => {
                                setName(keptChanges.name)
                                setDescription(keptChanges.description)
                                onKeepChanges(null)
                            }}
                        >
                            Re-apply my changes
                        </button>
                    </div>
                </section>
            ) : null}

            <AuthoringForm label="Edit world" onSubmit={handleSubmit}>
                <ErrorSummary errors={errors} attempt={attempt} />
                {error !== null && error.kind === "stale" ? (
                    <StaleWriteNotice
                        loading={refreshing}
                        onLoadLatest={() => {
                            onKeepChanges({ name, description })
                            mutation.reset()
                            void refetch()
                        }}
                        yourChanges={
                            <dl className="authoring-fact-list">
                                <dt>Name</dt>
                                <dd>{name}</dd>
                                <dt>Description</dt>
                                <dd>{description || "(empty)"}</dd>
                            </dl>
                        }
                    />
                ) : error !== null ? (
                    <MutationStatusMessage
                        error={error}
                        onRetry={mutation.retry}
                        onCheckSession={reload}
                    />
                ) : null}

                <TextField
                    id="edit-world-name"
                    label="World name"
                    value={name}
                    onChange={setName}
                    required
                    maxLength={NAME_MAX}
                    error={errorFor("edit-world-name")}
                />
                <TextAreaField
                    id="edit-world-description"
                    label="Description"
                    value={description}
                    onChange={setDescription}
                    maxLength={DESCRIPTION_MAX}
                    error={errorFor("edit-world-description")}
                />
                <FormActions
                    pending={pending}
                    onCancel={() => void navigate(`/worlds/${world.world_id}`)}
                />
            </AuthoringForm>

            <ConfirmDialog
                open={guard.blocked}
                title="Discard unsaved changes?"
                description="You have edits to this world that have not been saved."
                confirmLabel="Discard changes"
                onConfirm={guard.discard}
                onCancel={guard.stay}
                cancelLabel="Keep editing"
            />
        </>
    )
}
