import { useState } from "react"
import type { AuthoringResourceState } from "./useAuthoringResource"

// The last data a read returned, kept through a recoverable failure (a network or server error) and
// dropped on a denied or missing answer. `scope` names what is being read (the request path): when it
// changes, what was kept is dropped, so a failure on the next record never shows the previous one.
export function useKept<T>(state: AuthoringResourceState<T>, scope: string = ""): T | null {
    const [held, setHeld] = useState<{ scope: string; data: T | null }>({ scope, data: null })
    const kept = held.scope === scope ? held.data : null
    if (held.scope !== scope) setHeld({ scope, data: null })
    else if (state.kind === "ready" && kept !== state.data) setHeld({ scope, data: state.data })
    else if ((state.kind === "denied" || state.kind === "unavailable") && kept !== null)
        setHeld({ scope, data: null })
    return state.kind === "ready" ? state.data : state.kind === "error" ? kept : null
}
