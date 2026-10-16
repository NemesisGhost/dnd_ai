import { useState } from "react"
import { Link, useNavigate } from "react-router"
import { updateWorld } from "../api/worlds"
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

interface EditWorldPageProps {
    // The authorized world read model the route guard (App.tsx EditWorldRoute)
    // already loaded and confirmed to carry the server's `update` action. This
    // page never mounts for a world the caller may not edit.
    world: WorldDetail
    refreshing: boolean
    refetch: () => Promise<void>
}

export function EditWorldPage({ world, refreshing, refetch }: EditWorldPageProps) {
    const headingRef = usePageArrival(true)
    // The user's unsaved values at the moment a stale write was detected. They
    // stay visible after the form reloads from the server, so nothing typed is
    // lost, and are dropped on save or cancel.
    const [keptChanges, setKeptChanges] = useState<{ name: string; description: string } | null>(
        null,
    )

    return (
        <div className="world-page">
            <div className="authoring-page">
                <p className="authoring-page__breadcrumb">
                    <Link to="/worlds">Worlds</Link>
                    {" / "}
                    <Link to={`/worlds/${world.world_id}`}>{world.name}</Link>
                </p>
                <h1 ref={headingRef} tabIndex={-1}>
                    Edit world
                </h1>
                <EditWorldForm
                    key={world.row_version}
                    world={world}
                    refreshing={refreshing}
                    keptChanges={keptChanges}
                    onKeepChanges={setKeptChanges}
                    refetch={refetch}
                />
            </div>
        </div>
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
