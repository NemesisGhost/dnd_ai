import { useState } from "react"
import { Link, useNavigate, useParams } from "react-router"
import { branchPointsPath, createBranch, timelinePath } from "../api/timelines"
import { ConfirmDialog } from "../components/authoring/ConfirmDialog"
import { RadioGroupField, SelectField, TextAreaField, TextField } from "../components/authoring/fields"
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
import type {
    BranchPointListResponse,
    BranchPointOption,
    BranchPointRequest,
    CreateBranchRequest,
    CreateBranchResponse,
    TimelineDetail,
} from "../types/timelineAuthoring"
import {
    DESCRIPTION_MAX,
    LABEL_MAX,
    NAME_MAX,
    fieldForErrorCode,
    validateDescription,
    validateLabel,
    validateName,
} from "../utils/authoringValidation"
import { describeBranchPoint } from "../utils/branchPoints"
import "../components/authoring/authoring.css"

export function CreateTimelineBranchPage() {
    const { worldId = "", timelineId = "" } = useParams()
    const timeline = useAuthoringResource<TimelineDetail>(timelinePath(worldId, timelineId))
    const points = useAuthoringResource<BranchPointListResponse>(
        branchPointsPath(worldId, timelineId),
    )
    const ready = timeline.state.kind !== "loading" && points.state.kind !== "loading"
    const headingRef = usePageArrival(ready)

    return (
        <div className="world-page">
            <div className="authoring-page">
                <p className="authoring-page__breadcrumb">
                    <Link to="/worlds">Worlds</Link>
                    {" / "}
                    <Link to={`/worlds/${worldId}/timelines/${timelineId}`}>
                        {timeline.state.kind === "ready" ? timeline.state.data.name : "Timeline"}
                    </Link>
                </p>
                <h1 ref={headingRef} tabIndex={-1}>
                    Create a branch
                </h1>
                {!ready ? (
                    <p role="status">Loading…</p>
                ) : timeline.state.kind !== "ready" ? (
                    <p role="alert">This timeline does not exist, or you do not have access to it.</p>
                ) : !timeline.state.data.available_actions.includes("create_branch") ? (
                    <p role="alert">
                        This timeline cannot be branched right now. It may be archived, or its world may
                        be.{" "}
                        <Link to={`/worlds/${worldId}/timelines/${timelineId}`}>Back to the timeline</Link>
                    </p>
                ) : (
                    <BranchForm
                        worldId={worldId}
                        parentId={timelineId}
                        options={points.state.kind === "ready" ? points.state.data.items : []}
                    />
                )}
            </div>
        </div>
    )
}

interface BranchFormProps {
    worldId: string
    parentId: string
    options: BranchPointOption[]
}

function BranchForm({ worldId, parentId, options }: BranchFormProps) {
    const navigate = useNavigate()
    const { reload } = useSession()
    const [name, setName] = useState("")
    const [description, setDescription] = useState("")
    const [kind, setKind] = useState<"latest" | "existing_world_time">("latest")
    const [label, setLabel] = useState("")
    const [pointId, setPointId] = useState("")
    const [errors, setErrors] = useState<FieldError[]>([])
    const [attempt, setAttempt] = useState(0)
    const guard = useUnsavedChangesGuard(name !== "" || description !== "" || label !== "" || pointId !== "")

    const mutation = useAuthoringMutation<CreateBranchRequest, CreateBranchResponse>({
        scopeKey: `branch:${parentId}`,
        request: (body, ctx) => createBranch(worldId, parentId, body, ctx),
        onSuccess: (result) => {
            guard.release()
            void navigate(`/worlds/${worldId}/timelines/${result.timeline_id}`, {
                state: { announce: "Branch created" },
            })
        },
    })
    const error = mutation.status.kind === "error" ? mutation.status.error : null
    const serverField = error ? fieldForErrorCode(error.code) : null
    const serverErrors: FieldError[] =
        serverField === "branch-point"
            ? [{ fieldId: "branch-point", message: "That branch point is not valid for this timeline. Choose another." }]
            : []

    function handleSubmit() {
        const found: FieldError[] = []
        const nameError = validateName(name)
        if (nameError) found.push({ fieldId: "branch-name", message: nameError })
        const descriptionError = validateDescription(description)
        if (descriptionError) found.push({ fieldId: "branch-description", message: descriptionError })
        let branchPoint: BranchPointRequest | null = null
        if (kind === "latest") {
            const labelError = validateLabel(label)
            if (labelError) found.push({ fieldId: "branch-label", message: labelError })
            else branchPoint = { kind: "latest", label: label.trim() }
        } else if (pointId === "") {
            found.push({ fieldId: "branch-point", message: "Choose a point in the timeline's history." })
        } else {
            branchPoint = { kind: "existing_world_time", world_time_id: pointId }
        }
        setErrors(found)
        setAttempt((n) => n + 1)
        if (found.length > 0 || branchPoint === null) return
        mutation.submit({
            name: name.trim(),
            description: description.trim() === "" ? null : description.trim(),
            branch_point: branchPoint,
        })
    }

    const all = [...errors, ...serverErrors]
    const errorFor = (id: string) => all.find((e) => e.fieldId === id)?.message ?? null

    return (
        <>
            <p className="authoring-page__lead">
                A branch splits off from this timeline at one moment and inherits its history up to
                that point. Events recorded afterwards on either timeline stay separate.
            </p>
            <AuthoringForm label="Create branch" onSubmit={handleSubmit}>
                <ErrorSummary errors={all} attempt={attempt} />
                {error !== null && serverField === null ? (
                    <MutationStatusMessage error={error} onRetry={mutation.retry} onCheckSession={reload} />
                ) : null}
                <TextField
                    id="branch-name"
                    label="Branch name"
                    value={name}
                    onChange={setName}
                    required
                    maxLength={NAME_MAX}
                    error={errorFor("branch-name")}
                />
                <TextAreaField
                    id="branch-description"
                    label="Description"
                    value={description}
                    onChange={setDescription}
                    maxLength={DESCRIPTION_MAX}
                    error={errorFor("branch-description")}
                />
                <RadioGroupField
                    legend="Branch from"
                    value={kind}
                    onChange={(value) => setKind(value as "latest" | "existing_world_time")}
                    options={[
                        {
                            value: "latest",
                            label: "The present state of this timeline",
                            description: "Creates a new labeled moment just after everything recorded so far.",
                        },
                        {
                            value: "existing_world_time",
                            label: "An earlier moment in its history",
                            description:
                                options.length === 0
                                    ? "Unavailable: this timeline has no recorded history to branch from yet."
                                    : "Choose one of the moments events have been recorded at.",
                        },
                    ]}
                />
                {kind === "latest" ? (
                    <TextField
                        id="branch-label"
                        label="Label for the branch point"
                        hint="A short description of the moment, for example “The night the bridge fell”."
                        value={label}
                        onChange={setLabel}
                        required
                        maxLength={LABEL_MAX}
                        error={errorFor("branch-label")}
                    />
                ) : (
                    <SelectField
                        id="branch-point"
                        label="Branch point"
                        value={pointId}
                        placeholder="Choose a moment"
                        required
                        disabled={options.length === 0}
                        options={options.map((o) => ({
                            value: o.world_time_id,
                            label: describeBranchPoint(o),
                        }))}
                        onChange={setPointId}
                        error={errorFor("branch-point")}
                    />
                )}
                <FormActions
                    pending={mutation.status.kind === "pending"}
                    saveLabel="Create branch"
                    pendingLabel="Creating…"
                    onCancel={() => void navigate(`/worlds/${worldId}/timelines/${parentId}`)}
                />
            </AuthoringForm>
            <ConfirmDialog
                open={guard.blocked}
                title="Discard unsaved changes?"
                description="You have entered details for a new branch that have not been saved."
                confirmLabel="Discard changes"
                onConfirm={guard.discard}
                onCancel={guard.stay}
                cancelLabel="Keep editing"
            />
        </>
    )
}
