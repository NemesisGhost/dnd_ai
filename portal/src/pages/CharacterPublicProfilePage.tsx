import { useLayoutEffect, useState } from "react"
import type { ReactNode } from "react"
import { AlertTriangle } from "lucide-react"
import { Link, useParams } from "react-router"
import {
    publicProfilePath,
    releaseCharacterPublicProfile,
    saveCharacterPublicProfileDraft,
} from "../api/characterPublicProfile"
import { useAnnounce } from "../components/authoring/announcer"
import { ConfirmDialog } from "../components/authoring/ConfirmDialog"
import { TextAreaField } from "../components/authoring/fields"
import { ErrorSummary, MutationStatusMessage } from "../components/authoring/feedback"
import type { FieldError } from "../components/authoring/feedback"
import { CharacterRevelationsSection } from "../components/characters/CharacterRevelationsSection"
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
import { canTakeFocus } from "../utils/focusEligibility"
import { classifyApiError } from "../types/apiError"
import type { AuthoringError } from "../types/apiError"
import type {
    CharacterPublicProfileRead,
    PublicProfileDraft,
    PublicProfileLatestRelease,
    PublicProfileRelease,
    ReleasePublicProfileBody,
    ReleasePublicProfileReceipt,
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
interface CarriedChange extends RetainedChange {
    // Which draft field the value was typed into (absent for the release note).
    field?: string
}

interface Refusal {
    message: string
    carried: CarriedChange[]
}

// The text fields that can hold copied text under a source-read restriction. What the person typed into
// one of them is not shown back once the server has said, by refusal or by a read, that it is withheld
// from them: the page cannot tell what in that text came from the restricted source.
const PROTECTABLE: ReadonlySet<string> = new Set(["public_appearance", "public_background"])

function withheldIn(view: CharacterPublicProfileRead | null, field: string): boolean {
    if (view?.draft == null) return false
    return (
        (field === "public_appearance" && view.draft.public_appearance_withheld) ||
        (field === "public_background" && view.draft.public_background_withheld)
    )
}

// What may be shown back: every carried value except one for a field the latest read withholds.
function shownBack(carried: readonly CarriedChange[], view: CharacterPublicProfileRead | null): CarriedChange[] {
    return carried.filter((change) => change.field === undefined || !withheldIn(view, change.field))
}

// The ids of the controls whose focus the page keeps across a rebuild of the form, and of the status
// heading that takes it when the control cannot.
const IDS = {
    status: "public-profile-draft-status",
    save: "public-profile-save",
    discard: "public-profile-discard",
    release: "public-profile-release",
    species: "public-profile-publish-species",
    size: "public-profile-publish-size",
    clear: "public-profile-clear-background",
}
const KEPT_FOCUS: ReadonlySet<string> = new Set([
    ...Object.values(IDS),
    "public-profile-summary", "public-profile-appearance", "public-profile-background",
])

// Where focus was last (by control id) and whether the form that held it has been replaced since.
// A rebuilt form puts focus back only if it was lost with the old form and nothing else has it.
interface FocusHandoff {
    // A control took focus (by id), or the control that will take it back (a dialog's opener).
    note: (element: Element | null, id?: string) => void
    // The form that held focus is going away.
    leaving: () => void
    // The form that replaces it: give focus back if it was lost with the old form and nothing else has it.
    arrive: () => void
}

function createFocusHandoff(): FocusHandoff {
    let target: string | null = null
    let lost = false
    let restoring = false
    return {
        note: (element, id) => {
            if (id !== undefined) {
                target = id
                return
            }
            if (restoring || !(element instanceof HTMLElement) || element.closest("dialog") !== null) return
            target = element.id === "" ? null : element.id
            lost = false
        },
        leaving: () => {
            const active = document.activeElement
            if (active instanceof HTMLElement && (active.closest("dialog") !== null || KEPT_FOCUS.has(active.id))) lost = true
        },
        arrive: () => {
            if (!lost) return
            lost = false
            const active = document.activeElement
            if (active !== null && active !== document.body) return
            const wanted = target === null ? null : document.getElementById(target)
            const place = canTakeFocus(wanted) ? wanted : document.getElementById(IDS.status)
            if (place === null) return
            restoring = true
            place.focus()
            restoring = false
        },
    }
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
function retainedFromSave(body: SavePublicProfileDraftBody): CarriedChange[] {
    const out: CarriedChange[] = []
    for (const [key, label] of Object.entries(FIELD_LABEL)) {
        if (!(key in body)) continue
        const value = (body as unknown as Record<string, unknown>)[key]
        out.push({
            field: key,
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
    const [handoff] = useState(createFocusHandoff)

    // Once an applied read withholds a field, what was typed into it is discarded from the stored refusal,
    // not only hidden: when access comes back the old rejected input must not return. The state is this
    // character's own (the page is keyed on campaign and character), and `view` is its own read.
    const keptCarried = refusal === null ? null : shownBack(refusal.carried, view)
    if (refusal !== null && keptCarried !== null && keptCarried.length !== refusal.carried.length) {
        setRefusal({ ...refusal, carried: keptCarried })
    }

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
                {refusal !== null ? (
                    <RefusalNotice
                        refusal={{ ...refusal, carried: keptCarried ?? refusal.carried }}
                        onDismiss={() => setRefusal(null)}
                    />
                ) : null}
                <Loaded
                    key={`${epoch}:${view.draft?.row_version ?? 0}:${view.latest_release?.version_number ?? 0}`}
                    campaignId={campaignId}
                    characterId={characterId}
                    view={view}
                    refetch={refetch}
                    held={reading || stale}
                    pageStale={stale}
                    onUnread={announceWhenRead}
                    handoff={handoff}
                    onRefused={refuse}
                    onLost={setLost}
                />
                {/* Outside `Loaded`, which is rebuilt after a write, so the list survives it. It exists only
                    while this page's own read is held, and it asks the page to read again on a 404. */}
                <CharacterRevelationsSection
                    campaignId={campaignId}
                    characterId={characterId}
                    onGone={() => void refetch()}
                />
            </>
        )
    }
    return (
        <section
            className="authoring-page"
            aria-labelledby="public-profile-heading"
            // The control the person last used, so a rebuilt form can give it back. A control inside a
            // dialog is represented by the button that opened it (noted where it opens).
            onFocus={(event) => handoff.note(event.target)}
        >
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

const NOTE_MAX = 1000

const RELEASE_REFUSAL: Readonly<Record<string, string>> = {
    character_reveal_required: "You no longer have authority to release this profile. Nothing was released.",
    public_profile_field_withheld:
        "A field of this profile cannot be released by you, so nothing was released.",
    stale_write: "The draft or character changed since you opened it. Nothing was released; review the latest draft and try again.",
    public_profile_identity_version_required:
        "The draft or character changed since you opened it. Nothing was released; review the latest draft and try again.",
    public_profile_draft_missing: "There is no saved draft to release, so nothing was released.",
    public_profile_character_not_active: "This character is archived, so its public profile cannot be released.",
    campaign_archived: "This campaign is archived, so nothing can be released.",
    public_profile_identity_unavailable:
        "The character's species and size are not available to release right now, so nothing was released.",
}

function releaseRefusal(error: AuthoringError): string | null {
    const code = error.code ?? ""
    if (error.kind === "stale") return RELEASE_REFUSAL.stale_write!
    if (error.kind === "denied")
        return RELEASE_REFUSAL[code] ?? "Releasing this profile is not available to you right now. Nothing was released."
    // A 422 for the missing character version means the read the person saw is out of date.
    if (error.kind === "conflict" || (error.kind === "invalid" && code === "public_profile_identity_version_required"))
        return RELEASE_REFUSAL[code] ?? null
    return null
}

const RELEASE_AUTHORITY: Readonly<Record<string, string>> = { owner: "Owner", delegation: "Delegated GM" }

const when = (iso: string): string => new Date(iso).toLocaleString()

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
    handoff,
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
    handoff: FocusHandoff
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
    const [releasing, setReleasing] = useState(false)
    const [note, setNote] = useState("")
    const [releasedMessage, setReleasedMessage] = useState<string | null>(null)

    // A field the latest read withholds holds no text here, whatever was typed before it was withheld, and
    // a field that stops being withheld shows the draft's text, not what was typed under the old read.
    const withheldNow = {
        appearance: draft?.public_appearance_withheld === true,
        background: draft?.public_background_withheld === true,
    }
    const [seenWithheld, setSeenWithheld] = useState(withheldNow)
    if (seenWithheld.appearance !== withheldNow.appearance || seenWithheld.background !== withheldNow.background) {
        setSeenWithheld(withheldNow)
        setValues((current) => ({
            ...current,
            ...(seenWithheld.appearance !== withheldNow.appearance
                ? { public_appearance: draft?.public_appearance ?? "" }
                : {}),
            ...(seenWithheld.background !== withheldNow.background
                ? { public_background: draft?.public_background ?? "", clear_background: false }
                : {}),
        }))
    }

    // This form is replaced when a read changes the draft or the latest release, and after a refusal. If
    // focus was on something it is about to remove, say so; the form that replaces it gives focus back
    // to that control, or to the status, unless focus has moved to something else that is still there.
    useLayoutEffect(() => {
        handoff.arrive()
        return handoff.leaving
        // Once per form: it runs for the form that replaces the old one, and cleans up for the old one.
    }, [handoff])

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
                    const typed = retainedFromSave(body)
                    // A refusal for a withheld field cannot say which field, so none that could be withheld is kept.
                    const carried =
                        error.code === "public_profile_field_withheld"
                            ? typed.filter((change) => !PROTECTABLE.has(change.field ?? ""))
                            : typed
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
    // The release names the draft version (and, for species or size, the character version) that the
    // person is looking at. It is built only from the saved read, never from the form.
    const publishesIdentity = draft !== null && (draft.publish_species || draft.publish_size)
    const releaseBody: ReleasePublicProfileBody | null =
        draft === null || (publishesIdentity && view.identity_preview === null)
            ? null
            : {
                  expected_draft_row_version: draft.row_version,
                  ...(note.trim() === "" ? {} : { release_note: note.trim() }),
                  ...(publishesIdentity && view.identity_preview !== null
                      ? { expected_character_row_version: view.identity_preview.character_row_version }
                      : {}),
              }
    const releaseMutation = useAuthoringMutation<ReleasePublicProfileBody, ReleasePublicProfileReceipt>({
        scopeKey: `public-profile-release:${campaignId}:${characterId}`,
        request: async (body, ctx) => {
            try {
                return await releaseCharacterPublicProfile(campaignId, characterId, body, ctx)
            } catch (cause) {
                // As for a save: a refusal that means the page is out of date or the person's authority
                // changed is handled once, here, and the old tokens are never sent again.
                if (!ctx.signal.aborted) {
                    const error = classifyApiError(cause)
                    const carried: RetainedChange[] =
                        body.release_note === undefined ? [] : [{ label: "Release note", value: body.release_note }]
                    if (error.kind === "unavailable") onLost(carried)
                    else {
                        const message = releaseRefusal(error)
                        if (message !== null) onRefused({ message, carried })
                    }
                }
                throw cause
            }
        },
        onSuccess: async (result) => {
            const message = result.created
                ? `Released as version ${result.version_number}.`
                : "This version was already released."
            setReleasedMessage(message)
            setReleasing(false)
            setNote("")
            const outcome = await refetch()
            if (outcome === "ok") announce(message)
            else onUnread(message)
            return outcome
        },
    })
    const releasedRefresh = useConfirmedRefresh({
        status: releaseMutation.status,
        reset: releaseMutation.reset,
        what: "public profile",
        message: releasedMessage,
        read: refetch,
        pageStale,
        quietRecovery: true,
    })
    const writesHeld = held || savedRefresh.held || releasedRefresh.held
    const saving = saveMutation.status.kind === "pending"
    const releasePending = releaseMutation.status.kind === "pending"
    const busy = saving || releasePending || writesHeld
    const error = saveMutation.status.kind === "error" ? saveMutation.status.error : null
    const releaseError = releaseMutation.status.kind === "error" ? releaseMutation.status.error : null

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
            {releasedRefresh.notice}
            <p className="authoring-note">
                The draft of what players may later see about <strong>{view.label.name}</strong>. Saving a draft shows
                nothing to players. Releasing it makes a numbered snapshot, which also shows nothing to anyone: players
                see a release only after you reveal the character.
            </p>
            <section aria-label="Draft status">
                <h2 id={IDS.status} tabIndex={-1}>
                    Draft
                </h2>
                <p>
                    {draft === null ? "No draft has been saved yet." : `Draft version ${draft.row_version}.`}
                    {view.has_unreleased_changes ? " Unreleased changes." : ""}
                </p>
                <p>{latest === null ? "Nothing has been released yet." : `Latest release: version ${latest.version_number}.`}</p>
                {view.identity_differs_from_latest_release === true ? (
                    <p>Species or size has changed since the last release.</p>
                ) : null}
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
                                id={IDS.clear}
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
                                id={IDS.species}
                                type="checkbox"
                                checked={values.publish_species}
                                onChange={(event) => set("publish_species", event.currentTarget.checked)}
                            />{" "}
                            {`Publish species${view.identity_preview !== null ? `: ${view.identity_preview.species.label}` : ""}`}
                        </label>
                        <label className="authoring-checkbox">
                            <input
                                id={IDS.size}
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
                            id={IDS.save}
                            type="submit"
                            className="authoring-button authoring-button--primary"
                            disabled={!dirty || busy}
                            aria-busy={saving}
                        >
                            {saving ? "Saving…" : "Save draft"}
                        </button>
                        <button
                            id={IDS.discard}
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
            {draft !== null ? (
                <section aria-label="Release">
                    <h2>Release</h2>
                    {view.can_release ? (
                        <>
                            <button
                                id={IDS.release}
                                type="button"
                                className="authoring-button authoring-button--primary"
                                disabled={dirty || busy || releaseBody === null}
                                onClick={() => {
                                    // The dialog returns here; so does a rebuilt form if the page is replaced meanwhile.
                                    handoff.note(null, IDS.release)
                                    setReleasing(true)
                                }}
                            >
                                Release
                            </button>
                            {dirty ? <p>Save your changes before releasing.</p> : null}
                        </>
                    ) : (
                        <p>You can't release this profile.</p>
                    )}
                </section>
            ) : null}
            {draft !== null && releaseBody !== null ? (
                <ConfirmDialog
                    open={releasing}
                    title={`Release draft version ${draft.row_version}?`}
                    description="Releasing doesn't show this profile to anyone. Players see it only after you reveal the character."
                    confirmLabel={`Release as version ${(latest?.version_number ?? 0) + 1}`}
                    cancelLabel="Cancel"
                    pending={releasePending}
                    confirmDisabled={note.trim().length > NOTE_MAX}
                    reason={{
                        label: "Release note (optional)",
                        required: false,
                        value: note,
                        onChange: setNote,
                        error: note.trim().length > NOTE_MAX ? `The note must be ${NOTE_MAX} characters or fewer.` : null,
                    }}
                    error={
                        releaseError !== null ? (
                            <MutationStatusMessage
                                error={releaseError}
                                onRetry={() => releaseMutation.retry()}
                                onCheckSession={reload}
                            />
                        ) : null
                    }
                    onConfirm={() => {
                        if (!busy) releaseMutation.submit(releaseBody)
                    }}
                    onCancel={() => setReleasing(false)}
                />
            ) : null}
            {latest !== null ? <LatestRelease release={latest} /> : null}
            <ReleaseHistory releases={view.releases} />
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

// The latest release exactly as it was snapshotted: its own text and published labels, never merged
// with the draft. Origins and provenance are not shown.
function LatestRelease({ release }: { release: PublicProfileLatestRelease }) {
    const text = (value: string | null) => (trimmed(value) === "" ? "(empty)" : value)
    return (
        <section aria-label="Latest release">
            <h2>Latest release (version {release.version_number})</h2>
            <p>
                Released {when(release.released_at)}
                {release.released_by !== null ? ` by ${release.released_by}` : ""}
                {" "}({RELEASE_AUTHORITY[release.authority_source] ?? release.authority_source}). This snapshot does not
                change when the draft does.
            </p>
            <dl className="authoring-fact-list">
                <div>
                    <dt>Summary</dt>
                    <dd>{text(release.public_summary)}</dd>
                </div>
                <div>
                    <dt>Appearance</dt>
                    <dd>{text(release.public_appearance)}</dd>
                </div>
                <div>
                    <dt>Background</dt>
                    <dd>{text(release.public_background)}</dd>
                </div>
                <div>
                    <dt>Species</dt>
                    <dd>{release.species === null ? "Not published" : release.species.label}</dd>
                </div>
                <div>
                    <dt>Size</dt>
                    <dd>{release.size === null ? "Not published" : release.size.label}</dd>
                </div>
                {release.release_note !== null && release.release_note !== "" ? (
                    <div>
                        <dt>Release note</dt>
                        <dd>{release.release_note}</dd>
                    </div>
                ) : null}
            </dl>
        </section>
    )
}

// The metadata of every release, newest first. No text, and no link to a version.
function ReleaseHistory({ releases }: { releases: readonly PublicProfileRelease[] }) {
    if (releases.length === 0) return null
    const newestFirst = [...releases].sort((a, b) => b.version_number - a.version_number)
    return (
        <section aria-label="Release history">
            <h2>Release history</h2>
            <ul className="op-list">
                {newestFirst.map((release) => (
                    <li key={release.version_number}>
                        Version {release.version_number}, {when(release.released_at)}
                        {release.released_by !== null ? `, released by ${release.released_by}` : ""},{" "}
                        {RELEASE_AUTHORITY[release.authority_source] ?? release.authority_source}
                    </li>
                ))}
            </ul>
        </section>
    )
}
