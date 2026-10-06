import { useState } from "react"
import { Link, useParams } from "react-router"
import { questProgressPath, runQuestRuntimeCommand } from "../api/questRuntime"
import { ConfirmDialog } from "../components/authoring/ConfirmDialog"
import { useAnnounce } from "../components/authoring/announcer"
import { MutationStatusMessage, StaleWriteNotice } from "../components/authoring/feedback"
import { useSession } from "../context/SessionContext"
import { useAuthoringMutation } from "../hooks/useAuthoringMutation"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import { useCampaignCapability } from "../hooks/useCampaignCapability"
import { usePageArrival } from "../hooks/usePageArrival"
import type {
    QuestAction,
    QuestProgress,
    RuntimeCommand,
    RuntimeReceipt,
    ScopeProgress,
} from "../types/questRuntime"
import "../components/authoring/authoring.css"

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

// /app/:campaignId/quests/:questId/progress — the GM runs one quest. Under D-16 only these
// explicit commands change progress; nothing completes a quest by itself.
export function QuestProgressPage() {
    const { campaignId = "", questId = "" } = useParams()
    const { reload } = useSession()
    const announce = useAnnounce()
    const canEdit = useCampaignCapability(campaignId, "canon.edit")
    const { state, refetch } = useAuthoringResource<QuestProgress>(
        questProgressPath(campaignId, questId),
    )
    const headingRef = usePageArrival(state.kind === "ready")
    const [done, setDone] = useState<string | null>(null)
    const [confirm, setConfirm] = useState<{ scope: ScopeProgress; action: QuestAction } | null>(null)
    const [note, setNote] = useState("")
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

    return (
        <section className="authoring-page" aria-labelledby="quest-progress-heading">
            <p className="authoring-page__breadcrumb">
                <Link to={`/app/${encodeURIComponent(campaignId)}/quests`}>Quests</Link>
                {state.kind === "ready" ? <> / {state.data.name}</> : null}
            </p>
            <h1 id="quest-progress-heading" ref={headingRef} tabIndex={-1}>
                Run quest
            </h1>
            {!canEdit ? (
                <p role="alert">You do not have permission to run quests in this campaign.</p>
            ) : state.kind === "loading" ? (
                <p role="status">Loading progress…</p>
            ) : state.kind !== "ready" ? (
                <p role="alert">This quest does not exist, or you do not have access to it.</p>
            ) : (
                <>
                    <p>
                        <Link
                            to={`/app/${encodeURIComponent(campaignId)}/quests/${encodeURIComponent(questId)}/edit`}
                        >
                            Edit the quest definition
                        </Link>
                    </p>
                    {!state.data.published ? (
                        <p className="authoring-note">
                            This quest is not published, so it cannot be run until it is.
                        </p>
                    ) : null}
                    {staleOrError}
                    {state.data.scopes.map((scope) => (
                        <ScopeCard
                            key={scope.party_id ?? "everyone"}
                            scope={scope}
                            busy={busy}
                            onAction={(action) =>
                                CONFIRMED.has(action)
                                    ? setConfirm({ scope, action })
                                    : questCommand(scope, action, null)
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
                            if (confirm !== null)
                                questCommand(confirm.scope, confirm.action, note.trim() === "" ? null : note.trim())
                        }}
                        onCancel={() => {
                            setConfirm(null)
                            setNote("")
                            mutation.reset()
                        }}
                    />
                </>
            )}
        </section>
    )
}

function ScopeCard({
    scope,
    busy,
    onAction,
    onObjective,
}: {
    scope: ScopeProgress
    busy: boolean
    onAction: (action: QuestAction) => void
    onObjective: (objectiveId: string, status: string, expected: string | null) => void
}) {
    const who = scope.party_name ?? "Everyone"
    return (
        <article className="authoring-card" aria-label={`Progress for ${who}`}>
            <h2>
                {who}: <span>{statusLabel(scope.status)}</span>
            </h2>
            {scope.all_required_complete && scope.status === "active" ? (
                <p className="authoring-note">
                    All required objectives are complete. Complete the quest when you are ready.
                </p>
            ) : null}
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
            {scope.objectives.length === 0 ? (
                <p>This quest has no objectives.</p>
            ) : (
                <ul className="authoring-choice-list">
                    {scope.objectives.map((o) => (
                        <li key={o.quest_objective_id}>
                            {o.stage_name}: {o.name}
                            {o.requirement_level === "required" ? "" : " (optional)"} —{" "}
                            {statusLabel(o.status)}{" "}
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
                        </li>
                    ))}
                </ul>
            )}
        </article>
    )
}
