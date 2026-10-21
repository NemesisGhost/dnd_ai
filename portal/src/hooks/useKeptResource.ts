import { useState } from "react"
import type { AuthoringResourceState } from "./useAuthoringResource"

// The last data a read returned, kept through a recoverable failure (a network or server error) and
// dropped on a denied or missing answer.
export function useKept<T>(state: AuthoringResourceState<T>): T | null {
    const [kept, setKept] = useState<T | null>(null)
    if (state.kind === "ready" && kept !== state.data) setKept(state.data)
    if ((state.kind === "denied" || state.kind === "unavailable") && kept !== null) setKept(null)
    return state.kind === "ready" ? state.data : state.kind === "error" ? kept : null
}
