import { useState } from "react"
import { Link, useNavigate, useParams } from "react-router"
import {
    archiveParty,
    createParty,
    partiesPath,
    partyPath,
    restoreParty,
    updateParty,
} from "../api/parties"
import { ConfirmDialog } from "../components/authoring/ConfirmDialog"
import { useAnnounce } from "../components/authoring/announcer"
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
import type { PartyFieldsBody, PartyItem, PartyList, PartyReceipt } from "../types/parties"
import {
    DESCRIPTION_MAX,
    NAME_MAX,
    validateDescription,
    validateName,
} from "../utils/authoringValidation"
import "../components/authoring/authoring.css"

const base = (campaignId: string): string => `/app/${encodeURIComponent(campaignId)}`

const CODE_MESSAGE: Readonly<Record<string, string>> = {
    party_not_active: "This party is archived. Restore it first.",
    party_not_archived: "This party is not archived.",
}

// /app/:campaignId/parties — every member sees the active parties; editors can
// also show archived ones, create, edit, archive, and restore.
export function PartiesPage() {
    const { campaignId = "" } = useParams()
    const [showArchived, setShowArchived] = useState(false)
    const list = useAuthoringResource<PartyList>(partiesPath(campaignId, showArchived))
    const headingRef = usePageArrival(list.state.kind === "ready")
    const data = list.state.kind === "ready" ? list.state.data : null

    return (
        <section className="authoring-page" aria-labelledby="parties-heading">
            <p className="authoring-page__breadcrumb">
                <Link to={base(campaignId)}>Campaign Home</Link>
            </p>
            <h1 id="parties-heading" ref={headingRef} tabIndex={-1}>
                Parties
            </h1>
            {list.state.kind === "loading" ? (
                <p role="status">Loading parties…</p>
            ) : list.state.kind === "error" ? (
                <p role="alert">The parties could not be loaded. Try reloading the page.</p>
            ) : data === null ? (
                <p role="alert">You do not have access to this campaign's parties.</p>
            ) : (
                <>
                    {data.can_create ? (
                        <div className="authoring-page__actions-row">
                            <Link className="authoring-button" to={`${base(campaignId)}/parties/new`}>
                                New party
                            </Link>{" "}
                            <label className="authoring-checkbox">
                                <input
                                    type="checkbox"
                                    checked={showArchived}
                                    onChange={(event) => setShowArchived(event.target.checked)}
                                />{" "}
                                Show archived parties
                            </label>
                        </div>
                    ) : null}
                    {data.items.length === 0 ? (
                        <p>No parties yet.</p>
                    ) : (
                        <ul className="authoring-choice-list">
                            {data.items.map((party) => (
                                <PartyRow
                                    key={party.party_id}
                                    campaignId={campaignId}
                                    party={party}
                                    refetch={list.refetch}
                                />
                            ))}
                        </ul>
                    )}
                </>
            )}
        </section>
    )
}

function PartyRow({
    campaignId,
    party,
    refetch,
}: {
    campaignId: string
    party: PartyItem
    refetch: () => Promise<void>
}) {
    const { reload } = useSession()
    const announce = useAnnounce()
    const [dialog, setDialog] = useState<"archive" | "restore" | null>(null)
    const [reason, setReason] = useState("")
    const [reasonError, setReasonError] = useState<string | null>(null)
    const mutation = useAuthoringMutation<"archive" | "restore", PartyReceipt>({
        scopeKey: `party-lifecycle:${party.party_id}:${party.row_version}`,
        request: (action, ctx) =>
            action === "archive"
                ? archiveParty(
                      campaignId,
                      party.party_id,
                      { expected_row_version: party.row_version, reason: reason.trim() || null },
                      ctx,
                  )
                : restoreParty(
                      campaignId,
                      party.party_id,
                      { expected_row_version: party.row_version, reason: reason.trim() },
                      ctx,
                  ),
        onSuccess: async () => {
            const done = dialog === "archive" ? "Party archived" : "Party restored"
            setDialog(null)
            setReason("")
            await refetch()
            announce(done)
        },
    })
    const error = mutation.status.kind === "error" ? mutation.status.error : null
    const message = error?.code ? (CODE_MESSAGE[error.code] ?? null) : null
    const actions = party.available_actions ?? []

    return (
        <li>
            <strong>{party.name}</strong>
            {party.lifecycle_status === "archived" ? " (archived)" : ""}
            {party.description !== null ? <p>{party.description}</p> : null}
            {actions.length > 0 ? (
                <p className="authoring-actions">
                    <Link
                        className="authoring-button"
                        to={`${base(campaignId)}/parties/${encodeURIComponent(party.party_id)}`}
                    >
                        Members of {party.name}
                    </Link>
                    {actions.includes("update") ? (
                        <Link
                            className="authoring-button"
                            to={`${base(campaignId)}/parties/${encodeURIComponent(party.party_id)}/edit`}
                        >
                            Edit {party.name}
                        </Link>
                    ) : null}
                    {actions.includes("archive") ? (
                        <button
                            type="button"
                            className="authoring-button"
                            onClick={() => {
                                mutation.reset()
                                setDialog("archive")
                            }}
                        >
                            Archive {party.name}
                        </button>
                    ) : null}
                    {actions.includes("restore") ? (
                        <button
                            type="button"
                            className="authoring-button"
                            onClick={() => {
                                mutation.reset()
                                setDialog("restore")
                            }}
                        >
                            Restore {party.name}
                        </button>
                    ) : null}
                </p>
            ) : null}
            <ConfirmDialog
                open={dialog !== null}
                title={dialog === "restore" ? "Restore this party?" : "Archive this party?"}
                description={
                    dialog === "restore"
                        ? "The party returns to pickers and can take new members again."
                        : "The party stays in the campaign's history but is hidden from pickers and takes no new members."
                }
                confirmLabel={dialog === "restore" ? "Restore party" : "Archive party"}
                pending={mutation.status.kind === "pending"}
                reason={{
                    label: dialog === "restore" ? "Reason" : "Reason (optional)",
                    required: dialog === "restore",
                    value: reason,
                    onChange: (value) => {
                        setReason(value)
                        setReasonError(null)
                    },
                    error: reasonError,
                }}
                error={
                    error?.kind === "stale" ? (
                        <StaleWriteNotice
                            onLoadLatest={() => {
                                mutation.reset()
                                setDialog(null)
                                void refetch()
                            }}
                        />
                    ) : message !== null ? (
                        <p role="alert">{message}</p>
                    ) : error !== null ? (
                        <MutationStatusMessage
                            error={error}
                            onRetry={mutation.retry}
                            onCheckSession={reload}
                        />
                    ) : null
                }
                onConfirm={() => {
                    if (dialog === "restore" && reason.trim() === "") {
                        setReasonError("Enter a reason.")
                        return
                    }
                    if (dialog !== null) mutation.submit(dialog)
                }}
                onCancel={() => {
                    setDialog(null)
                    setReason("")
                    setReasonError(null)
                    mutation.reset()
                }}
            />
        </li>
    )
}

interface FormValues {
    name: string
    description: string
}

function validate(values: FormValues): FieldError[] {
    const errors: FieldError[] = []
    const nameError = validateName(values.name)
    if (nameError) errors.push({ fieldId: "party-name", message: nameError })
    const descriptionError = validateDescription(values.description)
    if (descriptionError) errors.push({ fieldId: "party-description", message: descriptionError })
    return errors
}

function PartyForm({
    campaignId,
    initial,
    version,
    partyId,
    onStale,
}: {
    campaignId: string
    initial: FormValues
    version: number | null
    partyId: string | null
    onStale: () => void
}) {
    const navigate = useNavigate()
    const { reload } = useSession()
    const [values, setValues] = useState<FormValues>(initial)
    const [errors, setErrors] = useState<FieldError[]>([])
    const [attempt, setAttempt] = useState(0)
    const dirty = values.name !== initial.name || values.description !== initial.description
    const guard = useUnsavedChangesGuard(dirty)
    const mutation = useAuthoringMutation<PartyFieldsBody, PartyReceipt>({
        scopeKey: `party-form:${campaignId}:${partyId ?? "new"}:${version ?? 0}`,
        request: (body, ctx) =>
            partyId === null || version === null
                ? createParty(campaignId, body, ctx)
                : updateParty(campaignId, partyId, { ...body, expected_row_version: version }, ctx),
        onSuccess: () => {
            guard.release()
            void navigate(`${base(campaignId)}/parties`, {
                replace: true,
                state: { announce: partyId === null ? "Party created" : "Party saved" },
            })
        },
    })
    const pending = mutation.status.kind === "pending"
    const error = mutation.status.kind === "error" ? mutation.status.error : null
    const message = error?.code ? (CODE_MESSAGE[error.code] ?? null) : null
    const errorFor = (id: string) => errors.find((e) => e.fieldId === id)?.message ?? null

    function submit() {
        const found = validate(values)
        setErrors(found)
        setAttempt((n) => n + 1)
        if (found.length > 0) return
        mutation.submit({
            name: values.name.trim(),
            description: values.description.trim() === "" ? null : values.description.trim(),
        })
    }

    return (
        <>
            <AuthoringForm label={partyId === null ? "New party" : "Edit party"} onSubmit={submit}>
                <ErrorSummary errors={errors} attempt={attempt} />
                {error?.kind === "stale" ? (
                    <StaleWriteNotice onLoadLatest={onStale} />
                ) : message !== null ? (
                    <p role="alert">{message}</p>
                ) : error !== null ? (
                    <MutationStatusMessage error={error} onRetry={mutation.retry} onCheckSession={reload} />
                ) : null}
                <TextField
                    id="party-name"
                    label="Name"
                    value={values.name}
                    onChange={(name) => setValues({ ...values, name })}
                    required
                    maxLength={NAME_MAX}
                    error={errorFor("party-name")}
                />
                <TextAreaField
                    id="party-description"
                    label="Description"
                    value={values.description}
                    onChange={(description) => setValues({ ...values, description })}
                    maxLength={DESCRIPTION_MAX}
                    error={errorFor("party-description")}
                />
                <FormActions
                    pending={pending}
                    saveLabel={partyId === null ? "Create party" : "Save party"}
                    onCancel={() => void navigate(`${base(campaignId)}/parties`)}
                />
            </AuthoringForm>
            <ConfirmDialog
                open={guard.blocked}
                title="Discard your changes?"
                description="You have entered details that have not been saved."
                confirmLabel="Discard"
                cancelLabel="Keep editing"
                onConfirm={guard.discard}
                onCancel={guard.stay}
            />
        </>
    )
}

// /app/:campaignId/parties/new
export function CreatePartyPage() {
    const { campaignId = "" } = useParams()
    const list = useAuthoringResource<PartyList>(partiesPath(campaignId))
    const headingRef = usePageArrival(list.state.kind === "ready")
    return (
        <section className="authoring-page" aria-labelledby="new-party-heading">
            <p className="authoring-page__breadcrumb">
                <Link to={`${base(campaignId)}/parties`}>Parties</Link>
            </p>
            <h1 id="new-party-heading" ref={headingRef} tabIndex={-1}>
                New party
            </h1>
            {list.state.kind === "loading" ? (
                <p role="status">Loading…</p>
            ) : list.state.kind === "ready" && list.state.data.can_create ? (
                <PartyForm
                    key={campaignId}
                    campaignId={campaignId}
                    initial={{ name: "", description: "" }}
                    version={null}
                    partyId={null}
                    onStale={() => undefined}
                />
            ) : (
                <p role="alert">You do not have permission to create parties in this campaign.</p>
            )}
        </section>
    )
}

// /app/:campaignId/parties/:partyId/edit
export function EditPartyPage() {
    const { campaignId = "", partyId = "" } = useParams()
    const party = useAuthoringResource<PartyItem>(partyPath(campaignId, partyId))
    const headingRef = usePageArrival(party.state.kind === "ready")
    const data = party.state.kind === "ready" ? party.state.data : null
    return (
        <section className="authoring-page" aria-labelledby="edit-party-heading">
            <p className="authoring-page__breadcrumb">
                <Link to={`${base(campaignId)}/parties`}>Parties</Link>
            </p>
            <h1 id="edit-party-heading" ref={headingRef} tabIndex={-1}>
                Edit party
            </h1>
            {party.state.kind === "loading" ? (
                <p role="status">Loading party…</p>
            ) : data === null ? (
                <p role="alert">This party does not exist, or you do not have access to it.</p>
            ) : !(data.available_actions ?? []).includes("update") ? (
                <p role="alert">
                    This party cannot be edited right now.{" "}
                    <Link to={`${base(campaignId)}/parties`}>Back to parties</Link>
                </p>
            ) : (
                <PartyForm
                    key={`${data.party_id}:${data.row_version}`}
                    campaignId={campaignId}
                    initial={{ name: data.name, description: data.description ?? "" }}
                    version={data.row_version}
                    partyId={data.party_id}
                    onStale={() => void party.refetch()}
                />
            )}
        </section>
    )
}
