import { useState } from "react"
import type { ReactNode } from "react"
import { Link, useNavigate, useParams } from "react-router"
import { useSession } from "../../context/SessionContext"
import { useAuthoringMutation } from "../../hooks/useAuthoringMutation"
import { useAuthoringResource } from "../../hooks/useAuthoringResource"
import { usePageArrival } from "../../hooks/usePageArrival"
import { useUnsavedChangesGuard } from "../../hooks/useUnsavedChangesGuard"
import type { MutationContext } from "../../api/worlds"
import { ERROR_CODE_MESSAGE, fieldForErrorCode } from "../../utils/authoringValidation"
import { ConfirmDialog } from "./ConfirmDialog"
import { AuthoringForm, ErrorSummary, FormActions, MutationStatusMessage } from "./feedback"
import type { FieldError } from "./feedback"
import "./authoring.css"

export interface FieldsRenderProps<TOptions, TValues> {
    campaignId: string
    options: TOptions
    values: TValues
    setValues: (values: TValues) => void
    errorFor: (fieldId: string) => string | null
}

// Everything that differs between content types. The shell owns what must not
// differ: loading the server's options (and treating a refused read as "no
// permission"), the typed form, client-side mirrors of the server limits, the
// idempotent single-flight save, server-code -> field mapping, `replace`
// navigation after create, the unsaved-change guard, focus, and announcements.
export interface ContentCreateConfig<TOptions, TValues, TBody, TResult> {
    // Lowercase noun for copy: "location".
    noun: string
    heading: string
    lead: string
    breadcrumbLabel: string
    worldPath: (campaignId: string) => string
    optionsPath: (campaignId: string) => string
    canCreate: (options: TOptions) => boolean
    initialValues: (options: TOptions) => TValues
    isDirty: (values: TValues, initial: TValues) => boolean
    validate: (values: TValues, options: TOptions) => FieldError[]
    toBody: (values: TValues, options: TOptions) => TBody
    create: (campaignId: string, body: TBody, ctx: MutationContext) => Promise<TResult>
    resultPath: (campaignId: string, result: TResult) => string
    announce: string
    saveLabel: string
    pendingLabel: string
    renderFields: (props: FieldsRenderProps<TOptions, TValues>) => ReactNode
}

interface Props<TOptions, TValues, TBody, TResult> {
    config: ContentCreateConfig<TOptions, TValues, TBody, TResult>
}

export function ContentCreatePage<TOptions, TValues, TBody, TResult>({
    config,
}: Props<TOptions, TValues, TBody, TResult>) {
    const { campaignId = "" } = useParams()
    const { state } = useAuthoringResource<TOptions>(config.optionsPath(campaignId))
    const headingRef = usePageArrival(state.kind === "ready")
    const headingId = `create-${config.noun.replace(/\s+/g, "-")}-heading`
    const denied = (
        <p role="alert">You do not have permission to create {config.noun}s in this campaign.</p>
    )

    return (
        <section className="authoring-page" aria-labelledby={headingId}>
            <p className="authoring-page__breadcrumb">
                <Link to={config.worldPath(campaignId)}>{config.breadcrumbLabel}</Link>
            </p>
            <h1 id={headingId} ref={headingRef} tabIndex={-1}>
                {config.heading}
            </h1>
            {state.kind === "loading" ? (
                <p role="status">Loading…</p>
            ) : state.kind === "denied" || state.kind === "unavailable" ? (
                denied
            ) : state.kind === "error" ? (
                <p role="alert">The form could not be loaded. Try reloading the page.</p>
            ) : !config.canCreate(state.data) ? (
                denied
            ) : (
                <CreateForm key={campaignId} campaignId={campaignId} options={state.data} config={config} />
            )}
        </section>
    )
}

function CreateForm<TOptions, TValues, TBody, TResult>({
    campaignId,
    options,
    config,
}: {
    campaignId: string
    options: TOptions
    config: ContentCreateConfig<TOptions, TValues, TBody, TResult>
}) {
    const navigate = useNavigate()
    const { reload } = useSession()
    const [initial] = useState(() => config.initialValues(options))
    const [values, setValues] = useState<TValues>(initial)
    const [errors, setErrors] = useState<FieldError[]>([])
    const [attempt, setAttempt] = useState(0)
    const guard = useUnsavedChangesGuard(config.isDirty(values, initial))

    const mutation = useAuthoringMutation<TBody, TResult>({
        scopeKey: `create-${config.noun}:${campaignId}`,
        request: (body, ctx) => config.create(campaignId, body, ctx),
        onSuccess: (created) => {
            guard.release()
            // Replace, so Back never returns to a form that was already submitted.
            void navigate(config.resultPath(campaignId, created), {
                replace: true,
                state: { announce: config.announce },
            })
        },
    })

    const pending = mutation.status.kind === "pending"
    const error = mutation.status.kind === "error" ? mutation.status.error : null
    const serverField = error ? fieldForErrorCode(error.code) : null
    const serverErrors: FieldError[] =
        serverField !== null && error?.code
            ? [{ fieldId: serverField, message: ERROR_CODE_MESSAGE[error.code] ?? "Check this field." }]
            : []
    const all = [...errors, ...serverErrors]
    const errorFor = (fieldId: string) => all.find((e) => e.fieldId === fieldId)?.message ?? null

    function handleSubmit() {
        const found = config.validate(values, options)
        setErrors(found)
        setAttempt((n) => n + 1)
        if (found.length > 0) {
            return
        }
        mutation.submit(config.toBody(values, options))
    }

    return (
        <>
            <p className="authoring-page__lead">{config.lead}</p>
            <AuthoringForm label={config.heading} onSubmit={handleSubmit}>
                <ErrorSummary errors={all} attempt={attempt} />
                {error !== null && serverField === null ? (
                    <MutationStatusMessage error={error} onRetry={mutation.retry} onCheckSession={reload} />
                ) : null}
                {config.renderFields({ campaignId, options, values, setValues, errorFor })}
                <FormActions
                    pending={pending}
                    saveLabel={config.saveLabel}
                    pendingLabel={config.pendingLabel}
                    onCancel={() => void navigate(config.worldPath(campaignId))}
                />
            </AuthoringForm>
            <ConfirmDialog
                open={guard.blocked}
                title={`Discard this new ${config.noun}?`}
                description="You have entered details that have not been saved."
                confirmLabel="Discard"
                cancelLabel="Keep editing"
                onConfirm={guard.discard}
                onCancel={guard.stay}
            />
        </>
    )
}
