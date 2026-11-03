import { useCallback, useContext, useEffect, useLayoutEffect, useRef, useState } from "react"
import { apiRequest } from "../api/http"
import { useSession } from "../context/SessionContext"
import { BreadcrumbLabelContext } from "../navigation/BreadcrumbLabelContext"
import type { LabelRegistry } from "../navigation/labelRegistry"
import { classifyApiError } from "../types/apiError"

export type AuthoringResourceState<T> =
    | { kind: "loading" }
    | { kind: "ready"; data: T; refreshing: boolean }
    | { kind: "unavailable" }
    | { kind: "denied" }
    | { kind: "error"; retryable: boolean }

// What a refetch did: "ok" the record was read and applied; "failed" it was not (denied, gone,
// signed out or a recoverable error: `state` says which); "superseded" a newer read or a change of
// record replaced it, so this one says nothing about the record.
export type RefetchOutcome = "ok" | "failed" | "superseded"

export interface UseAuthoringResourceResult<T> {
    state: AuthoringResourceState<T>
    // Re-fetches the authoritative record. Resolves once the response has been
    // applied (or failed), so a caller can sequence an announcement after the
    // refetch that proves a write, and tell a write whose re-read failed from one that
    // completed. It never rejects. The previous data stays on screen, marked
    // `refreshing`, until the new data arrives.
    refetch: () => Promise<RefetchOutcome>
    // Whether the latest `refetch` that completed read the record. `refetch` never rejects, so a
    // caller that must tell a successful write whose re-read failed reads this once it resolves.
    refreshOk: { readonly current: boolean }
    // The breadcrumb-label authority generation under which the read behind `state` STARTED, or null
    // (loading, no label registry, or a read begun without one). Only breadcrumb label publication reads
    // it (navigation/BreadcrumbLabelContext). Callers that ignore it are unaffected.
    authority: LabelRegistry | null
}

interface Snapshot<T> {
    path: string | null
    state: AuthoringResourceState<T>
    authority: LabelRegistry | null
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

// Retries the reads of a page that failed recoverably, and only those: a read that answered (even
// with a refusal) is left as it is, so a good answer is never replaced by a second attempt.
export function retryFailedReads(
    ...reads: readonly { state: { kind: string }; refetch: () => Promise<RefetchOutcome> }[]
): Promise<unknown> {
    return Promise.all(reads.filter((read) => read.state.kind === "error").map((read) => read.refetch()))
}

// A GET loader for authoring read models. State is keyed by the request path,
// so a record loaded for one URL is never shown under another while the next
// one loads. A 404 is "unavailable" (not found or not accessible — the server
// deliberately does not say which), a 403 is "denied", and a 401 reloads the
// session so the boundary redirects to sign-in.
export function useAuthoringResource<T>(
    path: string | null,
): UseAuthoringResourceResult<T> {
    const { reload } = useSession()
    const [snapshot, setSnapshot] = useState<Snapshot<T>>({ path, state: LOADING, authority: null })
    const refetchController = useRef<AbortController | null>(null)
    const loadController = useRef<AbortController | null>(null)
    // The label authority now in force, read when a request starts. A ref, not a dependency: an authority
    // change must not start a read.
    const registry = useContext(BreadcrumbLabelContext)
    const currentAuthority = useRef(registry)
    useLayoutEffect(() => {
        currentAuthority.current = registry
    })
    const refreshOk = useRef(true)

    const apply = useCallback(
        (forPath: string, outcome: Outcome<T>, authority: LabelRegistry | null) => {
            if (outcome.kind === "expired") {
                reload()
                return
            }
            setSnapshot({
                path: forPath,
                authority,
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
        loadController.current = controller
        const authority = currentAuthority.current
        void load<T>(path, controller.signal).then((outcome) => {
            if (!controller.signal.aborted) {
                apply(path, outcome, authority)
            }
        })
        return () => {
            controller.abort()
            refetchController.current?.abort()
        }
    }, [path, apply])

    const refetch = useCallback(async (): Promise<RefetchOutcome> => {
        if (path === null) {
            return "superseded"
        }
        refetchController.current?.abort()
        // A read that starts later owns the record: the first load, if still in flight, is superseded
        // and can no longer be applied over it.
        loadController.current?.abort()
        const controller = new AbortController()
        refetchController.current = controller
        const authority = currentAuthority.current
        setSnapshot((current) =>
            current.path === path && current.state.kind === "ready"
                ? { ...current, path, state: { ...current.state, refreshing: true } }
                : current,
        )
        const outcome = await load<T>(path, controller.signal)
        if (controller.signal.aborted) {
            return "superseded"
        }
        refreshOk.current = outcome.kind === "ready"
        apply(path, outcome, authority)
        return outcome.kind === "ready" ? "ok" : "failed"
    }, [path, apply])

    const state = snapshot.path === path ? snapshot.state : LOADING
    return { state, refetch, refreshOk, authority: snapshot.path === path ? snapshot.authority : null }
}
