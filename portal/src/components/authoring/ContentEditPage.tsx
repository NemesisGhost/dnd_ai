import { useState } from "react"
import type { ReactNode } from "react"
import { Link, useNavigate, useParams } from "react-router"
import { useSession } from "../../context/SessionContext"
import { useAuthoringMutation } from "../../hooks/useAuthoringMutation"
import { useAuthoringResource } from "../../hooks/useAuthoringResource"
import { usePageArrival } from "../../hooks/usePageArrival"
import { useUnsavedChangesGuard } from "../../hooks/useUnsavedChangesGuard"
import type { MutationContext } from "../../api/worlds"
import type { EntityBlockedAction } from "../../types/entityLifecycle"
import { REASON_MAX, ERROR_CODE_MESSAGE, fieldForErrorCode } from "../../utils/authoringValidation"
import { describeBlockedReason } from "../../utils/blockedReason"
import { ConfirmDialog } from "./ConfirmDialog"
import { TextField } from "./fields"
import {
    AuthoringForm,
    ErrorSummary,
    FormActions,
    MutationStatusMessage,
    StaleWriteNotice,
} from "./feedback"
import type { FieldError } from "./feedback"
import type { FieldsRenderProps } from "./ContentCreatePage"
import "./authoring.css"

// The server's authoring read model, as far as the shell needs it.
export interface EditableView {
    row_version: number
    canon_status: string
    available_actions: string[]
    blocked_actions: EntityBlockedAction[]
}

export interface ContentEditConfig<TView extends EditableView, TOptions, TValues, TBody> {
    noun: string
    heading: string
    // Name of the route parameter carrying the record id.
    entityParam: string
    breadcrumbLabel: string
    worldPath: (campaignId: string) => string
    detailPath: (campaignId: string, entityId: string) => string
    viewPath: (campaignId: string, entityId: string) => string
    optionsPath: (campaignId: string) => string
    name: (view: TView) => string
    valuesFromView: (view: TView) => TValues
    same: (a: TValues, b: TValues) => boolean
    validate: (values: TValues, view: TView, options: TOptions) => FieldError[]
    toBody: (values: TValues, view: TView, options: TOptions) => TBody
    update: (
        campaignId: string,
        entityId: string,
        body: TBody & { expected_row_version: number; change_note: string | null },
        ctx: MutationContext,
    ) => Promise<TView>
    renderFields: (
        props: FieldsRenderProps<TOptions, TValues> & { entityId: string; view: TView },
    ) => ReactNode
    // Read-only summary of values, shown in the stale-write panels.
    summarize: (values: TValues) => ReactNode
    // True when a change to a canon record needs a confirmation (always, today).
    canonWarning: string
    saved: string
}

interface Props<TView extends EditableView, TOptions, TValues, TBody> {
    config: ContentEditConfig<TView, TOptions, TValues, TBody>
}

// Edit a definition at its own reloadable route. Loads the authoring read model
// (never timeline state) keyed by the URL; a non-editor, a missing record, and
// another world's record all reach the same "unavailable" state. On a stale
// write the user's values are kept, the latest version is shown, and the old
// version is never resubmitted.
export function ContentEditPage<TView extends EditableView, TOptions, TValues, TBody>({
    config,
}: Props<TView, TOptions, TValues, TBody>) {
    const params = useParams()
    const campaignId = params.campaignId ?? ""
    const entityId = params[config.entityParam] ?? ""
    const { state, refetch } = useAuthoringResource<TView>(config.viewPath(campaignId, entityId))
    const options = useAuthoringResource<TOptions>(config.optionsPath(campaignId))
    const ready = state.kind === "ready" && options.state.kind === "ready"
    const headingRef = usePageArrival(ready)
    const [keptChanges, setKeptChanges] = useState<TValues | null>(null)
    const detailPath = config.detailPath(campaignId, entityId)
    const headingId = `edit-${config.noun.replace(/\s+/g, "-")}-heading`

    return (
        <section className="authoring-page" aria-labelledby={headingId}>
            <p className="authoring-page__breadcrumb">
                <Link to={config.worldPath(campaignId)}>{config.breadcrumbLabel}</Link>
                {state.kind === "ready" ? (
                    <>
                        {" / "}
                        <Link to={detailPath}>{config.name(state.data)}</Link>
                    </>
                ) : null}
            </p>
            <h1 id={headingId} ref={headingRef} tabIndex={-1}>
                {config.heading}
            </h1>
            {state.kind === "loading" || options.state.kind === "loading" ? (
                <p role="status">Loading {config.noun}…</p>
            ) : state.kind === "unavailable" || state.kind === "denied" ? (
                <p role="alert">
                    This {config.noun} does not exist, or you do not have access to it.
                </p>
            ) : state.kind === "error" || options.state.kind !== "ready" ? (
                <p role="alert">The {config.noun} could not be loaded. Try reloading the page.</p>
            ) : !state.data.available_actions.includes("update") ? (
                <NotEditable config={config} view={state.data} detailPath={detailPath} />
            ) : (
                <EditForm
                    key={state.data.row_version}
                    config={config}
                    campaignId={campaignId}
                    entityId={entityId}
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

function NotEditable<TView extends EditableView, TOptions, TValues, TBody>({
    config,
    view,
    detailPath,
}: {
    config: ContentEditConfig<TView, TOptions, TValues, TBody>
    view: TView
    detailPath: string
}) {
    const reason = view.blocked_actions.find((b) => b.action === "update")?.reason
    return (
        <p role="alert">
            This {config.noun} cannot be edited right now
            {reason !== undefined ? `: ${describeBlockedReason(reason)}` : "."}{" "}
            <Link to={detailPath}>Back to the {config.noun}</Link>
        </p>
    )
}

interface EditFormProps<TView extends EditableView, TOptions, TValues, TBody> {
    config: ContentEditConfig<TView, TOptions, TValues, TBody>
    campaignId: string
    entityId: string
    view: TView
    options: TOptions
    refreshing: boolean
    keptChanges: TValues | null
    onKeepChanges: (values: TValues | null) => void
    refetch: () => Promise<void>
    detailPath: string
}

function EditForm<TView extends EditableView, TOptions, TValues, TBody>({
    config,
    campaignId,
    entityId,
    view,
    options,
    refreshing,
    keptChanges,
    onKeepChanges,
    refetch,
    detailPath,
}: EditFormProps<TView, TOptions, TValues, TBody>) {
    const navigate = useNavigate()
    const { reload } = useSession()
    const [initial] = useState(() => config.valuesFromView(view))
    const [values, setValues] = useState<TValues>(initial)
    const [changeNote, setChangeNote] = useState("")
    const [errors, setErrors] = useState<FieldError[]>([])
    const [attempt, setAttempt] = useState(0)
    const [confirmingCanon, setConfirmingCanon] = useState(false)
    const isCanon = view.canon_status === "canon"
    const guard = useUnsavedChangesGuard(!config.same(values, initial) || changeNote.trim() !== "")

    const mutation = useAuthoringMutation<
        TBody & { expected_row_version: number; change_note: string | null },
        TView
    >({
        scopeKey: `edit-${config.noun}:${entityId}:${view.row_version}`,
        request: (body, ctx) => config.update(campaignId, entityId, body, ctx),
        onSuccess: () => {
            guard.release()
            onKeepChanges(null)
            setConfirmingCanon(false)
            void navigate(detailPath, { state: { announce: config.saved } })
        },
    })

    const pending = mutation.status.kind === "pending"
    const error = mutation.status.kind === "error" ? mutation.status.error : null
    const serverField = error ? fieldForErrorCode(error.code) : null
    const serverErrors: FieldError[] =
        serverField !== null && error?.code
            ? [{ fieldId: serverField, message: ERROR_CODE_MESSAGE[error.code] ?? "Check this field." }]
            : []
    const noteError =
        changeNote.trim().length > REASON_MAX
            ? [{ fieldId: "change-note", message: `Change note must be ${REASON_MAX} characters or fewer.` }]
            : []
    const all = [...errors, ...serverErrors]
    const errorFor = (fieldId: string) => all.find((e) => e.fieldId === fieldId)?.message ?? null

    function submitNow() {
        const note = changeNote.trim()
        mutation.submit({
            ...config.toBody(values, view, options),
            expected_row_version: view.row_version,
            change_note: note === "" ? null : note,
        })
    }

    function handleSubmit() {
        const found = [...config.validate(values, view, options), ...noteError]
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
                        {config.summarize(keptChanges)}
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

            <AuthoringForm label={config.heading} onSubmit={handleSubmit}>
                <ErrorSummary errors={all} attempt={attempt} />
                {error !== null && error.kind === "stale" ? (
                    <StaleWriteNotice
                        loading={refreshing}
                        onLoadLatest={() => {
                            onKeepChanges(values)
                            mutation.reset()
                            void refetch()
                        }}
                        yourChanges={config.summarize(values)}
                    />
                ) : error !== null && serverField === null ? (
                    <MutationStatusMessage error={error} onRetry={mutation.retry} onCheckSession={reload} />
                ) : null}
                {config.renderFields({
                    campaignId,
                    entityId,
                    view,
                    options,
                    values,
                    setValues,
                    errorFor,
                })}
                {isCanon ? (
                    <TextField
                        id="change-note"
                        label="Change note (optional)"
                        hint="Recorded in the audit history with this change."
                        value={changeNote}
                        onChange={setChangeNote}
                        maxLength={REASON_MAX}
                        error={errorFor("change-note")}
                    />
                ) : null}
                <FormActions pending={pending} onCancel={() => void navigate(detailPath)} />
            </AuthoringForm>

            <ConfirmDialog
                open={confirmingCanon && mutation.status.kind !== "error"}
                title={`Save changes to a published ${config.noun}?`}
                description={config.canonWarning}
                confirmLabel="Save changes"
                cancelLabel="Keep editing"
                pending={pending}
                onConfirm={submitNow}
                onCancel={() => setConfirmingCanon(false)}
            />
            <ConfirmDialog
                open={guard.blocked}
                title="Discard unsaved changes?"
                description={`You have edits to this ${config.noun} that have not been saved.`}
                confirmLabel="Discard changes"
                cancelLabel="Keep editing"
                onConfirm={guard.discard}
                onCancel={guard.stay}
            />
        </>
    )
}
