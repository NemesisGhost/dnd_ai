import { useRef } from "react"
import type { ReactNode } from "react"
import { runQuestCommand } from "../../api/questAuthoring"
import { useSession } from "../../context/SessionContext"
import { useAuthoringMutation } from "../../hooks/useAuthoringMutation"
import type { QuestReceipt } from "../../types/contentAuthoring"
import type { QuestCommand } from "../../types/questAuthoring"
import { useAnnounce } from "../authoring/announcer"
import { MutationStatusMessage, StaleWriteNotice } from "../authoring/feedback"

// What the server says for the quest commands a section can send, in words a person can act on.
export const QUEST_COMMAND_MESSAGE: Readonly<Record<string, string>> = {
    quest_has_progress: "This quest already has recorded progress, so its structure can no longer change.",
    objective_dependency_cycle: "That prerequisite would create a loop of objectives that wait on each other.",
    objective_dependency_invalid: "Choose two different objectives of this quest.",
    objective_dependency_exists: "That dependency already exists.",
    quest_participant_invalid: "That participant is not valid: choose a published character or an organization.",
    quest_participant_exists: "That participant already has that role in this quest.",
    quest_outcome_code_exists: "Another outcome of this quest already uses that code.",
    reward_knowledge_invalid: "A knowledge reward needs a valid knowledge item, and other rewards must not name one.",
}

export interface QuestCommandHandle {
    // Sends one command. `after` runs once the command succeeded and the quest was read again, so a
    // form clears only what its own successful command consumed.
    send: (command: QuestCommand, message: string, after?: () => void) => void
    busy: boolean
    // The section's own failure notice, or null. It lives in the section that sent the command.
    notice: ReactNode
}

// One section's quest commands: its own pending and error state (so a failure appears where it was
// sent), one idempotent mutation at a time, and the authoritative read after every success. The
// scope key names the section, so two sections never share a status.
export function useQuestCommand({
    campaignId,
    questId,
    scope,
    refetch,
}: {
    campaignId: string
    questId: string
    scope: string
    refetch: () => Promise<void>
}): QuestCommandHandle {
    const { reload } = useSession()
    const announce = useAnnounce()
    const pending = useRef<{ message: string; after: () => void } | null>(null)
    const mutation = useAuthoringMutation<QuestCommand, QuestReceipt>({
        scopeKey: `quest-${scope}:${questId}`,
        request: (command, ctx) => runQuestCommand(campaignId, questId, command, ctx),
        onSuccess: async () => {
            const done = pending.current
            pending.current = null
            await refetch()
            done?.after()
            if (done?.message) announce(done.message)
        },
    })
    const error = mutation.status.kind === "error" ? mutation.status.error : null
    const text = error?.code ? (QUEST_COMMAND_MESSAGE[error.code] ?? null) : null
    const notice =
        error === null ? null : error.kind === "stale" ? (
            <StaleWriteNotice
                onLoadLatest={() => {
                    mutation.reset()
                    void refetch()
                }}
            />
        ) : text !== null ? (
            <p role="alert">{text}</p>
        ) : (
            <MutationStatusMessage error={error} onRetry={mutation.retry} onCheckSession={reload} />
        )
    return {
        send: (command, message, after = () => {}) => {
            pending.current = { message, after }
            mutation.submit(command)
        },
        busy: mutation.status.kind === "pending",
        notice,
    }
}
