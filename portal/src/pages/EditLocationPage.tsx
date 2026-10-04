import { useState } from "react"
import { Link, useNavigate, useParams } from "react-router"
import {
    locationAuthoringPath,
    locationOptionsPath,
    updateLocation,
} from "../api/locationAuthoring"
import { ConfirmDialog } from "../components/authoring/ConfirmDialog"
import {
    AuthoringForm,
    ErrorSummary,
    FormActions,
    MutationStatusMessage,
    StaleWriteNotice,
} from "../components/authoring/feedback"
import type { FieldError } from "../components/authoring/feedback"
import { LocationFields } from "../components/authoring/LocationFields"
import { useSession } from "../context/SessionContext"
import { useAuthoringMutation } from "../hooks/useAuthoringMutation"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import { usePageArrival } from "../hooks/usePageArrival"
import { useUnsavedChangesGuard } from "../hooks/useUnsavedChangesGuard"
import type {
    LocationAuthoringView,
    LocationOptions,
    UpdateLocationBody,
} from "../types/locationAuthoring"
import { ERROR_CODE_MESSAGE, fieldForErrorCode } from "../utils/authoringValidation"
import { describeBlockedReason } from "../utils/blockedReason"
import {
    sameValues,
    toFieldsBody,
    validateLocationForm,
    valuesFromView,
} from "../utils/locationForm"
import type { LocationFormValues } from "../utils/locationForm"
import "../components/authoring/authoring.css"

// Edit a Location definition: /app/:campaignId/world/location/:entityId/edit.
// Loads the authoring read model (never timeline state) keyed by the URL, so the
// route reloads and deep-links on its own. A non-editor, a missing location, and
// another world's location all reach the same "unavailable" state.
export function EditLocationPage() {
    const { campaignId = "", entityId = "" } = useParams()
    const { state, refetch } = useAuthoringResource<LocationAuthoringView>(
        locationAuthoringPath(campaignId, entityId),
    )
    const options = useAuthoringResource<LocationOptions>(locationOptionsPath(campaignId))
    const ready = state.kind === "ready" && options.state.kind === "ready"
    const headingRef = usePageArrival(ready)
    // The user's unsaved values at the moment a stale write was detected. They
    // stay visible after the form reloads from the server and are dropped on save.
    const [keptChanges, setKeptChanges] = useState<LocationFormValues | null>(null)
    const detailPath = `/app/${encodeURIComponent(campaignId)}/world/location/${encodeURIComponent(entityId)}`

    return (
        <section className="authoring-page" aria-labelledby="edit-location-heading">
            <p className="authoring-page__breadcrumb">
                <Link to={`/app/${encodeURIComponent(campaignId)}/world`}>World</Link>
                {state.kind === "ready" ? (
                    <>
                        {" / "}
                        <Link to={detailPath}>{state.data.name}</Link>
                    </>
                ) : null}
            </p>
            <h1 id="edit-location-heading" ref={headingRef} tabIndex={-1}>
                Edit location
            </h1>
            {state.kind === "loading" || options.state.kind === "loading" ? (
                <p role="status">Loading location…</p>
            ) : state.kind === "unavailable" || state.kind === "denied" ? (
                <p role="alert">This location does not exist, or you do not have access to it.</p>
            ) : state.kind === "error" || options.state.kind !== "ready" ? (
                <p role="alert">The location could not be loaded. Try reloading the page.</p>
            ) : !state.data.available_actions.includes("update") ? (
                <NotEditable view={state.data} detailPath={detailPath} />
            ) : (
                <EditLocationForm
                    key={state.data.row_version}
                    campaignId={campaignId}
                    view={state.data}
                    options={options.state.data}
                    refreshing={state.refreshing}
                    keptChanges={keptChanges}
                    onKeepChanges={setKeptChanges}
                    refetch={refetch}
                    detailPath={detailPath}
                />
            )}
        </section>
    )
}

function NotEditable({ view, detailPath }: { view: LocationAuthoringView; detailPath: string }) {
    const reason = view.blocked_actions.find((b) => b.action === "update")?.reason
    return (
        <p role="alert">
            This location cannot be edited right now
            {reason !== undefined ? `: ${describeBlockedReason(reason)}` : "."}{" "}
            <Link to={detailPath}>Back to the location</Link>
        </p>
    )
}

interface EditLocationFormProps {
    campaignId: string
    view: LocationAuthoringView
    options: LocationOptions
    refreshing: boolean
    keptChanges: LocationFormValues | null
    onKeepChanges: (values: LocationFormValues | null) => void
    refetch: () => Promise<void>
    detailPath: string
}

function EditLocationForm({
    campaignId,
    view,
    options,
    refreshing,
    keptChanges,
    onKeepChanges,
    refetch,
    detailPath,
}: EditLocationFormProps) {
    const navigate = useNavigate()
    const { reload } = useSession()
    const initial = valuesFromView(view)
    const [values, setValues] = useState<LocationFormValues>(initial)
    const [errors, setErrors] = useState<FieldError[]>([])
    const [attempt, setAttempt] = useState(0)
    const [confirmingCanon, setConfirmingCanon] = useState(false)
    const dirty = !sameValues(values, initial)
    const guard = useUnsavedChangesGuard(dirty)
    const category = options.categories.find((c) => c.code === view.category.code)
    const isCanon = view.canon_status === "canon"

    const mutation = useAuthoringMutation<UpdateLocationBody, LocationAuthoringView>({
        scopeKey: `edit-location:${view.location_id}:${view.row_version}`,
        request: (body, ctx) => updateLocation(campaignId, view.location_id, body, ctx),
        onSuccess: () => {
            guard.release()
            onKeepChanges(null)
            setConfirmingCanon(false)
            void navigate(detailPath, { state: { announce: "Location saved" } })
        },
    })

    const pending = mutation.status.kind === "pending"
    const error = mutation.status.kind === "error" ? mutation.status.error : null
    const serverField = error ? fieldForErrorCode(error.code) : null
    const serverErrors: FieldError[] =
        serverField !== null && error?.code
            ? [
                  {
                      fieldId: serverField,
                      message: ERROR_CODE_MESSAGE[error.code] ?? "Check this field.",
                  },
              ]
            : []
    const all = [...errors, ...serverErrors]
    const errorFor = (fieldId: string) => all.find((e) => e.fieldId === fieldId)?.message ?? null

    function submitNow() {
        const note = values.changeNote.trim()
        mutation.submit({
            expected_row_version: view.row_version,
            ...toFieldsBody(values, category),
            change_note: note === "" ? null : note,
        })
    }

    function handleSubmit() {
        const found = validateLocationForm(values, category, { requireCategory: false })
        setErrors(found)
        setAttempt((n) => n + 1)
        if (found.length > 0) {
            return
        }
        if (isCanon) {
            setConfirmingCanon(true)
            return
        }
        submitNow()
    }

    return (
        <>
            {keptChanges !== null ? (
                <section
                    aria-label="Your unsaved changes"
                    className="authoring-message authoring-message--warning"
                >
                    <div>
                        <h2>Your unsaved changes</h2>
                        <p>
                            The form below now shows the latest version. These are the values you had
                            entered:
                        </p>
                        <ChangeSummary values={keptChanges} />
                        <button
                            type="button"
                            className="authoring-button"
                            onClick={() => {
                                setValues(keptChanges)
                                onKeepChanges(null)
                            }}
                        >
                            Re-apply my changes
                        </button>
                    </div>
                </section>
            ) : null}

            <AuthoringForm label="Edit location" onSubmit={handleSubmit}>
                <ErrorSummary errors={all} attempt={attempt} />
                {error !== null && error.kind === "stale" ? (
                    <StaleWriteNotice
                        loading={refreshing}
                        onLoadLatest={() => {
                            onKeepChanges(values)
                            mutation.reset()
                            void refetch()
                        }}
                        yourChanges={<ChangeSummary values={values} />}
                    />
                ) : error !== null && serverField === null ? (
                    <MutationStatusMessage
                        error={error}
                        onRetry={mutation.retry}
                        onCheckSession={reload}
                    />
                ) : null}
                <LocationFields
                    campaignId={campaignId}
                    locationId={view.location_id}
                    categories={options.categories}
                    values={values}
                    onChange={setValues}
                    errorFor={errorFor}
                    showChangeNote={isCanon}
                />
                <FormActions pending={pending} onCancel={() => void navigate(detailPath)} />
            </AuthoringForm>

            <ConfirmDialog
                open={confirmingCanon && mutation.status.kind !== "error"}
                title="Save changes to a published location?"
                description="This location is published. People with access will see the change. For a change in meaning, create a replacement and supersede this location instead."
                confirmLabel="Save changes"
                cancelLabel="Keep editing"
                pending={pending}
                onConfirm={submitNow}
                onCancel={() => setConfirmingCanon(false)}
            />
            <ConfirmDialog
                open={guard.blocked}
                title="Discard unsaved changes?"
                description="You have edits to this location that have not been saved."
                confirmLabel="Discard changes"
                cancelLabel="Keep editing"
                onConfirm={guard.discard}
                onCancel={guard.stay}
            />
        </>
    )
}

function ChangeSummary({ values }: { values: LocationFormValues }) {
    return (
        <dl className="authoring-fact-list">
            <dt>Name</dt>
            <dd>{values.name}</dd>
            <dt>Summary</dt>
            <dd>{values.summary || "(empty)"}</dd>
            <dt>Contained in</dt>
            <dd>{values.parent?.label ?? "(none)"}</dd>
            {values.population !== "" ? (
                <>
                    <dt>Population</dt>
                    <dd>{values.population}</dd>
                </>
            ) : null}
            {values.buildingUse !== "" ? (
                <>
                    <dt>Use</dt>
                    <dd>{values.buildingUse}</dd>
                </>
            ) : null}
        </dl>
    )
}
