import { useCallback, useEffect, useRef, useState } from "react"
import type { ReactNode } from "react"
import { useAnnounce } from "../components/authoring/announcer"
import { SavedRefreshFailedNotice } from "../components/authoring/feedback"
import type { AuthoringMutationStatus, RefreshOutcome } from "./useAuthoringMutation"

export interface ConfirmedRefresh {
    // The write was confirmed and what is shown has not been read since. A caller that sends a
    // version-checked write from the shown record holds it while this is true.
    held: boolean
    // The "saved, but the latest data could not be loaded" notice, or null.
    notice: ReactNode
}

// The recovery half of a confirmed write whose follow-up read did not complete (`useAuthoringMutation`
// reports it as `confirmed`). The change is saved, so the only action is a read: `read` runs again and
// never the write. When a read completes, the write is announced as done (`message`) and the notice
// goes away. `pageStale` is the page's own signal that its latest read failed and it is showing older
// data: while it is set the page offers the read itself, so the notice is quiet and without a button,
// and the first read that then succeeds recovers this write too.
export function useConfirmedRefresh({
    status,
    reset,
    what,
    message,
    read,
    pageStale = false,
    quietRecovery = false,
}: {
    status: AuthoringMutationStatus
    reset: () => void
    // What could not be read, in the page's words ("party list").
    what: string
    // What was saved, as announced once it shows ("Party archived"), or null for a plain "Saved.".
    message: string | null
    // Reads everything the write changed, and nothing else. It never sends the write.
    read: () => Promise<RefreshOutcome>
    pageStale?: boolean
    // For a row the recovered list may no longer contain (an archived party): the page announces the
    // write when its own read recovers, because this component is gone by then.
    quietRecovery?: boolean
}): ConfirmedRefresh {
    const announce = useAnnounce()
    const [retrying, setRetrying] = useState(false)
    // The page's read failed after this write (`sawStale`), and a later read worked (`recovered`).
    // Recovery is final for this write: a failure of some later, unrelated read does not bring the
    // notice back.
    const [sawStale, setSawStale] = useState(false)
    const [recovered, setRecovered] = useState(false)
    const mounted = useRef(true)
    const latest = useRef({ announce, message })
    useEffect(() => {
        mounted.current = true
        latest.current = { announce, message }
        return () => {
            mounted.current = false
        }
    })

    const confirmed = status.kind === "confirmed"
    // Adjusted while rendering (as `useKept` does), so a recovery is never a render behind.
    if (!confirmed) {
        if (sawStale) setSawStale(false)
        if (recovered) setRecovered(false)
    } else if (pageStale) {
        if (!sawStale) setSawStale(true)
    } else if (sawStale && !recovered) {
        setRecovered(true)
    }
    const active = confirmed && !recovered

    useEffect(() => {
        if (recovered && !quietRecovery && latest.current.message !== null) {
            latest.current.announce(latest.current.message)
        }
    }, [recovered, quietRecovery])

    async function load() {
        setRetrying(true)
        let outcome: RefreshOutcome
        try {
            outcome = await read()
        } catch {
            outcome = "failed"
        }
        if (!mounted.current) return
        setRetrying(false)
        if (outcome === "ok") {
            reset()
            if (message !== null && !quietRecovery) announce(message)
        }
    }

    return {
        held: active,
        notice: active ? (
            <SavedRefreshFailedNotice
                what={what}
                done={message === null ? "Saved." : /[.!?]$/.test(message) ? message : `${message}.`}
                quiet={pageStale}
                onRetry={pageStale ? undefined : () => void load()}
                retrying={retrying}
            />
        ) : null,
    }
}

// For a page whose rows or forms are replaced when the record is read again (a row that leaves the
// list, a form re-keyed to the new version): the component that saved is gone by the time the read
// succeeds, so the page announces the write once its own read is `fresh` (applied, and no newer read
// in flight). `token` changes with every read result, so a read that was superseded is announced when
// the newer one answers. Returns the function a component calls with what it saved but could not read
// back, and optionally what to do once it is announced (show a "go to the log" link, say); nothing
// is announced for a write whose read-back worked (the component announced it).
export function useAnnounceWhenRead(fresh: boolean, token: unknown): (message: string, then?: () => void) => void {
    const announce = useAnnounce()
    const waiting = useRef<{ message: string; then?: () => void } | null>(null)
    // Asking to announce re-runs the check, so a read that was applied just before the ask is not missed.
    const [asked, setAsked] = useState(0)
    useEffect(() => {
        const next = waiting.current
        if (fresh && next !== null) {
            waiting.current = null
            announce(next.message)
            next.then?.()
        }
    }, [fresh, token, asked, announce])
    return useCallback((message: string, then?: () => void) => {
        waiting.current = { message, then }
        setAsked((n) => n + 1)
    }, [])
}
