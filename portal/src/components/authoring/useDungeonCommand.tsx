import { useContext, useEffect, useRef, useState } from "react"
import type { ReactNode } from "react"
import { runDungeonCommand } from "../../api/dungeonAuthoring"
import { useSession } from "../../context/SessionContext"
import { useAuthoringMutation } from "../../hooks/useAuthoringMutation"
import type { RefreshOutcome } from "../../hooks/useAuthoringMutation"
import { useConfirmedRefresh } from "../../hooks/useConfirmedRefresh"
import type { DungeonCommand } from "../../types/dungeonAuthoring"
import { DUNGEON_CODE_MESSAGE } from "../../utils/dungeonForm"
import { useAnnounce } from "./announcer"
import { MutationStatusMessage, StaleWriteNotice } from "./feedback"
import { PermissionLossContext, isWorldAuthorityLoss } from "./permissionLoss"

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
    // "Saved, but the latest data could not be loaded", while a confirmed command has not been read back.
    // It is the section's to render, outside any form: the form that sent the command closes on success.
    savedNotice: ReactNode
    // Forgets a failure, for when the form it belonged to is opened again or closed.
    clear: () => void
}

export function useDungeonCommand({
    campaignId,
    dungeonId,
    areaId,
    scope,
    refetch,
    pageStale = false,
}: {
    campaignId: string
    dungeonId: string
    areaId: string | null
    scope: string
    // Reads the record again, and whatever depends on its version (the lifecycle, the revisions). Its
    // outcome says whether everything the command changed was read back.
    refetch: () => Promise<RefreshOutcome>
    // The section's own latest read failed and it shows the last that loaded: the version every
    // command names may be behind, so commands wait for the read.
    pageStale?: boolean
}): DungeonCommandHandle {
    const { reload } = useSession()
    const announce = useAnnounce()
    const pending = useRef<{ message: string; after: () => void } | null>(null)
    // What the last confirmed command said, for the notice if its read-back did not complete.
    const [saved, setSaved] = useState<string | null>(null)
    const mutation = useAuthoringMutation<DungeonCommand, unknown>({
        scopeKey: `dungeon-${scope}:${areaId ?? dungeonId}`,
        request: (command, ctx) => runDungeonCommand(campaignId, dungeonId, areaId, command, ctx),
        onSuccess: async () => {
            const done = pending.current
            pending.current = null
            done?.after()
            setSaved(done?.message ?? null)
            const outcome = await refetch()
            // A confirmed command whose read-back failed is reported by the notice below, not as done.
            if (outcome === "ok" && done?.message) announce(done.message)
            return outcome
        },
    })
    const refreshed = useConfirmedRefresh({
        status: mutation.status,
        reset: mutation.reset,
        what: "dungeon",
        message: saved,
        read: refetch,
        pageStale,
    })
    const error = mutation.status.kind === "error" ? mutation.status.error : null
    // A refusal for lack of the world authority is a confirmed loss, not a failure to retry: tell the
    // workspace, which withdraws the private views and controls and keeps only the unsent input.
    const loss = useContext(PermissionLossContext)
    const lost = isWorldAuthorityLoss(error)
    useEffect(() => {
        if (lost) loss?.reportLoss()
    }, [lost, loss])
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
        // Held while the version every command names is behind a command that was just confirmed.
        busy: mutation.status.kind === "pending" || refreshed.held || pageStale,
        notice,
        savedNotice: refreshed.notice,
        // Forgets a failure only. A command that was confirmed and not yet read back is not a failure
        // to forget: opening or closing a form must not lift the hold on the version it named.
        clear: () => {
            if (mutation.status.kind !== "confirmed") mutation.reset()
        },
    }
}
