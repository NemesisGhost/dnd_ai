import { createContext, useContext, useEffect } from "react"
import type { AuthoringError } from "../../types/apiError"
import { retainedChanges } from "../../utils/retainedChanges"
import type { RetainedChange } from "../../utils/retainedChanges"

// Losing the world role while a staged workspace (a dungeon, a dungeon area) is open. The server
// refuses a private-authoring command with 403 `world_authority_required`; that answer, and only
// that answer, is the confirmed loss. The workspace then discards what the server's private reads
// had loaded and withholds the controls built on them, and shows back, read-only, only what the
// person had typed and not sent (the same contract as the edit shell: utils/retainedChanges, and
// components/authoring/PermissionLost). The client decides nothing about who may do what: it reacts
// to the refusal and to the server's later answers.
export interface PermissionLossHandle {
    // A private-authoring command was refused for lack of the world authority.
    reportLoss: () => void
    // What one section or editor currently holds unsent, by source; an empty list clears it.
    retain: (source: string, changes: RetainedChange[]) => void
}

export const PermissionLossContext = createContext<PermissionLossHandle | null>(null)

export function isWorldAuthorityLoss(error: AuthoringError | null): boolean {
    return error !== null && error.kind === "denied" && error.code === "world_authority_required"
}

// Registers the unsent values of a form with the workspace, so they can be shown back if the right
// to send them is lost. A no-op outside a workspace that handles the loss. The values are held
// where the workspace can reach them after the section itself has been withdrawn.
export function useRetainedInput(source: string, prefix: string, changes: RetainedChange[]): void {
    const loss = useContext(PermissionLossContext)
    const key = JSON.stringify(changes)
    useEffect(() => {
        loss?.retain(
            source,
            (JSON.parse(key) as RetainedChange[]).map((c) => ({ ...c, label: `${prefix} · ${c.label}` })),
        )
    }, [loss, source, prefix, key])
}

// The fields of `current` that differ from `baseline`, for `useRetainedInput`.
export const changedFields = (baseline: object, current: object): RetainedChange[] =>
    retainedChanges(baseline, current, "")
