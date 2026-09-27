import { useEffect, useState } from "react"
import { AuditHistoryRequestError, fetchAuditActors } from "../api/auditHistory"
import { useSession } from "../context/SessionContext"
import type { AuditActor } from "../types/auditHistory"

export type AuditActorsState =
    | { status: "loading" }
    | { status: "success"; actors: AuditActor[] }
    | { status: "unavailable" }
    | { status: "error" }

export interface UseAuditActorsResult {
    state: AuditActorsState
}

interface Snapshot {
    campaignId: string
    state: AuditActorsState
}

const initialState: AuditActorsState = { status: "loading" }

// Audit-actor-contract fix: the actor-select filter's option list, fetched
// independently of the main audit-history page/list (`useAuditHistory`)
// and of the retired `access-overview` dependency this replaces. A
// campaign change never shows the previous campaign's actor options, even
// briefly — mirrors `useAccessOverview`'s own campaign-mismatch guard.
// Deliberately has no `retry` of its own: the actor filter is a secondary
// enhancement to the audit-history page, not its primary content, so a
// failed/unavailable fetch here simply means "the actor filter is not
// offered this time" (`AuditHistory`'s own `actors = []` default) rather
// than a retryable error state layered on top of the page.
export function useAuditActors(campaignId: string): UseAuditActorsResult {
    const { reload } = useSession()

    const [snapshot, setSnapshot] = useState<Snapshot>(() => ({
        campaignId,
        state: initialState,
    }))

    const state = snapshot.campaignId === campaignId ? snapshot.state : initialState

    useEffect(() => {
        const controller = new AbortController()

        void fetchAuditActors(campaignId, controller.signal)
            .then((actors) => {
                if (controller.signal.aborted) {
                    return
                }
                setSnapshot({ campaignId, state: { status: "success", actors } })
            })
            .catch((error: unknown) => {
                if (controller.signal.aborted) {
                    return
                }
                if (error instanceof DOMException && error.name === "AbortError") {
                    return
                }
                if (error instanceof AuditHistoryRequestError && error.status === 401) {
                    // A stale authorization: drop any retained state before
                    // reloading the session rather than leaving a now-
                    // untrustworthy actor list visible.
                    setSnapshot({ campaignId, state: initialState })
                    void reload()
                    return
                }
                if (
                    error instanceof AuditHistoryRequestError &&
                    (error.status === 403 || error.status === 404)
                ) {
                    setSnapshot({ campaignId, state: { status: "unavailable" } })
                    return
                }
                setSnapshot({ campaignId, state: { status: "error" } })
            })

        return () => {
            controller.abort()
        }
    }, [campaignId, reload])

    return { state }
}
