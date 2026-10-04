import { useCallback, useEffect, useRef, useState } from "react"
import { useSession } from "../context/SessionContext"
import { classifyApiError } from "../types/apiError"
import type { AuthoringError } from "../types/apiError"

export type AuthoringMutationStatus =
    | { kind: "idle" }
    | { kind: "pending" }
    | { kind: "success" }
    | { kind: "error"; error: AuthoringError }

export interface MutationRequestContext {
    csrfToken: string
    idempotencyKey: string
    signal: AbortSignal
}

export interface UseAuthoringMutationOptions<TBody, TResult> {
    // Identifies what this mutation targets (a record id, a route). Changing
    // it aborts any in-flight request, discards its late response, and resets
    // the status, so a result can never be shown under the wrong record.
    scopeKey: string
    request: (body: TBody, context: MutationRequestContext) => Promise<TResult>
    // Runs after a successful response and before the status becomes
    // "success". Callers refetch authoritatively and navigate here.
    onSuccess?: (result: TResult) => void | Promise<void>
}

export interface UseAuthoringMutationResult<TBody> {
    status: AuthoringMutationStatus
    submit: (body: TBody) => void
    // Resubmits the last body with the same idempotency key.
    retry: () => void
    reset: () => void
}

interface Snapshot {
    scopeKey: string
    status: AuthoringMutationStatus
}

interface Reservation {
    scopeKey: string
    fingerprint: string
    key: string
}

const IDLE: AuthoringMutationStatus = { kind: "idle" }

// The one mutation hook for every Phase 14 write. It:
//   - reuses the Idempotency-Key while the serialized body and scope are
//     unchanged (so Retry after a lost response replays instead of duplicating)
//     and rotates it when either changes;
//   - ignores a second submit while pending;
//   - aborts on unmount or scope change and ignores late responses;
//   - on a 401 reloads the session instead of showing an error;
//   - never optimistically assumes success: the status is "success" only after
//     the server confirmed AND onSuccess (the authoritative refetch) finished.
export function useAuthoringMutation<TBody, TResult>({
    scopeKey,
    request,
    onSuccess,
}: UseAuthoringMutationOptions<TBody, TResult>): UseAuthoringMutationResult<TBody> {
    const { state: sessionState, reload } = useSession()
    const [snapshot, setSnapshot] = useState<Snapshot>({ scopeKey, status: IDLE })
    const controllerRef = useRef<AbortController | null>(null)
    const reservationRef = useRef<Reservation | null>(null)
    const lastBodyRef = useRef<{ body: TBody; scopeKey: string } | null>(null)

    // The latest callbacks, read only inside event handlers/promises.
    const requestRef = useRef(request)
    const onSuccessRef = useRef(onSuccess)
    useEffect(() => {
        requestRef.current = request
        onSuccessRef.current = onSuccess
    })

    useEffect(() => {
        return () => {
            controllerRef.current?.abort()
        }
    }, [scopeKey])

    const status = snapshot.scopeKey === scopeKey ? snapshot.status : IDLE

    const run = useCallback(
        (body: TBody) => {
            if (status.kind === "pending" || sessionState.status !== "authenticated") {
                return
            }
            const requestScope = scopeKey
            const fingerprint = JSON.stringify(body)
            const reserved = reservationRef.current
            const key =
                reserved !== null &&
                reserved.scopeKey === requestScope &&
                reserved.fingerprint === fingerprint
                    ? reserved.key
                    : globalThis.crypto.randomUUID()
            reservationRef.current = { scopeKey: requestScope, fingerprint, key }
            lastBodyRef.current = { body, scopeKey: requestScope }

            const controller = new AbortController()
            controllerRef.current = controller
            setSnapshot({ scopeKey: requestScope, status: { kind: "pending" } })

            void (async () => {
                try {
                    const result = await requestRef.current(body, {
                        csrfToken: sessionState.bootstrap.csrf_token,
                        idempotencyKey: key,
                        signal: controller.signal,
                    })
                    if (controller.signal.aborted) {
                        return
                    }
                    await onSuccessRef.current?.(result)
                    if (controller.signal.aborted) {
                        return
                    }
                    reservationRef.current = null
                    setSnapshot({ scopeKey: requestScope, status: { kind: "success" } })
                } catch (cause) {
                    if (controller.signal.aborted) {
                        return
                    }
                    const error = classifyApiError(cause)
                    if (error.kind === "expired") {
                        setSnapshot({ scopeKey: requestScope, status: IDLE })
                        reload()
                        return
                    }
                    setSnapshot({ scopeKey: requestScope, status: { kind: "error", error } })
                }
            })()
        },
        [status.kind, sessionState, scopeKey, reload],
    )

    const retry = useCallback(() => {
        const last = lastBodyRef.current
        if (last !== null && last.scopeKey === scopeKey) {
            run(last.body)
        }
    }, [run, scopeKey])

    const reset = useCallback(() => {
        setSnapshot({ scopeKey, status: IDLE })
    }, [scopeKey])

    return { status, submit: run, retry, reset }
}
