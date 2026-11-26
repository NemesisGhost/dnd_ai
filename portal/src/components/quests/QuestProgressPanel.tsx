import { useEffect, useRef, useState } from "react"
import { questProgressPath, runQuestRuntimeCommand } from "../../api/questRuntime"
import { useSession } from "../../context/SessionContext"
import { useAuthoringMutation } from "../../hooks/useAuthoringMutation"
import type { RefreshOutcome } from "../../hooks/useAuthoringMutation"
import { useAuthoringResource } from "../../hooks/useAuthoringResource"
import type { QuestOutcomeView } from "../../types/questAuthoring"
import type { QuestAction, QuestProgress, RuntimeCommand, RuntimeReceipt, ScopeProgress } from "../../types/questRuntime"
import { combineRefetchOutcomes } from "../../utils/refreshOutcome"
import { useAnnounce } from "../authoring/announcer"
import { ConfirmDialog } from "../authoring/ConfirmDialog"
import { MutationStatusMessage, StaleWriteNotice } from "../authoring/feedback"
import { canTakeFocus } from "../../utils/focusEligibility"
import { QuestActionReceipts } from "./QuestActionReceipts"
import { receiptHeadingId, receiptHeadingText } from "./questReceipts"
import type { QuestReceipt } from "./questReceipts"
import { QuestFinishReview } from "./QuestFinishReview"
import type { QuestOptionLabels } from "./QuestFinishReview"
import { statusLabel } from "./questStatusLabel"
import { useUnsavedReport } from "./useUnsavedReport"
import type { ReportUnsaved } from "./useUnsavedReport"
import "../authoring/authoring.css"

const ACTION_LABEL: Readonly<Record<QuestAction, string>> = {
    activate: "Activate quest",
    complete: "Complete quest",
    fail: "Fail quest",
    suspend: "Suspend quest",
    resume: "Resume quest",
    abandon: "Abandon quest",
}

const OBJECTIVE_VERB: Readonly<Record<string, string>> = {
    available: "Reveal",
    active: "Start",
    completed: "Complete",
    failed: "Fail",
    skipped: "Skip",
}

const CODE_MESSAGE: Readonly<Record<string, string>> = {
    quest_transition_invalid: "The quest is not in a state that allows that. Reload to see where it is now.",
    quest_not_active: "Activate the quest, and resume it if it is suspended, before changing its objectives.",
    objective_transition_invalid: "The objective is not in a state that allows that.",
    clock_required: "Set the campaign time first.",
}

const RECEIPT_LIMIT = 10

// What the page's departure guard says while a quest request is pending or its answer was lost.
const UNKNOWN_LABEL = "a quest action whose result is not known"

// A quest action whose answer was lost, and whether progress has been read again since.
interface UnknownAttempt {
    seq: number
    action: QuestAction
    partyId: string | null
    who: string
    phase: "reading" | "read" | "unread"
}

const NO_LABELS: QuestOptionLabels = { outcomeCategories: [], rewardTypes: [] }

// Finishing a quest is a decision the GM confirms; the rest act at once.
const CONFIRMED: ReadonlySet<QuestAction> = new Set(["complete", "fail", "abandon"])

interface Props {
    campaignId: string
    questId: string
    // Why the commands are not offered (the page's own reading of the quest's status), or null when
    // the quest is published and active. An unknown status is also a reason: it is not eligibility.
    blockedText: string | null
    // Bumped by the page when the quest changed elsewhere (a lifecycle step, a save): progress is
    // read again in place, so nothing typed here is lost and nothing is remounted.
    refreshToken: number
    onUnsaved: ReportUnsaved
    // Called after a command succeeded and progress was read again, so the page reads what progress
    // decides (whether the structure is now locked) again too.
    onChanged?: () => Promise<RefreshOutcome> | void
    // The quest's authored outcomes and rewards, and the words for their kinds, from the reads the page
    // already holds. They are shown before finishing the quest as descriptions only: nothing here applies them.
    // Omitted where the quest's definition cannot be read (the page's progress-only view for a campaign GM).
    outcomes?: readonly QuestOutcomeView[]
    optionLabels?: QuestOptionLabels
}

// How far the campaign and each party have got, and the explicit moves the GM can make. This is
// timeline state under decision D-16: only these commands change it, and nothing completes a quest
// by itself. It is separate from the quest's publication and from the authored stages. Mounted
// only for editors, inside the Quest workspace.
export function QuestProgressPanel({
    campaignId,
    questId,
    blockedText,
    refreshToken,
    onUnsaved,
    onChanged,
    outcomes,
    optionLabels,
}: Props) {
    const { reload } = useSession()
    const announce = useAnnounce()
    const { state, refetch } = useAuthoringResource<QuestProgress>(questProgressPath(campaignId, questId))
    const [done, setDone] = useState<string | null>(null)
    const [confirm, setConfirm] = useState<{ scope: ScopeProgress; action: QuestAction } | null>(null)
    const [note, setNote] = useState("")
    // Which scope the details show (presentation only: nothing is sent). The campaign-wide scope has no party.
    const [selected, setSelected] = useState<string | null>(null)
    // The last read that succeeded. A refresh that fails recoverably keeps it on screen, said to be
    // possibly out of date, with Try again (which only reads); a denied or unavailable answer, or
    // another quest, discards it and fails closed.
    const [kept, setKept] = useState<QuestProgress | null>(null)
    if (state.kind === "ready" && kept !== state.data) setKept(state.data)
    if ((state.kind === "denied" || state.kind === "unavailable") && kept !== null) setKept(null)

    const first = useRef(true)
    useEffect(() => {
        if (first.current) {
            first.current = false
            return
        }
        void refetch()
    }, [refreshToken, refetch])

    // This visit's confirmed quest changes (newest first, the last RECEIPT_LIMIT), held in memory only.
    const [receipts, setReceipts] = useState<QuestReceipt[]>([])
    // A quest action whose answer was lost: what it was, for whom, and whether progress has been read again since.
    const [unknown, setUnknown] = useState<UnknownAttempt | null>(null)
    const nextReceipt = useRef(0)
    const nextUnknown = useRef(0)
    // The party names seen in progress reads, so a receipt names the party the confirmed request named.
    const partyNames = useRef(new Map<string, string>())
    // The quest action last sent (for a lost answer) and the controls the person used for it (for focus).
    const lastQuest = useRef<{ action: QuestAction; partyId: string | null; who: string } | null>(null)
    const origins = useRef<{ opener: Element | null; origin: Element | null }>({ opener: null, origin: null })
    const pendingFocus = useRef<{ id: string; opener: Element | null; origin: Element | null } | null>(null)
    const handledError = useRef<unknown>(null)

    const mutation = useAuthoringMutation<RuntimeCommand, RuntimeReceipt>({
        scopeKey: `quest-runtime:${questId}`,
        request: (command, ctx) => runQuestRuntimeCommand(campaignId, questId, command, ctx),
        onSuccess: async (result, body) => {
            const message = done
            setDone(null)
            setConfirm(null)
            setNote("")
            setUnknown(null)
            // The panel's own progress read and the quest read the page does after it: both must
            // have been applied for the command to be shown as done.
            const progress = await refetch()
            const outcome = combineRefetchOutcomes([progress, (await onChanged?.()) ?? "ok"])
            if (body.op === "quest") {
                const who = body.party_id === null ? "Everyone" : (partyNames.current.get(body.party_id) ?? "the party")
                nextReceipt.current += 1
                const id = String(nextReceipt.current)
                const finishing = CONFIRMED.has(body.action)
                const hasRewards = outcomes?.some((o) => o.rewards.length > 0)
                setReceipts((before) =>
                    [
                        {
                            id,
                            action: body.action,
                            who,
                            previous: result.previous_status,
                            status: result.status,
                            changed: result.changed,
                            eventId: result.event_id,
                            readBack: progress === "ok",
                            rewardsLine:
                                !finishing || hasRewards === false
                                    ? null
                                    : hasRewards === true
                                      ? "Rewards described in this quest were not applied."
                                      : "Authored rewards, if any, were not applied.",
                        },
                        ...before,
                    ].slice(0, RECEIPT_LIMIT),
                )
                pendingFocus.current = { id, ...origins.current }
                if (outcome === "ok") announce(receiptHeadingText(body.action, who))
            } else if (outcome === "ok" && message !== null) {
                announce(message)
            }
            return outcome
        },
    })
    const error = mutation.status.kind === "error" ? mutation.status.error : null
    const busy = mutation.status.kind === "pending"
    const explained = error?.code ? (CODE_MESSAGE[error.code] ?? null) : null
    // A lost answer: the request may or may not have been recorded.
    const lostAnswer = error !== null && (error.kind === "network" || error.kind === "server")

    // Leaving the page asks first while a quest request is pending or its result is not known; a typed note
    // is reported as before. A lost answer stops counting once progress has been read again.
    const unresolved = busy || (unknown !== null ? unknown.phase !== "read" : lostAnswer)
    useUnsavedReport(onUnsaved, "progress", [
        ...(confirm !== null && note.trim() !== "" ? ["a note for the quest action"] : []),
        ...(unresolved ? [UNKNOWN_LABEL] : []),
    ])

    // Reads progress once (read-only) after a lost answer, and says what it found.
    const reconcile = (attempt: { action: QuestAction; partyId: string | null; who: string }) => {
        nextUnknown.current += 1
        const seq = nextUnknown.current
        setUnknown({ ...attempt, seq, phase: "reading" })
        void refetch().then((outcome) =>
            setUnknown((current) =>
                current !== null && current.seq === seq ? { ...current, phase: outcome === "ok" ? "read" : "unread" } : current,
            ),
        )
    }
    // A lost answer on an action with no dialog is reconciled at once; in a dialog, its own retry message
    // stays and the read happens when it is cancelled.
    useEffect(() => {
        if (mutation.status.kind !== "error" || !lostAnswer || confirm !== null) return
        if (handledError.current === mutation.status) return
        handledError.current = mutation.status
        if (lastQuest.current !== null) reconcile(lastQuest.current)
    })

    // Focus moves to a new receipt only when focus was still where the action left it: nowhere, on the control
    // that started it, or in its dialog. Anything else the person chose, or a hidden section, keeps it.
    useEffect(() => {
        const pending = pendingFocus.current
        if (pending === null || receipts[0]?.id !== pending.id) return
        pendingFocus.current = null
        const active = document.activeElement
        const closedDialog = pending.origin instanceof Element ? pending.origin.closest("dialog") : null
        const ours =
            active === null ||
            active === document.body ||
            active === pending.origin ||
            active === pending.opener ||
            (closedDialog !== null && closedDialog.contains(active))
        const target = document.getElementById(receiptHeadingId(pending.id))
        if (ours && canTakeFocus(target)) target.focus()
    }, [receipts])

    const run = (command: RuntimeCommand, message: string | null) => {
        setDone(message)
        origins.current = { opener: origins.current.opener, origin: document.activeElement }
        mutation.submit(command)
    }
    const questCommand = (scope: ScopeProgress, action: QuestAction, text: string | null) => {
        lastQuest.current = { action, partyId: scope.party_id, who: scope.party_name ?? "Everyone" }
        run({ op: "quest", action, party_id: scope.party_id, expected_status: scope.status, note: text }, null)
    }
    const checkReceipt = (id: string) => {
        void refetch().then((outcome) => {
            if (outcome === "ok") setReceipts((before) => before.map((r) => (r.id === id ? { ...r, readBack: true } : r)))
        })
    }

    const staleOrError =
        error?.kind === "stale" ? (
            <StaleWriteNotice
                onLoadLatest={() => {
                    mutation.reset()
                    void refetch()
                }}
            />
        ) : explained !== null ? (
            <p role="alert">{explained}</p>
        ) : error !== null ? (
            <MutationStatusMessage error={error} onRetry={mutation.retry} onCheckSession={reload} />
        ) : null

    const stale = state.kind === "error" && kept !== null
    const data = state.kind === "ready" ? state.data : stale ? kept : null
    useEffect(() => {
        for (const s of data?.scopes ?? []) {
            if (s.party_id !== null && s.party_name !== null) partyNames.current.set(s.party_id, s.party_name)
        }
    }, [data])
    if (data === null) {
        return state.kind === "loading" ? (
            <p role="status">Loading progress…</p>
        ) : state.kind === "error" ? (
            <div className="authoring-message authoring-message--warning" role="alert">
                <p>Progress could not be loaded.</p>
                <button type="button" className="authoring-button" onClick={() => void refetch()}>
                    Try again
                </button>
            </div>
        ) : (
            <p role="alert">This quest does not exist, or you do not have access to it.</p>
        )
    }
    const offered = blockedText === null
    const scope = data.scopes.find((s) => s.party_id === selected) ?? data.scopes[0]!
    return (
        <>
            {blockedText !== null ? <p className="authoring-note">{blockedText}</p> : null}
            {offered && !data.published ? (
                <p className="authoring-note">This quest is not published, so it cannot be run until it is.</p>
            ) : null}
            <p className="authoring-note">
                Progress is kept for the whole campaign and for each party on its own. Publishing a quest does not
                start it, and nothing completes it automatically.
            </p>
            {stale ? (
                <div className="authoring-message authoring-message--warning" role="alert">
                    <p>The latest progress could not be loaded, so what is shown may be out of date.</p>
                    <button type="button" className="authoring-button" onClick={() => void refetch()}>
                        Try again
                    </button>
                </div>
            ) : null}
            {staleOrError}
            {unknown === null ? null : (
                <div className="authoring-message authoring-message--warning" role="status">
                    <p>
                        {`The request to ${unknown.action} the quest for ${unknown.who} may have been recorded.`}
                        {unknown.phase === "reading" ? " Progress is being read again." : ""}
                    </p>
                    {unknown.phase === "read" ? (
                        <p>
                            {`Progress was read again: ${unknown.who} is ${statusLabel(data.scopes.find((s) => s.party_id === unknown.partyId)?.status ?? null)}.`}
                        </p>
                    ) : null}
                    {unknown.phase === "unread" ? <p>Progress could not be read again.</p> : null}
                    {unknown.phase === "reading" ? null : (
                        <button type="button" className="authoring-button" onClick={() => reconcile(unknown)}>
                            Check progress
                        </button>
                    )}
                </div>
            )}
            <QuestActionReceipts campaignId={campaignId} receipts={receipts} onCheck={checkReceipt} />
            <div className="quest-progress">
                <nav aria-label="Progress scopes" className="quest-progress__scopes">
                    <ul>
                        {data.scopes.map((s) => (
                            <li key={s.party_id ?? "everyone"}>
                                <button
                                    type="button"
                                    className={
                                        s === scope
                                            ? "quest-progress__scope quest-progress__scope--current"
                                            : "quest-progress__scope"
                                    }
                                    aria-pressed={s === scope}
                                    onClick={() => setSelected(s.party_id)}
                                >
                                    <span>{s.party_name ?? "Everyone"}</span>
                                    <span className="quest-progress__scope-status">{statusLabel(s.status)}</span>
                                </button>
                            </li>
                        ))}
                    </ul>
                </nav>
                <ScopeCard
                    key={scope.party_id ?? "everyone"}
                    scope={scope}
                    busy={busy}
                    offered={offered}
                    onAction={(action) => {
                        origins.current = { opener: document.activeElement, origin: null }
                        if (CONFIRMED.has(action)) setConfirm({ scope, action })
                        else questCommand(scope, action, null)
                    }}
                    onObjective={(objectiveId, status, expected) => {
                        lastQuest.current = null
                        origins.current = { opener: null, origin: null }
                        run(
                            {
                                op: "objective",
                                objectiveId,
                                new_status: status,
                                party_id: scope.party_id,
                                expected_status: expected,
                            },
                            `Objective ${statusLabel(status).toLowerCase()}`,
                        )
                    }}
                />
            </div>
            <ConfirmDialog
                open={confirm !== null}
                title={confirm === null ? "" : `${ACTION_LABEL[confirm.action]}?`}
                description="This is recorded as an event in the campaign history. A correction can undo it only while nothing has changed since."
                confirmLabel={confirm === null ? "Confirm" : ACTION_LABEL[confirm.action]}
                pending={busy}
                error={staleOrError}
                reason={{
                    label: "Note (only editors see it)",
                    required: false,
                    value: note,
                    onChange: setNote,
                }}
                onConfirm={() => {
                    if (confirm !== null) {
                        questCommand(confirm.scope, confirm.action, note.trim() === "" ? null : note.trim())
                    }
                }}
                onCancel={() => {
                    // A lost answer is not forgotten: progress is read once, and what it shows is said.
                    if (lostAnswer && lastQuest.current !== null) reconcile(lastQuest.current)
                    setConfirm(null)
                    setNote("")
                    mutation.reset()
                }}
            >
                {confirm === null ? null : (
                    <QuestFinishReview
                        scope={confirm.scope}
                        action={confirm.action}
                        outcomes={outcomes ?? null}
                        labels={optionLabels ?? NO_LABELS}
                    />
                )}
            </ConfirmDialog>
        </>
    )
}

function ScopeCard({
    scope,
    busy,
    offered,
    onAction,
    onObjective,
}: {
    scope: ScopeProgress
    busy: boolean
    // False while the quest is not published and active: the recorded statuses stay readable and
    // no move is offered.
    offered: boolean
    onAction: (action: QuestAction) => void
    onObjective: (objectiveId: string, status: string, expected: string | null) => void
}) {
    const who = scope.party_name ?? "Everyone"
    return (
        <article className="authoring-card" aria-label={`Progress for ${who}`}>
            <h3>
                {who}: <span>{statusLabel(scope.status)}</span>
            </h3>
            {offered && scope.all_required_complete && scope.status === "active" ? (
                <p className="authoring-note">
                    All required objectives are complete. Complete the quest when you are ready.
                </p>
            ) : null}
            {offered && scope.actions.length > 0 ? (
                <div className="authoring-actions">
                    {scope.actions.map((action) => (
                        <button
                            key={action}
                            type="button"
                            className="authoring-button"
                            disabled={busy}
                            aria-label={`${ACTION_LABEL[action]} for ${who}`}
                            onClick={() => onAction(action)}
                        >
                            {ACTION_LABEL[action]}
                        </button>
                    ))}
                </div>
            ) : null}
            {scope.objectives.length === 0 ? (
                <p>This quest has no objectives.</p>
            ) : (
                <ul className="op-list">
                    {scope.objectives.map((o) => (
                        <li key={o.quest_objective_id} className="quest-progress__objective">
                            <span>
                                {o.stage_name}: {o.name}
                                {o.requirement_level === "required" ? "" : " (optional)"} — {statusLabel(o.status)}
                            </span>
                            {offered && o.next_statuses.length > 0 ? (
                                <span className="quest-progress__moves">
                                    {o.next_statuses.map((status) => (
                                        <button
                                            key={status}
                                            type="button"
                                            className="authoring-button"
                                            disabled={busy}
                                            aria-label={`${OBJECTIVE_VERB[status] ?? status} ${o.name} for ${who}`}
                                            onClick={() => onObjective(o.quest_objective_id, status, o.status)}
                                        >
                                            {OBJECTIVE_VERB[status] ?? status}
                                        </button>
                                    ))}
                                </span>
                            ) : null}
                        </li>
                    ))}
                </ul>
            )}
        </article>
    )
}
