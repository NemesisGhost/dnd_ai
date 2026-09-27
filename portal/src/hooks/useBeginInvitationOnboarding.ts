import { useCallback, useEffect, useRef, useState } from "react"
import {
    beginInvitationOnboarding,
    InvitationOnboardingRequestError,
} from "../api/invitationOnboarding"
import type { BeginInvitationOnboardingResponse } from "../types/invitationOnboarding"

export type BeginInvitationOnboardingStatus =
    | { kind: "idle" }
    | { kind: "pending" }
    | { kind: "success"; result: BeginInvitationOnboardingResponse }
    | { kind: "unavailable" }
    | { kind: "denied" }
    | { kind: "rate_limited" }
    | { kind: "error" }

export interface UseBeginInvitationOnboardingResult {
    status: BeginInvitationOnboardingStatus
    submit: (invitationToken: string) => void
    reset: () => void
}

const idleStatus: BeginInvitationOnboardingStatus = { kind: "idle" }

interface PendingRequest {
    token: string
    requestId: number
}

// Begins a single-link onboarding session for `invitationToken`.
// `invitationToken` is a plain function argument only, never retained in
// this hook's own state after the request resolves -- see
// PHASE13E_REMAINING_IMPLEMENTATION_PLAN.md §6.2's "Token elimination."
//
// The actual `fetch` is fired from a `useEffect` keyed on `pending`, not
// from inside the `submit` callback itself. That pairing matters: React 18
// StrictMode double-invokes a component's *first* mount's effects (mount ->
// cleanup -> mount again) to surface un-cleaned-up side effects. When the
// request used to start inline in `submit` (itself called from a caller's
// own one-shot mount effect) while a *separate* effect owned the
// AbortController's unmount cleanup, the phantom StrictMode teardown
// aborted the one real request and nothing ever resubmitted it, leaving
// `status` stuck at "pending" forever (the "Checking the invitation link."
// hang). Driving the fetch from an effect keyed on `pending` means the
// controller that gets created and the cleanup that aborts it are always
// the same effect invocation, so a StrictMode replay creates-then-aborts-
// then-recreates a fresh, live request instead of leaking an aborted one.
export function useBeginInvitationOnboarding(): UseBeginInvitationOnboardingResult {
    const [status, setStatus] = useState<BeginInvitationOnboardingStatus>(idleStatus)
    const [pending, setPending] = useState<PendingRequest | null>(null)
    const nextRequestIdRef = useRef(0)

    const submit = useCallback(
        (invitationToken: string) => {
            if (status.kind === "pending") {
                return
            }
            nextRequestIdRef.current += 1
            setStatus({ kind: "pending" })
            setPending({ token: invitationToken, requestId: nextRequestIdRef.current })
        },
        [status],
    )

    useEffect(() => {
        if (pending === null) {
            return
        }

        const controller = new AbortController()

        void beginInvitationOnboarding(pending.token, controller.signal)
            .then((result) => {
                if (controller.signal.aborted) {
                    return
                }
                setStatus({ kind: "success", result })
            })
            .catch((cause: unknown) => {
                if (controller.signal.aborted) {
                    return
                }

                if (cause instanceof InvitationOnboardingRequestError) {
                    if (cause.status === 404) {
                        setStatus({ kind: "unavailable" })
                        return
                    }
                    if (cause.status === 403) {
                        setStatus({ kind: "denied" })
                        return
                    }
                    if (cause.status === 429) {
                        setStatus({ kind: "rate_limited" })
                        return
                    }
                }

                setStatus({ kind: "error" })
            })

        return () => {
            controller.abort()
        }
    }, [pending])

    const reset = useCallback(() => {
        setStatus(idleStatus)
        setPending(null)
    }, [])

    return { status, submit, reset }
}
