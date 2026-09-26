import { useCallback, useEffect, useState } from "react"
import { EffectiveAccessRequestError, fetchMemberEffectiveAccess } from "../api/effectiveAccess"
import { useSession } from "../context/SessionContext"
import type { MemberEffectiveAccess } from "../types/effectiveAccess"

export type EffectiveAccessState =
    | { status: "loading" }
    | { status: "success"; access: MemberEffectiveAccess }
    | { status: "unavailable" }
    | { status: "error"; error: unknown }

export interface UseEffectiveAccessResult {
    state: EffectiveAccessState
    retry: () => void
}

interface EffectiveAccessSnapshot {
    campaignId: string
    campaignMembershipId: string
    requestVersion: number
    state: EffectiveAccessState
}

const initialState: EffectiveAccessState = { status: "loading" }

// Mirrors useAccessOverview's own "never keep a prior request's result
// visible as current" snapshot pattern: a mismatch between the last-seen
// request and the current (campaignId, campaignMembershipId) pair falls
// back to initialState below. The caller is expected to mount this hook
// only while its own effective-access disclosure is open (see
// EffectiveAccessPanel) — unmounting is what actually clears the member's
// access shape from memory once the panel closes or a different member is
// selected, per this checkpoint's own security invariant; this hook's own
// per-request-identity check exists only to keep a still-mounted instance
// from momentarily showing a stale result if its own props ever changed
// without a full remount.
export function useEffectiveAccess(
    campaignId: string,
    campaignMembershipId: string,
): UseEffectiveAccessResult {
    const { reload } = useSession()

    const [requestVersion, setRequestVersion] = useState(0)

    const [snapshot, setSnapshot] = useState<EffectiveAccessSnapshot>(() => ({
        campaignId,
        campaignMembershipId,
        requestVersion: 0,
        state: initialState,
    }))

    const retry = useCallback(() => {
        setRequestVersion((currentVersion) => currentVersion + 1)
    }, [])

    const snapshotMatchesRequest =
        snapshot.campaignId === campaignId &&
        snapshot.campaignMembershipId === campaignMembershipId &&
        snapshot.requestVersion === requestVersion

    const state = snapshotMatchesRequest ? snapshot.state : initialState

    useEffect(() => {
        const controller = new AbortController()

        void fetchMemberEffectiveAccess(campaignId, campaignMembershipId, controller.signal)
            .then((access) => {
                if (controller.signal.aborted) {
                    return
                }

                setSnapshot({
                    campaignId,
                    campaignMembershipId,
                    requestVersion,
                    state: { status: "success", access },
                })
            })
            .catch((error: unknown) => {
                if (controller.signal.aborted) {
                    return
                }

                if (error instanceof DOMException && error.name === "AbortError") {
                    return
                }

                if (error instanceof EffectiveAccessRequestError && error.status === 401) {
                    void reload()
                    return
                }

                if (
                    error instanceof EffectiveAccessRequestError &&
                    (error.status === 403 || error.status === 404)
                ) {
                    setSnapshot({
                        campaignId,
                        campaignMembershipId,
                        requestVersion,
                        state: { status: "unavailable" },
                    })
                    return
                }

                setSnapshot({
                    campaignId,
                    campaignMembershipId,
                    requestVersion,
                    state: { status: "error", error },
                })
            })

        return () => {
            controller.abort()
        }
    }, [campaignId, campaignMembershipId, reload, requestVersion])

    return { state, retry }
}
