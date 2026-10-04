import { useState } from "react"
import { Link, useNavigate, useParams } from "react-router"
import { createLocation, locationOptionsPath } from "../api/locationAuthoring"
import { ConfirmDialog } from "../components/authoring/ConfirmDialog"
import {
    AuthoringForm,
    ErrorSummary,
    FormActions,
    MutationStatusMessage,
} from "../components/authoring/feedback"
import type { FieldError } from "../components/authoring/feedback"
import { LocationFields } from "../components/authoring/LocationFields"
import { useSession } from "../context/SessionContext"
import { useAuthoringMutation } from "../hooks/useAuthoringMutation"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import { usePageArrival } from "../hooks/usePageArrival"
import { useUnsavedChangesGuard } from "../hooks/useUnsavedChangesGuard"
import type {
    CreateLocationBody,
    LocationAuthoringView,
    LocationOptions,
} from "../types/locationAuthoring"
import { ERROR_CODE_MESSAGE, fieldForErrorCode } from "../utils/authoringValidation"
import {
    EMPTY_LOCATION_FORM,
    sameValues,
    toFieldsBody,
    validateLocationForm,
} from "../utils/locationForm"
import type { LocationFormValues } from "../utils/locationForm"
import "../components/authoring/authoring.css"

// Create a Location draft: /app/:campaignId/world/location/new. The category
// catalog and the create permission come from the server; this page offers
// nothing the options read did not.
export function CreateLocationPage() {
    const { campaignId = "" } = useParams()
    const { state } = useAuthoringResource<LocationOptions>(locationOptionsPath(campaignId))
    const headingRef = usePageArrival(state.kind === "ready")
    const worldPath = `/app/${encodeURIComponent(campaignId)}/world`

    return (
        <section className="authoring-page" aria-labelledby="create-location-heading">
            <p className="authoring-page__breadcrumb">
                <Link to={worldPath}>World</Link>
            </p>
            <h1 id="create-location-heading" ref={headingRef} tabIndex={-1}>
                New location
            </h1>
            {state.kind === "loading" ? (
                <p role="status">Loading…</p>
            ) : state.kind === "denied" || state.kind === "unavailable" ? (
                <p role="alert">You do not have permission to create locations in this campaign.</p>
            ) : state.kind === "error" ? (
                <p role="alert">The form could not be loaded. Try reloading the page.</p>
            ) : !state.data.can_create ? (
                <p role="alert">You do not have permission to create locations in this campaign.</p>
            ) : (
                <CreateLocationForm key={campaignId} campaignId={campaignId} options={state.data} />
            )}
        </section>
    )
}

interface CreateLocationFormProps {
    campaignId: string
    options: LocationOptions
}

function CreateLocationForm({ campaignId, options }: CreateLocationFormProps) {
    const navigate = useNavigate()
    const { reload } = useSession()
    const [values, setValues] = useState<LocationFormValues>(EMPTY_LOCATION_FORM)
    const [errors, setErrors] = useState<FieldError[]>([])
    const [attempt, setAttempt] = useState(0)
    const dirty = !sameValues(values, EMPTY_LOCATION_FORM)
    const guard = useUnsavedChangesGuard(dirty)
    const category = options.categories.find((c) => c.code === values.category)

    const mutation = useAuthoringMutation<CreateLocationBody, LocationAuthoringView>({
        scopeKey: `create-location:${campaignId}`,
        request: (body, ctx) => createLocation(campaignId, body, ctx),
        onSuccess: (created) => {
            guard.release()
            // Replace, so Back never returns to a form that was already submitted.
            void navigate(
                `/app/${encodeURIComponent(campaignId)}/world/location/${encodeURIComponent(created.location_id)}`,
                { replace: true, state: { announce: "Location created as a draft" } },
            )
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

    function handleSubmit() {
        const found = validateLocationForm(values, category, { requireCategory: true })
        setErrors(found)
        setAttempt((n) => n + 1)
        if (found.length > 0) {
            return
        }
        mutation.submit({ category: values.category, ...toFieldsBody(values, category) })
    }

    return (
        <>
            <p className="authoring-page__lead">
                A new location is saved as a draft. Only people who can edit canon see it until it is
                published.
            </p>
            <AuthoringForm label="New location" onSubmit={handleSubmit}>
                <ErrorSummary errors={all} attempt={attempt} />
                {error !== null && serverField === null ? (
                    <MutationStatusMessage
                        error={error}
                        onRetry={mutation.retry}
                        onCheckSession={reload}
                    />
                ) : null}
                <LocationFields
                    campaignId={campaignId}
                    locationId={null}
                    categories={options.categories}
                    values={values}
                    onChange={setValues}
                    errorFor={errorFor}
                    showChangeNote={false}
                />
                <FormActions
                    pending={pending}
                    saveLabel="Create location"
                    pendingLabel="Creating…"
                    onCancel={() =>
                        void navigate(`/app/${encodeURIComponent(campaignId)}/world`)
                    }
                />
            </AuthoringForm>
            <ConfirmDialog
                open={guard.blocked}
                title="Discard this new location?"
                description="You have entered details that have not been saved."
                confirmLabel="Discard"
                cancelLabel="Keep editing"
                onConfirm={guard.discard}
                onCancel={guard.stay}
            />
        </>
    )
}
