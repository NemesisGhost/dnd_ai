import { useCallback, useEffect, useRef } from "react"
import { useSession } from "../context/SessionContext"

// What a refresh of the authoritative eligibility (the session bootstrap) did.
//   refreshed   the fresh bootstrap was applied; whatever it says about `authorized_parties` is now
//               what the page derives its party selection from.
//   failed      the read failed. Nothing is known about the party, so it is never treated as revoked.
//   signed_out  the session is gone; the session provider already leaves the signed-in UI.
export type EligibilityOutcome = "refreshed" | "failed" | "signed_out"

// Re-reads the bootstrap through the existing session mechanism (no second store, no remount, and
// concurrent calls share one request), after a *confirmed* write that can change who may take a
// party perspective: a clock advance or correction, a membership added or ended, a party archived or
// restored. It never repeats the write and never throws: a failed refresh leaves the previous
// bootstrap, and an external change is still found by the party-scoped not-found recovery below.
export function useEligibilityRefresh(): () => Promise<EligibilityOutcome> {
    const { refresh } = useSession()
    return useCallback(async () => {
        try {
            const applied = await refresh()
            return applied === false ? "signed_out" : "refreshed"
        } catch {
            return "failed"
        }
    }, [refresh])
}

// One refresh per request episode. A party-scoped read that gets the standard non-disclosing 404
// asks here with a key naming the whole episode (campaign, character, party, record or view, and the
// request version). The first ask for a key refreshes; later asks for the same key (a re-run of the
// effect) share that answer, so an episode can never refresh twice or loop. A different party, a
// different record or view, or the person's own "Try again" is a different episode.
export function usePartyNotFoundEpisodes(): (episodeKey: string) => Promise<EligibilityOutcome> {
    const refresh = useEligibilityRefresh()
    const refreshRef = useRef(refresh)
    useEffect(() => {
        refreshRef.current = refresh
    }, [refresh])
    const episodes = useRef(new Map<string, Promise<EligibilityOutcome>>())
    return useCallback((episodeKey: string) => {
        let outcome = episodes.current.get(episodeKey)
        if (outcome === undefined) {
            outcome = refreshRef.current()
            // Bounded: old episodes are never consulted again.
            if (episodes.current.size >= 32) episodes.current.clear()
            episodes.current.set(episodeKey, outcome)
        }
        return outcome
    }, [])
}
