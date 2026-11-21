import { AlertTriangle } from "lucide-react"
import { useEffect, useLayoutEffect, useRef, useState } from "react"
import type { ReactNode } from "react"
import {
    createCharacterRevelation,
    revelationsPath,
    revokeCharacterRevelation,
} from "../../api/characterRevelations"
import { useCampaignCapability } from "../../hooks/useCampaignCapability"
import { useAccessOverview } from "../../hooks/useAccessOverview"
import { useAuthoringMutation } from "../../hooks/useAuthoringMutation"
import { useAuthoringResource } from "../../hooks/useAuthoringResource"
import { useAnnounceWhenRead, useConfirmedRefresh } from "../../hooks/useConfirmedRefresh"
import { useKept } from "../../hooks/useKeptResource"
import { classifyApiError } from "../../types/apiError"
import type { AuthoringError } from "../../types/apiError"
import type {
    CharacterRevelation,
    CharacterRevelationsRead,
    CreateRevelationBody,
    CreateRevelationReceipt,
    RevelationAudienceKind,
    RevokeRevelationReceipt,
    RevokeRevelationSubmit,
} from "../../types/characterRevelations"
import { useAnnounce } from "../authoring/announcer"
import { canTakeFocus } from "../../utils/focusEligibility"
import { ConfirmDialog } from "../authoring/ConfirmDialog"
import { RadioGroupField, SelectField, TextAreaField } from "../authoring/fields"
import { ErrorSummary, MutationStatusMessage } from "../authoring/feedback"
import type { FieldError } from "../authoring/feedback"
import { StaleReadNotice } from "../StaleReadNotice"
import "../authoring/authoring.css"

const REASON_MAX = 1000

const END_REASON: Readonly<Record<string, string>> = {
    revoked: "Revoked",
    target_membership_ended: "Membership ended",
    access_group_deactivated: "Group deactivated",
}

const AUTHORITY: Readonly<Record<string, string>> = { owner: "Owner", delegation: "Delegated GM" }

const when = (iso: string): string => new Date(iso).toLocaleString()

const newestFirst = (rows: readonly CharacterRevelation[]): CharacterRevelation[] =>
    [...rows].sort((a, b) => b.created_at.localeCompare(a.created_at))

// What the audience of a revelation is called. Names only, never ids.
function audienceLabel(revelation: CharacterRevelation): string {
    switch (revelation.audience_kind) {
        case "member":
            return revelation.target_member_name ?? "A member"
        case "access_group":
            return `Group: ${revelation.target_access_group_name ?? "an access group"}`
        case "campaign_current":
            return `Campaign members at the time (${revelation.audience_size ?? 0})`
        case "campaign_current_and_future":
            return "All campaign members, including future ones"
    }
}

const NO_AUTHORITY = "You no longer have authority to reveal this character."

// What the person is told when the server refuses a write for a reason that means the page is out of
// date or their rights changed. Only mapped codes: the server's own words are never shown.
interface Refusal {
    message: string
    // What they typed, shown back read-only because the form it was in is gone or reset.
    reason: string
    // The refusal changes what the page offers (authority, release, archive), so the page reads again.
    pageChanged: boolean
    // The chosen target may no longer be active, so the options are read again.
    targetsChanged: boolean
}

function createRefusal(error: AuthoringError): Omit<Refusal, "reason"> | null {
    const code = error.code ?? ""
    if (error.kind === "denied")
        return { message: NO_AUTHORITY, pageChanged: true, targetsChanged: false }
    if (error.kind === "unavailable")
        return { message: "That audience is no longer available.", pageChanged: false, targetsChanged: true }
    if (error.kind === "conflict") {
        if (code === "revelation_target_not_active")
            return { message: "That member or group is no longer active.", pageChanged: false, targetsChanged: true }
        if (code === "public_profile_not_released")
            return {
                message: "This profile has not been released, so it can't be revealed yet. Release it first.",
                pageChanged: true,
                targetsChanged: false,
            }
        if (code === "public_profile_character_not_active")
            return {
                message: "This character is archived, so it can't be revealed.",
                pageChanged: true,
                targetsChanged: false,
            }
        if (code === "campaign_archived")
            return { message: "This campaign is archived, so nothing can be revealed.", pageChanged: true, targetsChanged: false }
    }
    return null
}

function revokeRefusal(error: AuthoringError): Omit<Refusal, "reason"> | null {
    const code = error.code ?? ""
    if (error.kind === "denied") return { message: NO_AUTHORITY, pageChanged: true, targetsChanged: false }
    if (error.kind === "unavailable")
        return { message: "That revelation is no longer available.", pageChanged: false, targetsChanged: false }
    if (error.kind === "conflict" && code === "campaign_archived")
        return { message: "This campaign is archived, so nothing can be revoked.", pageChanged: true, targetsChanged: false }
    return null
}

// The Revelations section of a character's Public profile page (docs/delivery/p15-c02-s02-revelations-plan.md).
// The page mounts it only while its own read is held, so its audience is the page's audience (the
// D8 read rule), and keys the page on the character, so what was read, typed or is pending for one
// character never appears under another. A 404 means the list may no longer be read: the content
// is dropped and the page is told its own read is denied (`onReadDenied`), which drops the page's protected
// content at once and reads it again; the page decides whether it is gone. That is not a write's 404, which
// only says the audience or revelation may be gone and re-reads the list.
// The offer to reveal or revoke is the server's `can_reveal`; the page never decides authority.
export function CharacterRevelationsSection({
    campaignId,
    characterId,
    hasRelease,
    readPage,
    onReadDenied,
}: {
    campaignId: string
    characterId: string
    // Whether the page's latest read has a release. Create needs one; revoke does not.
    hasRelease: boolean
    // Reads the page again (it decides whether the page is still readable, and what it offers).
    readPage: () => void
    // The list answered 404 or 403 on a read: the page may no longer be readable (the same D8 rule).
    onReadDenied: () => void
}) {
    const path = revelationsPath(campaignId, characterId)
    const { state, refetch } = useAuthoringResource<CharacterRevelationsRead>(path)
    const view = useKept(state, path)
    const announce = useAnnounce()
    const gone = state.kind === "unavailable" || state.kind === "denied"
    const stale = state.kind === "error" && view !== null
    const reading = state.kind === "ready" && state.refreshing
    const announceWhenRead = useAnnounceWhenRead(state.kind === "ready" && !state.refreshing, state)
    const canPickTargets = useCampaignCapability(campaignId, "access.manage")

    const readPageRef = useRef(readPage)
    useEffect(() => {
        readPageRef.current = readPage
    })
    const onReadDeniedRef = useRef(onReadDenied)
    useEffect(() => {
        onReadDeniedRef.current = onReadDenied
    })
    useEffect(() => {
        if (gone) onReadDeniedRef.current()
    }, [gone])

    // The create form.
    const [open, setOpen] = useState(false)
    // "" is no choice: what a member or group choice becomes when the right to pick one is lost, so the person
    // chooses again and a lost target never turns into a wider audience.
    const [kind, setKind] = useState<RevelationAudienceKind | "">("campaign_current")
    const [targetId, setTargetId] = useState("")
    const [reason, setReason] = useState("")
    const [errors, setErrors] = useState<FieldError[]>([])
    const [attempt, setAttempt] = useState(0)
    // The label of the audience being revealed to, kept for the announcement.
    const audienceName = useRef("")
    const [targetsToken, setTargetsToken] = useState(0)
    const [targetName, setTargetName] = useState("")
    // Whether the last create sent a member or group, so a retry of it can be refused after the right to pick one is lost.
    const lastTargeted = useRef(false)
    // Losing `access.manage` withdraws a member or group choice with everything that went with it. It is not
    // restored if the right comes back: the person chooses again.
    const [seenCanPick, setSeenCanPick] = useState(canPickTargets)
    if (seenCanPick !== canPickTargets) {
        setSeenCanPick(canPickTargets)
        if (!canPickTargets) {
            if (kind === "member" || kind === "access_group") setKind("")
            setTargetId("")
            setTargetName("")
            setErrors((current) => current.filter((e) => e.fieldId !== "revelation-target"))
        }
    }
    // The revoke dialog.
    const [revoking, setRevoking] = useState<CharacterRevelation | null>(null)
    const [revokeReason, setRevokeReason] = useState("")
    // What a refused write says, until it is dismissed.
    const [refusal, setRefusal] = useState<Refusal | null>(null)
    const [createdMessage, setCreatedMessage] = useState<string | null>(null)
    const [revokedMessage, setRevokedMessage] = useState<string | null>(null)
    // Raised after a confirmed write is read back, so focus lost with a removed control is put back.
    const [refocus, setRefocus] = useState(0)
    const revealRef = useRef<HTMLButtonElement>(null)
    const headingRef = useRef<HTMLHeadingElement>(null)

    function refuse(next: Omit<Refusal, "reason">, typed: string) {
        setRefusal({ ...next, reason: typed })
        if (next.targetsChanged) setTargetsToken((n) => n + 1)
        void refetch()
        if (next.pageChanged) readPageRef.current()
    }

    const createMutation = useAuthoringMutation<CreateRevelationBody, CreateRevelationReceipt>({
        scopeKey: `revelation-create:${campaignId}:${characterId}`,
        request: async (body, ctx) => {
            try {
                return await createCharacterRevelation(campaignId, characterId, body, ctx)
            } catch (cause) {
                // Handled once, here, and only for this scope's own live request: the old body is never re-sent.
                if (!ctx.signal.aborted) {
                    const error = classifyApiError(cause)
                    const mapped = createRefusal(error)
                    if (mapped !== null) refuse(mapped, body.reason)
                }
                throw cause
            }
        },
        onSuccess: async (result) => {
            const message = result.created
                ? `Revealed to ${audienceName.current}.`
                : "That audience can already see this profile."
            setCreatedMessage(message)
            setOpen(false)
            setReason("")
            setTargetId("")
            setRefusal(null)
            const outcome = await refetch()
            if (outcome === "ok") announce(message)
            else announceWhenRead(message)
            setRefocus((n) => n + 1)
            return outcome
        },
    })
    const createRefresh = useConfirmedRefresh({
        status: createMutation.status,
        reset: createMutation.reset,
        what: "revelations",
        message: createdMessage,
        read: refetch,
        pageStale: stale,
        quietRecovery: true,
    })

    const revokeMutation = useAuthoringMutation<RevokeRevelationSubmit, RevokeRevelationReceipt>({
        scopeKey: `revelation-revoke:${campaignId}:${characterId}:${revoking?.character_revelation_id ?? ""}`,
        request: async (submit, ctx) => {
            try {
                return await revokeCharacterRevelation(campaignId, characterId, submit, ctx)
            } catch (cause) {
                if (!ctx.signal.aborted) {
                    const mapped = revokeRefusal(classifyApiError(cause))
                    if (mapped !== null) {
                        setRevoking(null)
                        setRevokeReason("")
                        refuse(mapped, submit.reason)
                    }
                }
                throw cause
            }
        },
        onSuccess: async (result) => {
            const message = result.revoked ? "Revocation saved." : "That revelation had already ended."
            setRevokedMessage(message)
            setRevoking(null)
            setRevokeReason("")
            setRefusal(null)
            const outcome = await refetch()
            if (outcome === "ok") announce(message)
            else announceWhenRead(message)
            setRefocus((n) => n + 1)
            return outcome
        },
    })
    const revokeRefresh = useConfirmedRefresh({
        status: revokeMutation.status,
        reset: revokeMutation.reset,
        what: "revelations",
        message: revokedMessage,
        read: refetch,
        pageStale: stale,
        quietRecovery: true,
    })

    // After a write has been read back, a control that held focus may be gone (the form closed, the
    // revoked row moved). Focus goes to Reveal, or the section heading, only if it is on nothing; focus
    // the person moved to something still on the page is left alone.
    // Reveal is the target only if it can take focus now (it is disabled while a failed read holds writes);
    // otherwise the section heading, which is always there.
    useLayoutEffect(() => {
        if (refocus === 0) return
        const active = document.activeElement
        if (active !== null && active !== document.body) return
        const place = canTakeFocus(revealRef.current) ? revealRef.current : headingRef.current
        place?.focus()
    }, [refocus])
    // A failed create that sent a member or group offers no retry once the right to pick one is gone.
    const createStatusKind = createMutation.status.kind
    const discardCreate = createMutation.discard
    // The attempt's outcome is unknown, so it is not called unsent; it is only no longer ours to repeat. Its body,
    // reserved key and retry go, so choosing the same member again later is a new attempt under a new key.
    useEffect(() => {
        if (!canPickTargets && lastTargeted.current && createStatusKind === "error") {
            discardCreate()
            lastTargeted.current = false
        }
    }, [canPickTargets, createStatusKind, discardCreate])

    const writesHeld = reading || stale || createRefresh.held || revokeRefresh.held
    const creating = createMutation.status.kind === "pending"
    const revokePending = revokeMutation.status.kind === "pending"
    // A refusal the section explains itself (the alert above) is not shown a second time as a generic error.
    const createError =
        createMutation.status.kind === "error" && createRefusal(createMutation.status.error) === null
            ? createMutation.status.error
            : null
    const revokeError =
        revokeMutation.status.kind === "error" && revokeRefusal(revokeMutation.status.error) === null
            ? revokeMutation.status.error
            : null
    const canReveal = view?.can_reveal === true
    const needsTarget = kind === "member" || kind === "access_group"
    const kinds: { value: RevelationAudienceKind; label: string }[] = [
        { value: "campaign_current", label: "Everyone in the campaign now" },
        { value: "campaign_current_and_future", label: "Everyone in the campaign, including future members" },
        ...(canPickTargets
            ? [
                  { value: "member" as const, label: "One member" },
                  { value: "access_group" as const, label: "One access group" },
              ]
            : []),
    ]

    function submit() {
        // Whatever the form still holds, a member or group is sent only while the right to pick one is held now.
        if (needsTarget && !canPickTargets) return
        if (creating || writesHeld) return
        const trimmed = reason.trim()
        const problems: FieldError[] = []
        if (trimmed === "") problems.push({ fieldId: "revelation-reason", message: "Give a reason." })
        else if (trimmed.length > REASON_MAX)
            problems.push({ fieldId: "revelation-reason", message: `The reason must be ${REASON_MAX} characters or fewer.` })
        if (kind === "") problems.push({ fieldId: "revelation-kind", message: "Choose who to reveal to." })
        if (needsTarget && targetId === "")
            problems.push({
                fieldId: "revelation-target",
                message: kind === "member" ? "Choose a member." : "Choose an access group.",
            })
        setErrors(problems)
        if (problems.length > 0) {
            setAttempt((n) => n + 1)
            return
        }
        if (kind === "") return
        audienceName.current =
            kind === "member"
                ? targetName
                : kind === "access_group"
                  ? `Group: ${targetName}`
                  : kind === "campaign_current"
                    ? "the campaign members now"
                    : "all campaign members, including future ones"
        const body: CreateRevelationBody = {
            audience_kind: kind,
            ...(kind === "member" ? { target_campaign_membership_id: targetId } : {}),
            ...(kind === "access_group" ? { target_access_group_id: targetId } : {}),
            reason: trimmed,
        }
        lastTargeted.current = needsTarget
        createMutation.submit(body)
    }

    let body
    if (gone) {
        body = <p>The revelations of this character are not available to you.</p>
    } else if (view === null) {
        body =
            state.kind === "error" ? (
                <StaleReadNotice what="revelations" onRetry={() => void refetch()} />
            ) : (
                <p role="status">Loading revelations…</p>
            )
    } else {
        const live = newestFirst(view.revelations.filter((r) => r.live))
        const ended = newestFirst(view.revelations.filter((r) => !r.live))
        const row = (revelation: CharacterRevelation) => (
            <RevelationRow
                key={revelation.character_revelation_id}
                revelation={revelation}
                action={
                    canReveal && revelation.live ? (
                        <button
                            type="button"
                            className="authoring-button"
                            disabled={revokePending}
                            onClick={() => {
                                setRevokeReason("")
                                setRevoking(revelation)
                            }}
                        >
                            Revoke<span className="visually-hidden"> {audienceLabel(revelation)}</span>
                        </button>
                    ) : null
                }
            />
        )
        body = (
            <>
                {state.kind === "error" ? <StaleReadNotice what="revelations" onRetry={() => void refetch()} /> : null}
                {createRefresh.notice}
                {revokeRefresh.notice}
                {refusal !== null ? (
                    <div className="authoring-message authoring-message--warning" role="alert">
                        <AlertTriangle aria-hidden="true" className="authoring-message__icon" />
                        <div>
                            <p>{refusal.message}</p>
                            <section aria-label="Your unsent reason" className="authoring-your-changes">
                                <h4>Your reason, not sent</h4>
                                <p>{refusal.reason}</p>
                            </section>
                            <button type="button" className="authoring-button" onClick={() => setRefusal(null)}>
                                Dismiss
                            </button>
                        </div>
                    </div>
                ) : null}
                {canReveal ? (
                    hasRelease ? (
                        open ? null : (
                            <button
                                ref={revealRef}
                                type="button"
                                className="authoring-button authoring-button--primary"
                                disabled={writesHeld}
                                onClick={() => {
                                    setRefusal(null)
                                    setOpen(true)
                                }}
                            >
                                Reveal
                            </button>
                        )
                    ) : (
                        <p>Release the profile before revealing it.</p>
                    )
                ) : (
                    <p>You can't reveal or revoke this character.</p>
                )}
                {canReveal && hasRelease && open ? (
                    <form
                        noValidate
                        aria-label="Reveal this character"
                        className="authoring-form"
                        onSubmit={(event) => {
                            event.preventDefault()
                            submit()
                        }}
                    >
                        <ErrorSummary errors={errors} attempt={attempt} />
                        <p className="authoring-note">
                            A revelation lets its audience see this character's released public profile. It is seen on
                            their next request.
                        </p>
                        <RadioGroupField
                            id="revelation-kind"
                            legend="Reveal to"
                            value={kind}
                            options={kinds}
                            error={errors.find((e) => e.fieldId === "revelation-kind")?.message ?? null}
                            onChange={(value) => {
                                setKind(value as RevelationAudienceKind)
                                setTargetId("")
                                setTargetName("")
                            }}
                        />
                        {!canPickTargets ? (
                            <p className="authoring-field__hint">
                                To reveal to one member or group, ask someone who manages campaign access.
                            </p>
                        ) : null}
                        {canPickTargets && needsTarget ? (
                            <TargetPicker
                                campaignId={campaignId}
                                kind={kind}
                                value={targetId}
                                refreshToken={targetsToken}
                                error={errors.find((e) => e.fieldId === "revelation-target")?.message ?? null}
                                onChange={(id, name) => {
                                    setTargetId(id)
                                    setTargetName(name)
                                }}
                            />
                        ) : null}
                        <TextAreaField
                            id="revelation-reason"
                            label="Reason"
                            hint="Private to the GMs. It is not shown to the audience."
                            value={reason}
                            onChange={setReason}
                            maxLength={REASON_MAX}
                            required
                            error={errors.find((e) => e.fieldId === "revelation-reason")?.message ?? null}
                        />
                        {createError !== null ? (
                            <MutationStatusMessage
                                error={createError}
                                onRetry={() => {
                                    if (lastTargeted.current && !canPickTargets) {
                                        createMutation.discard()
                                        lastTargeted.current = false
                                    } else createMutation.retry()
                                }}
                                onCheckSession={() => readPageRef.current()}
                            />
                        ) : null}
                        <div className="authoring-actions">
                            <button
                                type="submit"
                                className="authoring-button authoring-button--primary"
                                disabled={creating || writesHeld}
                                aria-busy={creating}
                            >
                                {creating ? "Revealing…" : "Reveal"}
                            </button>
                            <button
                                type="button"
                                className="authoring-button"
                                disabled={creating}
                                onClick={() => {
                                    setOpen(false)
                                    setErrors([])
                                }}
                            >
                                Cancel
                            </button>
                        </div>
                    </form>
                ) : null}
                {view.revelations.length === 0 ? <p>This character hasn't been revealed to anyone.</p> : null}
                {live.length > 0 ? (
                    <section aria-label="Visible to">
                        <h3>Visible to</h3>
                        <ul className="op-list">{live.map(row)}</ul>
                    </section>
                ) : null}
                {ended.length > 0 ? (
                    <section aria-label="Ended">
                        <h3>Ended</h3>
                        <ul className="op-list">{ended.map(row)}</ul>
                    </section>
                ) : null}
                <ConfirmDialog
                    open={revoking !== null}
                    title={revoking === null ? "Revoke" : `Revoke access for ${audienceLabel(revoking)}?`}
                    description="Those people lose the access this revelation gave them, unless another revelation or role still gives it. They see the change on their next request."
                    confirmLabel="Revoke"
                    cancelLabel="Cancel"
                    pending={revokePending}
                    confirmDisabled={revokeReason.trim() === "" || revokeReason.trim().length > REASON_MAX}
                    reason={{
                        label: "Reason for revoking",
                        required: true,
                        value: revokeReason,
                        onChange: setRevokeReason,
                        error:
                            revokeReason.trim().length > REASON_MAX
                                ? `The reason must be ${REASON_MAX} characters or fewer.`
                                : null,
                    }}
                    error={
                        revokeError !== null ? (
                            <MutationStatusMessage
                                error={revokeError}
                                onRetry={() => revokeMutation.retry()}
                                onCheckSession={() => readPageRef.current()}
                            />
                        ) : null
                    }
                    onConfirm={() => {
                        if (revoking === null || revokePending || writesHeld) return
                        revokeMutation.submit({
                            character_revelation_id: revoking.character_revelation_id,
                            reason: revokeReason.trim(),
                        })
                    }}
                    onCancel={() => setRevoking(null)}
                />
            </>
        )
    }
    return (
        <section aria-label="Revelations" className="authoring-section">
            <h2 ref={headingRef} tabIndex={-1}>
                Revelations
            </h2>
            {body}
        </section>
    )
}

// The members or groups the access overview offers, active ones only. Mounted only for a person who holds
// `access.manage` and has chosen a member or group audience, so the overview is read only then. The
// selection is cleared when a re-read no longer offers it.
function TargetPicker({
    campaignId,
    kind,
    value,
    refreshToken,
    error,
    onChange,
}: {
    campaignId: string
    kind: RevelationAudienceKind
    value: string
    refreshToken: number
    error: string | null
    onChange: (id: string, name: string) => void
}) {
    const { state, retry } = useAccessOverview(campaignId)
    const first = useRef(refreshToken)
    useEffect(() => {
        if (first.current !== refreshToken) {
            first.current = refreshToken
            retry()
        }
    }, [refreshToken, retry])
    const options =
        state.status === "success"
            ? kind === "member"
                ? state.overview.members
                      .filter((m) => m.status_code === "active")
                      .map((m) => ({ value: m.campaign_membership_id, label: m.display_name }))
                : state.overview.access_groups
                      .filter((g) => g.status_code === "active")
                      .map((g) => ({ value: g.access_group_id, label: g.name }))
            : []
    const offered = options.some((o) => o.value === value)
    useEffect(() => {
        if (state.status === "success" && value !== "" && !offered) onChange("", "")
    }, [state.status, value, offered, onChange])
    if (state.status === "loading") return <p role="status">Loading the people you can choose…</p>
    if (state.status !== "success")
        return (
            <p role="alert">
                The people you can choose could not be loaded.{" "}
                <button type="button" className="authoring-button" onClick={retry}>
                    Try again
                </button>
            </p>
        )
    return (
        <SelectField
            id="revelation-target"
            label={kind === "member" ? "Member" : "Access group"}
            value={value}
            options={options}
            placeholder={kind === "member" ? "Choose a member" : "Choose an access group"}
            required
            error={error}
            onChange={(id) => onChange(id, options.find((o) => o.value === id)?.label ?? "")}
        />
    )
}

function RevelationRow({ revelation, action }: { revelation: CharacterRevelation; action: ReactNode }) {
    return (
        <li>
            <p>
                <strong>{audienceLabel(revelation)}</strong>
            </p>
            <p>
                Revealed by {revelation.created_by_name} on {when(revelation.created_at)} (
                {AUTHORITY[revelation.authority_source] ?? revelation.authority_source})
            </p>
            {!revelation.live && revelation.ended_at !== null ? (
                <p>
                    Ended {when(revelation.ended_at)}: {END_REASON[revelation.end_reason ?? ""] ?? "Ended"}
                </p>
            ) : null}
            {revelation.audience_kind === "campaign_current" && revelation.snapshot_members !== undefined ? (
                <details>
                    <summary>Members at the time</summary>
                    <ul>
                        {revelation.snapshot_members.map((member) => (
                            <li key={member.campaign_membership_id}>
                                {member.display_name}
                                {member.removed_at !== null ? " (Left the campaign)" : ""}
                            </li>
                        ))}
                    </ul>
                </details>
            ) : null}
            {action}
        </li>
    )
}
