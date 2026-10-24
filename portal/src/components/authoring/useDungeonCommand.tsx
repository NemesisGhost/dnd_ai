import { useRef } from "react"
import type { ReactNode } from "react"
import { runDungeonCommand } from "../../api/dungeonAuthoring"
import { useSession } from "../../context/SessionContext"
import { useAuthoringMutation } from "../../hooks/useAuthoringMutation"
import type { DungeonCommand } from "../../types/dungeonAuthoring"
import { DUNGEON_CODE_MESSAGE } from "../../utils/dungeonForm"
import { useAnnounce } from "./announcer"
import { MutationStatusMessage, StaleWriteNotice } from "./feedback"

// What one section's dungeon commands need: its own pending and error state (so a failure appears
// where it was sent), one idempotent mutation at a time, and the authoritative read after every
// success. Every structural command names the dungeon's version (decision D-31); the state command
// names the event it was read at.
export interface DungeonCommandHandle {
    // Sends one command. `after` runs once the command succeeded, before the page reads the record
    // again, so a form closes or clears only for a command the server accepted.
    send: (command: DungeonCommand, message: string, after?: () => void) => void
    busy: boolean
    // The section's own failure notice, or null.
    notice: ReactNode
    // Forgets a failure, for when the form it belonged to is opened again or closed.
    clear: () => void
}

export function useDungeonCommand({
    campaignId,
    dungeonId,
    areaId,
    scope,
    refetch,
}: {
    campaignId: string
    dungeonId: string
    areaId: string | null
    scope: string
    // Reads the record again, and whatever depends on its version (the lifecycle, the revisions).
    refetch: () => Promise<unknown>
}): DungeonCommandHandle {
    const { reload } = useSession()
    const announce = useAnnounce()
    const pending = useRef<{ message: string; after: () => void } | null>(null)
    const mutation = useAuthoringMutation<DungeonCommand, unknown>({
        scopeKey: `dungeon-${scope}:${areaId ?? dungeonId}`,
        request: (command, ctx) => runDungeonCommand(campaignId, dungeonId, areaId, command, ctx),
        onSuccess: async () => {
            const done = pending.current
            pending.current = null
            done?.after()
            await refetch()
            if (done?.message) announce(done.message)
        },
    })
    const error = mutation.status.kind === "error" ? mutation.status.error : null
    const text = error?.code ? (DUNGEON_CODE_MESSAGE[error.code] ?? null) : null
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
        clear: mutation.reset,
    }
}
