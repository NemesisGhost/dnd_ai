import { useEffect, useRef, useState } from "react"
import type { AuthoringResourceState } from "./useAuthoringResource"

// The last read that succeeded, for a panel that owns forms. A refresh that fails recoverably (a
// network or server error) keeps the panel mounted on it, so unsent input survives and the person
// can try again; a denied or unavailable answer, or a read that is loading again, discards it and
// fails closed.
export function useKeptData<T>(state: AuthoringResourceState<T>): T | null {
    const [kept, setKept] = useState<T | null>(null)
    if (state.kind === "ready" && kept !== state.data) setKept(state.data)
    if ((state.kind === "denied" || state.kind === "unavailable" || state.kind === "loading") && kept !== null) {
        setKept(null)
    }
    return state.kind === "ready" ? state.data : state.kind === "error" ? kept : null
}

// Reads a resource again when `token` changes (not on the first render), so a panel with its own read
// agrees with a change made elsewhere on the page without being remounted.
export function useRefetchOnChange(token: unknown, refetch: () => Promise<void>): void {
    const first = useRef(true)
    useEffect(() => {
        if (first.current) {
            first.current = false
            return
        }
        void refetch()
    }, [token, refetch])
}
