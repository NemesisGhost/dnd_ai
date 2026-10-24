import type { RefreshOutcome } from "../hooks/useAuthoringMutation"

// What re-reading the session bootstrap did, for a write whose result the bootstrap carries (a
// campaign name, its lifecycle). `refresh` resolves true when the fresh bootstrap was applied, false
// when the session ended (the sign-in boundary takes over, so there is nothing to explain), and
// rejects when the request failed, leaving the previous bootstrap in place.
export async function bootstrapRefreshOutcome(refresh: () => Promise<boolean>): Promise<RefreshOutcome> {
    try {
        return (await refresh()) ? "ok" : "superseded"
    } catch {
        return "failed"
    }
}
