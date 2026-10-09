import { useEffect, useState } from "react"
import type { ReactNode } from "react"
import { Link, useLocation } from "react-router"
import {
    fetchKnowledgeSubjectOptions,
    knowledgeAuthoringPath,
    knowledgeOptionsPath,
    updateKnowledgeItem,
} from "../api/knowledgeAuthoring"
import { AudiencePreviewSection } from "../components/AudiencePreviewSection"
import { useAnnounce } from "../components/authoring/announcer"
import { ConfirmDialog } from "../components/authoring/ConfirmDialog"
import { SelectField, TextAreaField, TextField } from "../components/authoring/fields"
import { ErrorSummary, MutationStatusMessage, StaleWriteNotice } from "../components/authoring/feedback"
import type { FieldError } from "../components/authoring/feedback"
import { ReferenceCombobox } from "../components/authoring/ReferenceCombobox"
import type { ReferenceOption } from "../components/authoring/ReferenceCombobox"
import { KnowledgeRoster } from "../components/knowledge/KnowledgeRoster"
import { KnowledgeSubjectLink } from "../components/KnowledgeSubjectLink"
import { useSession } from "../context/SessionContext"
import { useAuthoringMutation } from "../hooks/useAuthoringMutation"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import { useCampaignCapability } from "../hooks/useCampaignCapability"
import { useUnsavedChangesGuard } from "../hooks/useUnsavedChangesGuard"
import type { KnowledgeDetail } from "../types/knowledge"
import type { KnowledgeAuthoringView, KnowledgeOptions } from "../types/knowledgeAuthoring"
import { ERROR_CODE_MESSAGE, REASON_MAX, fieldForErrorCode } from "../utils/authoringValidation"
import { describeBlockedReason } from "../utils/blockedReason"
import { humanizeCode } from "../utils/humanize"
import { FIELD, STATEMENT_MAX, fromView, same, toBody, validate } from "../utils/knowledgeForm"
import type { KnowledgeFormValues } from "../utils/knowledgeForm"
import { statusDetail } from "../utils/locationForm"
import "../components/authoring/authoring.css"

interface KnowledgeClaimPageProps {
    campaignId: string
    /** The claim in the address. Every request names this id with this campaign, never an id
     * copied back out of a response. */
    knowledgeItemId: string
    item: KnowledgeDetail
    /** The perspective this claim was requested under. */
    characterId: string | null
    partyId: string | null
    /** Re-reads the audience-safe detail in place after a claim save. */
    refreshDetail: () => void
}

const LOCK_REASON = "Someone already knows this claim, so this cannot change."

// Moves the reader to a section named by the address's #fragment (the old Edit and
// "Who knows this" addresses redirect here with one), once that section exists.
function useFragmentFocus(id: string, ready: boolean) {
    const { hash } = useLocation()
    useEffect(() => {
        if (!ready || hash !== `#${id}`) return
        const target = document.getElementById(id)
        target?.scrollIntoView?.()
        target?.querySelector<HTMLElement>("h2")?.focus()
    }, [hash, id, ready])
}

// The one Knowledge claim page: /app/:campaignId/knowledge/:knowledgeItemId. The claim, what
// it is about, the GM's canonical record, the selected character's knowledge and the roster of
// who knows it, in that order. There is no view/edit toggle: whoever may change the claim gets
// its fields as controls, everyone else gets the same values as text, and anything they may not
// see is simply absent. The claim and each knowledge action save separately.
export function KnowledgeClaimPage({
    campaignId,
    knowledgeItemId,
    item,
    characterId,
    partyId,
    refreshDetail,
}: KnowledgeClaimPageProps) {
    const canEdit = useCampaignCapability(campaignId, "canon.edit")
    return (
        <section className="authoring-page knowledge-claim" aria-labelledby="knowledge-claim-heading">
            <nav aria-label="Breadcrumb" className="authoring-page__breadcrumb">
                <ol className="session-run__breadcrumb">
                    <li>
                        <Link to={`/app/${encodeURIComponent(campaignId)}/knowledge`}>Knowledge</Link>
                    </li>
                    <li aria-current="page">Claim</li>
                </ol>
            </nav>
            <div className="knowledge-claim__header">
                <h1 id="knowledge-claim-heading">Knowledge claim</h1>
                {canEdit ? (
                    <AudiencePreviewSection
                        campaignId={campaignId}
                        resourceType="knowledge_item"
                        fixedResource={{ id: knowledgeItemId, display_name: item.statement }}
                    />
                ) : null}
            </div>
            {canEdit ? (
                <EditableClaim
                    campaignId={campaignId}
                    knowledgeItemId={knowledgeItemId}
                    item={item}
                    characterId={characterId}
                    partyId={partyId}
                    refreshDetail={refreshDetail}
                />
            ) : (
                <ClaimLayout
                    campaignId={campaignId}
                    item={item}
                    characterId={characterId}
                    partyId={partyId}
                    edit={null}
                    note={null}
                />
            )}
            <KnowledgeRoster campaignId={campaignId} knowledgeItemId={knowledgeItemId} />
        </section>
    )
}

// Loads the editor's own read model. While it loads, or when editing is not offered, the same
// layout shows the values as text (with the server's reason when editing is blocked).
function EditableClaim(props: KnowledgeClaimPageProps) {
    const { campaignId, knowledgeItemId } = props
    const view = useAuthoringResource<KnowledgeAuthoringView>(knowledgeAuthoringPath(campaignId, knowledgeItemId))
    const options = useAuthoringResource<KnowledgeOptions>(knowledgeOptionsPath(campaignId))

    if (view.state.kind === "ready" && options.state.kind === "ready") {
        if (view.state.data.available_actions.includes("update")) {
            return (
                <ClaimForm
                    {...props}
                    view={view.state.data}
                    options={options.state.data}
                    refreshing={view.state.refreshing}
                    refetch={view.refetch}
                />
            )
        }
        const reason = view.state.data.blocked_actions.find((b) => b.action === "update")?.reason
        return (
            <ClaimLayout
                {...props}
                edit={null}
                note={reason === undefined ? null : `Editing unavailable: ${describeBlockedReason(reason)}`}
            />
        )
    }
    return <ClaimLayout {...props} edit={null} note={null} />
}

interface EditBindings {
    values: KnowledgeFormValues
    setValues: (values: KnowledgeFormValues) => void
    options: KnowledgeOptions
    locked: boolean
    errorFor: (fieldId: string) => string | null
    canon: boolean
    changeNote: string
    setChangeNote: (note: string) => void
    searchSubjects: (query: string, signal: AbortSignal) => Promise<ReferenceOption[]>
    /** Save, Discard and their feedback; rendered at the end of the claim's own sections. */
    actions: ReactNode
}

function changedFields(base: KnowledgeFormValues, next: KnowledgeFormValues): Partial<KnowledgeFormValues> {
    const out: Partial<KnowledgeFormValues> = {}
    if (next.statement !== base.statement) out.statement = next.statement
    if (next.knowledgeType !== base.knowledgeType) out.knowledgeType = next.knowledgeType
    if (next.truthStatus !== base.truthStatus) out.truthStatus = next.truthStatus
    if (next.sensitivity !== base.sensitivity) out.sensitivity = next.sensitivity
    if ((next.subject?.id ?? null) !== (base.subject?.id ?? null)) out.subject = next.subject
    return out
}

const readable = (options: { value: string; label: string }[], value: string): string =>
    options.find((o) => o.value === value)?.label ?? humanizeCode(value)

// The layout shared by the editable and the read-only presentations, so what moves between
// them is only whether a value is a control or text.
function ClaimLayout({
    campaignId,
    item,
    characterId,
    partyId,
    edit,
    note,
}: Pick<KnowledgeClaimPageProps, "campaignId" | "item" | "characterId" | "partyId"> & {
    edit: EditBindings | null
    note: string | null
}) {
    const hasCanonical = item.truth_status_code !== null || item.sensitivity !== null
    useFragmentFocus("claim", true)
    const hasSubject = item.subject !== null && item.subject !== undefined

    const subjectEditor =
        edit === null ? undefined : edit.locked ? (
            edit.values.subject !== null ? (
                <p className="authoring-note">The subject cannot change: {LOCK_REASON.toLowerCase()}</p>
            ) : null
        ) : (
            <ReferenceCombobox
                id={FIELD.subject}
                label="Subject"
                value={edit.values.subject}
                onChange={(subject) => edit.setValues({ ...edit.values, subject })}
                search={edit.searchSubjects}
                error={edit.errorFor(FIELD.subject)}
                placeholder="Search places, organizations, religions, characters, quests"
            />
        )

    return (
        <>
            <section id="claim" className="knowledge-claim__claim" aria-label="Claim">
                {note !== null ? <p className="authoring-note">{note}</p> : null}
                {edit === null ? (
                    <p className="knowledge-claim__text">{item.statement}</p>
                ) : (
                    <TextAreaField
                        id={FIELD.statement}
                        label="Claim"
                        hideLabel
                        className="knowledge-claim__textarea"
                        hint={edit.locked ? LOCK_REASON : undefined}
                        rows={3}
                        value={edit.values.statement}
                        onChange={(statement) => edit.setValues({ ...edit.values, statement })}
                        required
                        disabled={edit.locked}
                        maxLength={STATEMENT_MAX}
                        error={edit.errorFor(FIELD.statement)}
                    />
                )}
                {edit === null && !hasCanonical ? (
                    <p className="knowledge-claim__kind">{humanizeCode(item.knowledge_type_code)}</p>
                ) : null}
            </section>

            {hasSubject || subjectEditor !== undefined ? (
                <KnowledgeSubjectLink
                    campaignId={campaignId}
                    subject={item.subject}
                    characterId={characterId}
                    partyId={partyId}
                    variant="claim"
                >
                    {subjectEditor}
                </KnowledgeSubjectLink>
            ) : null}

            {edit !== null || hasCanonical ? (
                <section className="knowledge-gm" aria-labelledby="knowledge-canonical-heading">
                    <h2 id="knowledge-canonical-heading">GM and canonical information</h2>
                    {edit === null ? (
                        <dl className="knowledge-gm__grid knowledge-gm__facts">
                            <div>
                                <dt>Kind</dt>
                                <dd>{humanizeCode(item.knowledge_type_code)}</dd>
                            </div>
                            {item.truth_status_code !== null ? (
                                <div>
                                    <dt>Truth</dt>
                                    <dd>{humanizeCode(item.truth_status_code)}</dd>
                                </div>
                            ) : null}
                            {item.sensitivity !== null ? (
                                <div>
                                    <dt>Sensitivity</dt>
                                    <dd>{humanizeCode(item.sensitivity)}</dd>
                                </div>
                            ) : null}
                        </dl>
                    ) : (
                        <div className="knowledge-gm__grid">
                            <SelectField
                                id={FIELD.type}
                                label="Kind"
                                hint={edit.locked ? LOCK_REASON : undefined}
                                value={edit.values.knowledgeType}
                                placeholder="Choose a kind"
                                required
                                disabled={edit.locked}
                                options={edit.options.knowledge_types}
                                error={edit.errorFor(FIELD.type)}
                                onChange={(knowledgeType) => edit.setValues({ ...edit.values, knowledgeType })}
                            />
                            <SelectField
                                id={FIELD.truth}
                                label="Truth"
                                value={edit.values.truthStatus}
                                placeholder="Choose"
                                required
                                options={edit.options.truth_statuses}
                                error={edit.errorFor(FIELD.truth)}
                                onChange={(truthStatus) => edit.setValues({ ...edit.values, truthStatus })}
                            />
                            <SelectField
                                id={FIELD.sensitivity}
                                label="Sensitivity"
                                value={edit.values.sensitivity}
                                placeholder="Choose a sensitivity"
                                required
                                options={edit.options.sensitivities}
                                error={edit.errorFor(FIELD.sensitivity)}
                                onChange={(sensitivity) => edit.setValues({ ...edit.values, sensitivity })}
                            />
                            {edit.canon ? (
                                <div className="knowledge-gm__wide">
                                    <TextField
                                        id="change-note"
                                        label="Change note (optional)"
                                        value={edit.changeNote}
                                        onChange={edit.setChangeNote}
                                        maxLength={REASON_MAX}
                                        error={edit.errorFor("change-note")}
                                    />
                                </div>
                            ) : null}
                        </div>
                    )}
                    {edit !== null ? edit.actions : null}
                </section>
            ) : null}

            <CharacterKnowledge item={item} characterId={characterId} />
        </>
    )
}

function CharacterKnowledge({ item, characterId }: { item: KnowledgeDetail; characterId: string | null }) {
    const recorded = [
        item.awareness_level !== null
            ? { key: "awareness", label: "Awareness", value: humanizeCode(item.awareness_level) }
            : null,
        item.confidence !== null ? { key: "confidence", label: "Confidence", value: `${item.confidence}%` } : null,
        item.willing_to_share !== null
            ? { key: "share", label: "Willing to share", value: item.willing_to_share ? "Yes" : "No" }
            : null,
    ].filter((entry) => entry !== null)
    return (
        <section className="knowledge-section knowledge-character" aria-labelledby="knowledge-character-heading">
            <h2 id="knowledge-character-heading">Character knowledge</h2>
            {characterId === null ? (
                <p className="authoring-note">Select a character perspective to see what that character knows.</p>
            ) : recorded.length === 0 ? (
                <p className="authoring-note">The selected character has no recorded knowledge of this claim.</p>
            ) : (
                <dl className="knowledge-character__facts">
                    {recorded.map((entry) => (
                        <div key={entry.key} className="knowledge-claim__fact">
                            <dt>{entry.label}</dt>
                            <dd>{entry.value}</dd>
                        </div>
                    ))}
                </dl>
            )}
        </section>
    )
}

function ClaimForm({
    campaignId,
    knowledgeItemId,
    item,
    characterId,
    partyId,
    refreshDetail,
    view,
    options,
    refreshing,
    refetch,
}: KnowledgeClaimPageProps & {
    view: KnowledgeAuthoringView
    options: KnowledgeOptions
    refreshing: boolean
    refetch: () => Promise<void>
}) {
    const { reload } = useSession()
    const announce = useAnnounce()
    const base = fromView(view)
    // The unsaved claim edits: only the fields the user changed. Everything else follows the saved
    // claim, so a refresh of it (or of anything else on the page) never overwrites an edit in
    // progress and still brings in other people's changes to fields you have not touched.
    const [changes, setChanges] = useState<Partial<KnowledgeFormValues>>({})
    const [changeNote, setChangeNote] = useState("")
    const [errors, setErrors] = useState<FieldError[]>([])
    const [attempt, setAttempt] = useState(0)
    const [confirming, setConfirming] = useState(false)
    const [saved, setSaved] = useState(false)
    const values: KnowledgeFormValues = { ...base, ...changes }
    const setValues = (next: KnowledgeFormValues) => setChanges(changedFields(base, next))
    const dirty = !same(values, base) || changeNote.trim() !== ""
    const guard = useUnsavedChangesGuard(dirty)
    const isCanon = view.canon_status === "canon"

    const mutation = useAuthoringMutation<
        ReturnType<typeof toBody> & { expected_row_version: number; change_note: string | null },
        unknown
    >({
        scopeKey: `edit-knowledge-claim:${knowledgeItemId}:${view.row_version}`,
        request: (body, ctx) => updateKnowledgeItem(campaignId, knowledgeItemId, body, ctx),
        onSuccess: async () => {
            setConfirming(false)
            await refetch()
            refreshDetail()
            setChanges({})
            setChangeNote("")
            setErrors([])
            setSaved(true)
            announce("Knowledge claim saved")
        },
    })
    const pending = mutation.status.kind === "pending"
    const error = mutation.status.kind === "error" ? mutation.status.error : null
    const serverField = error ? fieldForErrorCode(error.code) : null
    const serverErrors: FieldError[] =
        serverField !== null && error?.code
            ? [{ fieldId: serverField, message: ERROR_CODE_MESSAGE[error.code] ?? "Check this field." }]
            : []
    const noteError: FieldError[] =
        changeNote.trim().length > REASON_MAX
            ? [{ fieldId: "change-note", message: `Change note must be ${REASON_MAX} characters or fewer.` }]
            : []
    const all = [...errors, ...serverErrors]
    const errorFor = (fieldId: string) => all.find((e) => e.fieldId === fieldId)?.message ?? null

    function submitNow() {
        const note = changeNote.trim()
        mutation.submit({
            ...toBody(values),
            expected_row_version: view.row_version,
            change_note: note === "" ? null : note,
        })
    }

    function handleSubmit() {
        setSaved(false)
        const found = [...validate(values), ...noteError]
        setErrors(found)
        setAttempt((n) => n + 1)
        if (found.length > 0) return
        if (isCanon) {
            setConfirming(true)
            return
        }
        submitNow()
    }

    async function searchSubjects(query: string, signal: AbortSignal): Promise<ReferenceOption[]> {
        const page = await fetchKnowledgeSubjectOptions(campaignId, query, signal)
        return page.items.map((option) => ({
            id: option.entity_id,
            label: option.name,
            detail: `${option.kind.replace(/_/g, " ")}, ${statusDetail(option.canon_status, "active")}`,
        }))
    }

    const summary = (v: KnowledgeFormValues) => (
        <dl className="authoring-fact-list">
            <dt>Claim</dt>
            <dd>{v.statement || "(empty)"}</dd>
            <dt>Kind</dt>
            <dd>{readable(options.knowledge_types, v.knowledgeType)}</dd>
            <dt>Truth</dt>
            <dd>{readable(options.truth_statuses, v.truthStatus)}</dd>
            <dt>Sensitivity</dt>
            <dd>{readable(options.sensitivities, v.sensitivity)}</dd>
            <dt>Subject</dt>
            <dd>{v.subject?.label ?? "(none)"}</dd>
        </dl>
    )

    const actions = (
        <>
            <ErrorSummary errors={all} attempt={attempt} />
            {error !== null && error.kind === "stale" ? (
                <StaleWriteNotice
                    loading={refreshing}
                    onLoadLatest={() => {
                        // Your edits stay in the form; only the saved version they build on is refreshed.
                        mutation.reset()
                        void refetch()
                    }}
                    yourChanges={summary(values)}
                />
            ) : error !== null && serverField === null ? (
                <MutationStatusMessage error={error} onRetry={mutation.retry} onCheckSession={reload} />
            ) : null}
            <div className="authoring-actions knowledge-claim__actions">
                <button
                    type="submit"
                    className="authoring-button authoring-button--primary"
                    disabled={pending || !dirty}
                    aria-busy={pending}
                >
                    {pending ? "Saving…" : "Save claim"}
                </button>
                <button
                    type="button"
                    className="authoring-button"
                    disabled={pending || !dirty}
                    aria-describedby="discard-claim-hint"
                    onClick={() => {
                        setChanges({})
                        setChangeNote("")
                        setErrors([])
                        mutation.reset()
                    }}
                >
                    Discard changes
                </button>
                <span className="knowledge-claim__state" role="status">
                    {dirty ? "Unsaved changes to the claim" : saved ? "Claim saved" : ""}
                </span>
            </div>
            <p id="discard-claim-hint" className="authoring-note">
                Claim changes and knowledge actions save independently.
            </p>
        </>
    )

    return (
        <form
            noValidate
            aria-label="Knowledge claim"
            className="knowledge-claim__form"
            onSubmit={(event) => {
                event.preventDefault()
                handleSubmit()
            }}
        >
            <ClaimLayout
                campaignId={campaignId}
                item={item}
                characterId={characterId}
                partyId={partyId}
                note={null}
                edit={{
                    values,
                    setValues,
                    options,
                    locked: view.in_use,
                    errorFor,
                    canon: isCanon,
                    changeNote,
                    setChangeNote,
                    searchSubjects,
                    actions,
                }}
            />
            <ConfirmDialog
                open={confirming && mutation.status.kind !== "error"}
                title="Save changes to a published claim?"
                description="This claim is published. People with access will see the change. For a change in meaning, create a replacement claim instead."
                confirmLabel="Save changes"
                cancelLabel="Keep editing"
                pending={pending}
                onConfirm={submitNow}
                onCancel={() => setConfirming(false)}
            />
            <ConfirmDialog
                open={guard.blocked}
                title="Discard unsaved changes?"
                description="You have edits to this claim that have not been saved."
                confirmLabel="Discard changes"
                cancelLabel="Keep editing"
                onConfirm={guard.discard}
                onCancel={guard.stay}
            />
        </form>
    )
}
