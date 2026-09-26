import { useCallback, useEffect, useState } from "react"
import {
    fetchInvitationOnboardingStatus,
    InvitationOnboardingRequestError,
} from "../api/invitationOnboarding"
import type { InvitationOnboardingStatus } from "../types/invitationOnboarding"

export type InvitationOnboardingStatusState =
    | { status: "loading" }
    | { status: "success"; data: InvitationOnboardingStatus }
    | { status: "unavailable" }
    | { status: "error"; error: unknown }

export interface UseInvitationOnboardingStatusResult {
    state: InvitationOnboardingStatusState
    retry: () => void
}

interface Snapshot {
    requestVersion: number
    state: InvitationOnboardingStatusState
}

const initialState: InvitationOnboardingStatusState = { status: "loading" }

// Reads the current onboarding session's status from the onboarding
// cookie the browser already sends -- no token or session id is ever
// passed explicitly. Used to resume after a refresh (a consumed/expired
// session resolves to "unavailable", rendered as a calm terminal state by
// the page, never an error with a retry button -- see R-2 of
// PHASE13E_REMAINING_IMPLEMENTATION_PLAN.md §7.3).
export function useInvitationOnboardingStatus(): UseInvitationOnboardingStatusResult {
    const [requestVersion, setRequestVersion] = useState(0)
    const [snapshot, setSnapshot] = useState<Snapshot>(() => ({
        requestVersion: 0,
        state: initialState,
    }))

    const retry = useCallback(() => {
        setRequestVersion((currentVersion) => currentVersion + 1)
    }, [])

    const state = snapshot.requestVersion === requestVersion ? snapshot.state : initialState

    useEffect(() => {
        const controller = new AbortController()

        void fetchInvitationOnboardingStatus(controller.signal)
            .then((data) => {
                if (controller.signal.aborted) {
                    return
                }
                setSnapshot({ requestVersion, state: { status: "success", data } })
            })
            .catch((error: unknown) => {
                if (controller.signal.aborted) {
                    return
                }
                if (error instanceof DOMException && error.name === "AbortError") {
                    return
                }
                if (error instanceof InvitationOnboardingRequestError && error.status === 404) {
                    setSnapshot({ requestVersion, state: { status: "unavailable" } })
                    return
                }
                setSnapshot({ requestVersion, state: { status: "error", error } })
            })

        return () => {
            controller.abort()
        }
    }, [requestVersion])

    return { state, retry }
}
