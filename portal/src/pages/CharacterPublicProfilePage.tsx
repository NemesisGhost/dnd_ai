import { useState } from "react"
import type { ReactNode } from "react"
import { AlertTriangle } from "lucide-react"
import { Link, useParams } from "react-router"
import { publicProfilePath, saveCharacterPublicProfileDraft } from "../api/characterPublicProfile"
import { useAnnounce } from "../components/authoring/announcer"
import { ConfirmDialog } from "../components/authoring/ConfirmDialog"
import { TextAreaField } from "../components/authoring/fields"
import { ErrorSummary, MutationStatusMessage } from "../components/authoring/feedback"
import type { FieldError } from "../components/authoring/feedback"
import { StaleReadNotice } from "../components/StaleReadNotice"
import { TaskBreadcrumb } from "../components/navigation/TaskBreadcrumb"
import { useBreadcrumbLabel } from "../navigation/BreadcrumbLabelContext"
import { useSession } from "../context/SessionContext"
import { useAuthoringMutation } from "../hooks/useAuthoringMutation"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import type { RefetchOutcome } from "../hooks/useAuthoringResource"
import { useAnnounceWhenRead, useConfirmedRefresh } from "../hooks/useConfirmedRefresh"
import { useKept } from "../hooks/useKeptResource"
import { usePageArrival } from "../hooks/usePageArrival"
import { useUnsavedChangesGuard } from "../hooks/useUnsavedChangesGuard"
import { classifyApiError } from "../types/apiError"
import type {
    CharacterPublicProfileRead,
    PublicProfileDraft,
    SavePublicProfileDraftBody,
    SavePublicProfileDraftReceipt,
} from "../types/characterPublicProfile"
import type { RetainedChange } from "../utils/retainedChanges"
import "../components/authoring/authoring.css"

const TEXT_MAX = 4000

const UNAVAILABLE = "This character's public profile is not available to you."

type TextKey = "public_summary" | "public_appearance" | "public_background"

const TEXT_FIELDS: readonly { key: TextKey; label: string; id: string }[] = [
    { key: "public_summary", label: "Public summary", id: "public-profile-summary" },
    { key: "public_appearance", label: "Public appearance", id: "public-profile-appearance" },
    { key: "public_background", label: "Public background", id: "public-profile-background" },
]

// What the page says after the server refuses a write for a reason that means the page is out of
// date or the person's rights changed. The person's own unsent input (and nothing the server sent)
// is shown back read-only, because the form is replaced by the latest read.
interface Refusal {
    message: string
    carried: RetainedChange[]
}

const trimmed = (value: string | null | undefined): string => (value ?? "").trim()

interface FormValues {
    public_summary: string
    public_appearance: string
    public_background: string
    publish_species: boolean
    publish_size: boolean
    // The person asked to clear a background they cannot read.
    clear_background: boolean
}

function initialValues(draft: PublicProfileDraft | null): FormValues {
    return {
        public_summary: draft?.public_summary ?? "",
        public_appearance: draft?.public_appearance ?? "",
        public_background: draft?.public_background ?? "",
        publish_species: draft?.publish_species ?? false,
        publish_size: draft?.publish_size ?? false,
        clear_background: false,
    }
}

// The save body for what the person changed, and only that: a key left out is untouched, an
// emptied text field is `null`. `null` when nothing changed, so nothing is sent.
function saveBody(draft: PublicProfileDraft | null, values: FormValues): SavePublicProfileDraftBody | null {
    const body: SavePublicProfileDraftBody = { expected_row_version: draft?.row_version ?? null }
    let changed = false
    for (const { key } of TEXT_FIELDS) {
        if (key === "public_background" && draft?.public_background_withheld === true) {
            // Its text is not ours to read or send: the only possible change is to clear it.
            if (values.clear_background) {
                body.public_background = null
                changed = true
            }
            continue
        }
        if (trimmed(values[key]) !== trimmed(draft?.[key])) {
            const next = trimmed(values[key])
            body[key] = next === "" ? null : next
            changed = true
        }
    }
    for (const flag of ["publish_species", "publish_size"] as const) {
        if (values[flag] !== (draft?.[flag] ?? false)) {
            body[flag] = values[flag]
            changed = true
        }
    }
    return changed ? body : null
}

const FIELD_LABEL: Readonly<Record<string, string>> = {
    public_summary: "Public summary",
    public_appearance: "Public appearance",
    public_background: "Public background",
    publish_species: "Publish species",
    publish_size: "Publish size",
}

// What the person had changed in a refused save, from the request itself (never from the form or
// the server's read), for showing back to them.
function retainedFromSave(body: SavePublicProfileDraftBody): RetainedChange[] {
    const out: RetainedChange[] = []
    for (const [key, label] of Object.entries(FIELD_LABEL)) {
        if (!(key in body)) continue
        const value = (body as unknown as Record<string, unknown>)[key]
        out.push({
            label,
            value:
                typeof value === "boolean"
                    ? value
                        ? "Yes"
                        : "No"
                    : value === null || value === undefined
                      ? "(cleared)"
                      : String(value),
        })
    }
    return out
}

// /app/:campaignId/characters/:characterId/public-profile — the GM's draft of what players may later
// see. The page is keyed on the character, so nothing read, typed or pending for one character can
// appear under another.
export function CharacterPublicProfilePage() {
    const { campaignId = "", characterId = "" } = useParams()
    return <PublicProfile key={`${campaignId}:${characterId}`} campaignId={campaignId} characterId={characterId} />
}

function PublicProfile({ campaignId, characterId }: { campaignId: string; characterId: string }) {
    const path = publicProfilePath(campaignId, characterId)
    const { state, refetch, authority } = useAuthoringResource<CharacterPublicProfileRead>(path)
    // The last read that loaded stays through a failed re-read; a denied or missing answer drops it.
    const view = useKept(state, path)
    const stale = state.kind === "error" && view !== null
    const reading = state.kind === "ready" && state.refreshing
    const [lost, setLost] = useState<RetainedChange[] | null>(null)
    const [refusal, setRefusal] = useState<Refusal | null>(null)
    // Raised on every refusal so the form is rebuilt from the next read, whatever its version says.
    const [epoch, setEpoch] = useState(0)
    useBreadcrumbLabel({
        route: "characters.detail",
        params: { campaignId, characterId },
        name: state.kind === "ready" && lost === null ? state.data.label.name : undefined,
        denied: state.kind === "denied" || state.kind === "unavailable" || lost !== null,
        authority,
    })
    const announceWhenRead = useAnnounceWhenRead(state.kind === "ready" && !state.refreshing, state)
    const headingRef = usePageArrival(state.kind === "ready")

    function refuse(next: Refusal) {
        setRefusal(next)
        setEpoch((n) => n + 1)
        void refetch()
    }

    let body: ReactNode
    if (lost !== null) {
        body = (
            <>
                <p role="alert">{UNAVAILABLE}</p>
                {lost.length > 0 ? <YourChanges changes={lost} /> : null}
                <p>
                    <Link to={`/app/${encodeURIComponent(campaignId)}/characters`}>Back to the characters</Link>
                </p>
            </>
        )
    } else if (state.kind === "loading") {
        body = <p role="status">Loading…</p>
    } else if (view === null) {
        body = <p role="alert">{UNAVAILABLE}</p>
    } else {
        body = (
            <>
                {stale ? <StaleReadNotice what="public profile" onRetry={() => void refetch()} /> : null}
                {refusal !== null ? <RefusalNotice refusal={refusal} onDismiss={() => setRefusal(null)} /> : null}
                <Loaded
                    key={`${epoch}:${view.draft?.row_version ?? 0}`}
                    campaignId={campaignId}
                    characterId={characterId}
                    view={view}
                    refetch={refetch}
                    held={reading || stale}
                    pageStale={stale}
                    onUnread={announceWhenRead}
                    onRefused={refuse}
                    onLost={setLost}
                />
            </>
        )
    }
    return (
        <section className="authoring-page" aria-labelledby="public-profile-heading">
            <TaskBreadcrumb />
            <h1 id="public-profile-heading" ref={headingRef} tabIndex={-1}>
                Public profile
            </h1>
            {body}
        </section>
    )
}

function YourChanges({ changes }: { changes: readonly RetainedChange[] }) {
    return (
        <section aria-label="Your unsaved changes" className="authoring-your-changes">
            <h2>Your unsaved changes</h2>
            <p>These were not saved. They are shown here, read-only, so you can copy them.</p>
            <dl className="authoring-fact-list">
                {changes.map((change) => (
                    <div key={`${change.label}:${change.value}`}>
                        <dt>{change.label}</dt>
                        <dd>{change.value}</dd>
                    </div>
                ))}
            </dl>
        </section>
    )
}

function RefusalNotice({ refusal, onDismiss }: { refusal: Refusal; onDismiss: () => void }) {
    return (
        <div className="authoring-message authoring-message--warning" role="alert">
            <AlertTriangle aria-hidden="true" className="authoring-message__icon" />
            <div>
                <p>{refusal.message}</p>
                {refusal.carried.length > 0 ? <YourChanges changes={refusal.carried} /> : null}
                <button type="button" className="authoring-button" onClick={onDismiss}>
                    Dismiss
                </button>
            </div>
        </div>
    )
}

const SAVE_REFUSAL: Readonly<Record<string, string>> = {
    stale_write:
        "The draft changed since you opened it. The form now shows the latest saved draft, and nothing you typed was saved.",
    public_profile_draft_missing:
        "The draft no longer matches what you were editing. The form now shows the latest saved draft, and nothing you typed was saved.",
    public_profile_character_not_active:
        "This character is archived, so its public profile cannot be edited. Nothing you typed was saved.",
    public_profile_edit_denied:
        "Editing this public profile is not available to you right now. Nothing you typed was saved.",
    public_profile_field_withheld:
        "A field of this profile is withheld from you, so this save was refused. Nothing you typed was saved.",
}

function Loaded({
    campaignId,
    characterId,
    view,
    refetch,
    held,
    pageStale,
    onUnread,
    onRefused,
    onLost,
}: {
    campaignId: string
    characterId: string
    view: CharacterPublicProfileRead
    refetch: () => Promise<RefetchOutcome>
    // A read is in flight or has failed, so what is shown may be older than the server's draft:
    // every write sends a version from what is shown, so it waits.
    held: boolean
    pageStale: boolean
    onUnread: (message: string) => void
    onRefused: (refusal: Refusal) => void
    onLost: (retained: RetainedChange[]) => void
}) {
    const { reload } = useSession()
    const announce = useAnnounce()
    const draft = view.draft
    const [values, setValues] = useState<FormValues>(() => initialValues(draft))
    const [errors, setErrors] = useState<FieldError[]>([])
    const [attempt, setAttempt] = useState(0)
    const [savedMessage, setSavedMessage] = useState<string | null>(null)

    const pending = saveBody(draft, values)
    const dirty = pending !== null
    const guard = useUnsavedChangesGuard(dirty)

    const saveMutation = useAuthoringMutation<SavePublicProfileDraftBody, SavePublicProfileDraftReceipt>({
        scopeKey: `public-profile-save:${campaignId}:${characterId}`,
        request: async (body, ctx) => {
            try {
                return await saveCharacterPublicProfileDraft(campaignId, characterId, body, ctx)
            } catch (cause) {
                // A refusal that means "this page is out of date" or "your rights changed" is handled
                // once, here: the page re-reads and the form is rebuilt from the answer. The old version
                // token is never sent again.
                if (!ctx.signal.aborted) {
                    const error = classifyApiError(cause)
                    const carried = retainedFromSave(body)
                    if (error.kind === "unavailable") onLost(carried)
                    else if (error.kind === "stale") onRefused({ message: SAVE_REFUSAL.stale_write!, carried })
                    else if (error.kind === "denied")
                        onRefused({
                            message: SAVE_REFUSAL[error.code ?? ""] ?? SAVE_REFUSAL.public_profile_edit_denied!,
                            carried,
                        })
                    else if (
                        error.kind === "conflict" &&
                        (error.code === "public_profile_draft_missing" ||
                            error.code === "public_profile_character_not_active")
                    )
                        onRefused({ message: SAVE_REFUSAL[error.code]!, carried })
                }
                throw cause
            }
        },
        onSuccess: async () => {
            setSavedMessage("Draft saved.")
            const outcome = await refetch()
            if (outcome === "ok") announce("Draft saved.")
            else onUnread("Draft saved.")
            return outcome
        },
    })
    const savedRefresh = useConfirmedRefresh({
        status: saveMutation.status,
        reset: saveMutation.reset,
        what: "public profile",
        message: savedMessage,
        read: refetch,
        pageStale,
        quietRecovery: true,
    })
    const writesHeld = held || savedRefresh.held
    const saving = saveMutation.status.kind === "pending"
    const busy = saving || writesHeld
    const error = saveMutation.status.kind === "error" ? saveMutation.status.error : null

    function submit() {
        if (pending === null || busy) return
        const problems: FieldError[] = TEXT_FIELDS.flatMap(({ key, label, id }) =>
            trimmed(values[key]).length > TEXT_MAX
                ? [{ fieldId: id, message: `${label} must be ${TEXT_MAX} characters or fewer.` }]
                : [],
        )
        setErrors(problems)
        if (problems.length > 0) {
            setAttempt((n) => n + 1)
            return
        }
        saveMutation.submit(pending)
    }

    const set = <K extends keyof FormValues>(key: K, value: FormValues[K]) =>
        setValues((current) => ({ ...current, [key]: value }))
    const fieldError = (id: string) => errors.find((e) => e.fieldId === id)?.message ?? null

    const latest = view.latest_release
    return (
        <>
            {error !== null ? (
                <MutationStatusMessage
                    error={error}
                    onRetry={() => saveMutation.retry()}
                    onCheckSession={reload}
                />
            ) : null}
            {savedRefresh.notice}
            <p className="authoring-note">
                The draft of what players may later see about <strong>{view.label.name}</strong>. Saving a draft shows
                nothing to players.
            </p>
            <section aria-label="Draft status">
                <h2>Draft</h2>
                <p>
                    {draft === null ? "No draft has been saved yet." : `Draft version ${draft.row_version}.`}
                    {view.has_unreleased_changes ? " Unreleased changes." : ""}
                </p>
                <p>{latest === null ? "Nothing has been released yet." : `Latest release: version ${latest.version_number}.`}</p>
            </section>
            {view.can_edit ? (
                <form
                    noValidate
                    aria-label="Public profile draft"
                    className="authoring-form"
                    onSubmit={(event) => {
                        event.preventDefault()
                        submit()
                    }}
                >
                    <ErrorSummary errors={errors} attempt={attempt} />
                    <TextAreaField
                        id="public-profile-summary"
                        label="Public summary"
                        value={values.public_summary}
                        onChange={(value) => set("public_summary", value)}
                        maxLength={TEXT_MAX}
                        error={fieldError("public-profile-summary")}
                    />
                    <TextAreaField
                        id="public-profile-appearance"
                        label="Public appearance"
                        value={values.public_appearance}
                        onChange={(value) => set("public_appearance", value)}
                        maxLength={TEXT_MAX}
                        error={fieldError("public-profile-appearance")}
                    />
                    {draft?.public_background_withheld === true ? (
                        <div className="authoring-field">
                            <p className="authoring-field__label">Public background</p>
                            <p>
                                This field holds copied text that you are not allowed to read, so it is not shown. You
                                can clear it, but not edit it.
                            </p>
                            <button
                                type="button"
                                className="authoring-button"
                                aria-pressed={values.clear_background}
                                onClick={() => set("clear_background", !values.clear_background)}
                            >
                                Clear public background
                            </button>
                            {values.clear_background ? (
                                <p role="status">The public background will be cleared when you save.</p>
                            ) : null}
                        </div>
                    ) : (
                        <TextAreaField
                            id="public-profile-background"
                            label="Public background"
                            value={values.public_background}
                            onChange={(value) => set("public_background", value)}
                            maxLength={TEXT_MAX}
                            error={fieldError("public-profile-background")}
                        />
                    )}
                    <fieldset className="authoring-fieldset">
                        <legend>Species and size</legend>
                        <p className="authoring-field__hint">
                            Choose whether the next release includes them. The choice itself shows nothing to players.
                        </p>
                        <label className="authoring-checkbox">
                            <input
                                type="checkbox"
                                checked={values.publish_species}
                                onChange={(event) => set("publish_species", event.currentTarget.checked)}
                            />{" "}
                            {`Publish species${view.identity_preview !== null ? `: ${view.identity_preview.species.label}` : ""}`}
                        </label>
                        <label className="authoring-checkbox">
                            <input
                                type="checkbox"
                                checked={values.publish_size}
                                onChange={(event) => set("publish_size", event.currentTarget.checked)}
                            />{" "}
                            {`Publish size${view.identity_preview !== null ? `: ${view.identity_preview.size.label}` : ""}`}
                        </label>
                        {view.identity_preview === null ? (
                            <p className="authoring-field__hint">Species and size cannot be previewed by you.</p>
                        ) : null}
                    </fieldset>
                    <div className="authoring-actions">
                        <button
                            type="submit"
                            className="authoring-button authoring-button--primary"
                            disabled={!dirty || busy}
                            aria-busy={saving}
                        >
                            {saving ? "Saving…" : "Save draft"}
                        </button>
                        <button
                            type="button"
                            className="authoring-button"
                            disabled={!dirty || saving}
                            onClick={() => {
                                setValues(initialValues(draft))
                                setErrors([])
                            }}
                        >
                            Discard changes
                        </button>
                    </div>
                </form>
            ) : (
                <ReadOnlyDraft draft={draft} />
            )}
            <ConfirmDialog
                open={guard.blocked}
                title="Discard unsaved changes?"
                description="You have edits to this public profile that have not been saved."
                confirmLabel="Discard changes"
                cancelLabel="Keep editing"
                onConfirm={guard.discard}
                onCancel={guard.stay}
            />
        </>
    )
}

// The draft as the server gave it, for a reader who may not edit it. Nothing here is a control.
function ReadOnlyDraft({ draft }: { draft: PublicProfileDraft | null }) {
    if (draft === null) {
        return <p>No draft has been saved yet.</p>
    }
    return (
        <dl className="authoring-fact-list" aria-label="Public profile draft">
            {TEXT_FIELDS.map(({ key, label }) => {
                const withheld =
                    (key === "public_appearance" && draft.public_appearance_withheld) ||
                    (key === "public_background" && draft.public_background_withheld)
                return (
                    <div key={key}>
                        <dt>{label}</dt>
                        <dd>
                            {withheld
                                ? "Holds copied text that you are not allowed to read."
                                : trimmed(draft[key]) === ""
                                  ? "(empty)"
                                  : draft[key]}
                        </dd>
                    </div>
                )
            })}
            <div>
                <dt>Publish species</dt>
                <dd>{draft.publish_species ? "Yes" : "No"}</dd>
            </div>
            <div>
                <dt>Publish size</dt>
                <dd>{draft.publish_size ? "Yes" : "No"}</dd>
            </div>
        </dl>
    )
}
