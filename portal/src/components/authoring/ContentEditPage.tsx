import { useEffect, useState } from "react"
import type { ReactNode } from "react"
import { Link, useLocation, useNavigate, useParams } from "react-router"
import { useSession } from "../../context/SessionContext"
import { useAuthoringMutation } from "../../hooks/useAuthoringMutation"
import { useAuthoringResource } from "../../hooks/useAuthoringResource"
import { useKept } from "../../hooks/useKeptResource"
import { usePageArrival } from "../../hooks/usePageArrival"
import { useWorldCapability, WORLD_CANON_EDIT } from "../../hooks/useWorldCapability"
import { useUnsavedChangesGuard } from "../../hooks/useUnsavedChangesGuard"
import type { MutationContext } from "../../api/worlds"
import type { EntityBlockedAction } from "../../types/entityLifecycle"
import { REASON_MAX, ERROR_CODE_MESSAGE, fieldForErrorCode } from "../../utils/authoringValidation"
import { describeBlockedReason } from "../../utils/blockedReason"
import { retainedChanges } from "../../utils/retainedChanges"
import type { RetainedChange } from "../../utils/retainedChanges"
import { StaleReadNotice } from "../StaleReadNotice"
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
import { PermissionLost } from "./PermissionLost"
import { ReadFailedNotice } from "./ReadState"
import "./authoring.css"

// The server's authoring read model, as far as the shell needs it.
export interface EditableView {
    row_version: number
    canon_status: string
    available_actions: string[]
    blocked_actions: EntityBlockedAction[]
}

// Where the page's links lead: the collection, and the record page the person came from.
export interface EditNavigation {
    listPath: string
    detail: { to: string; state?: object }
}

export interface ContentEditConfig<TView extends EditableView, TOptions, TValues, TBody> {
    noun: string
    heading: string
    // Records that are campaign-originated (player-character identity, ADR 0020 E3) need no
    // world Editor role; every other definition is shared world canon and does.
    campaignOriginated?: boolean
    // Name of the route parameter carrying the record id.
    entityParam: string
    breadcrumbLabel: string
    worldPath: (campaignId: string) => string
    detailPath: (campaignId: string, entityId: string) => string
    // Optional: a record that can be reached from more than one place returns to where the person
    // came from (the router state names it) instead of the single `worldPath`/`detailPath`.
    navigation?: (context: {
        campaignId: string
        entityId: string
        state: unknown
        params: Record<string, string | undefined>
    }) => EditNavigation
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
    ) => Promise<unknown>
    renderFields: (
        props: FieldsRenderProps<TOptions, TValues> & { entityId: string; view: TView },
    ) => ReactNode
    // Read-only summary of values, shown in the stale-write panels.
    summarize: (values: TValues) => ReactNode
    // True when a change to a canon record needs a confirmation (always, today).
    canonWarning: string
    saved: string
    // Optional sections rendered after the form, sharing the page view and refetch (for an
    // aggregate whose children are edited beside its own fields).
    renderExtra?: (props: {
        campaignId: string
        entityId: string
        view: TView
        options: TOptions
        refetch: () => Promise<unknown>
    }) => ReactNode
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
    const viewPath = config.viewPath(campaignId, entityId)
    const optionsPath = config.optionsPath(campaignId)
    const { state, refetch } = useAuthoringResource<TView>(viewPath)
    const options = useAuthoringResource<TOptions>(optionsPath)
    // The last record and choices that loaded, held through a recoverable read failure so the form
    // and what was typed in it stay put; a denied or missing answer, or another record, drops them.
    const view = useKept(state, viewPath)
    const choices = useKept(options.state, optionsPath)
    const readStale = state.kind === "error" || options.state.kind === "error"
    const ready = state.kind === "ready" && options.state.kind === "ready"
    const hasWorldEdit = useWorldCapability(campaignId, WORLD_CANON_EDIT)
    const needsWorldEdit = config.campaignOriginated !== true && !hasWorldEdit
    const headingRef = usePageArrival(ready || needsWorldEdit)
    const [keptChanges, setKeptChanges] = useState<TValues | null>(null)
    // What the person has changed in the open form, kept by the page (the form is unmounted when a
    // read is refused). Only changes are kept, never the record the server sent: when the right to
    // edit or read is lost, that is all that may be shown back (see utils/retainedChanges).
    const [live, setLive] = useState<{ path: string; changes: RetainedChange[] } | null>(null)
    const [lost, setLost] = useState<{ path: string; changes: RetainedChange[] } | null>(null)
    const readRefused = state.kind === "denied" || state.kind === "unavailable"
    const refusedWhileEditing = readRefused && live !== null && live.path === viewPath ? live : null
    if (refusedWhileEditing !== null && lost?.path !== viewPath) setLost(refusedWhileEditing)
    const permissionLost = lost !== null && lost.path === viewPath ? lost : null
    const location = useLocation()
    const target: EditNavigation = config.navigation?.({ campaignId, entityId, state: location.state, params }) ?? {
        listPath: config.worldPath(campaignId),
        detail: { to: config.detailPath(campaignId, entityId) },
    }
    const headingId = `edit-${config.noun.replace(/\s+/g, "-")}-heading`

    return (
        <section className="authoring-page" aria-labelledby={headingId}>
            <p className="authoring-page__breadcrumb">
                <Link to={target.listPath}>{config.breadcrumbLabel}</Link>
                {view !== null ? (
                    <>
                        {" / "}
                        <Link to={target.detail.to} state={target.detail.state}>
                            {config.name(view)}
                        </Link>
                    </>
                ) : null}
            </p>
            <h1 id={headingId} ref={headingRef} tabIndex={-1}>
                {config.heading}
            </h1>
            {permissionLost !== null ? (
                <PermissionLost noun={config.noun} retained={permissionLost.changes} back={target.detail} />
            ) : needsWorldEdit ? (
                <p role="alert">Editing shared world content requires the world Editor role. Ask the world owner.</p>
            ) : state.kind === "loading" || options.state.kind === "loading" ? (
                <p role="status">Loading {config.noun}…</p>
            ) : state.kind === "unavailable" ||
              state.kind === "denied" ||
              options.state.kind === "unavailable" ||
              options.state.kind === "denied" ? (
                // One message for both: the server deliberately does not say whether the record is
                // missing or merely not the person's to edit.
                <p role="alert">
                    This {config.noun} does not exist, or you do not have access to it.
                </p>
            ) : view === null || choices === null ? (
                <ReadFailedNotice
                    what={config.noun}
                    onRetry={() => {
                        if (state.kind === "error") void refetch()
                        if (options.state.kind === "error") void options.refetch()
                    }}
                />
            ) : !view.available_actions.includes("update") ? (
                <NotEditable config={config} view={view} target={target.detail} />
            ) : (
                <>
                    {readStale ? (
                        <StaleReadNotice
                            what={config.noun}
                            onRetry={() => {
                                if (state.kind === "error") void refetch()
                                if (options.state.kind === "error") void options.refetch()
                            }}
                        />
                    ) : null}
                    <EditForm
                        key={view.row_version}
                        config={config}
                        campaignId={campaignId}
                        entityId={entityId}
                        view={view}
                        options={choices}
                        refreshing={state.kind === "ready" && state.refreshing}
                        readStale={readStale}
                        keptChanges={keptChanges}
                        onKeepChanges={setKeptChanges}
                        refetch={refetch}
                        target={target.detail}
                        onChanges={(changes) => setLive({ path: viewPath, changes })}
                        onPermissionLost={(changes) => setLost({ path: viewPath, changes })}
                    />
                </>
            )}
        </section>
    )
}

function NotEditable<TView extends EditableView, TOptions, TValues, TBody>({
    config,
    view,
    target,
}: {
    config: ContentEditConfig<TView, TOptions, TValues, TBody>
    view: TView
    target: EditNavigation["detail"]
}) {
    const reason = view.blocked_actions.find((b) => b.action === "update")?.reason
    return (
        <p role="alert">
            This {config.noun} cannot be edited right now
            {reason !== undefined ? `: ${describeBlockedReason(reason)}` : "."}{" "}
            <Link to={target.to} state={target.state}>
                Back to the {config.noun}
            </Link>
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
    // The latest read failed and `view` is the last that loaded: its version may be behind, so a
    // version-checked save is held until it reloads (what was typed stays).
    readStale: boolean
    keptChanges: TValues | null
    onKeepChanges: (values: TValues | null) => void
    refetch: () => Promise<unknown>
    target: EditNavigation["detail"]
    // The changes the person has made so far, reported on every edit.
    onChanges: (changes: RetainedChange[]) => void
    // The save was refused because the right to edit is gone: stop, and hand over what to keep.
    onPermissionLost: (changes: RetainedChange[]) => void
}

function EditForm<TView extends EditableView, TOptions, TValues, TBody>({
    config,
    campaignId,
    entityId,
    view,
    options,
    refreshing,
    readStale,
    keptChanges,
    onKeepChanges,
    refetch,
    target,
    onChanges,
    onPermissionLost,
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
        unknown
    >({
        scopeKey: `edit-${config.noun}:${entityId}:${view.row_version}`,
        request: (body, ctx) => config.update(campaignId, entityId, body, ctx),
        onSuccess: () => {
            guard.release()
            onKeepChanges(null)
            setConfirmingCanon(false)
            void navigate(target.to, { state: { ...target.state, announce: config.saved } })
        },
    })

    const pending = mutation.status.kind === "pending"
    const error = mutation.status.kind === "error" ? mutation.status.error : null
    // Refused because the world role is gone (403 `world_authority_required`) or because the record
    // is no longer the person's to reach (404): nothing more can be sent, and what they typed is all
    // that is kept. A bare 403 is not that: it is also what a stale CSRF token or session answers,
    // which "Check my session" recovers with the form intact.
    const refused =
        error !== null &&
        ((error.kind === "denied" && error.code === "world_authority_required") ||
            error.kind === "unavailable")
    const [reported, setReported] = useState(false)
    const changes = retainedChanges(initial, values, changeNote)
    const changesKey = JSON.stringify(changes)
    useEffect(() => {
        onChanges(JSON.parse(changesKey) as RetainedChange[])
        // Reported when the changes change (their serialization), not on every render.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [changesKey])
    if (refused && !reported) {
        setReported(true)
        onPermissionLost(changes)
        // Read the record again so whatever the server still holds for this person is dropped with
        // the form; a refused read clears it.
        void refetch()
    }
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
        if (readStale) return
        const note = changeNote.trim()
        mutation.submit({
            ...config.toBody(values, view, options),
            expected_row_version: view.row_version,
            change_note: note === "" ? null : note,
        })
    }

    function handleSubmit() {
        if (readStale) return
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
                <FormActions pending={pending} saveDisabled={readStale} onCancel={() => void navigate(target.to, { state: target.state })} />
            </AuthoringForm>

            {config.renderExtra?.({ campaignId, entityId, view, options, refetch })}

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
