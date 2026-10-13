import { useEffect, useRef, useState } from "react"
import { questProgressPath, runQuestRuntimeCommand } from "../../api/questRuntime"
import { useSession } from "../../context/SessionContext"
import { useAuthoringMutation } from "../../hooks/useAuthoringMutation"
import { useAuthoringResource } from "../../hooks/useAuthoringResource"
import type { QuestAction, QuestProgress, RuntimeCommand, RuntimeReceipt, ScopeProgress } from "../../types/questRuntime"
import { useAnnounce } from "../authoring/announcer"
import { ConfirmDialog } from "../authoring/ConfirmDialog"
import { MutationStatusMessage, StaleWriteNotice } from "../authoring/feedback"
import { useUnsavedReport } from "./useUnsavedReport"
import type { ReportUnsaved } from "./useUnsavedReport"
import "../authoring/authoring.css"

const STATUS_LABEL: Readonly<Record<string, string>> = {
    unavailable: "Not available",
    available: "Available",
    active: "Active",
    suspended: "Suspended",
    completed: "Completed",
    failed: "Failed",
    abandoned: "Abandoned",
    hidden: "Hidden",
    skipped: "Skipped",
    superseded: "Replaced",
}

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

// Finishing a quest is a decision the GM confirms; the rest act at once.
const CONFIRMED: ReadonlySet<QuestAction> = new Set(["complete", "fail", "abandon"])

const statusLabel = (status: string | null): string =>
    status === null ? "Not started" : (STATUS_LABEL[status] ?? status)

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
}

// How far the campaign and each party have got, and the explicit moves the GM can make. This is
// timeline state under decision D-16: only these commands change it, and nothing completes a quest
// by itself. It is separate from the quest's publication and from the authored stages. Mounted
// only for editors, inside the Quest workspace.
export function QuestProgressPanel({ campaignId, questId, blockedText, refreshToken, onUnsaved }: Props) {
    const { reload } = useSession()
    const announce = useAnnounce()
    const { state, refetch } = useAuthoringResource<QuestProgress>(questProgressPath(campaignId, questId))
    const [done, setDone] = useState<string | null>(null)
    const [confirm, setConfirm] = useState<{ scope: ScopeProgress; action: QuestAction } | null>(null)
    const [note, setNote] = useState("")
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

    useUnsavedReport(onUnsaved, "progress", confirm !== null && note.trim() !== "" ? ["a note for the quest action"] : [])

    const mutation = useAuthoringMutation<RuntimeCommand, RuntimeReceipt>({
        scopeKey: `quest-runtime:${questId}`,
        request: (command, ctx) => runQuestRuntimeCommand(campaignId, questId, command, ctx),
        onSuccess: async () => {
            const message = done
            setDone(null)
            setConfirm(null)
            setNote("")
            await refetch()
            if (message !== null) announce(message)
        },
    })
    const error = mutation.status.kind === "error" ? mutation.status.error : null
    const busy = mutation.status.kind === "pending"
    const explained = error?.code ? (CODE_MESSAGE[error.code] ?? null) : null

    const run = (command: RuntimeCommand, message: string) => {
        setDone(message)
        mutation.submit(command)
    }
    const questCommand = (scope: ScopeProgress, action: QuestAction, text: string | null) =>
        run(
            { op: "quest", action, party_id: scope.party_id, expected_status: scope.status, note: text },
            `${ACTION_LABEL[action]}: done`,
        )

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
            {data.scopes.map((scope) => (
                <ScopeCard
                    key={scope.party_id ?? "everyone"}
                    scope={scope}
                    busy={busy}
                    offered={offered}
                    onAction={(action) =>
                        CONFIRMED.has(action) ? setConfirm({ scope, action }) : questCommand(scope, action, null)
                    }
                    onObjective={(objectiveId, status, expected) =>
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
                    }
                />
            ))}
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
                    setConfirm(null)
                    setNote("")
                    mutation.reset()
                }}
            />
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
                        <li key={o.quest_objective_id}>
                            {o.stage_name}: {o.name}
                            {o.requirement_level === "required" ? "" : " (optional)"} — {statusLabel(o.status)}{" "}
                            {offered
                                ? o.next_statuses.map((status) => (
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
                                  ))
                                : null}
                        </li>
                    ))}
                </ul>
            )}
        </article>
    )
}
