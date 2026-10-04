import { useCallback, useEffect, useRef, useState } from "react"
import { apiRequest } from "../api/http"
import { useSession } from "../context/SessionContext"
import { classifyApiError } from "../types/apiError"

export type AuthoringResourceState<T> =
    | { kind: "loading" }
    | { kind: "ready"; data: T; refreshing: boolean }
    | { kind: "unavailable" }
    | { kind: "denied" }
    | { kind: "error"; retryable: boolean }

export interface UseAuthoringResourceResult<T> {
    state: AuthoringResourceState<T>
    // Re-fetches the authoritative record. Resolves once the response has been
    // applied (or failed), so a caller can sequence an announcement after the
    // refetch that proves a write. The previous data stays on screen,
    // marked `refreshing`, until the new data arrives.
    refetch: () => Promise<void>
}

interface Snapshot<T> {
    path: string | null
    state: AuthoringResourceState<T>
}

type Outcome<T> =
    | { kind: "ready"; data: T }
    | { kind: "unavailable" }
    | { kind: "denied" }
    | { kind: "expired" }
    | { kind: "error"; retryable: boolean }

async function load<T>(path: string, signal: AbortSignal): Promise<Outcome<T>> {
    try {
        return { kind: "ready", data: await apiRequest<T>("GET", path, { signal }) }
    } catch (cause) {
        const error = classifyApiError(cause)
        if (error.kind === "unavailable") return { kind: "unavailable" }
        if (error.kind === "denied") return { kind: "denied" }
        if (error.kind === "expired") return { kind: "expired" }
        return { kind: "error", retryable: true }
    }
}

const LOADING = { kind: "loading" } as const

// A GET loader for authoring read models. State is keyed by the request path,
// so a record loaded for one URL is never shown under another while the next
// one loads. A 404 is "unavailable" (not found or not accessible — the server
// deliberately does not say which), a 403 is "denied", and a 401 reloads the
// session so the boundary redirects to sign-in.
export function useAuthoringResource<T>(
    path: string | null,
): UseAuthoringResourceResult<T> {
    const { reload } = useSession()
    const [snapshot, setSnapshot] = useState<Snapshot<T>>({ path, state: LOADING })
    const refetchController = useRef<AbortController | null>(null)

    const apply = useCallback(
        (forPath: string, outcome: Outcome<T>) => {
            if (outcome.kind === "expired") {
                reload()
                return
            }
            setSnapshot({
                path: forPath,
                state:
                    outcome.kind === "ready"
                        ? { kind: "ready", data: outcome.data, refreshing: false }
                        : outcome,
            })
        },
        [reload],
    )

    useEffect(() => {
        if (path === null) {
            return
        }
        const controller = new AbortController()
        void load<T>(path, controller.signal).then((outcome) => {
            if (!controller.signal.aborted) {
                apply(path, outcome)
            }
        })
        return () => {
            controller.abort()
            refetchController.current?.abort()
        }
    }, [path, apply])

    const refetch = useCallback(async () => {
        if (path === null) {
            return
        }
        refetchController.current?.abort()
        const controller = new AbortController()
        refetchController.current = controller
        setSnapshot((current) =>
            current.path === path && current.state.kind === "ready"
                ? { path, state: { ...current.state, refreshing: true } }
                : current,
        )
        const outcome = await load<T>(path, controller.signal)
        if (!controller.signal.aborted) {
            apply(path, outcome)
        }
    }, [path, apply])

    const state = snapshot.path === path ? snapshot.state : LOADING
    return { state, refetch }
}
