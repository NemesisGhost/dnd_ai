import { useCallback, useEffect, useRef, useState } from "react"
import { useSession } from "../context/SessionContext"
import { classifyApiError } from "../types/apiError"
import type { AuthoringError } from "../types/apiError"

export type AuthoringMutationStatus =
    | { kind: "idle" }
    | { kind: "pending" }
    // The server confirmed the write and the follow-up refresh worked.
    | { kind: "success" }
    // The server confirmed the write, but re-reading what it changed failed. Nothing failed to
    // save: the caller shows what is stale and offers a read-only retry, never the write again.
    | { kind: "confirmed"; refresh: "failed" }
    // The request did not succeed. A `network` or `server` error may not mean the write did not
    // happen: `retry` repeats the same request under the same key, which is safe either way.
    | { kind: "error"; error: AuthoringError }

export interface MutationRequestContext {
    csrfToken: string
    idempotencyKey: string
    signal: AbortSignal
}

// What a follow-up read did. "failed" is the only value that matters to the mutation: the write is
// still confirmed, but its refresh is reported as failed. Matches `RefetchOutcome`.
export type RefreshOutcome = "ok" | "failed" | "superseded"

export interface UseAuthoringMutationOptions<TBody, TResult> {
    // Identifies what this mutation targets (a record id, a route). Changing
    // it aborts any in-flight request, discards its late response, and resets
    // the status, so a result can never be shown under the wrong record.
    scopeKey: string
    request: (body: TBody, context: MutationRequestContext) => Promise<TResult>
    // Runs once the server has confirmed the write, before the status becomes "success". Callers
    // refetch authoritatively and navigate here. Return the refetch outcome (or throw) to report
    // that the follow-up failed: the write is still confirmed and is never repeated for it.
    onSuccess?: (result: TResult) => void | RefreshOutcome | Promise<void | RefreshOutcome>
}

export interface UseAuthoringMutationResult<TBody, TResult> {
    status: AuthoringMutationStatus
    // The server's receipt for the last confirmed write in this scope (its new row version, for
    // one), until the scope changes or `reset` is called.
    receipt: TResult | null
    submit: (body: TBody) => void
    // Repeats the last unconfirmed request exactly (same body, same request, same key). Does
    // nothing once a write is confirmed, so it can never repeat a confirmed write.
    retry: () => void
    reset: () => void
}

interface Snapshot<TResult> {
    scopeKey: string
    status: AuthoringMutationStatus
    receipt: TResult | null
}

interface Reservation {
    scopeKey: string
    fingerprint: string
    key: string
}

interface LastAttempt<TBody, TResult> {
    body: TBody
    scopeKey: string
    // The request as it was when the user submitted, so a retry sends the same payload even if
    // the component has since seen a newer row version.
    request: UseAuthoringMutationOptions<TBody, TResult>["request"]
}

const IDLE: AuthoringMutationStatus = { kind: "idle" }

// The one mutation hook for every Phase 14 write. It:
//   - reuses the Idempotency-Key while the serialized body and scope are
//     unchanged (so Retry after a lost response replays instead of duplicating)
//     and rotates it when either changes (edited input is a new request);
//   - retries with the request exactly as first submitted;
//   - ignores a second submit while pending;
//   - aborts on unmount or scope change and ignores late responses;
//   - on a 401 reloads the session instead of showing an error;
//   - never optimistically assumes success, and keeps three outcomes apart: the write was not
//     confirmed ("error"), it was confirmed and the refresh worked ("success"), or it was
//     confirmed and the refresh failed ("confirmed").
export function useAuthoringMutation<TBody, TResult>({
    scopeKey,
    request,
    onSuccess,
}: UseAuthoringMutationOptions<TBody, TResult>): UseAuthoringMutationResult<TBody, TResult> {
    const { state: sessionState, reload } = useSession()
    const [snapshot, setSnapshot] = useState<Snapshot<TResult>>({ scopeKey, status: IDLE, receipt: null })
    const controllerRef = useRef<AbortController | null>(null)
    const reservationRef = useRef<Reservation | null>(null)
    const lastRef = useRef<LastAttempt<TBody, TResult> | null>(null)

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

    const current = snapshot.scopeKey === scopeKey
    const status = current ? snapshot.status : IDLE
    const receipt = current ? snapshot.receipt : null

    const start = useCallback(
        (body: TBody, send: LastAttempt<TBody, TResult>["request"]) => {
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
            lastRef.current = { body, scopeKey: requestScope, request: send }

            const controller = new AbortController()
            controllerRef.current = controller
            setSnapshot({ scopeKey: requestScope, status: { kind: "pending" }, receipt: null })

            void (async () => {
                let result: TResult
                try {
                    result = await send(body, {
                        csrfToken: sessionState.bootstrap.csrf_token,
                        idempotencyKey: key,
                        signal: controller.signal,
                    })
                } catch (cause) {
                    if (controller.signal.aborted) {
                        return
                    }
                    const error = classifyApiError(cause)
                    if (error.kind === "expired") {
                        setSnapshot({ scopeKey: requestScope, status: IDLE, receipt: null })
                        reload()
                        return
                    }
                    setSnapshot({ scopeKey: requestScope, status: { kind: "error", error }, receipt: null })
                    return
                }
                if (controller.signal.aborted) {
                    return
                }
                // Confirmed: the key and the body are spent, so nothing here can repeat the write.
                reservationRef.current = null
                lastRef.current = null
                let refresh: "ok" | "failed" = "ok"
                try {
                    if ((await onSuccessRef.current?.(result)) === "failed") {
                        refresh = "failed"
                    }
                } catch {
                    refresh = "failed"
                }
                if (controller.signal.aborted) {
                    return
                }
                setSnapshot({
                    scopeKey: requestScope,
                    status: refresh === "ok" ? { kind: "success" } : { kind: "confirmed", refresh: "failed" },
                    receipt: result,
                })
            })()
        },
        [status.kind, sessionState, scopeKey, reload],
    )

    const submit = useCallback((body: TBody) => start(body, requestRef.current), [start])

    const retry = useCallback(() => {
        const last = lastRef.current
        if (last !== null && last.scopeKey === scopeKey) {
            start(last.body, last.request)
        }
    }, [start, scopeKey])

    const reset = useCallback(() => {
        setSnapshot({ scopeKey, status: IDLE, receipt: null })
    }, [scopeKey])

    return { status, receipt, submit, retry, reset }
}
